# Samaktha Tool Ecosystem Hardening Analysis

Companion to `AUDIT_tool_ecosystem.md`. Role: Lead Architect review. No implementation performed.
Goal: validate priorities, classify bug-vs-design, define the Phase 11.5 hardening design and the exact
completion criteria before Phase 12 (Internet Intelligence) begins.

---

## Executive Summary

The audit's P0/P1 findings are accurate and, if anything, under-weighted. They cluster into two distinct
populations that must be treated differently:

1. **Mechanical bugs** (C1, C2, C10, C12) — wrong-variable typos, a field-name error, a fabricated
   count, a missing registry guard. Cheap, isolated, low-risk to fix. But their existence at this
   maturity level is itself a signal: **there is no lint/typecheck/test gate on the tool layer**, and
   that gate is a project defect, not a tool defect.
2. **Design defects** (C5, C4, C3, C6, C7) — these are not typos. They all trace to one root cause:
   **the capability boundary is enforced by self-declared strings and caller-supplied markers instead
   of a typed, CAP-issued, verified authorization artifact.** CAP's own invariant ("CAP is the final
   authority for capability execution") is currently enforced as a classification exercise over an
   unverifiable label, and tools either self-authorize (internet `_cap_permit`) or not at all
   (windows terminal).

Findings C8 and C9 (mock tools reporting success) are **invariant violations** (results must
accurately represent reality; memory must not store false execution states), not "nice to have"
cleanliness.

**Recommendation:** Phase 12 must not start until the P0 set and the cheap P1 honesty/availability
fixes are landed and covered by tests. The realistic critical path is: tool contract repairs →
deny-by-default governance → signed permit binding → tool-boundary verification → shell/filesystem
execution hardening. No rewrite is required; the architecture is sound at the skeleton level and only
the capability boundary needs to be made real.

---

## Architecture Impact

### Mapping findings to the six invariants

| Invariant | Status | Violating findings |
|-----------|--------|--------------------|
| 1. CAP is final authority for capability execution | **VIOLATED** | C5 (label-based classification, allow-by-default), C4 (caller-supplied `_cap_permit`) |
| 2. GAMBIT plans but never executes tools | Satisfied | GAMBIT only emits metadata; but see C5 — the metadata it emits is the *entire* security boundary |
| 3. Tools are capabilities, not autonomous agents | **VIOLATED (partial)** | C4 (internet tool grants itself access on key presence), C6 (windows terminal acts without any authorization hook) |
| 4. Tools must not self-authorize | **VIOLATED** | C4: `internet/tool.py:196-199` accepts `"_cap_permit" in arguments` |
| 5. Results must accurately represent reality | **VIOLATED** | C8/C9 (mocks return `ok=True`), C10 (memory search fabricates `count=1`) |
| 6. Memory must not store false execution states | **VIOLATED (conditional)** | C10 feeds `ok=True` fabrication into downstream ingestion; document-read persistence (`engine.py:362-364`) bypasses privacy gating |

### Bug fixes vs design corrections

| Class | Findings | Rationale |
|-------|----------|-----------|
| **Mechanical bugs** | C1 (`kwargs`/`arguments`), C2 (`ToolResult(success=True)`), C10 (count fallback), C12 (duplicate registration) | Single-line defects, no schema or flow change. C10 is slightly structural (backend contract) but the fix is "require a list or error". |
| **Design corrections** | C5 (deny-by-default + typed actions + permit binding), C4 (signed permit verification at tool boundary), C3 (tokenize/normalize shell command instead of substring match) | Change *how* authorization and validation are computed. These are the real work. |
| **Security posture decisions** | C6 (windows `terminal`), C7 (filesystem sandbox default) | Not bugs — deliberate choices with no current enforcement. Decision needed: govern or disable/require-config. |
| **Honesty contract** | C8, C9 | Framework-level contract: `ok=True` implies a verified real effect. Includes a registry integrity guard (C12). |
| **Project-level gap** | No lint/typecheck gate | Not a tool defect; a delivery defect. Would have caught C1+C2 in seconds. |

**Key architectural conclusion:** CAP is currently a *classifier*, not an *authority*. The runtime
gate (`runtime/engine.py:69-108`) genuinely requires a permit and blocks non-`allow` decisions — that
part is real. But the permit is derived from a string the planner wrote into metadata, and nothing
proves the executed tool+args correspond to the approved label. Making CAP an authority requires two
additions, not a rewrite:

1. **A typed, per-tool action schema** (the capability's declared surface) so classification and
   planner output are validated against the same artifact.
2. **A bound, signed permit** verified inside the runtime executor and at the tool boundary.

---

## Priority Review

### Confirmations

- **C5 (label-based governance)** — correct as P0, and it is the *highest* priority, above the crash
  bugs. It is the silent capability-boundary bypass (invariant 1). Everything else can be understood
  as a special case of it.
- **C3 (shell denylist)** — correct as P0. Substring matching (`shell.py:71-77`) is a paper guard on
  the highest-privilege tool.
- **C4 (internet permit forgery)** — correct as P0 **and it is a hard Phase-12 blocker by definition**:
  Phase 12 *is* the internet tool.
- **C1/C2 (broken personal tools)** — correct as P0 in the sense of "ships broken"; cheap, do first.

### Adjustments

| Finding | Audited priority | Adjusted priority | Rationale |
|---------|------------------|-------------------|-----------|
| C8 (notification overwritten by mock) | P1 | **P0 — before Phase 12** | Silent loss of a working feature + registry integrity. Two lines + a test. Do not ship Phase 12 with the real notifier dead. |
| C9 (email/message stubs claim success) | P1 | **P0 (honesty half only) — before Phase 12** | Invariant 5/6 violation. The fix is "return `ok=False, NOT_CONFIGURED`"; real providers stay P3. |
| C6 (windows `terminal` raw exec) | P1 | **P0 (remove/hide action) — before Phase 12** | Cheapest way to shrink attack surface before granting more model reach. Either govern it via the signed-permit flow or strip the `terminal` action from the advertised capability set until Phase 11.5 lands. |
| C7 (filesystem sandbox) | P1 | **Design now; default-safe toggle before Phase 12; full planner path sandboxing P1** | Making `root_dir` mandatory is a one-line default but breaks planner absolute-path workflows and document persistence. Must be designed in 11.5; the safe default should flip before Phase 12 with a migration flag; complete enforcement during Phase 12. |
| C11 (timeout/retry not enforced) | P2 | P1 — during Phase 12 | `ToolPolicy` already declares the values (`framework/models.py:32-36`); the executor just needs to apply them. Low effort, real safety. |
| CI lint/typecheck gate | (new) | **P1 — before Phase 12** | The NameError class (C1) would never have shipped past a pyright/ruff pass on `app/tools`. Cheap, prevents recurrence. |
| C10 (memory fabrication) | P1 | P1 — before Phase 12 | Small; required for invariant 6. |
| C12 (duplicate registration) | P2 | P1 — before Phase 12 | Registry integrity underpins C8's fix. |
| Real email/message providers, secrets store, concurrency caps | P2/P3 | unchanged (after Phase 12) | Not on the critical path. |

### Must be fixed before Phase 12 (final set)

C1, C2, C5, C4, C3, C8, C9 (honesty), C10, C12, C6 (disable), filesystem default-safe toggle, CI gate.

### Can wait

C7 full sandboxing (during Phase 12), C11 (during Phase 12), real communication providers (P3),
secrets store (P2), per-tool concurrency caps (P2/P3).

---

## Dependency Plan

```
1. Tool Contract Repair                     (C1, C2, C10, C12 + registry guard)
   ├─ makes every tool return valid, honest ToolResult
   └─ precondition for schema extraction
                    ↓
2. Typed Capability Schema + Registry       (per-tool action enums; schema is single source of truth)
                    ↓
3. CAP Governance Upgrade — deny-by-default  (C5: classification over typed actions; unknown ⇒ DENY)
   └─ Planner/capability-matching now validates against the same schema (GAMBIT change, small)
                    ↓
4. Signed Bound Permit                       (Extend ExecutionPermit: args-hash + HMAC; orchestrator signs)
                    ↓
5. Tool-Boundary Verification                (C4: ToolExecutor + tools verify permit; remove _cap_permit)
   └─ covers internet (Phase-12 blocker) and windows.terminal if retained
                    ↓
6. Secure Tool Execution                     (C3 shell tokenizer/normalizer; C7 sandbox default)
   └─ independent of 3–5; can run in parallel with 4
                    ↓
7. Phase 12 — Internet Intelligence
```

Critical path: **1 → 2 → 3 → 4 → 5**. Items 6 (shell/sandbox) and the honesty fixes (C8/C9) are
parallelizable and should be picked up by a second workstream so the critical path is not serialized
into a long phase. Item 2 (typed schema) is the load-bearing piece — it is what turns CAP from a
string classifier into an authority, and it retrofits cleanly onto the existing `ToolCapability` enums
(`app/tools/framework/capabilities.py`).

---

## Phase 11.5 Design — Tool Ecosystem Hardening

### New tool execution lifecycle

```
User
 ↓
CAP Context Gateway (request context: user, session, privacy)
 ↓
GAMBIT plan (intent + capability intent, no raw tool args beyond schema)
 ↓
CapabilitySchema validation (plan-time): tool_id ∈ registry, action ∈ schema(action enum)
 ↓
CAP Policy + Risk (classify over TYPED action, not free string; unknown ⇒ DENY)
 ↓
Approval Engine (decide; ask_user/deny block at runtime)
 ↓
CAP issues BoundPermit {tool_id, action, args_hash, request_id, session_id, issued_at, expires_at, sig}
 ↓
Audit Logger (every permit + every execution verdict)
 ↓
Runtime Engine (re-check permit: allow + not expired + signature valid)
 ↓
ToolExecutor (verify permit binds THIS tool/action/args-hash; apply ToolPolicy timeout/retry/concurrency)
 ↓
Tool boundary (framework dispatcher re-verifies; executes)
 ↓
CapabilityResult validated: honest status; effect_metadata attached
 ↓
Result → user; verified outcomes only → Memory
```

### Tool request structure (CapabilityRequest)

```jsonc
{
  "request_id": "…", "session_id": "…", "user_id": "…",
  "tool_id": "filesystem",
  "action": "write",                 // typed: drawn from the tool's action enum
  "args": { "path": "…", "content": "…" },
  "intent": { "goal": "…", "description": "…" },
  "desired_capabilities": ["write"]
}
```

Key change: `action` is no longer a free string from planner metadata — it is validated at plan time
against the tool's declared schema. `args` is validated against the schema (the Phase-13 `ToolValidator`
already exists; it becomes mandatory, not advisory).

### Tool response structure (CapabilityResult)

```jsonc
{
  "ok": true,
  "status": "SUCCESS",               // SUCCESS | FAILED | DENIED | REJECTED_BY_GOVERNANCE |
                                     // NOT_CONFIGURED | TIMEOUT | PARTIAL
  "data": { … },
  "error": null,
  "effect": {                        // new: what actually changed, for CAP/memory verification
    "changed_paths": ["…"], "items_deleted": 3, "notification_delivered": true, "bytes_written": 42
  },
  "audit_ref": "…"
}
```

The `status` enum replaces binary `ok` ambiguity. **A tool may return `ok=true` only when `effect`
records a real side effect** — this is how invariants 5 and 6 become enforceable rather than aspirational.
Phase 20.1's execution-truth machinery (orchestrator-side `_has_runtime_success`) is the natural home
for this check; it moves down into the result contract.

### CAP authorization flow

1. **Typed classification**: `PolicyEngine` consumes the schema-validated `action`; unknown/undefined
   action ⇒ `DENY` (deny-by-default, replacing `policy_engine.py:112-113`'s MEDIUM-allow).
2. **Permission derivation** stays as-is (`policy_engine.py:72-90`) but now reads the typed action.
3. **Approval** per current flow; `ask_user`/`deny` unchanged.
4. **Permit issuance**: `ExecutionPermit` gains `args_hash = sha256(canonical(args))` and a
   `sig = HMAC(cap_key, tool|action|args_hash|request_id|expires_at)`. Orchestrator signs
   (`engine.py:339-347` becomes a signing call; the `_cap_permit` marker is deleted).
5. **Audit**: every issue + every verification result appended to the audit log.

### Runtime validation flow

- `RuntimeEngine` (`runtime/engine.py`): existing permit checks stay; add expiry + signature check.
- `ToolExecutor` (`executor.py:117-185`): verify signature; recompute `args_hash` from the actual
  `task.inputs` and reject on mismatch (**prevents the read-labeled-delete class outright**, because
  the args the planner submits are bound into the permit at approval time).
- Framework dispatcher re-verifies at the tool boundary; **tools contain no authorization logic**
  (the `_governed`/`_cap_permit` pattern is removed globally).

### Error handling model

| Status | Meaning | Runtime mapping | Retry |
|--------|---------|-----------------|-------|
| `DENIED` / `REJECTED_BY_GOVERNANCE` | CAP refused | `PAUSED`/blocked, surfaced to user | no |
| `NOT_CONFIGURED` | honest unavailable (email, internet w/o key) | `FAILED` w/ clear message | no |
| `VALIDATION` | args violate schema | `FAILED`; planner re-emits corrected args | yes (new plan) |
| `EXECUTION` | tool failed at runtime | `FAILED` | per `ToolPolicy.max_retries` |
| `TIMEOUT` | policy deadline exceeded | `FAILED` + kill | per policy |
| `PARTIAL` | some effects applied | `FAILED` w/ `effect` payload | manual decision |

### Security boundaries

- **Permits are issued, never accepted**: HMAC-signed; tool layer holds only a verify key; expiry ≤
  request lifetime.
- **Args are schema-validated before execution**; no `**kwargs` passthrough to subprocess-like
  surfaces without normalization (shell tokenizer).
- **Shell**: tokenize → normalize whitespace/flags → reapply denylist + allowlist of bases/`cwd`.
- **Filesystem**: `root_dir` mandatory in default config; traversal guard always active
  (`filesystem.py:57-61` currently only when `root_dir` set).
- **Secrets**: redaction applied to every `data`/log payload; framework `_is_secret` extended to all
  result emission.
- **Windows `terminal`**: either governed through the signed-permit flow (reuse ShellTool policy) or
  removed from advertised capabilities.

---

## Migration Strategy

No rewrite. Every change is additive or contractual, and the existing test suite (~865 passing,
fixtures `build_memory_stack` / `build_orchestrator`) is preserved via a fixture shim.

**Order of module changes (incremental, each independently shippable):**

1. **`app/tools/{calendar,tasks,notes,contacts,reminder}.py`** — fix `kwargs`→`arguments` (C1),
   calendar `ok=True` (C2). Zero blast radius; add regression tests. *Do this first; it unblocks
   feature testing.*
2. **`app/tools/registry.py` + `app/core/app.py`** — duplicate-id rejection (C12); resolve the
   notification conflict (C8); honesty stubs for email/message when unconfigured (C9); disable the
   windows `terminal` action until governed (C6).
3. **`app/tools/framework/capabilities.py` + new `app/tools/framework/schema.py`** — extract the typed
   action schema per tool; build the `CapabilityRegistry` artifact. The Phase-13 enums already exist;
   this formalizes them as the single source of truth for both CAP and GAMBIT capability matching.
4. **`app/core/cap/policy_engine.py`** — deny-by-default. Riskiest behavioral change; mitigate with a
   short compatibility window that logs denied-but-previously-allowed labels before enforcing, and run
   the full suite to find tests that depended on allow-by-default. Update those tests deliberately,
   not by silencing.
5. **`app/core/contracts/policy.py` + `engine.py`** — extend `ExecutionPermit` (args_hash, signature,
   expiry); orchestrator signs instead of writing a marker.
6. **`app/runtime/executor.py` + `app/tools/manager.py`** — enforce permit verification + `ToolPolicy`
   timeout/retry/concurrency.
7. **`app/tools/shell.py`** — tokenizer + denylist v2; keep the public `run` signature.
8. **`app/tools/filesystem.py` + `app/core/app.py`** — sandbox default with migration flag.
9. **`app/tools/memory.py`** — non-list backend ⇒ `ok=False` (C10).
10. **`app/internet/tool.py`** — delete `_cap_permit`; require verified permit (blocker for Phase 12).

**Preserving tests / avoiding breakage:**

- Introduce `build_tool_ecosystem()` fixture that wires a test-only CAP signer, so every existing
  `ApprovedRuntimeTask` fixture produces valid signed permits via one shim — existing runtime tests
  keep passing unchanged.
- Keep `ToolInfo`/`ToolResult` field names stable; add fields, don't rename.
- GAMBIT change is minimal: plan-time schema validation adds a rejection path before CAP; the
  capability-matching already keys off `ToolInfo.capabilities` — point both at the typed schema.
- Do not parallelize 4 and 5 (policy + signing) across two heads without a shared contract doc; they
  are the critical path.

---

## Testing Strategy

### Test categories

| Category | Scope | Examples |
|----------|-------|----------|
| **Tool contract** | every tool × every declared action returns a valid `ToolResult`, no `NameError`, honest `ok` | `test_phase14_tools_do_not_crash.py`, `test_calendar_create_result.py`, `test_communication_honest_failure.py`, `test_memory_search_fabrication.py` |
| **CAP governance** | deny-by-default; typed action validation; permit binding | `test_policy_engine_deny_by_default.py`, `test_permit_args_hash_mismatch.py`, `test_unknown_action_denied.py` |
| **Security** | bypass attempts against every guard | shell obfuscation suite, permit forgery, traversal, forged `_cap_permit` |
| **Runtime integration** | full request→CAP→runtime→tool→result with permit lifecycle | `test_cap_to_tool_end_to_end.py`, `test_runtime_timeout_retry.py` |
| **Regression** | existing suite stays green; fixture shim verified | run full `pytest` per milestone |

### Required attack scenarios (each must be a test)

1. **Fake action labels** — a task labeled `action="read"` carrying `filesystem.delete` args must be
   rejected at permit binding (args-hash mismatch) and/or at execution.
2. **Forged capability permissions** — caller appends `_cap_permit`/any permit-like marker; must be
   rejected (signature check).
3. **Shell bypass attempts** — `rm -rf  /`, `rm --recursive --force /`, `del /f/s/q C:\`, `format q:`,
   case/whitespace/flag variants, command chaining (`;`, `&&`, `|`, `>`), path obfuscation.
4. **Unauthorized filesystem access** — absolute path outside `root_dir`, `..` traversal, symlink
   escape; default config must refuse writes.
5. **Permit replay** — reuse an approved permit with different args → rejected.
6. **Mock success claims** — notification/email returning `ok=True` without a real effect must be
   caught by the result validator (invariant 5).
7. **Registry shadowing** — duplicate tool id must raise (invariant: deterministic capability set).
8. **Label collapse abuse** — planner naming a task `read_windows_clipboard` / `read_secrets` must not
   inherit READ clearance (regression on `engine.py:312-319`).

---

## Phase 12 Readiness Criteria

Phase 12 (Internet Intelligence) may begin only when **all** of the following are true and enforced by
automated tests:

1. **All tools work.** Reminder, notes, tasks, contacts, calendar execute every declared action and
   return contract-valid, honest `ToolResult`s.
2. **CAP is deny-by-default.** Unknown/undefined action labels are denied; every declared tool action
   has an explicit risk classification; no write/delete/execute/network action is executable without
   approval.
3. **Authorization is real, not labeled.** Every capability execution — including internet — requires
   a CAP-issued, signature-verified `BoundPermit` bound to tool+action+args-hash. Forged, absent,
   expired, or args-mismatched permits are rejected. **Zero self-authorization logic remains in any
   tool** (the `_cap_permit` pattern is deleted).
4. **Execution surfaces are hardened.** Shell commands are tokenized/normalized before denylist
   enforcement, with all known bypass variants covered by tests. Filesystem defaults to a sandboxed
   root with traversal always enforced (migration flag documented, not default-off).
5. **No lies.** No tool returns `ok=True` without a recorded effect; unconfigured providers return
   honest `NOT_CONFIGURED` failures; the registry cannot shadow tools; the real notification tool is
   the registered one.
6. **Memory integrity.** Memory ingestion records only verified outcomes; `MemoryTool` returns
   `ok=False` rather than fabricated counts.
7. **Gate is in place.** CI runs lint/typecheck + the full test suite (existing + new categories) on
   every change; the suite is green.

When these seven criteria are met, Phase 12 becomes a straightforward extension of an already-bound
capability boundary — the internet tool is then governed by the same signed-permit flow as everything
else, which is precisely the state required for a network-capable agent.

---

## Phase 11.5 Progress Log

| Step | Scope | Status |
|------|-------|--------|
| 1 | Tool Contract Repair (C1, C2, C10, C12 + registry guard) | ✅ Done — 25 new contract tests in `tests/tools/test_phase14_tools_contract.py`; full suite green (1598 passed) |

**Completed under step 1:**
- C1: `kwargs`→`arguments` fixed in all 5 personal tools (`calendar`, `tasks`, `notes`, `contacts`, `reminder`).
- C2: calendar create returns `ToolResult(ok=True, ...)`.
- C10: memory `_search` returns `ok=False` for non-list backend results instead of fabricating `count=1`.
- C12: `ToolRegistry.register` raises `ValueError` on duplicate tool id.
- C8 (registry half): the Phase-15 mock notification re-registration removed from `app/core/app.py`; the real
  Phase-13 notifier is the registered one. A duplicate registration would now fail loudly (C12).
- Additional latent bugs surfaced by the contract tests and fixed: `notes._update_note` splatted `note_id`/`action`
  into the store kwargs (`TypeError`); `calendar.Event.__init__` parameter `timezone` shadowed the
  `datetime.timezone` import (`AttributeError`); `reminder._snooze_reminder` stored a float instead of a
  `datetime` for `snoozed_until`.

**Still open:** items 2–9 of the Migration Strategy (typed schema, deny-by-default CAP, signed permits,
boundary verification, shell/filesystem hardening, honesty stubs C9, CI lint/typecheck gate, C11).
