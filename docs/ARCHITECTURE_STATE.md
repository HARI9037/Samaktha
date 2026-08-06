# Architecture State

## Executive Summary

Samaktha Core concludes Phase 10A, wiring the deterministic Personality vertical
slice (Phase 9.1–9.5) and Session Memory (Phase 10.1) into the production
orchestration path. The architecture definitively separates planning,
coordination, execution, governance, and communication into completely isolated
subsystems. The Personality Engine is a permanent, co-equal first-class
subsystem: it decides **how** Samaktha behaves and communicates, never what it
plans, governs, or executes. The composed system prompt is now the single prompt
source for all text-generation tasks; the legacy raw `memory_context` string is
removed from the runtime path.

## Current Architecture

The architecture strictly enforces an execution pipeline separated by discrete
contracts (`app.core.contracts`). No subsystem is permitted to bypass its defined
scope. The contracts layer remains fully decoupled from runtime implementations,
guaranteeing zero circular dependencies. All subsystem dependencies point
inwards to `contracts`.

## Subsystem Responsibilities

- **CAP (Cognitive Alignment and Policy):** The absolute governance boundary.
  Evaluates the risk and privacy of actions.
- **GAMBIT (Goal-directed Autonomous Meaning and Behavioral Intent Translator):**
  The planning, reflection, and learning engine. Generates execution plans,
  extracts reusable skills from execution traces, and injects retrieved skills
  into future plans. It has no direct access to tools, providers, or memory
  modification beyond safe API boundaries.
- **Personality Engine:** The communication boundary. Deterministically
  transforms a single request into a structured evaluation — identity and
  greeting classification (9.1), a memory-visibility gate (9.2), a behavior
  decision (9.3), and a composed system prompt (9.4). It never reasons, never
  plans, never governs, never writes to memory, never selects models, and never
  invokes tools. A deterministic reflection engine (9.5) observes completed
  interactions read-only.
- **Workflow:** The coordination engine. Transforms GAMBIT plans into sequential
  execution steps. Operates deterministically without autonomous loops.
- **Runtime:** The execution engine. Executes `RuntimeTask` definitions by
  invoking the appropriate Managers. Does not manage tool lifecycles, select
  providers, or perform any cognitive tasks.
- **Router:** The selection engine. Routes runtime executions to the most
  appropriate provider/model combination deterministically.
- **ProviderManager:** The absolute entry point for all provider invocations,
  equipped with resilient retries, cooldowns, and performance tracking.
- **ToolManager:** The canonical, metered execution boundary for all tool
  operations, standardizing execution and tracking.
- **Memory (MemoryManager):** Cognitive storage system and lifecycle owner.
  Responsible for persisting learned skills, managing decay, deprecation,
  archival, and duplicate merging.
- **Memory Controller:** Read/write facade and lifecycle manager over
  `MemoryManager` (deletion by id/type, consolidation, preference resolution,
  promotion). Backed by the SQLite store.
- **Session Memory (Phase 10.1):** Deterministic, structured, temporary
  conversational knowledge (current task, project context, temporary decisions).
  Strictly separate from long-term memory; never promoted automatically.

## Execution Pipeline

1. **Orchestrator** receives the user request and provisions a `RuntimeContext`
   and `ExecutionTrace`.
2. **ContextEngine** retrieves necessary conversation and memory history.
3. **Personality Engine** evaluates the request against retrieved memories
   (visibility gate + behavior decision); the **Prompt Composer** emits the
   composed `system_prompt`.
4. **GAMBIT Planner** retrieves relevant, ACTIVE skills from Memory and
   deterministically injects them into an `ExecutionPlan`.
5. **CAP** audits the plan for privacy and policy violations, halting execution
   if blocked.
6. **WorkflowEngine** sequences the approved plan into tasks, injecting the
   composed `system_prompt` into text-generation tasks.
7. **Router** determines the execution provider for each task.
8. **Runtime** executes the tasks sequentially through the **ProviderManager**
   and **ToolManager** using the composed `system_prompt`.
9. **GAMBIT ReflectionEngine, Phase 8.2 Memory Formation, and the Personality
   ReflectionEngine** analyze the trace to extract `SkillCandidate`s, form
   observations, and produce a reflection report — persisted to Memory.
10. **Orchestrator** returns a `RuntimeResult` to the user interface.

## Architecture Invariants

- CAP is the sole governance boundary.
- GAMBIT only plans, reflects, and learns.
- Personality only communicates — it never reasons, plans, governs, selects
  models, invokes tools, or writes to memory.
- Personality output is deterministic: given identical inputs, a byte-identical
  directive is produced (no LLM, no embeddings, no remote calls, no randomness).
- Workflow only coordinates.
- Runtime only executes.
- Router only selects.
- Memory owns skill persistence and lifecycle management (not GAMBIT).
- Session Memory owns temporary conversational state (never promoted).
- ProviderManager is the sole provider execution entry point.
- ToolManager is the sole tool execution entry point.
- ModelRegistry is the canonical metadata source.
- No direct GAMBIT → Memory dependency for modification.
- No `app.core.contracts` → `app.runtime` dependency.
- No unmetered bypasses exist for tool or provider execution.
- No circular imports.

## Observability

- **ExecutionReport**: Synthesizes the end-to-end task workflow (success/failure,
  duration, generated results, errors, diagnostic metadata).
- **ExecutionTrace**: High-resolution, hierarchical timeline recording engine
  (`TimelineEvent`) embedded throughout the execution stack.
- **Metrics**: Real-time, strictly deterministic, in-memory telemetry gathered by
  decoupled components, including `SkillMetricsCollector` to track skill
  lifecycle health.
- **PipelineState**: Captures per-request `personality_evaluation`,
  `prompt_composition`, and `reflection_report` alongside the execution plan.

## Testing

The system currently boasts a robust 883-test regression suite ensuring stable
execution. Tests strictly target architectural integrity, boundary preservation,
deterministic cognitive behavior, persistent memory deletion, session memory,
and the production personality wiring — without mimicking autonomous behavior.

## Current Metrics
- **Phase 10A Completion**: 100%
- **Failing Tests**: 0
- **Total Tests**: 883
- **Critical Issues**: 0

## Phase 9 Achievements (Personality Engine)

- **9.1 Identity & Greeting**: Deterministic `IdentityPolicy` and
  `GreetingPolicy` with structured decisions.
- **9.2 Memory Visibility**: `MemoryVisibilityPolicy` + rule detectors gate which
  memories may surface; greeting turns expose zero memories.
- **9.3 Behavior Engine**: Deterministic feature extraction and policy
  evaluators producing a structured `BehaviorDecision` (no tone-in-prompts).
- **9.4 Prompt Composer**: Deterministic section builders (`prompt_sections.py`)
  emitting the composed `system_prompt` — the single prompt source.
- **9.5 Reflection Engine**: Deterministic feature extraction and reflection
  report models, observed read-only after interactions.

## Phase 10 Achievements

- **10.1 Session Memory**: `SessionManager` with structured models, a
  deterministic store, and an index; wired through `create_orchestrator`.
- **10A Production Runtime Integration**: The personality vertical slice is wired
  into the orchestrator (`personality_engine` / `prompt_composer` /
  `reflection_engine`); composed `system_prompt` injected into runtime
  text-generation tasks; `delete_session` session_id injection; CAP
  `delete*` action normalization; persistent memory deletion paths verified;
  `ProviderExecutor` prefers the composed prompt; the raw `memory_context`
  string is removed from the runtime path.

## Final Architecture Status (v0.10)

Samaktha Core represents the finalized foundational architecture. All invariant
boundaries (CAP, GAMBIT, Personality, Workflow, Runtime, Memory) are strictly
enforced and thoroughly covered by automated tests. The Personality Engine is
fully integrated into production routing, execution, and reflection.

## Phase 10B Entry Point

Phase 10B continues production-facing work on top of the integrated personality
and session-memory foundation.
