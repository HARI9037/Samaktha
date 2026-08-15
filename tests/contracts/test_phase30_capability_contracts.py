"""P2.3 — Versioned Capability Contracts regression tests.

Covers the capability contract models, structural compatibility validation,
breaking-change detection, semantic-versioning discipline, contract builders
for tools/providers/skills/personalities, the versioned contract registry,
migration planning and integration with real plugin contributions.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.capabilities import (
    CapabilityContract,
    ContractError,
    ContractParameter,
    ContractRegistry,
    MigrationPlan,
    breaking_changes,
    compatible_range,
    compare_contracts,
    contract_for_personality,
    contract_for_provider,
    contract_for_skill,
    contract_for_tool,
    is_compatible,
    is_consumer_compatible,
    is_semver_compatible,
    plan_migration,
    recommended_bump,
    upgrade_path,
    version_respects_bump,
)
from app.plugins.models import PluginKind
from app.plugins.sdk.testing import PluginHarness
from app.tools.models import ToolInfo

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "plugins"


def _tool(kind="tool", name="pdf", version="1.0.0", **overrides):
    base = {
        "kind": PluginKind(kind),
        "name": name,
        "version": version,
        "capabilities": ["pdf_read"],
        "actions": ["extract_text"],
        "permissions": ["read"],
        "parameters": [ContractParameter(name="path", required=True)],
        "output_keys": ["pages", "text"],
    }
    base.update(overrides)
    return CapabilityContract(**base)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


def test_contract_defaults_and_key():
    contract = CapabilityContract(kind=PluginKind.TOOL, name="pdf")
    assert contract.version == "1.0.0"
    assert contract.key == "tool:pdf"
    assert contract.semver.major == 1
    assert contract.parameter_names == frozenset()
    assert contract.required_parameter_names == frozenset()


def test_contract_parameter_helpers():
    contract = _tool(
        parameters=[
            ContractParameter(name="path", required=True),
            ContractParameter(name="password", required=False),
        ]
    )
    assert contract.parameter_names == frozenset({"path", "password"})
    assert contract.required_parameter_names == frozenset({"path"})


def test_contract_rejects_invalid_semver():
    with pytest.raises(ValueError):
        _tool(version="not-a-version").semver


def test_kinds_span_all_contribution_types():
    for kind in PluginKind:
        contract = CapabilityContract(kind=kind, name="demo")
        assert contract.key == f"{kind.value}:demo"


# --------------------------------------------------------------------------- #
# Compatibility validation
# --------------------------------------------------------------------------- #


def test_additive_change_is_compatible():
    old = _tool()
    new = _tool(version="1.1.0", capabilities=["pdf_read", "pdf_ocr"])
    comparison = compare_contracts(old, new)
    assert comparison.compatible is True
    assert comparison.breaking_changes == []


def test_removed_capability_is_breaking():
    old = _tool(version="1.0.0", capabilities=["pdf_read", "pdf_ocr"])
    new = _tool(version="2.0.0", capabilities=["pdf_read"])
    assert is_compatible(old, new) is False
    details = [c.detail for c in breaking_changes(old, new)]
    assert "Capability removed: pdf_ocr" in details


def test_removed_action_is_breaking():
    old = _tool(actions=["extract_text", "ocr"])
    new = _tool(version="2.0.0", actions=["extract_text"])
    assert is_compatible(old, new) is False
    assert any("Action removed: ocr" in c.detail for c in breaking_changes(old, new))


def test_removed_permission_is_breaking():
    old = _tool(permissions=["read", "admin"])
    new = _tool(version="2.0.0", permissions=["read"])
    assert is_compatible(old, new) is False
    assert any("Permission removed: admin" in c.detail for c in breaking_changes(old, new))


def test_removed_parameter_is_breaking():
    old = _tool(
        parameters=[
            ContractParameter(name="path", required=True),
            ContractParameter(name="password", required=False),
        ]
    )
    new = _tool(version="1.1.0", parameters=[ContractParameter(name="path", required=True)])
    assert is_compatible(old, new) is False
    assert any("Parameter removed: password" in c.detail for c in breaking_changes(old, new))


def test_added_required_parameter_is_breaking():
    old = _tool()
    new = _tool(
        version="1.1.0",
        parameters=[
            ContractParameter(name="path", required=True),
            ContractParameter(name="page", required=True),
        ],
    )
    assert is_compatible(old, new) is False
    assert any("Required parameter added: page" in c.detail for c in breaking_changes(old, new))


def test_added_optional_parameter_is_compatible():
    old = _tool()
    new = _tool(
        version="1.1.0",
        parameters=[
            ContractParameter(name="path", required=True),
            ContractParameter(name="page", required=False),
        ],
    )
    assert is_compatible(old, new) is True


def test_removed_output_key_is_breaking():
    old = _tool(output_keys=["pages", "text"])
    new = _tool(version="2.0.0", output_keys=["pages"])
    assert is_compatible(old, new) is False
    assert any("Output key removed: text" in c.detail for c in breaking_changes(old, new))


def test_identical_surface_same_version_is_compatible():
    old = _tool()
    new = _tool()
    assert is_compatible(old, new) is True
    assert recommended_bump(old, new) == "none"


def test_same_version_but_surface_differs_is_breaking():
    old = _tool(version="1.0.0", capabilities=["pdf_read", "pdf_ocr"])
    new = _tool(version="1.0.0", capabilities=["pdf_read"])
    comparison = compare_contracts(old, new)
    assert comparison.compatible is False
    assert any(
        "Version unchanged" in c.detail and c.breaking
        for c in comparison.changes
    )


def test_downgrade_is_breaking():
    old = _tool(version="2.0.0")
    new = _tool(version="1.0.0")
    assert is_compatible(old, new) is False
    assert any("Downgrade" in c.detail for c in breaking_changes(old, new))


def test_compare_unrelated_contracts_raises():
    old = _tool(name="pdf")
    new = _tool(name="image")
    with pytest.raises(ContractError, match="unrelated"):
        compare_contracts(old, new)


def test_compare_across_kinds_raises():
    old = _tool(name="pdf")
    new = CapabilityContract(kind=PluginKind.PROVIDER, name="pdf", version="1.0.0")
    with pytest.raises(ContractError, match="unrelated"):
        compare_contracts(old, new)


# --------------------------------------------------------------------------- #
# Versioning strategy
# --------------------------------------------------------------------------- #


def test_compatible_range_uses_caret():
    assert compatible_range("1.2.3") == "^1.2.3"


def test_recommended_bump_levels():
    assert recommended_bump(_tool(), _tool()) == "none"
    assert recommended_bump(_tool(), _tool(version="1.0.1")) == "patch"
    assert (
        recommended_bump(
            _tool(), _tool(version="1.1.0", capabilities=["pdf_read", "pdf_ocr"])
        )
        == "minor"
    )
    assert (
        recommended_bump(
            _tool(capabilities=["pdf_read", "pdf_ocr"]),
            _tool(version="2.0.0", capabilities=["pdf_read"]),
        )
        == "major"
    )


def test_version_respects_bump_discipline():
    ok, _ = version_respects_bump(
        _tool(), _tool(version="2.0.0", capabilities=["pdf_read"])
    )
    assert ok is True

    ok, reason = version_respects_bump(
        _tool(capabilities=["pdf_read", "pdf_ocr"]),
        _tool(version="1.1.0", capabilities=["pdf_read"]),
    )
    assert ok is False
    assert "major" in reason

    ok, _ = version_respects_bump(_tool(), _tool(version="1.1.0", capabilities=["pdf_read", "pdf_ocr"]))
    assert ok is True

    ok, reason = version_respects_bump(
        _tool(), _tool(version="1.0.1", capabilities=["pdf_read", "pdf_ocr"])
    )
    assert ok is False
    assert "minor" in reason


def test_semver_compatibility_ignores_surface():
    old = _tool(version="1.0.0")
    new = _tool(version="1.5.0")
    assert is_semver_compatible(old, new) is True
    assert is_semver_compatible(new, old) is False
    assert is_semver_compatible(old, _tool(version="2.0.0")) is False


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def test_contract_for_tool_from_tool_info():
    info = ToolInfo(
        tool_id="pdf",
        description="Extract text from PDFs.",
        capabilities=["pdf_read", "metadata"],
        version="1.0.0",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}, "pages": {"type": "integer"}},
            "required": ["path"],
        },
        metadata={"source": "system"},
    )
    contract = contract_for_tool(info)
    assert contract.kind == PluginKind.TOOL
    assert contract.name == "pdf"
    assert contract.version == "1.0.0"
    assert set(contract.capabilities) == {"pdf_read", "metadata"}
    assert contract.parameters == [
        ContractParameter(name="path", required=True),
        ContractParameter(name="pages", required=False),
    ]


def test_contract_for_tool_defaults_version():
    info = ToolInfo(tool_id="shell", description="", capabilities=["shell_exec"])
    contract = contract_for_tool(info)
    assert contract.version == "1.0.0"
    assert contract.actions == []


def test_contract_for_provider():
    contract = contract_for_provider(
        "email",
        version="2.0.0",
        description="Email communication.",
        capabilities=["communication_send", "communication_read"],
        actions=["send", "reply"],
        permissions=["network"],
    )
    assert contract.kind == PluginKind.PROVIDER
    assert contract.name == "email"
    assert contract.version == "2.0.0"
    assert contract.permissions == ["network"]


def test_contract_for_skill():
    contract = contract_for_skill(
        "summarize",
        version="1.1.0",
        capabilities=["summarize", "extract"],
        parameters=[ContractParameter(name="text", required=True)],
        output_keys=["summary"],
    )
    assert contract.kind == PluginKind.SKILL
    assert contract.output_keys == ["summary"]
    assert contract.required_parameter_names == frozenset({"text"})


def test_contract_for_personality():
    contract = contract_for_personality(
        "concise",
        version="1.0.0",
        capabilities=["tone_control"],
        parameters=[ContractParameter(name="verbosity", required=False)],
    )
    assert contract.kind == PluginKind.PERSONALITY
    assert contract.name == "concise"
    assert contract.parameters[0].required is False


def test_builder_sorts_and_dedupes_surface():
    contract = contract_for_provider(
        "p", capabilities=["b", "a", "b"], actions=["y", "x"], permissions=["read", "read"]
    )
    assert contract.capabilities == ["a", "b"]
    assert contract.actions == ["x", "y"]
    assert contract.permissions == ["read"]


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


def test_registry_version_history_and_lookup():
    registry = ContractRegistry(
        [_tool(version="1.0.0"), _tool(version="1.1.0"), _tool(version="1.2.0")]
    )
    assert registry.versions(PluginKind.TOOL, "pdf") == ["1.0.0", "1.1.0", "1.2.0"]
    assert registry.latest(PluginKind.TOOL, "pdf").version == "1.2.0"
    assert registry.get(PluginKind.TOOL, "pdf", "1.1.0").version == "1.1.0"
    assert registry.get(PluginKind.TOOL, "pdf", "9.9.9") is None
    assert registry.get(PluginKind.TOOL, "missing") is None


def test_registry_keys_are_kind_scoped():
    registry = ContractRegistry()
    registry.register(_tool(name="pdf", version="1.0.0"))
    registry.register(CapabilityContract(kind=PluginKind.PROVIDER, name="pdf", version="1.0.0"))
    assert registry.has(PluginKind.TOOL, "pdf")
    assert registry.has(PluginKind.PROVIDER, "pdf")
    assert len(registry.all()) == 2


def test_registry_rejects_duplicate_version():
    registry = ContractRegistry([_tool(version="1.0.0")])
    with pytest.raises(ContractError, match="already registered"):
        registry.register(_tool(version="1.0.0"))


def test_registry_lookup_accepts_string_kinds():
    registry = ContractRegistry([_tool(version="1.0.0")])
    assert registry.latest("tool", "pdf") is not None
    assert registry.versions("tool", "pdf") == ["1.0.0"]


def test_registry_is_compatible_with_latest():
    registry = ContractRegistry(
        [_tool(version="1.0.0", capabilities=["pdf_read", "pdf_ocr"])]
    )

    compatible = _tool(version="1.1.0", capabilities=["pdf_read", "pdf_ocr", "pdf_export"])
    comparison = registry.is_compatible_with_latest(compatible)
    assert comparison is not None
    assert comparison.compatible is True

    breaking = _tool(version="2.0.0", capabilities=["pdf_read"])
    comparison = registry.is_compatible_with_latest(breaking)
    assert comparison.compatible is False
    assert comparison.breaking_changes != []

    assert registry.is_compatible_with_latest(_tool(version="1.0.0")) is None


# --------------------------------------------------------------------------- #
# Migration strategy
# --------------------------------------------------------------------------- #


def test_plan_migration_compatible_upgrade():
    old = _tool(version="1.0.0")
    new = _tool(version="1.1.0", capabilities=["pdf_read", "pdf_ocr"])
    plan = plan_migration(old, new)
    assert isinstance(plan, MigrationPlan)
    assert plan.kind == PluginKind.TOOL
    assert plan.from_version == "1.0.0"
    assert plan.to_version == "1.1.0"
    assert plan.compatible is True
    assert plan.requires_consumer_update is False
    assert any(c.detail == "Capability added: pdf_ocr" for c in plan.changes)


def test_plan_migration_breaking_upgrade():
    old = _tool(version="1.0.0", capabilities=["pdf_read", "pdf_ocr"])
    new = _tool(version="2.0.0", capabilities=["pdf_read"])
    plan = plan_migration(old, new)
    assert plan.compatible is False
    assert plan.requires_consumer_update is True
    assert any("Capability removed: pdf_ocr" in c.detail for c in plan.changes)


def test_upgrade_path_through_registry():
    registry = ContractRegistry(
        [
            _tool(version="1.0.0", capabilities=["pdf_read"]),
            _tool(version="1.1.0", capabilities=["pdf_read", "pdf_ocr"]),
        ]
    )

    plan = upgrade_path(
        registry, PluginKind.TOOL, "pdf", to_version="1.1.0", from_version="1.0.0"
    )
    assert plan is not None
    assert plan.from_version == "1.0.0"
    assert plan.to_version == "1.1.0"
    assert plan.compatible is True
    assert any("Capability added: pdf_ocr" in c.detail for c in plan.changes)

    assert upgrade_path(registry, PluginKind.TOOL, "pdf") is None

    downgrade = upgrade_path(registry, PluginKind.TOOL, "pdf", to_version="1.0.0")
    assert downgrade is not None
    assert downgrade.compatible is False
    assert downgrade.requires_consumer_update is True

    assert upgrade_path(registry, PluginKind.TOOL, "missing") is None
    assert upgrade_path(registry, PluginKind.TOOL, "pdf", to_version="9.9.9") is None


def test_is_consumer_compatible_uses_constraints():
    contract = _tool(version="1.4.0")
    assert is_consumer_compatible("*", contract) is True
    assert is_consumer_compatible("^1.0.0", contract) is True
    assert is_consumer_compatible(">=1.2.0", contract) is True
    assert is_consumer_compatible("1.4.0", contract) is True
    assert is_consumer_compatible("^2.0.0", contract) is False
    assert is_consumer_compatible("~1.3.0", contract) is False


# --------------------------------------------------------------------------- #
# Integration with plugin contributions
# --------------------------------------------------------------------------- #


def test_contract_from_loaded_plugin_tool():
    harness = PluginHarness(plugin_dir=EXAMPLES / "wordbox")
    try:
        asyncio.run(harness.load("wordbox@1.0.0"))
        info = harness.tool_registry.info_for("wordbox")
        contract = contract_for_tool(info)
        assert contract.kind == PluginKind.TOOL
        assert contract.name == "wordbox"
        assert contract.version == "1.0.0"
        assert "wordbox" in contract.capabilities
        assert "read" in contract.permissions
        assert contract.metadata.get("source") == "plugin"
    finally:
        harness.cleanup()


def test_contract_from_loaded_plugin_provider():
    harness = PluginHarness(plugin_dir=EXAMPLES / "health_probe")
    try:
        asyncio.run(harness.load("health_probe@1.0.0"))
        provider = harness.communication_registry.get_provider("health_probe")
        contract = contract_for_provider(
            provider.provider_id,
            description="deterministic smoke-test provider",
            capabilities=["communication_send", "communication_read"],
            actions=["send", "receive"],
        )
        assert contract.key == "provider:health_probe"
        assert contract.actions == ["receive", "send"]
    finally:
        harness.cleanup()


def test_contract_roundtrip_against_latest_plugin_version():
    old = _tool(version="1.0.0", name="wordbox", capabilities=["wordbox"])
    new = _tool(
        version="1.1.0",
        name="wordbox",
        capabilities=["wordbox", "wordbox_count"],
    )
    registry = ContractRegistry([old])
    comparison = registry.is_compatible_with_latest(new)
    assert comparison is not None
    assert comparison.compatible is True
