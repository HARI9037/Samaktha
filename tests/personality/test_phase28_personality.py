"""P2.8 — Personality registry, lifecycle, switching, persistence and
personality → GAMBIT integration tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.orchestrator import SamakthaOrchestrator
from app.personality import (
    DEFAULT_PERSONALITY_ID,
    PersonalityLifecycleManager,
    PersonalityPersistence,
    PersonalityRegistry,
    PersonalityValidationError,
    default_personality_registry,
)
from app.personality.engine import SAMAKTHA_IDENTITY_PROFILE
from app.personality.models import IdentityProfile
from app.personality.registry import PersonalityDefinition


def _profile(name: str = "Tester") -> IdentityProfile:
    return IdentityProfile(
        name=name,
        mission="Test mission",
        description="Test description",
        capabilities=["test"],
        limitations=["none"],
        philosophy="Test philosophy",
    )


def _tester_definition(profile_id: str = "tester") -> PersonalityDefinition:
    return PersonalityDefinition(
        profile_id=profile_id,
        name="Tester",
        description="Test personality",
        profile=_profile(),
    )


# ---------------------------------------------------------------------------
# Personality registry
# ---------------------------------------------------------------------------


class TestPersonalityRegistry:
    def test_default_registry_seeds_samaktha_core(self):
        registry = default_personality_registry()
        assert registry.contains(DEFAULT_PERSONALITY_ID)
        definition = registry.get(DEFAULT_PERSONALITY_ID)
        assert definition is not None
        assert definition.profile.name == "Samaktha"
        assert definition.profile is SAMAKTHA_IDENTITY_PROFILE

    def test_register_get_list_contains(self):
        registry = PersonalityRegistry()
        registry.register(_tester_definition())
        assert registry.contains("tester")
        assert registry.get("tester").name == "Tester"
        assert registry.get("missing") is None
        assert [d.profile_id for d in registry.list()] == ["tester"]

    def test_register_profile_builds_definition(self):
        registry = PersonalityRegistry()
        definition = registry.register_profile("tester", "Tester", "desc", _profile())
        assert definition.profile_id == "tester"
        assert registry.get("tester").description == "desc"

    def test_duplicate_registration_raises(self):
        registry = PersonalityRegistry()
        registry.register(_tester_definition())
        with pytest.raises(PersonalityValidationError):
            registry.register(_tester_definition())

    def test_unregister_is_idempotent(self):
        registry = PersonalityRegistry()
        registry.register(_tester_definition())
        assert registry.unregister("tester") is True
        assert registry.unregister("tester") is False
        assert not registry.contains("tester")

    def test_require_raises_for_unknown(self):
        registry = default_personality_registry()
        with pytest.raises(PersonalityValidationError):
            registry.require("unknown")

    def test_validation_rejects_empty_id(self):
        with pytest.raises(PersonalityValidationError):
            PersonalityRegistry().register(_tester_definition(profile_id=" "))

    def test_validation_rejects_empty_profile_field(self):
        definition = PersonalityDefinition(
            profile_id="broken",
            name="Broken",
            description="desc",
            profile=IdentityProfile(
                name="Broken", mission="", description="desc", philosophy="p"
            ),
        )
        with pytest.raises(PersonalityValidationError):
            PersonalityRegistry().register(definition)


# ---------------------------------------------------------------------------
# Personality persistence
# ---------------------------------------------------------------------------


class TestPersonalityPersistence:
    def test_load_returns_none_when_missing(self, tmp_path):
        persistence = PersonalityPersistence(str(tmp_path / "missing.json"))
        assert persistence.load() is None

    def test_save_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "state.json")
        persistence = PersonalityPersistence(path)
        persistence.save("tester")
        assert persistence.load() == "tester"

    def test_load_returns_none_for_invalid_content(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("not-json", encoding="utf-8")
        assert PersonalityPersistence(str(path)).load() is None

    def test_load_returns_none_for_non_dict(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("[1, 2]", encoding="utf-8")
        assert PersonalityPersistence(str(path)).load() is None

    def test_clear_removes_selection(self, tmp_path):
        path = str(tmp_path / "state.json")
        persistence = PersonalityPersistence(path)
        persistence.save("tester")
        persistence.clear()
        assert persistence.load() is None


# ---------------------------------------------------------------------------
# Personality lifecycle
# ---------------------------------------------------------------------------


class TestPersonalityLifecycle:
    def test_default_active_is_samaktha_core(self):
        manager = PersonalityLifecycleManager(default_personality_registry())
        assert manager.active_profile_id == DEFAULT_PERSONALITY_ID
        assert manager.current_profile().name == "Samaktha"

    def test_activate_switches_and_validates(self):
        registry = default_personality_registry()
        registry.register(_tester_definition())
        manager = PersonalityLifecycleManager(registry)
        definition = manager.activate("tester")
        assert definition.profile_id == "tester"
        assert manager.active_profile_id == "tester"
        assert manager.current_profile().name == "Tester"

    def test_activate_unknown_raises(self):
        manager = PersonalityLifecycleManager(default_personality_registry())
        with pytest.raises(PersonalityValidationError):
            manager.activate("nope")

    def test_deactivate_resets_to_default(self):
        registry = default_personality_registry()
        registry.register(_tester_definition())
        manager = PersonalityLifecycleManager(registry)
        manager.activate("tester")
        manager.deactivate()
        assert manager.active_profile_id == DEFAULT_PERSONALITY_ID

    def test_available_lists_registered(self):
        registry = default_personality_registry()
        registry.register(_tester_definition())
        manager = PersonalityLifecycleManager(registry)
        ids = [d.profile_id for d in manager.available()]
        assert ids == [DEFAULT_PERSONALITY_ID, "tester"]

    def test_switch_is_persisted_and_restored(self, tmp_path):
        path = str(tmp_path / "state.json")
        registry = default_personality_registry()
        registry.register(_tester_definition())
        persistence = PersonalityPersistence(path)
        manager = PersonalityLifecycleManager(registry, persistence=persistence)
        manager.activate("tester")
        assert persistence.load() == "tester"

        restarted = PersonalityLifecycleManager(registry, persistence=persistence)
        assert restarted.active_profile_id == "tester"

    def test_default_profile_id_tolerates_bad_configuration(self):
        registry = default_personality_registry()
        manager = PersonalityLifecycleManager(
            registry, default_profile_id="does-not-exist"
        )
        assert manager.active_profile_id == DEFAULT_PERSONALITY_ID


# ---------------------------------------------------------------------------
# Personality switching on the engine and orchestrator
# ---------------------------------------------------------------------------


class TestPersonalitySwitching:
    def test_engine_set_profile_switches_evaluation(self):
        from app.personality import PersonalityEngine

        engine = PersonalityEngine()
        engine.set_profile(_profile(name="Switched"))
        evaluation = engine.evaluate("hello there")
        assert evaluation.profile.name == "Switched"

    def _orchestrator(self, **kwargs):
        return SamakthaOrchestrator(
            context_engine=MagicMock(),
            planner=MagicMock(),
            router=MagicMock(),
            runtime=MagicMock(),
            **kwargs,
        )

    def test_orchestrator_default_personality(self):
        orch = self._orchestrator()
        assert orch.get_personality()["profile_id"] == DEFAULT_PERSONALITY_ID
        assert orch.list_personalities()[0]["name"] == "Samaktha Core"

    def test_orchestrator_switch_personality(self):
        orch = self._orchestrator()
        orch.personality_registry.register_profile(
            "tester", "Tester", "Test personality", _profile()
        )
        result = orch.switch_personality("tester")
        assert result["profile_id"] == "tester"
        assert orch.get_personality()["profile_id"] == "tester"
        assert orch._personality_engine.profile.name == "Tester"

    def test_orchestrator_switch_unknown_raises(self):
        orch = self._orchestrator()
        with pytest.raises(PersonalityValidationError):
            orch.switch_personality("nope")

    def test_orchestrator_switch_accepts_registry_manager(self):
        registry = default_personality_registry()
        registry.register(_tester_definition())
        manager = PersonalityLifecycleManager(registry)
        orch = self._orchestrator(
            personality_registry=registry, personality_manager=manager
        )
        orch.switch_personality("tester")
        assert orch.get_personality()["profile_id"] == "tester"

    def test_orchestrator_engine_uses_manager_profile(self):
        registry = default_personality_registry()
        registry.register(_tester_definition())
        manager = PersonalityLifecycleManager(registry)
        manager.activate("tester")
        orch = self._orchestrator(personality_manager=manager)
        assert orch._personality_engine.profile.name == "Tester"


# ---------------------------------------------------------------------------
# Personality → GAMBIT integration
# ---------------------------------------------------------------------------


class _RecordingPlanner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def plan_with_capability_check(
        self, request: str, planning_context=None, personality_context=None
    ):
        self.calls.append(
            {
                "request": request,
                "planning_context": planning_context,
                "personality_context": personality_context,
            }
        )
        return "plan"


class _LegacyPlanner:
    async def plan_with_capability_check(self, request: str, planning_context=None):
        return "plan"


class TestPersonalityGambitIntegration:
    def test_planner_records_personality_directive_in_plan(self):
        from app.core.gambit import Planner
        from app.tools.capability_registry import CapabilityEntry, CapabilityRegistry

        planner = Planner(capability_registry=CapabilityRegistry([
            CapabilityEntry(domain="filesystem", tool_id="resolver")
        ]))
        import asyncio

        result = asyncio.run(
            planner.plan_with_capability_check(
                "list the files in the current folder",
                personality_context={
                    "profile_id": "samaktha-core",
                    "name": "Samaktha",
                    "tone": "professional",
                    "reasoning": "step_by_step",
                },
            )
        )
        assert result.status.value == "ok"
        assert result.plan is not None
        assert any("Active personality: personality=samaktha-core" in note for note in result.plan.notes)
        assert any("Personality directive applied" in line for line in result.plan.planner_reasoning)

    def test_planner_without_personality_context_is_unchanged(self):
        from app.core.gambit import Planner
        from app.tools.capability_registry import CapabilityEntry, CapabilityRegistry

        planner = Planner(capability_registry=CapabilityRegistry([
            CapabilityEntry(domain="filesystem", tool_id="resolver")
        ]))
        import asyncio

        result = asyncio.run(
            planner.plan_with_capability_check("list the files in the current folder")
        )
        assert result.plan is not None
        assert not any("personality" in note.lower() for note in result.plan.notes)

    @pytest.mark.asyncio
    async def test_orchestrator_passes_personality_context_to_planner(self):
        planner = _RecordingPlanner()
        orch = SamakthaOrchestrator(
            context_engine=MagicMock(),
            planner=planner,
            router=MagicMock(),
            runtime=MagicMock(),
        )
        await orch._planner_plan(
            "hello", None, {"profile_id": "samaktha-core", "name": "Samaktha"}
        )
        assert planner.calls[0]["personality_context"]["profile_id"] == "samaktha-core"
        assert planner.calls[0]["personality_context"]["name"] == "Samaktha"

    @pytest.mark.asyncio
    async def test_orchestrator_falls_back_for_legacy_planner(self):
        planner = _LegacyPlanner()
        orch = SamakthaOrchestrator(
            context_engine=MagicMock(),
            planner=planner,
            router=MagicMock(),
            runtime=MagicMock(),
        )
        assert await orch._planner_plan("hello", None) == "plan"


# ---------------------------------------------------------------------------
# Personality API
# ---------------------------------------------------------------------------


def _metrics_client(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "SAMAKTHA_PERSONALITY_STATE_PATH", str(tmp_path / "state.json")
    )
    from fastapi.testclient import TestClient

    from app.config.settings import Settings
    from app.core.app import create_app

    return TestClient(create_app(Settings()))


class TestPersonalityApi:
    def test_get_personality_returns_active_and_available(self, tmp_path, monkeypatch):
        client = _metrics_client(tmp_path, monkeypatch)
        response = client.get("/personality")
        assert response.status_code == 200
        body = response.json()
        assert body["active"]["profile_id"] == DEFAULT_PERSONALITY_ID
        assert any(
            p["profile_id"] == DEFAULT_PERSONALITY_ID for p in body["available"]
        )
        assert all("profile_id" in p for p in body["available"])

    def test_switch_personality_known_profile(self, tmp_path, monkeypatch):
        client = _metrics_client(tmp_path, monkeypatch)
        response = client.put(f"/personality/{DEFAULT_PERSONALITY_ID}")
        assert response.status_code == 200
        assert response.json()["profile_id"] == DEFAULT_PERSONALITY_ID

    def test_switch_personality_unknown_returns_404(self, tmp_path, monkeypatch):
        client = _metrics_client(tmp_path, monkeypatch)
        response = client.put("/personality/does-not-exist")
        assert response.status_code == 404

    def test_switch_personality_is_persisted(self, tmp_path, monkeypatch):
        state_path = tmp_path / "state.json"
        monkeypatch.setenv("SAMAKTHA_PERSONALITY_STATE_PATH", str(state_path))
        from fastapi.testclient import TestClient

        from app.config.settings import Settings
        from app.core.app import create_app

        client = TestClient(create_app(Settings()))
        client.put(f"/personality/{DEFAULT_PERSONALITY_ID}")
        import json

        assert json.loads(state_path.read_text(encoding="utf-8"))["profile_id"] == (
            DEFAULT_PERSONALITY_ID
        )
