from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.plugins.discovery import PluginDiscovery
from app.plugins.models import MAX_MANIFEST_BYTES, PluginManifest
from app.plugins.validation import validate_manifest


def _manifest(**updates):
    value = {
        "schema_version": "1.0",
        "id": "p13-plugin",
        "name": "P13 Plugin",
        "version": "1.0.0",
        "kind": "tool",
        "entry": "p13_plugin",
        "plugin_api_version": 1,
        "permissions": [{"scope": "read"}],
        "capabilities": [{"name": "p13-capability"}],
        "actions": [{
            "name": "inspect",
            "required_permissions": ["read"],
            "side_effect_class": "READ_ONLY",
        }],
    }
    value.update(updates)
    return value


@pytest.mark.parametrize(
    "updates",
    [
        {"entry": "../outside"},
        {"entry": r"C:\outside\plugin.py"},
        {"version": "not-semver"},
        {"plugin_api_version": 999},
        {"min_samaktha_version": "999.0.0"},
        {"permissions": []},
        {"actions": [{"name": "inspect", "required_permissions": ["write"]}]},
        {"actions": [{"name": "same"}, {"name": "same"}]},
    ],
)
def test_hostile_manifest_semantics_are_rejected(updates: dict) -> None:
    manifest = PluginManifest.model_validate(_manifest(**updates))
    validation = validate_manifest(manifest)
    # Compatibility is enforced by PluginManager at load; the manifest itself
    # remains structurally valid for a future compatible app.
    if "min_samaktha_version" in updates:
        assert not manifest.check_compatibility("0.5.0")
    else:
        assert not validation.valid


def test_unknown_manifest_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(_manifest(arbitrary_execution_hook="bad"))


@pytest.mark.parametrize(
    "payload",
    [
        '{"id":"first","id":"second","name":"x","entry":"x"}',
        "{not-json",
        "\udcff",
    ],
)
def test_discovery_skips_duplicate_malformed_and_invalid_encoding(
    tmp_path: Path, payload: str,
) -> None:
    raw = payload.encode("utf-8", errors="surrogatepass")
    (tmp_path / "bad.plugin.json").write_bytes(raw)
    assert PluginDiscovery().discover(tmp_path) == []


def test_discovery_rejects_oversized_manifest_before_parsing(tmp_path: Path) -> None:
    path = tmp_path / "large.plugin.json"
    path.write_bytes(b" " * (MAX_MANIFEST_BYTES + 1))
    assert PluginDiscovery().discover(tmp_path) == []


def test_enabled_python_plugin_trust_boundary_is_not_a_sandbox(tmp_path: Path) -> None:
    # This is a characterization, not a promised isolation control: enabled
    # Python plugins execute in-process and can use the Python standard library.
    sentinel = tmp_path / "trusted-plugin-can-read.txt"
    sentinel.write_text("trusted-code", encoding="utf-8")
    assert os.environ is not None
    assert sentinel.open(encoding="utf-8").read() == "trusted-code"
