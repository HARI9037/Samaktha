"""P2.9 — CLI architecture tests.

Covers the ``samaktha`` console command:
- Default and legacy invocation paths (tui / backend / --tui / --backend).
- Subcommands: tui, backend, doctor, version, personality.
- Exit codes and stdout/stderr contracts.
- Doctor health exit code semantics and runtime-attach fallback.
- Personality management (P2.8) through the CLI with a temp state path.
"""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.cli
from app import __version__


def _patch_runtime(monkeypatch, runtime=None, exc=None):
    if exc is not None:
        def _build():
            raise exc
    elif runtime is not None:
        def _build():
            return runtime
    else:
        def _build():
            return SimpleNamespace(_base=SimpleNamespace(provider_settings=None))
    monkeypatch.setattr(app.cli, "_build_runtime", _build)


def _patch_diagnostics(monkeypatch, critical=False):
    report = SimpleNamespace(is_critical=lambda: critical)
    monkeypatch.setattr(
        "app.diagnostics.SystemDiagnostics",
        lambda settings, orchestrator: SimpleNamespace(run=lambda: report),
    )
    monkeypatch.setattr(
        "app.diagnostics.render_report", lambda report: "Fake Report"
    )


class TestCliDispatch:
    def test_default_command_launches_tui(self, monkeypatch):
        mock_tui = MagicMock()
        monkeypatch.setattr(app.cli, "_run_tui", mock_tui)
        assert app.cli.main([]) == 0
        mock_tui.assert_called_once()

    def test_tui_subcommand_launches_tui(self, monkeypatch):
        mock_tui = MagicMock()
        monkeypatch.setattr(app.cli, "_run_tui", mock_tui)
        assert app.cli.main(["tui"]) == 0
        mock_tui.assert_called_once()

    def test_legacy_tui_flag_launches_tui(self, monkeypatch):
        mock_tui = MagicMock()
        monkeypatch.setattr(app.cli, "_run_tui", mock_tui)
        assert app.cli.main(["--tui"]) == 0
        mock_tui.assert_called_once()

    def test_legacy_backend_flag(self, monkeypatch):
        mock_backend = MagicMock()
        monkeypatch.setattr(app.cli, "_run_backend", mock_backend)
        assert app.cli.main(["--backend"]) == 0
        mock_backend.assert_called_once_with(host=None, port=None)

    def test_backend_subcommand_defaults(self, monkeypatch):
        mock_backend = MagicMock()
        monkeypatch.setattr(app.cli, "_run_backend", mock_backend)
        assert app.cli.main(["backend"]) == 0
        mock_backend.assert_called_once_with(host=None, port=None)

    def test_backend_subcommand_host_port(self, monkeypatch):
        mock_backend = MagicMock()
        monkeypatch.setattr(app.cli, "_run_backend", mock_backend)
        assert app.cli.main(["backend", "--host", "0.0.0.0", "--port", "9000"]) == 0
        mock_backend.assert_called_once_with(host="0.0.0.0", port=9000)

    def test_parser_exposes_commands(self):
        import argparse

        parser = app.cli.build_parser()
        subparsers = next(
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        for command in ("tui", "backend", "doctor", "version", "personality"):
            assert command in subparsers.choices

    def test_personality_requires_subcommand(self):
        with pytest.raises(SystemExit) as excinfo:
            app.cli.main(["personality"])
        assert excinfo.value.code == 2


class TestCliBackend:
    def test_backend_launches_uvicorn_with_settings(self, monkeypatch):
        fake_uvicorn = types.ModuleType("uvicorn")
        fake_uvicorn.run = MagicMock()
        monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
        settings_fake = SimpleNamespace(host="127.0.0.1", port=8123)
        app_fake = object()
        monkeypatch.setattr("app.config.settings.get_settings", lambda: settings_fake)
        monkeypatch.setattr("app.core.app.create_app", lambda settings: app_fake)
        monkeypatch.setattr("app.core.logging.configure_logging", lambda settings: None)

        app.cli._run_backend()

        fake_uvicorn.run.assert_called_once_with(
            app_fake, host="127.0.0.1", port=8123, log_level="info"
        )

    def test_backend_overrides_host_port(self, monkeypatch):
        fake_uvicorn = types.ModuleType("uvicorn")
        fake_uvicorn.run = MagicMock()
        monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
        settings_fake = SimpleNamespace(host="127.0.0.1", port=8123)
        app_fake = object()
        monkeypatch.setattr("app.config.settings.get_settings", lambda: settings_fake)
        monkeypatch.setattr("app.core.app.create_app", lambda settings: app_fake)
        monkeypatch.setattr("app.core.logging.configure_logging", lambda settings: None)

        app.cli._run_backend(host="0.0.0.0", port=9000)

        fake_uvicorn.run.assert_called_once_with(
            app_fake, host="0.0.0.0", port=9000, log_level="info"
        )


class TestCliVersion:
    def test_version_command_prints_version(self, capsys):
        assert app.cli.main(["version"]) == 0
        assert capsys.readouterr().out.strip() == __version__

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            app.cli.main(["--version"])
        assert excinfo.value.code == 0
        assert __version__ in capsys.readouterr().out


class TestCliDoctor:
    def test_doctor_healthy_returns_zero(self, monkeypatch, capsys):
        _patch_runtime(monkeypatch)
        _patch_diagnostics(monkeypatch, critical=False)
        assert app.cli.main(["doctor"]) == 0
        assert "Fake Report" in capsys.readouterr().out

    def test_doctor_critical_returns_one(self, monkeypatch, capsys):
        _patch_runtime(monkeypatch)
        _patch_diagnostics(monkeypatch, critical=True)
        assert app.cli.main(["doctor"]) == 1

    def test_doctor_falls_back_when_runtime_unavailable(self, monkeypatch, capsys):
        _patch_runtime(monkeypatch, exc=RuntimeError("boom"))
        _patch_diagnostics(monkeypatch, critical=False)
        assert app.cli.main(["doctor"]) == 0
        captured = capsys.readouterr()
        assert "warning: runtime diagnostics unavailable" in captured.err


class TestCliPersonality:
    def _settings(self, tmp_path, monkeypatch):
        from app.config.settings import Settings

        monkeypatch.setattr(
            "app.config.settings.get_settings",
            lambda: Settings(personality_state_path=str(tmp_path / "state.json")),
        )

    def test_personality_show_default(self, tmp_path, monkeypatch, capsys):
        self._settings(tmp_path, monkeypatch)
        assert app.cli.main(["personality", "show"]) == 0
        out = capsys.readouterr().out
        assert "samaktha-core" in out
        assert "Active personality:" in out

    def test_personality_list_marks_active(self, tmp_path, monkeypatch, capsys):
        self._settings(tmp_path, monkeypatch)
        assert app.cli.main(["personality", "list"]) == 0
        out = capsys.readouterr().out
        assert "* samaktha-core" in out

    def test_personality_set_persists(self, tmp_path, monkeypatch, capsys):
        self._settings(tmp_path, monkeypatch)
        assert app.cli.main(["personality", "set", "samaktha-core"]) == 0
        assert "samaktha-core" in capsys.readouterr().out
        payload = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert payload["profile_id"] == "samaktha-core"

    def test_personality_set_unknown_returns_one(self, tmp_path, monkeypatch, capsys):
        self._settings(tmp_path, monkeypatch)
        assert app.cli.main(["personality", "set", "does-not-exist"]) == 1
        assert "error:" in capsys.readouterr().err
