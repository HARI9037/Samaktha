# Phase 13 — Tool Ecosystem Audit — Final Report

Date: 2026-08-02

Scope: Production-grade tool framework, dynamic registry, CAP-governed
dispatcher, built-in core tools (Shell, Clipboard, Notification),
interface-only external adapters, tool memory and diagnostics, GAMBIT
integration, and regression coverage. The LLM never executes tools directly;
every tool call is planned by GAMBIT, approved by CAP, dispatched by the
ToolDispatcher, and reported for memory and diagnostics. No changes were
committed; this report is the phase deliverable.

Explicitly excluded from Phase 13: Marketplace, plugin auto-discovery,
per-tool GUIs, streaming tool progress, tool-to-tool calls, and live
provider SDK integration (adapters are interface-only by design).

---

## 1. Architecture

```
USER QUERY
   ↓
CAP user-level approval                    app/core/cap/*
   → PermissionScope (READ/WRITE/MODIFY/DELETE/EXECUTE/NETWORK/ADMIN)
   ↓
GAMBIT                                  app/core/gambit/*
   GoalIntent (… CLIPBOARD, SEND_NOTIFICATION)  app/core/contracts/planning.py
   GoalParser (phase-13 triggers before filesystem routing)
   TaskDecomposer (capability/domain hints; tool=None + metadata)
   Planner._resolve_tool_ids → ToolSelector (capability → registered tool)
   ↓
ToolDispatcher                            app/tools/framework/dispatcher.py
   ToolCall {tool_id, arguments, timeout_s, retries, cancel_event}
   → permission gate (ToolValidator) → ToolHealthMonitor
   → execute → ToolExecutionReport → ToolMemoryStore + ToolDiagnostics
   → parallel execute_many / dependency-ordered execute_ordered
   ↓
ToolRegistry                              app/tools/registry.py
   get_tool_and_info → (Tool, ToolInfo)   [registry never introspects tools]
   ↓
Tool.run                                  app/tools/*  (base.py / shell / clipboard / notification / …)
   ↓
Result → Formatter → LLM → Memory        (unchanged core path)
```

The framework is data-driven: the registry owns discovery and returns
`(Tool, ToolInfo)` pairs; the selector resolves capabilities using only
registered metadata; the dispatcher treats every tool uniformly
(timeouts/retries/reports). Core layers stay provider-agnostic — adapters are
interface-only (19 providers, zero SDKs).

## 2. Sub-phase coverage

- **13.1/13.3** Framework — `app/tools/framework/`:
  `errors.py` (ToolError hierarchy: NotFound/Unavailable/Validation/
  Permission/Timeout/Execution/Cancelled/Dependency),
  `capabilities.py` (ToolCategory x11 + ToolCapability vocabulary),
  `models.py` (ToolPermission x7, ToolPolicy, ToolContext,
  ToolExecutionReport).
- **13.2** Dynamic registry — `app/tools/registry.py` (register/unregister,
  get_tool_and_info, info_for, has_tool, find by capability/category/version,
  availability filtering) + `ToolInfo` enriched (category, permissions,
  approval_required, supported_actions, available, policy).
- **13.4** ToolSelector — `app/tools/framework/selector.py` (prefer() hints,
  case-insensitive capabilities, category filter, explicit tool_id override,
  registry-view protocol `list_tools()`).
- **13.5** ToolHealth — `app/tools/framework/health.py` (ToolHealth,
  ToolStatus, TTL-based ToolHealthMonitor).
- **13.6** ToolDispatcher — `app/tools/framework/dispatcher.py` (ToolCall with
  timeout/retries/cancellation, permission gating via ToolValidator, parallel
  `execute_many`, dependency-ordered `execute_ordered` with cycle detection,
  execution reports, diagnostics + memory hooks).
- **13.7** ToolValidator — `app/tools/framework/validator.py` (input schema
  validation: required, types, enums, length/numeric bounds; permission gate
  when a ToolContext is supplied).
- **13.8** Native tools — `app/tools/shell.py` (ShellTool: denylist,
  EXECUTE+approval policy, max-output cap), `app/tools/clipboard.py`
  (ClipboardTool: pyperclip optional, READ/WRITE),
  `app/tools/notification.py` (NotificationTool: plyer/win10toast optional,
  graceful degradation).
- **13.9** External adapters — `app/tools/adapters/` (ExternalAdapter ABC,
  ExternalTool, AdaptersCatalog, `default_catalog()`, `provider_catalog()`;
  19 interface-only providers incl. Google Workspace, Microsoft 365, GitHub,
  Slack, Discord, Notion, SQLite, Postgres, MongoDB — no live integration).
- **13.10** ToolMemoryStore — `app/tools/framework/memory.py`
  (ToolUsageRecord, usage history w/ cap, preferences, remembered
  permissions, snapshot scrubbing; secret keys are never stored).
- **13.11** ToolDiagnostics — `app/tools/framework/diagnostics.py` (8 known
  stages: capability_requested → tool_selected → permission_checked →
  approval → execution → result → formatter → memory; unknown stages fall
  back to execution).
- **13.12** Regression tests — `tests/phase13/` (10 modules, 118 tests).
- **13.13** Architecture verification — InternetTool unchanged; no
  per-provider logic in orchestrator/CAP/GAMBIT; LLM never executes tools.
- **13.14** Production audit — this report.

## 3. Execution trace (E2E)

```
request: "run `pwd` in the project directory"
  goal        → RUN_COMMAND (phase-13 trigger before filesystem routing)
  plan        → [understand | tool:shell(capability=shell_exec, domain=shell)
                 | text_generation | reflect]   (tool=None, resolved via CAP view)
  registry    → capability "shell_exec" → ToolSelector → "shell"
  cap         → EXECUTE, approval_required=True
  dispatcher  → ToolCall(shell, {command:"pwd", cwd:"…", timeout_s:15})
  validator   → schema ok, EXECUTE granted
  shell       → ShellTool._run_command (denylist checked) → "C:\project"
  report      → ToolExecutionReport{success: True, duration_ms, …}
  memory      → usage record (never secrets) + diagnostics trace
  formatter   → result presented to LLM
  result      → completed
```

## 4. Design decisions

1. **Registry owns metadata; never introspects tools.** `ToolInfo` is supplied
   at registration (`app/core/app.py`); the selector/dispatcher operate purely
   on that record. This is why `InternetTool` and other existing tools needed
   zero changes — new behavior is layered, not invasive.
2. **Permission gating is context-scoped.** `ToolDispatcher.execute` gates
   permissions only when a `ToolContext` is supplied. The legacy boundary
   (`ToolManager.execute_tool`) runs ungated because CAP already approved at
   plan time — this preserves the established runtime contract (e.g. exact
   `"Tool not found: {tool_id}"` messages) while the new permission-aware path
   (`execute_tool_with_context`) is a defense-in-depth layer for callers that
   bypass CAP.
3. **Secrets never enter tool memory.** `ToolMemoryStore` filters keys marked
   token/password/secret/api_key/credential/oauth/bearer/authorization/
   private_key and scrubs any injected secret from snapshots; secret-valued
   preferences/config raise `ToolValidationError`.
4. **Deterministic selection.** No LLM heuristic picks tools. Capability
   resolution uses exact (case-insensitive) capability names, optional prefer
   hints and category filters, with deterministic registry order.
5. **Governance ownership stays in CAP.** Phase 13 adds the permission
   *model*; CAP retains the approval decision. The core `PolicyEngine`
   posture is unchanged (READ-scoped actions require approval), preserving
   the Phase 2.1 architecture tests that pause sensitive/critical runtime
   execution for approval.
6. **GAMBIT intents precede filesystem routing.** High-precision phase-13
   triggers (`list processes`, notify/clipboard/command keywords) are
   evaluated as "1d" before filesystem routing so `"copy X to the clipboard"`
   is not COPY_RESOURCE and `"run command … directory"` is not LIST_DIRECTORY;
   `"list processes"` intentionally stays OPERATE_WINDOWS (process listing is
   window/OS territory).
7. **Adapters are interface-only.** 19 providers define capability contracts
   and approval posture without SDK calls; real integration is a future,
   additive phase and cannot destabilize core flow.

## 5. Files modified

Application code (NEW):

- `app/tools/framework/__init__.py`, `errors.py`, `capabilities.py`,
  `models.py`, `validator.py`, `health.py`, `selector.py`, `dispatcher.py`,
  `memory.py`, `diagnostics.py` — tool framework.
- `app/tools/shell.py`, `app/tools/clipboard.py`, `app/tools/notification.py`
  — built-in core tools.
- `app/tools/adapters/base.py`, `providers.py`, `__init__.py` — external
  adapters (interface-only).

Application code (enhanced):

- `app/tools/registry.py` — dynamic registry (find/unregister/availability,
  case-insensitive capabilities).
- `app/tools/models.py` — ToolInfo enriched (category, permissions,
  approval_required, supported_actions, available, policy).
- `app/tools/manager.py` — dispatcher façade (`execute_tool_with_context`,
  `execute_many`, `execute_ordered`, `execution_reports`,
  `last_execution_report`, `get_tool_info`, `has_tool`, find-by-*,
  `set_availability`, `validate_tool_capabilities`, `.memory`, `.dispatcher`).
- `app/tools/capability_registry.py` — shell/clipboard/notification domains
  (+ `installed_domains()`, `entries()`); terminal→shell kept for compat.
- `app/core/contracts/planning.py` — `CLIPBOARD`, `SEND_NOTIFICATION` intents.
- `app/core/gambit/goal_parser.py` — phase-13 intent triggers + capability
  domains (`_INTENT_CAPABILITY_DOMAIN`).
- `app/core/gambit/task_decomposer.py` — capability/domain hints;
  RUN_COMMAND/CLIPBOARD/SEND_NOTIFICATION branches.
- `app/core/gambit/planner.py` — `_CapabilityRegistryView` + `_resolve_tool_ids`
  in `plan()` and `plan_with_capability_check()`.
- `app/core/app.py` — shell/clipboard/notification registration (v1.0.0,
  category "system", policy fields).

Test code (NEW):

- `tests/phase13/` — conftest + 10 modules, 118 tests.

## 6. Performance & security analysis

- **Performance:** tool memory is O(n) capped; health checks are TTL-cached;
  selection is a registry linear scan over ≤11 tools; parallel/ordered
  execution is asyncio-native (gather).
- **Security:** shell denylist blocks destructive/system-modifying commands
  (`rm -rf /`, `format c:`, shutdown, etc.); shell requires approval;
  clipboard/notification degrade gracefully when optional OS libs are absent;
  tool memory never stores secret-valued keys.
- **Governance:** permission-aware dispatch is gated by ToolContext when
  supplied; CAP remains the sole approval authority; capability resolution is
  deterministic so a tool can never be reached by accident.

## 7. Test report

| Module | Tests |
|--------|-------|
| test_tool_framework.py | 10 |
| test_tool_registry.py | 7 |
| test_tool_validator.py | 13 |
| test_tool_selector.py | 8 |
| test_tool_dispatcher.py | 14 |
| test_tool_memory.py | 10 |
| test_tool_diagnostics.py | 6 |
| test_native_tools.py | 13 |
| test_adapters.py | 9 |
| test_gambit_tool_ecosystem.py | 28 |
| **Total** | **118** |

## 8. Final test results

- Phase 13 suite: **118 passed**.
- Full suite: **1404 passed, 0 failed** (155.2 s) — 1286 pre-existing +
  118 new, no regressions. Phase 2.1 approval/governance architecture tests
  (sensitive-request pause + approve/deny lifecycle) remain green.

## 9. Production-stability confirmation

- LLM never executes tools directly; tool selection is deterministic via
  GAMBIT + ToolSelector.
- Core CAP governance posture is unchanged; the tool ecosystem layers on top
  of it.
- `InternetTool` is untouched and its Phase 12 behavior is regression-tested.
- External adapters are interface-only; no live SDK calls can destabilize the
  core flow.
- Phase 13 tests are fully offline (no network, optional OS libs mocked).

## 10. Recommendation log

1. **Commit.** Phases 11–13 remain uncommitted per phase policy; commit after
   review.
2. **Permission-aware execution path.** The legacy `execute_tool` boundary is
   intentionally ungated; consider routing runtime tool calls through
   `execute_tool_with_context` so the dispatcher enforces ToolPolicy as a
   second line of defense beneath CAP.
3. **Adapters next step.** When a provider is integrated (e.g. GitHub), map
   its capability (e.g. `git_*`) into the registry and let ToolSelector +
   CAP govern it — no core-layer changes required.
