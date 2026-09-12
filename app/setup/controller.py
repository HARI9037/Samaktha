"""UI-neutral setup controller."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import SecretStr, ValidationError

from app.setup.models import SetupDraft, SetupOutcome, ValidationResult
from app.setup.service import SetupService


class SetupController:
    def __init__(self, service: SetupService) -> None:
        self.service = service
        self._values = service.new_draft().model_dump(mode="python")

    def initial_values(self) -> dict[str, Any]:
        return dict(self._values)

    def build_draft(self, values: dict[str, Any]) -> SetupDraft:
        from app.setup.field_state import capture_fields
        sanitized = capture_fields(self._values, values)
        self._values = dict(sanitized)
        for field in ("provider_api_key", "brave_api_key", "smtp_password"):
            value = sanitized.get(field)
            if isinstance(value, str):
                sanitized[field] = SecretStr(value) if value else None
        return SetupDraft.model_validate(sanitized)

    def validate(self, values: dict[str, Any]) -> list[ValidationResult]:
        try:
            draft = self.build_draft(values)
        except ValidationError as exc:
            raise ValueError("Setup contains invalid fields.") from exc
        return self.service.validate_draft(draft)

    def finish(self, values: dict[str, Any]) -> SetupOutcome:
        return self.service.commit(self.build_draft(values))

    def test_provider(self, values: dict[str, Any]) -> ValidationResult:
        return asyncio.run(self.service.test_provider_connection(self.build_draft(values)))

    def test_search(self, values: dict[str, Any]) -> ValidationResult:
        return asyncio.run(self.service.test_search_connection(self.build_draft(values)))

    def test_smtp_authentication(self, values: dict[str, Any]) -> ValidationResult:
        return asyncio.run(self.service.test_smtp_authentication(self.build_draft(values)))

    def send_smtp_test_email(self, recipient: str, *, confirmed: bool) -> ValidationResult:
        return asyncio.run(
            self.service.send_smtp_test_email(recipient, confirmed=confirmed)
        )
