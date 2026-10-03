# Samaktha Harness Integration Blueprint

**Status:** architecture study and implementation blueprint; no runtime implementation is included in this change.

**Evidence boundary.** This document is based on the current checkout of Samaktha and shallow source checkouts of `xai-org/grok-build` and `openai/codex` inspected on 2026-10-03. Upstream paths are repository-relative and should be re-verified against a pinned commit before implementation. The external repositories are Apache-2.0; this document recommends reimplementation of patterns, not transplantation of source.

## Executive Summary

Grok Build and Codex both model a coding task as a durable session containing typed turns, tool calls, streamed events, policy decisions, and persisted state. Grok Build is especially useful for tool-context design, workflow journaling, background-task ownership, skill/MCP discovery, and local workspace/session persistence. Codex is especially useful for explicit thread/turn/item protocol, interrupt/resume, approval and sandbox policy separation, app-server boundaries, structured event reduction, and testable lifecycle protocols.

Neither should replace Samaktha. Samaktha already has the stronger governing boundary: `CAP` makes deterministic policy decisions, `GAMBIT` owns planning, `Runtime` owns execution, and memory is explicitly scoped. The recommended design is to add a typed observation and adaptive loop around those boundaries:

```text
USER -> CAP -> GAMBIT -> AgentLoop -> CAP -> Runtime -> Tool
     <- final response <- StateUpdate <- Observer <- execution evidence
                                      -> GAMBIT replan
```

The first implementation should be a no-breaking one-step cycle: preserve the existing orchestrator and tools, add typed state/observation adapters, execute one governed action, persist the observation, and let GAMBIT decide whether to continue. Subagents, broad web changes, and runtime replacement are explicitly deferred.

## Why We Studied Grok Build and Codex

Samaktha’s previous failure modes are state-boundary failures: generated prose was treated as execution truth, search results were confused with conclusions, and an artifact’s identity was not always preserved across follow-up turns. These harnesses expose useful counter-patterns: IDs for threads/turns/tool calls, typed protocol items, explicit tool results and errors, durable journals/checkpoints, cancellation signals, and policy decisions separated from execution.

## Grok Build Architecture

### Repository and source map

Repository: `https://github.com/xai-org/grok-build` (Apache-2.0).

| Concern | Exact implementation reference | Observed responsibility |
|---|---|---|
| Agent construction and prompt/tool definition lifecycle | `crates/codegen/xai-grok-agent/src/agent.rs`, `builder.rs`, `config.rs` | `Agent`, `AgentBuilder`, `AgentDefinition`; assemble model-facing prompt and tool definitions. |
| Tool bridge and shared execution context | `crates/codegen/xai-grok-tools/src/bridge.rs`, `registry/types.rs`, `types/tool_metadata.rs` | Resolves tools, calls them, carries `ToolCallContext`, shared resources, origin and working directory. |
| Tool protocol/runtime | `crates/common/xai-tool-runtime`, `crates/common/xai-tool-types` | Typed definitions, call context, streaming/error conversion, dynamic tool execution. |
| Workflow/task execution | `crates/codegen/xai-workflow/src/engine.rs`, `host.rs`, `journal.rs`, `validate.rs` | Host options/results, workflow execution and journal validation. This is a workflow engine, not evidence that Grok has a GAMBIT-equivalent planner. |
| Session and turn lifecycle | `crates/codegen/xai-agent-lifecycle/src/send/contributors/turn_lifecycle.rs`, `turn_input.rs`, `session_lifecycle.rs` | Typed turn start/done/abort/error and input fragments; contributor registry emits lifecycle events. |
| Chat state and compaction | `crates/codegen/xai-chat-state/src/handle.rs`, `types.rs`, `compaction_utils.rs`, `usage.rs` | Actor/handle-mediated conversation state, compaction context, usage accounting and running-subagent summaries. |
| Persistence | `crates/codegen/xai-grok-tools/src/persistence.rs`, `registry/types.rs` | Snapshot save/flush and state restoration hooks. |
| Web search | `crates/codegen/xai-grok-tools/src/implementations/web_search/client.rs`, `implementations/grok_build/web_search/mod.rs` | Search call and tool-facing result; provenance must be carried by the caller/model, not treated as a conclusion. |
| Files and shell | `crates/codegen/xai-grok-tools/src/implementations/grok_build_hashline`, `implementations/opencode`, `computer/local`, `util/read_policy.rs`, `util/fs.rs` | Read/edit/search/bash, path policy and local process/workspace handling. |
| MCP | `crates/codegen/xai-grok-mcp`, `xai-grok-tools/src/implementations/use_tool/mod.rs` | MCP dispatch, target validation and use-tool adaptation. |
| Subagents | `crates/codegen/xai-grok-subagent-resolution`, `xai-chat-state/src/usage.rs`, `xai-grok-tools/src/registry/types.rs` | Resolution, child usage accounting, context/resource inheritance and task ownership. |
| Sandbox/egress/security | `crates/codegen/xai-grok-sandbox`, `xai-grok-egress-proxy`, `xai-grok-permission-rules`, `xai-grok-secrets` | Process/filesystem/network restrictions, permission rules, secret handling. |
| Cancellation/background work | `xai-grok-tools/src/bridge.rs` (`kill_*`, `background_*`), `computer/types.rs` (`TaskKind`, `TaskSnapshot`) | Owner-scoped process/task lifecycle and kill/reparent operations. |
| Memory/skills/hooks | `xai-grok-memory`, `xai-grok-hooks`, `xai-grok-agent/src/prompt/skills.rs`, `prompt/agents_md.rs` | Session/project memory, hook trust, skills and repository instructions. |

### Actual flow

The implementation flow is: a host builds an `Agent`; the agent finalizes prompt and definitions; a model response is parsed into tool calls; the bridge resolves the tool and constructs `ToolCallContext`; registry dispatch runs the tool and returns typed output/error/notifications; shared resources and persistence are updated; the lifecycle layer emits turn events; the next model input is rendered from chat state and tool observations. Grok’s strongest architectural lesson is not a single planner class: it is the correlation of every call with a context, owner, resource set, lifecycle event, and persistence boundary.

### Limits of the evidence

The current source contains workflow/task constructs and dynamic tools, but no externally verified claim should be made that Grok’s workflow engine is an adaptive goal planner equivalent to GAMBIT. Treat plan mutation and replan behavior as an integration opportunity, not as a copied Grok feature.

## Codex Architecture

### Repository and source map

Repository: `https://github.com/openai/codex` (Apache-2.0). The relevant implementation is primarily Rust under `codex-rs/`; `codex-cli/` is the packaging/launcher surface.

| Concern | Exact implementation reference | Observed responsibility |
|---|---|---|
| Core agent/task execution | `codex-rs/core/src`, especially `codex-rs/core/src/task` and `codex-rs/core/src/agent` where present in the pinned checkout | Model interaction, turn execution, tool calls and state transitions. Names vary across current modules; pin and re-verify before coding. |
| Thread/turn protocol | `codex-rs/app-server-protocol/src`, `codex-rs/app-server/src/request_processors/turn_processor.rs`, `thread_processor.rs` | Typed thread, turn and item requests/responses; admission, execution and completion notifications. |
| App-server boundary | `codex-rs/app-server/src/lib.rs`, `message_processor.rs`, `request_processors`, `app-server/README.md` | JSON-RPC-like client/server boundary, typed requests, notifications, pagination, resume and interrupt APIs. |
| Tool execution | `codex-rs/exec`, `exec-server`, `tools`, `apply-patch`, `file-system`, `shell-command` | Command/file/patch tools, execution servers, tool protocol and output handling. |
| Approval/policy | `codex-rs/execpolicy`, `codex-rs/core`, app-server resolved configuration types | Approval policy is resolved before execution; approval requests are distinct from tool results. |
| Sandboxing | `codex-rs/sandboxing`, `linux-sandbox`, `mxc-sandbox`, `windows-sandbox-rs`, `process-hardening`, `network-proxy` | OS-specific execution isolation, network/process controls and Windows support. |
| Persistence/resume/history | `codex-rs/thread-store`, `history`, `rollout`, `state`, `message-history` | Durable thread history, rollout records, state snapshots and resume/revert/inject operations. |
| Interrupt/cancellation | `codex-rs/app-server/tests/suite/v2/turn_interrupt.rs`, `request_processors/turn_processor.rs` | Typed turn interruption and completion/error state rather than a best-effort text instruction. |
| MCP/dynamic tools | `codex-rs/codex-mcp`, `app-server/src/dynamic_tools.rs`, app-server MCP tests | Discovery, registration and invocation through protocol-level tool items. |
| Subagents/collaboration | `codex-rs/agent-roles`, `agent-message-board-client`, `core-plugins`, `collaboration-mode-templates` | Role/context separation and parent/child or collaborative execution surfaces. |
| Observability | `codex-rs/analytics`, `otel`, `rollout-trace`, app-server notifications | Event/fact reduction, traces and lifecycle telemetry distinct from user-visible assistant text. |

### Actual flow

The client opens or resumes a thread, starts a typed turn, and supplies resolved model, sandbox, approval and environment settings. The turn processor admits the request, invokes the core agent loop, emits typed assistant/tool/approval/status items, routes tool calls through exec/MCP/file subsystems, and finishes with a typed completion or error notification. A later `turn/start` or resume operation reads durable thread state, not just the last assistant paragraph. The app-server tests are particularly valuable because they encode expected lifecycle behavior for interruption, resume, dynamic tools, MCP, and failures.

### Codex-specific caution

Codex is a Rust-native coding agent with OS-level sandboxing and a broad product protocol. Its policies are not a replacement for CAP, and its Rust process model is not a reason to add a Rust dependency to Samaktha. Reproduce the protocol ideas in Python/Pydantic and retain CAP as the governing authority.

## Agent Loop Comparison

| Phase | Grok Build | Codex | Samaktha decision |
|---|---|---|---|
| Understand | Agent prompt/context rendering and chat state | Thread history plus typed turn input | Keep `ContextEngine`; produce a typed `AgentState` view. |
| Plan | Workflow/task facilities and model-produced tool sequence; no proven GAMBIT equivalent | Core turn loop and task/turn protocol; plan is represented through items/state rather than a Samaktha-style planner | GAMBIT remains planner; borrow explicit step IDs and mutable status. |
| Govern | Tool/permission/sandbox layers | Approval policy, exec policy and sandbox resolution before execution | CAP must be the final deterministic gate. |
| Act | `ToolBridge`/registry dispatch | exec, file, patch, MCP and dynamic tool services | Runtime dispatch remains Samaktha-owned. |
| Observe | Typed tool notifications/results and lifecycle events | Typed tool/approval/status items and completion events | Add first-class `Observation` and `StateTransition`. |
| Continue | More model input after tool output; persistence/compaction | Turn continues until completion, interruption or failure | `Replanner` decides continuation; no implicit loop on prose. |
| Recover | Persistence, task ownership, retries and kill/reparent APIs | resume/revert/interrupt plus durable rollout/history | Wire to existing checkpoints and recovery policies. |

## Observation Comparison

Both systems separate tool execution results from ordinary assistant text through typed call IDs and lifecycle events. Grok uses `ToolCallContext`, notifications, shared resources and persistence. Codex exposes typed protocol items, approval requests, tool results, status and completion notifications. Neither gives Samaktha permission to infer filesystem success from an LLM sentence. Samaktha should make observation deterministic at the Runtime boundary and model-assisted only for interpretation or next-step suggestions.

## State Model Comparison

Grok has `SessionContext`, lifecycle inputs, chat-state handles, usage ledgers, task snapshots and persistent snapshots. Codex has thread/turn/item identities, resolved per-turn configuration, durable history/rollout and typed app-server state. The shared pattern is identity plus lifecycle, not a monolithic conversation string. Samaktha should retain separate `ConversationState`, `WorkflowState`, `RuntimeResult`, `MemoryResult`, `ArtifactRecord`, `WebEvidence` and `AssistantResponse` types.

## Memory Comparison

Grok’s `xai-grok-memory` and skill/prompt mechanisms provide project/session continuity and discovery. Codex’s `memories`, `history`, `thread-store` and compaction paths provide scoped durable context and resume-oriented state. These systems demonstrate useful scoping and compaction, but do not establish that their persistence policies match Samaktha’s privacy model. Samaktha’s governed memory contracts in `app/core/contracts/memory.py`, controller, repository and session stores remain authoritative; adopt only typed references, scope checks, evidence and compaction metadata.

## Web Comparison

Grok has explicit search implementation and web-search tool modules. Codex has web/search-related tools and source/event plumbing in the broader tools and app-server surfaces, but the coding-agent core is not a research citation system. Neither should be represented as a complete evidence graph. Samaktha already has provider/cache/ranker/verifier seams under `app/search` where present and tests under `tests/phase12`; preserve the distinction `SearchResult -> SourceDocument -> RetrievedContent -> Evidence -> Conclusion`.

## Artifact/File Comparison

Grok’s tool implementations include read/edit/hashline/search-replace, path policy, file readers and call IDs; Codex has file-system, apply-patch, history/rollout and workspace components. Both make tool calls and workspace paths first-class. Samaktha’s `FileSystemTool`, `ToolSecurityEnforcer`, file parsers and `app/conversation/reference_resolver.py` are the correct integration points. Add stable artifact identity and verification records; do not use a displayed path as the artifact’s sole identity.

## Tool System Comparison

Grok’s registry/bridge separates definition discovery, call context, cancellation, notifications, resource access and dispatch. Codex separates tool protocol from exec servers, policy, sandbox and app-server notifications. Samaktha should wire the same separations through `app/tools/registry.py`, `app/tools/models.py`, `app/core/contracts/tools.py`, `app/runtime/dispatcher.py`, `app/runtime/engine.py`, and CAP security checks. Tool schemas must be validated before execution; outputs must be bounded, serializable, correlated, and marked as evidence or failure.

## Security/Sandbox Comparison

Grok provides sandbox, egress proxy, permission rules, secrets and path policies. Codex provides execpolicy, process hardening, network proxy, Linux/macOS/Windows sandbox implementations and explicit approval policy. These are stronger execution-control references than a generic prompt guard, but neither replaces Samaktha’s CAP + permit/signing model. Adopt deny-by-default validation, owner-scoped cancellation, bounded output, network/path normalization, secret redaction and platform-specific adapters. Keep policy authority in `app/core/cap`, `app/governance`, and `app/tools/security.py`.

## Subagent Comparison

Grok tracks child task ownership, shared resources, running snapshots and usage folding. Codex has roles, child/collaboration surfaces, message boards and child-turn analytics. Useful Samaktha design: a child gets an explicit `parent_task_id`, scoped `session_id`, capability subset, budget/deadline, cancellation token, result envelope and evidence references. Do not add unrestricted parallel agents until CAP propagation and checkpoint aggregation are tested.

## Recovery Comparison

Grok persists snapshots and has task kill/reparent/flush operations. Codex has durable history/rollout, resume/revert, turn interruption and daemon recovery tests. Samaktha already has `app/runtime/checkpoint.py`, `app/runtime/recovery.py` where present, workflow pause/state, and recovery tests. Wire observations and permit identity into existing checkpoints; do not create a second persistence authority.

## Samaktha Current Architecture

The production composition root is `app/core/app.py:create_orchestrator()`. The current path is `Interface -> ExecutionCoordinator -> SamakthaOrchestrator -> CAP approval/signed permit -> GAMBIT -> WorkflowEngine -> Router -> RuntimeEngine -> ProviderExecutor or ToolExecutor -> evidence/checkpoints/memory`. Relevant existing surfaces are:

| Boundary | Current files |
|---|---|
| Coordination/orchestration | `app/core/execution_coordinator.py`, `app/core/orchestrator/engine.py`, `app/core/orchestrator/pipeline.py`, `app/core/app.py` |
| CAP/governance | `app/core/cap/context_engine.py`, `policy_engine.py`, `approval_engine.py`, `permission_store.py`, `ambiguity_resolver.py`; `app/governance/*` |
| GAMBIT/planning | `app/core/gambit/agent_planner.py`, `planner.py`, `plan_builder.py`, `task_decomposer.py`, `goal_parser.py`, `agents.py` |
| Runtime | `app/runtime/base.py`, `engine.py`, `dispatcher.py`, `registry.py`, `checkpoint.py`, `recovery.py` |
| Contracts | `app/core/contracts/planning.py`, `runtime.py`, `tools.py`, `state.py`, `memory.py`, `policy.py`, `trace.py` |
| Tools/security | `app/tools/registry.py`, `manager.py`, `models.py`, `filesystem.py`, `shell.py`, `security.py`, `resolver.py` |
| Memory/session | `app/memory/controller/*`, `repository.py`, `session_manager.py`, `session_store.py`, `models.py`, `app/core/contracts/memory.py` |
| Conversation/artifacts | `app/conversation/models.py`, `conversation_state.py`, `state_manager.py`, `reference_resolver.py`, `app/fileparsers/*` |
| Web | `app/search/*` and `tests/phase12/*` if present; verify exact checkout before implementation |
| UI/streaming/events | `app/tui/*`, `app/core/events.py`, `app/core/contracts/streaming.py`, `app/voice/*` |

## Capability Gap Analysis

| Capability | Samaktha current implementation | Grok pattern | Codex pattern | Recommended Samaktha approach |
|---|---|---|---|---|
| Agent loop | Orchestrator/workflow path; no single typed observe-replan controller | Agent + lifecycle + bridge | Core turn processor + typed protocol | ADAPT into `AgentLoop` around existing orchestration. |
| Observation | Runtime results/evidence exist but are not one uniform loop contract | Tool notifications/context | Typed items/status/completion | ADOPT a normalized observation envelope. |
| Replanning | GAMBIT planner/decomposer | Workflow/task facilities | Turn continuation/state | WIRE observations into GAMBIT; retain planner authority. |
| State | Multiple strong contracts and stores | Context, snapshots, usage | Thread/turn/item state | ADAPT with explicit ownership and IDs. |
| Sessions/tasks/turns | Session/workflow models | Session lifecycle | Thread/turn/item protocol | ADAPT IDs and lifecycle statuses. |
| Memory | Governed, scoped controller/repository | Project/session memory | History/compaction/resume | WIRE typed memory references; do not replace. |
| Web | Existing search providers/cache/ranker/verifier | Search tool | Tool/event plumbing | WIRE provenance-rich web state. |
| Files/artifacts | FileSystemTool and reference resolver | Path policy/read/edit | File/patch/history | ADOPT stable artifact records; keep tool. |
| Tools/MCP | Registry/contracts/plugins; MCP seam requires verification | Bridge/registry/MCP | Dynamic tools/MCP protocol | ADAPT typed call context and lifecycle. |
| Security/sandbox | CAP, permits, ToolSecurityEnforcer, Windows behavior | Sandbox/egress/path rules | execpolicy/OS sandbox | WIRE hardening; CAP remains authority. |
| Approvals | CAP approval and signed permits | Permission rules | Approval policy/request items | WIRE explicit approval outcome into observation. |
| Recovery | Checkpoints/recovery/reconciliation | Snapshot/flush/kill | Resume/revert/interrupt | WIRE observation/permit/checkpoint identity. |
| Subagents | Existing worker/multi-agent tests and contracts | Child task/resource ownership | Roles/message board/child turns | STUDY ONLY until parent governance is complete. |
| Streaming/cancellation | Streaming contracts, runtime events, voice/UI | Notifications, kill owner | App-server notifications/interrupt | ADAPT correlated lifecycle events. |
| Provider abstraction/router | Existing router/provider contracts | Model/tool bridge | Model-provider/config resolution | KEEP and WIRE loop calls through Router. |
| TUI/logging/telemetry | Existing TUI, event bus, telemetry | Ratatui/events/tracing | app-server/analytics/OTel/rollout | WIRE state transitions to existing surfaces. |

## Patterns to ADOPT

1. **Typed correlation identities.** Every task, turn, step, action, tool call, observation, approval, artifact, and checkpoint gets an ID and parent relationship. Evidence: Grok `ToolCallContext`/`SessionContext`; Codex typed thread/turn/item protocol. Test: replay a multi-step artifact task and prove each observation points to exactly one action.
2. **Explicit tool result versus assistant response.** Runtime returns a structured result; the response formatter may summarize it but cannot mutate execution truth. Evidence: both harnesses emit tool/lifecycle items separately. Test: generated “file created” text without a filesystem write must remain failure/unverified.
3. **Owner-scoped cancellation and bounded outputs.** Borrow Grok owner IDs/kill operations and Codex interrupt semantics. Test cancellation of foreground, background, and nested calls.
4. **Durable lifecycle events.** Persist state transitions and checkpoint references, not raw model prose. Evidence: Grok persistence/journal and Codex history/rollout. Test interruption after tool side effect and resume without duplicate execution.
5. **Approval as a typed state transition.** An approval request, denial, approval permit, and execution result are different records. CAP remains the decider.

## Patterns to ADAPT

* Grok’s `ToolCallContext` becomes a Python `RuntimeContext` extension containing principal, session/task/step IDs, workspace identity, permit ID, cancellation token, deadline, capability scope, redaction policy, and trace ID.
* Codex’s thread/turn/item vocabulary becomes Samaktha `Session -> Task -> Turn -> Step -> Action -> Observation`, using Pydantic models in existing contract modules rather than a new protocol server.
* Grok’s shared resources become explicit runtime dependencies passed through `RuntimeContext`, never ambient unrestricted globals.
* Codex’s app-server request/notification separation becomes internal interfaces: command/request methods return typed values; event bus publishes lifecycle notifications.
* Compaction becomes governed context reduction: retain IDs, unfinished actions, failures, artifact references, evidence citations, and permits while dropping redundant prose.

## Patterns to WIRE

Keep and connect existing `CAP`, `GAMBIT`, `ContextEngine`, `RuntimeEngine`, `FileSystemTool`, provider/router, memory controller, checkpoint store, event bus, TUI, and telemetry. Wire them through the new observation adapter and loop controller. No external runtime becomes a dependency.

## Components to REPLACE

**None justified by this study.** The evidence supports additive integration. A future replacement would require a measured defect, a migration adapter, and parity tests; repository size or feature count is not sufficient.

## Components to STUDY ONLY

Grok’s full Rust sandbox/egress architecture, Grok’s skill marketplace and cloud workspace daemon, Codex’s OS-level sandbox services, collaborative subagents, app-server transport, and external agent protocol integrations. They are valuable references but premature for the first Samaktha loop.

## Patterns to REJECT

Reject wrapper architecture, wholesale Rust/Rust-toolchain adoption, model-controlled governance, treating shell output or assistant prose as truth, unscoped ambient memory, automatic provider fallback that hides failure, unrestricted subagent inheritance, and replacing Windows-native controls with assumptions based on Linux/macOS sandbox behavior.

## Samaktha Agent Loop Design

Implement an adapter around existing names:

```python
class AgentLoop:
    async def run(self, state: AgentState) -> LoopResult: ...
```

`AgentState` owns goal, session/task/turn IDs, current plan, pending/completed steps, last observation, failures, artifacts, web evidence, memory references, budgets, cancellation and termination status. GAMBIT proposes a `Plan`; the loop selects one `Action`; CAP evaluates it; Runtime executes it; `Observer` converts the deterministic result into an `Observation`; `StateTransition` updates state; `Replanner` asks GAMBIT for continue/retry/alternate/recover/ask/finish.

`Step` is a planned unit with status and dependency IDs. `Action` is an executable intent with capability and typed arguments. `Observation` is the only input used to claim execution happened. `TerminationPolicy` checks goal satisfaction, denied governance, budget/deadline, cancellation, unrecoverable failure and user escalation. `RecoveryPolicy` classifies retryable provider/tool failures, stale checkpoints, partial side effects and permission denials.

## Observer Design

Proposed contract, implemented with existing Pydantic conventions:

```python
class Observation(BaseModel):
    observation_id: str
    task_id: str
    turn_id: str
    step_id: str
    action_id: str
    intent: IntentRecord
    planned_action: Action
    executed_action: ExecutedAction | None
    status: Literal["succeeded", "failed", "denied", "cancelled", "partial", "unverified"]
    tool_result: ToolResult | None
    failure: FailureRecord | None
    verification: VerificationRecord
    side_effects: list[SideEffect]
    new_state: StateDelta
    next_step_hint: NextStepHint | None
    evidence_refs: list[str]
    created_at: datetime
```

Deterministic components: IDs, permit matching, tool status, exit code, bytes/path evidence, artifact hash/metadata, timeout/cancellation, schema validation, and policy outcome. Model-assisted components: classify human-readable failure, suggest an alternative, summarize evidence, or identify missing information. The model cannot mark `succeeded`, create evidence, bypass CAP, or write memory directly.

## State Model

Keep distinct stores/records: `ConversationMessage`, `AssistantResponse`, `Plan`, `Action`, `ToolResult`, `Observation`, `ArtifactRecord`, `WebResearchState`, `MemoryReference`, `Checkpoint`, and `StateTransition`. Every record carries scope and provenance. A state transition is append-only in the audit stream and applies a validated delta to the current snapshot. The snapshot is reconstructable from transitions plus checkpoint metadata.

## Replanning Design

* **Success:** mark the step complete, verify side effects, advance dependencies, and ask GAMBIT whether the goal is now satisfied.
* **Failure:** classify deterministic failure; apply bounded retry only when policy says retryable; otherwise select alternate capability, recovery action, or user escalation.
* **New information:** append evidence, invalidate affected assumptions, and replan dependent steps.
* **Missing information:** plan a governed acquisition action; do not invent it.
* **Ambiguity:** use `ambiguity_resolver` and scoped context; ask when confidence or authorization is insufficient.
* **Goal achieved:** require deterministic verification where possible, then terminate with an evidence-backed result.
* **Governance denied:** persist denial and stop/escalate; never retry by changing arguments to evade CAP.

## Artifact State

Extend existing artifact/reference models with `artifact_id`, `workspace_id`, canonical path, display filename, media/type/format, creation and modification turn IDs, content/version hash where safe, verification status, source/evidence references, parent artifact ID, and lifecycle status (`created`, `modified`, `renamed`, `converted`, `missing`, `unverified`). A rename changes the current locator but not identity; an edit creates a version/transition; a read resolves identity through the registry before opening a path. Runtime evidence, not response text, changes verification status.

## Web Research State

Use separate records for query, result, source, fetch, evidence and conclusion:

```text
WebResearchState(query, provider, requested_at, results[])
SearchResult(result_id, url, title, snippet, rank, retrieved_at)
SourceDocument(source_id, canonical_url, fetched_at, status, content_ref, freshness)
Evidence(evidence_id, source_id, quote_or_span_ref, claim, confidence)
Conclusion(conclusion_id, evidence_refs, generated_at, model, text)
```

Search results are not fetched documents; fetched documents are not conclusions; conclusions cannot be persisted as memory without governed evidence and scope.

## Migration Strategy

### Stage A — no-breaking integration

Files: add contract models beside `app/core/contracts/state.py`, `runtime.py`, `tools.py`; add an observer adapter beside `app/runtime`; modify only composition wiring in `app/core/orchestrator/pipeline.py`. Dependencies: none. Tests: synthetic tool result to observation. Rollback: disable adapter flag and retain current pipeline. Risk: duplicate event emission.

### Stage B — observation/state abstractions

Files: `app/core/contracts/state.py`, `runtime.py`, `trace.py`, `app/runtime/engine.py`, `app/core/events.py`. Add typed IDs, `Observation`, `StateTransition`, and deterministic verification. Tests: success/failure/denial/unverified serialization and replay. Rollback: adapter converts observations back to existing `RuntimeResult`.

### Stage C — loop controller

Files: new `app/core/agent_loop.py` or `app/agent/loop.py`; `app/core/orchestrator/engine.py`; tests under `tests/runtime` and `tests/workflow`. Add one action per cycle and termination policy. Rollback: feature flag to old orchestrator path.

### Stage D — GAMBIT replanning

Files: `app/core/gambit/planner.py`, `plan_builder.py`, `agent_planner.py`, `app/core/contracts/planning.py`. Add observation-to-plan-delta adapter; do not modify CAP semantics. Tests: success continuation, alternate tool, missing information, ambiguity and achieved goal.

### Stage E — recovery

Files: `app/runtime/checkpoint.py`, `recovery.py`, `workflow/state.py`, `workflow/pause.py`. Include action/permit/observation IDs and side-effect reconciliation. Tests: interruption, provider failure, partial file write, stale checkpoint and resume. Rollback: read old checkpoint format through compatibility parser.

### Stage F — web/artifact/subagent expansion

Files: `app/conversation/reference_resolver.py`, `app/tools/filesystem.py`, `app/search/*`, memory controller, and worker contracts. Tests: search-to-file, fetch-to-synthesis, artifact rename/reference, scoped subagent and cancellation. Risk: scope leakage and token growth. Rollback: keep new state read-only until parity is proven.

## Exact Files to Keep

Keep `app/core/app.py`, `app/core/execution_coordinator.py`, `app/core/cap/*`, `app/governance/*`, `app/core/gambit/*`, `app/runtime/base.py`, `engine.py`, `dispatcher.py`, `checkpoint.py`, `recovery.py`, `app/tools/filesystem.py`, `security.py`, `app/router/*`, `app/models/*`, `app/memory/*`, `app/conversation/*`, `app/core/contracts/*`, `app/core/events.py`, and existing tests. These are Samaktha’s architecture, not obstacles to be replaced.

## Exact Files to Modify

* `app/core/contracts/state.py`: add typed agent/step/action/observation/transition records while preserving existing schemas.
* `app/core/contracts/runtime.py` and `tools.py`: add correlation IDs, verification/failure envelopes and context fields.
* `app/runtime/engine.py` and `dispatcher.py`: emit deterministic execution observations and honor cancellation/deadlines.
* `app/core/orchestrator/pipeline.py` and `engine.py`: insert the loop adapter after CAP and before/around existing Runtime calls.
* `app/core/gambit/planner.py`, `plan_builder.py`, `agent_planner.py`: accept structured observations and return plan deltas.
* `app/core/events.py`: publish typed lifecycle events without treating them as assistant responses.
* `app/runtime/checkpoint.py` and `recovery.py`: persist loop state and reconcile side effects.
* `app/conversation/reference_resolver.py`: resolve artifact identity before path/content operations.
* `app/memory/controller/*`: store only governed references/evidence, not arbitrary loop prose.
* `tests/runtime/*`, `tests/workflow/*`, `tests/production/*`, `tests/security/*`: add contract, replay and boundary coverage.

## Exact Files to Replace

None. No replacement has a demonstrated technical justification. If later evidence shows a single legacy seam bypasses `ExecutionCoordinator` or CAP, replace only that seam after adding an adapter and parity tests.

## External Code / Licensing Analysis

Both repositories declare Apache-2.0 licensing (`LICENSE` at each root; Codex also has `NOTICE` and third-party notices; Grok has `LICENSE`, `THIRD-PARTY-NOTICES`, and third-party directories). Reimplement interfaces and behavior from the public architectural evidence. Do not copy Rust files into Samaktha. If a future decision copies a specific Apache-2.0 file, preserve its copyright/license/NOTICE obligations and audit its third-party dependencies individually. Reimplementation is cleaner here because Samaktha is Python, CAP-governed, Windows-aware, and already has corresponding abstractions.

## Dependency Impact

| Dependency | Source | Why needed | Samaktha impact | Optional? |
|---|---|---|---|---|
| None initially | Native Samaktha/Pydantic | Typed loop contracts | Small code-only change | No |
| Existing Pydantic | Current project | Validation/serialization | Extend models | No |
| Existing SQLite/session stack | Current project | Checkpoints/state/memory | Add tables or records only after schema review | No for durable recovery |
| Rust/Bazel/sandbox services | External harnesses | Full external execution model | High startup/build/platform cost | Yes; do not add initially |
| MCP client library | Existing/verified Samaktha seam | Tool discovery | Only if current implementation lacks required protocol support | Yes |

## Performance Impact

**Measured:** no new Samaktha benchmark was run; no performance claim is made. **Inferred:** typed observation and persistence add serialization and disk I/O per action; replanning adds model calls/tokens; verification adds tool calls; bounded output and compaction reduce context growth; owner-scoped cancellation reduces leaked background work; keeping Python/native Windows paths avoids Rust/Bazel startup cost. Measure action latency, model-call count, tool-call count, serialized state size, checkpoint latency, memory, CPU, disk, and Windows cold start before/after each stage.

## Security Impact

Positive if boundaries are preserved: CAP decisions become explicit and auditable; tool outputs cannot impersonate assistant responses; artifacts and web evidence gain provenance; cancellation and checkpoint IDs reduce replay ambiguity. Risks: state records may contain secrets, path metadata or web content; redact at event and persistence boundaries; keep credentials environment/credential-store-only; do not expose the unauthenticated loopback API remotely; preserve configured roots, protected targets, size/recursion/file-count limits and overwrite approval in `ToolSecurityEnforcer`.

## Testing Strategy

Add regression tests mapped to behaviors:

| Test | Protected behavior |
|---|---|
| one-step success | Action -> CAP -> Runtime -> Observation -> finish |
| multi-step | dependency advancement and continuation |
| tool failure/retry | structured failure and bounded retry |
| alternate tool/replan | GAMBIT receives failure and changes action |
| missing information/ambiguity | acquisition or user escalation; no invention |
| governance denial | stop; no bypass/retry mutation |
| provider failure | recovery classification and provider boundary |
| file create/modify/rename/read | artifact identity and runtime verification |
| search -> file; search -> fetch -> synthesis | search/source/content/conclusion separation |
| memory -> planning/provider | scoped references only, no leakage |
| session continuity | resume from typed state/checkpoint |
| interruption/cancellation | no duplicate side effects; owner-scoped stop |
| checkpoint/recovery | reconcile partial execution and stale state |
| subagent | capability subset, parent/child IDs, result aggregation |
| termination | achieved, denied, cancelled, budget and unrecoverable paths |

Also retain current adversarial security, Windows, production, memory-isolation, execution-truth and checkpoint reconciliation suites. No external repository test suite is a substitute for these tests.

## Rollback Strategy

Use a feature flag at the composition root. New observations can be emitted in shadow mode and converted to current `RuntimeResult` objects. Persist new records in a versioned namespace; never rewrite old checkpoints in place. On failure, disable the loop flag, replay only verified existing checkpoints, and retain the new audit records for diagnosis. Roll back one stage at a time; never delete evidence or reset the working tree.

## Implementation Order

1. Contract models and deterministic observer adapter.
2. Unit tests for result/evidence separation.
3. One-step loop behind a feature flag.
4. GAMBIT plan-delta integration.
5. Checkpoint/recovery and interruption.
6. Artifact/web state integration.
7. Only then prototype governed subagents and richer MCP/background work.

## Future Extensions

Governed subagents with capability subsets; event-sourced replay UI; evidence graph and freshness policies; resumable long-running workflows; provider-specific planning budgets; ACP/app-server-like local protocol if multiple clients need it; stronger Windows job-object/process isolation after a threat-model decision; and measured adaptive policies learned from failure telemetry without allowing telemetry to change CAP rules.

## Final Architectural Recommendation

Samaktha should adopt the harnesses’ explicit identity, lifecycle, typed result, cancellation, checkpoint and protocol patterns, but implement them in its own Python contracts and preserve its governing architecture. CAP remains the deterministic authority. GAMBIT remains the adaptive planner. Runtime remains the controlled executor. The Observer becomes the evidence boundary. Memory stores governed continuity, not execution claims. The first implementation is therefore ready only for the additive one-step observation cycle; broad sandbox replacement, subagents, external protocol adoption and wholesale runtime replacement are **DO NOT IMPLEMENT** until separately prototyped and threat-modeled.

## Implementation Readiness

| Proposal | Classification | Reason |
|---|---|---|
| Typed IDs and observation envelope | READY | Fits existing contracts and directly addresses execution-truth bugs. |
| Deterministic Observer adapter | READY | Can wrap existing RuntimeResult/tool evidence without changing providers. |
| One-step loop behind flag | READY | Narrow, reversible, testable migration. |
| GAMBIT replan integration | NEEDS DESIGN DECISION | Exact existing planner return contracts and plan persistence must be reconciled first. |
| Checkpoint/recovery wiring | NEEDS PROTOTYPE | Side-effect reconciliation and compatibility need failure injection tests. |
| Artifact/web state schemas | NEEDS DESIGN DECISION | Verify current search/artifact models and migration format before editing. |
| Subagents | NEEDS PROTOTYPE | Parent governance, budget, cancellation and evidence aggregation are unresolved. |
| Full Grok/Codex sandbox adoption | DO NOT IMPLEMENT | Wrong language/runtime boundary and unnecessary migration/security risk at this stage. |
| Replacing CAP/GAMBIT/Runtime/Memory | DO NOT IMPLEMENT | No evidence that replacement improves Samaktha’s governing architecture. |

## Validation Report

* Blueprint path: `docs/architecture/HARNESS_INTEGRATION_BLUEPRINT.md`.
* External repositories verified: `xai-org/grok-build` and `openai/codex`; root licenses and cited source directories were inspected.
* Samaktha paths cited as existing were enumerated from the current checkout; the web/search path is explicitly marked for exact re-verification because its presence varies by checkout surface.
* No replacement is proposed, so no false replacement responsibility claim is made.
* CAP/GAMBIT/Runtime boundaries are preserved throughout; the Observer is inserted between Runtime evidence and GAMBIT replanning.
* No Samaktha implementation was started after document creation.
