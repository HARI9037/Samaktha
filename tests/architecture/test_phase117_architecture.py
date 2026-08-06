"""Phase 11.7 — regression protection for production stabilization.

Locks in the Phase 11.7 architecture guarantees:
    - one production pipeline: a single shared orchestrator serves every
      message and resume (no per-request construction)
    - OpenRouter is fully registered (provider, model, router, capability)
    - MockProvider can never appear in a production composition
    - provider selection is unified through one candidate source
    - startup diagnostics cover environment, models, and database
    - deprecated APIs (datetime.utcnow, get_event_loop) are gone from app/
    - dead debug code (trace files, orphan helpers) is removed
"""

import asyncio
from types import SimpleNamespace
from pathlib import Path

import app.core.app as core_app
import app.agent.production as production_module
from app.providers.config import ProviderSettings, _PRODUCTION_PROVIDERS
from app.diagnostics import SystemDiagnostics

REPO_ROOT = Path(__file__).resolve().parents[2]


def _source(module) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Part 1 — Runtime unification (one production pipeline)
# ---------------------------------------------------------------------------


def test_production_runtime_builds_exactly_one_orchestrator():
    source = _source(production_module)
    assert source.count("create_orchestrator()") == 1
    assert source.count("SamakthaOrchestrator(") == 1
    assert source.count("bridge = _StreamingRuntimeBridge(") == 1


def test_message_and_resume_reuse_the_shared_orchestrator():
    source = _source(production_module)
    assert "self._orchestrator.run_pipeline" in source
    assert "self._orchestrator.resume_pipeline" in source
    assert "async def handle_message" in source
    assert "async def resume" in source


def test_single_orchestrator_serves_message_and_resume():
    """A message and its resume traverse the SAME orchestrator instance."""
    real_orchestrator = production_module.SamakthaOrchestrator
    real_factory = production_module.create_orchestrator
    constructed: list = []

    class RecordingOrchestrator:
        def __init__(self, *args, **kwargs):
            constructed.append(self)
            self._runtime = kwargs.get("runtime")
            self.streaming_executor = None

        async def run_pipeline(self, request, context):
            return SimpleNamespace(runtime_result=None)

        async def resume_pipeline(self, state, context, task_id, updates):
            return state

    def _stub_base():
        return SimpleNamespace(
            streaming_executor=None,
            _runtime=None,
            _context_engine=None,
            _planner=None,
            _router=None,
            _workflow_engine=None,
            _policy_engine=None,
            _approval_engine=None,
            memory_manager=None,
            memory_controller=None,
            session_manager=None,
            conversation_state_manager=None,
        )

    production_module.SamakthaOrchestrator = RecordingOrchestrator
    production_module.create_orchestrator = _stub_base
    try:
        runtime = production_module.ProductionAgentRuntime()

        async def consume(agen):
            items = []
            async for item in agen:
                items.append(item)
            return items

        async def main():
            await consume(runtime.handle_message("session-a", "hello"))
            state = runtime._active_states["session-a"]
            await consume(runtime.resume("session-a", "task-1", {}))
            assert state is runtime._active_states["session-a"]

        asyncio.run(main())
    finally:
        production_module.SamakthaOrchestrator = real_orchestrator
        production_module.create_orchestrator = real_factory

    assert len(constructed) == 1


# ---------------------------------------------------------------------------
# Part 2 — Unified provider selection (no duplicate fallback paths)
# ---------------------------------------------------------------------------


def test_execution_paths_share_one_candidate_source():
    import app.providers.manager as manager_module

    source = _source(manager_module)
    assert "_candidate_infos" in source
    assert "def _candidate_infos" in source
    assert "_ordered_stream_candidates" not in source
    assert source.count("_candidate_infos(") >= 3


def test_candidate_source_orders_primary_first():
    from app.providers.registry import ProviderRegistry
    from app.providers.models import ProviderInfo
    from app.providers.manager import ProviderManager
    from app.providers.config import ProviderSettings

    registry = ProviderRegistry()
    for provider_id in ("openai", "groq", "openrouter", "local"):
        registry.register(
            provider_id=provider_id,
            provider=None,
            info=ProviderInfo(
                provider_id=provider_id,
                capabilities=["text_generation"],
                models=[f"{provider_id}-model"],
                supported_models=[f"{provider_id}-model"],
                metadata={},
            ),
        )
    manager = ProviderManager(registry, ProviderSettings(_env_file=None))
    candidates = manager._candidate_infos("openrouter", ["text_generation"])
    ids = [candidate.provider_id for candidate in candidates]
    assert ids[0] == "openrouter"
    assert "openrouter" in ids
    assert "groq" in ids


# ---------------------------------------------------------------------------
# Part 3 — OpenRouter fully registered (provider, model, router, capability)
# ---------------------------------------------------------------------------


def test_openrouter_registered_across_all_layers():
    source = _source(core_app)
    assert source.count('provider_id="openrouter"') >= 4
    assert 'provider_id="openrouter"' in source
    assert 'capabilities=["text_generation", "code_generation"]' in source


# ---------------------------------------------------------------------------
# Part 4 — MockProvider never enters production composition
# ---------------------------------------------------------------------------


def test_production_provider_set_excludes_mock():
    assert "mock" not in _PRODUCTION_PROVIDERS
    assert "groq" in _PRODUCTION_PROVIDERS
    assert "openrouter" in _PRODUCTION_PROVIDERS


def test_production_composition_has_no_mock_when_not_allowed(monkeypatch):
    monkeypatch.delenv("MOCK_AGENT", raising=False)
    monkeypatch.setattr(
        core_app,
        "ProviderSettings",
        lambda: ProviderSettings(_env_file=None, groq_api_key="test-key"),
    )
    orchestrator = core_app.create_orchestrator()
    manager = orchestrator.provider_manager
    registered = {info.provider_id for info in manager.list_providers()}
    assert "mock" not in registered
    for provider_id in ("groq", "openai", "openrouter", "local"):
        candidates = manager._candidate_infos(provider_id, ["text_generation"])
        assert all(c.provider_id != "mock" for c in candidates)
    router_registrations = orchestrator._router._registry.all()
    assert all(r.provider_id != "mock" for r in router_registrations)


def test_mock_only_enters_composition_when_explicitly_allowed(monkeypatch):
    monkeypatch.delenv("MOCK_AGENT", raising=False)
    monkeypatch.setattr(
        core_app,
        "ProviderSettings",
        lambda: ProviderSettings(_env_file=None, groq_api_key="test-key", mock_agent=True),
    )
    orchestrator = core_app.create_orchestrator()
    registered = {info.provider_id for info in orchestrator.provider_manager.list_providers()}
    assert "mock" in registered


def test_mock_allowed_is_single_source_of_truth():
    source = _source(core_app)
    assert "_mock_allowed" not in source
    assert "provider_settings.mock_allowed()" in source


# ---------------------------------------------------------------------------
# Part 5 — Startup validation (environment, models, database)
# ---------------------------------------------------------------------------


def test_diagnostics_cover_critical_sections():
    report = SystemDiagnostics(settings=ProviderSettings(_env_file=None)).run()
    sections = set(report.sections())
    assert {"Environment", "Models", "Memory", "Providers", "Router", "Runtime"} <= sections
    labels = {check.label for check in report.checks}
    assert {"Python", "Default Model", "Model Registry", "SQLite"} <= labels


# ---------------------------------------------------------------------------
# Part 6 — Deprecated APIs and dead code removed
# ---------------------------------------------------------------------------


def test_no_deprecated_datetime_utcnow_in_app():
    for source_path in (REPO_ROOT / "app").rglob("*.py"):
        text = source_path.read_text(encoding="utf-8")
        assert "datetime.utcnow" not in text, source_path


def test_no_get_event_loop_in_app():
    for source_path in (REPO_ROOT / "app").rglob("*.py"):
        text = source_path.read_text(encoding="utf-8")
        assert "get_event_loop" not in text, source_path


def test_debug_trace_files_removed():
    for source_path in (REPO_ROOT / "app").rglob("*.py"):
        text = source_path.read_text(encoding="utf-8")
        assert "samaktha_trace" not in text, source_path


def test_dead_helper_removed_from_orchestrator():
    import app.core.orchestrator.engine as engine_module

    assert "_select_runtime_plan_task" not in _source(engine_module)
