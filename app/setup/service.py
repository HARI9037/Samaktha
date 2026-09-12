"""Transactional first-run setup application service."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app import __version__
from app.config.credentials import CredentialStore, production_credential_store
from app.config.runtime_config import PROVIDER_CREDENTIAL_IDS, SMTP_PASSWORD_CREDENTIAL_ID
from app.config.settings import get_settings
from app.config.store import CURRENT_SETUP_VERSION, SettingsStore
from app.paths import ApplicationPaths, get_application_paths
from app.setup.capabilities import SetupCapabilityRegistry, readiness
from app.setup.models import SetupDraft, SetupOutcome, ValidationResult, ValidationStatus
from app.setup.validators import SetupValidator


class SetupError(RuntimeError):
    """Raised when setup cannot safely reach a committed ready state."""


SecurityInitializer = Callable[[], None]
_EMAIL_ADDRESS = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class SetupService:
    def __init__(
        self, *, paths: ApplicationPaths | None = None,
        settings_store: SettingsStore | None = None,
        credential_store: CredentialStore | None = None,
        capability_registry: SetupCapabilityRegistry | None = None,
        security_initializer: SecurityInitializer | None = None,
        orchestrator_factory: Callable[[], object] | None = None,
    ) -> None:
        self.paths = paths or get_application_paths()
        self.settings_store = settings_store or SettingsStore(paths=self.paths)
        self.credential_store = credential_store or production_credential_store()
        self.capability_registry = capability_registry or SetupCapabilityRegistry(paths=self.paths)
        self.security_initializer = security_initializer or self._initialize_security
        self.orchestrator_factory = orchestrator_factory or self._production_orchestrator

    def is_setup_complete(self) -> bool:
        return self.settings_store.is_setup_complete()

    def new_draft(self) -> SetupDraft:
        document = self.settings_store.load()
        providers = document["providers"]
        primary = providers.get("primary", "groq")
        selected = providers.get(primary, {}) if primary in providers else {}
        search = document["search"]
        email = document["email"]
        return SetupDraft(
            display_name=document["user"].get("display_name", ""),
            workspace_path=document["workspace"].get("default_path", str(self.paths.workspace_root)),
            memory_enabled=document["memory"].get("enabled", True),
            session_history_enabled=document["memory"].get("session_history", True),
            primary_provider=primary,
            provider_model=selected.get("model", ""),
            provider_endpoint=selected.get("endpoint", ""),
            provider_verified=selected.get("verified", False),
            provider_credential_state=self._credential_state(selected.get("credential_id")),
            search_enabled=search.get("enabled", True),
            search_provider=search.get("provider", "ddgs"),
            searxng_url=search.get("searxng_url", ""),
            search_verified=search.get("verified", False),
            brave_credential_state=self._credential_state(search.get("brave_credential_id")),
            shell_enabled=document["shell"].get("enabled", False),
            smtp_enabled=email.get("smtp_enabled", False),
            smtp_preset=email.get("smtp_preset", "custom"),
            smtp_sender=email.get("sender", ""),
            smtp_host=email.get("host", ""),
            smtp_port=int(email.get("port", 587)),
            smtp_security=email.get("security", "starttls"),
            smtp_username=email.get("username", ""),
            smtp_auth_verified=email.get("auth_verified", False),
            smtp_credential_state=self._credential_state(email.get("password_credential_id")),
            notifications_enabled=document["experimental"].get("notifications", False),
            ocr_enabled=document["experimental"].get("ocr", False),
            voice_enabled=document["experimental"].get("voice", False),
            developer_plugins_enabled=document["advanced"].get("plugins_enabled", False),
            offline_without_provider=primary == "later",
        )

    def validate_draft(self, draft: SetupDraft) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        workspace = Path(draft.workspace_path).expanduser()
        root_like = workspace.parent == workspace
        parent = workspace if workspace.exists() else workspace.parent
        workspace_ok = not root_like and parent.exists() and os.access(parent, os.W_OK)
        results.append(ValidationResult(validator_id="draft.workspace", label="Workspace", status=ValidationStatus.PASS if workspace_ok else ValidationStatus.FAIL, detail="valid user workspace" if workspace_ok else "workspace must be a writable non-root path", critical=True))

        if draft.primary_provider == "later" or draft.offline_without_provider or draft.remove_provider_credential:
            provider_ok = True
        elif draft.primary_provider == "local":
            provider_ok = bool(draft.provider_endpoint and draft.provider_model)
        else:
            provider_ok = bool(self._draft_secret(draft, "provider"))
        results.append(ValidationResult(validator_id="draft.provider", label="AI Provider", status=ValidationStatus.PASS if provider_ok else ValidationStatus.FAIL, detail="selection is complete" if provider_ok else "credential or local endpoint/model required", critical=True))

        search_ok = not draft.search_enabled or draft.search_provider == "ddgs" or (draft.search_provider == "searxng" and bool(draft.searxng_url)) or (draft.search_provider == "brave" and bool(self._draft_secret(draft, "brave")))
        results.append(ValidationResult(validator_id="draft.search", label="Internet Search", status=ValidationStatus.PASS if search_ok else ValidationStatus.FAIL, detail="selection is complete" if search_ok else "selected provider requires configuration"))

        smtp_ok = not draft.smtp_enabled or bool(draft.smtp_sender and draft.smtp_host and 0 < draft.smtp_port < 65536)
        results.append(ValidationResult(validator_id="draft.smtp", label="Experimental SMTP", status=ValidationStatus.EXPERIMENTAL if smtp_ok and draft.smtp_enabled else ValidationStatus.DISABLED if not draft.smtp_enabled else ValidationStatus.FAIL, detail="experimental configuration accepted" if smtp_ok and draft.smtp_enabled else "disabled" if not draft.smtp_enabled else "sender, host and port required"))
        return results

    def system_validations(self) -> list[ValidationResult]:
        """Return the shared, read-only preflight rows used by the wizard."""
        validator = SetupValidator(
            paths=self.paths,
            settings_store=self.settings_store,
            credential_store=self.credential_store,
        )
        return validator.system_checks()

    def commit(self, draft: SetupDraft) -> SetupOutcome:
        draft_results = self.validate_draft(draft)
        if any(result.critical and result.status == ValidationStatus.FAIL for result in draft_results):
            return SetupOutcome(completed=False, ready=False, validations=draft_results)

        old_settings = self.settings_store.path.read_bytes() if self.settings_store.path.exists() else None
        credential_changes: list[tuple[str, str | None]] = []
        try:
            document = self._document_for(draft, completed=False)
            self._write_credentials(draft, document, credential_changes)
            self.settings_store.save(document)
            get_settings.cache_clear()
            self.paths.ensure_directories()
            Path(draft.workspace_path).mkdir(parents=True, exist_ok=True)
            self.security_initializer()
            validator = SetupValidator(paths=self.paths, settings_store=self.settings_store, credential_store=self.credential_store)
            validations = validator.run()
            ready = validator.minimum_ready(validations)
            if not ready:
                raise SetupError("Setup validation did not reach the minimum ready state.")

            completed_at = datetime.now(timezone.utc).isoformat()
            document["installation"].update({"setup_completed": True, "setup_version": CURRENT_SETUP_VERSION, "installed_version": __version__})
            document["setup"].update({"completed": True, "completed_at": completed_at, "setup_version": CURRENT_SETUP_VERSION})
            self.settings_store.save(document)
            capabilities = self._capabilities(document)
            self.capability_registry.replace(capabilities)
            self.capability_registry.save()
            get_settings.cache_clear()
            return SetupOutcome(completed=True, ready=True, validations=validations, capabilities=capabilities)
        except Exception as exc:
            self._rollback_settings(old_settings)
            self._rollback_credentials(credential_changes)
            get_settings.cache_clear()
            if isinstance(exc, SetupError):
                raise
            raise SetupError("Samaktha setup failed; configuration was not marked complete.") from exc

    async def test_provider_connection(self, draft: SetupDraft) -> ValidationResult:
        """Perform an explicit, bounded low-output provider test."""
        if draft.primary_provider in {"later"} or draft.offline_without_provider:
            return ValidationResult(validator_id="provider.connection", label="AI Provider Connection", status=ValidationStatus.DISABLED, detail="configure later selected")
        from app.providers.config import ProviderSettings
        from app.providers.groq_provider import GroqProvider
        from app.providers.openai_provider import OpenAIProvider
        from app.providers.openrouter_provider import OpenRouterProvider
        from app.providers.local_provider import LocalProvider
        provider_id = draft.primary_provider
        key = self._draft_secret(draft, "provider")
        values = ProviderSettings(_env_file=None).model_dump()
        values.update({"default_provider": provider_id, "max_output_tokens": 1, "request_timeout_seconds": 10.0})
        if provider_id == "local":
            values.update({"local_base_url": draft.provider_endpoint, "local_model": draft.provider_model})
        else:
            values[f"{provider_id}_api_key"] = key
            if draft.provider_model:
                values[f"{provider_id}_model"] = draft.provider_model
        settings = ProviderSettings(**values)
        provider = {"groq": GroqProvider, "openai": OpenAIProvider, "openrouter": OpenRouterProvider, "local": LocalProvider}[provider_id](settings)
        try:
            result = await asyncio.wait_for(provider.execute({"messages": [{"role": "user", "content": "Reply OK."}], "max_tokens": 1}), timeout=12.0)
        except Exception:
            return ValidationResult(validator_id="provider.connection", label="AI Provider Connection", status=ValidationStatus.FAIL, detail=f"{provider_id} connection failed")
        return ValidationResult(validator_id="provider.connection", label="AI Provider Connection", status=ValidationStatus.PASS if result.get("success", True) else ValidationStatus.FAIL, detail=f"{provider_id} responded" if result.get("success", True) else f"{provider_id} rejected the test")

    async def test_search_connection(self, draft: SetupDraft) -> ValidationResult:
        """Run one explicit bounded search probe; setup never calls this implicitly."""
        if not draft.search_enabled:
            return ValidationResult(
                validator_id="search.connection", label="Internet Search",
                status=ValidationStatus.DISABLED, detail="disabled by user",
            )
        from app.internet import BraveSearchProvider, DDGSSearchProvider, SearXNGSearchProvider

        if draft.search_provider == "ddgs":
            provider = DDGSSearchProvider(timeout=10.0, backend="duckduckgo")
        elif draft.search_provider == "searxng":
            provider = SearXNGSearchProvider(
                base_url=draft.searxng_url, timeout=10.0, max_retries=0,
            )
        else:
            key = self._draft_secret(draft, "brave")
            provider = BraveSearchProvider(api_key=key, timeout=10.0, max_retries=0)
        try:
            response = await asyncio.wait_for(
                provider.search("Samaktha setup connectivity check", max_results=1),
                timeout=12.0,
            )
        except Exception:
            return ValidationResult(
                validator_id="search.connection", label="Internet Search",
                status=ValidationStatus.FAIL,
                detail=f"{draft.search_provider} connection failed",
            )
        return ValidationResult(
            validator_id="search.connection", label="Internet Search",
            status=ValidationStatus.PASS,
            detail=f"{draft.search_provider} responded with {len(response.results)} result(s)",
        )

    async def test_smtp_authentication(self, draft: SetupDraft) -> ValidationResult:
        from app.integrations.email_smtp import SMTPIntegrationProvider
        password = self._draft_secret(draft, "smtp") or ""
        provider = SMTPIntegrationProvider({"host": draft.smtp_host, "port": draft.smtp_port, "username": draft.smtp_username, "password": password, "from_address": draft.smtp_sender, "use_tls": draft.smtp_security == "starttls", "use_ssl": draft.smtp_security == "ssl"})
        health = await provider.authentication_diagnostics()
        passed = bool(health["connection"] and health["tls"] and health["authentication"])
        return ValidationResult(
            validator_id="smtp.authentication", label="SMTP Authentication",
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            detail="TLS/authentication succeeded; no email sent" if passed else "SMTP authentication failed",
            metadata={
                "connection": bool(health["connection"]),
                "tls": bool(health["tls"]),
                "authentication": bool(health["authentication"]),
                "failure_stage": str(health.get("failure_stage", "")),
            },
        )

    async def send_smtp_test_email(
        self, recipient: str, *, confirmed: bool,
    ) -> ValidationResult:
        """Send one explicitly confirmed test through canonical CAP/Runtime."""
        if not confirmed:
            return ValidationResult(
                validator_id="smtp.test_send", label="SMTP Test Send",
                status=ValidationStatus.DISABLED, detail="cancelled; no email sent",
            )
        recipient = recipient.strip()
        if not _EMAIL_ADDRESS.fullmatch(recipient):
            return ValidationResult(
                validator_id="smtp.test_send", label="SMTP Test Send",
                status=ValidationStatus.FAIL, detail="a valid recipient address is required",
            )
        document = self.settings_store.load()
        email = document.get("email", {})
        if not self.settings_store.is_setup_complete() or not (
            email.get("smtp_enabled") and email.get("auth_verified")
        ):
            return ValidationResult(
                validator_id="smtp.test_send", label="SMTP Test Send",
                status=ValidationStatus.FAIL,
                detail="complete setup and verify SMTP authentication first",
            )

        from app.core.contracts.memory import DEFAULT_LOCAL_PRINCIPAL_ID
        from app.core.contracts.state import ExecutionStatus

        orchestrator = self.orchestrator_factory()
        coordinator = orchestrator.execution_coordinator
        request = (
            "send an email\n"
            f"recipient: {recipient}\n"
            "subject: Samaktha setup test\n"
            "body:\nThis is an explicitly confirmed Samaktha SMTP test message."
        )
        state = await coordinator.start_execution(
            request,
            principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
            session_id="setup-smtp-test",
            source="setup",
            wait=True,
        )
        if state.status != ExecutionStatus.AWAITING_APPROVAL:
            return ValidationResult(
                validator_id="smtp.test_send", label="SMTP Test Send",
                status=ValidationStatus.FAIL,
                detail="canonical governance did not produce the required approval",
            )
        pending = coordinator.pending_approval(
            state.execution_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
        )
        if not pending or not pending.get("approval_id"):
            return ValidationResult(
                validator_id="smtp.test_send", label="SMTP Test Send",
                status=ValidationStatus.FAIL, detail="approval state unavailable",
            )
        final = await coordinator.submit_approval(
            state.execution_id, pending["approval_id"], "allow",
            principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
            reasons=["Explicit confirmation in Samaktha setup"],
            source="setup",
            wait=True,
        )
        runtime_result = coordinator.result(
            state.execution_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
        )
        output = runtime_result.output if runtime_result is not None else {}
        provider_accepted = bool(
            isinstance(output, dict)
            and (
                output.get("status") == "provider_accepted"
                or output.get("submission_status") == "provider_accepted"
            )
        )
        succeeded = (
            final.status == ExecutionStatus.COMPLETED
            and runtime_result is not None
            and not runtime_result.error
            and provider_accepted
        )
        if succeeded:
            document["email"]["send_acceptance_verified"] = True
            self.settings_store.save(document)
            self.capability_registry.replace(self._capabilities(document))
            self.capability_registry.save()
        return ValidationResult(
            validator_id="smtp.test_send", label="SMTP Test Send",
            status=ValidationStatus.PASS if succeeded else ValidationStatus.FAIL,
            detail=(
                "SMTP provider accepted the message for delivery; recipient delivery is not proven"
                if succeeded else "SMTP test send failed"
            ),
            metadata={"execution_id": state.execution_id, "provider_accepted": provider_accepted},
        )

    def _document_for(self, draft: SetupDraft, *, completed: bool) -> dict:
        document = self.settings_store.load()
        document["user"]["display_name"] = draft.display_name.strip()
        document["workspace"]["default_path"] = str(Path(draft.workspace_path).expanduser().resolve(strict=False))
        document["memory"].update({"enabled": draft.memory_enabled, "session_history": draft.session_history_enabled})
        document["local_capabilities"]["memory"] = draft.memory_enabled
        primary = "later" if draft.offline_without_provider or draft.remove_provider_credential else draft.primary_provider
        document["providers"]["primary"] = primary
        for provider_id in ("groq", "openai", "openrouter", "local"):
            document["providers"][provider_id]["enabled"] = provider_id == primary
            if provider_id == primary:
                document["providers"][provider_id]["verified"] = draft.provider_verified
        if primary in {"groq", "openai", "openrouter", "local"}:
            if draft.provider_model:
                document["providers"][primary]["model"] = draft.provider_model
            if primary == "local":
                document["providers"][primary]["endpoint"] = draft.provider_endpoint.strip()
        document["search"].update({"enabled": draft.search_enabled, "verified": draft.search_verified, "provider": draft.search_provider, "backend": "duckduckgo", "searxng_url": draft.searxng_url.strip()})
        document["shell"]["enabled"] = draft.shell_enabled
        old_email = dict(document["email"])
        document["email"].update({"smtp_enabled": draft.smtp_enabled, "smtp_preset": draft.smtp_preset, "sender": draft.smtp_sender.strip(), "host": draft.smtp_host.strip(), "port": draft.smtp_port, "security": draft.smtp_security, "username": draft.smtp_username.strip(), "auth_verified": draft.smtp_auth_verified and not draft.remove_smtp_credential})
        if draft.smtp_password or draft.remove_smtp_credential or any(old_email.get(k) != document["email"].get(k) for k in ("host", "port", "sender", "security", "username", "auth_verified")):
            document["email"]["send_acceptance_verified"] = False
        document["experimental"].update({"notifications": draft.notifications_enabled, "ocr": draft.ocr_enabled, "voice": draft.voice_enabled})
        document["advanced"]["plugins_enabled"] = bool(draft.developer_plugins_enabled)
        document["setup"].update({"completed": completed, "setup_version": CURRENT_SETUP_VERSION})
        document["installation"].update({"setup_completed": completed, "setup_version": CURRENT_SETUP_VERSION})
        return document

    def _write_credentials(self, draft: SetupDraft, document: dict, changes: list[tuple[str, str | None]]) -> None:
        removals = [
            (draft.remove_provider_credential, PROVIDER_CREDENTIAL_IDS.get(draft.primary_provider), document["providers"].get(draft.primary_provider, {}), "credential_id", "verified"),
            (draft.remove_brave_credential, PROVIDER_CREDENTIAL_IDS["brave"], document["search"], "brave_credential_id", "verified"),
            (draft.remove_smtp_credential, SMTP_PASSWORD_CREDENTIAL_ID, document["email"], "password_credential_id", "auth_verified"),
        ]
        for remove, identifier, section, reference, verified in removals:
            if remove and identifier:
                changes.append((identifier, self.credential_store.get(identifier)))
                self.credential_store.delete(identifier)
                section[reference] = ""
                section[verified] = False
        primary = document["providers"]["primary"]
        if primary in PROVIDER_CREDENTIAL_IDS:
            secret = draft.provider_api_key.get_secret_value() if draft.provider_api_key else None
            if not secret and draft.import_environment_credential:
                secret = self._environment_provider_secret(primary)
            if secret:
                identifier = PROVIDER_CREDENTIAL_IDS[primary]
                changes.append((identifier, self.credential_store.get(identifier)))
                self.credential_store.set(identifier, secret)
                document["providers"][primary]["credential_id"] = identifier
        if draft.search_provider == "brave" and draft.brave_api_key and not draft.remove_brave_credential:
            identifier = PROVIDER_CREDENTIAL_IDS["brave"]
            changes.append((identifier, self.credential_store.get(identifier)))
            self.credential_store.set(identifier, draft.brave_api_key.get_secret_value())
            document["search"]["brave_credential_id"] = identifier
        if draft.smtp_enabled and draft.smtp_password and not draft.remove_smtp_credential:
            changes.append((SMTP_PASSWORD_CREDENTIAL_ID, self.credential_store.get(SMTP_PASSWORD_CREDENTIAL_ID)))
            self.credential_store.set(SMTP_PASSWORD_CREDENTIAL_ID, draft.smtp_password.get_secret_value())
            document["email"]["password_credential_id"] = SMTP_PASSWORD_CREDENTIAL_ID

    def _environment_provider_secret(self, provider: str) -> str | None:
        return os.getenv(f"SAMAKTHA_{provider.upper()}_API_KEY")

    def _credential_state(self, reference: str | None) -> str:
        return "unchanged_existing_secret" if reference and self.credential_store.exists(reference) else "no_secret_configured"

    def _draft_secret(self, draft: SetupDraft, kind: str) -> str | None:
        fields = {"provider": ("provider_api_key", "remove_provider_credential", PROVIDER_CREDENTIAL_IDS.get(draft.primary_provider)),
                  "brave": ("brave_api_key", "remove_brave_credential", PROVIDER_CREDENTIAL_IDS["brave"]),
                  "smtp": ("smtp_password", "remove_smtp_credential", SMTP_PASSWORD_CREDENTIAL_ID)}
        field, remove, identifier = fields[kind]
        if getattr(draft, remove):
            return None
        secret = getattr(draft, field)
        if secret:
            return secret.get_secret_value()
        if kind == "provider" and draft.import_environment_credential:
            return self._environment_provider_secret(draft.primary_provider)
        return self.credential_store.get(identifier) if identifier else None

    def _initialize_security(self) -> None:
        # Reuse the canonical production composition; it owns signing-key and
        # checkpoint-integrity initialization and Windows intended-user ACLs.
        from app.core.app import create_orchestrator
        create_orchestrator(get_settings())

    @staticmethod
    def _production_orchestrator():
        from app.core.app import create_orchestrator

        return create_orchestrator(get_settings())

    def _rollback_settings(self, old: bytes | None) -> None:
        if old is None:
            self.settings_store.path.unlink(missing_ok=True)
        else:
            self.settings_store.path.write_bytes(old)

    def _rollback_credentials(self, changes: list[tuple[str, str | None]]) -> None:
        for identifier, previous in reversed(changes):
            if previous is None:
                self.credential_store.delete(identifier)
            else:
                self.credential_store.set(identifier, previous)

    def _capabilities(self, document: dict):
        local = document["local_capabilities"]
        provider = document["providers"]["primary"]
        email = document["email"]
        provider_config = document["providers"].get(provider, {})
        provider_configured = provider != "later" and bool(provider_config.get("enabled"))
        if provider == "local":
            provider_configured = provider_configured and bool(
                provider_config.get("endpoint") and provider_config.get("model")
            )
        elif provider != "later":
            provider_configured = provider_configured and bool(
                provider_config.get("credential_id")
            )
        search = document["search"]
        search_provider = search.get("provider")
        search_configured = bool(search.get("enabled")) and (
            (search_provider == "ddgs" and search.get("backend") == "duckduckgo")
            or (search_provider == "searxng" and bool(search.get("searxng_url")))
            or (search_provider == "brave" and bool(search.get("brave_credential_id")))
        )
        smtp_configured = bool(
            email.get("smtp_enabled")
            and email.get("sender")
            and email.get("host")
            and email.get("port")
            and (not email.get("username") or (email.get("password_credential_id") and self.credential_store.exists(email["password_credential_id"])))
        )
        return [
            readiness("ai", configured=provider_configured, verified=provider_configured and bool(provider_config.get("verified")), enabled=provider != "later"),
            readiness("internet_search", configured=search_configured, verified=search_configured and bool(search.get("verified")), enabled=bool(search.get("enabled"))),
            *[readiness(name, enabled=bool(local.get(name, True))) for name in ("filesystem", "memory", "clipboard", "notes", "tasks", "contacts", "calendar")],
            readiness("shell", enabled=document["shell"]["enabled"]),
            readiness("email.send", configured=smtp_configured, verified=smtp_configured and email["auth_verified"], enabled=email["smtp_enabled"], experimental=True, reason="SMTP sending requires manual acceptance validation."),
            readiness("notifications", implemented=False, configured=False, verified=False, enabled=False),
            readiness("ocr", configured=document["experimental"]["ocr"], verified=False, enabled=document["experimental"]["ocr"], experimental=True),
            readiness("voice", configured=document["experimental"]["voice"], verified=False, enabled=document["experimental"]["voice"], experimental=True),
            readiness("plugins", configured=False, verified=False, enabled=False, experimental=True, reason="Developer feature only."),
        ]
