"""P0.4 — Runtime Path Cleanup regression guards.

Locks in the canonical-runtime cleanup:
- The legacy AgentRuntime module is gone (ProductionAgentRuntime is canonical).
- The empty app/utils/ package is gone.
- The duplicate notification capability registration is removed.
- main.py / app.cli backend mode actually launches a server (uvicorn).
"""
import os
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.cli
import app.tools.capability_registry as cap_reg_module
import main

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


def test_legacy_agent_runtime_removed():
    assert not os.path.exists(os.path.join(ROOT, "app", "agent", "runtime.py"))
    with pytest.raises(ImportError):
        __import__("app.agent.runtime")


def test_app_utils_package_removed():
    assert not os.path.exists(os.path.join(ROOT, "app", "utils"))


def test_capability_registry_has_single_notification_domain():
    registry = cap_reg_module.CapabilityRegistry.default()
    notification = [e for e in registry.entries() if e.domain == "notification"]
    assert len(notification) == 1
    # Conservative standalone registries advertise no implementation. The
    # production registry is derived from create_orchestrator's ToolRegistry.
    assert notification[0].tool_id is None
    assert notification[0].availability.value == "unavailable"


def test_capability_registry_installed_domains_unique():
    registry = cap_reg_module.CapabilityRegistry.default()
    domains = [e.domain for e in registry.entries()]
    assert len(domains) == len(set(domains))


def _assert_backend_launches(module, monkeypatch):
    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = MagicMock()
    sys.modules["uvicorn"] = fake_uvicorn
    try:
        settings_fake = SimpleNamespace(host="127.0.0.1", port=8123)
        app_fake = object()
        monkeypatch.setattr("app.config.settings.get_settings", lambda: settings_fake)
        monkeypatch.setattr("app.core.app.create_app", lambda settings: app_fake)
        monkeypatch.setattr("app.core.logging.configure_logging", lambda settings: None)
        module._run_backend()
        fake_uvicorn.run.assert_called_once_with(
            app_fake,
            host="127.0.0.1",
            port=8123,
            log_level="info",
        )
    finally:
        sys.modules.pop("uvicorn", None)


def test_main_backend_launches_uvicorn(monkeypatch):
    _assert_backend_launches(main, monkeypatch)


def test_cli_backend_launches_uvicorn(monkeypatch):
    _assert_backend_launches(app.cli, monkeypatch)
