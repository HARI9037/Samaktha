# Samaktha Tool Ecosystem — Critical Audit Report

Date: 2026-08-03
Scope: `app/tools/**`, `app/communication/**`, `app/internet/**`, `app/runtime/**`,
`app/core/orchestrator/engine.py`, `app/core/cap/**`, `app/core/gambit/**`, `app/memory/**`, `tests/**`
Method: source review + live empirical probes + subagent deep-dives. Every claim below was verified
against the working tree, with file:line evidence.

---

## 0. Executive Summary

The tool ecosystem is **not production-ready**. Of 18 unique registered tools, **5 are completely
broken** (every action raises `NameError`), **2 expose bypassable security guards** (shell denylist,
internet CAP permit), **4 are non-functional mocks that report success without doing anything**
(email, message, expanded notification, and their providers), and the **CAP governance layer is
label-based, not behavior-based**, meaning its enforcement can be spoofed through task metadata.
There are **zero direct tests** for the 5 broken tools and the 4 mocks.

The system has real strengths: a working task-level permit gate in the runtime, a genuine CAP
evaluation loop, a clean `ToolResult` contract, and a well-factored Phase-13 framework
(validator/selector/dispatcher). But those strengths are undermined by broken tool bodies and by
governance that trusts self-declared action strings.

**Bottom line:** treat Phase 14 (personal tools) and Phase 15 (communication) as unshipped code.
Phase 13 core tools work but have exploitable guard gaps. Until P0s below are fixed, the ecosystem
should not be exposed to an LLM that can synthesize tool arguments freely.

---

## 1. Evidence Base & Verification Log

Verified by direct source read and/or live execution:

| # | Claim | Evidence |
|---|-------|----------|
| V1 | Phase-14 handlers call `self._*(kwargs)` with undefined `kwargs` | `app/tools/calendar.py:229-243`, `tasks.py:191-203`, `notes.py:190-200`, `contacts.py:193-209`, `reminder.py:193-203` — executed, `NameError` raised |
| V2 | `ToolResult(success=True, ...)` → pydantic `ValidationError` (`ok` required; `success` not a field) | `calendar.py:283-284` vs `app/tools/base.py:7-10` |
| V3 | Shell denylist bypassable by obfuscation | `shell.py:71-77` substring match over `_DENYLIST` (`shell.py:23-38`); probe confirmed `rm -rf  /`, `rm --recursive --force /`, `del /f/s/q C:\`, `format q:` all pass |
| V4 | Internet `_cap_permit` is bare key-presence check | `app/internet/tool.py:196-199` (`return "_cap_permit" in arguments`), deny only for literal `"deny"` (line 80) |
| V5 | CAP risk/approval derived from self-declared action string | `engine.py:310-319` reads `task.metadata.get("action", task.title)`; `app/core/cap/policy_engine.py:28-66` classifies that string |
| V6 | Unknown action labels → MEDIUM risk, no approval, allowed | `policy_engine.py:112-113` (`if action_type not in READ_ACTIONS: return ActionRisk.MEDIUM`), `_approval_required` line 116-132 |
| V7 | Registration metadata is descriptive only; never enforced at execution | `ToolInfo` (`app/tools/models.py:8-19`); executor reads only `tool_id`/`task.inputs` (`app/runtime/executor.py:124-140`) |
| V8 | `notification` registered twice; second silently overwrites first | `app.py:361-377` (real) and `app.py:507-523` (mock); `registry.py:20-22` `self._tools[tool_id] = ...` no duplicate guard |
| V9 | Phase-15 communication tools are mocks returning `ok=True` | `app/communication/notification_tool.py:112-148` (no real delivery); providers `SMTP/Gmail/Outlook` return `not_configured` (`provider.py:53-73`, `85-103`) |
| V10 | Memory search fabricates `count=1` for non-list backend result | `app/tools/memory.py:53-55` (`"count": len(res) if isinstance(res, list) else 1`, `"memories": str(res)`) |
| V11 | Filesystem registered with no sandbox root and absolute-path capability | `app.py:248` comment "No sandbox"; `filesystem.py:14-19` (`root_dir=None`); traversal guard only enforced when `root_dir` set (`filesystem.py:57-61`) |
| V12 | Windows tool exposes raw `terminal` action with no governance metadata | `windows.py:37-41`; `app.py:296-304` (no category/permissions/approval/policy/version) |
| V13 | Runtime permit gate exists but never revalidates tool behavior | `app/runtime/engine.py:69-108` (permit checked) but `executor.py:140` passes `task.inputs` verbatim |
| V14 | No direct tests for 5 broken + 4 mock tools | grep over `tests/**` for `ReminderTool|NotesTool|TasksTool|ContactsTool|CalendarTool|WindowsTool|PDFTool|ImageTool` → no matches |
| V15 | `.env` holds a Groq API key in plaintext | gitignored (`.gitignore`) and untracked (`git ls-files` empty) — not committed, but disk-readable |

---

## 2. Tool Inventory & Readiness Matrix

Rubric: **Runtime** = does the tool execute its declared function end-to-end.
**Governance** = is it correctly declared (category/permissions/approval/policy) and can CAP actually gate its behavior.
**Security** = can the guard be bypassed from a compromised/errant caller.
**Tests** = direct automated coverage.

| Tool | Purpose | Runtime | Governance | Security | Tests | **Readiness** |
|------|---------|:-------:|:----------:|:--------:|:-----:|:-------------:|
| resolver | route paths→format tools | PASS | bare | MED | some | **85** |
| filesystem | read/write/delete anywhere | PASS | bare, no sandbox | HIGH | some | **55** |
| document | Docling extraction | PASS | bare | MED | yes | **70** |
| pdf | PDF extraction | PASS | bare | MED | yes | **70** |
| image | image analyze/metadata | PASS | bare | MED | none | **60** |
| memory | search/delete memories | PASS | bare | MED | some | **60** |
| windows | processes/clipboard/**terminal** | PASS | **none** | **HIGH** | some | **30** |
| internet | governed search/fetch | PASS | forgeable | **HIGH** | yes | **65** |
| shell | approved command exec | PASS | declared | **HIGH** (denylist bypass) | yes | **45** |
| clipboard | read/write clipboard | PASS | declared | MED | yes | **80** |
| notification (Phase-13) | real desktop notify | PASS | declared | LOW | yes | **80** |
| notification (Phase-15) | mock — **overwrites the above** | **FAIL** | declared | MED (lies ok=True) | none | **20** |
| reminder | scheduling/reminders | **FAIL** (NameError) | declared | — | none | **10** |
| notes | markdown notes CRUD | **FAIL** (NameError) | declared | — | none | **10** |
| tasks | task management | **FAIL** (NameError) | declared | — | none | **10** |
| contacts | contacts CRUD/vCard | **FAIL** (NameError) | declared | — | none | **10** |
| calendar | events/conflicts/recurring | **FAIL** (NameError + ValidationError) | declared | — | none | **10** |
| email | compose/send/read/search | **FAIL** (stub provider) | declared | MED (lies ok) | some | **25** |
| message | send/reply/history | **FAIL** (stub) | declared | MED (lies ok) | some | **25** |

18 unique tools, 19 registrations. **Effective readiness: 5 broken, 4 mocks, 4 bare-registered
high-risk, 2 bypassable guards, only 5 genuinely healthy.**

---

## 3. Architecture Findings

### A1. Two-layer tool dispatch is redundant and diverges
`app/tools/manager.py` / `app/tools/framework/dispatcher.py` (in-process dispatcher with diagnostics,
memory, selector) coexists with `app/runtime/{dispatcher,engine,executor}.py` (runtime layer). The
runtime `ToolExecutor` (`executor.py:124-140`) reaches straight into `tool_manager.execute_tool()`
and bypasses the framework dispatcher — so framework features (timeouts/retries declared in
`ToolPolicy`) are **not** reliably applied at execution. The comment in `app.py:325-326` ("the
dispatcher can enforce timeouts/retries") describes an aspiration, not the executed path.

### A2. Tool registration metadata is decorative
`ToolInfo` (`models.py:8-19`) carries `approval_required`, `permissions`, `category`, `policy`, but
nothing at execution reads them. The runtime gate is the CAP permit attached to the *task*; the
registration metadata merely feeds discovery/selector. Consequence: declaring a tool
`approval_required=False` (all 5 personal tools) does nothing, and declaring nothing (windows,
filesystem) is indistinguishable — governance is entirely a function of the action-label
classification in §5.

### A3. Five Phase-14 tools are dead on arrival
Every handler dispatches to `self._*(kwargs)` while `kwargs` is undefined and the handler signature
uses `arguments`:

- `calendar.py:229-243` → handlers use `arguments` at `calendar.py:249-277`
- `tasks.py:191-203` → handlers use `arguments` at `tasks.py:209+`
- `notes.py:190-200`, `contacts.py:193-209`, `reminder.py:193-203` — same pattern

Verified by direct invocation: `NameError: name 'kwargs' is not defined` on *every* action of all
five tools. A single find-and-replace would have caught this; no linting/type-check gate caught it.

### A4. Calendar create has a second latent crash
Even with A3 fixed, `calendar.py:283-284` constructs `ToolResult(success=True, data=...)`. `ToolResult`
(`base.py:7-10`) requires `ok` and has no `success` field → pydantic `ValidationError`. Masked today
only because A3 crashes first.

### A5. Notification tool is silently replaced by a mock
`app.py:361` registers the real Phase-13 `app.tools.notification.NotificationTool`; `app.py:507`
registers the Phase-15 `app.communication.notification_tool.NotificationTool` under the same id.
`registry.py:20-22` overwrites silently. The mock (`notification_tool.py:112-148`) returns
`ok=True, status="sent"` for every action without ever dispatching a notification. A working feature
is quietly disabled and replaced by a lie.

---

## 4. Contract & Result-Model Findings

- `ToolResult` (`base.py:7-10`) is minimal and correct: `ok / data / error`. The two rule violations
  are both in `calendar.py` (`success=True`, `ok` omitted) — see A4.
- `MemoryTool._search` (`memory.py:53-55`): `"count": len(res) if isinstance(res, list) else 1` and
  `"memories": str(res)` fabricate a `count=1` success when the backend returns any non-list. Callers
  (planner, user, memory ingestion) cannot distinguish "1 real memory found" from "search returned a
  string/None". This is a silent correctness lie.
- Adapters (`app/tools/adapters/base.py:92-98`) treat `action`/`operation` generically — fine, but
  they also bypass framework dispatch.

---

## 5. CAP Governance Findings

### G1 (CRITICAL, structural). Governance is label-based, not behavior-based
The whole CAP gate reduces to one string. Orchestrator maps intent → base action from
`task.metadata.get("action", task.title)` (`engine.py:310-319`), then `PolicyEngine.evaluate`
classifies that string (`policy_engine.py:28-66`). The runtime executes `task.inputs` verbatim
(`executor.py:140`). There is **no cross-check** that the action the tool actually performs matches
the label that was approved.

Attack chain:
1. Planner writes `action="read"` (`engine.py:312` even maps `read_*` → `read`) for a task that
   actually calls `filesystem.write`, `filesystem.delete`, or `windows.terminal`.
2. PolicyEngine sees READ (`policy_engine.py:12,78`) → LOW/MEDIUM risk.
3. Permit granted; `ToolExecutor` runs the args as-is.

### G2 (CRITICAL). Unknown action labels bypass approval entirely
`policy_engine.py:112-113`: any action type not in `READ_ACTIONS` is classified MEDIUM, and
`_approval_required` (lines 116-132) returns `False` when no permission matched. So `snooze`,
`agenda`, `lookup`, `filter`, `recurring`, `import`, `export`, `clipboard_set`, `terminal`, `remember`
etc. — the labels the Phase-14 tools actually use — require **no approval** and are **allowed**
(`allowed = not approval_required and risk != CRITICAL`, line 59). The most sensitive actions of the
most privileged tools are the least gated.

### G3 (CRITICAL). `_cap_permit` for internet is forgeable
`internet/tool.py:196-199`: `_governed()` returns `"_cap_permit" in arguments` — mere key presence,
any value. Only the literal string `"deny"` is refused (line 80). The legitimate injector is
`engine.py:344-347`, but the tool never validates the value against the issued `ExecutionPermit`
(`task.metadata["permit"]`, `engine.py:339-343`). Any caller that appends `_cap_permit="allow"` —
planner, another tool, an adapter, or a corrupted request — bypasses governance. Worse,
`SearchPolicy.require_approval=False` (default, per `tool.py:197-198`) disables the gate entirely.

### G4 (HIGH). Permit is never revalidated at execution
`runtime/engine.py:69-108` requires `task.permit` and blocks non-`allow` decisions — good. But the
permit carries only `action_id/decision/reasons` (`app/core/contracts/policy.py`); it binds to a task
id, not to the tool+args. Nothing at `executor.py:140` checks that the executing tool/args match what
was approved.

### G5 (HIGH). Registration metadata never enforced
See A2. `windows.py:37-41` exposes `terminal` (raw subprocess on Windows) with zero governance
metadata at `app.py:296-304`; `filesystem` at `app.py:246-254` with the explicit comment
"No sandbox — allows absolute paths from planner". These are the two highest-privilege surfaces and
the least declared.

### G6 (MED). Action-type normalization is lossy
`engine.py:312-319` collapses `read_x`→`read`, `write_x`→`write`, `list_x`→`list`, any
`delete*`→`delete`. A planner naming a task `read_windows_clipboard` or `read_secrets` gets it
classified as a plain READ. The prefix-based collapse actively helps label spoofing.

---

## 6. GAMBIT Integration Findings

- GAMBIT generates the `execution_plan.tasks` whose `metadata` fields (tool, action, args) are the
  sole inputs to CAP. There is **no allowlist of tool/action pairs** in the planner; it is free to
  emit any tool id + action + args (`app/core/gambit/agent_planner.py`, `task_decomposer.py`). See
  G1/G2 for consequences.
- The resolver (`resolver.py`, `resolver_layer.py`) lets the planner reference resources by relative
  path/extension and routes to target tools (`resolver_layer.py:27-51`) — a convenience that widens
  the planner's reach beyond declared tools.
- GAMBIT capability matching (`app/core/gambit/capability matching`) keys off `ToolInfo.capabilities`,
  which for bare registrations (filesystem, windows) are self-declared free strings — matching is
  unconstrained by any permission model.

---

## 7. Runtime Findings

- **Timeout/retry is not uniform.** `ShellTool` enforces its own timeout (`shell.py:89,116-122`);
  `ToolPolicy.default_timeout_s/max_retries` (`framework/models.py:32-33`) are declared but the
  runtime `ToolExecutor` (`executor.py:117-185`) applies neither. A hung `windows.terminal` or
  `filesystem` call has no default kill switch at the runtime layer.
- **No per-tool concurrency cap.** `ToolPolicy.max_parallel_instances` (`models.py:36`) exists; the
  executor ignores it. `runtime/engine.py:48+` executes batches; `tool_chain.py` can chain tools, but
  no budget/concurrency limit is enforced.
- **Error→RuntimeResult mapping is lossy.** `ToolExecutor` maps `ok=False` to `FAILED` with only the
  error string (`executor.py:160-166`); `data` from partial results is dropped, losing diagnostics
  that `ToolInfo`/diagnostics could have carried.
- **`MULTIPLE_MATCHES` pause is the only structured pause** (`executor.py:149-159`); CAP "ask_user"
  pauses are handled in `runtime/engine.py:83-97`. Both exist, but nothing throttles repeated
  pause/resume loops.

---

## 8. Security Findings

| ID | Severity | Finding | Evidence |
|----|----------|---------|----------|
| S1 | **P0** | Shell denylist is substring match; trivially bypassed (`rm -rf  /`, `rm --recursive --force /`, `del /f/s/q C:\`, `format q:`) | `shell.py:71-77`; probe-verified |
| S2 | **P0** | CAP action-label spoofing (G1) lets a planner execute write/delete/terminal under a "read" label | `engine.py:310-319`, `policy_engine.py:28-66`, `executor.py:140` |
| S3 | **P0** | Internet `_cap_permit` forgeable; `require_approval=False` default disables gate | `internet/tool.py:196-199,80`, `engine.py:344-347` |
| S4 | **P1** | Filesystem: no sandbox by default, absolute paths, traversal guard only when `root_dir` set | `app.py:248`, `filesystem.py:14-19,57-61` |
| S5 | **P1** | Windows `terminal` = raw command execution, ungated registration | `windows.py:37-41`, `app.py:296-304` |
| S6 | **P1** | Mocks return `ok=True` (email/message/notification) → planner and user believe side effects happened | `communication/notification_tool.py:112-148`, `provider.py:53-73` |
| S7 | **P2** | Memory delete surfaces (`delete_all`, `delete_session`) ungated and reachable by label | `memory.py:100-130`, G2 |
| S8 | **P2** | Groq API key in plaintext `.env` (gitignored, untracked — not committed, but disk-readable) | `.gitignore`, `git ls-files` |
| S9 | **P2** | No secret redaction in tool `data`/logs (framework `_is_secret` exists in memory store but not applied to all result payloads) | `app/tools/framework/memory.py` |

---

## 9. Memory Interaction Findings

- **Ingestion leak:** orchestrator persists *all* document reads to memory (`engine.py:362-364`,
  `_persist_documents_to_memory` up to line 845) and records all outputs into working memory
  (`engine.py:369`). No privacy/criticality gating before write — sensitive documents enter long-term
  memory even though CAP flagged `use_local_model` for SENSITIVE/CRITICAL privacy (`policy_engine.py:47-50`).
- **Delete-memory path:** `MemoryTool` delete actions consult `_controller.delete_by_type`,
  `delete_memory`, etc. (`memory.py:84-147`). The orchestrator's Phase-20.1 fix routes
  `DELETE_MEMORY` tasks through the execution report — but the tool itself still returns `ok=True`
  with fabricated `count` when the backend returns non-list (`memory.py:53-55`), so delete/verify
  loops can believe deletion succeeded when it didn't.
- **Cross-tool memory reach:** `MemoryTool` can read/delete other subsystems' memory with no approval
  (bare registration + G2). A planner label "search" is enough to dump stored context.

---

## 10. Critical Issue Register

| ID | Sev | Issue | Location | Impact | Root cause | Fix | Status |
|----|-----|-------|----------|--------|------------|-----|--------|
| C1 | P0 | 5 personal tools crash with `NameError` on every action | calendar.py:229-243 (etc.) | Features dead; user-facing failures 100% | `kwargs` vs `arguments` typo; no lint/typecheck gate | Pass `arguments` to handlers; add lint rule; add tests | ✅ Resolved (Phase 11.5) |
| C2 | P0 | Calendar create → pydantic `ValidationError` | calendar.py:283-284 | Latent crash | `ToolResult(success=True)` | Use `ok=True` | ✅ Resolved (Phase 11.5) |
| C3 | P0 | Shell denylist bypassable | shell.py:71-77 | Destructive command execution | substring match | Tokenize/normalize (collapse whitespace, resolve flags), add allowlist for cwd, block `:` `>` `|` chaining, tests |
| C4 | P0 | Internet `_cap_permit` forgeable | internet/tool.py:196-199 | Governance bypass for network | bare key-presence | Validate against cryptographically-bound permit; require signed/opaque token |
| C5 | P0 | Action-label governance spoofing + allow-by-default for unknown labels | policy_engine.py:112-113; engine.py:310-319; executor.py:140 | Write/delete/terminal under "read" approval | classification of self-declared string | Bind permit to tool+action+args hash; reject unknown labels (deny-by-default); cross-check at tool boundary |
| C6 | P1 | Windows `terminal` ungated, raw exec | windows.py:37-41; app.py:296-304 | Arbitrary command execution | missing registration metadata | Declare permissions/approval; reuse ShellTool policy or remove action |
| C7 | P1 | Filesystem no-sandbox default | app.py:248; filesystem.py:14-19 | Arbitrary file access | `root_dir=None` | Require root_dir; enforce traversal always; separate read vs write permissions |
| C8 | P1 | Notification silently replaced by mock | app.py:361 vs 507; registry.py:20-22 | Notifications stop working | duplicate registration overwrite | Registry reject duplicate id; delete mock; fix Phase-15 or gate it off | ✅ Resolved (Phase 11.5) |
| C9 | P1 | Email/Message claim success via stubs | provider.py:53-73,85-103 | "Message sent" when nothing sent | stub providers | Return `ok=False, error=not_configured`; or implement real providers | OPEN |
| C10 | P1 | Memory search fabricates results | memory.py:53-55 | False count/context | `count=1` fallback | Return non-list backend as error; require list result | ✅ Resolved (Phase 11.5) |
| C11 | P2 | Timeout/retry not enforced at runtime | executor.py:117-185 | Hung tools unkillable | ToolPolicy unused | Apply default_timeout_s/max_retries in ToolExecutor | OPEN |
| C12 | P2 | No duplicate-tool-id guard | registry.py:20-22 | Silent overwrite | dict assignment | Raise on re-register | ✅ Resolved (Phase 11.5) |
| C13 | P2 | Plaintext `.env` credential | `.env` | Credential theft | config practice | Secret manager / env injection; key rotation | OPEN |

---

## 11. Missing Infrastructure

1. **Behavioral tool contract enforcement** — a per-tool "effective operation" reporter so CAP can
   verify label vs reality (or a forced-typed action enum per tool).
2. **Deny-by-default policy engine** — unknown action labels must be DENIED, not allowed.
3. **Signed/opaque CAP permits** verified at the tool boundary (not a key-presence check).
4. **Runtime timeout/retry/concurrency enforcement** via `ToolPolicy` in `ToolExecutor`.
5. **Registry integrity** — duplicate-id rejection, frozen tool manifest.
6. **Lint/typecheck CI gate** — the `kwargs`/`arguments` bug class would be caught by `ruff`/`pyright`.
7. **Secret redaction layer** on all `ToolResult.data` and log emission.
8. **Real communication providers** or honest `ok=False` stubs.
9. **Per-tool test harness** (see §14).

---

## 12. Test Coverage Gaps

| Tool | Covered | Coverage notes |
|------|---------|----------------|
| shell | yes | `tests/phase13/test_native_tools.py`, `tests/security/test_phase55_tool_guard.py`, `tests/shell/` — but **no obfuscation-bypass tests** |
| clipboard | yes | `test_native_tools.py` (fake pyperclip) |
| internet | yes | `tests/phase12/test_internet_tool.py` — **no permit-forgery test** |
| filesystem | partial | `tests/tools/test_phase2_tools.py` — **no no-sandbox/path test** |
| document/pdf | yes | `tests/tools/test_document_tool.py`, `tests/fileparsers/` |
| windows | partial | `tests/windows/test_phase64_windows.py` — **no terminal-action test** |
| memory | partial | framework memory (`test_tool_memory.py`); **MemoryTool search fabrication untested** |
| resolver | partial | indirect via filesystem tests |
| reminder/notes/tasks/contacts/calendar | **none** | grep found zero references |
| email/message/notification(Phase15) | **none** (only layer tests) | `tests/communication/test_phase15_communication.py` tests the abstraction, not the tools |
| image | **none** | — |
| Phase-13 framework | strong | `tests/phase13/test_tool_{framework,dispatcher,registry,selector,validator,diagnostics,memory}.py` |

---

## 13. Recommended Roadmap

### P0 — Ship-blocking (do first, in order)
1. Fix C1: pass `arguments` into all 5 Phase-14 handlers; add regression tests.
2. Fix C2: `ToolResult(ok=True, ...)` in calendar create.
3. Fix C5: **deny-by-default** policy engine — reject unknown action labels; bind permit to
   `tool + action + args_hash`; enforce in `ToolExecutor`.
4. Fix C3: robust shell command normalization + explicit allowlist; tests for every denylist bypass
   variant.
5. Fix C4: replace `_cap_permit` key-presence with a real permit verification at the tool boundary.
6. Fix C8/C12: registry duplicate rejection; resolve notification conflict.

### P1 — High impact
7. Fix C7: mandatory `root_dir` sandbox; always enforce traversal.
8. Fix C6: declare (or remove) `windows.terminal` governance.
9. Fix C9: honest `ok=False` for unconfigured communication.
10. Fix C10: memory search backend must return a list or error.

### P2 — Hardening
11. Fix C11: enforce `ToolPolicy` timeout/retry/concurrency in the runtime executor.
12. Add CI lint/typecheck gate; add secret-redaction pass.
13. Move `.env` credential to secret store; rotate key.

### P3 — Follow-ups
14. Real providers for email/message; per-tool test matrix; action-lint tests; planner
    tool/action allowlist in GAMBIT.

---

## 14. Proposed New Tests

1. `test_phase14_tools_do_not_crash.py` — every action of reminder/notes/tasks/contacts/calendar
   returns a `ToolResult` (not `NameError`).
2. `test_calendar_create_result.py` — create event returns `ok=True` with event payload.
3. `test_policy_engine_deny_by_default.py` — unknown labels denied; known write/delete/execute require
   approval; no allowed-without-approval for any risky label.
4. `test_cap_permit_tamper.py` — forged `_cap_permit` rejected; expired/wrong-scope permit rejected.
5. `test_shell_denylist_bypass.py` — `rm -rf  /`, `rm --recursive --force /`, `del /f/s/q C:\`,
   `format q:`, case/whitespace/flag variants all refused.
6. `test_tool_registry_duplicate_id.py` — second registration raises.
7. `test_runtime_timeout_retry.py` — ToolExecutor applies `ToolPolicy.default_timeout_s`/`max_retries`.
8. `test_filesystem_sandbox.py` — without `root_dir` the tool refuses absolute-path writes; traversal
   always blocked.
9. `test_windows_terminal_governance.py` — `terminal` action requires approval/declared permissions.
10. `test_memory_search_fabrication.py` — non-list backend returns `ok=False`, not `count=1`.
11. `test_communication_honest_failure.py` — unconfigured email/message return `ok=False`.
12. `test_notification_registry.py` — exactly one `notification` registration; real tool wins.

---

## Appendix: files that must change for P0

- `app/tools/{calendar,tasks,notes,contacts,reminder}.py`
- `app/core/cap/policy_engine.py`
- `app/core/orchestrator/engine.py` (permit binding + internet injection)
- `app/runtime/executor.py` (permit/args verification)
- `app/tools/shell.py` (denylist)
- `app/internet/tool.py` (permit validation)
- `app/core/app.py` (notification conflict, filesystem sandbox, windows metadata)
- `app/tools/registry.py` (duplicate guard)
- `app/tools/memory.py` (search fabrication)
- `app/communication/provider.py` (honest failures)
