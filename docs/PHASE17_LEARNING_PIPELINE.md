# Phase 17 Learning Pipeline

Date: 2026-08-03

## Purpose

This document defines how Samaktha turns evidence into durable knowledge while
remaining deterministic, governable, and auditable.

This is architecture only.

## Learning Pipeline Overview

The learning pipeline has seven stages:

1. Capture
2. Normalize
3. Validate
4. Score
5. Classify
6. Propose
7. Persist

## 1. Capture

Capture collects candidate learning inputs from:

- runtime traces
- review findings
- repository intelligence
- code intelligence
- test outcomes
- CI outcomes
- user corrections

Capture is passive and read-only.

## 2. Normalize

Normalize turns raw observations into structured learning candidates.

Normalization produces:

- canonical text
- stable identifiers
- source metadata
- evidence links
- scope labels

## 3. Validate

Validation checks whether a candidate is eligible for learning.

Validation rules:

- evidence must exist
- source must be supported
- candidate must be within an allowed scope
- candidate must not conflict with higher-priority facts
- candidate must not be classified as prohibited by CAP

Candidates failing validation are retained only as observations.

## 4. Score

Scoring estimates whether the candidate is worth remembering.

Scoring dimensions:

- frequency
- usefulness
- recurrence
- confidence
- project relevance
- risk
- freshness

Scores are deterministic and based on observed signals only.

## 5. Classify

Learning classification determines the destination:

- session memory
- project memory
- long-term memory
- skill memory
- no persistence

Classification is driven by scope and stability.

Examples:

- temporary task detail -> session memory
- reusable project convention -> long-term memory
- repeated step sequence -> skill memory
- unstable one-off observation -> no persistence

## 6. Propose

Proposals are the handoff from analysis to governance.

Proposal contents:

- candidate summary
- evidence list
- confidence score
- storage target
- retention policy
- justification

Learning proposals do not mutate memory directly.

## 7. Persist

Persistence occurs only after governance approval and memory-layer acceptance.

Persistence requirements:

- source trace attached
- confidence threshold met
- target chosen
- expiry or refresh policy defined
- duplicate policy checked

## Skill Learning Architecture

Skills are a special form of learned knowledge.

A skill may be learned when:

- it appears repeatedly in execution traces
- it improves task success
- it is reusable across similar tasks
- it is describable as a deterministic procedure

Skill learning must produce:

- trigger conditions
- steps
- constraints
- failure conditions
- evidence list

Skill learning is distinct from skill execution.
Skill learning proposes skills.
Skill Runner loads approved skills and expands them at execution time.

Skills do not contain model-generated speculation.

## Memory Evolution Architecture

Memory evolves through stable states:

- Captured
- Validated
- Approved
- Active
- Stale
- Archived
- Deleted

Deletion is governance-controlled.
Deletion preserves audit history.
Deletion does not remove provenance.

Transitions are deterministic and require policy checks.

## Regression Awareness

The learning pipeline records regressions when:

- a previously successful action starts failing
- a test begins failing after a code change
- a repository or workspace pattern changes shape

Regression observations can lower confidence for previously learned items.

## Confidence Model

Confidence is updated over time using:

- recurrence
- successful reuse
- disagreement from later evidence
- explicit correction

Confidence never grows from unsupported repetition alone.

The independent confidence domains are:

- Evidence Confidence
- Retrieval Confidence
- Reasoning Confidence
- Execution Confidence
- Memory Confidence
- Learning Confidence

Each domain has a single owner:

- Evidence Confidence: Reflection and Retrieval
- Retrieval Confidence: RetrievalEngine
- Reasoning Confidence: GAMBIT
- Execution Confidence: Runtime
- Memory Confidence: MemoryController
- Learning Confidence: IntelligenceManager

## Hallucination Prevention

Learning may only use evidence that is:

- directly observed
- traceable
- scoped
- versioned

The pipeline must reject:

- invented root causes
- unverified assumptions
- ambiguous matches without sufficient support

## Learning Budget

The Learning Budget prevents unlimited background learning.

Budget dimensions are deterministic limits on:

- maximum reflections
- maximum proposals
- maximum semantic retrieval depth
- maximum memory writes
- maximum indexing operations

Budget policies are deterministic and are owned by IntelligenceManager.

## Relationship to Existing Subsystems

- GAMBIT may request retrieval from learned knowledge.
- Memory stores the approved learning artifacts.
- Runtime generates traces that feed learning.
- ToolManager and ProviderManager remain execution-only.
- CAP is the final authority for risky persistence or destructive change.

## Non-Goals

- No autonomous self-training loop.
- No direct provider usage inside learning.
- No hidden memory mutation.
- No learning from uncaptured data.
- No skill execution inside learning.
- No memory ranking inside learning.
