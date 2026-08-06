# Phase 17 Reflection Pipeline

Date: 2026-08-03

## Purpose

Reflection is the deterministic post-execution analysis layer that turns
completed activity into evidence for learning and planning improvement.

This document is architecture only.

## Reflection Objectives

- Summarize what happened
- Compare intended and actual outcomes
- Classify success, partial success, or failure
- Extract reusable lessons
- Detect regressions
- Feed the learning pipeline

## Reflection Inputs

Reflection may observe:

- execution traces
- runtime reports
- tool results
- repository intelligence summaries
- code intelligence summaries
- test outputs
- CI results
- user corrections

Reflection must not rely on hidden state.

## Reflection Stages

1. Trace normalization
2. Outcome classification
3. Evidence extraction
4. Comparison to intent
5. Pattern detection
6. Confidence assignment
7. Learning proposal generation

## 1. Trace Normalization

Normalize execution artifacts into a stable event stream:

- ordered events
- consistent labels
- stable timing buckets
- error boundaries

## 2. Outcome Classification

Classify the completed task into one of:

- success
- partial success
- failure
- blocked
- inconclusive

Classification must be evidence-based.

## 3. Evidence Extraction

Extract only explicit facts:

- command or task attempted
- outputs produced
- errors raised
- files changed
- tests passed or failed
- repository or workspace effects

## 4. Comparison to Intent

Reflection compares expected behavior with actual behavior.

This comparison answers:

- Did the task complete?
- Did the task complete safely?
- Did the task produce the intended output?
- Did a prior assumption prove false?

## 5. Pattern Detection

Pattern detection looks for recurrence:

- repeated failure signatures
- repeated success signatures
- recurring test gaps
- recurring review findings
- recurring repository or workspace patterns

Pattern detection is deterministic and bounded by observed evidence.

## 6. Confidence Assignment

Reflection assigns confidence to conclusions based on:

- directness of evidence
- number of agreeing signals
- trace clarity
- absence of contradictory evidence

## 7. Learning Proposal Generation

Reflection may emit proposals for:

- new skill candidates
- memory updates
- plan adjustments
- test suggestions
- documentation updates

These are proposals only. They require governance before persistence.

## Reflection Artifacts

The architecture expects these conceptual artifacts:

- ReflectionSummary
- ReflectionMetrics
- FailureSignature
- SuccessSignature
- RegressionSignal
- LearningProposal
- ConfidenceAssessment

## Reflection Metrics

ReflectionMetrics are analytics only and never affect execution directly.

Conceptual metrics include:

- Success Rate
- Retry Count
- Planning Depth
- Tool Failure Rate
- Memory Recall Accuracy
- Context Utilization
- Hallucination Avoidance Events
- Approval Delay
- Learning Proposal Count

## Relation to Planning

Reflection informs GAMBIT by identifying:

- what plan shapes worked
- what dependencies slowed execution
- what changed between intent and result
- which steps are reusable

Reflection must never mutate the original plan retroactively.

## Hallucination Prevention

Reflection cannot claim:

- a root cause without evidence
- a hidden intent without proof
- a system state not observed
- a user preference not recorded

If evidence is incomplete, reflection must explicitly mark the conclusion as
limited.

## Determinism

Reflection output must be reproducible when trace inputs are unchanged.

Determinism requires:

- stable ordering
- stable thresholds
- stable wording templates
- stable evidence selection rules

## Non-Goals

- No autonomous remediation loop.
- No hidden provider calls.
- No hidden tool execution.
- No memory mutation without governance.
- No analytics-driven execution changes.
