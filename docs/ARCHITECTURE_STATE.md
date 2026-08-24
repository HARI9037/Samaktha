# Architecture State

## Status

Samaktha 0.5.0 has completed the P0–P14 engineering-convergence baseline and is
ready for a private controlled pilot. This document describes executable
production composition, not roadmap subsystems or historical phase intent.

## Production composition

`app.core.app.create_orchestrator()` owns the canonical composition:

```text
Interface
  → ExecutionCoordinator
  → SamakthaOrchestrator
  → CAP
  → GAMBIT
  → WorkflowEngine
  → Router
  → RuntimeEngine
      → ProviderExecutor → ProviderManager → Provider
      → ToolExecutor → ToolSecurityEnforcer → ToolManager → Tool
  → Memory / Evidence / Checkpoints
```

The API, CLI/TUI, and voice adapter converge on this lifecycle. Runtime batch
and parallel scheduling remain internal infrastructure and preserve per-task
permit validation.

## Boundaries and responsibilities

- **ExecutionCoordinator** owns user-visible lifecycle state: start, wait,
  approval, cancel, result, inspection, and recovery.
- **CAP** evaluates policy/risk, obtains human decisions where required, and
  issues the signed final `ExecutionPermit` bound to the exact operation.
- **GAMBIT** parses goals and creates deterministic plans. It cannot invoke
  providers or tools.
- **ContextEngine / PreparedContext** form the single provider-context boundary
  from normalized conversation, visible memory, personality, and completed tool
  evidence.
- **WorkflowEngine** coordinates tasks and approval pauses without becoming an
  execution authority.
- **Router** selects compatible provider/model pairs under typed privacy and
  local-only constraints.
- **RuntimeEngine** validates permits and dispatches the two canonical
  executors.
- **ProviderExecutor** serializes validated prepared context and delegates to
  `ProviderManager`; fallback cannot escape execution-location policy.
- **ToolExecutor** delegates only after permit/governance validation and applies
  `ToolSecurityEnforcer` before `ToolManager` invokes a registered tool.
- **Memory/session stores** enforce principal, session, and workspace scope.
- **EvidenceStore** records correlated, sanitized authorization, routing,
  execution, and outcome events.
- **CheckpointStore / recovery** integrity-protect execution state and prevent
  unsafe replay of unknown non-idempotent effects.
- **PluginManager** owns discovery and explicit lifecycle only. Enabled trusted
  plugins register adapters into the canonical ToolRegistry and do not gain an
  alternate execution path.

## Architectural invariants

1. Models and planners may propose actions but cannot execute them.
2. Every user-reachable provider/tool task enters Runtime with a valid signed
   permit bound to the exact principal and operation.
3. A valid approved permit is not subjected to a second human approval for the
   same operation; mismatched, expired, tampered, or invalid permits are denied.
4. Runtime exposes exactly two canonical executor types: provider and tool.
5. Every tool action passes through ToolExecutor and ToolSecurityEnforcer.
6. Generated prose is not execution evidence and cannot fabricate success.
7. Local-only and privacy constraints survive routing, retry, and fallback.
8. PreparedContext is the authoritative model-message contract.
9. Memory access is explicitly scoped before retrieval, caching, or writeback.
10. Recovery cannot automatically replay an uncertain non-idempotent effect.
11. Scheduled reminder firing obtains fresh authorization and re-enters Runtime.
12. Plugin discovery never enables code; PluginManager is not execution
    authority.
13. Evidence and diagnostics sanitize secrets and user content by default.
14. Frozen/disconnected future subsystems may not become production paths
    without updating architecture guards and the production composition.

## Capability truth

The production `ToolRegistry` and product capability registry, not class
existence, determine user-visible support. The controlled pilot currently treats
filesystem as production-ready; memory and personal-information tools as local
only; internet/provider work as conditional on configuration; shell as an
advanced governed capability; email/message delivery as simulated or explicitly
limited; plugins as engineering-only; document extraction as internal; and
browser/media as unavailable.

See `docs/pilot/PILOT_SCOPE.md` for the complete matrix.

## Reliability and observability

- ExecutionCoordinator state and signed checkpoints support pause/restart and
  recovery.
- Unknown mutations are not automatically replayed.
- Evidence uses correlated execution, permit, operation, principal, and outcome
  identities and persists independently of checkpoints.
- Runtime capacity, retries, timeouts, cancellation, and retention are bounded.
- Diagnostics are read-only; explicit export contains sanitized aggregate data
  and performs no upload.

## Verification baseline

Canonical P14 acceptance, Python 3.14.5:

```text
2851 passed
0 failed
0 skipped
149 warnings
```

Relevant maintained gates include 115 architecture tests, 145 adversarial
security tests, 112 production tests, 159 stress tests, 150 plugin tests, and 27
pilot-readiness tests.

## Transitional and excluded systems

`AgentPlanner`, `MultimodalExecutor`, `ToolChainExecutor`, and
`CommunicationManager` are not canonical user execution paths. Runtime-parallel
workers are canonical infrastructure, not a second runtime. Plugins are excluded
from the initial user cohort despite their maintained engineering lifecycle.

Historical phase documents under `docs/` record earlier designs and do not
supersede this file.
