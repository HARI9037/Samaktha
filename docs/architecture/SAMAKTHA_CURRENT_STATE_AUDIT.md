# Samaktha — Current State Audit

**Scope:** what Samaktha is *today*, evidenced from this repository.
**Method:** read-only inspection of source, configuration, tests, and packaging manifests.
**Explicitly out of scope:** redesign, migration, rewrite, or recommendation of replacement technology. Nothing in this document proposes Rust, Go, TypeScript, WebAssembly, a new framework, or a replacement architecture.

Every substantive claim below carries one of these labels:

| Label | Meaning |
| --- | --- |
| `IMPLEMENTED` | Code exists and is wired into the production composition. |
| `PARTIAL` | Code exists, but integration, coverage, or error handling is incomplete. |
| `DOCUMENTED ONLY` | Described in docstrings, docs, or comments; not verifiable as working behavior in code. |
| `PLANNED` | Intended future direction per existing repository documents. |
| `MISSING` | Referenced or expected, but absent from the repository. |
| `UNKNOWN` | Not established from current repository evidence. |

A caveat that applies to the whole document: no full test suite run and no live provider/API/external-binary invocation was performed during this audit. Behavior claims are derived from source reading and test collection only. Line numbers are from this audit pass and will drift as code changes.

---

## 1. What Samaktha Is

`IMPLEMENTED`

Samaktha is a single-user, local-first AI agent application written in Python. It presents a Textual terminal user interface and an optional FastAPI HTTP backend. It accepts natural-language goals, parses them into intents and plans, decides which capabilities to use, evaluates every consequential action against a policy/approval system, and then executes provider (LLM) calls and local tool invocations.

It is a personal agent runtime with a real governance layer, not a chat wrapper: the codebase contains a genuine deterministic policy engine, approval workflow with remembered permissions, cryptographic permit signing, action-level permission scoping, and an architecture-freeze test suite that explicitly tracks known bypasses.

It is not currently a distributed, multi-tenant, or cloud service. There is no authentication layer, no multi-user isolation, no scheduler service, and no message queue. Session identity is a fixed local principal constant.

## 2. Language and Technology Inventory

`IMPLEMENTED`

Measured over tracked files:

| Measure | Count |
| --- | --- |
| Tracked files (total) | 778 |
| Python files (`.py`, total) | 724 |
| Application Python files (`app/**/*.py`) | 442 |
| Test Python files (`tests/**/*.py`) | 275 |

Non-Python tracked implementation and configuration files:

| File | Purpose |
| --- | --- |
| `scripts/build_windows.ps1` | PowerShell build driver |
| `samaktha.spec` | PyInstaller packaging specification |
| `samaktha.iss` | Inno Setup installer definition |
| `pyproject.toml` | Package metadata, dependencies, tooling config |
| `config/settings.toml` | Runtime configuration |
| `config/capability_state.json` | Persisted capability/approval state |
| `config/checkpoint_integrity.json` | Checkpoint integrity metadata |
| `config/permit_signing.key` | HMAC permit-signing secret material |

`IMPLEMENTED` — no tracked Rust, Go, TypeScript, JavaScript, C/C++, Java, or WebAssembly source files exist. The implementation language is Python. There is no frontend build toolchain, bundler, or Node manifest.

`MISSING` — no CI/CD pipeline. There is no `.github` directory and no other tracked pipeline definition. All verification is local and manual.

## 3. Interpreter and Environment

`IMPLEMENTED`

- `pyproject.toml` declares `requires-python = ">=3.12"`.
- The checked-in virtual environment runs **CPython 3.14.5** on Windows (`pyvenv.cfg` points to `C:\Python314\python.exe`, `include-system-site-packages = false`).
- `requirements/pilot-windows-py314.txt` pins a resolved dependency set for Windows on CPython 3.14. It is a dependency lock for a pilot configuration, **not** an application manifest, and it is not used as an installer input.

`PARTIAL` — the supported floor (3.12) and the environment in use (3.14) diverge by two minor releases, and no automation enforces testing on the declared floor. The repository has no evidence of test execution on 3.12.

## 4. Packaging and Dependency Management

`IMPLEMENTED`

- `pyproject.toml` declares project `samaktha-core`, version `0.5.0`.
- Build backend is Hatchling; wheel packaging is declared there.
- Pytest configuration lives in `pyproject.toml`.
- Two console scripts are declared, including `samaktha` and a `samaktha-plugin` entry point.
- Notable dependency groups: FastAPI and Pydantic for the HTTP surface, Textual for the TUI, document/OCR stack (PyMuPDF, pdfplumber, pypdf, Docling, OCR), networking clients, Windows-specific packages, and voice/audio packages.

`PARTIAL` — Windows packaging is assembled from three separate artifacts that must stay manually consistent: `scripts/build_windows.ps1`, `samaktha.spec`, and `samaktha.iss`. There is no test asserting they agree (for example, that the version in `pyproject.toml` matches the Inno Setup `AppVersion`, or that the spec bundles every runtime dependency).

`UNKNOWN` — whether the packaged build actually launches and passes a smoke test on a clean machine. No build, packaging test, or installer test exists in the repository, and none was run.

## 5. Distribution

`IMPLEMENTED`

Windows desktop distribution via PyInstaller in `ONEDIR` layout, driven by `scripts/build_windows.ps1`, with Inno Setup producing an installer from `samaktha.iss`.

`MISSING` — no code signing, no installer upgrade path, no uninstall verification, no multi-platform packaging (no macOS or Linux build definitions).

## 6. Entry Points and Composition Root

`IMPLEMENTED`

`main.py` is a thin shim that delegates to `app.cli:main`. Default invocation launches the TUI; the CLI also exposes backend-server mode and diagnostic commands.

`app/core/app.py` is the composition root. It is **1,718 lines / ~76 KB** and constructs essentially the entire application: CAP components, GAMBIT planning, orchestrator, providers, memory, tools, runtime, security, and personality. This single function is where the real system wiring is expressed.

`PARTIAL` — a 1,718-line composition root is a maintainability and reviewability concern. It is also the reason architectural intent is hard to enforce: the freeze test in Section 21 exists partly because this one function decides what is live.

## 7. Primary Runtime

`IMPLEMENTED` — Python 3.12+, asyncio throughout the request path, with a FastAPI HTTP surface and a Textual TUI. Windows is the supported deployment target and Windows-specific native API use is present (see Section 24).

## 8. Supported Platforms

`IMPLEMENTED` — Windows is the target, evidenced by the PowerShell build script, Inno Setup installer, Windows dependency set, and native Windows API hardening calls.

`UNKNOWN` — macOS and Linux behavior. Platform-gated code exists, but there is no packaging definition and no test evidence for non-Windows operation.

## 9. Architecture Overview

`IMPLEMENTED`

Samaktha is a layered, policy-gated pipeline. A user message becomes a pipeline state; intent is parsed; a plan is produced; every resulting action is proposed to CAP; CAP returns a decision and an optional signed permit; the runtime validates the permit; only then does a provider call or tool run.

Layers, from the outside in:

1. **Interface** — Textual TUI (`app/agent/production.py` adapter) or FastAPI backend.
2. **Execution coordinator** — `app/core/execution_coordinator.py` (862 lines / ~38 KB): lifecycle, locking, concurrency limits, checkpoints, cancellation, approvals, events.
3. **Orchestrator** — `app/core/orchestrator/engine.py` (1,615 lines / ~78 KB): the main engine driving planning → CAP → runtime → response.
4. **CAP (policy/approval)** — `app/core/cap/`: policy engine, approval engine, context engine, privacy classifier, ambiguity resolver, permission store.
5. **GAMBIT (planning)** — `app/core/gambit/`: goal parser, planner, task decomposer, capability selection.
6. **Runtime** — `app/runtime/`: engine, governance permit gate, dispatcher, executors, checkpoints, recovery, parallel scheduler.
7. **Providers** — `app/providers/`: Groq, OpenAI, OpenRouter, local, mock; `app/router/router.py` for selection.
8. **Tools** — `app/tools/`: 18 registered tools.
9. **Memory** — `app/memory/`: SQLite-backed long-term and session memory.
10. **Governance/security** — `app/governance/engine.py`, `app/security/tool_guard.py`.

## 10. System Context

`IMPLEMENTED`

Samaktha runs locally as one process on one machine under one user account. It talks outbound to LLM providers over HTTPS, optionally performs web search (DDGS), optionally invokes local OCR binaries, and optionally sends email. It stores durable state in a local SQLite database plus several JSON config files and a local signing key.

Trust boundaries: user input (untrusted), LLM provider output (partially trusted — it proposes actions, it does not authorize them), local filesystem and shell (privileged, must be gated), and external services (email, search).

## 11. Component Map

`IMPLEMENTED`

| Component | Path | Size / shape | Status |
| --- | --- | --- | --- |
| Composition root | `app/core/app.py` | 1,718 lines | `IMPLEMENTED` |
| Orchestrator engine | `app/core/orchestrator/engine.py` | 1,615 lines | `IMPLEMENTED` |
| Execution coordinator | `app/core/execution_coordinator.py` | 862 lines | `IMPLEMENTED` |
| Goal parser | `app/core/gambit/goal_parser.py` | 867 lines | `IMPLEMENTED` |
| Runtime governance (CAP gate) | `app/runtime/governance.py` | 270 lines | `IMPLEMENTED` |
| Runtime engine | `app/runtime/engine.py` | runtime pool, retries, workers, recovery, scheduling, checkpoints | `PARTIAL` |
| Runtime parallel runtime | `app/runtime_parallel/` | scheduler, dependency graph, worker pool, resource allocation, recovery, aggregation | `IMPLEMENTED` (see Section 21 note) |
| Memory repository | `app/memory/repository.py` | 42 lines | `IMPLEMENTED` |
| Memory search | `app/memory/search.py` | 19 lines | `IMPLEMENTED` |
| SQLite store | `app/memory/sqlite_store.py` | 103 lines | `IMPLEMENTED` |
| DB connection config | `app/db/config.py` | 69 lines | `IMPLEMENTED` |
| Tool chain executor | `app/runtime/tool_chain.py` | 177 lines | `PARTIAL` — implemented, **not** in production composition |
| Streaming executor | `app/runtime/streaming.py` | 137 lines | `PARTIAL` — implemented, **not** in production composition |
| Multimodal executor | `app/runtime/multimodal.py` | ~153 lines | `PARTIAL` — implemented, **not** in production composition |
| Tool chain freeze guard | `tests/architecture/test_p0_architecture_freeze.py` | 744 lines | `IMPLEMENTED` |

## 12. Primary Runtime Flow (TUI)

`IMPLEMENTED`

Traced path, with file evidence:

1. Textual TUI receives user input and calls the production agent adapter.
2. `app/agent/production.py` — `ProductionAgentRuntime.handle_message` (line 91) creates an execution id `tui-<uuid4hex>` and an `asyncio.Queue`, then calls the coordinator.
3. `ProductionAgentRuntime.__init__` (lines 58–67) obtains the orchestrator via `create_orchestrator()` and reuses `orchestrator.execution_coordinator` for **every** message and approval, so one composition is shared across the session.
4. `app/core/execution_coordinator.py` — `start_execution(user_input, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID, session_id=..., source="tui", streaming=True, wait=True, event_bus=bus, execution_id=...)`.
5. Coordinator → orchestrator → GAMBIT planning → CAP proposal/approval → runtime.
6. Streaming tokens arrive as `RuntimeEventType.TOKEN` events on a per-session `RuntimeEventBus`; the adapter's `on_event` callback (lines 100–109) pushes token text into the output queue, so tokens are rendered live.
7. If no token was observed, `_enqueue_runtime_result` (lines 33–47) emits the final result as provider text or tool output.
8. If the state is `awaiting_approval`, the adapter fires `AgentEvent.PAUSE_REQUESTED` with the approval reason and metadata (lines 131–148).
9. `ProductionAgentRuntime.resume` (line 163) calls `coordinator.submit_approval(...)` with a decision defaulting to `deny`.
10. `ProductionAgentRuntime.cancel` (line 219) calls `coordinator.cancel_execution(...)`.

The adapter explicitly owns no pipeline state and no provider execution path; it only renders canonical events. This is a clean separation and is verified by its own docstrings.

## 13. Primary Runtime Flow (HTTP backend)

`IMPLEMENTED` — a FastAPI application is composed in `app/core/app.py` and served via `app.cli`. It exposes the same orchestrator path.

`UNKNOWN` — I did not enumerate every HTTP route, its authentication posture, request schema, or error contract in this pass. Route-level coverage should be confirmed before relying on the backend in any multi-user context. See Section 25.

## 14. CAP: Policy and Approval Layer

`IMPLEMENTED`

This is the most substantive subsystem in the repository and the clearest differentiator from a typical agent codebase.

`app/core/cap/` contains a deterministic policy engine (`policy_engine.py`) that evaluates intent, resource, risk, and permission state into a decision; an approval engine (`approval_engine.py`) that handles ask-user flows and remembered permissions; plus a context engine, privacy classifier, ambiguity resolver, and permission store.

The canonical enforcement point is `enforce_cap_permit` in `app/runtime/governance.py`. This is the function the architecture freeze test treats as the governed boundary: `ProviderExecutor` is described in the freeze test as "the governed provider execution boundary" and as performing "governed token streaming after permit validation".

Observed behavior of the gate: it requires an approved task carrying a permit, and it checks the permit's integrity, validity window, and scope (principal/subject, session, workspace, action, and operation identity) before allowing execution. `PARTIAL` — I did not re-verify the exhaustive check list line-by-line in this pass; the exact set of scope predicates should be confirmed against `app/runtime/governance.py` before this gate is described as security-complete.

Tool execution is defended in depth: the runtime's `ToolExecutor` layers a CAP network-constraint check, `ToolGuard` prechecks (`app/security/tool_guard.py`), `GovernanceEngine.enforce_tool`, and `ToolSecurityEnforcer.validate`.

The TUI shell route is also governed: `/delete-session` in `app/shell/command_router.py` (lines 398–425) routes through `_approve_delete` and handles `DENY`, `ASK_USER` (pending confirmation), and `ALLOW`/remembered-permission outcomes. Its module docstring states the router never talks to the orchestrator and that `/delete-session` is the single exception that passes through real CAP.

## 15. Planning Subsystem (GAMBIT)

`IMPLEMENTED`

`app/core/gambit/goal_parser.py` parses natural-language goals into intents and complexity signals. `planner.py` builds plans, decomposes them, selects capabilities, and integrates adaptive replanning. `task_decomposer.py` maps intents to plans.

`PARTIAL` — `goal_parser.py` is 867 lines / ~42 KB and is dense with regular expressions. Regex compilation and matching strategy were not audited in detail in this pass; this file is a plausible source of both latency and false-positive intent classification and deserves a focused review.

## 16. Runtime Engine and Parallel Execution

`IMPLEMENTED`

`app/runtime/` provides the execution engine with a runtime pool, retries, worker management, recovery, scheduling, and checkpointing. `app/runtime_parallel/` provides a dependency-aware scheduler, worker pool, resource allocation, recovery, and aggregation.

The freeze test records an explicit, deliberate finding here: `runtime_parallel` was **reverified as a live `RuntimeEngine.run_batch` dependency, not as an isolated future library**, and classifies it `CANONICAL_RUNTIME_INTERNAL`. This is worth stating plainly because the presence of a second parallel-execution layer invites the assumption that it is unused. Per the repository's own architecture guard, it is used.

`app/workflow/engine.py` provides dependency-aware parallel workflow execution.

## 17. AgentLoop

`IMPLEMENTED`

`app/core/agent_loop.py` implements a deliberately minimal loop: it executes **exactly one already-planned action** and terminates. It is not an autonomous iterate-until-done loop. `app/core/contracts/agent_loop.py` defines the typed state, observation, verification, failure, transition, and termination models. `tests/runtime/test_agent_loop_v1.py` covers this v1 behavior.

The orchestrator's own step function (`app/core/orchestrator/engine.py`, around lines 233–274) likewise runs with `max_steps=1`, and `apply_observation` does not retry or replan.

`IMPLEMENTED` as a design property, and it is the correct reading of the code: **Samaktha currently performs single-step execution, not open-ended autonomous iteration.** Any description of it as a self-directing agent loop that runs until the goal is met overstates the implementation. Iterative refinement is `PLANNED`/absent, not present.

## 18. Provider Layer

`IMPLEMENTED`

Providers implemented: Groq, OpenAI, OpenRouter, local, and mock (`app/providers/groq_provider.py`, `openai_provider.py`, `openrouter_provider.py`, `local_provider.py`, `mock.py`). `app/providers/manager.py` provides the registry with health tracking, selection, retry, and cooldown handling. `app/router/router.py` performs capability scoring and health-aware model selection.

`config/settings.toml` enables Groq and DDGS search by default.

`PARTIAL` — no live provider call was made during this audit. Retry counts, timeout values, rate-limit handling, and streaming chunk behavior are unverified against real endpoints. Provider secrets are expected to come from the environment; `PARTIAL` — this audit did not confirm that no secret is committed to the repository.

## 19. Tool Layer

`IMPLEMENTED`

18 tools are registered in the production composition in `app/core/app.py`:

`resolver`, `filesystem`, `document`, `pdf`, `image`, `memory`, `windows`, `internet`, `shell`, `clipboard`, `notification`, `reminder`, `notes`, `tasks`, `contacts`, `calendar`, `email`, `message`.

Registration uses explicit tool ids, categories, capability lists, permissions, approval flags, supported actions, and policies. Example: the `email` tool is registered with `category="communication"`, `permissions=["read", "write", "network"]`, `approval_required=True`, and `supported_actions=["compose", "draft", "send"]`, with a comment explaining that `SEND` stays advertised even when SMTP is absent so Runtime can return a truthful setup-required result rather than silently substituting `DRAFT`. That is a good pattern: the metadata honestly describes capability rather than overstating it.

`app/tools/shell.py` executes **structured argv** via `asyncio.create_subprocess_exec` against an allowlist, with a minimal environment, output bounds, and timeouts — not string-interpolated shell invocation.

`PARTIAL` — `email` and `message` are registered, and the freeze test states that production registers local email/message *tools* while `CommunicationManager` delivery stays disconnected. Actual outbound email/message delivery capability is therefore `UNKNOWN` pending credential and integration verification.

## 20. Memory Subsystem

`IMPLEMENTED`

SQLite-backed long-term memory with a `MemoryStore` protocol, `SQLiteStore`, `MemoryRepository`, `MemoryManager`, and a controller/facade layer (`app/memory/controller/facade.py`) that provides the controlled public API.

All SQLite access is centralized in `app/db/config.py`, which resolves the database path from `Settings.sqlite_url`, applies shared PRAGMAs, and implements a documented **connect-per-operation** lifecycle: `connect()` (lines 52–69) creates the parent directory, opens a connection with `check_same_thread=False` and a 5-second timeout, then applies `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`. The module docstring names itself the single source of truth so that file location and reliability settings cannot drift between the long-term memory, session memory, productivity, and scheduler stores. This is good design and is worth crediting.

**Two concrete findings in this subsystem:**

**Finding M1 — full-table scan on every memory search.** `MemoryRepository.search` (`app/memory/repository.py`, lines 33–42) calls `self._store.list_entries()` — a full read of every memory entry — and then filters with Python substring matching:

```python
entries = self._store.list_entries()
matches = []
query_lower = query.lower()
for entry in entries:
    if (not query or query_lower in str(entry.value).lower() or query_lower in entry.key.lower()):
        if (category is None) or (entry.category == category):
            matches.append(entry)
```

There is no SQL `LIKE`, no index use, and no SQLite FTS table. Cost grows linearly with total stored memory on every search, and this sits on the agent's hot path. `app/memory/search.py` (19 lines) performs the same kind of Python-side matching and deterministic sorting.

**Finding M2 — unbounded `n=1000` retrieval in a delete path.** `MemoryManager.delete_memory_by_type` obtains recent context with a large fixed bound and then filters in Python, meaning a type-scoped delete can pull a thousand rows to find its matches.

`PARTIAL` — FTS or indexed search is not implemented. `UNKNOWN` — actual memory volume in real use; the severity of M1 grows with it.

## 21. Security Posture

`IMPLEMENTED`

Governance is real and layered:

- Deterministic CAP policy evaluation with risk and permission inputs.
- Approval engine with ask-user flow and remembered permissions.
- Cryptographically signed permits: `config/permit_signing.key` holds 32 bytes of secret material; permits carry an integrity digest checked by the runtime gate, so a permit cannot be forged or edited in transit between CAP and the runtime.
- Action-level permission scoping with supported-action allowlists per tool.
- Tool-layer defenses in depth: ToolGuard, `GovernanceEngine`, `ToolSecurityEnforcer`.
- Windows-specific file hardening: native Windows API calls (`kernel32`/`advapi32` via `ctypes`) are used to apply restrictive DACLs to sensitive local files. This is genuinely defense-in-depth against other local principals.
- Shell execution is allowlisted structured-argv subprocess execution with bounded output and timeouts, and process trees are terminated with `taskkill /F /T`.

**The architecture freeze test is the standout governance artifact.** `tests/architecture/test_p0_architecture_freeze.py` (744 lines) is a 744-line architectural invariant suite that statically analyzes call sites via `ast`, walks object graphs, and classifies every execution entry point. Its own docstring states the right policy: "An allowlisted bypass is not an endorsement: it is a visible migration boundary that must be reviewed before the allowlist is changed." It records:

| Subsystem | Classification | Repository's stated reason |
| --- | --- | --- |
| `ToolChainExecutor` | `POTENTIAL_BYPASS` | "It calls ToolManager directly and has not been migrated to Runtime permits." |
| `MultimodalExecutor` | `POTENTIAL_BYPASS` | "It calls ProviderManager directly and has not been migrated to Runtime permits." |
| `StreamingExecutor` | `POTENTIAL_BYPASS` | (classified bypass entry point) |
| `ToolManager.execute_tool` | `POTENTIAL_BYPASS` | called directly rather than through Runtime permits |
| `AgentPlanner` | `SHOULD_REMAIN_DISCONNECTED` | "The canonical GAMBIT planner is Planner; multi-agent planning stays disconnected." |
| `CommunicationManager` | `SHOULD_REMAIN_DISCONNECTED` | "Production registers local email/message tools, not CommunicationManager delivery." |
| `RecoveryManager` | `TRANSITIONAL` | "Runtime accepts this transitional dependency, but composition supplies None." |
| `runtime_parallel` | `CANONICAL_RUNTIME_INTERNAL` | reverified as a live `RuntimeEngine.run_batch` dependency |

`IMPLEMENTED` and materially reducing risk: the bypasses are enumerated, classified, and asserted in CI-style tests rather than left as folklore.

**Confirmed bypass detail.** In `app/runtime/tool_chain.py`, `ToolChainExecutor._execute_step_with_retry` invokes `self._tool_manager.execute_tool(...)` directly, skipping `enforce_cap_permit`, ToolGuard, `GovernanceEngine`, and `ToolSecurityEnforcer`. `app/runtime/multimodal.py` shows the same shape: `MultimodalExecutor.execute` (lines 57–88) routes a payload straight to `ProviderManager` with trace instrumentation but no permit validation.

**Mitigating and decisive fact:** neither class is reachable from production. A repository-wide search for `ToolChainExecutor` returns only its definition plus test references (`tests/runtime/test_phase54_tool_chain.py`, `tests/benchmark/test_phase56_benchmarks.py`, `tests/architecture/test_p0_architecture_freeze.py`). `MultimodalExecutor` and `StreamingExecutor` are likewise unreferenced by `create_orchestrator`. I verified the streaming case specifically: `app/core/app.py` line 1724 sets `orchestrator.streaming_executor = provider_executor` — the governed canonical executor — with the adjacent comment "The legacy StreamingExecutor remains a disconnected library helper."

So the accurate finding is: **the bypass classes exist and are real, but they are quarantined, and the quarantine is test-enforced.** The residual risk is prospective — if someone wires `ToolChainExecutor` or `MultimodalExecutor` into production, the freeze test should fail. That is a design whose failure mode is a red test, not a silent hole. This is the correct way to hold a migration boundary, and it is a strength of the codebase, not merely a caveat.

`PARTIAL` — permit-integrity and scope checks were not exhaustively re-verified line-by-line in this pass; `UNKNOWN` — whether the signing key is protected adequately at rest on a shared machine, and whether the DACL hardening covers every sensitive file the app writes.

## 22. Observability and Diagnostics

`IMPLEMENTED`

- A typed runtime event bus (`app/events.py`) with `RuntimeEventType` including `TOKEN`, published per session and consumed by the TUI adapter.
- Structured execution traces: `RuntimeContext.trace.add_event(...)` is called by runtime components (e.g. `runtime.multimodal` execution-started events).
- Executor-level metrics: `MultimodalExecutor.get_metrics()` and a `StreamingExecutor.get_metrics()` expose snapshots via `MultimodalMetricsCollector`.
- A `/doctor` diagnostic command in the TUI shell, surfaced through `app/shell/command_router.py`.
- Developer review tooling: `/repo`, `/workspace`, `/review`, with `ReviewEngine.review_repository(Path.cwd())` producing severity-bucketed findings.
- A dedicated CLI diagnostics command.

`PARTIAL` — no metrics export (Prometheus/OpenTelemetry), no structured log shipping, and no centralized tracing backend were found. Observability is in-process and developer-facing.

## 23. Error Handling and Resilience

`IMPLEMENTED`

- Typed result and failure contracts: `RuntimeResult` carries `status`, `output`, `error`, and `metadata`; `TaskStatus` includes `PAUSED`; AgentLoop contracts define explicit verification and failure records.
- Retry with cooldown in the provider manager; retries in the runtime engine.
- Checkpointing plus a `RecoveryManager` for resume.
- Cancellation support end to end (`cancel_execution`), propagated through the TUI adapter.
- Approval pause/resume as a first-class control-flow state rather than an exception.
- Bounded concurrency: the execution coordinator uses an `asyncio.Lock` and a semaphore capping active executions.
- SQLite resilience: WAL journaling and a 5-second busy timeout across all stores.
- User-facing error surfacing in the adapter: exceptions become `⚠ {exc}` queue items rather than crashing the TUI.

`PARTIAL` — the `RecoveryManager` is classified `TRANSITIONAL` and composition supplies `None`, so the recovery capability is present but not active in the production path. Any claim that Samaktha recovers interrupted executions today is `UNSUPPORTED`.

## 24. Concurrency Model

`IMPLEMENTED`

Single-process asyncio. The coordinator serializes per-execution state with `asyncio.Lock` and caps concurrency with a semaphore; `RuntimeBase` exposes a concurrent `run_batch`; `app/runtime_parallel/` provides scheduler, dependency, worker, resource, recovery, and aggregation components; `app/workflow/engine.py` runs dependency-aware parallel workflows. Subprocess work uses `asyncio.create_subprocess_exec`.

`PARTIAL` / **Finding C1 — blocking I/O on the event loop is a real risk and needs verification.** `app/db/config.py` uses synchronous `sqlite3` with a `threading.Lock`, called from async request paths. Sync `sqlite3` calls block the event loop thread for their duration. The same pattern applies to OCR: the OCR parser invokes Tesseract and, optionally, an EasyOCR worker as a **synchronous subprocess**, and PyMuPDF/pytesseract page parsing is CPU-bound synchronous work called from async code. Under concurrent load this will serialize and stall the loop. I did not measure this in this pass, so treat the magnitude as `UNKNOWN` — but the pattern is present and should be confirmed and quantified. Moving these to a thread pool, or making the process-spawning paths use the asyncio subprocess API, would be the targeted fix; the OCR subprocess spawns are the worst offenders because external-binary startup plus document rasterization is slow by nature.

`MISSING` — no multi-process or distributed execution. There is no worker process pool beyond what `asyncio` provides, and no cross-process coordination beyond SQLite's file locking.

## 25. Testing and Quality Gates

`IMPLEMENTED`

- **3,151 tests collected in 4.03s.** Collection is fast and the suite is large.
- 275 Python test files.
- The architecture freeze suite (`tests/architecture/test_p0_architecture_freeze.py`, 744 lines) enforces composition and direct-execution invariants statically via `ast`, and freezes subsystem classifications.
- Layered test organization, including `tests/runtime/`, `tests/architecture/`, and `tests/benchmark/` (phase-numbered benchmark and feature suites, e.g. `test_phase54_tool_chain.py`, `test_phase56_benchmarks.py`).
- Governance behavior has dedicated coverage, including runtime permit tests and agent-loop v1 tests.
- Pytest configuration is centralized in `pyproject.toml`.

`PARTIAL` — **no full suite was run in this audit; only collection.** Pass/fail status is therefore `UNKNOWN`. `UNKNOWN` — coverage percentage (no coverage config or report was established), mutation testing, type checking (no mypy/pyright config confirmed), and linting (no ruff/flake8 config confirmed).

`MISSING` — no CI/CD. Every gate described above runs only if a developer remembers to run it locally. This is the single highest-leverage gap relative to the quality of the code that exists.

`UNKNOWN` — whether all 3,151 tests pass on the declared Python floor of 3.12, versus the 3.14.5 interpreter actually in use.

## 26. Performance Characteristics

`IMPLEMENTED` findings, in order of likely impact:

| # | Finding | Evidence | Severity |
| --- | --- | --- | --- |
| P1 | Memory search reads every row, then filters in Python | `app/memory/repository.py:33-42`, `app/memory/search.py` | High (grows unbounded) |
| P2 | Type-scoped memory delete pulls a large fixed recent set and filters in Python | `MemoryManager.delete_memory_by_type` | Medium |
| P3 | Connect-per-operation SQLite: every read/write opens a connection and applies 4 PRAGMAs | `app/db/config.py:52-69` | Medium (constant cost, high frequency) |
| P4 | Synchronous external-binary and CPU-bound document work on the event loop | OCR parser paths, PyMuPDF/tesseract | High under concurrency |
| P5 | `goal_parser.py` is 867 lines of regex-heavy parsing on the per-request path | `app/core/gambit/goal_parser.py` | Medium |
| P6 | Composition root and orchestrator are very large single modules | `app/core/app.py` 1,718 lines; `orchestrator/engine.py` 1,615 lines | Maintainability, not runtime |

`PARTIAL` — no benchmark results were produced or read in this pass, so none of the above is quantified. `tests/benchmark/` exists and is the natural place to measure P1–P5. `UNKNOWN` — no production profiling data, no latency percentiles, no token-economics tracking.

## 27. Code Quality and Maintainability

`IMPLEMENTED`

Genuine strengths, evidenced rather than asserted:

- **Excellent docstrings on security-relevant code.** `app/db/config.py`, `app/runtime/multimodal.py`, `app/agent/production.py`, and the freeze test all explain *why* a design is what it is, including rationale for things that look odd (connect-per-operation lifecycle; why `email` keeps `SEND` advertised).
- **Intent-revealing classification vocabulary.** `CANONICAL PRODUCTION`, `SAFE INTERNAL`, `POTENTIAL BYYPASS`-style labels make architectural status legible in one grep.
- **Typed contracts at boundaries.** AgentLoop, runtime, and memory contracts are dataclass/model based rather than dict-shaped.
- **Modular packaging.** `contracts/` separated from implementations; clean store/repository/manager layering in memory.

`PARTIAL` — three files exceed 1,500 lines and two more exceed 850. `app/core/app.py` at 1,718 lines is a single function-level bottleneck for architectural change: every wiring decision routes through it, which is precisely why the freeze test had to be built. `UNKNOWN` — typing strictness, lint cleanliness, and duplication levels were not measured.

## 28. Technical Debt

`PARTIAL`

| Item | Nature | Status |
| --- | --- | --- |
| `ToolChainExecutor` / `MultimodalExecutor` / `StreamingExecutor` direct-call bypasses | Governance migration boundary | `IMPLEMENTED` but quarantined and test-enforced |
| `RecoveryManager` disconnected | Transitional dependency, composition supplies `None` | `PARTIAL` |
| `AgentPlanner` disconnected from canonical planner | Intentional multi-agent hold | `DOCUMENTED ONLY` as a feature |
| `CommunicationManager` delivery disconnected | Intentional; tools registered instead | `DOCUMENTED ONLY` as a feature |
| Memory search without index/FTS | Performance debt | `IMPLEMENTED` |
| Blocking I/O on the async loop | Performance + concurrency debt | `IMPLEMENTED` |
| Python floor 3.12 vs environment 3.14 | Compatibility risk, untested floor | `IMPLEMENTED` |
| Three manually-synchronized Windows packaging files | Configuration drift risk | `IMPLEMENTED` |
| No CI/CD | Process debt | `IMPLEMENTED` |
| Single 1,718-line composition root | Architectural concentration | `IMPLEMENTED` |
| Single local principal, no auth | Deployment-scope limitation | `IMPLEMENTED` |

`PLANNED` — nothing in the repository documents a dated remediation plan for any of the above; the migration boundaries are described as future-phase work.

## 29. Documentation Status

`PARTIAL`

`docs/architecture/` contains exactly one document: `HARNESS_INTEGRATION_BLUEPRINT.md` (~41 KB). Additional content directories exist (`docs/pilot`, `docs/assets`, `docs/.qodo`, `.qodo/agents`, `.qodo/workflows`).

`MISSING` — no README-level architecture overview in `docs/architecture/`, no ADRs, no data-flow or sequence diagrams, no operational runbook, no onboarding guide, and no deployment guide. Notably, the architecture freeze test's classification table is the de facto authoritative architecture document, and it lives in a test file rather than in `docs/`. That is a documentation-structure gap worth closing by *referencing* the test from documentation, not by moving it.

## 30. Build and Release Process

`IMPLEMENTED`

Manual and Windows-targeted: `scripts/build_windows.ps1` drives PyInstaller using `samaktha.spec` (ONEDIR), then Inno Setup consumes `samaktha.iss` to produce an installer.

`MISSING` — no CI/CD, no release automation, no version-bump automation, no changelog generation, no artifact publishing, no code signing, no release verification step.

## 31. Dependencies and Supply Chain

`IMPLEMENTED`

Dependencies are declared in `pyproject.toml` with feature groupings (web, document/OCR, network, Windows, voice). `requirements/pilot-windows-py314.txt` pins a resolved Windows/CPython-3.14 set.

`PARTIAL` — no dependency-scanning configuration, no automated update policy, and no SBOM were found. `UNKNOWN` — whether the two manifests (`pyproject.toml` ranges vs. the pinned pilot file) are verified to agree.

## 32. Deployment Model

`IMPLEMENTED`

Local single-user desktop install on Windows, backed by a local SQLite database, local JSON state files, and a local signing key. Outbound network only to configured providers and search.

`MISSING` — no containerization, no service/systemd units, no reverse-proxy or TLS configuration, no multi-tenant isolation, no authentication or authorization layer.

## 33. Interoperability and Integrations

`IMPLEMENTED` — outbound LLM providers (Groq, OpenAI, OpenRouter, local), DDGS web search, optional Docling for document conversion, optional Tesseract/EasyOCR for OCR, Windows shell and filesystem, clipboard, notifications, reminders, and local email/message tooling.

`PARTIAL` / `UNKNOWN` — real delivery for email and message is unverified; `CommunicationManager` delivery is deliberately disconnected. No inbound integration (email polling, webhooks, calendar sync) is present.

## 34. Data Model

`IMPLEMENTED` — typed contracts for agent loop state, runtime context/task/result, memory entries with categories, planning tasks with status, pipeline state, and runtime events. Memory entries carry key, value, and category.

`PARTIAL` — schema versioning and migration strategy for the SQLite database are not established in this pass. `UNKNOWN` — whether there is any migration tooling, given that the store schema is applied at initialization.

## 35. Storage

`IMPLEMENTED` — SQLite is the single persistence substrate for long-term memory, session memory, productivity tools, and scheduler, all routed through the centralized `app/db/config.py` with WAL, `synchronous=NORMAL`, foreign keys on, and a 5-second busy timeout. JSON files hold capability state, checkpoint integrity metadata, and settings.

`MISSING` — no vector store and no embedding index. `app/memory/search.py` performs deterministic keyword matching only, so semantic retrieval is not implemented. Given the app's domain (personal memory, documents, skills), this is the most consequential functional limitation in the storage layer.

## 36. Caching

`IMPLEMENTED` — OCR results are cached to a temporary directory, avoiding repeated rasterization and Tesseract invocation for the same document. Provider layer has health/cooldown state. Checkpointing caches in-flight execution state.

`MISSING` — no provider response cache, no document-parse cache outside OCR, no semantic/embedding cache.

## 37. Error Handling and Validation (boundary)

`IMPLEMENTED` — Pydantic models for config and contracts; structured validation in the policy engine; explicit supported-action allowlists per tool; typed `RuntimeResult` with separate `error` field; graceful degradation for unavailable optional dependencies (OCR availability probing, `email` setup-required results).

`PARTIAL` — validation of HTTP request bodies and error response contracts were not enumerated in this pass. `UNKNOWN` — whether provider responses are schema-validated before being trusted into planning.

## 38. Logging

`IMPLEMENTED` — standard `logging` with module-level loggers (e.g. `app/agent/production.py` uses `log.debug` on the approval-resume path) and a `ResponseFormatter` for user-facing output.

`PARTIAL` / `UNKNOWN` — no structured logging configuration, no log rotation policy, no redaction of sensitive content in logs, and no centralized log sink were confirmed.

## 39. Developer Experience

`IMPLEMENTED` — Hatchling packaging, consolidated pytest config, a fast-collecting large test suite, in-app developer commands (`/repo`, `/workspace`, `/review`) backed by a `ReviewEngine`, `.qodo/agents` and `.qodo/workflows`, `.vscode/settings.json`, and an architecture freeze suite that makes architectural intent executable.

`PARTIAL` — no `CONTRIBUTING` or `AGENTS.md` equivalent confirmed in this pass; no documented local run/verify workflow. `MISSING` — no pre-commit configuration, no formatter configuration confirmed.

## 40. Code Review and Auditability

`IMPLEMENTED` — the architecture freeze suite is effectively an automated architectural review with explicit classifications and stated reasons, including the self-aware policy that an allowlist entry is "not an endorsement." Governance decisions are recorded as typed decisions and signed permits with an audit trail.

`PARTIAL` — `UNKNOWN` for human review process: no `CODEOWNERS`, no review policy document, no PR template.

## 41. Framework and Library Usage

`IMPLEMENTED` — FastAPI + Pydantic (HTTP and validation), Textual (TUI), asyncio (concurrency), SQLite via stdlib `sqlite3`, Hatchling (build), pytest (test), PyInstaller + Inno Setup (distribution), `ctypes` against `kernel32`/`advapi32` for Windows DACL hardening.

`PARTIAL` — dependency count is high across the document/OCR/voice/network/Win32 groups, all installed together by default even though several are optional at runtime. This inflates install size and attack surface; whether groups are actually selectable at install time is `UNKNOWN`.

## 42. Key Strengths

1. **A real governance layer, not a prompt-level suggestion.** Deterministic policy evaluation, approval with remembered permissions, signed permits, integrity digests, and action-level permission scoping.
2. **Bypasses are enumerated and test-enforced.** The 744-line architecture freeze suite converts "we know this is a bypass" into a red test. That is the professional way to hold a migration boundary.
3. **Centralized storage configuration.** `app/db/config.py` makes drift between four SQLite consumers structurally impossible and documents why.
4. **Honest capability metadata.** The `email` tool advertises `SEND` even when SMTP is absent so Runtime can return a truthful setup-required result rather than silently degrading.
5. **Clean UI/logic separation.** `ProductionAgentRuntime` owns no pipeline state and no provider execution path; it only renders canonical events.
6. **Substantial test investment.** 3,151 collected tests including architecture invariants, with 4-second collection.
7. **Windows-native security hardening.** DACL application via Win32 APIs is real defense-in-depth for a local-first agent.
8. **Genuine typed contracts** at loop, runtime, and memory boundaries.

## 43. Notable Risks

| Risk | Evidence | Impact |
| --- | --- | --- |
| Prospective governance bypass if a quarantined executor is wired in | `tool_chain.py` direct `execute_tool`; `multimodal.py` direct `ProviderManager`; freeze test classifications | High — mitigated by test enforcement today |
| Blocking I/O on the event loop | sync `sqlite3` + `threading.Lock`; sync OCR subprocesses and CPU-bound parsing in async paths | High under concurrency |
| Memory search degrades linearly with stored memory | `repository.py:33-42` full scan + Python filter | High over time |
| No CI/CD | no `.github` or any pipeline definition | High — all gates are manual |
| Single local principal, no authentication | `DEFAULT_LOCAL_PRINCIPAL_ID` used for all TUI executions | High if ever exposed beyond localhost |
| Untested declared Python floor (3.12 vs 3.14 in use) | `requires-python`, `.venv` on 3.14.5 | Medium |
| Three-file manual packaging sync | `build_windows.ps1`, `samaktha.spec`, `samaktha.iss` | Medium |
| Large single-module concentration | `app.py` 1,718; `orchestrator/engine.py` 1,615 | Medium (reviewability) |
| Recovery capability inactive | `RecoveryManager` `TRANSITIONAL`, composition supplies `None` | Medium — do not claim resumability |
| Unsigned installer, no release verification | Inno Setup script only | Medium |
| No semantic/vector retrieval | keyword-only memory search | Medium for the product's domain |
| Unverified supply-chain posture | no scanning config, no SBOM | Medium |

## 44. Current Maturity Scorecard

| Area | Rating | Basis |
| --- | --- | --- |
| Core architecture | **Strong** | Layered, typed, single canonical governed path |
| Governance and security | **Strong** | Signed permits, layered tool defense, freeze-tested bypass registry |
| Testing | **Strong in volume, unverified in health** | 3,151 collected; full suite not run; no coverage data |
| Documentation | **Weak** | One architecture doc; freeze test is the de facto standard |
| CI/CD and release | **Weak** | Manual Windows-only build, no pipeline, no signing |
| Performance engineering | **Weak** | Known O(n) memory search, blocking I/O, no profiling |
| Observability | **Moderate** | In-process events/traces/metrics; no export or centralized logging |
| Resilience | **Moderate** | Retries, checkpoints, cancellation; recovery manager inactive |
| Portability | **Windows-only by design** | No other packaging; native Win32 DACL code |
| Multi-user readiness | **Not applicable / absent** | Single local principal, no auth |
| Semantic retrieval | **Absent** | Keyword-only memory search |
| Autonomy / iterative execution | **Minimal by design** | `AgentLoop` is one action then terminate; `max_steps=1` |

**Overall:** a **serious, well-governed single-user local agent prototype with production-grade security thinking and engineering discipline in its architecture tests, held back by absent delivery infrastructure (no CI/CD), thin documentation, and unaddressed performance debt in memory search and event-loop blocking.**

## 45. Architecture Diagrams

### Diagram 1 — Layered architecture

```
┌───────────────────────────────────────────────────────────────────┐
│ INTERFACE LAYER                                                   │
│  Textual TUI (app/agent/production.py)   FastAPI backend (app/core)│
└───────────────────────┬───────────────────────────┬───────────────┘
                        │                           │
┌───────────────────────▼───────────────────────────▼───────────────┐
│ EXECUTION COORDINATOR  (app/core/execution_coordinator.py)      │
│  lifecycle · asyncio.Lock · semaphore cap · checkpoints · cancel  │
│  approvals · per-session RuntimeEventBus                          │
└───────────────────────┬───────────────────────────────────────────┘
                        │
┌───────────────────────▼───────────────────────────────────────────┐
│ ORCHESTRATOR  (app/core/orchestrator/engine.py)                  │
│  pipeline state · step execution (max_steps=1) · result assembly  │
└───────┬───────────────────────────────────┬───────────────────────┘
        │                                   │
┌───────▼──────────────────┐   ┌────────────▼───────────────────────┐
│ GAMBIT (planning)        │   │ CAP (policy + approval)            │
│  goal_parser (867 LOC)   │   │  policy_engine  (deterministic)    │
│  planner                 │   │  approval_engine (+ remembered)    │
│  task_decomposer         │   │  context · privacy · ambiguity     │
│  capability selection    │   │  permission_store                  │
└──────────────────────────┘   └────────────┬───────────────────────┘
                                          │ signed permit
                                (permit + integrity digest)
┌─────────────────────────────────────────▼─────────────────────────┐
│ RUNTIME  (app/runtime/, app/runtime_parallel/)                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ *** enforce_cap_permit  (governance.py) ***  CANONICAL GATE│  │
│  │   integrity · validity window · principal/session/workspace│  │
│  │   action · operation scope · approval decision              │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  engine (pool/retries/workers/checkpoints/recovery)               │
│  run_batch → runtime_parallel (scheduler/workers/resources)       │
│  dispatcher → ProviderExecutor · ToolExecutor                     │
│  ToolExecutor: CAP net-constraint → ToolGuard →                   │
│                GovernanceEngine → ToolSecurityEnforcer           │
└───────────┬──────────────────────────────────┬───────────────────┘
            │                                  │
┌───────────▼──────────────┐   ┌───────────────▼───────────────────┐
│ PROVIDERS                │   │ TOOLS (18 registered)             │
│  Groq · OpenAI           │   │  resolver · filesystem · document │
│  OpenRouter · local      │   │  pdf · image · memory · windows   │
│  mock                    │   │  internet · shell · clipboard     │
│  manager (health, retry, │   │  notification · reminder · notes  │
│  cooldown) + router      │   │  tasks · contacts · calendar      │
│  (capability scoring)    │   │  email · message                  │
└──────────────────────────┘   └───────────────┬───────────────────┘
                                              │
                            ┌─────────────────▼───────────────────┐
                            │ MEMORY  (app/memory/)              │
                            │  SQLite ← app/db/config.py (WAL)   │
                            │  store → repository → manager      │
                            │  controller/facade (public API)    │
                            └────────────────────────────────────┘

QUARANTINED (not in production composition; freeze-test enforced):
  ToolChainExecutor · MultimodalExecutor · StreamingExecutor
  AgentPlanner · CommunicationManager · RecoveryManager(None)
```

### Diagram 2 — Governed tool-execution sequence

```
User/TUI      Coordinator      Orchestrator      CAP        Runtime Gate      Tool
   │               │               │              │              │              │
   │ handle_message │               │              │              │              │
   ├───────────────>│ start_execution              │              │              │
   │               ├──────────────>│ parse + plan │              │              │
   │               │               ├─────────────>│ evaluate   │              │
   │               │               │              │ policy     │              │
   │               │               │              │ risk       │              │
   │               │               │<── decision + signed permit ───┤         │
   │               │               ├─────────────────────────────>│         │
   │               │               │              │   verify:  │         │
   │               │               │              │   integrity │         │
   │               │               │              │   validity  │         │
   │               │               │              │   scope     │         │
   │               │               │              │   (principal│         │
   │               │               │              │    /session │         │
   │               │               │              │    /workzone│         │
   │               │               │              │    /action) │         │
   │               │               │              │              │         │
   │               │               │              │  ASK_USER ──┼──> PAUSED │
   │<── PAUSE_REQUESTED (approval prompt) ───────────────────────┤         │
   │  reply y/n → resume() → submit_approval ──>│  ALLOW       │         │
   │               │               │              ├─────────────>│         │
   │               │               │              │              ├─ ToolGuard
   │               │               │              │              ├─ Governance
   │               │               │              │              ├─ Security
   │               │               │              │              ├──────────>│
   │               │               │              │              │        execute
   │               │               │              │              │<─────────┤
   │<── TOKEN events / final result / tool output ──────────────────────── │
```

### Diagram 3 — Dual execution surface (live vs. quarantined)

```
LIVE GOVERNED PATH (canonical)
  TUI ─▶ Coordinator ─▶ Orchestrator ─▶ CAP ─▶ enforce_cap_permit
                                                     │
                                                     ▼
                                        ProviderExecutor ─▶ ProviderManager
                                        ToolExecutor      ─▶ ToolManager

QUARANTINED PATHS (exist, tested, NOT wired into create_orchestrator)
  ToolChainExecutor  ─▶ ToolManager.execute_tool   ✗ no permit validation
        │                  └─ skips CAP gate, ToolGuard, Governance, Security
        └─ referenced only by tests/runtime/test_phase54_tool_chain.py
                          tests/benchmark/test_phase56_benchmarks.py
                          tests/architecture/test_p0_architecture_freeze.py

  MultimodalExecutor ─▶ ProviderManager.execute_provider
        └─ no permit validation; POTENTIAL_BYPASS per freeze test

  StreamingExecutor  ─▶ (legacy, disconnected)
        └─ app.py:1724 assigns provider_executor instead:
           "orchestrator.streaming_executor = provider_executor"
           "The legacy StreamingExecutor remains a disconnected library helper."

  AgentPlanner / CommunicationManager ─▶ SHOULD_REMAIN_DISCONNECTED
  RecoveryManager ─▶ TRANSITIONAL, composition supplies None

SAFETY PROPERTY: test_p0_architecture_freeze.py fails if any quarantined
class is instantiated by create_orchestrator(). Failure mode = red test,
not a silent governance hole.
```

## 46. What Samaktha Can Do Today (verified)

`IMPLEMENTED`

- Accept natural-language goals in a Windows terminal UI or over HTTP.
- Parse goals into intents and plans, decomposing them into tasks.
- Evaluate each proposed action against deterministic policy and risk rules.
- Ask the user for approval, remember granted permissions, and pause/resume execution.
- Issue cryptographically signed, scope-checked permits and validate them at the runtime boundary.
- Call Groq, OpenAI, OpenRouter, local, or mock providers, with capability-aware health-scored routing, retries, and cooldowns.
- Stream tokens live to the TUI through a typed event bus.
- Execute 18 governed local tools, including filesystem, shell (allowlisted structured argv), documents, PDF, image, memory, Windows integration, clipboard, notifications, reminders, notes, tasks, contacts, calendar, and email/message tooling.
- Parse documents with a PyMuPDF → pdfplumber → OCR → Docling chain, stopping at first successful extraction.
- OCR documents with Tesseract, optionally via an isolated EasyOCR subprocess worker, with disk caching.
- Persist and recall long-term memory in SQLite across four stores sharing one configuration source.
- Run dependency-aware parallel workflows and batch runtime execution with worker scheduling, resource allocation, and checkpoints.
- Cancel in-flight executions.
- Run `/doctor` diagnostics, `/repo`, `/workspace`, and `/review` repository analysis.

## 47. What Samaktha Cannot Do Today (verified gaps)

`MISSING`

- No iterative autonomous execution: `AgentLoop` performs exactly one action then terminates; orchestrator steps use `max_steps=1`.
- No execution recovery: `RecoveryManager` is transitional and composition supplies `None`.
- No semantic or vector memory retrieval: keyword-only matching.
- No authentication, authorization, or multi-user isolation: one hardcoded local principal.
- No CI/CD, no release automation, no code signing, no installer upgrade path.
- No cross-platform packaging: Windows only.
- No inbound integrations: no email polling, webhooks, or calendar sync.
- No metrics export, distributed tracing, or centralized logging.
- No multi-agent planning: `AgentPlanner` is deliberately disconnected from the canonical `Planner`.
- No `CommunicationManager` delivery: production registers local email/message tools instead.
- No semantic layer over raw data: every store reads rows and filters in Python.

`DOCUMENTED ONLY` — outbound email send, outbound message delivery, and native reminders/notifications have implementation and registration, but no verified live execution was established in this audit.

## 48. Comparison to Common Agent Architectures

For calibration, stated plainly and without proposing change:

| Pattern | Samaktha's position |
| --- | --- |
| Bare LLM wrapper | **No.** Substantial deterministic policy, approval, and permit machinery sits between the model and any effect. |
| ReAct-style autonomous loop | **No.** Single-action execution with explicit termination. |
| Multi-agent framework | **No.** `AgentPlanner` exists but is deliberately disconnected. |
| Plugin/microservice mesh | **No.** Single process, single local principal, in-process composition. |
| Event-sourced architecture | **Partial.** Typed runtime events and trace events exist; no event sourcing or persistence-as-source-of-truth was found. |
| Zero-trust tool execution | **Yes, in design.** Signed, integrity-checked, scope-bound permits with defense-in-depth tool validation. |
| Local-first personal agent | **Yes.** SQLite local storage, Windows desktop install, local signing key, outbound-only network. |
| Workflow orchestrator | **Yes.** Dependency-aware parallel workflows, scheduler, worker pool, checkpoints. |

Samaktha's distinctive combination is **local-first single-user operation with zero-trust-style tool authorization and an executable architecture contract** — an unusual and defensible pairing, though the autonomy layer is currently minimal by design.

## 49. Planned vs. Implemented

`PLANNED` (referenced as future work, not present in code)

- Migrating `ToolChainExecutor`, `MultimodalExecutor`, and `StreamingExecutor` onto Runtime permits — named as the reason for their `POTENTIAL_BYPASS` classification.
- Activating `RecoveryManager` in composition (currently `TRANSITIONAL` with `None`).
- Enabling multi-agent planning via `AgentPlanner` (currently `SHOULD_REMAIN_DISCONNECTED`).
- Wiring `CommunicationManager` delivery (currently `SHOULD_REMAIN_DISCONNECTED`).

`IMPLEMENTED` — everything in Section 46.

`UNKNOWN` — the repository contains no dated roadmap, milestone list, or sequenced remediation plan; the only forward-looking intent is encoded in the freeze test's classifications and their "later phase" phrasing.

## 50. Maturity Assessment

Samaktha is **beyond prototype** in architecture, security design, and test investment, and **pre-production** in delivery practice.

What is genuinely production-grade: the governance and permit model, the layered tool defense, the centralized persistence configuration, the typed contracts, the honest capability metadata, and above all the architecture freeze suite that makes architectural boundaries executable rather than aspirational.

What is pre-production: no CI/CD, no release automation or signing, thin documentation, unverified full-suite health, no coverage measurement, unaddressed performance debt (full-scan memory search, event-loop blocking), Windows-only packaging, and an untested declared Python floor.

The clearest single observation: **this codebase has unusually mature internal engineering discipline and unusually immature external delivery infrastructure.** The gap between the two is the main thing standing between it and dependable operation.

## 51. Recommended Investigation Order

These are investigation priorities — what to examine, verify, or measure next. They propose no architecture change.

1. **Run the full test suite and record the result.** 3,151 tests collected but never executed in this audit. Everything else is secondary until the baseline is known.
2. **Read `app/runtime/governance.py` end to end and enumerate the complete permit check list.** This is the security boundary; confirm exactly which scope predicates are enforced and which are not.
3. **Measure Finding P1** (full-scan memory search) against realistic memory volume, and check for SQLite FTS availability in the current build.
4. **Profile the event loop under concurrency** to quantify Finding P4: sync `sqlite3` + `threading.Lock`, synchronous OCR subprocess spawns, and CPU-bound PDF parsing in async paths.
5. **Enumerate the FastAPI surface** — every route, its auth posture, body validation, and error contract — before any non-localhost exposure is contemplated.
6. **Confirm secret handling**: that no credential is committed, and that `config/permit_signing.key` permissions are adequate at rest on a shared machine.
7. **Verify Windows packaging consistency** across `pyproject.toml` version, `samaktha.spec`, and `samaktha.iss`, then attempt a clean build and launch smoke test.
8. **Test on the declared Python floor (3.12)**, not only the 3.14.5 interpreter in use.
9. **Audit `goal_parser.py`** (867 lines, regex-heavy, per-request path) for false-positive intent classification and compilation-in-hot-path issues.
10. **Establish coverage and static-analysis baselines** (coverage, a type checker, a linter), none of which are currently configured.
11. **Confirm the freeze test actually fails** if `ToolChainExecutor` is instantiated in `create_orchestrator` — the quarantine is only as good as its enforcement, and this is worth demonstrating rather than assuming.
12. **Document the architecture freeze classifications in `docs/architecture/`** by reference, so the de facto architecture standard is discoverable outside the test suite.

## 52. Final Summary

**Overall maturity:** Samaktha is a serious, well-governed, local-first single-user AI agent application with production-grade security architecture and unusually strong executable architecture tests, held back by absent delivery infrastructure, thin documentation, and unaddressed performance debt. It is beyond prototype in design and pre-production in practice.

**Primary technical strength:** the governance layer. Deterministic policy evaluation, approval with remembered permissions, cryptographically signed and scope-validated permits, and defense-in-depth tool validation constitute a real authorization boundary between the model and any effect on the system.

**Primary technical weakness:** no CI/CD. Every quality gate in a codebase with 3,151 tests and a 744-line architecture invariant suite depends on a human remembering to run it.

**Most consequential verified findings:**
1. Three executor classes bypass permit validation by design and are quarantined from production; the quarantine is enforced by `tests/architecture/test_p0_architecture_freeze.py`, and `app/core/app.py:1724` confirms the streaming path was deliberately rewired to the governed executor. Residual risk is prospective, not present.
2. Memory search performs a full-table read with Python-side filtering on every query (`app/memory/repository.py:33-42`), degrading linearly with stored memory on the agent's hot path.
3. Synchronous SQLite and synchronous external-binary/OCR work run on the asyncio event loop, creating a concurrency and latency risk that is present but unquantified.
4. Autonomy is minimal by design: `AgentLoop` executes exactly one action then terminates, and orchestrator steps use `max_steps=1`. Samaktha is not an open-ended autonomous agent today.
5. No authentication and a single hardcoded local principal (`DEFAULT_LOCAL_PRINCIPAL_ID`) make the system strictly single-user, which constrains any future network exposure.

**Critical caveat on this audit:** collection succeeded at 3,151 tests in 4.03s, but **no test was executed and no provider, OCR binary, or installer was invoked.** Health, latency, and live-integration behavior remain `UNKNOWN`. Several claims — permit check completeness, FastAPI route surface, Python-floor compatibility, packaging consistency, and secret hygiene — are explicitly flagged for verification rather than asserted.

**Recommended next step:** establish the test baseline, then read `app/runtime/governance.py` end to end. Everything else is secondary to knowing whether the suite passes and whether the authorization boundary is exactly as strong as its documentation claims.

---

**Audit basis:** repository inspection of tracked source, configuration, tests, and packaging manifests.
**Files changed by this audit:** this report only. No source code was modified.