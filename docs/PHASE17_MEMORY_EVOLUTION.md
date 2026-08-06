# Phase 17 Memory Evolution

Date: 2026-08-03

## Purpose

This document defines how memory changes over time as Samaktha learns from
experience while preserving architectural boundaries.

This is architecture only.

## Memory Surfaces

Phase 17 distinguishes four memory surfaces:

1. Session memory
2. Project memory
3. Long-term memory
4. Skill memory

## Session Memory

Session memory stores temporary, task-local context:

- current goal
- working assumptions
- active file set
- transient decisions
- short-lived debugging state

Session memory is disposable and must not be promoted automatically.

## Project Memory

Project memory stores stable facts about the current repository or workspace:

- architecture notes
- folder relationships
- repo-specific conventions
- dependency patterns
- test layout

Project memory is reusable within the project boundary.

## Long-Term Memory

Long-term memory stores reusable knowledge that can apply across projects:

- deterministic procedures
- learned debugging heuristics
- reflection summaries
- stable review patterns
- confidence calibration signals

Long-term memory requires stronger validation than session memory.

## Skill Memory

Skill memory stores reusable procedures extracted from repeated execution.

Each skill should include:

- trigger
- steps
- constraints
- failure modes
- evidence summary

Skill memory is the most structured memory tier.

## Evolution Stages

Memory evolves through the following states:

- Captured
- Validated
- Approved
- Active
- Stale
- Archived
- Deleted

## Promotion Rules

Promotion to a durable tier requires:

- repeated evidence or strong direct evidence
- stable relevance
- scoped applicability
- no conflict with existing facts
- governance approval when required

## Decay Rules

Memory decays when:

- evidence becomes stale
- a project changes shape
- a learned pattern stops recurring
- later evidence contradicts earlier evidence

Decay does not delete history. It changes usefulness.

## Refresh Rules

Refresh occurs when a learned item remains useful but needs updated evidence.

Refresh updates:

- confidence
- recency
- provenance
- applicability scope

## Conflict Resolution

When memory items conflict:

- direct evidence outranks inference
- recent verified evidence outranks stale evidence
- project-local evidence outranks workspace-wide generalization
- higher-confidence items outrank lower-confidence items

Conflicts should be preserved as audit history when possible.

## Hallucination Prevention

Memory evolution must never store:

- unsupported guesses
- ambiguous claims without evidence
- claims with missing provenance
- data disallowed by CAP

If the system cannot justify persistence, it must keep the item ephemeral.

## Relationship to RAG

Memory feeds retrieval, and retrieval feeds learning.

The loop is:

1. observe
2. retrieve
3. reflect
4. propose
5. govern
6. persist
7. retrieve again

This loop must remain bounded and auditable.

## Relationship to GAMBIT

GAMBIT may ask memory for:

- prior plans
- useful skills
- repository conventions
- repeated failure patterns

GAMBIT does not own memory mutation.

## Deletion Semantics

Deletion is governance-controlled.
Deletion preserves audit history.
Deletion preserves provenance.
Deletion removes the active record from future retrieval, but not the record of
that record.

## Non-Goals

- No automatic promotion from raw trace to long-term memory.
- No hidden online learning.
- No direct provider-based memory writes.
- No memory change outside governance.
- No provenance destruction on deletion.
