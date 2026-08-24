# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased — 0.5.0 Controlled Pilot RC]

### Engineering convergence

- Converged authorization on CAP-issued, signed execution permits bound to exact
  principals and operations, with Runtime enforcement and correlated governance
  evidence.
- Made the product capability registry and production ToolRegistry authoritative
  for planning, user-visible support, and execution truth.
- Converged provider context on typed `PreparedContext`, including scoped memory,
  conversation history, personality, and completed Runtime tool evidence.
- Added principal/session/workspace memory isolation, bounded execution lifecycle,
  signed checkpoint recovery, and persistent sanitized evidence.
- Hardened filesystem, shell, network, reminder, provider fallback, plugin, and
  integration boundaries without introducing a second execution path.
- Composed the explicit PluginManager lifecycle into production while preserving
  discovery-without-enablement and canonical Runtime/ToolExecutor execution.
- Added reproducible Windows ONEDIR packaging, per-user bootstrap paths,
  single-instance protection, diagnostics, and controlled-pilot documentation.
- Added architecture, exact-production, stress, packaged, adversarial-security,
  and pilot-readiness regression suites.

### Pilot readiness

- Added Unicode-safe packaged CLI output and canonical rotating TUI logs.
- Added `doctor --export`, which creates a local sanitized aggregate diagnostic
  bundle without prompts, memory, file contents, credentials, or automatic
  upload.
- Clarified approval, denial, cancellation, timeout, simulation, provider
  acceptance, and unavailable-state presentation.
- Verified the engineering baseline with 2,851 passing tests and zero failures
  under Python 3.14.5.

This candidate is unsigned and intended only for a private controlled pilot. It
is not a new historical 0.5.0 release date and does not claim field-pilot or
public-release completion.

## [v0.5.0] - 2026-07-19

> Historical release record. Some experimental subsystems listed below are not
> part of the current canonical user execution path; the Unreleased pilot-RC
> section and `ARCHITECTURE_STATE.md` describe current production composition.

### Added
- **Advanced Provider Ecosystem**: Multi-provider support (OpenAI, Anthropic, Groq, local) via `ProviderManager`.
- **Multimodal Capabilities**: Introduced `multimodal` routing and image/audio base64 data injection without boundary violations.
- **Streaming Responses**: Deterministic server-sent event chunk streams via `StreamingExecutor`.
- **Tool Composition**: Evolved `ToolManager` to support sequential and parallel `ToolChain` dependency execution.
- **Security & Privacy Layer**: Built `ToolGuard`, `InputSecurityScanner`, and `OutputSecurityFilter` to proactively intercept path traversal, leakages, and credentials before tool execution. Added `retention_policy` and `SecurityLevel` privacy markings to `ContextMemoryStore`.

## [v0.4.0] - 2026-07-19

### Added
- **Parallel Execution**: Replaced linear workflow iteration with `ParallelWorkflowScheduler` to handle dynamic ExecutionGraph dependencies using asynchronous coroutines (`asyncio.gather`).
- **Multi-Agent Orchestration**: Enhanced GAMBIT with `AgentPlanner` and `AgentRegistry` to assign complex multi-agent goals without violating workflow/runtime isolation.
- **Distributed State Foundation**: Added `ExecutionGraph` dependency tracking and `RuntimeExecutionPool` to maintain state consistency across concurrent workers.
- **Semantic Memory**: Upgraded `MemoryManager` and `SkillMemoryStore` with a purely deterministic TF-IDF semantic index for context and skill retrieval.
- **Unified Telemetry**: Centralized metrics and observability under `app.core.telemetry`, defining rigid `TelemetrySnapshot` and `TelemetryEvent` structures in contracts.

### Changed
- **Protocol Centralization**: Moved `ProviderLike`, `ToolLike`, `ProviderManagerLike`, and `ToolManagerLike` to `app.core.contracts.protocols`.
- **GAMBIT Naming**: Renamed internal `WorkflowEngine` inside GAMBIT to `PlanBuilder` to eliminate naming ambiguity with the Workflow subsystem.
- **Test Suite**: Expanded test coverage heavily to 315 passing tests encompassing concurrent scheduling, fault tolerance, and agent isolation.

## [v0.3.0] - 2026-07-19

### Added
- **Reflection Engine**: Built deterministic capability to classify execution failures, generate lessons, and identify successful task sequences from `ExecutionTrace`s.
- **Learning Engine**: Implemented analytical extraction of `SkillCandidate`s from workflow results without direct provider/tool execution.
- **Skill Memory Store**: Established a deterministic, persistence-only SQLite schema to store and keyword-search extracted skills (`SkillRecord`s).
- **Planner Skill Retrieval**: Augmented the GAMBIT Planner to query active, high-confidence skills and seamlessly inject them into new `ExecutionPlan`s.
- **Skill Lifecycle Management**: Deployed usage tracking, deterministic confidence decay, automatic low-success deprecation, and archival, entirely owned by `MemoryManager`.
- **Cognitive Layer Observability**: Expanded `SkillMetricsCollector` to observe active/deprecated state counts, merge events, and decay iterations.

### Changed
- **Memory Store Refactoring**: Refactored `MemoryManager` and `SkillMemoryStore` to act as the strict persistence and lifecycle owner of skills, separating persistence logic from GAMBIT.
- **Planner Evaluation Rules**: Replaced tag-based skill deprecation filtering with explicit `SkillLifecycleState` enforcement directly at the retrieval layer.
- **Test Suite Expansion**: Added robust testing for cognitive operations (Reflection, Learning, Memory, Planner Integration, Lifecycle), increasing test suite to 246 passing tests.

## [v0.2.0] - 2026-07-19

### Added
- **Architecture Alignment**: Fully aligned execution subsystems to strictly separate governance (CAP), planning (GAMBIT), coordination (Workflow), and execution (Runtime).
- **Execution Reporting**: Integrated a deterministic reporting flow encapsulating partial failures, duration, outputs, and diagnostic metadata into a uniform `ExecutionReport`.
- **Execution Tracing**: Implemented low-overhead hierarchical event tracing (`ExecutionTrace` and `TimelineEvent`) within `app.core.contracts.trace` to provide detailed diagnostic timelines without polluting execution state.
- **Runtime Metrics**: Deployed an in-memory, deterministic metrics and observability subsystem capturing operational statistics.
- **Metrics Collectors**: Introduced specialized telemetry aggregators including `OrchestratorMetricsCollector`, `WorkflowMetricsCollector`, `ToolMetricsCollector`, `RouterMetricsCollector`, and `MemoryMetricsCollector`.
- **Canonical ProviderManager**: Solidified `ProviderManager` as the absolute entry point for all provider invocations, equipped with robust retry and metrics pipelines.
- **Canonical ToolManager**: Established `ToolManager.execute_tool` as the strict execution boundary for all tool operations, guaranteeing observability and standardized error handling.
- **Model Registry Improvements**: Enhanced model tracking with versioning, capability flags, and pricing metadata.
- **Capability Registry Improvements**: Formalized tool and provider capability resolution mechanisms.
- **Comprehensive Testing Suite**: Expanded the `pytest` regression suite to 181 tests, ensuring flawless functionality across boundaries and edge cases.

### Changed
- **Contracts Boundary**: Hardened `app.core.contracts` to act exclusively as a dependency-free governance boundary.
- **Tool Execution Boundary**: Refactored `app.runtime.executor` to proxy all tool executions through `ToolManager.execute_tool`, avoiding direct invocations.
- **Trace Contract Placement**: Migrated `ExecutionTrace` and `TimelineEvent` into `app.core.contracts.trace` to invert dependencies properly.

### Fixed
- **Architectural Circular Dependencies**: Eliminated cyclic imports between the runtime implementation layers and the generic contracts layers.
- **Tool Execution Bypasses**: Resolved vulnerabilities where runtime implementations bypassed tool observability pipelines.
- **Workflow State Management**: Handled edge cases involving partial progress and controlled termination on step failures.
