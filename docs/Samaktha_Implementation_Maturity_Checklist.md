# Samaktha Implementation & Maturity Checklist

> **Objective:** Convert Samaktha's architectural blueprint into a coherent, operational, extensible framework.

---

# 🟥 P0 — Correctness & Architectural Enforcement

**Objective:** Nothing that the architecture says must be enforced is allowed to be bypassed or silently broken.

## P0.1 — CAP Governance Enforcement

- [x] CAP permit gate enforced for **every executable path**
- [x] TUI → Runtime path audited
- [x] Voice → Runtime path audited
- [x] HTTP → Runtime path audited
- [x] StreamingExecutor → CAP integration fixed
- [x] Provider execution cannot bypass CAP
- [x] Tool execution cannot bypass CAP
- [x] Denied operations are actually prevented
- [x] Pending approval operations pause correctly
- [x] Approved operations execute correctly
- [x] Resume flow works after approval

**Done when:** There is no production execution path capable of reaching an actionable provider/tool without the required CAP decision.

## P0.2 — Security Pipeline

- [x] `InputSecurityScanner` wired into production
- [x] `OutputSecurityFilter` wired into production
- [x] `ToolGuard` wired into production
- [x] Security checks occur at the correct execution boundary
- [x] Security failures stop execution
- [x] Security decisions are observable/auditable
- [x] Tests cover allowed + rejected inputs
- [x] Tests cover malicious/unsafe tool arguments
- [x] Tests cover unsafe outputs

**Done when:** Security components are active runtime controls, not dead code.

## P0.3 — Application Startup

- [x] Application starts without provider API keys
- [x] `/health` remains available without configured providers
- [x] Provider validation occurs at the correct lifecycle stage
- [x] Configuration errors are reported cleanly
- [x] Startup failures don't destroy unrelated functionality
- [x] Production startup path verified

**Done when:** `create_app()` and `/health` work independently of optional provider configuration.

## P0.4 — Runtime Path Cleanup

- [x] Remove/retire unused `AgentRuntime`
- [x] Confirm `ProductionAgentRuntime` is canonical
- [x] Remove duplicate runtime logic
- [x] Fix `main.py` application launch
- [x] Expose intended streaming path
- [x] Remove orphaned modules
- [x] Remove duplicate registrations
- [x] Remove duplicate developer-tool names
- [x] Resolve `app/utils/` inconsistency

**Done when:** Every production subsystem has one clearly defined canonical path.

## P0.5 — Configuration & Version Integrity

- [x] Remove hardcoded SQLite paths
- [x] Use configured `sqlite_url`
- [x] Harmonize application version
- [x] Fix version detection
- [x] Stop swallowing version-import errors
- [x] Audit environment configuration
- [x] Audit development vs production configuration

**Done when:** Configuration has a single source of truth.

## P0.6 — Test Recovery

- [x] Fix all currently failing tests
- [x] Fix environment-sensitive tests
- [x] Fix TUI tests
- [x] Fix startup tests
- [x] Run complete regression suite
- [x] No unexplained failures
- [x] No newly introduced regressions

### P0 Exit Gate

- [x] All known critical defects resolved
- [x] CAP cannot be bypassed
- [x] Security controls are live
- [x] Application starts correctly
- [x] Canonical runtime path established
- [x] Full test suite passes

---

# 🟧 P1 — Core Implementation Completion

**Objective:** Make the existing architecture function end-to-end rather than merely exist structurally.

## P1.1 — Persistent Productivity Layer

- [x] Calendar persistence
- [x] Contacts persistence
- [x] Tasks persistence
- [x] Notes persistence
- [x] Reminders persistence
- [x] CRUD operations survive restart
- [x] Data validation
- [x] Error recovery
- [x] CAP integration for sensitive operations

**Done when:** Restarting Samaktha does not erase productivity state.

**Completion record (P1.1):**
- Implementation: each productivity store (Calendar/Contacts/Tasks/Notes/Reminder) is now durable — an in-memory cache rebuilt from and persisted to the canonical SQLite DB via the generic `SQLiteJsonTable`. New `app/tools/storage.py` (open_table / rebuild / save / delete_row). Tool constructors accept `db_path`; `create_orchestrator` passes the canonical `resolve_sqlite_path(settings.sqlite_url)` path so all personal data shares the memory DB file. Direct-mutation flows (task complete, reminder update/snooze/complete) now persist.
- Recovery: a single corrupt row is skipped (log warning) instead of aborting reload; `SQLiteJsonTable.get/all` tolerate bad JSON rows.
- CAP: destructive personal-data operations (`notes.delete`, `tasks.delete`, `contacts.delete`, `calendar.delete`, `reminder.cancel`) now require CRITICAL context in `ToolGuard`, consistent with `filesystem.delete` / `system.exec`.
- Tests: new `tests/tools/test_phase14_persistence.py` (19 tests) — per-tool restart persistence, canonical default path, invalid-datetime validation, corrupt-row recovery, CAP gating with/without CRITICAL context, complete/snooze persistence. `tests/tools/test_phase14_tools_contract.py` updated with an autouse tmp-DB fixture so the contract suite is hermetic.
- Results: `tests/tools` 93/93; security + api + phase13 suites 145/145; full suite **1836 passed / 0 failures** (previous 1818 + 18). 21 warnings (pre-existing categories).
- Invariants preserved: CAP, security wiring, canonical runtime path, app boot, full suite green.

## P1.2 — Reminder & Scheduler Lifecycle

- [x] Scheduler starts automatically
- [x] Scheduler shutdown is graceful
- [x] Reminder execution works
- [x] Scheduled jobs survive appropriate lifecycle boundaries
- [x] Scheduler errors are observable
- [x] Scheduler state is recoverable
- [x] Duplicate jobs prevented

**Completion record (P1.2):**
- Implementation: `app/tools/reminder.py` — `ReminderScheduler` rewritten with a real async lifecycle: idempotent `start()` (single named asyncio task "reminder-scheduler"), graceful `stop()` (cancel + await), `_poll_loop` polling `check_due()` every `poll_interval` (default 30s) and surviving callback errors; `check_due()` fires callbacks, completes one-shot reminders, and reschedules repeating ones to their next daily/weekly/monthly occurrence (`_next_occurrence`); duplicate reminder ids rejected (`ValueError`); `errors` property (bounded deque, `MAX_ERRORS=100`) makes failures observable; durable store kept, so jobs survive restarts.
- Wiring: `app/core/app.py` — notification callback registered on the scheduler inside `create_orchestrator`; `orchestrator.reminder_scheduler` attached; FastAPI `create_app` gained an `asynccontextmanager` lifespan that `start()`s the scheduler on startup and `stop()`s it on shutdown. `app/agent/production.py` — `ProductionAgentRuntime.start()/stop()` expose the shared scheduler and `handle_message` lazily ensures it is started (mock-safe via `inspect.iscoroutinefunction`). `app/tui/app.py` — Textual `on_mount`/`on_unmount` start/stop the scheduler through the runtime facade.
- Tests: new `tests/tools/test_phase14_scheduler_lifecycle.py` (12 tests) — due reminders fire callbacks, one-shots complete after firing, repeating reminders reschedule to the next occurrence, duplicate ids rejected, start idempotency (no duplicate loop task), graceful stop, poll loop fires due reminders, callback errors observable via `errors`, jobs survive restart, FastAPI lifespan starts/stops the scheduler, TUI runtime start/stop, `ReminderTool.scheduler` property.
- Results: `tests/tools` 93/93; tui runtime bus integration 3/3; api+security+communication+db 115/115; full suite **1848 passed / 0 failures** (baseline 1836 + 12). 20 warnings (pre-existing categories only).
- Invariants preserved: CAP, security wiring, canonical runtime path, app boot, full suite green.

## P1.3 — SQLite Reliability

- [x] WAL enabled
- [x] `busy_timeout` configured
- [x] Connection lifecycle reviewed
- [x] Transaction boundaries reviewed
- [x] Concurrent writes tested
- [x] Database path centralized
- [x] Migration/version strategy defined
- [x] Recovery behavior tested

**Completion record (P1.3):**
- Implementation: new `app/db/` package — `config.py` (canonical path from `Settings.sqlite_url` via `resolve_database_path`, `configure_connection` applying WAL / `synchronous=NORMAL` / `foreign_keys=ON` / `busy_timeout=5000ms`, `connect()` connect-per-operation lifecycle with parent-dir creation); `base.py` (versioned additive schema helper `ensure_table` with `PRAGMA user_version`, generic durable `SQLiteJsonTable` JSON-row store with per-instance lock for the productivity layer).
- `app/memory/sqlite_store.py` refactored onto the shared config; removed hardcoded `_DB_PATH` default (now resolves from settings). `app/diagnostics.py` SQLite check now uses the canonical settings path instead of `data/memory.db`. `.gitignore` covers WAL/SHM sidecars.
- Tests: new `tests/db/test_phase13_sqlite_reliability.py` (12 tests) — WAL/busy_timeout, path centralization (store + diagnostics), user_version stamping, idempotent ensure, legacy-table upgrade, concurrent writes across instances, restart persistence, JSON table roundtrip/restart, no-hardcoded-path guard.
- Results: `tests/db` 12/12; memory + architecture diagnostics suites 126/126; full suite **1818 passed / 0 failures** (baseline 1806 + 12). 21 warnings (pre-existing categories only).
- Invariants preserved: CAP, security wiring, canonical runtime path, app boot, full suite green.

## P1.4 — Session & State Lifecycle

- [ ] Conversation state persistence policy defined
- [ ] State pruning implemented
- [ ] Scheduler history pruning implemented
- [ ] Memory lifecycle boundaries defined
- [ ] Expiration/archival rules defined
- [ ] Memory growth bounded
- [ ] Restart behavior tested

## P1.4 — Session & State Lifecycle

- [x] Conversation state persistence policy defined
- [x] State pruning implemented
- [x] Scheduler history pruning implemented
- [x] Memory lifecycle boundaries defined
- [x] Expiration/archival rules defined
- [x] Memory growth bounded
- [x] Restart behavior tested

**Completion record (P1.4):**
- Policy: conversation state is **ephemeral by design** — `ConversationStateManager` state is short-lived in-memory working memory, rebuilt lazily as empty on restart; the durable record of a conversation lives in `SessionManager` session memory (history + facts). Lifecycle boundaries are explicit: `get_state` (lazy create), `reset`, `remove`, `clear`; session create ↔ delete; history rotation ↔ archive sidecar; cache eviction ↔ reload from disk; scheduler completion ↔ retained/pruned.
- Expiration/archival rules: session history over `max_history_entries` is **moved** (never deleted) to `session_memory_archive.json`; sessions stay durable on disk so cache eviction never loses data; completed reminders beyond the retention cap are pruned (active/repeating jobs never touched).
- SessionManager: in-memory `_cache` now bounded by `max_cached_sessions` (default `DEFAULT_MAX_CACHED_SESSIONS=256`) using LRU eviction (`OrderedDict` + `_cache_session`/`_bound_cache`); public `prune_cache()`; `max_cached_sessions=None` keeps prior unbounded behavior.
- ConversationStateManager: `max_sessions` (default 128) with LRU eviction by `updated_at`; new `prune_idle(max_age_seconds)` drops untouched states; policy documented in the module docstring.
- ReminderScheduler: `keep_completed` (default `DEFAULT_KEPT_COMPLETED_REMINDERS=200`), `prune_completed(keep)` removes oldest completed reminders from memory **and** the durable store, auto-prunes after saves and on rebuild; active/repeating jobs never pruned; `keep_completed=None` disables.
- Tests: new `tests/memory/test_phase14_session_lifecycle.py` (12 tests) — cache bound + LRU eviction, evicted session reloads from disk with history intact, `prune_cache` count, unbounded mode, history rotation archives and survives restart, state max-sessions eviction, `prune_idle` count, ephemeral-on-restart policy, scheduler prune keeps newest, auto-prune on save, active jobs never pruned, pruning disabled.
- Results: `tests/memory` 66/66; conversation + tools 227/227; full suite **1860 passed / 0 failures** (baseline 1848 + 12). 22 warnings (pre-existing categories only).
- Invariants preserved: CAP, security wiring, canonical runtime path, app boot, full suite green.

## P1.5 — HTTP Execution Layer

- [x] `/execute` supports intended execution flow
- [x] Conversation/session continuity
- [x] Streaming endpoint
- [x] Structured errors
- [x] No raw 500 leakage
- [x] Request size limits
- [x] Rate limiting
- [x] Timeout handling
- [x] Cancellation
- [x] Request/task IDs
- [x] CAP integration
- [x] Observability integration

**Completion record (P1.5):**
- `/execute` flow: `app/api/execute.py` rewritten — `ExecuteRequest` gained optional `session_id` and `conversation` (session continuity; conversation passed through only when supplied, keeping minimal orchestrators compatible); `ExecuteResponse` gained `request_id`, `session_id`, `task_id` correlation ids; the endpoint runs the canonical `orchestrator.run` in a task with a hard timeout (`api_execute_timeout_seconds`) and disconnect-driven cancellation (`_await_with_limits`, cancels in-flight work, 499 `client_disconnected`).
- Streaming endpoint: `/execute/stream` — SSE over the canonical `run_pipeline` (`pipeline.started` / `pipeline.completed` / `pipeline.failed`), timeout-cancelled, non-buffered headers, covered by the same limits.
- Structured errors / no raw leakage: `413 request_too_large`, `429 rate_limited` (with `Retry-After`), `504 timeout`, `499 client_disconnected`, and a global `Exception` handler returning `500 {"code","message","request_id"}` with the real exception only logged.
- Request size limits: `api_max_request_bytes` enforced via Content-Length middleware; rate limiting: thread-safe fixed-window `RateLimiter` (`api_rate_limit_per_minute`) keyed by client address (`app/api/limits.py`).
- Observability: `app/api/metrics.py` — `HttpMetricsCollector` (requests/completed/failed/timeouts/rate_limited/request_too_large/cancelled/durations) + `snapshot_adapter`; `create_app` wires a `TelemetryRegistry` with http + security + streaming collectors and a `/metrics` endpoint returning the aggregated snapshot.
- Tests: new `tests/api/test_phase15_http_execution.py` (14 tests) — session/conversation passthrough, default-session behavior, SSE lifecycle + timeout failure, 504 timeout, in-flight cancellation flag, structured 500 without leakage, CAP-denied status/error passthrough, 413 size, 429 rate limit + Retry-After, metrics aggregation, metrics counters (too-large/rate-limited/timeouts). Two architecture tests updated for the intentional `execute_request(request=...)` signature change (inject minimal fake Request).
- Results: `tests/api` 20/20; architecture 86/86; full suite **1874 passed / 0 failures** (baseline 1860 + 14). 22 warnings (pre-existing categories only).
- Invariants preserved: CAP, security wiring, canonical runtime path (streaming endpoint runs the same `run_pipeline`), app boot, full suite green.

## P1.6 — Communication Layer

- [x] SMTP provider implementation
- [x] Outbound message execution
- [x] Configuration validation
- [x] Failure handling
- [x] Retry policy
- [x] CAP approval integration
- [x] Audit trail
- [x] Test provider

**Completion record (P1.6):**
- SMTP provider implementation: `SMTPProvider` (`app/communication/provider.py`) is now a real SMTP client — builds an `email.message.EmailMessage`, connects via `smtplib.SMTP`/`SMTP_SSL`, optional StartTLS, optional login, `sendmail` with recipient-rejection detection, monotonic message ids, graceful `quit()`. Unconfigured providers are inert: every operation returns a deterministic `not_configured` result and never touches the network.
- Configuration validation: new `app/communication/config.py` — `CommunicationConfig` (host/port/username/password/from_address/use_tls/use_ssl/timeout_s), `validate_smtp_config` (host, from-address, port whitelist, timeout range), `load_smtp_config` from `SAMAKTHA_SMTP_*` env values, `SMTP_ENV_PREFIX`.
- Outbound message execution: `CommunicationManager.send` resolves the provider, validates, dispatches, and returns structured `CommunicationResult` outcomes; every outcome is appended to the audit history.
- Failure handling: structured errors at every layer (config missing, validation errors, missing provider, transport exceptions) — real exception text is logged, only a wrapped `SMTP delivery error: …` surface string is returned to callers.
- Retry policy: new `app/communication/retry.py` — `RetryPolicy(max_attempts, backoff_s, retryable_statuses)`; the manager retries transient `FAILED` outcomes up to `max_attempts` with optional backoff and stops on success.
- CAP approval integration: the manager now enforces an explicit gate — any request with `approval_required=True` must carry `metadata["approved"]=True` (set by the CAP-approved tool flow) or it is refused with `approval_required` status; policy already marked every non-desktop provider as approval-required and `EmailTool`/`MessageTool` as `approval_required=True`.
- Audit trail: `CommunicationHistory` is now durable when `db_path` is supplied (shared `SQLiteJsonTable`, table `communication_history`), reloads across instances, and is bounded by `max_entries` in both memory and storage (oldest dropped first); the manager records every send outcome. Without `db_path` it stays purely in-memory.
- Test provider: new `TestProvider` (registered as `"test"` in the default registry) — deterministic in-memory delivery, records `sent_messages`, health true, `__test__ = False` so pytest does not collect it.
- Tests: new `tests/communication/test_phase16_communication_reliability.py` (25 tests) — SMTP config validation (5), SMTP provider mocked-transport success/SSL/failure/validation/unconfigured-inert (5), test provider (3), retry policy (4), CAP approval gate (4), durable audit trail (4).
- Results: `tests/communication` 69/69; full suite **1899 passed / 0 failures** (baseline 1874 + 25). 22 warnings (pre-existing categories only).
- Invariants preserved: CAP (approval gate is defense-in-depth on top of tool/CAP enforcement — no bypass), security wiring, canonical runtime path, app boot, full suite green.

## P1.7 — Developer Intelligence

- [x] Replace fabricated analyzer responses
- [x] Real code analyzer integration
- [x] Review engine
- [x] Structured findings
- [x] Severity classification
- [x] Evidence attached to findings
- [x] Tests against real repositories/code
- [x] Failure behavior

**Completion record (P1.7):**
- Replaced fabricated analyzer responses: `app/developer/review.py` rewritten from keyword heuristics (a literal `"password"` string, two `for` keywords, a `"subprocess"` token) to **real AST-based analyzers** that operate on actual Python syntax.
- Structured findings: `Finding` dataclass (`rule`, `severity`, `message`, `category`, `file`, `line`, `evidence`) and `ReviewResult` (`findings`, `files_scanned`, `errors`, `count()`, `by_severity()`, `sorted_findings()`).
- Severity classification: `Severity` enum (INFO/LOW/MEDIUM/HIGH) with `rank` for ordering; `sorted_findings()` orders HIGH-first, then file/line/rule.
- Evidence attached: every finding carries the source line (`evidence`) it was derived from, so findings are auditable.
- Real code analyzer integration: `ReviewEngine` runs a default analyzer set over a single file, a list of files, or a whole repository (`review` / `review_files` / `review_repository`); the `/review` shell command now runs the engine over the cwd and renders findings with severity counts (was a placeholder summary).
- Analyzers: `HardcodedSecretAnalyzer` (HIGH/security — secret-named assignments and dict-literal values), `UnusedImportAnalyzer` (LOW/correctness — imports never referenced, aliases and `from … import` handled, `import *` ignored), `LongFunctionAnalyzer` (MEDIUM/maintainability — body span > threshold), `NestedLoopAnalyzer` (LOW/performance — loop depth >= 2), `TodoFIXMEAnalyzer` (INFO/maintainability). `list_rules()` exposes the active rules.
- Failure behavior: missing path → recorded in `errors`; unparseable file → structured `parse-error` finding (HIGH/correctness) instead of a crash; a raising analyzer is caught per-file and recorded in `errors` without aborting the scan; repository scans skip `.venv`/`node_modules`/`__pycache__`/`site-packages`/`.git`.
- Tests: new `tests/developer/test_phase17_developer_intelligence.py` (23 tests) — structured finding shape + evidence, severity ranking, severity counts, ordering, secret assignment/dict-literal/innocent-name cases, nested vs flat loops, unused imports (plain/alias/from/star), long vs short functions, TODO/FIXME markers, missing-path/unparseable/not-a-file/analyzer-error behavior, ignored-dir scanning, and a full-repository scan against real code fixtures. Old fabricated-reviewer assertions removed from `tests/developer/test_phase16_repository_ecosystem.py` (intentional behavior change per roadmap).
- Results: `tests/developer` 32/32; shell 22/22; full suite **1922 passed / 0 failures** (baseline 1899 + 23). 22 warnings (pre-existing categories only).
- Invariants preserved: CAP, security wiring, canonical runtime path, app boot, full suite green.

### P1 Exit Gate

- [x] Core subsystems survive real execution
- [x] Persistent state works
- [x] Scheduler works
- [x] HTTP execution works
- [x] Communication works
- [x] Developer tools produce real results
- [x] SQLite is reliable
- [x] State lifecycle is bounded
- [x] Regression suite passes

**Exit gate verification (P1):**
- Core subsystems survive real execution: P0 gate already green; every P1 phase re-ran the full suite after its changes.
- Persistent state works: P1.1 durable notes/tasks/contacts/calendar/reminders on SQLite (reopen-after-restart tests green).
- Scheduler works: P1.2 `ReminderScheduler` lifecycle wired into FastAPI lifespan and the TUI; due-time firing + one-shot completion + repeating rescheduling tested.
- HTTP execution works: P1.5 `/execute` + `/execute/stream`, timeouts, cancellation, structured errors, 413/429 limits, metrics — all tested.
- Communication works: P1.6 real SMTP provider, outbound manager execution, retries, CAP approval gate, durable audit trail, test provider — tested with mocked transport (no network).
- Developer tools produce real results: P1.7 AST analyzers produce structured findings with evidence on real code; `/review` uses the engine.
- SQLite is reliable: P1.3 shared connection config, WAL, busy timeout, schema versioning, JSON table store; reliability tests green.
- State lifecycle is bounded: P1.4 LRU-bounded session cache/state, prune policies, rotation-to-archive; bounded tests green.
- Regression suite passes: **1922 passed / 0 failures**, 22 warnings (pre-existing categories only).
- Result: **P1 Core Implementation is COMPLETE** (P1.1–P1.7 + exit gate).

---

# 🟦 P2 — Framework & Platform Maturity

**Objective:** Transform Samaktha from a functioning agent into an extensible framework.

## P2.1 — Plugin Architecture

- [x] Plugin specification
- [x] Plugin manifest
- [x] Plugin identity
- [x] Plugin metadata
- [x] Plugin lifecycle
- [x] Plugin discovery
- [x] Plugin registry
- [x] Plugin loading
- [x] Plugin unloading
- [x] Dependency resolution
- [x] Capability declaration
- [x] Permission declaration
- [x] Plugin isolation boundaries
- [x] Plugin validation

**Completion record (P2.1):**
- Plugin specification + manifest: new `app/plugins/models.py` — `PluginManifest` (schema_version 1.0, id, name, version, kind, author, entry module path, dependencies, capabilities, permissions, metadata) is the canonical declaration; `PluginDependency`, `PluginCapability`, `PluginPermission` are typed sub-models; `key` is `id@version`.
- Plugin identity + metadata: `PluginIdentity` (plugin_id/name/version + `key`), `PluginMetadata` snapshot, and `PluginRecord.metadata_snapshot` expose stable identity and full current state; `PluginKind` (tool/provider/skill/personality) classifies contributions.
- Plugin lifecycle: `PluginState` state machine (discovered → registered → loading → loaded → active → unloading → unloaded, plus disabled/failed); `Plugin` ABC in `app/plugins/plugin.py` with async `start`/`stop` hooks; `PluginManager` drives activate/deactivate/reload transitions.
- Plugin discovery: `app/plugins/discovery.py` scans `*.plugin.json` (root) and `<dir>/manifest.json` (subdirs), skips unparseable/duplicate manifests, returns deterministic order.
- Plugin registry: `app/plugins/registry.py` — keyed `id@version`, rejects duplicates, `get_by_id` prefers highest version, kind/loaded filtering.
- Dependency resolution: `app/plugins/dependencies.py` — minimal semver (`app/plugins/semver.py`: parse, comparison, `*`, exact, `>=`, `^`, `~` constraints), resolves plugin_id deps to concrete versions, prefers already-loaded versions, topological load order, transitive closure per target, missing/cycle/constraint errors.
- Capability + permission declaration: manifests declare capability domains and permission scopes; `ToolPermission` is the only valid permission vocabulary; every declared capability must be provided by a contributed tool and every tool capability/permission must be declared (no silent extras).
- Plugin loading/unloading: `PluginManager.load` imports the entry module (`create_plugin` factory | `plugin` instance | `Plugin` subclass), validates, enforces isolation boundaries, registers contributions through the canonical registries — `ToolRegistry` (ToolInfo derived from the tool), `CommunicationRegistry` (new `register` guard against shadowing via has_provider), and `CapabilityRegistry` (new `register`/`unregister_domain`, rejects duplicate domains). Unload removes contributions in reverse order and blocks while loaded dependents remain.
- Plugin isolation boundaries: `app/plugins/isolation.py` — tools must be `Tool` instances, providers must be `CommunicationProvider` instances, undeclared permissions/capabilities are refused at load time; `PluginContext` exposes only registries (never the runtime dispatcher, CAP, or security stores), so plugin execution flows through the exact same CAP/security pipeline as system tools.
- Plugin validation: `app/plugins/validation.py` — semantic manifest checks (schema version, id/entry format, semver, dependency constraints, permission vocabulary, duplicate declarations) and structural checks on loaded instances (identity match, Tool types, unique tool names).
- Tests: new `tests/plugins/test_phase20_plugin_architecture.py` (53 tests) — models/identity/metadata, manifest validation, semver parse/ordering/constraints, discovery (root+subdir, skip-invalid, dedup, order), registry (duplicates, version preference, state), dependency resolution (order, missing, constraints, cycles, prefer-loaded, transitive closure), manager loading (contributions, auto-load deps, missing dep, entry-symbol, identity mismatch, undeclared permission/capability, tool-id collision, provider plugin), unloading (removal, dependent block, reload), lifecycle (deactivate/activate), capability-registry additions, and structural plugin validation.
- Results: `tests/plugins` 53/53; full suite **1975 passed / 0 failures** (baseline 1922 + 53). 21 warnings (pre-existing categories only).
- Invariants preserved: CAP, security wiring, canonical runtime path (plugin tools are ordinary `Tool` instances in the same `ToolRegistry` the orchestrator uses), app boot, full suite green.

## P2.2 — Plugin SDK

- [x] `samaktha-plugin` CLI
- [x] Plugin scaffolding
- [x] Development template
- [x] Local plugin installation
- [x] Plugin testing utilities
- [x] Plugin documentation
- [x] Example plugin
- [x] Example provider
- [x] Example tool

**Completion record (P2.2):**
- `samaktha-plugin` CLI: new `app/plugins/sdk/cli.py` + `app/plugins/sdk/__init__.py` — `new` (scaffold), `install`, `uninstall`, `list`, `validate`, `test` subcommands; console entry point `samaktha-plugin = "app.plugins.sdk.cli:main"` added to `pyproject.toml`. The CLI never bypasses manifest validation or the plugin architecture.
- Plugin scaffolding + development template: `app/plugins/sdk/scaffold.py` — `scaffold_plugin` derives a manifest-safe id (`template_plugin_id`), entry module name and class name, and writes a complete plugin directory (manifest.json, entry module, `tests/test_<module>.py`, README.md) for kinds `tool`/`provider`/`skill`/`personality`; every scaffolded artifact is validated by P2.1 validation before writing; `ScaffoldError` for invalid kind/name/existing directory.
- Local plugin installation: `app/plugins/sdk/install.py` — `install_plugin` validates, verifies the entry module exists, copies to `<plugins-dir>/<id>/` (native P2.1 discovery layout), duplicate guard + `force`; `uninstall_plugin` (idempotent), `list_installed`, `validate_plugin_directory`; `resolve_plugins_dir` honors explicit override then `SAMAKTHA_PLUGIN_DIR`/`Settings.plugin_dir` (new `plugin_dir` field, default `samaktha_plugins`).
- Plugin testing utilities: `app/plugins/sdk/testing.py` — `PluginHarness` provides a fresh `PluginManager` wired to fresh tool/communication/capability registries plus sys.path management, with `load`/`load_sync`/`unload`/`is_loaded`/`keys`/`cleanup`.
- Plugin documentation: new `docs/PLUGINS.md` — quick start, plugin anatomy, manifest reference, validation/isolation contract, dependencies, installation, testing with `PluginHarness`, examples, references.
- Example plugin: `examples/plugins/hello/` — greeting tool with lifecycle hooks, manifest, README and pytest suite.
- Example provider: `examples/plugins/health_probe/` — deterministic `CommunicationProvider` (no network), manifest, README and pytest suite.
- Example tool: `examples/plugins/wordbox/` — word/character-counting tool, manifest, README and pytest suite.
- Tests: new `tests/plugins/test_phase21_plugin_sdk.py` (41 tests) — id/module derivation, scaffold layout+validation per kind, scaffolded tool/provider load via `PluginHarness`, invalid kind/name/existing-dir errors, install/uninstall/list (valid, invalid manifest, missing entry, duplicate+force, idempotent uninstall, empty), settings env override, harness fresh registries/unload/cleanup/load_sync, CLI new/validate/install/list/uninstall round-trips and error paths, CLI `test` running a scaffolded suite, and all three example plugins validating and loading.
- Results: `tests/plugins` 94/94 (53 P2.1 + 41 P2.2); full suite **2016 passed / 0 failures** (baseline 1975 + 41). 22 warnings (pre-existing categories only; +1 instance of an existing category).
- Invariants preserved: CAP, security wiring, canonical runtime path (SDK exercises the real P2.1 manager — no parallel loading path), app boot, full suite green.

## P2.3 — Versioned Capability Contracts

- [x] Tool capability contract
- [x] Provider capability contract
- [x] Skill capability contract
- [x] Personality capability contract
- [x] Versioning strategy
- [x] Semantic versioning
- [x] Compatibility validation
- [x] Breaking-change detection
- [x] Contract tests
- [x] Migration strategy

**Completion record (P2.3):**
- New package `app/capabilities/` — a versioned, machine-readable capability-contract layer shared by system tools and plugin contributions (builds on `PluginKind` for the four contribution kinds and on the P2.1 semver engine; no parallel versioning code).
- Contract models (`app/capabilities/models.py`): `CapabilityContract` (kind/name/version/description + capability surface: capabilities, actions, permissions, parameters, output keys, metadata; `key` = `kind:name`, `semver` = strict parsed version), `ContractParameter`, `ContractChange`, `ContractChangeKind`, `ContractComparison` (compatible + breaking/additive change subsets).
- Tool capability contract: `contract_for_tool(info)` builds a contract from a registered tool's `ToolInfo` (capabilities, supported actions, permissions, JSON-schema-derived parameters incl. required flags, metadata source).
- Provider capability contract: `contract_for_provider(...)` builds a provider contract from explicit declarations (provider_id, capabilities, actions, permissions).
- Skill capability contract: `contract_for_skill(...)` builds a skill contract (capabilities, parameters, output keys).
- Personality capability contract: `contract_for_personality(...)` builds a personality contract (capabilities, parameters).
- Versioning strategy (`app/capabilities/versioning.py`): semver discipline — `recommended_bump` (none/patch/minor/major) derived from structural surface changes (ignores informational version notes), `version_respects_bump` verifies an author bumped correctly, `compatible_range` = `^major` consumer constraint.
- Semantic versioning: reuses `app/plugins/semver.py` (`SemanticVersion`/`satisfies`) for parsing, ordering and consumer constraints; `is_semver_compatible` = same major, non-downgrade.
- Compatibility validation (`app/capabilities/compat.py`): structural — a new contract is compatible iff it preserves every capability/action/permission/parameter/output key of the old surface (strict superset); same-version surface drift and downgrades are breaking; unrelated keys raise `ContractError`. `is_compatible`, `compare_contracts`, `is_semver_compatible`.
- Breaking-change detection: `breaking_changes` / `ContractComparison.breaking_changes` enumerate removals and newly-required parameters; additive changes (new capability/action/permission/optional parameter/output key) are non-breaking. A version number is never trusted alone.
- Versioned contract registry (`app/capabilities/registry.py`): `ContractRegistry` keeps full history per `kind:name` (sorted ascending, duplicate-version rejection), `get`/`latest`/`versions`/`has`/`all`, kind-scoped keys, and `is_compatible_with_latest` returning a `ContractComparison` against the newest registered version.
- Migration strategy (`app/capabilities/migration.py`): `MigrationPlan` (from/to version, compatible, requires_consumer_update, change list), `plan_migration`, `upgrade_path` (registry-based, optional from/to versions, detects downgrades), `is_consumer_compatible` (consumer constraint vs contract version).
- Tests: new `tests/contracts/test_phase30_capability_contracts.py` (39 tests) — models/defaults/keys/parameter helpers, semver parsing + versioning discipline, compatibility (additive/breaking/optional-vs-required params/output keys, same-version drift, downgrades, unrelated keys), breaking-change detection, all four builders (incl. JSON-schema parameter derivation), registry (history, kind scoping, duplicate rejection, string kinds, compatibility-with-latest), migration planning (compatible/breaking/downgrade paths, consumer constraints), and integration with real plugin contributions (loading `examples/plugins/wordbox` and `health_probe` through `PluginHarness` and building contracts from the live registries).
- Results: `tests/contracts` 41/41 (2 pre-existing + 39 new); full suite **2055 passed / 0 failures** (baseline 2016 + 39). 22 warnings (pre-existing categories only).
- Invariants preserved: CAP, security wiring, canonical runtime path (contracts are a read-only metadata layer; plugin loading/registries untouched), app boot, full suite green.

## P2.4 — Runtime Hot-Loading

- [x] Load plugin without restart
- [x] Unload plugin safely
- [x] Reload plugin
- [x] Dependency checks
- [x] Active-task protection
- [x] State migration
- [x] Failure rollback
- [x] Plugin lifecycle events

**Completion record (P2.4):**
- Runtime hot-loading built directly on the P2.1 `PluginManager` — no parallel plugin paths. New primitives `app/plugins/events.py` (`PluginLifecycleEvent` frozen dataclass: event/plugin_key/state/details/timestamp; `PluginEventBus` with per-event + `*` wildcard subscribe/`on`/unsubscribe, idempotent unsubscribe, `listener_count`, `clear`) and `app/plugins/activity.py` (`PluginActivityTracker` reference-counted `begin`/`end`/`in_use`/`active_tool_ids`, idempotent `end`).
- Load plugin without restart: `PluginManager.load_directory(directory, *, auto_load_dependencies=True)` discovers and registers new manifests under a directory and loads them in one call; already-registered plugins are left untouched (their instances and states preserved); one broken plugin is recorded FAILED and skipped without blocking the others.
- Unload safely + dependency checks: `unload` reuses the P2.1 reversal order via extracted `_unregister_contributions` (idempotent), enforces loaded-dependents and active-task checks; new public `dependent_keys`/`has_loaded_dependents`.
- Active-task protection: `_ensure_no_active_contributions` consults the optional `PluginActivityTracker` and raises `PluginUnloadError` naming the in-use tools before any unload/reload swap; with no tracker, behavior is unchanged.
- Transactional reload: `PluginManager.reload` snapshots instance/tools/providers/contributions/state/loaded_at plus `snapshot_state()` data; enforces dependency + active-task guards; on load failure it unregisters any partially-registered contributions and re-registers the previous surface (rollback), restoring the prior plugin instance and state. If re-registration itself fails the record is marked FAILED with a "Rollback failed" error — rollback is never silent.
- State migration: `Plugin.snapshot_state()` / `Plugin.restore_state(state)` hooks (base no-ops); the manager calls restore on the fresh instance after a successful reload (awaiting coroutine hooks).
- Lifecycle events: manager emits `registered`/`loading`/`active`/`unloading`/`unloaded`/`failed`/`reloading`/`rollback`/`activated`/`deactivated` through the optional event bus (host-facing convenience `PluginManager.on`); `active` events carry the contributions list.
- Tests: new `tests/plugins/test_phase24_runtime_hot_loading.py` (17 tests) — event-bus and activity-tracker primitives, `load_directory` (fresh plugins only, broken-plugin skip, instance preservation), unload/reload blocked while a tool is in use (and unaffected without a tracker), reload fresh instance, reload blocked by loaded dependent, state migration across reload (counter preserved, snapshot/restore hooks invoked), failure rollback restoring the previous instance, partial-registration cleanup, honest rollback failure, and event ordering/state/details across the full lifecycle.
- Results: `tests/plugins` + `tests/contracts` 157/157; full suite **2072 passed / 0 failures** (baseline 2055 + 17). 22 warnings (pre-existing categories only).
- Invariants preserved: CAP, security pipeline, single canonical runtime path (hot-loading only re-uses the existing load/unload machinery), app boot, full suite green.

## P2.5 — Governance Maturity

- [x] Policy-as-code foundation
- [x] Capability permissions
- [x] Provider permissions
- [x] Tool permissions
- [x] Risk classification
- [x] Approval policies
- [x] Immutable execution records
- [x] Governance audit trail
- [x] Policy violation handling
- [x] Rollback/recovery policy

**Completion record (P2.5):**
- New package `app/governance/` implements policy-as-code governance on the existing `ActionRisk`/`ApprovalDecision` and canonical `ToolPermission`/`ToolPolicy` vocabularies — no new parallel models. `models.py` defines `TargetType` (tool/provider/capability/action), `PermissionRule` + `CapabilityPermissionRule`/`ProviderPermissionRule`/`ToolPermissionRule`, `RiskRule`, `ApprovalRule`, `RollbackRule`, the versioned `GovernancePolicy` document (`key = policy_id@version`, `rule_for`, `extra="forbid"`), the frozen `GovernanceDecision` (with `allowed`), and the immutable `ExecutionRecord`/`AuditEntry` (frozen, hash-chained via sha256 of canonical JSON over `previous_hash` + payload).
- Policy-as-code foundation: `policy.py` — `validate_policy` (dict or model; reports empty id/name, bad semver via `SemanticVersion`, duplicate per-target rules), `load_policy`/`load_policy_file` (JSON), `PolicyRegistry` (idempotent-`id@version` store with duplicate rejection, `get`/`has`/`latest`/`list`/`count`/`clear`, `latest` picks the highest semver).
- Risk classification: `risk.py` — `RiskClassifier.classify` returns `(ActionRisk, reasons)`; policy `risks` rules first (target/target_type/scope match), then deterministic defaults: admin/delete → CRITICAL, execute/network or approval-required → HIGH, write/modify → MEDIUM, else policy `default_risk`/LOW; `risk_at_least` + `security_level_for` bridge to the security vocabulary.
- Approval policies: `approval.py` — `ApprovalPolicyEngine.required`/`decision`; policy `approvals` rules take precedence (first match, `require`/exempt), then per-rule `approval_required`, then risk ≥ HIGH, then policy `default_approval_required`; decisions use the existing `ApprovalDecision` (allow/ask_user/deny; DENY when a declared/requested permission is not granted).
- Permission enforcement: `engine.py` `GovernanceEngine` — the single entry point. `evaluate` resolves the active policy (explicit `policy_id` or `default_policy_id` via `set_default_policy`), grants rule permissions for tools/providers and declared permissions for capabilities (the capability rule's permissions are the *required* set, checked against the provider tool's declared set), computes denied permissions, classifies risk, derives the approval decision, and audits every decision. `enforce_tool`/`enforce_capability`/`enforce_provider` raise `PolicyViolationError` on any non-allow outcome; without any registered policy the engine is permissive (grants declared permissions), preserving the canonical runtime baseline.
- Immutable execution records: `records.py` — `ExecutionRecordStore` is append-only (no update/delete/clear API), rejects duplicate `record_id`s, and chains each record's sha256 hash to the previous one; `verify_chain` recomputes the whole chain to detect tampering; optional `SQLiteJsonTable` backing persists the chain (loaded in `recorded_at` order and re-verified). `build_execution_record` factory leaves the hash to be sealed on append.
- Governance audit trail: `audit.py` — `GovernanceAuditLog` append-only, monotonic `seq`, hash-chained, with `query(category/action/subject/result)` filters and `verify_chain`; every evaluate/violation/execution decision is audited (categories: governance/execution/violation).
- Policy violation handling: `violations.py` — frozen `PolicyViolation` + `PolicyViolationError`; `ViolationHandler.blocked` returns a deterministic blocked payload (governance_blocked/violation/reason/decision/risk) and audits the violation — never silent, never mutating the stores.
- Rollback/recovery policy: `rollback.py` — `RollbackPolicy.should_rollback`: policy `rollbacks` rules first (force/exempt per `when` failure/denial), else high/critical risk + rollback support + (failed or denied), else any supported failure; engine-level `should_rollback` resolves the active policy.
- Runtime integration (optional, zero behavior change when unset): `ToolExecutor(tool_manager, tool_guard, governance=None)` — governance gate after the ToolGuard gate; blocked tools return FAILED with `governance_blocked`/decision/risk/record_id metadata and an immutable record (BLOCKED/APPROVAL_REQUIRED); allowed tools execute via `execute_tool_with_context` with a `ToolContext(granted_permissions, timeout_s)` so the dispatcher enforces the granted scope; outcomes are recorded (EXECUTED/FAILED/ROLLED_BACK with rollback decision metadata). `ProviderExecutor(provider_manager, governance=None)` — provider rules gate execution before any provider call. Production wiring (`app/core/app.py`) constructs one shared `GovernanceEngine` and passes it to both executors; the wiring test `tests/security/test_phase55_production_wiring.py` still passes.
- Tests: new `tests/governance/test_phase50_governance_maturity.py` (55 tests) — policy load/validate/registry + semver `latest`, risk defaults + rule override + `risk_at_least`/`security_level_for`, approval allow/ask_user/deny + rule override, tool/capability/provider permission enforcement, append-only hash-chained records (duplicate rejection, tamper detection, SQLite backing persistence), audit trail (query, chain, tamper, persistence), violation handling + engine-denial auditing, rollback defaults/rules/force-exempt/engine resolution, and ToolExecutor/ProviderExecutor integration (allowed + recorded, blocked + recorded, rollback on failure, ungoverned behavior unchanged) plus production wiring.
- Results: `tests/governance` 55/55; full suite **2127 passed / 0 failures** (baseline 2072 + 55). 22 warnings (pre-existing categories only).
- Invariants preserved: CAP governance, security pipeline (ToolGuard still first), single canonical runtime path (governance is an optional, in-band layer on the existing executors), app boot, full suite green.

## P2.6 — Advanced Runtime

- [x] Task scheduler hardening
- [x] Parallel execution
- [x] Worker lifecycle
- [x] Task dependency graph
- [x] Resource allocation
- [x] Concurrency controls
- [x] Cancellation
- [x] Retry policies
- [x] Failure isolation
- [x] Result aggregation

**Completion record (P2.6):**
- P2.6 hardened the existing Phase-18 parallel runtime (`app/runtime_parallel/`, consumed by `RuntimeExecutionPool`/`RuntimeScheduler` and driven from `RuntimeEngine.run_batch`) — no parallel implementations, no new subsystems.
- Task dependency graph + scheduler hardening: `DependencyResolver.validate` now raises on cycles AND unknown dependency references (previously unknown deps silently vanished tasks from results); `schedule()` runs `validate` up front. `TaskStatus.CANCELLED` added to the canonical enum.
- Concurrency controls: `RuntimeScheduler.max_parallelism` was dead — now enforced via an `asyncio.Semaphore` around worker execution. `RuntimeEngine(max_parallelism=...)` threads the cap through both the scheduler path and a new bounded wrapper in `RuntimeExecutionPool.execute_batch` (semaphore optional; `None` keeps the unbounded baseline so existing behavior is unchanged).
- Failure isolation: level `asyncio.gather` now uses `return_exceptions=True` and converts any escaping exception into a FAILED result for that task, so one worker's unexpected exception can no longer abort the whole batch. Dependency-failed tasks still fail with "dependency failed"; dependents of cancelled tasks fail with "dependency cancelled".
- Worker lifecycle: per-task `timeout` (from `task.metadata["timeout"]`) is enforced with `asyncio.wait_for` → FAILED "worker timeout after Xs"; worker `status` transitions to COMPLETED/CANCELLED/FAILED properly; `WorkerManager.count`/`active_count` added.
- Resource allocation: `ResourceAllocator` is now thread-safe and gained `release()` (returns budget after each worker — previously allocated resources were never returned, permanently starving the budget) and `available()`; the scheduler releases allocations in a `finally`.
- Retry policies: `FailureRecoveryEngine.should_retry` fixed (only retries FAILED workers — previously any non-COMPLETED state, including CANCELLED, was retried — and now honors `attempt <= max_retries` so N retries really happen) plus `backoff_ms` exponential backoff; the scheduler runs a retry loop with backoff and records each attempt (provenance `runtime:<id>:retryN`) in history.
- Cancellation: `RuntimeScheduler.cancel(task_id)` / `cancel_all()` / `is_cancelled(task_id)` — cancelled tasks become CANCELLED (worker lifecycle CANCELLED) without executing; dependents are marked cancelled.
- Result aggregation: `ResultAggregator` (previously wired nowhere) now selects the best attempt (highest-confidence success first) across retries and is used to choose the returned `RuntimeResult`.
- Worker metrics (`record_success`/`record_failure`) are now recorded per final task outcome in the scheduler, preserving the Phase-4.3 invariant (`failed_executions` counts tasks that ultimately failed, not attempts).
- Tests: new `tests/runtime_parallel/test_phase26_advanced_runtime.py` (20 tests) — validate rejects unknown deps + cycles; max_parallelism cap (==2) and unbounded parallelism (==4); failure isolation keeps siblings running; dependency failure blocks dependents; specific-task cancellation propagates to dependents (CANCELLED lifecycle) and cancel-all; retry-until-success honoring max_retries + `:retryN` provenance; stop-after-max-retries; backoff timing; worker timeout → FAILED; resources released after workers (budget restored); best-attempt aggregation; allocator release/available; retry semantics (no retry for RUNNING/COMPLETED/CANCELLED); manager active/status counts; pool max_parallelism cap; aggregator prefers success-then-confidence. Existing `tests/runtime_parallel/test_phase18_multi_agent.py` (11 tests) unchanged and green.
- Results: `tests/runtime_parallel` 31/31; full suite **2147 passed / 0 failures** (baseline 2127 + 20). 22 warnings (pre-existing categories only).
- Invariants preserved: CAP governance, security pipeline, single canonical runtime path (hardening applied in-band on the existing scheduler/pool, both still driven by `RuntimeEngine.run_batch`), app boot, Phase-4.3 worker-metrics invariant, full suite green.

## P2.7 — Observability

- [x] Execution tracing
- [x] Correlation IDs
- [x] Task IDs
- [x] Tool metrics
- [x] Provider metrics
- [x] Memory metrics
- [x] Governance metrics
- [x] Error metrics
- [x] Runtime metrics
- [x] Structured logs
- [x] Execution timeline
- [x] Diagnostic reporting

**Completion record (P2.7):**
- P2.7 wired the *existing* telemetry infrastructure into the production paths — no new observability framework, no parallel telemetry systems. Every collector now records during real execution and is exposed through the pre-existing aggregated `/metrics` endpoint.
- Governance metrics (new): `app/governance/metrics.py` — `GovernanceMetricsCollector` (+ pydantic snapshot) recording evaluations, allow/ask-user/deny decisions, blocks, violations and rollbacks. Wired additively into `GovernanceEngine`: `evaluate` records the decision split, `enforce_tool`/`enforce_capability`/`enforce_provider` record blocks on `PolicyViolationError`, `violation` records violations, `should_rollback` records rollback decisions; `get_metrics()` accessor added. Zero behavior change (governance tests unchanged).
- Runtime metrics: `RuntimeEngine` already recorded runtime + worker metrics; added the missing `get_worker_metrics()` accessor so both are observable. `ModelRouter.get_metrics`, `ToolManager.get_metrics`, `MemoryManager.get_metrics`, `WorkflowEngine.get_metrics`, `SamakthaOrchestrator.get_metrics`, `ProviderManager.list_provider_metrics` and `GovernanceEngine.get_metrics` now all feed `/metrics`.
- Registration: `create_app` registers all subsystem collectors into the shared `TelemetryRegistry` (`runtime`, `workers`, `tool`, `memory`, `workflow`, `orchestrator`, `router`, `provider`, `governance` in addition to the existing `http`/`security`/`streaming`) via a hardened `snapshot_adapter` (pydantic snapshots dumped to flat dicts; zero-arg callables supported) and a new `provider_metrics_adapter` (per-provider dicts). `/metrics` now returns all 12 collectors with error/failure counters per domain (http failed/timeouts, tool failures, provider failures, runtime dispatch, worker failed_executions, orchestrator failures, governance deny/blocks, security tool_denials/blocked_requests).
- Execution tracing in production: `app/api/execute.py` sets `enable_tracing` on the `RuntimeContext` for both `/execute` and `/execute/stream`; `SamakthaOrchestrator.run_pipeline` creates the `ExecutionTrace` up front (so even security-blocked requests are observable), emits `orchestrator.started`/`orchestrator.completed`/`security.input.blocked`, and attaches the trace to the `ExecutionReport` (existing wiring) so the `/execute` response `diagnostics` carries the full execution timeline. Existing runtime/workflow/executor trace event emission (`runtime.batch.*`, `runtime.provider.*`, `runtime.tool.*`, `worker.execution.*`, `workflow.*`) is now live in production.
- Correlation IDs: the API layer now derives the execution `request_id` from the middleware correlation id (the `x-request-id` header, uuid fallback) so header → response `request_id` → `RuntimeContext.request_id` → `ExecutionTrace.request_id` → execution report are one id. `app/core/logging.py` gains a `request_id` contextvar (`set_request_id`/`clear_request_id`, set per request by the HTTP middleware and cleared in `finally`) and a `CorrelationFilter` that injects it into every log record.
- Structured logs: `Settings.log_format` (`text` default, `json` opt-in) + `configure_logging` — a `JsonFormatter` (timestamp/level/logger/message/request_id/exc_info, one JSON object per line) and a `TextFormatter` that appends `[request_id=…]` when a correlation id is active.
- Error metrics: all per-domain failure counters are exposed via `/metrics` (no new parallel error counter; the existing failures/timeouts/denials/blocks are the single source of truth).
- Diagnostic reporting: new HTTP `/diagnostics` endpoint reuses the existing `SystemDiagnostics` sweep (the TUI `/doctor` engine) as JSON — version, healthy, health_percentage, per-section checks.
- Secret hardening: trace events no longer carry the raw request text (removed `request=` from `orchestrator.started`/`security.input.blocked`), so response `diagnostics` cannot leak credentials via the timeline; regression-tested.
- Tests: new `tests/metrics/test_phase27_observability.py` (30 tests) — governance collector unit + engine integration (allow/deny/block/rollback), snapshot/provider adapters, runtime worker-metrics accessor, all-12-collector `/metrics` aggregation, security-blocked + full-pipeline trace/correlation, `x-request-id` header propagation to response and trace, JSON/text log formatters + correlation filter, `/diagnostics`, and trace secret-redaction.
- Results: `tests/metrics` 60/60 (30 P2.2.3 + 30 P2.7); full suite **2177 passed / 0 failures** (baseline 2147 + 30). 102 warnings (pre-existing categories only).
- Invariants preserved: CAP governance (governance metrics additive only), security pipeline (ToolGuard still first; output filter still redacts), single canonical runtime path (`RuntimeEngine.run_batch` untouched; `app/runtime_parallel` unchanged from P2.6), Phase-4.3 worker-metrics invariant, app boot, full suite green.

## P2.8 — Personality & Voice Integration

- [x] Personality registry
- [x] Personality lifecycle
- [x] Personality switching
- [x] Personality persistence
- [x] Personality → GAMBIT integration
- [x] Voice → intent pipeline
- [x] Voice → CAP pipeline
- [x] Voice → execution pipeline
- [x] Voice execution observability

**Completion record (P2.8):**
- P2.8 wired the *existing* personality and voice infrastructure into the production paths — no new personality/voice framework, no parallel systems. Personality is now a first-class, switchable, persisted attribute of the production orchestrator; the voice subsystem gains deterministic intent classification, spoken CAP approvals, and execution observability — all through pre-existing pipelines.
- Personality registry (new): `app/personality/registry.py` — `PersonalityDefinition`, `PersonalityRegistry` (register/register_profile/unregister/get/require/contains/list/validate), `PersonalityValidationError`, `DEFAULT_PERSONALITY_ID = "samaktha-core"`, `default_personality_registry()` seeded with the production `SAMAKTHA_IDENTITY_PROFILE`.
- Personality lifecycle + persistence (new): `app/personality/lifecycle.py` (`PersonalityLifecycleManager` — activate/deactivate/current/current_profile/available; re-activates a persisted selection at startup; tolerates a misconfigured default id) and `app/personality/persistence.py` (`PersonalityPersistence` — atomic tmp+rename JSON read/write of the active `profile_id`; missing/invalid content loads as None). `app/config/settings.py` gains `personality_profile` (`samaktha-core`) and `personality_state_path` (`data/personality_state.json`).
- Personality switching: `PersonalityEngine.set_profile` added; `SamakthaOrchestrator` builds its deterministic engine from the manager's current profile, exposes `get_personality`/`list_personalities`/`switch_personality` (validated via the manager, persisted), and registers the manager+registry from `create_orchestrator`. New API: `GET /personality` (active + available), `PUT /personality/{profile_id}` (switch; 404 on unknown id, 503 when unsupported).
- Personality → GAMBIT: `Planner.plan`/`plan_with_capability_check` accept an optional `personality_context`; the orchestrator derives it from the active profile + the personality engine's evaluation (profile_id/name/tone/reasoning/explanation) and passes it through `_planner_plan` (signature-tolerant fallback for older planners). The planner records an "Active personality" directive in `planner_reasoning` and `notes` — no new planning path, no prompt injection surface.
- Voice → intent pipeline: `VoiceManager` now runs the existing `IntentEngine` over each transcript, emits `VOICE_TRANSCRIBED` with `{"text", "intent"}` (deterministic enum value), and records the intent in voice metrics.
- Voice → CAP pipeline: `VoiceSession._wire_approval` routes `AgentEvent.PAUSE_REQUESTED` (with task id + pause payload) into a voice approval loop — announce the pause, listen for an answer, `resume_after_approval` with `permit.decision` allow/deny, 30s timeout. Transcribed answers are classified (whole-phrase + leading-word accept/reject sets). Two real bugs fixed in the voice loop: an approved action was resumed with a `deny` permit (decision result vs raw-word mapping) and a timed-out approval left stale pending state.
- Voice → execution pipeline: `VoiceSession.submit_text(text)` runs text through the existing `VoiceRuntimeAdapter` → `ProductionAgentRuntime` → orchestrator path (provider-only chunks; tool/error events filtered or surfaced as speech). No bypass of the canonical pipeline, no separate voice HTTP endpoint, still a single runtime instance.
- Voice execution observability (new): `app/voice/metrics.py` — `VoiceMetricsCollector` + pydantic `VoiceMetricsSnapshot` (sessions, utterances, transcriptions/errors, per-event counts, per-intent counts, interruptions, cancelled responses, approval request/allow/deny/timeout counters, STT/runtime/TTS/first-word latency averages). `get_metrics()` returns a `TelemetrySnapshot` so it registers into the shared `TelemetryRegistry` (P2.7 pattern). `create_app` registers a process-scoped `"voice"` collector (13th collector in `/metrics`); `VoiceSession.start` also registers its per-session collector into the telemetry it receives.
- Adversarial audit: no secrets/tokens in the new code or events; `events`/`intents` dicts are bounded by enum values (no unbounded user-input keys); orchestrator stays voice-agnostic (no "voice" strings); voice import boundaries and `VoiceSession` source-string constraints preserved (architecture tests green); no execution-semantics change (personality_context is additive and defaults to None; voice changes are confined to the voice path).
- Tests: new `tests/personality/test_phase28_personality.py` (30 tests — registry, persistence, lifecycle, engine switching, orchestrator switching, planner directive, orchestrator→planner context pass-through + legacy fallback, personality API) and `tests/voice/test_phase28_voice.py` (23 tests — collector unit + TelemetrySnapshot shape, VoiceManager intent/error metrics + `VOICE_TRANSCRIBED` intent, `submit_text` streaming/suppression/error, CAP allow/deny/timeout/transcribed-answer flows, telemetry registration, `/metrics` 13-collector aggregation).
- Results: `tests/personality` 30/30 + `tests/voice` + others; full suite **2230 passed / 0 failures** (baseline 2177 + 53). 101 warnings (pre-existing categories only).
- Invariants preserved: CAP governance (voice approvals route through `ProductionAgentRuntime.resume` with a permit), security pipeline, single canonical runtime path, Phase-4.3 worker-metrics invariant, voice architecture/import boundaries, app boot, full suite green.

## P2.9 — Developer Experience

- [x] CLI architecture
- [x] TUI architecture
- [ ] Execution timeline
- [ ] Tool cards
- [ ] Provider cards
- [ ] Approval interface
- [ ] Runtime diagnostics
- [ ] Developer documentation
- [ ] Architecture documentation
- [ ] Plugin development documentation

**Completion record (P2.9 — CLI architecture):**
- Rebuilt `app/cli.py` as a structured, argparse-based console command — the single `samaktha` entry point (`pyproject.toml` unchanged). Every command is a thin wrapper around existing production infrastructure; the CLI never re-implements logic.
- Commands: `samaktha` (default → TUI), `tui`, `backend [--host H] [--port P]`, `doctor`, `version`, `--version`, and `personality list|show|set <id>`. Legacy `--tui` / `--backend` flags preserved verbatim (P0.4 architecture guards still green).
- `doctor` runs the same deterministic `SystemDiagnostics` sweep as the TUI `/doctor` and the `/diagnostics` endpoint (orchestrator-backed via `build_production_runtime`, with a graceful config-level fallback) and returns exit code 0 healthy / 1 critical.
- `personality` reuses the P2.8 `PersonalityLifecycleManager` + `PersonalityPersistence` (default registry, configured state path) — `set` validates via the shared registry and persists the switch so the orchestrator loads it at startup.
- `main.py` is now a thin delegate to `app.cli.main` (verified `main.main is app.cli.main`), so the command-line surface lives in exactly one place; `_run_backend`/`_run_tui` remain re-exported for the P0.4 tests.
- Tests: new `tests/cli/test_phase29_cli.py` (19 tests) — default/legacy/subcommand dispatch, backend host/port overrides + uvicorn launch, `--version`/`version`, doctor exit-code semantics + runtime fallback, personality list/show/set persistence + unknown-id error.
- Results: full suite **2249 passed / 0 failures** (baseline 2230 + 19). 101 warnings (pre-existing categories only).
- Adversarial audit: no secrets/tokens in CLI code or output (provider checks report presence, never values); no new dependencies; no parallel CLI surface; no side effects beyond the intended persisted personality selection; full suite green.

**Completion record (P2.9 — TUI architecture):**
- Formalized the TUI's runtime-interaction architecture on top of the existing Phase-6.x widgets — no redesign, no new panels, no parallel event paths. The TUI now has exactly one canonical runtime-stream consumer that all runtime interaction flows through.
- Canonical consumer (new): `MainScreen._consume_runtime_stream(stream, error_prefix)` in `app/tui/app.py` owns provider-chunk streaming, the tool-output visibility gate (`settings.debug` / `show_tool_output`), error rendering, and the `finally`-guaranteed input-bar restore. Both `_stream_response` (message flow) and `_submit_resume` (CAP approval resume flow) now delegate to it — eliminating the ~70-line duplicated stream loops. The tool-output gate now lives in exactly one place.
- Real bug fixed by the consolidation: submitting a resume with no runtime attached previously returned without re-enabling the input bar (leaving the TUI stuck); the no-runtime path now restores input + focus (regression-tested).
- Reload binding completed (was a stub): `ctrl+r` "Reload" now saves the active session and re-reads its persisted state via the new `CommandRouter.reload_session` (returns a `CommandResult` with the persisted `message_count`; tolerant of missing sessions and demo mode). `_apply_command_result` handles the `reload_session` action, refreshing the active session id, message count, and shell-history binding.
- Cleanup: the in-class `from textual.widgets import Button` import was hoisted to module top; the demo-mode echo path was extracted into `_consume_demo_response`.
- Tests: `tests/tui/test_phase29_tui_architecture.py` (17 tests) — structural checks (reload no longer a stub, both stream paths delegate, gate defined once, module-level Button import) plus behavioral checks via a Textual `run_test` harness (provider token streaming, non-dict item tolerance, tool-output gate on/off, failure recovery restoring input, no-runtime resume restoring input, reload state application) and the `CommandRouter.reload_session` contract (persisted count round-trip, missing session, no manager). `tests/tui/test_tool_output_visibility.py` updated to assert the gate lives in the canonical consumer.
- Results: `tests/tui` + `tests/cli` + `tests/architecture` + `tests/agent` 329/329; full suite **2267 passed / 0 failures** (baseline 2249 + 18). 101 warnings (pre-existing categories only).
- Invariants preserved: TUI import boundaries (AST guard — `app/tui/*` only reaches `app.agent.*`), single canonical runtime path, Phase-5.8.1 tool-output visibility semantics, app boot, full suite green.

### P2 Exit Gate

- [ ] Plugins can be created
- [ ] Plugins can be discovered
- [ ] Plugins can be validated
- [ ] Plugins can be loaded
- [ ] Plugins can be versioned
- [ ] Capability contracts are enforced
- [ ] Governance is auditable
- [ ] Runtime parallelism is controlled
- [ ] Observability covers execution
- [ ] Developer tooling is usable

---

# 🟪 P3 — Distributed Platform & Ecosystem

**Objective:** Scale Samaktha beyond the local single-agent architecture.

> P3 should not block the current framework-completion milestone.

## P3.1 — Distributed Runtime

- [ ] IPC worker support
- [ ] TCP worker support
- [ ] Remote workers
- [ ] Worker discovery
- [ ] Worker health
- [ ] Task routing
- [ ] Distributed scheduling
- [ ] Failure recovery

## P3.2 — Multi-Tenancy

- [ ] Tenant identity
- [ ] Tenant isolation
- [ ] Resource quotas
- [ ] Capability isolation
- [ ] Memory isolation
- [ ] Execution isolation
- [ ] Tenant-level observability

## P3.3 — Agent Networking

- [ ] Agent identity
- [ ] Agent discovery
- [ ] Agent-to-agent communication
- [ ] Capability negotiation
- [ ] Secure routing
- [ ] Cross-agent governance

## P3.4 — Ecosystem

- [ ] Public plugin registry
- [ ] Plugin publishing
- [ ] Plugin discovery
- [ ] Plugin trust model
- [ ] Marketplace
- [ ] Provider ecosystem
- [ ] Tool ecosystem
- [ ] Community SDK

## P3.5 — Production Hardening

- [ ] Load testing
- [ ] Stress testing
- [ ] Long-running tests
- [ ] Failure injection
- [ ] Recovery testing
- [ ] Security testing
- [ ] Resource exhaustion testing
- [ ] Deployment automation
- [ ] Upgrade/rollback testing

---

# 🎯 Milestone Definition

## 🟥 P0 — Correct

> **Samaktha does what its architecture says it should do.**

- [ ] P0 complete

## 🟧 P1 — Complete

> **Samaktha's core architecture works end-to-end.**

- [ ] P1 complete

## 🟦 P2 — Framework

> **Samaktha can be extended, governed, observed, and developed as a framework.**

- [ ] P2 complete

## 🟪 P3 — Scale

> **Samaktha can operate as distributed infrastructure and support an ecosystem.**

- [ ] P3 complete

---

# 🚀 Current Major Milestone

The immediate target is:

**P0 + P1 + P2**

This represents the transition from:

> **Architecture ≫ Implementation**

to:

> **Architecture ≈ Implementation**

After P2, Samaktha's next major stage is distributed/platform-scale development through P3.

---

## Progress Summary

| Milestone | Status |
|---|---|
| 🟥 P0 — Correctness | ✅ Complete (exit gate passed: 1806/0 green) |
| 🟧 P1 — Core Implementation | ✅ Complete (P1.1–P1.7 + exit gate: 1922/0 green) |
| 🟦 P2 — Framework Maturity | 🔵 In progress (P2.1–P2.9 CLI + TUI architecture: 2267/0 green) |
| 🟪 P3 — Scale & Ecosystem | ☐ Not started |

**Definition of current completion:** P0 + P1 + P2.
