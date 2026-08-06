# Phase 17 Knowledge Graph

Date: 2026-08-03

## Purpose

The Knowledge Graph is the conceptual relationship model for project,
repository, code, and dependency understanding.

It is read-only during planning and only updated through governed workflows.

## Relationship Model

The graph describes relationships such as:

- Project contains Repository
- Repository contains Directory
- Directory contains File
- File contains Class
- Class contains Method
- Method calls Method
- File imports File
- Repository depends_on Repository

## Ownership

The Knowledge Graph is owned as a conceptual intelligence artifact by
IntelligenceManager.

The physical data behind it may be sourced from:

- Repository Index
- Code Index
- Workspace Index
- Project summaries

## Responsibilities

The Knowledge Graph supports:

- dependency understanding
- architecture summaries
- code navigation
- cross-project search
- safe retrieval
- planning context generation

## Access Rules

- Read-only during planning.
- Updates require governance.
- Updates are derived from evidence, not inference alone.
- No direct mutation from Runtime, GAMBIT, or ToolManager.

## Consumers

The Knowledge Graph can be used by:

- RetrievalEngine
- IntelligenceManager
- GAMBIT for planning context
- Project summarization
- Review analysis

## Non-Goals

- No graph database requirement.
- No autonomous mutation.
- No runtime execution responsibility.
- No tool execution responsibility.

