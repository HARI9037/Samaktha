from __future__ import annotations

from app.tools.models import CapabilityAvailability


def test_pilot_capability_matrix_is_derived_from_production_composition(
    pilot_orchestrator,
) -> None:
    registry = pilot_orchestrator.product_capability_registry

    expected_modes = {
        "filesystem": CapabilityAvailability.PRODUCTION_READY,
        "memory": CapabilityAvailability.LOCAL_ONLY,
        "windows": CapabilityAvailability.LOCAL_ONLY,
        "internet": CapabilityAvailability.PRODUCTION_READY,
        "shell": CapabilityAvailability.PRODUCTION_READY,
        "clipboard": CapabilityAvailability.LOCAL_ONLY,
        "notification": CapabilityAvailability.LOCAL_ONLY,
        "reminder": CapabilityAvailability.LOCAL_ONLY,
        "note": CapabilityAvailability.LOCAL_ONLY,
        "task": CapabilityAvailability.LOCAL_ONLY,
        "contact": CapabilityAvailability.LOCAL_ONLY,
        "calendar": CapabilityAvailability.LOCAL_ONLY,
        "email": CapabilityAvailability.SIMULATED,
        "message": CapabilityAvailability.SIMULATED,
    }

    assert registry.source_registry is pilot_orchestrator.tool_registry
    assert {
        entry.domain: entry.availability
        for entry in registry.advertised_entries()
    } == expected_modes


def test_pilot_scope_keeps_internal_and_unavailable_capabilities_unadvertised(
    pilot_orchestrator,
) -> None:
    registry = pilot_orchestrator.product_capability_registry

    document = registry.entry_for("document")
    assert document is not None
    assert document.availability == CapabilityAvailability.INTERNAL_ONLY
    assert document.advertised is False

    for domain in ("browser", "media"):
        entry = registry.entry_for(domain)
        assert entry is not None
        assert entry.tool_id is None
        assert entry.availability == CapabilityAvailability.UNAVAILABLE
        assert entry.advertised is False


def test_pilot_plugins_are_discovered_but_never_auto_enabled(
    pilot_orchestrator,
) -> None:
    manager = pilot_orchestrator.plugin_manager

    assert manager._require_explicit_enable is True
    assert all(record.enabled is False for record in manager.list_plugins())
    assert manager.list_loaded() == []
