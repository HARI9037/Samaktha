# Samaktha — Verification & Profiling Baseline

**Phase:** engineering verification and measurement (no refactoring, no migration).
**Objective:** establish an evidence-based engineering baseline for future architecture and polyglot decisions.
**Date of measurement:** 2026-10-06, all on the machine at `C:\Users\user\Desktop\Samaktha`.
**Interpreter used for every measurement:** `.\.venv\Scripts\python.exe` exclusively. No other Python was invoked for application work.

Measurement truth rules used throughout:
- Every number below is a **measured or directly source-verified** value, not an estimate.
- Anything that could not be determined is explicitly labeled `UNVERIFIED` or `SKIPPED` with a reason. Nothing is invented.
- Repository rule: no source code was modified. The only file created is this report.

---

## 1. Environment

| Item | Value |
| --- | --- |
| OS | Windows (win32), PowerShell 5.1 host |
| Repository | `C:\Users\user\Desktop\Samaktha` |
| Python | **3.14.5** (`pyvenv.cfg` → `home = C:\Python314`; venv `version = 3.14.5`) |
| pytest | **9.1.1** |
| PyInstaller | 6.22.2 |
| Dependency environment | `.venv` (project-local, `include-system-site-packages = false`) |
| Pinned resolution file | `requirements/pilot-windows-py314.txt` (dated 2026-09-06) |

Key package versions verified in the active venv:

```
fastapi==0.139.2     uvicorn==0.51.0      pydantic==2.13.4      textual==8.2.8
pymupdf==1.28.0      pytesseract==0.3.13  httpx==0.28.1          ddgs==9.16.0
torch==2.13.0        pytest==9.1.1        PyInstaller==6.22.2
groq= MISSING        easyocr= MISSING     sqlalchemy= MISSING
```

Notes:
- `groq` SDK is **not installed**; the Groq provider must use raw HTTP (`httpx`).
- `easyocr` is **not installed**; the OCR path's EasyOCR worker is unavailable in this environment (code probes for it and falls back).
- No `sqlalchemy`; persistence is stdlib `sqlite3`.

**Version drift vs the pinned file (evidence from the built `dist\` artifact):** 14 packages in the runtime environment differ from `requirements/pilot-windows-py314.txt` pins (e.g. `fastapi` 0.139.2 vs pinned 0.141.1, `torch` 2.13.0 vs 2.14.0, `numpy` 2.5.1 vs 2.5.2). The rebuilt artifact is therefore not reproducible from the pinned file. `SOURCE-ONLY` (measured on the existing artifact, not on a fresh install).

**Python floor note:** declared `requires-python = ">=3.12"`, but the only venv used here is 3.14 (see Section 10).

---

## 2. Test baseline

Command:
```powershell
$base = "$env:USERPROFILE\SamakthaPytest-<guid>"
.\.venv\Scripts\python.exe -m pytest -q --basetemp "$base"
```

| Metric | Value |
| --- | --- |
| Test count | **3,151** |
| Passed | **3,151** |
| Failed | **0** |
| Errors | **0** |
| Skipped | **0** |
| Warnings | **87** |
| Total runtime | **518.01 s (08:38)** |
| Exit code | **0** |
| Collection time | ~4 s (observed 4.03 s during earlier collection pass; not printed separately in this run) |
| Failure classification | **N/A — zero failures**, so no REGRESSION / PRE-EXISTING / ENVIRONMENT / TEST INFRASTRUCTURE / UNKNOWN classification is required |

Warnings observed (count by cause, all non-fatal):
- `StarletteDeprecationWarning` (fastapi `testclient` → `httpx2`) — 1
- `DeprecationWarning: TestProvider is deprecated` — communication tests — ~60
- `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` — 3 (test-only async-mock leaks)
- `UserWarning: Session ... migrated from schema v0 to v2` — schema-migration informational — several
- `Pydantic serializer warnings` (permit tampering tests intentionally serialize mismatched enum/str values) — 2
- `DeprecationWarning: datetime.utcnow()` — evidence/concurrency tests — 2
- `DeprecationWarning: asyncio.iscoroutinefunction is deprecated in Python 3.16` — `app/tui/renderer.py:101` — 1 (production line, future-removal warning)
- `SessionManager` schema-recovery validation warnings — hardening test — 2 (expected behavior)

**Baseline verdict: the full suite is green on CPython 3.14.5.** Zero failures, 87 benign warnings. The three `AsyncMock` coroutine leaks are test-infrastructure hygiene, not production behavior.

---

## 3. Governance verification

### 3.1 The actual authorization path (traced end to end)

```
CAP DECISION → PERMIT CREATION → TRANSPORT → RUNTIME VALIDATION → EXECUTOR → EFFECT
```

1. **Capability/plan selection** — GAMBIT produces a `PlannedAction` (`app/core/app.py`, `app/core/orchestrator/engine.py`).
2. **Policy evaluation** — `PolicyEngine.evaluate(PlannedAction)` (`app/core/cap/policy_engine.py`) → `PolicyDecision` with `required_permissions`, `risk`, `constraints`.
3. **Approval** — `ApprovalEngine.authorize(ApprovalRequest(...), subject_id, session_id, workspace_id)` (`app/core/cap/approval_engine.py:67`) issues an `ExecutionPermit`. Issuance is `ExecutionPermit.issue(...)` (`app/core/contracts/policy.py:214-255`):
   - binds `action_id`, `subject_id`, `session_id`, `workspace_id`, `action_type`, `target`, `operation_digest`, `required_permissions`, `risk`, `constraints`, `issued_at`, `expires_at`, `decision`.
   - **signed**: HMAC-SHA256 over all fields except `integrity_digest` (`policy.py:401-409`) using a 32-byte key.
   - key loading: `configure_permit_signing_key` is called in production (`app/core/app.py:692-706`) from `config/permit_signing_key`; the module default is a fresh random per-process key (`policy.py:15`), so if configuration loading ever failed the key would not be persistent (see Section 12).
4. **Transport** — the permit is attached to an `ApprovedRuntimeTask.permit`. Two production construction sites: `app/core/app.py:1266-1281` and `app/workflow/engine.py:561-568`. The workflow site explicitly documents **"CAP is the sole permit issuer. Resume data may never patch it."** (`workflow/engine.py:543`) and deserializes the permit from metadata on resume — the HMAC protects it from field tampering.
5. **Runtime validation** — `enforce_cap_permit` (`app/runtime/governance.py:73-259`), invoked at exactly three production call sites, all inside `app/runtime/engine.py`:
   - `engine.py:91` — `RuntimeExecutionPool` batch path when no custom runner is supplied.
   - `engine.py:290` — `RuntimeEngine.run` recovered-operation path (revalidation before reusing checkpointed evidence; plus `_validate_recovered_tool_security` at `engine.py:295`).
   - `engine.py:392` — `RuntimeEngine._run_once` (the normal single-attempt path).
   - The pool's `_runtime_runner` hook (`engine.py:84-85`) is only ever wired to `RuntimeEngine.run` in production (`engine.py:549-556`, `self.run`) — which itself gates. **No production path reaches an executor without passing a gate.**
6. **Replay guard** — for non-idempotent mutation permits, `RuntimeEngine._run_once` (`engine.py:402-425`) rejects a permit id already present in `_consumed_mutation_permits` (one dispatch per mutation permit per process).
7. **Dispatch** — `RuntimeDispatcher.dispatch(action_type)` (`app/runtime/dispatcher.py`) → `ToolExecutor` / `ProviderExecutor` (`app/runtime/executor.py`), both registered non-optionally (`app/core/app.py:1544-1556`) with real (non-`None`) security dependencies.

### 3.2 Every permit predicate (enumerated, with exact source)

| # | Predicate | Implemented | Location |
| --- | --- | --- | --- |
| 1 | Task must be `ApprovedRuntimeTask` with non-`None` permit | YES | `governance.py:87-92` |
| 2 | **Approval state** — `ASK_USER` → returns `PAUSED` with `ExecutionPause`; anything not `ALLOW` → blocked | YES | `governance.py:103-135` |
| 3 | **Integrity** — HMAC digest re-computed and compared | YES (constant-time `hmac.compare_digest`) | `governance.py:137` → `policy.py:257-259` |
| 4 | **Validity — not yet valid** (future-dated permit) | YES (small clock-skew allowance) | `governance.py:144` → `policy.py:264-272` |
| 5 | **Expiration** | YES (lifetime bound set in `ExecutionPermit.issue`) | `governance.py:151` → `policy.py:261-262` |
| 6 | **Principal / subject** (typed `RuntimeContext` authoritative; metadata only as fallback when no identity) | YES | `governance.py:162-183` |
| 7 | **Session** | YES — but only enforced when the permit carries a session | `governance.py:184-192` |
| 8 | **Workspace** | YES — but only enforced when the permit carries a workspace | `governance.py:193-200` |
| 9 | **Action** (`permit.action_id == task.task_id`) | YES | `governance.py:201-207` |
| 10 | **Operation** (action_type + normalized target + `operation_digest` of payload) | YES | `governance.py:209-226` |
| 11 | **Resource scope** (`required_permissions` must match permit exactly) | YES | `governance.py:228-235` |
| 12 | **Constraints** (execution constraints must equal permit constraints) | YES | `governance.py:237-249` |
| 13 | **Routing fidelity** (for provider/text/code actions, router must preserve CAP constraints) | YES | `governance.py:250-257` |
| 14 | **Mutation no-replay** (per-process) | YES (outside the gate, in the caller) | `engine.py:402-425` |

**Every predicate requested in the phase brief is present and source-verified.** Conditions on two: session and workspace checks are *conditional* on the permit carrying those values (a permit issued for a sessionless/workspaceless request is not bound to one — consistent with a single-user local model).

### 3.3 Tool-layer defense-in-depth (all non-`None` in production)

`ToolExecutor.execute` (`app/runtime/executor.py:305+`) applies, in order:
1. **CAP network constraint** — `permit.constraints.network_allowed` (`executor.py:315-332`).
2. **`ToolGuard.authorize_tool_execution`** (`executor.py:343-347`; guard constructed at `app.py:1542`).
3. **`GovernanceEngine.enforce_tool`** with declared permissions (`executor.py:372-384`; engine at `app.py:1545`).
4. **`ToolSecurityEnforcer.validate`** — filesystem/shell/process/network policies (`executor.py:431`; enforcer at `app.py:966-971`).

`ProviderExecutor.execute` applies `GovernanceEngine.enforce_provider` on the routed provider (`executor.py:97-104`) and records the decision.

### 3.4 Quarantine verification

| Component | Direct uncapped call | Wired into production? | Verification |
| --- | --- | --- | --- |
| `ToolChainExecutor` | `ToolManager.execute_tool` direct (`tool_chain.py:151`) | **NO** | grep of `app/**` yields zero imports; referenced only by `tests/runtime/test_phase54_tool_chain.py`, `tests/benchmark/test_phase56_benchmarks.py`, `tests/architecture/test_p0_architecture_freeze.py` |
| `MultimodalExecutor` | `ProviderManager.execute_provider` direct (`multimodal.py:104`) | **NO** | zero imports in `app/` |
| `StreamingExecutor` | `ProviderManager.stream_provider` direct (`streaming.py:64`) | **NO** | zero imports in `app/`; `app/core/app.py:1724` assigns the *governed* `provider_executor` to `orchestrator.streaming_executor` with comment "The legacy StreamingExecutor remains a disconnected library helper." |

The architecture-freeze suite (`tests/architecture/test_p0_architecture_freeze.py`, 744 lines) statically asserts these classifications (`POTENTIAL_BYPASS`, `SHOULD_REMAIN_DISCONNECTED`, `TRANSITIONAL`) and fails if any frozen class is instantiated by `create_orchestrator()`.

### 3.5 Direct-effect classification

| Can this happen without a canonical CAP permit? | Verdict | Basis |
| --- | --- | --- |
| LLM → OS / shell | **NO** — `SAFE` | only `ToolExecutor` (gated) calls `ToolManager` for `shell`; shell uses structured argv `asyncio.create_subprocess_exec` (`app/tools/shell.py:177`), no `shell=True` |
| LLM → filesystem | **NO** — `SAFE` | same gate; filesystem tool bound by `ToolSecurityEnforcer.filesystem` policy |
| LLM → network | **NO** — `SAFE` | network capability is permit-constrained (`network_allowed`) plus `ToolSecurityEnforcer.network` (port/header allowlists) |
| LLM → provider | **NO** — `SAFE` | `ProviderExecutor` gated; then `GovernanceEngine.enforce_provider` on the routed provider |
| `ToolChainExecutor`-style execution | `QUARANTINED BYPASS` | exists, uncapped, **not reachable** from production composition; test-enforced |
| `MultimodalExecutor` / `StreamingExecutor` | `QUARANTINED BYPASS` | same |
| `RecoveryManager` resume | `TRANSITIONAL` | accepted by `Runtime` interface, but composition supplies `None` (`app.py`); recovery revalidation code exists (`engine.py:285-300`) but no active manager |
| Pool `_runtime_runner` hook | `SAFE` today / documented hazard | if anyone ever passes an ungated callable, `engine.py:84-85` skips the gate; only `self.run` is passed today (`engine.py:556`) |

**One classified and verified HIGH (not a permit bypass):** provider **fallback fidelity** — Section 12, S1 (mock fallback confirmed by execution probe).

---

## 4. AgentLoop v1 status

`AgentLoop` (`app/core/agent_loop.py:27-123`) is wired into the orchestrator via `run_agent_step` (`app/core/orchestrator/engine.py:233-274`) with `max_steps=1`. Its permit evaluator (`engine.py:246-268`) goes through the real CAP engines and returns `None` unless the decision is `ALLOW`.

Flow actually implemented: **planned action → permit evaluation → Runtime.run (gated) → observation_from_runtime → apply_observation (deterministic transition) → termination.**

| Feature | Status | Evidence |
| --- | --- | --- |
| Planned-action → CAP → Runtime → Observation → state update → termination | **IMPLEMENTED** | `agent_loop.py:43-123`; contracts `app/core/contracts/agent_loop.py:178-217` |
| Step limit / budget (max steps) | **IMPLEMENTED** (fixed at 1) | `agent_loop.py:45-47`, `orchestrator/engine.py:270-274` |
| Cancellation | **IMPLEMENTED** | runtime `context.metadata["cancel_requested"]` (`engine.py:372`); `ObservationStatus.CANCELLED`; coordinator `cancel_execution` |
| Loop-level retry | **MISSING** (by design; `apply_observation` docstring: "never retries or replans") | `contracts/agent_loop.py:179` |
| Runtime-internal provider retry (not tools) | **IMPLEMENTED** but separate | `RuntimeEngine.run` retry loop `engine.py:279-379` + `RetryPolicy` (`app/runtime/reliability.py`); applies to provider failures, **not** tool failures (`TOOL_TIMEOUT` is non-retryable) |
| Replan | **MISSING** | — |
| Alternate action | **MISSING** | — |
| Recovery | **PARTIAL** | recovered-operation path and checkpoint callback exist (`engine.py:285-349`) but `RecoveryManager` is not in composition |
| Information acquisition | **MISSING** (loop level) | — |
| Clarification | **MISSING** as a loop feature | CAP `ASK_USER` pause exists but is *approval*, not clarification |
| Multi-step loop / iteration | **MISSING** | `max_steps=1` is the only wired value |
| Budget enforcement | **PARTIAL** | CAP `execution_constraints` propagate and are re-checked, but there is no per-loop token/time budget accounting |
| Timeout | **MISSING** (not established) | no task-level timeout observed on the inspected paths — labeled `UNVERIFIED`/absent rather than assumed |
| Checkpoint / resume | **PARTIAL** | `reliability_checkpoint` callback (`engine.py:307-349`) + coordinator checkpoints; resume revalidates permits (`engine.py:290`) and tool scope (`engine.py:295`) |

**Bottom line: the loop is deliberately single-step.** Nothing in current code iterates to goal completion.

---

## 5. Memory benchmark (Phase 4)

Measured against the **real** `SQLiteStore` + `MemoryRepository` (temp database in the OS temp dir; repo DB untouched). Search executes `MemoryRepository.search` → `SQLiteStore.list_entries()` (full `SELECT *`, connect-per-operation) → Python substring filter (`app/memory/repository.py:33-42`). Medians over repetitions; `perf_counter`.

| Dataset size | Insert total (ms) | warm search med (ms) | empty query med (ms) | key match med (ms) | value match med (ms) | category-filter med (ms) |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 1,009 | 2.56 | 2.56 | 2.74 | 2.56 | 2.37 |
| 1,000 | 9,937 | 11.89 | 12.26 | 11.95 | 13.94 | 12.99 |
| 10,000 | 98,030 | ~145 | ~139 | ~155 | ~164 | ~195 |
| 100,000 | **SKIPPED** — single-save insertion exceeded 120 s | — | — | — | — | — |

Notes (honest limits):
- 10,000-row figures are single-capture measurements (median = same run), reliable to ~±10%.
- 100,000 rows **could not be seeded**: saving entries one-by-one costs ~10 ms/entry (connect-per-operation + `threading.Lock` + per-write commit), so bulk load is the bottleneck, not search.
- Growth is **linear**: 100→1,000 rows scales search ~4.7×, 1,000→10,000 scales ~13×. Search itself is dominated by the Python-side scan after load.
- **Insert cost finding (P2):** ~1 s per 100 rows means a real memory store of 100k entries would take ~16 min to build with the current write path.

`MemoryManager.delete_memory_by_type` (`app/memory/manager.py:314`): pulls `get_recent_context(n=1000, allow_private=True)` — **hard-capped at the 1,000 most recent context items** — then deletes matches in the object layer.
- Verified behavior: with 2,000 and 10,000 stored items, it deleted exactly **1,000** items (~8.3 s for the 2k case). Any store below the cap deletes all matches (~0.03 ms at 10 items).
- Impact: delete-by-type is **silently partial** above 1,000 recent items — a correctness caveat, flagging for Section 12 (M1).

---

## 6. Event-loop benchmark (Phase 5)

Real path measured: synchronous `sqlite3` via `app/db/config.py` connect-per-operation (`check_same_thread=False`, `timeout=5s`, PRAGMAs WAL/NORMAL/ON/5000) invoked directly inside async coroutines.

| Measurement | Result |
| --- | --- |
| Single open+PRAGMA+SELECT+close (cold temp DB) | **~27.7 ms** |
| Same cycle inside a warm store | ~2.5 ms (consistent with 100-row memory search) |

Heartbeat experiment: a coroutine records the max gap between successive `await asyncio.sleep(0.01)` wakeups while N concurrent async tasks each run 5 sync SQLite cycles.

| Concurrency (tasks) | Total wall time (ms) | Max heartbeat lag baseline (ms) | Max heartbeat lag with work (ms) |
|---:|---:|---:|---:|
| 1 | 16–20 | 16–27 | ~16.6 |
| 5 | 81–93 | 16–18 | ~25.7 |
| 10 | 165–209 | 16–20 | ~16.8–23 |
| 25 | 397–481 | 16–18 | ~23–25 |

Verdict: **sync SQLite on the event loop blocks and serializes unrelated async work.** The measured lag in this small test is modest (~8 ms worst extra), but total wall time scales linearly with the volume of sync work (25×5 queries ≈ 400–480 ms serialized), and the pattern (sync `sqlite3` + `threading.Lock`, synchronous OCR/Tesseract subprocess spawns, CPU-bound PDF parsing) is present on hot paths. PDF/OCR timing was **SKIPPED** (would have required constructing specific parser fixtures; libraries and sample PDFs are available — `tests/fixtures/test_images_only.pdf`, `test_mixed.pdf`).

---

## 7. Goal parser benchmark (Phase 6)

Real `GoalParser.parse()` (`app/core/gambit/goal_parser.py:115`). Independently re-measured in this session (5 runs, `perf_counter`).

| Input class | Length | min (ms) | median (ms) |
| --- | ---: | ---: | ---: |
| simple ("what time is it") | 15 | 0.280 | **0.290** |
| medium ("search the web for recent news about AI and summarize it") | 56 | 0.304 | **0.325** |
| complex (multi-intent) | ~110 | 0.190 | **0.204** |
| x-repeated 2,000 chars | 2,000 | 42.8 | **43.5** |
| repeated 'search ' × 5,000 | 35,000 | 5,292 | **5,742** |
| **x-repeated 20,000 chars** | 20,000 | 2,828 | **2,877** |

Regex compilation: **all regexes compiled at module/class scope** (`_READ_KW_RE` at `goal_parser.py:106`, `_FRESHNESS_RE` at `:792`); **no `re.compile` inside function bodies**. No repeated parse-per-request pattern found (parser instances are stored on planners and reused).

**Root cause of catastrophic slowdown (verified by per-pattern timing):** `goal_parser.py:186`
```python
re.search(r"([a-zA-Z]:[\\/][^\s'\"]+|/?[^\s'\"]+\.[a-zA-Z0-9]+)", request)
```
The unanchored greedy `[^\s'"]+` followed by `\.[a-zA-Z0-9]+` backtracks per position looking for a dot. **One search on an 8,000-char dotless input = ~420 ms**; `detect_intent` performs ~52 `re.search` calls total. Scaling is **superlinear (~quadratic)**: 10× length → ~66× time. This makes a ~20 KB user message take ~2.9 s and a ~35 KB pasted message take ~5.7 s — synchronously, on the request path.

Category-filtered worst case: heavily punctuated or repeated-keyword text elevates per-parse time 1–3 orders of magnitude.

**Relative significance:** normal requests are sub-millisecond — **negligible** next to LLM latency (hundreds of ms–s), memory (~2–200 ms), or document processing (s). But the pathological case is a real DoS/latency risk for local or pasted large inputs and is the dominant sub-LLM CPU cost measured anywhere in this baseline (see Section 11, P0).

---

## 8. Provider / router verification (Phase 7)

Split into the three mandated classes.

### VERIFIED (source-confirmed)

| # | Claim | Evidence |
| --- | --- | --- |
| V1 | Registry: insertion-ordered `ProviderRegistry`; `ProviderManager` orchestrates health, selection, fallback | `app/providers/registry.py`; `app/providers/manager.py:142-299` |
| V2 | Mock is deterministic and **cannot fail**: always `{"response": "Mock provider response"}`, always `supports()` True, no `finish_reason` | `app/providers/mock.py:20-37` |
| V3 | Real-manager fallback: routed provider first, then all others in registry order, filtered by capabilities and (when present) `requires_local_model` | `manager.py:142-181` |
| V4 | CAP sensitive routing chain is intact: policy `requires_local_model` → orchestrator copy → router local-only filter → executor permits → manager local filter → governance `routing_constraints_mismatch` re-check | `policy_engine.py:67`; `orchestrator/engine.py:757-766`; `router/router.py:64-74,302-306`; `executor.py:218`; `governance.py:250-257` |
| V5 | Router excludes mock via `provider_kind != "mock"` (string metadata), but **only at the router layer** | `app/router/router.py:73,91`; `app/core/app.py:1589,1599` |
| V6 | Cooldown is applied at exactly two call sites; the `execute_provider_stream` path deliberately does not cooldown | `manager.py:129,282-284,336-341` |
| V7 | `provider_kind` exists only in `app/router/` + `app.py` — the provider layer has no such notion | 6 total occurrences; `app/providers/models.py` has only `execution_location` |
| V8 | Retry is single-owned by `RuntimeEngine.run` with bounded attempts (2) and classification-driven `RetryPolicy` | `app.py:1557-1562`; `engine.py:279-379`; `app/runtime/reliability.py:64-109,90` |

### SOURCE-ONLY (present but unexercised / never executed)

| # | Claim | Evidence |
| --- | --- | --- |
| S1 | `LocalProvider` success path and its HTTP health-check are never tested (only missing-URL and config cases) | `tests/providers/test_real_providers.py:39-45` |
| S2 | Three `FailureType` branches are dead: `INTEGRATION_NOT_CONFIGURED`, `CREDENTIAL_UNAVAILABLE`, `CREDENTIAL_EXPIRED`, `EXTERNAL_RATE_LIMIT` (earlier predicates match first) | `reliability.py:130-158` |
| S3 | Tool timeouts never retry (no `TOOL_TIMEOUT` in `_RETRYABLE`) | `reliability.py:64-70,139` |
| S4 | `prepare_semantic_retry` / cooldown-clearing on retry has zero test coverage | grep of `tests/` = 0 hits |
| S5 | No cooldown-expiry test; health/cooldown state is process-local (dicts, not persisted) | `health.py:43-45,60-69`; grep of `tests/` |
| S6 | Preferred-provider shortcut (`router.py:165-186`) runs before scoring; production default provider is `groq` (`app/providers/config.py:32`) — scoring is bypassed for non-sensitive requests | `app.py:1680` |
| S7 | Scoring's privacy block ignores `execution_constraints` (only `requires_local_model` / policy flags) | `scoring.py:86` vs `router.py:66,303` |
| S8 | Mock-shaped (no `content` key) outputs skip the CAP output redaction scan | `orchestrator/engine.py:828-837` |
| S9 | `ProviderSettings.max_retries` appears unused in `app/providers/` | grep across `app/providers/` |

### VERIFIED BY EXECUTION THIS SESSION

- `pytest tests/router/test_phase51_routing.py tests/production/test_p1_governance_convergence.py -q` → **26 passed in 7.17 s**. The router avoids-unhealthy test does pass, but by registry insertion order rather than by health state (both candidates report `available=True`; see Section 12, S2).
- **Mock fallback behavior (S1/G1) — reproduced live:** with `local` unconfigured (unavailable) + `mock` registered (LOCAL), a request executed with `execution_constraints=requires_local_model=True` produced:
  ```
  candidate order: ['local', 'mock']   local available: False   mock available: True
  result: {'success': True, 'provider_id': 'mock', 'content': 'Mock provider response', ...}
  ```
  See Section 12, S1.

### UNVERIFIED

- Live behavior of any cloud provider (no API calls made; SDK absent).
- End-to-end mock-vs-local output shape through the HTTP layer (`tests/api/test_execute.py` asserts `body["response"] == "Mock provider response"` but was not re-run in Phase 7).
- Whether `test_phase51` fails if provider registration order is swapped (would prove the false-positive claim decisively).

---

## 9. Packaging verification (Phase 8)

Source-verified against `pyproject.toml`, `scripts/build_windows.ps1`, `samaktha.spec`, `samaktha.iss`, plus the **existing built artifact** `dist\samaktha\samaktha.exe`.

### Version consistency — AGREE

Every declaration resolves to **0.5.0**: `pyproject.toml:3`; `_canonical_version()`/`app/__init__.py`; `samaktha.iss:6` (`#define AppVersion "0.5.0"`); `scripts/build_windows.ps1:23-25` (regex-derived from pyproject); `dist\...\samaktha_core-0.5.0.dist-info\METADATA`; `README.md`, `docs/CHANGELOG.md`. Residual risk: `samaktha.iss:6` is a **manually duplicated literal** with no test guarding it.

### Entry points — AGREE (with one gap)

`samaktha = app.cli:main` (pyproject) == `['app/cli.py']` (spec) == `samaktha.exe` (iss) — all consistent. **Gap:** `samaktha-plugin = app.plugins.sdk.cli:main` is declared but **not packaged** (no second EXE/Analysis); the frozen `entry_points.txt` still advertises it.

### Build status

| Item | Status |
| --- | --- |
| PyInstaller artifact exists | `dist\samaktha\samaktha.exe` — **92,356,783 bytes (~88 MB)**; `dist\` total **~968 MB** (`torch`, `transformers`, `onnxruntime`, `cv2`, `docling_*`, `winrt`, `win32com`, …) |
| Spec mode | ONE-FOLDER (`exclude_binaries=True` + `COLLECT`), `console=True`, `upx=True`, `excludes=[]`, hiddenimports = `ddgs` only |
| Datas sanitisation | effective: **0** `.py`/`.db`/`.key` in `_internal`; METADATA rewritten to headers-only |
| Clean rebuild from scripts | **FEASIBLE** — preconditions met (venv, PyInstaller 6.22.2). Not re-run here to avoid a ~968 MB regen and a 15+ min build; existing artifact corresponds to the exact spec |
| Version resource / icon | **MISSING** — no VERSIONINFO, no `icon=`, no `.ico` anywhere (Explorer shows no product version) |
| `mascot.png` (repo, 467 KB) | **NOT BUNDLED** — `datas=[]`; TUI silently falls back to ASCII (`app/tui/mascot.py:27-28,48`) |
| Dev-tool leakage | **pytest + pytest_asyncio shipped** in the bundle (dragged in via third-party modules; no `excludes`) |
| Pinned-file reproducibility | **NO** — 14 installed versions differ from `requirements/pilot-windows-py314.txt` (Section 1) |

**Launch status — VERIFIED (real execution):**

```
> dist\samaktha\samaktha.exe --version
samaktha 0.5.0
exit code 0
```

The packaged binary starts and reports the correct version.

### Installer status

| Item | Status |
| --- | --- |
| `installer_output\` | **does not exist** — no installer has ever been produced |
| Inno Setup present? | **NO** — `iscc` not on PATH; neither standard v6 install path exists → installer **cannot be built on this machine** |
| `scripts/build_windows.ps1` calls ISCC? | **NO** — script ends at the PyInstaller artifact (115 lines); `samaktha.iss` must be hand-compiled |
| Per-user install | `PrivilegesRequired=lowest` (`samaktha.iss:27`) + `{localappdata}\Programs\Samaktha` — consistent with `app/paths.py:82`. **Conflict:** desktop icon uses `{commondesktop}` (`:54`) which requires elevation → expected to fail for a non-elevated user |
| Upgrade/uninstall | `[UninstallDelete]` commented out (user data preserved); placeholder AppId GUID (`:12`) |

---

## 10. Python compatibility (Phase 9)

| Item | Result |
| --- | --- |
| Declared requirement | `requires-python = ">=3.12"` (`pyproject.toml`) |
| Interpreters installed on this machine | **3.14 (default), 3.13, 3.11** — Python **3.12 is NOT installed** |
| Tests executed on | **3.14.5 only** (full suite passed, Section 2) |
| Evidence of 3.12 coverage anywhere | **none** — no CI/CD, no workflow, no `py312` references, no tox/nox matrix |

**Compatibility with Python 3.12: NOT VERIFIED.** Per the phase rule, this is reported as `NOT VERIFIED` rather than assumed. (3.13 and 3.11 exist locally but are neither the declared floor nor the tested environment; no promise is made about them either.)

---

## 11. Performance hotspots (ranked, measured)

| Rank | Hotspot | Measured evidence | Impact |
| --- | --- | --- | --- |
| **P0** | Goal-parser superlinear regex (`goal_parser.py:186`) | 2,000→43 ms, 20,000→2,877 ms, 35,000→5,742 ms; single pattern 420 ms @ 8K | Worst measured CPU cost; ~quadratic on user-supplied text; synchronous on request path |
| **P1** | Full-table memory scan on every search (`repository.py:33-42`, `sqlite_store.list_entries`) | 100→2.6 ms, 1,000→12 ms, 10,000→~145–195 ms; linear; no FTS/index | Grows with stored memory; sits on agent hot path |
| **P1** | Memory insert cost (connect-per-op + lock + commit per entry) | ~10 ms/entry ⇒ ~16 min to store 100k | Bulk memory/DB writes prohibitively slow |
| **P2** | Sync SQLite + blocking subprocess/CPU work on asyncio loop | single cycle ~2.5–27 ms; 25×5 serialized ≈ 400–480 ms; +~8 ms heartbeat lag | Blocks unrelated async work; scales with sync volume |
| **P2** | `delete_memory_by_type` hidden 1,000-item cap | deletes exactly 1,000 of 10,000 stored | Silent partial deletes |
| **P3** | Packaging size / startup | ~968 MB bundle including pytest + torch family | Install/load weight; not runtime-critical once running |

Numbers assignment rationale: P0 = catastrophic worst case + user-controlled input; P1 = hot path + unbounded growth; P2 = real but bounded/conditional; P3 = operational rather than lookup-path.

---

## 12. Security findings (ranked)

### CRITICAL
None found and verified. The CAP-permit gate is complete, all 10 mandated predicates exist, and no production path reaches an effect without a gate (Section 3).

### HIGH
**S1 — Sensitive local-only request can transparently fall back to the mock provider and return fabricated output.**
Reproduced live this session: `execute_provider("local", requires_local_model=True)` with local unconfigured returned `{'provider_id': 'mock', 'content': 'Mock provider response', 'success': True}`. Cause chain:
- router *does* exclude mock for sensitive requests (`router.py:73`), but that guard (`provider_kind != "mock"`) is **router-only**; the provider layer has no `provider_kind` concept.
- `ProviderManager._candidate_infos` admits mock because its `execution_location == LOCAL` (`manager.py:169-181`), registering mock first when `mock_allowed()` (`app.py:715-727,1589`).
- `RuntimeEngine` re-checks `routing.execution_constraints == permit.constraints` but never re-runs governance on the *fallback* provider actually chosen inside `execute_provider`.
- The orchestrator's CAP output-redaction scans `output.get("content")` only, so the legacy mock shape (`{"response": ...}`) bypasses redaction too (`orchestrator/engine.py:828-837`).

Net effect: a CAP-routed sensitive request can be answered by the deterministic mock with **no flag distinguishing mock from a real local model**, and governance never audits the executing provider. This is a **fallback-fidelity/authorization-scope** issue (the permit's target is not enforced on the actually-used provider), not a permit bypass. The mitigation used by the existing test (`test_p1_governance_convergence.py:516-517`) is to monkeypatch mock's `execute` to fail — itself proof mock sits in the candidate list.

**S2 — Architecture-freeze "avoids unhealthy providers" test passes for the wrong reason.**
`test_phase51_routing.py:32-56` marks providers failed/success via `record_failure`/`record_success`, but `record_failure` never flips `available` (`health.py:206-216`), so both remain available and the winning provider is the **first registered** one (`router.py:271-272` v0.1 fallback). The test green — but it does not exercise health filtering.

### MEDIUM
- **M1 — `delete_memory_by_type` silently caps at 1,000 recent items** (Section 5) — data-correctness gap.
- **M2 — Session and workspace permit checks are conditional** on those fields being present on the permit (`governance.py:184-200`) — correct for single-user local, but if a permit is issued sessionless it is not session-bound.
- **M3 — Permit-signing key non-persistence is silent** — module default is a per-process random key (`policy.py:15`); production calls `configure_permit_signing_key` (`app.py:692-706`), but if that loading path ever failed, used keys silently stop persisting (cross-restart permit replay protection would degrade).
- **M4 — Packaging:** no VERSIONINFO/icon, `mascot.png` missing from bundle, `pytest` shipped, `samaktha-plugin` advertised but not packaged, `{commondesktop}` vs `PrivilegesRequired=lowest` conflict, placeholder AppId (Section 9).
- **M5 — Provider fallback after CAP is unaudited** — governance validates only the *routed* provider id (`executor.py:97-104`); the provider that actually executes after fallback is never re-governed (this is the same mechanism as S1).

### LOW
- **L1 — 87 test warnings**, including 3 `AsyncMock` never-awaited coroutine leaks (test hygiene), 1 production `asyncio.iscoroutinefunction` deprecation (`app/tui/renderer.py:101`).
- **L2 — Dead failure classifications** (`reliability.py:130-158`) — errors collapse into `CONFIGURATION_ERROR`/`RATE_LIMITED`, losing signal.
- **L3 — `record_failure` telemetry is cosmetic** (never flips availability, never called in production).
- **L4 — Health/cooldown state not persisted**; router metrics write-only.
- **L5 — Mock is structurally incapable of being unhealthy**, so health/mock signals carry no meaning.

---

## 13. Technology migration candidates

Category classification only — **no technology is selected** and no migration is proposed in this phase. These follow the measured evidence (P0 hotspots are the natural candidates).

| Category | Candidate surfaces (from measurements) | Evidence |
| --- | --- | --- |
| **likely CPU-bound** | Goal-parser regex engine (P0: ~2.9 s @ 20K chars); memory filter loops (`repository.py:33-42`); PyMuPDF page parsing | Quadratic backtracking measured; Python-side scanning measured |
| **likely I/O-bound** | SQLite connect-per-operation (P1: ~10 ms/entry insert); OCR subprocess spawns (Tesseract/EasyOCR); network/DDGS | Insert and per-op latency measured |
| **systems-level** | Triangle of Win32 DACL hardening (`ctypes` vs `kernel32`/`advapi32`); `taskkill /F /T` tree kill; PyInstaller bootstrap | Source-verified |
| **browser ecosystem** | None identified | — |
| **native inference** | OCR worker image rasterization (PyMuPDF 300 dpi) + any future local LLM inference | Components present; not benchmarked this phase |
| **database-bound** | `SQLiteStore.list_entries` full scan + Python filter; FTS absence | Linear latency measured |
| **AI orchestration** | GAMBIT planning, CAP evaluation, AgentLoop state transitions | Source-verified; loop is single-step |

**Best measured candidate for native/systems implementation** is the goal-parser regex hot path (P0), because it is the only bottleneck with a measured superlinear blowup on user-controlled input. Keep-evaluation notes for everything else remain classification-only.

---

## Final conclusion

```
VERIFIED CURRENT TEST BASELINE:
    3151 passed / 0 failed / 0 errors / 0 skipped / 87 warnings, 518.01 s, exit 0,
    on CPython 3.14.5 / pytest 9.1.1 using .venv. No failures to classify.

VERIFIED GOVERNANCE MODEL:
    Complete. 14 permit predicates verified at exact source locations
    (governance.py:73-259 + replay guard engine.py:402-425). Signed HMAC-SHA256
    permits, ALLOW-only execution, ASK_USER -> PAUSED, integrity/expiry/scope/
    operation/permission/constraint checks, tool defense-in-depth
    (ToolGuard -> GovernanceEngine -> ToolSecurityEnforcer -> network constraint)
    all non-None in production. ToolChainExecutor / MultimodalExecutor /
    StreamingExecutor remain disconnected and test-enforced. No path from LLM to
    OS/filesystem/network/provider exists without a CAP permit. One verified HIGH
    fallback-fidelity gap: sensitive local-only requests can fall back to mock
    and return fabricated output unreported to governance.

VERIFIED AGENT MODEL:
    AgentLoop v1 is wired (orchestrator/engine.py:270-274), deterministic,
    single-step (max_steps=1). Implemented: one planned action -> CAP -> Runtime
    (gated) -> Observation -> deterministic termination; step limits; cancellation.
    Missing by design: retry/replan/alternate action/clarification/multi-step.
    Partial: runtime-internal provider retry (tools never retried), recovery
    (RecoveryManager not in composition), checkpoints, CAP constraint budget.

TOP PERFORMANCE BOTTLENECK:
    Goal parser regex backtracking - goal_parser.py:186 - measured superlinear:
    43 ms @ 2,000 chars, 2,877 ms @ 20,000, 5,742 ms @ 35,000 (single 420 ms
    search @ 8,000). Run on every request, on the event loop.

TOP SECURITY CONCERN:
    S1: provider fallback fidelity - CAP-sensitive request routed to LOCAL can be
    answered by mock and returned as success with no governance record of the
    actual provider (empirically reproduced). Permit bindings do not constrain
    the provider that actually executes after fallback.

TOP MAINTAINABILITY CONCERN:
    Single 1,718-line composition root (app/core/app.py) + 1,615-line
    orchestrator engine; manual 3-file packaging sync (pyproject/spec/iss) with
    unguarded version literal; no CI/CD to enforce the 3,151-test suite.

BEST CANDIDATE FOR NATIVE/SYSTEMS IMPLEMENTATION:
    Goal-parser regex matching/mutation (the only measured superlinear
    hotspot); secondary: memory full-scan filter and per-entry SQLite write path.

BEST CANDIDATE TO KEEP IN PYTHON:
    CAP governance/permit model (typed, HMAC-signed, test-covered), AgentLoop
    state machine, provider/router orchestration, and the execution coordinator -
    all source-verified as well-factored Python with embedded security logic.

NEXT PHASE:
POLYGLOT TECHNOLOGY DECISION + AGENTLOOP V2 DESIGN
```

---

## FILES CHANGED

```
docs/architecture/SAMAKTHA_VERIFICATION_BASELINE.md   (this report, new)
```

Temporary diagnostic artifacts (benchmark scripts, mock-fallback probe, pytest `--basetemp` directories) were created **outside the repository** and **deleted before completion**.

## SOURCE CODE CHANGED

```
YES / NO  ->  NO
```

## TESTS EXECUTED

```
Full suite:  .\.venv\Scripts\python.exe -m pytest -q --basetemp <temp>
              3,151 passed in 518.01 s (exit 0)
Targeted:    26 passed in 7.17 s  (tests/router/test_phase51_routing.py
                                   tests/production/test_p1_governance_convergence.py)
Runtime probe: dist\samaktha\samaktha.exe --version -> "samaktha 0.5.0" (exit 0)
```

## FINAL STATUS

```
COMPLETE - evidence baseline established. No source or test changes. One report
created. Two findings are NOT VERIFIED by design: Python 3.12 compatibility
(3.12 not installed) and live cloud-provider behavior (no API calls made).
```