# Phase 11.7 — Production Stabilization & Architecture Cleanup — Final Audit Report

Date: 2026-08-02

Scope: No new features. Stabilization, cleanup, and production hardening only.
No changes were committed; this report is the phase deliverable.

---

## 1. Files modified (Phase 11.7 work)

Application code:

- `app/providers/config.py` — `mock_allowed()` is now the single source of
  truth for mock-provider admission (mock_enabled → mock_agent/dev_mode →
  `MOCK_AGENT` env). `_PRODUCTION_PROVIDERS` already excludes `mock`.
- `app/providers/manager.py` — unified the duplicate fallback candidate logic:
  `_ordered_stream_candidates` removed, both `execute_provider` and
  `execute_provider_stream` now share one `_candidate_infos` source.
- `app/core/app.py` — removed the duplicated local `_mock_allowed(settings)`;
  all call sites use `provider_settings.mock_allowed()`; OpenRouter now
  registered in the RouterRegistry and CapabilityRegistry; `model_manager`
  attached to the orchestrator for startup validation.
- `app/agent/production.py` — runtime unification: `ProductionAgentRuntime`
  builds exactly ONE `SamakthaOrchestrator` and ONE `_StreamingRuntimeBridge`
  in `__init__`; `handle_message` and `resume` reuse `self._orchestrator`
  (per-request construction removed). Per-request output queue travels through
  `RuntimeContext.metadata["output_queue"]`. Removed leftover debug trace write.
- `app/diagnostics.py` — added Environment section (Python, Temp Dir), Model
  Registry validation for the default model, and a real SQLite connectivity
  check; `Environment` added to `_CRITICAL_SECTIONS`.
- `app/core/orchestrator/engine.py` — removed dead `_select_runtime_plan_task`,
  unused imports, and leftover `samaktha_trace.txt` debug writes.
- `app/workflow/engine.py` — removed leftover `samaktha_trace.txt` debug writes,
  unused imports.
- `app/runtime/checkpoint.py` — timezone-aware timestamps.
- `app/memory/*` (manager, skills, resources, context, models, controller/*) —
  timezone-aware timestamps.
- `app/core/contracts/*` (memory, skills, pause, telemetry, trace) — timezone-
  aware timestamp default factories.
- `app/tui/app.py`, `app/tui/events.py` — `get_event_loop()` → `get_running_loop()`.
- `app/tui/mascot.py` — deprecated Pillow `getdata()` → `get_flattened_data()`
  with a version-compatible fallback.
- Import cleanups (unused imports removed): `app/agent/personality_profiles.py`,
  `app/core/gambit/agent_planner.py`, `app/memory/agent_memory.py`,
  `app/memory/controller/lifecycle_manager.py`, `app/router/policy.py`,
  `app/runtime/engine.py`, `app/security/input_scanner.py`,
  `app/tools/capability_registry.py`, `app/tools/models.py`,
  `app/windows/clipboard.py`, `app/workflow/metrics.py`,
  `app/core/contracts/pause.py`, `app/tui/events.py`.

Test files:

- `tests/architecture/test_phase117_architecture.py` — NEW regression suite (15 tests).
- `tests/gambit/test_phase35_skill_lifecycle.py` — tz-aware timestamps.

## 2. Dead code eliminated

- `SamakthaOrchestrator._select_runtime_plan_task` (defined, zero callers).
- `samaktha_trace.txt` debug writes in `orchestrator/engine.py` and
  `workflow/engine.py` (per-request file I/O removed).
- Unused imports across 13 files (see section 1).

## 3. Architecture improvements

- **One production pipeline (Part 1).** The TUI facade and the API backend now
  both traverse a single `SamakthaOrchestrator` instance. `ProductionAgentRuntime`
  constructs one orchestrator once; every message and resume routes through it.
  The `_StreamingRuntimeBridge` is transport-only and stateless.
- **Provider architecture (Part 2).** Manager executes, Router decides,
  HealthChecker reports. Verified: `ModelRouter.route()` selects (Router decides);
  `ProviderManager.execute*` executes with deterministic fallback (Manager
  executes); `ProviderHealthChecker` tracks health/cooldown (reports), no network
  calls. Single candidate source `_candidate_infos` feeds both sync and streaming
  execution.
- **OpenRouter fully registered (Part 3).** ProviderRegistry, ModelRegistry,
  RouterRegistry, and CapabilityRegistry now all contain OpenRouter (model
  `openai/gpt-oss-120b`, text + code generation).
- **Production/Test separation (Part 4).** MockProvider cannot enter a
  production composition: every reference is gated by
  `ProviderSettings.mock_allowed()`, which is the single source of truth;
  `_PRODUCTION_PROVIDERS` excludes `mock`.
- **Startup validation (Part 5).** Diagnostics now cover Environment
  (Python version, temp dir), Models (default model registration), and a real
  SQLite connectivity check. Failures in Environment, Providers, Router,
  Memory, and Runtime abort startup.

## 4. Tech debt removed

- `datetime.utcnow()` → `datetime.now(timezone.utc)`: 30 call sites plus
  `default_factory=datetime.utcnow` in 5 contract/model files (now timezone-aware
  via explicit UTC).
- `asyncio.get_event_loop()` → `asyncio.get_running_loop()` (3 sites).
- Pillow `Image.getdata()` → `get_flattened_data()` (version-compatible fallback).
- Dynamic `__import__("datetime").datetime.utcnow()` in preference_resolver
  replaced with a normal import.
- Debug trace file writes removed from the hot path.

## 5. Tech debt remaining (intentional)

- `asyncio.iscoroutinefunction` checks in `tui/renderer.py` — required
  cross-version guard (Textual `update` is async in some versions, sync in others).
- `ProviderManager.select_provider` / `ProviderSelectionEngine` — exercised by
  `test_provider_selection.py`; kept as a deterministic selection helper.
- `ProviderRegistry.find_by_capability` / `validate_availability` — test-facing;
  kept.
- Legacy `_persist_conversation_to_memory` fallback — documented fallback when
  the Memory Formation Engine is absent; kept.
- Voice `__import__("asyncio")` / `__import__("sys")` lazy shims — optional-
  dependency guards; kept.
- SQLite connect-per-operation in `sqlite_store.py` — existing design; see
  recommendation 5.

## 6. Test summary

- New regression tests: 15 (`tests/architecture/test_phase117_architecture.py`)
  covering runtime unification, unified candidate selection, OpenRouter
  registration, mock production-isolation, startup diagnostics coverage, and
  removal of deprecated APIs / dead code.
- Full suite: **1183 passed, 4 failed**.
- The 4 failures are the pre-existing environment failures in
  `tests/fileparsers/test_ocr_pipeline.py` (TestScannedPDF ×3,
  TestImageOnlyDocument) — no OCR engine in this environment. Same baseline as
  before Phase 11.7 (1168 passed → 1183 passed with the 15 new tests).

## 7. Performance audit (Part 8)

All `tests/benchmark` thresholds comfortably met:

| Benchmark | Result | Threshold |
|---|---|---|
| Router (50 routes) | 0.004 ms/op | < 50 ms |
| ToolChain 3-step (50 runs) | 0.098 ms/run | < 50 ms |
| SemanticMemory 100 items (50 searches) | 0.995 ms/search | < 100 ms |
| SkillRetrieval 50 skills (100 searches) | 0.619 ms/search | < 50 ms |
| SecurityScanner (500 scans) | 0.017 ms/scan | < 2 ms |
| OutputFilter (500 ops) | 0.008 ms/op | < 2 ms |
| Streaming 10 chunks (20 runs) | 0.019 ms/run | < 100 ms |

No per-request orchestrator/provider/router construction remains. Health checks
are local-only (no network). Candidate selection is bounded by provider count.

## 8. Architecture audit results (Part 7)

- [x] One orchestrator shared across message + resume (verified behaviorally).
- [x] No per-request construction of orchestrator, router, or provider manager.
- [x] Router decides (verified: routes text + code generation), Manager
  executes, HealthChecker reports.
- [x] OpenRouter routable; candidates ordered primary-first.
- [x] No mock provider in production composition when mock is not allowed.
- [x] No duplicated selection/fallback loops.

## 9. Consistency audit results (Part 9)

- [x] No TODO/FIXME/HACK markers in `app/`.
- [x] No stray debug `print()` in production paths (remaining prints are
  subprocess IPC / pre-TUI startup diagnostics).
- [x] Unused imports removed where confirmed (import-only occurrences).
- Note: no linter is configured; a `[tool.ruff]` section is a recommended
  follow-up (recommendation 2). Most remaining flagged imports are `__init__.py`
  re-exports or string-annotation usages, which are intentional.

## 10. Recommendation log

1. **Commit.** Phase 11.5–11.7 work is uncommitted; commit after review.
2. **Add a linter.** Introduce `ruff` (or pyflakes) with `app/` clean checks to
   keep import hygiene enforced.
3. **Drop legacy persistence** when the Memory Formation Engine is guaranteed
   present in production composition (removes `_persist_conversation_to_memory`).
4. **Consolidate test-facing provider helpers** (`select_provider`,
   `find_by_capability`, `validate_availability`) behind an explicit test API or
   remove if Phase 12 drops the legacy tests.
5. **SQLite connection reuse** in `sqlite_store.py` (connection-per-op) is the
   largest remaining micro-cost; evaluate a pool in Phase 12.
6. **CI OCR.** Install an OCR engine (tesseract or easyocr) to clear the 4
   environment-failing OCR tests.

## 11. Closing

Phase 11.7 delivered the stabilization pass without adding features: a single
production pipeline, a clean provider architecture, complete OpenRouter
registration, hardened mock isolation, deeper startup validation, removal of
deprecated APIs and dead code, and 15 regression tests locking the guarantees in
place. Full suite 1183 passed / 4 pre-existing environment failures. Ready for
review before Phase 12.
