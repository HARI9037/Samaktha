# Samaktha Core

**Current Stable Release:** Samaktha Core v0.5.0

---

## Project Overview

Samaktha is a next-generation AI infrastructure framework built to resolve the fundamental boundary problem in LLM-powered applications. Traditional AI wrappers dangerously conflate cognitive behaviors (planning) with deterministic flow (execution). Samaktha provides an unbreakable architectural structure designed to safely sandbox advanced AI cognition behind strict, observable, and policy-governed boundaries.

## Vision

The goal of Samaktha is to provide the deterministic foundation necessary to safely build autonomous, goal-directed AI agents. The infrastructure guarantees that no agent can bypass safety guardrails, hallucinate unauthorized executions, or operate outside a metered, fully observable environment.

## Current Architecture

Samaktha enforces execution through completely decoupled subsystems mapped by rigid protocols. Subsystem integrations rely exclusively on a generic `contracts` domain.

### Subsystems

- **CAP (Cognitive Alignment and Policy):** The sole governance engine.
- **GAMBIT (Goal-directed Autonomous Meaning and Behavioral Intent Translator):** The exclusive cognitive planner, reflection, and learning engine.
- **Workflow:** The sequential execution coordinator.
- **Runtime:** The deterministic task execution engine.
- **Router:** The intelligent provider selection protocol.
- **Memory:** The persistence and lifecycle owner of context, sessions, and learned skills.
- **ProviderManager & ToolManager:** The strict canonical boundaries for all external interactions.

### Extended Capability Layers

- **Personality Engine:** Behavior, intent, reflection, and response-style control for consistent conversational identity.
- **Conversation Engine:** Conversational memory synthesis and continuity.
- **Intelligence Layer:** RAG retrieval, knowledge graph, learning and reflection pipelines, memory evolution.
- **Internet Layer:** Web intelligence and retrieval tools.
- **Tool Ecosystem:** Filesystem, shell, calendar, contacts, notes, reminders, tasks, notifications, clipboard, and voice tools.
- **Voice Runtime:** Streaming STT/TTS with VAD and wake-word support.
- **Communication Hub:** Messaging/communication integrations.
- **Developer Ecosystem:** Developer-oriented tools and helpers.
- **Multi-Agent & Parallel Execution:** `runtime_parallel` for parallel task execution.
- **Windows TUI:** A native Windows terminal interface with themes, status bar, and command history.

## Architecture Diagram

```mermaid
graph TD
    User([User Request]) --> Orchestrator
    Orchestrator --> ContextEngine
    Orchestrator --> GAMBIT[GAMBIT Planner & Learner]
    Orchestrator --> CAP[CAP Governance]
    Orchestrator --> WorkflowEngine

    GAMBIT --> ExecutionPlan
    CAP --> Approval[Approval & Policy]

    WorkflowEngine --> Router
    WorkflowEngine --> Runtime

    Runtime --> ProviderManager
    Runtime --> ToolManager

    ProviderManager --> Providers[(Cloud / Local Models)]
    ToolManager --> Tools[(System Tools)]

    ContextEngine --> MemoryManager[(Memory SQLite)]
    MemoryManager --> GAMBIT
```

## Repository Structure

```text
Samaktha/
├── app/
│   ├── agent/             # Agent personalities and production routing
│   ├── api/               # HTTP API layer (execute, health, schemas)
│   ├── communication/     # Communication hub integrations
│   ├── config/            # Application settings
│   ├── conversation/      # Conversational intelligence and memory
│   ├── core/              # Core systems (CAP, GAMBIT, contracts, orchestrator, events)
│   ├── developer/         # Developer ecosystem tools
│   ├── fileparsers/       # Document parsing and writing
│   ├── intelligence/      # RAG, knowledge graph, learning pipelines
│   ├── internet/          # Web intelligence and retrieval
│   ├── memory/            # Storage, sessions, skills, and context retrieval
│   ├── models/            # Shared data models
│   ├── personality/       # Personality, behavior, intent, and reflection engine
│   ├── providers/         # LLM provider implementations
│   ├── router/            # Execution routing logic
│   ├── runtime/           # Deterministic execution and tool integration
│   ├── runtime_parallel/  # Parallel execution engine
│   ├── security/          # Input scanning and redaction
│   ├── shell/             # Shell integration
│   ├── tools/             # Functional capability registry and adapters
│   ├── tui/               # Windows-native terminal UI
│   ├── utils/             # Shared utilities
│   ├── voice/             # Streaming STT/TTS, VAD, wake-word
│   ├── windows/           # Windows-specific helpers
│   └── workflow/          # Sequential coordination
├── docs/                  # Architecture state, phase audits, changelog, release notes
├── tests/                 # 1782-test strict regression suite
├── main.py                # Entry point (backend or TUI)
└── pyproject.toml         # Packaging and project metadata
```

## Requirements

- Python **3.12+**

## Installation

```bash
git clone https://github.com/HARI9037/Samaktha.git
cd Samaktha
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -e .
```

## Running Locally

Backend (FastAPI) mode:

```bash
python main.py
```

Windows-native TUI mode:

```bash
python main.py --tui
```

## Environment Variables

Create a `.env` file in the project root with the provider keys you intend to use:

```env
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk-...
OPENROUTER_API_KEY=...
```

`.env` is gitignored and must never be committed.

## Running Tests

Run the full regression suite to verify boundary integrity:

```bash
pytest
```

## Current Capabilities

- Multi-provider dynamic routing (OpenAI, Groq, OpenRouter, local).
- Complete execution determinism.
- Sophisticated in-memory operation metrics.
- High-resolution timeline tracing.
- SQLite-backed memory and session persistence.
- Tool capability sandboxing and strict canonical boundaries.
- Deterministic cognitive learning (skill extraction and persistence).
- Automated skill lifecycle management (decay, deprecation, archival).
- Multimodal data injection (image, audio, video context).
- Deterministic streaming execution (SSE chunks).
- Deterministic tool composition (tool chains).
- Security & privacy layer (input filtering, output redaction, ToolGuard).
- Personality and behavioral engine with reflection.
- Session memory and conversational continuity.
- RAG retrieval and knowledge-graph-backed intelligence.
- Voice runtime (STT, TTS, VAD, wake-word).
- Parallel and multi-agent task execution.
- Windows-native TUI with themes and command history.

## Documentation

- [Changelog](docs/CHANGELOG.md)
- [Release Notes v0.3](docs/RELEASE_NOTES_v0.3.md)
- [Architecture State](docs/ARCHITECTURE_STATE.md)

Phase design documents and audit reports live under `docs/` (`PHASE*_*.md`).

## Roadmap / Known Limitations

- Memory currently relies on keyword/structured retrieval alongside RAG; semantic coverage is expanding.
- Continuous long-term learning systems are still evolving.
