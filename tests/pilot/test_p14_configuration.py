from __future__ import annotations

from app.diagnostics import DiagnosticStatus, SystemDiagnostics


def test_doctor_covers_pilot_operational_health(pilot_orchestrator) -> None:
    report = SystemDiagnostics(
        settings=pilot_orchestrator.provider_settings,
        orchestrator=pilot_orchestrator,
        application_settings=pilot_orchestrator.pilot_test_settings,
    ).run()
    by_label = {check.label: check for check in report.checks}

    for label in (
        "Workspace",
        "Permit Signing",
        "SQLite",
        "Evidence Store",
        "Checkpoint Store",
        "Plugin Manager",
        "Discovered",
        "Loaded",
    ):
        assert label in by_label

    assert by_label["Permit Signing"].status == DiagnosticStatus.OK
    assert by_label["SQLite"].status == DiagnosticStatus.OK
    assert by_label["Evidence Store"].status == DiagnosticStatus.OK
    assert by_label["Checkpoint Store"].status == DiagnosticStatus.OK
    assert by_label["Plugin Manager"].status == DiagnosticStatus.OK


def test_doctor_never_includes_secret_values_in_rendered_output(
    pilot_orchestrator,
) -> None:
    from app.diagnostics import render_report

    sentinel = "P14-SENTINEL-SECRET-DO-NOT-LEAK"
    pilot_orchestrator.provider_settings.groq_api_key = sentinel
    report = SystemDiagnostics(
        settings=pilot_orchestrator.provider_settings,
        orchestrator=pilot_orchestrator,
        application_settings=pilot_orchestrator.pilot_test_settings,
    ).run()

    rendered = render_report(report)
    assert sentinel not in rendered
    assert "API Key ... OK" in rendered
