# Rust TUI Protocol-First Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the terminal presentation layer from Python/Textual to a Rust `ratatui`/`crossterm` client incrementally, using a typed localhost HTTP/SSE protocol while preserving backend governance, approval, execution, persistence, and Textual rollback behavior.

**Architecture:** The Rust TUI is a client and presentation layer only. It submits requests and approval/cancellation decisions to the existing backend surface, which continues to route through `ExecutionCoordinator`, GAMBIT, CAP, signed `ExecutionPermit` objects, immediate runtime permit validation, and governed tools/providers. The migration first formalizes event and resource contracts, then proves the existing Textual client against those contracts, then adds the Rust client beside it and keeps Textual available until parity and rollback gates pass.

**Tech Stack:** Existing Python/FastAPI/Pydantic backend, `RuntimeEventBus`, `ExecutionCoordinator`, CAP, GAMBIT, signed permits, governed tools, HTTP/JSON, Server-Sent Events, Rust `ratatui`, `crossterm`, `serde`, `serde_json`, `reqwest`, and the repository’s existing pytest test suite.

**Spec:** `docs/superpowers/specs/2026-11-24-rust-tui-migration-design.md`

## Global Constraints

- CAP remains the authority for policy, risk, privacy, permissions, and approval.
- GAMBIT remains the authority for goal parsing, decomposition, intent extraction, and planning.
- Signed permits remain mandatory for governed effects.
- Runtime permit validation remains mandatory immediately before execution.
- The TUI is a client/presentation layer and must never execute tools directly.
- The TUI must not forge, modify, replay, or locally substitute approval or permit state.
- Backend authorization must validate every state-changing request from every client.
- Existing tools and providers remain reachable only through governed backend paths.
- Use an incremental migration; do not perform a big-bang rewrite.
- The Python/Textual TUI remains available as a rollback path until Rust parity is demonstrated.
- The backend remains loopback-only; this plan does not add public deployment, remote authentication, or multi-tenant behavior.
- Client input, event payloads, paths, and tool arguments are untrusted until validated by the backend.
- Protocol payloads use typed JSON serialization. Do not use pickle or client-defined executable payloads.
- Protocol versioning is additive within a major version; breaking wire changes require a new major version and an explicit compatibility decision.
- Event sequence numbers are backend-assigned and are never accepted from a client as authority.
- Resource context is backend-owned and must never expand filesystem or tool permissions.
- Security controls from Section 6 of the design are mandatory for every milestone: idempotency keys, loopback-only binding, explicit DTO redaction, SSE sequence/cursor binding, opaque approvals, opaque resource IDs, terminal sanitization, and fail-closed version negotiation.
- No staged or committed file may contain credentials, API keys, signing keys, `.env`, local databases, permit material, runtime state, or generated private data.
- No implementation, Rust project creation, dependency installation, CAP change, GAMBIT change, signed-permit change, runtime-authorization change, Textual removal, commit, or push is part of this planning gate.
- Never stage or commit credentials, API keys, signing keys, `.env` files, local databases, permit material, runtime state, or private generated data.
- Every completed implementation milestone must have focused tests, documented verification commands, a recorded status/evidence update, and a focused commit before any possible push.

## Review Focus

1. **Search result loss:** A successful search must produce structured results and sources that normal TUI mode renders without requiring debug tool-output mode. Test the full governed path and the wire payload.
2. **Follow-up resource ambiguity:** “Write inside that file” must resolve only to one backend-owned, validated resource; zero or multiple candidates must produce clarification without executing a write.
3. **Approval substitution:** Allow and deny must be sent to the backend with the real approval identifier; the client must never create or alter a permit locally. Test that denial starts no governed tool effect.
4. **Reconnect ordering:** A reconnect must retain the same session/execution identity and replay only events after the requested cursor. Test duplicate, stale, and out-of-order events without mutating client state incorrectly.
5. **Sensitive event leakage:** Protocol serialization must omit permit material, integrity digests, secrets, and other sensitive metadata while retaining the bounded approval and result data required for presentation.

## File Map and Responsibilities

The following files are the expected change surface. Implementers must confirm line locations before editing and must not broaden the surface without recording why in this plan.

| Path | Responsibility in this migration |
|---|---|
| `app/api/protocol.py` | New public wire-contract models, protocol version negotiation, event serialization, cursor/error models, and sensitive-field filtering. |
| `app/api/schemas.py` | Extend existing request/response models only where the HTTP contract needs an explicit protocol version or structured error/cursor response; preserve compatibility fields and routes. |
| `app/api/execute.py` | Formalize execution HTTP/SSE request and event flow, reconnect cursor handling, ownership checks, and disconnect behavior without creating a second execution path. |
| `app/core/events.py` | Add backend-assigned sequence/version metadata and the canonical structured event types while retaining internal event-bus behavior. |
| `app/core/execution_coordinator.py` | Expose the existing lifecycle and event history through the protocol adapter; preserve coordinator ownership, cancellation, approval, and runtime delegation. |
| `app/agent/production.py` | Keep the existing UI-facing facade interface-neutral and map structured backend events/resources without direct tool execution. |
| `app/core/resource_context.py` | New backend-owned session resource context and deterministic reference resolver, if no more specific existing session-resource module is found during implementation. |
| `app/core/gambit/goal_parser.py` and `app/core/gambit/resource_parser.py` | Read-only integration boundary initially. Do not change GAMBIT parsing unless implementation proves it is unavoidable; any such change stops for architecture review. |
| `app/tools/filesystem.py` and `app/tools/resolver.py` | Preserve existing security validation and governed dispatch. Only add narrowly scoped result metadata if required for canonical file events; never move authorization into the client. |
| `app/tui/models.py` | Add presentation models for structured search/source and file events while retaining existing message compatibility. |
| `app/tui/renderer.py` | Render structured search, source, file, error, and approval data in normal mode with bounded/safe fields. |
| `app/tui/app.py` | Adapt the Textual client to the protocol/event models surgically; preserve the pre-existing working-tree changes and button-driven approval behavior. |
| `clients/rust-tui/Cargo.toml` | New isolated Rust TUI package and pinned dependencies after the implementation plan is approved. |
| `clients/rust-tui/src/main.rs` | Rust client entry point and terminal lifecycle only. |
| `clients/rust-tui/src/protocol.rs` | Rust wire models and JSON/SSE event decoding. |
| `clients/rust-tui/src/transport.rs` | Localhost HTTP request, SSE stream, reconnect, cursor, approval, cancellation, and structured-error transport. |
| `clients/rust-tui/src/state.rs` | Typed execution state machine, sequence validation, duplicate/stale/out-of-order handling, and replay requests. |
| `clients/rust-tui/src/ui.rs` | `ratatui`/`crossterm` rendering for conversation, activity, approvals, search results/sources, files, and errors. |
| `clients/rust-tui/tests/` | Rust protocol/state/transport fixture tests; no direct tool or governance implementation. |
| `tests/api/` | Python protocol schema, HTTP authorization, SSE, cursor, and reconnect tests. |
| `tests/core/` | Event bus sequencing, resource context, and coordinator lifecycle tests. |
| `tests/integration/` | Full request → plan → CAP → permit → runtime → tool → event → client-facing result regressions. |
| `tests/tui/` | Textual compatibility, structured rendering, and approval-button regression tests. |
| `docs/superpowers/plans/2026-11-24-rust-tui-migration.md` | This implementation plan, milestone status/evidence, parity checklist, rollback criteria, and handoff record. |

If the repository already has a canonical module for any proposed new responsibility, use that module instead of creating a duplicate and update this map before implementation.

---

## Milestone Status

| Milestone | Status at planning gate | Completion evidence required |
|---|---|---|
| M0. Implementation gate and branch baseline | **Completed** | User approved this plan; feature branch `feature/rust-tui-protocol-migration` created at commit `b17fec9`; baseline tests: 40 passed, 1 failed (pre-existing flaky DDGS search test `tests/integration/test_search_e2e.py::TestSearchE2E::test_internet_search_with_approval` - DDGS backend unavailable, not a migration regression); loopback-only binding confirmed via `app/config/settings.py:77` (`host="127.0.0.1"`) and `app/core/app.py`; RULES.md and docs/superpowers/ committed as baseline checkpoint; staged-file secret review clean. |
| M1. Typed protocol and event envelope | **Completed** | Commit `feb419e`: `app/api/protocol.py`, `app/api/schemas.py`, `app/core/events.py`, `app/api/execute.py`, `app/core/execution_coordinator.py`; 37 tests passing (`tests/api/test_protocol_contract.py` 19, `tests/core/test_events.py` 18); protocol version negotiation, event envelope with sequences, idempotency keys, SSE cursor binding, explicit DTOs with `extra=forbid`, redaction of sensitive fields, fail-closed version negotiation all verified. |
| M2. HTTP/SSE execution and reconnect contract | **Completed** | Commit `806ea91`: `app/api/execute.py` `serialize_sse_event` with SSE `id:` = sequence; `app/core/execution_coordinator.py` CREATED/PLANNING state handling for `wait=False`; 30 tests passing (`tests/api/test_m2_http_sse_execution.py`); execution creation with idempotency, SSE stream with cursor replay, reconnect without new execution, ownership checks, structured cursor-expired response, approval/cancellation endpoints all verified. |
| M3. Structured search/file/assistant events | **Completed** | Commit `64ce6ea`: 14 typed Pydantic models for structured event payloads (Search, File, Assistant events), 23 contract tests passing (`tests/api/test_m3_structured_events.py`), all 112 API/core tests passing. |
| M4. Backend-owned resource context | **Completed** | Commit in tree: `app/core/resource_context.py` (326 lines), `tests/core/test_resource_context.py` 20/20 unit tests + 2 regression tests (`TestM4FileFollowUpRegression`) all passing; 132 total API/core tests pass. Unique "that file" resolution, explicit-path precedence, ambiguity clarification, opaque resource IDs, session/workspace binding, and security validation all verified. |
| M5. Textual protocol compatibility | **Completed** | Commit `45665ed`: `app/tui/app.py`, `app/tui/renderer.py`, `app/tui/models.py` updated to render structured protocol events (search results, sources, file ops, assistant tokens, approvals, errors) in normal TUI mode; approval/denial/cancel/error behavior preserved via button-driven CAP integration; no local approval substitution. 257 TUI tests passing (`tests/tui/`). |
| M6. Rust client scaffold and typed state machine | Not started | Rust builds/tests against fixtures and has no tool/governance code; duplicate/stale/out-of-order handling verified. |
| M7. Rust TUI interaction and reconnect parity | Not started | Manual and automated parity checks pass for normal, approval, denial, cancellation, errors, and reconnects. |
| M8. Release gate and rollback verification | Not started | Full suite, security review, staged-file review, parity checklist, and documented Textual rollback pass. |

Every implementation task below must update the corresponding row with one of `Not started`, `In progress`, `Blocked`, or `Completed` and link the commands/results used as evidence. No row may be marked `Completed` from code inspection alone.

## Protocol Decisions

These are planning decisions for the implementation; they do not authorize implementation before this plan is approved.

### Wire format and versioning

- Use UTF-8 JSON for HTTP bodies and SSE `data` fields.
- Define `PROTOCOL_VERSION = "1.0"` in `app/api/protocol.py`.
- A wire event contains at least: `protocol_version`, `event_id`, `sequence`, `timestamp`, `session_id`, `execution_id`, `event_type`, `status`, and typed `payload`.
- `sequence` is a positive integer assigned by the backend for the execution event stream and begins at 1 for each execution. It is not derived from a client cursor and is not accepted from a client.
- SSE uses the event sequence as the SSE `id`; the JSON event type is also emitted as the SSE `event` name.
- JSON model serialization must use the existing Pydantic configuration and explicit JSON-compatible dumps. Internal Python objects, exceptions, permits, and signing material must never be serialized directly.
- A client may send the supported protocol major/minor it understands. The server accepts the same major and an additive compatible minor; unsupported major versions receive a structured `PROTOCOL_VERSION_UNSUPPORTED` error rather than silent downgrade.
- Existing compatibility endpoints remain available during migration. Additive protocol fields must not break the current Textual client or existing API tests.
- A breaking change to request meaning, event ordering, authentication/ownership, or permit/approval semantics requires a new major version and an explicit architecture review.

### Event ordering and cursor policy

- `after` is an exclusive cursor: a client requesting `after=N` receives only events with `sequence > N`.
- `Last-Event-ID`, when present, is parsed as a non-negative integer. If both `after` and `Last-Event-ID` are present, they must agree; otherwise return a structured client error.
- The backend validates session/execution ownership before revealing event history.
- Reconnecting to an active execution does not create a new execution and does not restart planning or tools.
- The reconnect stream replays retained events in ascending sequence order, then follows new events.
- A disconnect from a reconnect-only stream detaches the subscriber and does not cancel the execution. Preserve the current compatibility endpoint’s documented disconnect behavior unless a focused compatibility test proves it must change.
- If a cursor predates retained history, return a structured cursor-expired response containing only safe cursor bounds; do not silently skip events. Current in-memory execution history must support the active-execution acceptance test.
- The Rust and Textual client state machines must not render or commit an event that is stale, conflicting at an already accepted sequence, or out of order. Exact duplicate replay is idempotently ignored; a conflicting duplicate or sequence gap causes a replay/reconnect request.

### Structured event policy

Add protocol-facing event types for the design-required lifecycle categories without deleting existing internal events:

- execution accepted/created/started/completed/failed/cancelled/timed out
- approval requested/resolved/approved/denied/expired as applicable to existing backend state
- tool started/progress/completed/failed
- search started/results/sources/completed
- file created/written/read/failed
- assistant token/message
- structured error and reconnect/cursor outcomes

Search result payloads must contain typed, bounded result fields such as title, URL, snippet, rank, and source metadata. File payloads must contain only safe canonical resource identifiers/path display data and operation metadata, never permits or hidden authorization state. Event adapters must preserve the canonical result even when a generic tool-result fallback is also emitted.

### Resource-context policy

- The backend owns session resource context, including active workspace and bounded records for successful file create/open/read/write operations.
- Context is updated only from backend-validated successful operations/events, never from client claims or merely typed text.
- Explicit, backend-validated paths take precedence over inferred references.
- A phrase such as “that file” resolves only when one candidate is uniquely identified by the session context and workspace rules.
- No candidate or multiple candidates produces a clarification response and no governed write is started.
- Resource resolution must use existing path normalization and filesystem security policy. It must not grant access outside the already authorized workspace or alter CAP/runtime permit scope.
- The first implementation should be an adapter/request-preparation boundary around existing GAMBIT input. `app/core/gambit/goal_parser.py` and `app/core/gambit/resource_parser.py` remain unchanged unless a concrete integration blocker is found; such a blocker is an explicit stop condition below.

---

## Task 0: Implementation Gate, Branch, and Baseline

**Files:**
- Read: `RULES.md`, `docs/superpowers/specs/2026-11-24-rust-tui-migration-design.md`, this plan, and current migration-related tests.
- Modify: none before plan approval.
- Preserve: current changes in `app/tui/app.py`, `RULES.md`, and `docs/superpowers/`.

**Interfaces:**
- Consumes: approved design and this implementation plan.
- Produces: an isolated feature branch, recorded baseline test result, and a clean inventory separating pre-existing user changes from migration changes.

- [x] **Step 1: Obtain explicit approval of this implementation plan.** ✅ **COMPLETED**

User provided explicit approval via second pasted_content message. Do not create the Rust project, install dependencies, or modify product code before approval.

- [x] **Step 2: Create the feature branch without discarding existing work.** ✅ **COMPLETED**

Created branch `feature/rust-tui-protocol-migration` at commit `b17fec9` (chore: add migration plan, design, and rules for Rust TUI migration). Pre-existing `app/tui/app.py` change preserved in working tree. Working-tree inventory confirmed clean.

- [x] **Step 3: Run the baseline focused tests.** ✅ **COMPLETED**

Ran:
```text
python -m pytest tests/api tests/core tests/integration tests/tui -x --tb=short
```

**Results:** 40 passed, 1 failed.

**Pre-existing failure:** `tests/integration/test_search_e2e.py::TestSearchE2E::test_internet_search_with_approval` — "Search completed but returned no results" after 2 retries; DDGS warnings show `lite - backends do not exist or are disabled. Available: brave, duckduckgo, google, grokipedia, mojeek, startpage, wikipedia, yahoo`. This is a network-dependent flaky test (DDGS backend unavailable upstream), NOT a migration regression. Recorded separately as pre-existing.

- [x] **Step 4: Confirm the backend boundary is loopback-only and inspect staged-file hygiene rules.** ✅ **COMPLETED**

Verified via `app/config/settings.py:77` — `host="127.0.0.1"` is the default. `app/core/app.py` uses `settings.host` with no explicit bind override. Loopback-only binding confirmed. No binding, authentication, or secret-handling changes made.

- [x] **Step 5: Commit only an approved, isolated planning/branch-preparation checkpoint if requested.** ✅ **COMPLETED**

Committed `RULES.md` and `docs/superpowers/` as baseline checkpoint at `b17fec9`. Commit message includes required attribution:
```text
Co-Authored-By: Claude Code <noreply@anthropic.com>
```
No push performed (awaiting explicit remote/branch authorization for subsequent milestones).

**Milestone gate:** CAP, GAMBIT, signed permits, runtime validation, and Textual are untouched. Any unexpected dependency on changing them stops implementation.

**M0 Status: Completed** — Evidence recorded above. Ready for M1 confirmation.

---

## Task 1: Define the Typed Protocol and Event Envelope

**Files:**
- Create: `app/api/protocol.py`
- Modify: `app/api/schemas.py` only for shared request/response compatibility fields and structured protocol errors.
- Modify: `app/core/events.py`
- Test: `tests/api/test_protocol_contract.py`
- Test: `tests/core/test_events.py` or the repository’s existing event-bus test module.

**Interfaces:**
- Consumes: `RuntimeEvent`, `RuntimeEventPayload`, `RuntimeEventBus`, existing Pydantic API schemas.
- Produces: `PROTOCOL_VERSION`, typed wire models, a `serialize_runtime_event(event: RuntimeEvent) -> ProtocolEvent` adapter, protocol-version validation, redaction, and event-bus sequence/history APIs.

- [ ] **Step 1: Add failing protocol-schema tests.**

Cover:

- required event envelope fields and JSON round-trip
- positive backend sequence values
- protocol version presence
- typed search/file payload validation
- rejection of malformed versions, negative sequences, missing execution/session identity, and non-JSON values
- omission of `permit`, `execution_permit`, `integrity_digest`, `secret`, and equivalent sensitive metadata from public DTOs
- additive optional fields remaining compatible within major version
- unsupported major version returning the structured protocol error code
- client idempotency key acceptance and duplicate-key dedup (same key returns same execution ID, no second execution)
- `extra=forbid` rejection of unknown security-relevant fields

- [ ] **Step 2: Add failing event-bus sequencing tests.**

Publish events for one execution and assert sequences `1, 2, 3`; request history after `1` and assert only `2, 3`; publish events for a second execution and assert its stream begins at `1` when the existing bus is shared. Assert event IDs remain unique and history order is stable.

- [ ] **Step 3: Implement the wire models and serializer in `app/api/protocol.py`.**

Use Pydantic models with explicit bounds and JSON-compatible payload types. Keep the public wire model separate from internal event objects so sensitive internal metadata is filtered by an allowlist/explicit projection rather than copied wholesale.

- [ ] **Step 4: Add sequence and protocol metadata to `app/core/events.py`.**

Assign sequence numbers in the backend event bus. Keep the counter backend-owned and execution-scoped. Add a cursor-aware history method that uses sequence comparison rather than list position. Preserve existing subscribers and internal event behavior.

- [ ] **Step 5: Add only additive shared schema fields in `app/api/schemas.py`.**

Existing callers that omit the protocol version must continue to work on compatibility routes. New protocol-aware callers must be able to state the version they support. Do not accept client-supplied event sequence, permit, or authorization state.

- [ ] **Step 6: Run the focused protocol/event tests.**

Run:

```text
python -m pytest tests/api/test_protocol_contract.py tests/core/test_events.py -v
```

Expected: all pass, with no changes to CAP, GAMBIT, permit validation, or runtime dispatch.

- [ ] **Step 7: Inspect the diff and stage only Task 1 files.**

Run:

```text
git diff --check
git diff -- app/api/protocol.py app/api/schemas.py app/core/events.py tests/api/test_protocol_contract.py tests/core/test_events.py
git status --short
```

Run a staged-file secret/runtime-state review before any commit.

- [ ] **Step 8: Commit the isolated protocol milestone.**

Use a focused message such as `feat: define versioned execution protocol` and include the required attribution line. Push only after explicit remote/branch authorization.

**Acceptance criteria:** Every protocol event has execution/session identity, sequence, timestamp, and version; serialization is typed and redacted; cursors use sequence numbers; existing internal event consumers remain compatible; focused tests pass.

**Milestone gate:** No event schema may expose signed permits or change the authority of CAP/runtime validation.

---

## Task 2: Formalize HTTP/SSE Execution, Approval, Cancellation, and Reconnect

**Files:**
- Modify: `app/api/execute.py`
- Modify: `app/api/schemas.py` and/or `app/api/protocol.py`
- Modify: `app/core/execution_coordinator.py` only to expose the existing lifecycle/history semantics needed by the protocol adapter.
- Test: existing `tests/api/test_phase15_http_execution.py` and neighboring execution API tests.
- Test: create `tests/api/test_execution_sse_reconnect.py` if no focused reconnect module exists.

**Interfaces:**
- Consumes: Task 1 protocol models, `ExecutionCoordinator.events(...)`, `start_execution(...)`, `submit_approval(...)`, `cancel_execution(...)`, existing ownership checks, and existing SSE helper.
- Produces: a formal execution stream contract, cursor-aware JSON event retrieval, and a reconnectable SSE endpoint such as `GET /executions/{execution_id}/events/stream` without replacing compatibility endpoints.

- [ ] **Step 1: Add failing request/response and authorization tests.**

Cover:

- `POST /executions` starts only through `ExecutionCoordinator` and returns the same execution identity used by the stream.
- approval requests contain only `approval_id`, `decision`, and bounded reasons; permit material is ignored/rejected and never trusted.
- cancellation is ownership-checked and delegated to the coordinator.
- another session/principal cannot inspect events, submit approval, cancel, or retrieve results.
- malformed/unsupported protocol versions produce structured errors.

- [ ] **Step 2: Add failing SSE replay tests.**

Start an execution with a deterministic fake backend/orchestrator, publish events with sequences 1–4, connect with `after=2`, and assert the stream emits only 3 and 4 in order with SSE `id:` matching those sequences. Assert `Last-Event-ID: 2` has the same behavior.

- [ ] **Step 3: Add failing cursor edge-case tests.**

Cover missing cursor, zero cursor, cursor beyond the latest event, conflicting `after` and `Last-Event-ID`, expired cursor, malformed non-integer cursor, duplicate replay request, reconnect after a terminal event, cursor for another execution/principal (must be rejected), and cursor predating retained history (structured cursor-expired response, no silent skip). Assert each result is deterministic and structured.

- [ ] **Step 4: Add a failing disconnect/reconnect identity test.**

Disconnect from the reconnect-only stream while execution remains active, reconnect with the last accepted sequence, and assert the same execution continues without a second planning/tool invocation. Assert a dropped/retried stream with the same idempotency key produces one execution ID and one side effect. Preserve and separately test the documented compatibility behavior of `POST /execute/stream`.

- [ ] **Step 5: Implement the protocol adapter in `app/api/execute.py`.**

Use the existing coordinator-backed routes. Serialize events through Task 1. Emit `event: <event_type>`, `id: <sequence>`, and one JSON `data` object. Validate ownership before reading history. Do not accept client event sequence as state. Do not create a second execution/orchestration path.

- [ ] **Step 6: Implement reconnect semantics.**

Replay retained events with `sequence > after`, follow new events, and close cleanly after terminal replay when no more events are expected. A reconnect-only client disconnect detaches the stream rather than cancelling the execution. If the cursor is outside retained history, return a structured cursor-expired response instead of silently skipping events.

- [ ] **Step 7: Run focused API/SSE tests.**

Run:

```text
python -m pytest tests/api/test_phase15_http_execution.py tests/api/test_execution_sse_reconnect.py -v
```

Expected: existing API behavior remains passing and new sequence/reconnect/ownership tests pass.

- [ ] **Step 8: Run the HTTP contract diff and secret review, then commit.**

Use a focused commit such as `feat: add reconnectable execution event streaming`. Do not push without explicit authorization.

**Acceptance criteria:** A client can reconnect to an active local execution by cursor without losing execution identity; stale cursors are explicit errors; approval, denial, cancellation, and result access remain backend-authorized and coordinator-backed; compatibility endpoints remain available.

**Milestone gate:** No route may call a tool, provider, CAP decision, permit constructor, or runtime executor directly.

---

## Task 3: Emit Structured Search, Source, File, Assistant, and Error Events

**Files:**
- Modify: `app/core/events.py`
- Modify: the existing backend event/result adapter identified during implementation, expected candidates `app/agent/production.py`, runtime event publication code, and the relevant search/tool integration module.
- Modify: `app/tools/filesystem.py` only if a narrowly scoped safe result identifier is needed for canonical file events; retain all existing security checks.
- Test: `tests/integration/test_search_e2e.py` and existing search/provider tests.
- Test: create `tests/integration/test_structured_runtime_events.py` if no suitable module exists.

**Interfaces:**
- Consumes: governed tool/provider results, Task 1 typed event payloads, and the existing `RuntimeEventBus`.
- Produces: canonical search result/source events and file lifecycle events that are visible to both clients without requiring clients to interpret arbitrary tool dictionaries.

- [ ] **Step 1: Add failing structured search tests.**

Run a deterministic search fixture through the existing request → GAMBIT → CAP → signed permit → runtime → search provider path. Assert the event stream contains typed search-started, search-results, and source data with title/URL/snippet/rank/source fields and a final synthesis/result. Assert normal mode does not rely on debug-only generic tool output. Assert search/event payloads contain no permit material, signing keys, or secret-bearing tool arguments.

- [ ] **Step 2: Add failing file lifecycle event tests.**

For a governed file create, write, and read, assert the backend emits safe structured file-created/file-written/file-read data only after the corresponding operation succeeds. For denial, cancellation, and tool failure, assert no false success event is emitted and a structured failure event is present.

- [ ] **Step 3: Add failing assistant/error event tests.**

Assert token/message events preserve order and execution identity, and structured errors expose stable error codes/messages without raw tracebacks, permits, signing material, or secrets.

- [ ] **Step 4: Implement explicit event payload models and backend adapters.**

Use bounded typed projections of search/provider/filesystem results. Preserve generic internal events where existing consumers require them, but make structured events canonical for protocol clients. Do not stringify structured results into an opaque tool message.

- [ ] **Step 5: Verify approval and runtime invariants through the same full path.**

The search/file event adapter must observe results after governed execution. It must not invoke a provider or filesystem operation, approve an action, construct a permit, or replace `enforce_cap_permit(...)`.

- [ ] **Step 6: Run focused structured-event tests.**

Run:

```text
python -m pytest tests/integration/test_search_e2e.py tests/integration/test_structured_runtime_events.py -v
```

Expected: search results and sources are structured, file events reflect actual outcomes, and approval/denial/cancellation/failure tests remain backend-enforced.

- [ ] **Step 7: Review payloads for leakage and commit the isolated milestone.**

Use a focused commit such as `feat: expose structured search and file events`, after staged-path and secret review.

**Acceptance criteria:** Search results and sources are present as typed events; file lifecycle events are truthful and ordered; generic rendering is no longer the only path for structured results; sensitive governance metadata is absent.

**Milestone gate:** Existing tools/providers, CAP, GAMBIT, signed permits, and runtime enforcement remain authoritative and unchanged in behavior.

---

## Task 4: Add Backend-Owned Resource Context and Deterministic File Follow-Ups

**Files:**
- Create: `app/core/resource_context.py` unless an existing session-resource module is confirmed during implementation.
- Modify: `app/core/execution_coordinator.py` or the existing backend request-preparation boundary to attach session-owned context without moving planning/authorization into the client.
- Modify: `app/agent/production.py` and `app/api/execute.py` only at the shared backend request boundary so Textual and Rust receive identical behavior.
- Read/integrate: `app/core/gambit/goal_parser.py`, `app/core/gambit/resource_parser.py`, `app/tools/filesystem.py`, `app/tools/resolver.py`.
- Test: create `tests/core/test_resource_context.py`.
- Test: create or extend `tests/integration/test_file_followup_context.py`.

**Interfaces:**
- Consumes: session ID, active workspace, successful structured file events, existing resource/path parsing and filesystem security policy.
- Produces: backend-owned `ResourceContext`, unique reference resolution, explicit-path precedence, and a clarification result that starts no governed effect when resolution is unsafe or ambiguous.

- [ ] **Step 1: Add failing unit tests for context state.**

Cover successful create/open/read/write updates, bounded history, session isolation, workspace isolation, opaque server-issued resource IDs, and rejection of client-provided fake “last file” metadata. Context must update only from backend-confirmed operations.

- [ ] **Step 2: Add failing resolution tests.**

Cover:

- explicit validated path wins over inferred context;
- one last-created/opened file resolves “that file” deterministically;
- no candidate returns a structured clarification/unavailable result;
- multiple candidates return a structured ambiguity result with safe candidate labels;
- path traversal, UNC/drive-relative, null-byte, and outside-workspace inputs never bypass existing security validation;
- resource context does not alter required permissions, action type, target validation, or permit digest.

- [ ] **Step 3: Add the full file-follow-up regression test.**

Execute “create a file” through the normal governed path, then submit “write inside that file” in the same session. Assert the second request targets the backend-identified file. Repeat with two candidates and assert a clarification response and zero filesystem write calls.

- [ ] **Step 4: Implement the context store and resolver.**

Store canonical backend-derived resource records keyed by session/workspace. Keep only bounded safe metadata needed for deterministic reference resolution. Do not use browser/client storage as authority. Use existing path normalization and filesystem policy before producing a resolved request.

- [ ] **Step 5: Integrate request preparation without changing GAMBIT authority.**

Resolve the resource reference at the backend boundary before the existing planning path, preserving the original user request for audit and passing only an explicit, validated resource reference into the existing planner/tool path. If this requires changing GAMBIT parser semantics rather than adding an adapter, stop and request architecture review before editing GAMBIT.

- [ ] **Step 6: Run focused resource and integration tests.**

Run:

```text
python -m pytest tests/core/test_resource_context.py tests/integration/test_file_followup_context.py -v
```

Expected: unique references work, ambiguity never performs a write, and all existing filesystem security tests pass.

- [ ] **Step 7: Review the diff and commit only resource-context files/tests.**

Use a focused commit such as `feat: add backend resource context for file followups`. Do not include unrelated filesystem cleanup.

**Acceptance criteria:** Creating/opening a file followed by a unique “that file” reference targets the correct backend-owned resource; ambiguous references request clarification; explicit paths retain precedence; permissions are not expanded.

**Milestone gate:** Any need to alter GAMBIT planning semantics, CAP policy, signed permits, or runtime enforcement is a blocker requiring explicit architecture review.

---

## Task 5: Make the Python/Textual Client Protocol-Compatible

**Files:**
- Modify: `app/tui/models.py`
- Modify: `app/tui/renderer.py`
- Modify: `app/tui/app.py` surgically; preserve all unrelated pre-existing working-tree changes.
- Test: existing `tests/tui/` modules and create focused tests for structured rendering/approval if absent.

**Interfaces:**
- Consumes: Task 1 wire/event models and Task 3/4 structured events.
- Produces: Textual rendering of search results/sources/files/errors and unchanged backend-delegated approval, denial, cancellation, and reconnect behavior.

- [ ] **Step 1: Add failing renderer tests.**

Assert normal mode renders structured search result titles, URLs, snippets, and sources; file lifecycle events show safe paths/status; generic legacy tool output still renders; malformed payloads become bounded errors rather than crashing the UI.

- [ ] **Step 2: Add failing approval/cancellation compatibility tests.**

Assert clicking Allow/Deny sends the backend approval identifier and decision, while typed words such as `approved` remain ordinary chat input. Assert cancellation calls the coordinator/API and never executes a tool from the UI.

- [ ] **Step 3: Implement presentation models and rendering.**

Add dedicated conversation content models or bounded render adapters in `app/tui/models.py` and `app/tui/renderer.py`. Keep sensitive approval fields filtered. Retain generic fallback only for backward compatibility, not as the canonical search path.

- [ ] **Step 4: Adapt the stream consumer in `app/tui/app.py`.**

Map protocol event names/payloads to presentation messages. Keep the app as a client, preserve existing event-bus subscriptions, and do not add direct imports/calls to filesystem, search providers, runtime executors, CAP, or permit constructors.

- [ ] **Step 5: Run focused Textual tests.**

Run:

```text
python -m pytest tests/tui -v
```

Then run the relevant structured search/file integration tests from Tasks 3 and 4.

- [ ] **Step 6: Manually verify the rollback client remains launchable.**

Use the existing documented Textual launch command. Verify normal search output, file follow-up, Allow, Deny, cancellation, failure, and reconnect presentation without changing the backend authority.

- [ ] **Step 7: Commit the compatibility milestone after diff and secret review.**

Use a focused message such as `feat: render structured execution events in textual tui` and include the required attribution.

**Acceptance criteria:** Textual displays structured search results and sources in normal mode, preserves existing approval button semantics, and remains a functioning rollback client against the same backend protocol.

**Milestone gate:** Textual remains available; no direct tool execution or local approval substitution is introduced.

---

## Task 6: Create the Isolated Rust Client and Typed State Machine

**Files:**
- Create: `clients/rust-tui/Cargo.toml`
- Create: `clients/rust-tui/src/main.rs`
- Create: `clients/rust-tui/src/protocol.rs`
- Create: `clients/rust-tui/src/transport.rs`
- Create: `clients/rust-tui/src/state.rs`
- Create: `clients/rust-tui/src/ui.rs`
- Create: `clients/rust-tui/tests/protocol_fixtures.rs`
- Create: `clients/rust-tui/tests/state_machine.rs`
- Create: `clients/rust-tui/tests/sse_reconnect.rs`
- Modify: packaging/launcher configuration only after locating the existing TUI entrypoint; preserve Textual selector/fallback.

**Interfaces:**
- Consumes: Task 1 JSON/SSE contract and Task 2 HTTP routes.
- Produces: a Rust client with typed request/event models, backend-only transport, deterministic event state, and no duplicated governance/tool logic.

- [ ] **Step 1: Create the minimal Rust package only after the Python protocol is stable.**

Pin compatible versions of `ratatui`, `crossterm`, `serde`, `serde_json`, `reqwest`, and the async/runtime dependencies in the new package. Do not add Rust dependencies to Python or move Python governance code.

- [ ] **Step 2: Add failing Rust protocol fixture tests.**

Decode representative execution, approval, search, source, file, token, error, and terminal events. Reject missing identity/version/sequence and sensitive fields where the client contract requires rejection. Assert terminal content is sanitized (ANSI/OSC/control sequences stripped) before rendering. Assert unsupported protocol major versions are rejected rather than silently downgraded.

- [ ] **Step 3: Add failing state-machine tests.**

Implement and test `apply_event` behavior for:

- first event at sequence 1;
- exact duplicate event ignored idempotently;
- stale event rejected/ignored without UI mutation;
- conflicting duplicate rejected as a protocol error;
- sequence gap held/rejected and converted into a replay request;
- terminal events stop further mutation;
- search/source/file/approval/error state updates remain tied to the execution ID.

- [ ] **Step 4: Implement `transport.rs`.**

Use only localhost HTTP/SSE. Implement start execution, event stream, reconnect with `after`/`Last-Event-ID`, approval submission, cancellation, and structured error decoding. The transport must never accept or send permits, tool arguments outside backend request contracts, or locally authorized effects.

- [ ] **Step 5: Implement typed state in `state.rs`.**

Track session ID, execution ID, protocol version, last accepted sequence, lifecycle status, pending approval display data, search results/sources, file events, assistant content, errors, and reconnect state. Keep duplicate/stale/out-of-order behavior deterministic and testable without a terminal.

- [ ] **Step 6: Implement terminal lifecycle and minimal rendering.**

`main.rs` owns terminal setup/restore and event-loop lifecycle. `ui.rs` renders state through `ratatui` and `crossterm`; it does not plan, authorize, approve, or execute tools. Approval and cancellation actions call transport endpoints only.

- [ ] **Step 7: Run Rust tests and formatting.**

Run:

```text
cargo fmt --manifest-path clients/rust-tui/Cargo.toml -- --check
cargo test --manifest-path clients/rust-tui/Cargo.toml
```

Expected: protocol/state/reconnect tests pass without a running backend or network dependency.

- [ ] **Step 8: Build a local client smoke test against the existing backend.**

Start the loopback backend using the repository’s documented command, run the Rust client, and verify session/execution identity, structured search display, approval buttons, denial, cancellation, errors, and terminal cleanup. Do not expose the server beyond loopback.

- [ ] **Step 9: Commit the isolated Rust scaffold/state milestone.**

Inspect `Cargo.lock`, build outputs, and staged paths for generated/private data before committing. Use a focused message such as `feat: add rust tui protocol client` with the required attribution.

**Acceptance criteria:** Rust compiles and tests without Python tool logic; the client renders typed protocol state; reconnect uses the same execution ID and cursor; duplicate/stale/out-of-order events cannot corrupt state; approvals/cancellation are backend requests only.

**Milestone gate:** The Rust package contains no CAP, GAMBIT, permit-signing, runtime-validation, filesystem, search-provider, or direct tool-execution implementation.

---

## Task 7: Prove Rust/Textual Behavioral Parity and Compatibility Selection

**Files:**
- Modify: the existing TUI launcher/CLI selection file identified during implementation, or add a narrowly scoped selector under the existing application entrypoint.
- Modify: `app/tui/` only for shared protocol-compatible behavior discovered by parity tests.
- Test: `tests/integration/` and `clients/rust-tui/tests/`.
- Documentation: this plan’s parity checklist and the existing project run documentation if a selector must be documented.

**Interfaces:**
- Consumes: Task 5 Textual client and Task 6 Rust client against the same HTTP/SSE backend.
- Produces: explicit client selection with Textual fallback and evidence that both clients observe identical backend governance/results.

- [ ] **Step 1: Define fixture-driven parity cases.**

Use the same backend event fixtures and deterministic fake provider/tool results for both clients. Cover ordinary assistant response, search results/sources, create-then-write file context, approval allow, approval deny, cancellation, provider/tool failure, reconnect, stale event, duplicate event, and out-of-order event.

- [ ] **Step 2: Add failing parity assertions.**

Assert both clients retain the same session/execution identity, event order, terminal outcome, approval outcome, search/file data, and structured error code. Presentation wording may differ, but governance and lifecycle state may not.

- [ ] **Step 3: Implement explicit client selection.**

Keep the existing Textual path as the default or documented fallback until the release gate is met. Add Rust selection without removing the Textual import/entrypoint. Invalid selection must fail safely and identify the fallback command.

- [ ] **Step 4: Run parity and full focused suites.**

Run:

```text
python -m pytest tests/api tests/core tests/integration tests/tui -x --tb=short
cargo test --manifest-path clients/rust-tui/Cargo.toml
```

Expected: all baseline tests plus migration tests pass; no network-dependent test is required for protocol/state coverage.

- [ ] **Step 5: Record parity evidence and review rollback.**

Update the milestone table with commands/results. Keep the Textual rollback command and known limitations explicit.

- [ ] **Step 6: Commit only the selector/parity milestone.**

Use a focused commit such as `test: verify rust and textual tui parity`. Ask before pushing if the destination branch or authorization remains unclear.

**Acceptance criteria:** Both clients consume the same governed backend contract; Rust can be selected without deleting Textual; parity cases pass; rollback remains one documented client-selection change.

**Milestone gate:** No client-specific path may bypass backend authorization or create a second execution lifecycle.

---

## Task 8: Final Verification, Security Review, and Release/Rollback Gate

**Files:**
- Modify: `docs/superpowers/plans/2026-11-24-rust-tui-migration.md` with final evidence and status only after verification.
- Modify: release/run documentation only if the selector or rollback command requires it.
- No deletion of Textual files in this migration phase.

**Interfaces:**
- Consumes: all completed milestones, focused tests, parity evidence, staged diff, and security review.
- Produces: a release recommendation or a documented blocker; never an implicit retirement of Textual.

- [ ] **Step 1: Run the complete Python suite.**

Run:

```text
python -m pytest -x --tb=short
```

Record the exact result. If failures are pre-existing, identify them and do not relabel them as migration success.

- [ ] **Step 2: Run the complete Rust checks.**

Run:

```text
cargo fmt --manifest-path clients/rust-tui/Cargo.toml -- --check
cargo test --manifest-path clients/rust-tui/Cargo.toml
```

- [ ] **Step 3: Run the required governance regression matrix.**

Verify the complete path for search results, file follow-up, approval, denial, cancellation, failures, reconnects, stale events, duplicate events, and out-of-order events. Confirm CAP approval/denial, signed permit integrity, immediate runtime validation, and tool authorization remain covered by tests.

- [ ] **Step 4: Perform security and data-hygiene review.**

Inspect:

```text
git diff --check
git status --short
git diff --stat
git diff --cached --name-only
git diff --cached --check
```

Review all staged paths for credentials, keys, `.env`, databases, permits, runtime state, generated private data, build artifacts, and unintended changes to `RULES.md`/pre-existing work. Confirm every Section 6 control is met:

1. Idempotency key on execution creation; reconnect never calls start.
2. Loopback-only binding; no client-supplied principal/authorization claims.
3. Explicit public DTOs — no raw `model_dump()`, no permit/secret/key leakage.
4. Monotonic per-execution sequences as SSE `id:`; cursor binds to execution+session; cursor-expired on stale history; no silent skip.
5. Approval transport is opaque — client sends `approval_id` + `decision` + bounded reason only.
6. Resource references are opaque server-issued IDs, backend-resolved and scope-bound.
7. Terminal output is sanitized — ANSI/OSC/control sequences stripped from untrusted content.
8. Version negotiation fails closed — unsupported major versions return structured errors.

Confirm the backend is still loopback-only and event payloads are redacted.

- [ ] **Step 5: Perform the rollback drill.**

Switch from Rust to Textual using the documented selector, reconnect to an active execution if supported by the runbook, and verify that Textual still presents the same backend state. Do not delete or rename the Textual path.

- [ ] **Step 6: Apply the release gate.**

Rust may be considered the preferred client only when all acceptance criteria in the design are met, all focused and full tests pass, approval/denial/cancellation and reconnect behavior are verified, packaging works, and rollback is documented. Otherwise mark M8 `Blocked` and keep Textual as the operational path.

- [ ] **Step 7: Commit verified release documentation/checkpoint.**

Create a focused final commit only after all verification passes and staged-file review is complete. The commit message must end with the required attribution. Do not push until branch, remote, and authorization are confirmed.

**Acceptance criteria:** The migration meets all six design acceptance criteria, existing core tests pass, no governance invariant changed, sensitive files are absent, and Textual remains a tested rollback path.

**Milestone gate:** A failed security review, missing parity evidence, unclear push authorization, or any required governance change blocks release and requires an explicit user decision.

---

## Stop/Ask Conditions

Stop implementation and report using “what was found / why it matters / available options / recommendation / exact decision needed” if any of the following occurs:

1. A change appears necessary to CAP, GAMBIT, signed permit creation/integrity, `enforce_cap_permit`, runtime authorization, or tool dispatch.
2. The existing implementation conflicts with the approved design or requires a breaking public API/persistent-data change.
3. Resource context cannot be implemented as a backend adapter without changing GAMBIT parsing or widening filesystem permissions.
4. SSE retention/reconnect semantics cannot guarantee the documented active-execution behavior without a persistence/schema decision.
5. Approval, denial, cancellation, or reconnect behavior differs between Textual and Rust in a way not explained by presentation alone.
6. A client would need credentials, a public bind address, destructive commands, direct provider/tool access, or locally trusted authorization state.
7. A test exposes an architectural problem or an unexplained pre-existing failure blocks milestone evidence.
8. Two reasonable protocol/resource designs materially change compatibility or scope.
9. The repository contains suspicious secrets, signing keys, private runtime state, local databases, or generated data that would be staged.
10. The GitHub remote, branch destination, or permission to push is unclear.

## Planned Commit Checkpoints

No commits or pushes are performed during this planning gate. After approval, use one focused commit per independently verified milestone, in this order:

1. `feat: define versioned execution protocol`
2. `feat: add reconnectable execution event streaming`
3. `feat: expose structured search and file events`
4. `feat: add backend resource context for file followups`
5. `feat: render structured execution events in textual tui`
6. `feat: add rust tui protocol client`
7. `test: verify rust and textual tui parity`
8. final verification/documentation checkpoint, only if needed

Every commit must be reviewed before staging, must exclude secrets/runtime state, and must end with:

```text
Co-Authored-By: Claude Code <noreply@anthropic.com>
```

## Self-Review

**Spec coverage:** The plan covers the approved design’s protocol boundary, typed/versioned events, HTTP/SSE, sequence numbers, cursor replay, stale/duplicate/out-of-order handling, structured search/source events, backend-owned file context, deterministic and ambiguous “that file” behavior, Rust `ratatui`/`crossterm` milestones, Textual compatibility, governance invariants, end-to-end regressions, acceptance criteria, verification, rollback, and Git checkpoints.

**Step scan:** Each task has ordered failing-test, implementation, verification, diff/secret-review, and commit steps. Exact signatures and event fields are defined where later tasks depend on them; implementation bodies remain intentionally unprescribed.

**Type consistency:** Python protocol events are the source contract; SSE IDs are integer sequences; `after` is exclusive; Rust state consumes the same fields and uses the same execution/session identity. Approval and cancellation remain request actions, not events fabricated by clients.

**Review-focus coverage:** Search visibility is pinned in Task 3/5; file ambiguity in Task 4; approval substitution in Tasks 2/5/6; reconnect ordering in Tasks 2/6/7; sensitive metadata leakage in Tasks 1/2/3/8.

**Proportion:** The plan is detailed because the migration spans backend protocol, lifecycle state, two clients, governance-sensitive tests, and rollback. It avoids prescribing CAP/GAMBIT/runtime rewrites and keeps implementation work in independently reviewable milestones.
