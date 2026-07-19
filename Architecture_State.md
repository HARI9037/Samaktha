# Architecture State

## Executive Summary

Samaktha Core v0.2 concludes Phase 2, finalizing a rigid, deterministic, and highly observable infrastructure layer. The architecture definitively separates planning, coordination, execution, and governance into completely isolated subsystems. This structure resolves the inherent unpredictability of LLM agents by ensuring that cognitive behaviors do not silently leak into deterministic control flows. 

## Current Architecture

The architecture strictly enforces an execution pipeline separated by discrete contracts (`app.core.contracts`). No subsystem is permitted to bypass its defined scope. The contracts layer remains fully decoupled from runtime implementations, guaranteeing zero circular dependencies. All subsystem dependencies point inwards to `contracts`.

## Subsystem Responsibilities

- **CAP (Cognitive Alignment and Policy):** The absolute governance boundary. Evaluates the risk and privacy of actions.
- **GAMBIT (Goal-directed Autonomous Meaning and Behavioral Intent Translator):** The planning engine. Generates execution plans but cannot coordinate or execute them. It has no direct access to tools or memory interfaces.
- **Workflow:** The coordination engine. Transforms GAMBIT plans into sequential execution steps. Operates deterministically without autonomous loops.
- **Runtime:** The execution engine. Executes `RuntimeTask` definitions by invoking the appropriate Managers. Does not manage tool lifecycles or select providers.
- **Router:** The selection engine. Routes runtime executions to the most appropriate provider/model combination deterministically.
- **ProviderManager:** The absolute entry point for all provider invocations, equipped with resilient retries, cooldowns, and performance tracking.
- **ToolManager:** The canonical, metered execution boundary for all tool operations, standardizing execution and tracking.
- **Memory:** Cognitive storage system backed by an SQLite persistence layer with robust key-value indexing and keyword search.

## Execution Pipeline

1. **Orchestrator** receives the user request and provisions a `RuntimeContext` and `ExecutionTrace`.
2. **ContextEngine** retrieves necessary conversation and memory history.
3. **GAMBIT** generates an `ExecutionPlan`.
4. **CAP** audits the plan for privacy and policy violations, halting execution if blocked.
5. **WorkflowEngine** sequences the approved plan into tasks.
6. **Router** determines the execution provider for each task.
7. **Runtime** executes the tasks sequentially through the **ProviderManager** and **ToolManager**.
8. **WorkflowEngine** returns an `ExecutionReport` synthesizing outputs, diagnostic traces, and metrics.
9. **Orchestrator** returns a `RuntimeResult` to the user interface.

## Architecture Invariants

- CAP is the sole governance boundary.
- GAMBIT only plans.
- Workflow only coordinates.
- Runtime only executes.
- Router only selects.
- ProviderManager is the sole provider execution entry point.
- ToolManager is the sole tool execution entry point.
- ModelRegistry is the canonical metadata source.
- No direct GAMBIT → Memory dependency.
- No `app.core.contracts` → `app.runtime` dependency.
- No unmetered bypasses exist for tool or provider execution.
- No circular imports.

## Observability

- **ExecutionReport**: Synthesizes the end-to-end task workflow (success/failure, duration, generated results, errors, diagnostic metadata).
- **ExecutionTrace**: High-resolution, hierarchical timeline recording engine (`TimelineEvent`) embedded throughout the execution stack.
- **Metrics**: Real-time, strictly deterministic, in-memory telemetry gathered by decoupled components (`OrchestratorMetricsCollector`, `WorkflowMetricsCollector`, `RouterMetricsCollector`, `ToolMetricsCollector`, `MemoryMetricsCollector`, `ProviderMetrics`).

## Testing

The system currently boasts a robust, 181-test regression suite ensuring 100% stable execution. Tests strictly target architectural integrity, boundary preservation, partial failure handling, and observability constraints without mimicking autonomous behavior.

## Current Metrics
- **Phase 2 Completion**: 100%
- **Failing Tests**: 0
- **Total Tests**: 181
- **Critical Issues**: 0

## Phase 2 Achievements

- Achieved 100% deterministic infrastructure.
- Formalized execution reporting and diagnostic tracing.
- Centralized execution pipelines behind canonical managers.
- Eliminated all circular dependencies and boundary violations.
- Implemented comprehensive operational metrics.

## Deferred Improvements

- Unifying metric collectors under a generic observable contract within `app.core.contracts`.
- Renaming GAMBIT's internal `WorkflowEngine` component to `PlanBuilder` to eliminate naming collisions.
- Moving scattered base protocols (`ProviderLike`, `ToolLike`) fully into the central contracts domain.

## Phase 3 Entry Point

Phase 3 is prepared to commence focusing on intelligent and autonomous behavior. The deterministic infrastructure is ready to safely accommodate:
- Semantic memory and RAG embeddings.
- Autonomous execution loops and intelligent agents.
- Reflection, self-correction, and heuristic learning.
