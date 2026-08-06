# Phase 17 Intelligence Manager

Date: 2026-08-03

## Purpose

IntelligenceManager is the orchestration boundary for the intelligence
subsystem. It coordinates intelligence lifecycle operations and nothing else.

It does not:

- execute tools
- plan tasks
- own memory
- replace CAP
- replace GAMBIT
- replace Runtime

## Single Owner Responsibilities

IntelligenceManager owns:

- retrieval orchestration
- reflection orchestration
- learning orchestration
- skill proposal orchestration
- knowledge proposal orchestration
- confidence updates across intelligence domains
- context bundle generation
- learning budget enforcement
- intelligence version assignment

## Conceptual Operations

IntelligenceManager exposes the following conceptual operations:

- `retrieve()`
- `reflect()`
- `learn()`
- `propose()`
- `assemble_context()`

These are orchestration concepts only. They are not implementation details.

## Coordination Flow

The orchestrator sequence is:

1. Receive an intelligence request or execution completion signal.
2. Ask RetrievalEngine for evidence and context.
3. Assemble a context bundle.
4. Hand the context bundle to GAMBIT, Reflection, or Learning as needed.
5. Collect reflection and learning outputs.
6. Produce memory proposals or skill proposals.
7. Route any approval-requiring persistence through CAP.
8. Pass approved proposals to MemoryController for storage.

## Ownership Boundaries

IntelligenceManager never:

- ranks retrieved items itself
- mutates memory directly
- writes to indexes directly
- performs reflection analysis itself
- performs planning itself
- executes tools or providers

## Event Role

IntelligenceManager is the conceptual consumer and producer of intelligence
events:

- Runtime Finished
- ReflectionRequested
- LearningProposalCreated
- MemoryProposalReady
- GovernanceApprovalRequested
- MemoryPersisted

## Non-Goals

- No event bus implementation.
- No autonomous background learning loop.
- No planning logic.
- No memory storage logic.

