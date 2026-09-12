# Samaktha Explicit Memory Write & Targeted Recall Convergence Report

12 September 2026. **Read-only diagnosis; implementation stopped under section 53 of the supplied request.** Only this report was added. No application source, tests, live memory, or configuration was changed.

## 1. Executive Result

| Gate | Result | Evidence / blocker |
|---|---|---|
| M1 — Store classification | PARTIAL | Incorrect classification reproduced; no repair applied |
| M2 — Store payload | BLOCKED | No typed store goal/action to carry it |
| M3 — Canonical mutation | BLOCKED | Production MemoryTool has no store/write action |
| M4 — Store confirmation | BLOCKED | No explicit-store Runtime evidence path exists |
| M5 — Targeted query | PARTIAL | Current incorrect query derivation identified |
| M6 — Relevance/not-found | PARTIAL | Unrelated candidate inclusion identified; not changed |
| M7 — Restart durability | BLOCKED | Cannot run the required explicit-store restart test yet |
| M8 — Scope isolation | BLOCKED | Existing controls found; new store path does not exist to validate |
| M9 — Previous-session regression | BLOCKED | Not rerun in this stopped phase; no source changed |
| M10 — Full regression gate | BLOCKED | No completed implementation or new full-suite run |

The storage substrate exists. The missing piece is specifically a **user-requested, governed MemoryTool write operation**, not a database. This report applies the request's explicit instruction to stop if no canonical durable memory-write operation currently exists. Adding a new authorized tool action would be the narrow next step if you permit that exception.

## 2. Real-User Failure

Reported: `remember that my pilot validation codeword is COBALT-619` produced a generic answer or broad memory search. The read-only executable trace reproduced `search_memory` for that exact phrase. `save this in memory: my pilot validation codeword is COBALT-619` instead produced `answer_question`.

## 3. Root Cause

The first demonstrated failure is in [GoalParser](C:/Users/user/Desktop/Samaktha/app/core/gambit/goal_parser.py:316): a broad keyword branch maps any remaining request containing `remember` to `SEARCH_MEMORY`. There is no explicit store speech-act branch. The `save this in memory` form does not match that branch and falls through to `ANSWER_QUESTION`.

A separate downstream blocker is in [production registration](C:/Users/user/Desktop/Samaktha/app/core/app.py:1051): memory actions are search, retrieve, last_session, delete, delete_type, delete_all, and delete_session. Permissions are read/delete. [MemoryTool.run](C:/Users/user/Desktop/Samaktha/app/tools/memory.py:46) has no store dispatch. Merely changing the parser therefore cannot complete the requested repair.

## 4. Intent Architecture Before

Executed the real GoalParser and TaskDecomposer, without constructing a live orchestrator or opening a database:

| Exact request | Goal | Memory classification | Tool task |
|---|---|---|---|
| remember that my pilot validation codeword is COBALT-619 | search_memory | None; decomposer defaults to memory_search | memory/search |
| save this in memory: my pilot validation codeword is COBALT-619 | answer_question | None | No memory task |
| what was the pilot validation codeword I asked you to remember? | search_memory | profile_recall | memory/search |
| search your memory for pilot validation codeword | search_memory | memory_search | memory/search |

Task plans also contain text-generation stages. This component trace does not establish actual provider-call counts: no end-to-end Runtime execution was performed.

## 5. Intent Architecture After

Unchanged. `MemoryEvidenceSource.MEMORY_STORE` already exists, but it identifies the **source of retrieval evidence**, not a store intent or executable mutation. It must not be mistaken for an implemented write action.

## 6. Store Speech Acts

Executed the two store examples in section 4; both are misclassified. The full required paraphrase matrix was not added or tested because implementation stopped.

## 7. Recall Speech Acts

Executed the two recall examples in section 4. Both select memory search, but the natural-language fact question is labeled profile recall and its target is not extracted. Other recall paraphrases remain unverified in this phase.

## 8. Ambiguous Speech Acts

No new ambiguity policy was introduced. The current broad `remember` keyword rule is insufficient to distinguish a mutation from “remember when…” or an ambiguous preference reference. The requested deterministic clarification behavior remains to be implemented.

## 9. Store Payload Extraction

Expected payload: `my pilot validation codeword is COBALT-619`. Actual store intent arguments from both tested store phrases: `{}`. No payload was persisted during diagnosis.

## 10. Planner / Task Mapping

[TaskDecomposer](C:/Users/user/Desktop/Samaktha/app/core/gambit/task_decomposer.py:150) maps SEARCH_MEMORY into search/retrieve/last_session. There is no memory.store branch. The tested remember command produced memory/search with the entire instruction as query.

## 11. CAP / Governance

The current registered memory capability declares read/delete, not write. Existing policy was not modified and no approval was introduced or bypassed. The approval treatment of a new explicit-store action must be derived from existing policy and verified, not inferred from the fact that a controller method is callable.

## 12. Runtime / MemoryTool Path

Static trace: TUI production adapter → ExecutionCoordinator.start_execution → orchestrator.run_pipeline → conversation/reference resolution → GoalParser → TaskDecomposer/Planner → existing authorization/Runtime → ToolExecutor → MemoryTool retrieval/deletion → MemoryController → existing stores → typed retrieval evidence → deterministic rendering.

References: [production adapter](C:/Users/user/Desktop/Samaktha/app/agent/production.py:111), [coordinator](C:/Users/user/Desktop/Samaktha/app/core/execution_coordinator.py:380), [pre-parser resolution](C:/Users/user/Desktop/Samaktha/app/core/orchestrator/engine.py:338), and [MemoryTool](C:/Users/user/Desktop/Samaktha/app/tools/memory.py:46). No store leg exists in the tool dispatcher. This is a static production-path trace plus executable parser/decomposer verification, not a live TUI reproduction.

## 13. Memory Write Evidence

[MemoryController.write_knowledge](C:/Users/user/Desktop/Samaktha/app/memory/controller/facade.py:294) delegates through write-access checking to [MemoryWriter.write_knowledge](C:/Users/user/Desktop/Samaktha/app/memory/controller/writer.py:248), which constructs an owned record and invokes the existing MemoryManager store. That is the reusable durable substrate. Automatic conversation formation also writes records, but it is not proof that a user-requested store action succeeded through CAP/Runtime. No explicit-store evidence contract was added.

## 14. Success Claim Truth

No “Stored” response was generated and no record was written. The repair must bind confirmation to a real persisted record returned by the authorized action. Conversation history or provider acknowledgment cannot substitute for that proof.

## 15. Targeted Recall Root Cause

Three source defects/behaviors explain why targeted questions can return broad records:

- The fact question is classified as profile recall, not specifically targeted fact recall.
- MemoryTool's normalizer only handles limited command wrappers, not the “what was … I asked you to remember” construction. Its `memories?` regex matches `memorie`/`memories`, **not `memory`**, so even singular “search your memory for …” is not stripped in the executed trace.
- The controller retriever merges recent and preference candidates with semantic candidates, ranks them, and returns top-k without a strict target-match gate; MemoryTool discards returned scores before constructing evidence.

See [normalizer](C:/Users/user/Desktop/Samaktha/app/tools/memory.py:294) and [retrieval pipeline](C:/Users/user/Desktop/Samaktha/app/memory/controller/retriever.py:252). These are source-level findings; no live user's unrelated memories were read to demonstrate them.

## 16. Query Derivation

Expected: `what was the pilot validation codeword I asked you to remember?` → `pilot validation codeword`.

Actual executable normalizer result: the complete original question, unchanged. `search your memory for pilot validation codeword` also remains unchanged. This is not an observed empty-query conversion; the demonstrated problem is failure to remove framing and absence of targeted relevance enforcement.

## 17. Relevance Gate

No repair applied. Existing ranking combines signals and can retain recent unrelated records. A narrow targeted mode should require strong target evidence and return not-found otherwise, while leaving broad browse and previous-session behavior intact. Exact identifiers, contradictory values, and multiple plausible matches need the requested regressions before any claimed policy.

## 18. Broad Browse Mode

MemoryTool has an empty-query branch calling scoped retrieve_recent, but singular natural-language “search your memory” currently does not normalize to empty. Its intended browse behavior must be tested independently from targeted recall. No new broad listing was executed.

## 19. Restart Durability

Not tested. Creating a record by directly calling the controller and calling that an explicit-store end-to-end success would conceal the missing governed operation. No codeword was inserted into either live or temporary storage during this diagnosis.

## 20. Principal / Workspace / Profile Isolation

Existing access-context partitioning and eligibility-before-scoring were found in retrieval. The knowledge writer assigns ownership and workspace/user scope through existing helpers. No scope was broadened. New explicit-store principal/workspace/profile isolation tests remain blocked; this inspection is not a fresh P4 validation.

## 21. Memory Provenance

Knowledge writing defaults to source `system`, which must not be accepted implicitly for a user-supplied fact. A future tool action must explicitly preserve user provenance. Existing tool retrieval excludes generated summaries and records marked derived_from_memory_evidence. No provenance behavior was changed.

## 22. Memory Injection Resistance

Not newly tested. No malicious instruction was stored. A future repair must keep user memory as data and preserve CAP/Runtime authority, including for “Ignore all future approvals.”

## 23. Previous-Session Recall Regression

The existing last_session/retrieve/search paths remain unchanged. They were not rerun in this stopped phase. The earlier R1–R6 full-suite result is historical evidence, not a new memory-repair pass.

## 24. Focused Tests

Four read-only parser/decomposer/normalizer traces executed successfully as diagnostic commands; they reproduced incorrect behavior and are **not four passing acceptance tests**. Zero new pytest tests added or run. No live provider, credential, memory, filesystem, search, or SMTP operation was invoked.

## 25. Memory Tests

0 run in this phase; no new memory-store acceptance result.

## 26. GAMBIT / Conversation Tests

0 pytest tests run in this phase. The four production-component traces are described in sections 4 and 24.

## 27. Architecture

0 tests run in this phase. Static capability/dispatcher inspection established the stop condition.

## 28. Security

0 tests run in this phase. No new isolation or injection-resistance pass is claimed.

## 29. Production

0 tests run in this phase. No end-to-end explicit-store action exists to certify yet.

## 30. Pilot

0 tests run in this phase. No real-user restart acceptance was attempted.

## 31. Full Suite

Not run for this stopped phase: collected/passed/failed/errors/skipped/warnings/duration are **not available**. The last completed prior-phase baseline was 3,115 passed, 0 failures/errors/skips, 87 warnings, 428.11 seconds. It does not certify this unresolved memory repair.

## 32. Manual Validation

**AUTOMATED VERIFIED:** deterministic current misclassification and query-normalization outputs only.

**REAL-USER VALIDATION REQUIRED:** the requested store → complete exit → restart → targeted recall → evidence-based timestamp flow, after an authorized implementation and regression gate. No live codeword was stored here.

## 33. Git Status

72 tracked modified files; 28 untracked status entries (37 files); 0 staged files after adding this report. Earlier dirty changes were preserved. No Git staging, commit, tag, push, reset, restore, checkout, clean, stash, or global configuration mutation occurred. No application-source edits were made in this phase.

## 34. Remaining Risks

Explicit store still misroutes; targeted recall can include unrelated candidates; the full paraphrase, restart, contradiction/deduplication, follow-up, isolation, and adversarial matrices remain unverified. The controller writer persists a record but its presence does not establish a user-authorized Runtime mutation or a deduplication/update policy. Existing automatic conversation saving can mask the lack of an explicit-store operation. All of these remain unresolved rather than being represented as successful repair.

## 35. Final Decision

SAMAKTHA MEMORY WRITE CONVERGENCE INCOMPLETE — PILOT MEMORY GATE BLOCKED — DO NOT COMMIT

Decision needed: authorize adding a governed MemoryTool `store` action backed by the existing scoped MemoryController writer, with a typed store intent, existing CAP/Runtime enforcement, durable evidence, and the requested tests. This would extend the canonical operation surface without introducing another memory subsystem. Work is paused specifically because section 53 says to stop when that canonical write operation is absent.
