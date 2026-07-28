# Architecture State

## Executive Summary

Samaktha Core v0.3 concludes Phase 3, finalizing the Cognitive Layer (Reflection, Learning, and Skill Memory). The architecture definitively separates planning, coordination, execution, and governance into completely isolated subsystems while introducing a purely deterministic, persistence-only learning engine. This structure resolves the inherent unpredictability of LLM agents by ensuring that cognitive behaviors do not silently leak into deterministic control flows and that learned skills follow a strict, trackable lifecycle.

## Current Architecture

The architecture strictly enforces an execution pipeline separated by discrete contracts (`app.core.contracts`). No subsystem is permitted to bypass its defined scope. The contracts layer remains fully decoupled from runtime implementations, guaranteeing zero circular dependencies. All subsystem dependencies point inwards to `contracts`.

## Subsystem Responsibilities

- **CAP (Cognitive Alignment and Policy):** The absolute governance boundary. Evaluates the risk and privacy of actions.
- **GAMBIT (Goal-directed Autonomous Meaning and Behavioral Intent Translator):** The planning, reflection, and learning engine. Generates execution plans, extracts reusable skills from execution traces, and injects retrieved skills into future plans. It has no direct access to tools, providers, or memory modification beyond safe API boundaries.
- **Workflow:** The coordination engine. Transforms GAMBIT plans into sequential execution steps. Operates deterministically without autonomous loops.
- **Runtime:** The execution engine. Executes `RuntimeTask` definitions by invoking the appropriate Managers. Does not manage tool lifecycles, select providers, or perform any cognitive tasks.
- **Router:** The selection engine. Routes runtime executions to the most appropriate provider/model combination deterministically.
- **ProviderManager:** The absolute entry point for all provider invocations, equipped with resilient retries, cooldowns, and performance tracking.
- **ToolManager:** The canonical, metered execution boundary for all tool operations, standardizing execution and tracking.
- **Memory (MemoryManager):** Cognitive storage system and lifecycle owner. Responsible for persisting learned skills, managing decay, deprecation, archival, and duplicate merging.

## Execution Pipeline

1. **Orchestrator** receives the user request and provisions a `RuntimeContext` and `ExecutionTrace`.
2. **ContextEngine** retrieves necessary conversation and memory history.
3. **GAMBIT Planner** retrieves relevant, ACTIVE skills from Memory and deterministically injects them into an `ExecutionPlan`.
4. **CAP** audits the plan for privacy and policy violations, halting execution if blocked.
5. **WorkflowEngine** sequences the approved plan into tasks.
6. **Router** determines the execution provider for each task.
7. **Runtime** executes the tasks sequentially through the **ProviderManager** and **ToolManager**.
8. **WorkflowEngine** returns an `ExecutionReport` synthesizing outputs, diagnostic traces, and metrics.
9. **GAMBIT ReflectionEngine & LearningEngine** analyze the trace to extract potential `SkillCandidate`s and persist them to Memory.
10. **Orchestrator** returns a `RuntimeResult` to the user interface.

## Architecture Invariants

- CAP is the sole governance boundary.
- GAMBIT only plans, reflects, and learns.
- Workflow only coordinates.
- Runtime only executes.
- Router only selects.
- Memory owns skill persistence and lifecycle management (not GAMBIT).
- ProviderManager is the sole provider execution entry point.
- ToolManager is the sole tool execution entry point.
- ModelRegistry is the canonical metadata source.
- No direct GAMBIT → Memory dependency for modification.
- No `app.core.contracts` → `app.runtime` dependency.
- No unmetered bypasses exist for tool or provider execution.
- No circular imports.

## Observability

- **ExecutionReport**: Synthesizes the end-to-end task workflow (success/failure, duration, generated results, errors, diagnostic metadata).
- **ExecutionTrace**: High-resolution, hierarchical timeline recording engine (`TimelineEvent`) embedded throughout the execution stack.
- **Metrics**: Real-time, strictly deterministic, in-memory telemetry gathered by decoupled components, including `SkillMetricsCollector` to track skill lifecycle health.

## Testing

The system currently boasts a robust, 246-test regression suite ensuring 100% stable execution. Tests strictly target architectural integrity, boundary preservation, partial failure handling, observability constraints, and deterministic cognitive learning without mimicking autonomous behavior.

## Current Metrics
- **Phase 4 Completion**: 100%
- **Failing Tests**: 0
- **Total Tests**: 314
- **Critical Issues**: 0

## Phase 4 Achievements

- **Parallel Execution**: Refactored WorkflowEngine into a `ParallelWorkflowScheduler` to handle complex dependency execution via `asyncio.gather`.
- **Multi-Agent Orchestration**: Abstracted delegation strategies into `AgentRegistry` and `AgentPlanner` within GAMBIT without mutating runtime boundaries.
- **Distributed State Foundation**: Deployed robust `ExecutionGraph` state tracking and `RuntimeExecutionPool` logic.
- **Semantic Memory**: Upgraded the `MemoryManager` with a deterministic, local TF-IDF semantic index to surface intelligent context and skills.
- **Telemetry Consolidation**: Unified tracing and observability under `app.core.telemetry`, exposing rigorous `TelemetrySnapshot` and `MetricCategory` structures.

## Final Architecture Status (v0.4)

Samaktha Core v0.4 represents the finalized foundational architecture. All invariant boundaries (CAP, GAMBIT, Workflow, Runtime) are strictly enforced and thoroughly covered by over 314 automated tests. Protocol definitions have been centralized, and naming collisions (e.g., GAMBIT's `PlanBuilder`) have been resolved.

## Phase 5 Entry Point

Phase 5 will begin focusing on Provider Integrations and external API orchestration, leveraging the bulletproof foundation established in v0.4.
