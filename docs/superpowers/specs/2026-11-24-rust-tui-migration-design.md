# Rust TUI Migration Design

**Date:** 2026-11-24  
**Status:** Approved for planning — implementation not yet approved  
**Security review:** Completed (2026-11-24). All HIGH and MEDIUM findings from `security-review-report.md` are incorporated below as mandatory controls before implementation.

## Intent

Replace the tightly coupled Python/Textual terminal UI with a Rust terminal client through an incremental migration. Improve search-result visibility, file-operation continuity, approval UX, event observability, and UI resilience without weakening Samaktha's governance architecture.

## Goals

- Build a Rust TUI using `ratatui` and `crossterm`.
- Keep CAP, GAMBIT, the ExecutionCoordinator, signed permits, runtime validation, persistence, providers, and existing tools authoritative.
- Define a typed, versioned backend protocol for requests, execution lifecycle, approvals, tool events, search results, file events, errors, and final results.
- Preserve the current Python/Textual TUI as a fallback until behavioral parity is proven.
- Fix the two confirmed interaction gaps: search results not reaching normal TUI output and follow-up file references lacking reliable resource context.
- Add end-to-end regression coverage before replacing the current UI.

## Non-goals

- Rewriting CAP or GAMBIT in Rust.
- Allowing the Rust client to execute tools directly.
- Replacing all Python tools in the first migration.
- Making the backend public or multi-tenant.
- Introducing remote authentication or external deployment as part of this migration.
- Removing the Textual TUI before parity and rollback criteria are met.

## Anti-goals

- No UI shortcut may approve, forge, alter, or bypass a permit.
- No client-provided path, tool, capability, or approval claim is trusted without backend validation.
- No migration step should silently discard structured tool results.
- No commit or push may contain signing keys, credentials, runtime state, or local databases.
- No broad refactor is combined with an unrelated feature change.

## Current architecture constraints

The backend remains the authority:

```text
Rust TUI → localhost HTTP/SSE protocol → ExecutionCoordinator
                                      → GAMBIT
                                      → CAP
                                      → signed permit
                                      → Runtime validation
                                      → tools/providers/persistence
```

The Rust TUI is a presentation and client-state layer. CAP remains authoritative for policy and approval. GAMBIT remains authoritative for goal parsing and planning. Runtime permit validation remains mandatory immediately before effects.

## Approaches considered

### A — Incremental migration (selected)

Define the protocol, improve backend event/resource contracts, build the Rust TUI alongside Textual, run both during migration, then retire Textual after parity. This minimizes operational risk and preserves working capabilities.

### B — Rust TUI against the current backend first

This gives faster visible progress but carries current event and resource-context defects into the new client and creates avoidable rework.

### C — Full rewrite

This would replace UI, tool boundaries, and orchestration together. It has the highest risk of regressions and accidental governance bypass, so it is rejected.

## Proposed design

### 1. Protocol boundary

Add a local, versioned API/event contract. Prefer the existing HTTP execution surface and SSE for live events before considering WebSockets. The contract must model at least:

- execution accepted/started/completed/failed/cancelled
- approval required/approved/denied/expired
- tool started/progress/completed/failed
- search started/results/sources
- file created/written/read/failed
- assistant tokens/messages
- structured errors and reconnect state

Every event carries an execution ID, session ID, sequence number, timestamp, and protocol version. Backend authorization is repeated for every state-changing request.

### 2. Resource context

Track structured session resources, initially including the last created/opened file and active workspace. Resolve references such as “that file” only when the backend can identify a unique resource; otherwise request clarification. Explicit paths override inferred context. Resource context must not expand filesystem permissions.

### 3. Rust client

Create a separate Rust workspace/application for the TUI. It consumes only the protocol, maintains a typed state machine, renders conversation/activity/approval/search/file views, handles reconnects, and reports backend errors clearly. It does not import or reimplement CAP, GAMBIT, or tool execution logic.

### 4. Compatibility period

Keep the Textual TUI available. Both clients use the same backend contract. Use feature flags or an explicit CLI selector to choose the client. Remove the old TUI only after acceptance tests, manual approval flows, reconnect behavior, packaging, and rollback are verified.

### 5. Verification

Before each milestone is marked complete:

- Add or update focused tests first for changed behavior.
- Run relevant unit and integration tests.
- Run protocol/schema validation.
- Verify CAP approval, denial, cancellation, and permit enforcement.
- Verify no sensitive files are staged.
- Record the milestone status and evidence in the plan.

## 6. Security Controls (mandatory before implementation)

The following controls are release-blocking. None may be weakened by the Rust client, the protocol, or any backend change made during migration.

### 6.1 Idempotency and replay integrity

- Execution creation and event subscription are separate protocol operations.
- `POST /executions` accepts exactly one client-supplied idempotency key scoped to the local principal. The same key must return the same `execution_id` and must not start a second execution.
- Reconnect uses `GET /executions/{execution_id}/events` (or an SSE equivalent) with a sequence cursor; it never re-posts the execution-start operation.
- Retrying after a dropped stream asserts one execution ID and one side effect per idempotency key.

### 6.2 Loopback-only binding as a hard trust boundary

- The backend binds only to loopback by default. A non-loopback bind is rejected or explicitly gated behind an architecture review.
- The Rust client enforces nothing about identity — the backend derives every principal at the boundary.
- No client-supplied `principal_id`, `user_id`, or authorization claim is accepted in the protocol.
- Remote access, browser clients, multiple OS users, or service-account deployment are out of scope unless an explicit architecture review defines authentication, principal derivation, session ownership, CSRF/origin policy, and secure transport.

### 6.3 Explicit public DTOs — no raw serialization

- Protocol events and results use explicit allowlisted DTOs, never `model_dump()` of internal Python objects, exceptions, permits, checkpoints, signing material, or arbitrary `RuntimeResult.metadata`.
- Public DTOs exclude or redact: permit bodies, integrity digests, secrets, credentials, API keys, raw prompts, raw file content, and secret-bearing tool arguments.
- Approval responses never contain permit material. Provider tokens are delivered only through the intended display channel.

### 6.4 Monotonic sequences, SSE identity, and cursor binding

- Every event carries a backend-assigned, monotonic, per-execution sequence number starting at 1.
- The sequence is emitted as the SSE `id:` field and in the typed event envelope.
- Cursors bind to execution + session/principal. A cursor for another execution or principal is rejected.
- `after=N` is exclusive (`sequence > N`). `Last-Event-ID` must agree with `after` when both are present.
- A cursor predating retained history returns a structured cursor-expired response with safe bounds — no silent skipping.
- On a sequence gap, send an explicit resynchronization signal; never synthesize state from an incomplete stream.

### 6.5 Approval transport — opaque backend operation

- The client sends only: opaque `approval_id`, a bounded `decision` enum, and bounded reason text.
- The client never sends permits, capabilities, targets, tools, paths, subjects, permissions, operation digests, workspaces, or "approved" state.
- A UI `allow` flag is only a request to resolve the current backend approval; it is not authorization.
- Decisions route through the existing coordinator/CAP path; the signed permit is resolved and runtime validation remains immediately before effect execution.
- Unknown protocol fields are rejected (`extra=forbid`).

### 6.6 Resource references — backend-resolved and scope-bound

- The backend issues opaque resource IDs resolved to canonical resource records bound to principal, session, and workspace.
- The Rust TUI never converts a user-visible path or resource label into an executable path.
- Existence, uniqueness, workspace scope, and operation type are rechecked at the backend boundary.
- Resource context never expands filesystem or tool permissions.

### 6.7 Terminal rendering — untrusted content is inert

- All protocol content (search titles/snippets, provider tokens, tool errors, filenames, paths) is treated as plain data.
- C0 controls, ESC/CSI/OSC sequences, invalid UTF-8, and terminal formatting are stripped before rendering.
- ratatui text spans are used; payloads are never interpreted as markup, shell input, or client-side evaluation.

### 6.8 Version negotiation — fail closed

- Protocol major version is negotiated before execution. Unsupported major versions return a structured `PROTOCOL_VERSION_UNSUPPORTED` error — never silent downgrade.
- Unknown security-relevant fields are rejected, not silently dropped.
- Rollback reconnects to the same backend execution ID, obtains authoritative state, and never locally recreates approval or resends the original request.
- Resume/cancel uses explicit execution IDs, not client-local session-to-execution guesses.

## Acceptance criteria

The migration is successful when:

1. Normal TUI mode displays structured search results and sources as well as synthesis.
2. Creating a file followed by “write inside that file” targets the uniquely identified file or asks for clarification.
3. Approval and denial remain backend-enforced and auditable; no client can forge, modify, replay, or locally substitute approval or permit state.
4. The Rust TUI can reconnect to a running local backend without losing execution identity; reconnect never re-executes a governed operation.
5. Existing core tests remain passing and new end-to-end tests cover the reported regressions plus all security controls in Section 6 (idempotency, loopback binding, DTO redaction, SSE sequence/cursor binding, opaque approvals, opaque resource IDs, terminal sanitization, fail-closed version negotiation).
6. The Textual TUI remains a documented rollback path until Rust parity is demonstrated.
7. No staged or committed file contains credentials, API keys, signing keys, `.env`, local databases, permit material, runtime state, or generated private data.

## Open decisions for implementation planning

- Exact protocol schema location and serialization format.
- Whether SSE is sufficient for all event volume or a later WebSocket phase is needed.
- Rust workspace layout and packaging integration.
- Exact parity checklist for retiring Textual.
- GitHub branch and remote policy for milestone pushes.
