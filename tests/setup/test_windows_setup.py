from __future__ import annotations

import os
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.config.credentials import InMemoryCredentialStore
from app.config.runtime_config import (
    PROVIDER_CREDENTIAL_IDS,
    SMTP_PASSWORD_CREDENTIAL_ID,
    resolve_provider_settings,
    resolve_smtp_credentials,
)
from app.config.settings import get_settings
from app.config.store import CURRENT_SETUP_VERSION, SettingsStore, SettingsStoreError
from app.core.contracts.planning import GoalIntent
from app.core.gambit.goal_parser import GoalParser
from app.paths import ApplicationPaths
from app.setup.capabilities import SetupCapabilityRegistry, readiness
from app.setup.first_run import FirstRunCoordinator
from app.setup.models import SetupCapabilityState, SetupDraft, ValidationStatus
from app.setup.service import SetupError, SetupService
from app.setup.validators import SetupValidator
from app.setup.wizard import PAGE_IDS


def _paths(root: Path, *, installed: bool = True) -> ApplicationPaths:
    return ApplicationPaths(
        install_root=root / "install",
        config_root=root / "config",
        data_root=root / "data",
        cache_root=root / "cache",
        log_root=root / "logs",
        workspace_root=root / "workspace",
        checkpoint_root=root / "data" / "checkpoints",
        evidence_db=root / "data" / "evidence.db",
        memory_db=root / "data" / "memory.db",
        plugin_root=root / "plugins",
        personality_state=root / "config" / "personality.json",
        is_installed=installed,
        is_development=not installed,
    )


def _service(tmp_path: Path, *, initializer=None):
    paths = _paths(tmp_path / "state")
    paths.ensure_directories()
    credentials = InMemoryCredentialStore()
    store = SettingsStore(paths=paths)

    def safe_initializer() -> None:
        paths.config_root.mkdir(parents=True, exist_ok=True)
        (paths.config_root / "permit_signing.key").write_bytes(b"k" * 32)

    return SetupService(
        paths=paths,
        settings_store=store,
        credential_store=credentials,
        capability_registry=SetupCapabilityRegistry(paths=paths),
        security_initializer=initializer or safe_initializer,
    ), paths, store, credentials


def test_application_paths_installed_layout_is_per_user(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setattr("app.paths.ApplicationPaths._is_installed_mode", lambda: True)
    paths = ApplicationPaths.resolve()
    assert paths.install_root == tmp_path / "LocalAppData" / "Programs" / "Samaktha"
    assert paths.settings_file == tmp_path / "LocalAppData" / "Samaktha" / "config" / "settings.toml"
    assert paths.backup_root == tmp_path / "LocalAppData" / "Samaktha" / "backups"


def test_settings_store_round_trip_is_atomic_and_contains_no_secrets(tmp_path: Path) -> None:
    service, paths, store, _ = _service(tmp_path)
    document = store.load()
    document["setup"]["completed"] = True
    document["installation"]["setup_completed"] = True
    document["providers"]["groq"]["credential_id"] = PROVIDER_CREDENTIAL_IDS["groq"]
    store.save(document)
    text = paths.settings_file.read_text(encoding="utf-8")
    assert PROVIDER_CREDENTIAL_IDS["groq"] in text
    assert "secret-value" not in text
    assert not list(paths.config_root.glob(".settings.toml.tmp-*"))
    assert store.is_setup_complete()
    assert store.load()["setup"]["setup_version"] == CURRENT_SETUP_VERSION


def test_settings_store_rejects_plaintext_secret_fields(tmp_path: Path) -> None:
    _, _, store, _ = _service(tmp_path)
    document = store.load()
    document["providers"]["groq"]["api_key"] = "must-not-persist"
    with pytest.raises(SettingsStoreError):
        store.save(document)


def test_provider_settings_precedence_environment_over_persistent(monkeypatch, tmp_path: Path) -> None:
    _, _, store, credentials = _service(tmp_path)
    document = store.load()
    document["providers"]["primary"] = "groq"
    document["providers"]["groq"].update(enabled=True, credential_id=PROVIDER_CREDENTIAL_IDS["groq"])
    store.save(document)
    credentials.set(PROVIDER_CREDENTIAL_IDS["groq"], "stored-key")
    # ProviderSettings intentionally supports a development .env. Move away
    # from the developer checkout so this test proves only the stated layers.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SAMAKTHA_DEFAULT_PROVIDER", "openai")
    monkeypatch.setenv("SAMAKTHA_OPENAI_API_KEY", "environment-key")
    resolved = resolve_provider_settings(settings_store=store, credential_store=credentials)
    assert resolved.default_provider == "openai"
    assert resolved.openai_api_key == "environment-key"
    assert resolved.groq_api_key == "stored-key"


def test_persistent_workspace_and_disabled_search_flow_into_settings(monkeypatch, tmp_path: Path) -> None:
    _, paths, store, _ = _service(tmp_path)
    workspace = tmp_path / "bounded-workspace"
    document = store.load()
    document["workspace"]["default_path"] = str(workspace)
    document["search"].update(enabled=False, provider="ddgs", backend="duckduckgo")
    store.save(document)
    monkeypatch.setattr("app.config.store.SettingsStore", lambda: store)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.filesystem_allowed_roots == [str(workspace)]
        assert settings.search_provider == "ddgs"
        assert settings.internet_search_enabled is False
    finally:
        get_settings.cache_clear()


def test_setup_commit_marks_complete_only_after_security_and_validation(tmp_path: Path) -> None:
    service, paths, store, _ = _service(tmp_path)
    draft = service.new_draft().model_copy(update={
        "workspace_path": str(paths.workspace_root),
        "primary_provider": "later",
        "offline_without_provider": True,
        "search_enabled": False,
    })
    outcome = service.commit(draft)
    assert outcome.completed and outcome.ready
    assert store.is_setup_complete()
    assert (paths.config_root / "permit_signing.key").read_bytes() == b"k" * 32
    assert SetupCapabilityRegistry(paths=paths).load()


def test_setup_failure_rolls_back_config_and_credentials(tmp_path: Path) -> None:
    def fail() -> None:
        raise RuntimeError("initialization failed")

    service, paths, store, credentials = _service(tmp_path, initializer=fail)
    draft = service.new_draft().model_copy(update={
        "workspace_path": str(paths.workspace_root),
        "primary_provider": "groq",
        "provider_api_key": SecretStr("transaction-secret"),
        "provider_verified": True,
        "search_enabled": False,
    })
    with pytest.raises(SetupError):
        service.commit(draft)
    assert not store.exists()
    assert not credentials.exists(PROVIDER_CREDENTIAL_IDS["groq"])


def test_explicit_environment_secret_import_uses_secure_store(monkeypatch, tmp_path: Path) -> None:
    service, paths, store, credentials = _service(tmp_path)
    monkeypatch.setenv("SAMAKTHA_GROQ_API_KEY", "temporary-import-secret")
    draft = service.new_draft().model_copy(update={
        "workspace_path": str(paths.workspace_root),
        "primary_provider": "groq", "provider_verified": True,
        "import_environment_credential": True, "search_enabled": False,
    })
    assert service.commit(draft).completed
    assert credentials.get(PROVIDER_CREDENTIAL_IDS["groq"]) == "temporary-import-secret"
    persisted = paths.settings_file.read_text(encoding="utf-8")
    assert "temporary-import-secret" not in persisted
    assert PROVIDER_CREDENTIAL_IDS["groq"] in persisted


def test_setup_version_mismatch_reopens_setup(tmp_path: Path) -> None:
    _, _, store, _ = _service(tmp_path)
    document = store.load()
    document["setup"].update(completed=True, setup_version=CURRENT_SETUP_VERSION + 1)
    document["installation"].update(setup_completed=True)
    store.save(document)
    assert not store.is_setup_complete()


def test_first_run_detection_and_resume_use_same_isolated_paths(monkeypatch, tmp_path: Path) -> None:
    _, paths, store, _ = _service(tmp_path)
    coordinator = FirstRunCoordinator(paths=paths, settings_store=store)
    assert coordinator.setup_required()
    captured = {}
    monkeypatch.setattr("app.setup.wizard.launch_setup_wizard", lambda service: captured.setdefault("service", service) is not None)
    assert coordinator.launch_setup()
    assert captured["service"].paths == paths


def test_development_mode_never_forces_first_run(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "source", installed=False)
    assert not FirstRunCoordinator(paths=paths).setup_required()


def test_capability_readiness_states_are_setup_only(tmp_path: Path) -> None:
    _, paths, _, _ = _service(tmp_path)
    registry = SetupCapabilityRegistry(paths=paths)
    entries = [
        readiness("local", enabled=True),
        readiness("configured", configured=True, verified=False, enabled=True),
        readiness("disabled", enabled=False),
        readiness("smtp", configured=True, verified=True, enabled=True, experimental=True),
    ]
    registry.replace(entries)
    registry.save()
    states = {item.capability_id: item.state for item in SetupCapabilityRegistry(paths=paths).load()}
    assert states == {
        "configured": SetupCapabilityState.CONFIGURED,
        "disabled": SetupCapabilityState.DISABLED,
        "local": SetupCapabilityState.AVAILABLE,
        "smtp": SetupCapabilityState.EXPERIMENTAL,
    }
    import app.core.app as core_app
    assert "SetupCapabilityRegistry" not in inspect.getsource(core_app.create_orchestrator)


@pytest.mark.asyncio
async def test_provider_connection_is_explicit_bounded_and_sanitized(monkeypatch, tmp_path: Path) -> None:
    service, paths, _, _ = _service(tmp_path)

    async def execute(self, payload):
        assert payload["max_tokens"] == 1
        return {"success": True}

    monkeypatch.setattr("app.providers.groq_provider.GroqProvider.execute", execute)
    draft = service.new_draft().model_copy(update={
        "workspace_path": str(paths.workspace_root),
        "provider_api_key": SecretStr("never-log-this"),
    })
    result = await service.test_provider_connection(draft)
    assert result.status == ValidationStatus.PASS
    assert "never-log-this" not in result.detail


@pytest.mark.asyncio
async def test_search_connection_is_explicit_and_keeps_duckduckgo(monkeypatch, tmp_path: Path) -> None:
    from app.internet.models import SearchResponse

    service, paths, _, _ = _service(tmp_path)

    async def search(self, query, *, max_results=5, timeout=None):
        assert self._backend == "duckduckgo"
        assert max_results == 1
        return SearchResponse(query=query, category="web", results=[], total=0, source="ddgs")

    monkeypatch.setattr("app.internet.ddgs.DDGSSearchProvider.search", search)
    draft = service.new_draft().model_copy(update={"workspace_path": str(paths.workspace_root)})
    result = await service.test_search_connection(draft)
    assert result.status == ValidationStatus.PASS


@pytest.mark.asyncio
async def test_smtp_authentication_uses_secret_without_sending(monkeypatch, tmp_path: Path) -> None:
    service, paths, _, _ = _service(tmp_path)
    calls = {"auth": 0, "execute": 0}

    async def auth(self):
        calls["auth"] += 1
        assert self._config["password"] == "smtp-secret"
        return {
            "connection": True, "tls": True, "authentication": True,
            "failure_stage": "",
        }

    async def execute(self, request):
        calls["execute"] += 1

    monkeypatch.setattr("app.integrations.email_smtp.SMTPIntegrationProvider.authentication_diagnostics", auth)
    monkeypatch.setattr("app.integrations.email_smtp.SMTPIntegrationProvider.execute", execute)
    draft = service.new_draft().model_copy(update={
        "workspace_path": str(paths.workspace_root), "smtp_enabled": True,
        "smtp_sender": "sender@example.com", "smtp_host": "smtp.example.com",
        "smtp_username": "sender@example.com", "smtp_password": SecretStr("smtp-secret"),
    })
    result = await service.test_smtp_authentication(draft)
    assert result.status == ValidationStatus.PASS
    assert calls == {"auth": 1, "execute": 0}
    assert "smtp-secret" not in result.detail
    assert result.metadata == {
        "connection": True, "tls": True, "authentication": True,
        "failure_stage": "",
    }


@pytest.mark.asyncio
async def test_smtp_authentication_failure_is_sanitized(monkeypatch, tmp_path: Path) -> None:
    service, paths, _, _ = _service(tmp_path)

    async def failed(self):
        return {
            "connection": True, "tls": True, "authentication": False,
            "failure_stage": "authentication",
        }

    monkeypatch.setattr(
        "app.integrations.email_smtp.SMTPIntegrationProvider.authentication_diagnostics",
        failed,
    )
    draft = service.new_draft().model_copy(update={
        "workspace_path": str(paths.workspace_root), "smtp_enabled": True,
        "smtp_sender": "sender@example.com", "smtp_host": "smtp.example.com",
        "smtp_password": SecretStr("do-not-disclose"),
    })
    result = await service.test_smtp_authentication(draft)
    assert result.status == ValidationStatus.FAIL
    assert result.metadata["failure_stage"] == "authentication"
    assert "do-not-disclose" not in result.model_dump_json()


def test_smtp_secret_resolves_from_secure_reference_not_toml(tmp_path: Path) -> None:
    _, paths, store, credentials = _service(tmp_path)
    document = store.load()
    document["email"].update({
        "smtp_enabled": True, "sender": "sender@example.com",
        "host": "smtp.example.com", "password_credential_id": SMTP_PASSWORD_CREDENTIAL_ID,
    })
    store.save(document)
    credentials.set(SMTP_PASSWORD_CREDENTIAL_ID, "smtp-secret")
    resolved = resolve_smtp_credentials(settings_store=store, credential_store=credentials)
    assert resolved["password"] == "smtp-secret"
    assert "smtp-secret" not in paths.settings_file.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_explicit_smtp_test_send_uses_canonical_coordinator_once(tmp_path: Path) -> None:
    from app.core.contracts.planning import TaskStatus
    from app.core.contracts.runtime import RuntimeResult
    from app.core.contracts.state import ExecutionState, ExecutionStatus

    calls = {"start": 0, "approve": 0}

    class Coordinator:
        async def start_execution(self, request, **kwargs):
            calls["start"] += 1
            assert "recipient: recipient@example.com" in request
            assert kwargs["source"] == "setup"
            return ExecutionState(
                execution_id="smtp-test-execution",
                status=ExecutionStatus.AWAITING_APPROVAL,
                principal_id=kwargs["principal_id"],
                session_id=kwargs["session_id"],
                pending_approval_id="approval-1",
                pending_task_id="email-task",
            )

        def pending_approval(self, execution_id, **kwargs):
            return {"approval_id": "approval-1"}

        async def submit_approval(self, execution_id, approval_id, decision, **kwargs):
            calls["approve"] += 1
            assert decision == "allow"
            assert kwargs["source"] == "setup"
            return ExecutionState(
                execution_id=execution_id,
                status=ExecutionStatus.COMPLETED,
            )

        def result(self, execution_id, **kwargs):
            return RuntimeResult(
                task_id="email-task", status=TaskStatus.COMPLETED,
                output={
                    "status": "provider_accepted",
                    "submission_status": "provider_accepted",
                    "delivery_status": "unknown",
                },
            )

    coordinator = Coordinator()
    service, paths, store, _ = _service(tmp_path)
    service.orchestrator_factory = lambda: SimpleNamespace(
        execution_coordinator=coordinator
    )
    draft = service.new_draft().model_copy(update={
        "workspace_path": str(paths.workspace_root),
        "primary_provider": "later", "offline_without_provider": True,
        "search_enabled": False,
        "smtp_enabled": True, "smtp_auth_verified": True,
        "smtp_sender": "sender@example.com", "smtp_host": "smtp.example.com",
        "smtp_username": "sender@example.com", "smtp_password": SecretStr("secret"),
    })
    assert service.commit(draft).completed
    cancelled = await service.send_smtp_test_email(
        "recipient@example.com", confirmed=False,
    )
    assert cancelled.status == ValidationStatus.DISABLED
    assert calls == {"start": 0, "approve": 0}
    result = await service.send_smtp_test_email(
        "recipient@example.com", confirmed=True,
    )
    assert result.status == ValidationStatus.PASS
    assert result.detail == (
        "SMTP provider accepted the message for delivery; recipient delivery is not proven"
    )
    assert calls == {"start": 1, "approve": 1}
    assert store.load()["email"]["send_acceptance_verified"] is True


def test_setup_and_doctor_share_validator_contract(tmp_path: Path) -> None:
    service, _, _, _ = _service(tmp_path)
    assert isinstance(service.system_validations()[0], type(SetupValidator(
        paths=service.paths, settings_store=service.settings_store,
        credential_store=service.credential_store,
    ).system_checks()[0]))


def test_shared_validator_is_read_only(tmp_path: Path) -> None:
    service, paths, _, _ = _service(tmp_path)
    before = sorted(
        (item.relative_to(paths.data_root.parent), item.stat().st_size)
        for item in paths.data_root.parent.rglob("*") if item.is_file()
    )
    service.system_validations()
    SetupValidator(
        paths=paths, settings_store=service.settings_store,
        credential_store=service.credential_store,
    ).run()
    after = sorted(
        (item.relative_to(paths.data_root.parent), item.stat().st_size)
        for item in paths.data_root.parent.rglob("*") if item.is_file()
    )
    assert after == before


def test_cli_setup_command_delegates_to_first_run_coordinator(monkeypatch) -> None:
    from app import cli

    calls = []
    monkeypatch.setattr(
        "app.setup.first_run.FirstRunCoordinator.launch_setup",
        lambda self: calls.append("setup") or True,
    )
    assert cli._cmd_setup() == 0
    assert calls == ["setup"]


def test_stale_launcher_detection_is_bounded(monkeypatch, tmp_path: Path) -> None:
    service, _, _, _ = _service(tmp_path)
    monkeypatch.setattr(
        "app.setup.validators._all_commands",
        lambda _name: [str(tmp_path / "legacy" / "samaktha.exe")],
    )
    result = SetupValidator(
        paths=service.paths, settings_store=service.settings_store,
        credential_store=service.credential_store,
    ).launcher_resolution()
    assert result.status == ValidationStatus.WARN
    assert result.metadata["competing_count"] == 1
    assert "legacy" not in result.detail


def test_setup_draft_repr_and_dump_never_disclose_secrets(tmp_path: Path) -> None:
    service, paths, _, _ = _service(tmp_path)
    draft = service.new_draft().model_copy(update={
        "workspace_path": str(paths.workspace_root),
        "provider_api_key": SecretStr("provider-secret"),
        "brave_api_key": SecretStr("brave-secret"),
        "smtp_password": SecretStr("smtp-secret"),
    })
    rendered = repr(draft) + str(draft.model_dump(mode="json"))
    assert "provider-secret" not in rendered
    assert "brave-secret" not in rendered
    assert "smtp-secret" not in rendered


def test_wizard_surface_hides_plugins_and_connector_catalog() -> None:
    assert PAGE_IDS == (
        "welcome", "system", "workspace", "provider", "search", "local",
        "shell", "experimental", "validation", "finish",
    )
    assert "plugins" not in PAGE_IDS
    assert "connectors" not in PAGE_IDS


@pytest.mark.asyncio
async def test_email_send_without_smtp_never_becomes_draft() -> None:
    from app.communication.email_tool import EmailTool

    result = await EmailTool().run({
        "action": "send", "recipient": "x@example.com",
        "subject": "Test", "body": "Hello",
    })
    assert result.ok is False
    assert result.data["action"] == "send"
    assert result.data["status"] == "unavailable"
    assert "draft" not in (result.error or "").casefold()


def test_email_send_after_prior_draft_remains_send() -> None:
    parser = GoalParser()
    first = parser.parse("draft an email to x@example.com subject: Old body: Draft")
    second = parser.parse("send an email to x@example.com with subject Test and body Hello")
    assert first.intent == second.intent == GoalIntent.SEND_EMAIL
    assert first.intent_action == "draft"
    assert second.intent_action == "send"


def test_multiline_email_fields_are_preserved() -> None:
    goal = GoalParser().parse(
        "send an email\nrecipient: x@example.com\nsubject: Test\nbody:\n"
        "Hello,\nthis is a multiline body.\nRegards,\nUser"
    )
    assert goal.intent_action == "send"
    assert goal.intent_arguments["recipient"] == "x@example.com"
    assert goal.intent_arguments["subject"] == "Test"
    assert goal.intent_arguments["body"] == "Hello,\nthis is a multiline body.\nRegards,\nUser"
    assert goal.missing_arguments == []
