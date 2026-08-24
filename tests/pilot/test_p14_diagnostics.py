from __future__ import annotations

import json
from pathlib import Path

from app.diagnostics import (
    SystemDiagnostics,
    build_safe_diagnostic_bundle,
    export_safe_diagnostic_bundle,
)


FORBIDDEN_DIAGNOSTIC_KEYS = {
    "prompt",
    "response",
    "messages",
    "memory_contents",
    "file_contents",
    "environment",
    "checkpoint_payload",
    "api_key",
    "password",
    "signing_key",
}


def _report(orchestrator):
    return SystemDiagnostics(
        settings=orchestrator.provider_settings,
        orchestrator=orchestrator,
        application_settings=orchestrator.pilot_test_settings,
    ).run()


def test_safe_diagnostics_exclude_user_content_secrets_and_raw_paths(
    pilot_orchestrator, monkeypatch
) -> None:
    sentinel = "P14-SENTINEL-ULTRA-SECRET"
    pilot_orchestrator.provider_settings.groq_api_key = sentinel
    monkeypatch.setenv("P14_PRIVATE_ENV_VALUE", sentinel)

    payload = build_safe_diagnostic_bundle(
        _report(pilot_orchestrator), orchestrator=pilot_orchestrator
    )
    serialized = json.dumps(payload, sort_keys=True)

    assert sentinel not in serialized
    assert str(Path.home()) not in serialized
    assert payload["privacy"] == {
        "contains_prompts": False,
        "contains_responses": False,
        "contains_memory_contents": False,
        "contains_file_contents": False,
        "contains_environment": False,
        "contains_checkpoint_payloads": False,
        "contains_credentials": False,
        "contains_signing_material": False,
        "uploaded": False,
    }
    assert not (FORBIDDEN_DIAGNOSTIC_KEYS & set(payload))
    assert all("detail" not in check for check in payload["health"]["checks"])


def test_diagnostic_export_is_explicit_local_and_atomic(
    pilot_orchestrator, tmp_path: Path
) -> None:
    output_dir = tmp_path / "pilot diagnostics"

    exported = export_safe_diagnostic_bundle(
        _report(pilot_orchestrator),
        orchestrator=pilot_orchestrator,
        output_dir=output_dir,
    )

    assert exported.parent == output_dir
    assert exported.name.startswith("samaktha-diagnostics-")
    assert exported.suffix == ".json"
    assert not list(output_dir.glob("*.tmp"))
    payload = json.loads(exported.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["privacy"]["uploaded"] is False
    assert payload["plugins"]["loaded"] == 0


def test_diagnostic_failure_details_are_not_exported(pilot_orchestrator) -> None:
    sentinel_error = "provider failed with password=P14-DO-NOT-EXPORT"
    status = pilot_orchestrator.provider_manager.get_provider_status("groq")
    status.last_error = sentinel_error
    status.available = False

    payload = build_safe_diagnostic_bundle(
        _report(pilot_orchestrator), orchestrator=pilot_orchestrator
    )

    assert sentinel_error not in json.dumps(payload)
    groq = next(row for row in payload["providers"] if row["provider"] == "groq")
    assert groq["available"] is False
