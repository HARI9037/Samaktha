# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
