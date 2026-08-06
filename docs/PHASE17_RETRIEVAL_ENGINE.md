# Phase 17 Retrieval Engine

Date: 2026-08-03

## Purpose

RetrievalEngine is the single owner of knowledge retrieval. It is responsible
for finding, ranking, filtering, deduplicating, and packaging evidence for
downstream intelligence consumers.

## Single Owner Responsibilities

RetrievalEngine owns:

- exact retrieval
- semantic retrieval
- hybrid retrieval
- ranking
- deduplication
- provenance assembly
- confidence scoring
- freshness filtering
- context bundle assembly

## Input Sources

RetrievalEngine may consume:

- Session Memory
- Project Memory
- Skill Memory
- Long-Term Memory
- Repository Index
- Code Index
- Internet Cache, in a future governed phase

## Output

RetrievalEngine outputs a context bundle containing:

- ranked evidence
- provenance
- freshness state
- retrieval confidence
- source type
- scope information

## Ownership Boundaries

RetrievalEngine never:

- mutates memory
- performs governance approval
- executes tools
- executes providers
- plans tasks
- reflects on outcomes

Memory stores knowledge.
RetrievalEngine retrieves knowledge.

Memory never ranks.
Memory never assembles context bundles.

## Determinism Rules

RetrievalEngine must preserve:

- stable sort order
- stable tie-breaking
- stable provenance identifiers
- stable deduplication rules
- stable freshness ordering

## Consumers

RetrievalEngine serves:

- IntelligenceManager
- GAMBIT
- Reflection
- Learning
- Developer-facing explainability surfaces

## Non-Goals

- No memory writes.
- No background indexing ownership.
- No direct planner control.
- No provider calls.

