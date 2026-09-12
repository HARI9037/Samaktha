import json

import pytest
from pydantic import SecretStr

from app.config.runtime_config import PROVIDER_CREDENTIAL_IDS, SMTP_PASSWORD_CREDENTIAL_ID
from app.setup.controller import SetupController
from app.setup.field_state import capture_fields
from app.setup.validators import SetupValidator
from tests.setup.test_windows_setup import _service


def configured(tmp_path):
    service, paths, store, credentials = _service(tmp_path)
    draft = service.new_draft().model_copy(update={
        "provider_api_key": SecretStr("R3-fake-provider-secret"), "provider_verified": True,
        "brave_api_key": SecretStr("R3-fake-brave-secret"), "search_provider": "brave", "search_verified": True,
        "smtp_enabled": True, "smtp_host": "smtp.example.invalid", "smtp_port": 587,
        "smtp_sender": "sender@example.invalid", "smtp_username": "sender@example.invalid",
        "smtp_password": SecretStr("R3-fake-smtp-secret"), "smtp_auth_verified": True,
    })
    assert service.commit(draft).ready
    return service, paths, store, credentials


def test_reopen_blank_fields_preserve_verified_configuration_and_hide_secrets(tmp_path, caplog):
    service, paths, store, _ = configured(tmp_path)
    controller = SetupController(service)
    initial = controller.initial_values()
    assert initial["provider_credential_state"] == "unchanged_existing_secret"
    assert initial["smtp_credential_state"] == "unchanged_existing_secret"
    values = capture_fields(initial, {"provider_api_key": "", "brave_api_key": "", "smtp_password": ""})
    assert controller.finish(values).ready
    saved = store.load()
    assert saved["providers"]["groq"]["verified"]
    assert saved["search"]["verified"]
    assert saved["email"]["auth_verified"]
    serialized = json.dumps(initial) + paths.settings_file.read_text() + caplog.text
    for value in ("R3-fake-provider-secret", "R3-fake-brave-secret", "R3-fake-smtp-secret"):
        assert value not in serialized
    assert not any(k in initial for k in ("provider_api_key", "brave_api_key", "smtp_password"))
    validator = SetupValidator(paths=paths, settings_store=store, credential_store=service.credential_store)
    assert validator.ai_provider().status.value == "pass"
    assert validator.search().status.value == "pass"
    assert validator.smtp().status.value == "experimental"
    assert str(paths.workspace_root) in validator.workspace().detail


@pytest.mark.parametrize("change,verification", [
    ({"provider_model": "different-model"}, "provider_verified"),
    ({"provider_endpoint": "http://localhost:9999"}, "provider_verified"),
    ({"provider_api_key": "replacement-secret"}, "provider_verified"),
    ({"remove_provider_credential": True}, "provider_verified"),
    ({"searxng_url": "http://localhost:9999"}, "search_verified"),
    ({"brave_api_key": "replacement-secret"}, "search_verified"),
    ({"remove_brave_credential": True}, "search_verified"),
    ({"smtp_port": 465}, "smtp_auth_verified"),
    ({"smtp_password": "replacement-secret"}, "smtp_auth_verified"),
    ({"remove_smtp_credential": True}, "smtp_auth_verified"),
])
def test_only_dependent_verification_invalidated(tmp_path, change, verification):
    service, *_ = configured(tmp_path)
    controller = SetupController(service)
    values = {**controller.initial_values(), **change}
    draft = controller.build_draft(values)
    for field in ("provider_verified", "search_verified", "smtp_auth_verified"):
        assert getattr(draft, field) is (field != verification)


@pytest.mark.parametrize("kind,identifier", [
    ("provider", PROVIDER_CREDENTIAL_IDS["groq"]),
    ("brave", PROVIDER_CREDENTIAL_IDS["brave"]),
    ("smtp", SMTP_PASSWORD_CREDENTIAL_ID),
])
def test_explicit_removal_is_committed_without_secret_reentry(tmp_path, kind, identifier):
    service, _, store, credentials = configured(tmp_path)
    controller = SetupController(service)
    values = {**controller.initial_values(), f"remove_{kind}_credential": True}
    assert controller.finish(values).completed
    assert not credentials.exists(identifier)
    saved = store.load()
    if kind == "provider":
        assert saved["providers"]["primary"] == "later"
        assert not saved["providers"]["groq"]["verified"]
    elif kind == "brave":
        assert not saved["search"]["verified"]
    else:
        assert not saved["email"]["auth_verified"]


async def test_saved_provider_test_reuses_hidden_credential(tmp_path, monkeypatch):
    service, *_ = configured(tmp_path)
    observed = []
    async def execute(self, payload):
        assert self._settings.groq_api_key == "R3-fake-provider-secret"
        observed.append(self)
        return {"success": True, "content": "OK"}
    monkeypatch.setattr("app.providers.groq_provider.GroqProvider.execute", execute)
    result = await service.test_provider_connection(service.new_draft())
    assert result.status.value == "pass"
    assert observed
