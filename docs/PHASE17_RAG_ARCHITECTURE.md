# Phase 17 RAG Architecture

Date: 2026-08-03

## Purpose

This document defines the long-term retrieval architecture that supports
learning, planning, review, and explanation.

It is architecture only. No production code is added in Phase 17.0.

## Ownership Clarification

Retrieval is owned by the RetrievalEngine, orchestrated by the
IntelligenceManager.

Memory stores knowledge.
Memory never ranks knowledge.
Memory never assembles context bundles.
Memory never performs semantic retrieval.

RAG is the broader architecture pattern, not the owner of retrieval.

## RAG Objectives

- Retrieve only evidence-backed knowledge.
- Keep retrieval deterministic.
- Preserve provenance and recency.
- Separate transient session context from durable knowledge.
- Support planning, debugging, review, and summarization without hallucination.

## Retrieval Tiers

Phase 17 uses layered retrieval:

1. Session retrieval
2. Project retrieval
3. Repository retrieval
4. Skill retrieval
5. Long-term semantic retrieval

Each layer can contribute evidence, but higher layers must not override lower
layers without provenance.

## Retrieval Sources

Approved sources for retrieval:

- session memory
- long-term memory
- repository index
- code index
- project model
- review findings
- test history
- CI history
- approved skill memory

Disallowed sources:

- unreviewed model guesses
- unsupported inferences
- private data without governance approval
- direct provider output without evidence capture

## RAG Data Model

The architecture assumes the following conceptual records:

- RetrievalQuery
- RetrievalCandidate
- RetrievedEvidence
- EvidenceRank
- ProvenanceChain
- MemoryCitation
- ContextBundle

Each retrieved item must carry:

- source
- timestamp or version
- confidence
- evidence summary
- provenance pointer

## Ranking Strategy

Ranking is deterministic and uses evidence-first heuristics:

- exact match signals outrank fuzzy match signals
- recent evidence outranks stale evidence when relevance is equal
- project-local evidence outranks workspace-wide evidence when scope matches
- direct trace evidence outranks inferred evidence
- explicit user-confirmed facts outrank passive observations

## Semantic Layer

The semantic layer is long-term only and is used when exact lookup is
insufficient.

Semantic retrieval must remain bounded by:

- vocabulary overlap
- document/source identity
- confidence threshold
- freshness
- scope

The semantic layer may improve recall, but it may not invent meaning.

## Planning Integration

RAG is fed into GAMBIT before plan construction.

GAMBIT may use retrieved knowledge to:

- select the right execution strategy
- reuse prior successful subplans
- avoid repeated failures
- choose the right skill candidates
- respect project-specific conventions

GAMBIT may not use retrieval to bypass CAP, ToolManager, or ProviderManager.

## Reflection Integration

Reflection consumes RAG outputs to:

- compare expectation and outcome
- identify stable patterns
- identify recurring regressions
- find reusable skills
- assess confidence drift

Reflection never writes directly to memory.

## Explanation Integration

The explanation surface can cite RAG evidence to answer questions such as:

- why a plan was chosen
- why a test was considered impacted
- why a failure was classified a certain way
- why a repository was detected as a monorepo

All explanations must be traceable to evidence.

## Long-Term Memory Interaction

Long-term memory stores stable knowledge objects:

- reusable procedures
- recurring project facts
- verified repository topology
- validated code relationships
- learned failure signatures

The architecture requires explicit expiration and refresh policies for mutable
knowledge.

## Freshness Model

Every retrievable item has a freshness state:

- active
- stale
- deprecated
- expired

Freshness affects ranking and whether the item may influence new plans.

## Confidence and Recall

Retrieval confidence is determined by:

- source trust level
- evidence density
- recency
- recurrence
- provenance integrity

Low-confidence candidates may be returned for inspection, but they must not be
treated as fact.

## Hallucination Controls

RAG hallucination prevention requires:

- no uncited retrieval summaries
- no cross-source claim fusion without evidence
- no synthetic answers when evidence is absent
- no silent fallback to model intuition

When evidence is weak, the system should answer with uncertainty instead of
inventing detail.

## Determinism Requirements

Retrieval must be reproducible for the same underlying state.

Determinism is preserved by:

- stable sort order
- stable scoring weights
- stable provenance identifiers
- stable truncation rules
- stable tie-breaking

## Non-Goals

- No learned embeddings requirement in Phase 17.0.
- No online training loop.
- No autonomous memory writes during retrieval.
- No direct provider or tool bypass.
- No memory-owned ranking.
- No prompt assembly inside Memory.
