# Phase 11.8 — Memory-Retrieval Stabilization Audit — Final Report

Date: 2026-08-02

Scope: Defensive audit of the memory-retrieval pipeline only. No new RAG,
embeddings, vector search, Knowledge Router, MemoryController redesign,
learning systems, or architecture changes. No changes were committed; this
report is the phase deliverable.

---

## 1. Pipeline audited

```
USER QUERY
   ↓
MemoryController.retrieve()                 app/memory/controller/facade.py:300
   ↓  (delegates to MemoryRetriever.retrieve)
retrieval cache lookup (key = query:top_k:session_id:include_flags)
   ↓
MemoryRetriever stages                       app/memory/controller/retriever.py
   ├─ _retrieve_recent      (recent memories, newest first)
   ├─ _retrieve_semantic    (TF-IDF SemanticIndex via _DefaultSemanticEngine)
   ├─ _retrieve_skills      (SkillMemoryStore via find_relevant_skills)
   ├─ _retrieve_preferences (type="preference", full-store scan)
   └─ _retrieve_documents   (DocumentMemoryStore via search_documents)
   ↓
merge (max 6 per type)
   ↓
MemoryRanker.rank                           app/memory/controller/ranker.py
   semantic .40 | recency .25 | importance .20 | confidence .10 | frequency .05
   ↓
dedupe by id → top_k
   ↓
MemoryVisibilityPolicy.evaluate            app/personality/memory_visibility.py
   gates retrieved_memories → visible_memories + visibility summary
   ↓
PromptComposer.compose (identity/behavior/context/memory/task sections)
   ↓
build_provider_messages → Runtime → LLM
```

Single consumer besides docs: `SamakthaOrchestrator._retrieve_memory_items`
(`app/core/orchestrator/engine.py:608`). Post-interaction writes flow through
`MemoryFormationEngine.ingest` → `MemoryController` (and the orchestrator's
`_persist_documents_to_memory` / `ConversationStateManager.record_outputs`).

The pipeline is fully deterministic and local (TF-IDF cosine over
`[a-z0-9]`-tokenized text, no network, no embeddings).

## 2. Bugs found, root cause, fix

### Bug A — stale retrieval cache after writes (determinism)
**Root cause:** `MemoryCache._retrieval_cache` is keyed by query only and was
populated on every `retrieve` (`store_retrieval`); several controller write
paths never invalidated it, so a second `retrieve` after a new write returned
the identical cached list.
**Fix:** `MemoryController` now calls `self._cache.clear_retrievals()` after
every write (`write_conversation`, `write_document`, `write_preference`,
`write_workflow`, `write_tool`, `write_knowledge`, `write_system`).

### Bug B — semantic hits outside the recent-100 window dropped
**Root cause:** the semantic stage only re-materialized items that were still
present in the cached recent-100 list, so the semantic slope to older items
was silently discarded.
**Fix:** `_retrieve_semantic` now hydrates a hit not in the cache from the full
store via the new `MemoryManager.get_context_item(id)` →
`ContextMemoryStore.get(id)` path (`app/memory/context.py`, `manager.py`).

### Bug C — preferences scanned only from recent-50
**Root cause:** `_retrieve_preferences` scanned `list_cached_memories()` or fell
back to `get_recent_context(n=50)`. A preference written before many unrelated
conversations was invisible even though the store still held it.
**Fix:** `_retrieve_preferences` now scans the full store by type via
`MemoryManager.get_context_items_by_type("preference", n=50)` →
`ContextMemoryStore.get_by_type` (newest first, deterministic ordering). This is
the only recovery path for queries like "Do you remember my preferences?" whose
words share no tokens with preference content.

### Bug D — recent stage returned the oldest cache slice
**Root cause:** `_BoundedDict` is insertion-ordered oldest-first, but
`_retrieve_recent` returned `cached[:top_k_recent]` — i.e. the OLDEST cached
items instead of the newest.
**Fix:** `_retrieve_recent` now returns `list(reversed(cached[-top_k_recent:]))`
(newest slice, newest first) and filters `None` entries left by deletes.

### Bug E — retrieval cache-key collision across include flags
**Root cause:** `include_recent/semantic/skills/preferences/documents` were not
part of the cache key, so two calls with different flags collided on the same
stale result.
**Fix:** cache key is now
`f"{query}:{top_k}:{session_id}:{include_flags}"` (`retriever.py:187`).

Supporting change: `get_recent_context` and `get_by_type` sort by
`(created_at, id)` so ordering is deterministic when many items share a
created-at microsecond.

## 3. Execution traces (5 test queries)

All traces ran against `MemoryManager(InMemoryStore)` + `MemoryController` in
`C:\Users\user\AppData\Local\Temp\opencode\` (`trace_retrieval.py`,
`trace_bug_b.py`, `trace_bug_c.py`, `trace_order2.py`, `trace_rules.py`).

- **"What do you know about me?"** → visibility Rule 3 exposes
  preference/workflow/project/knowledge/conversation; 6 visible / 1 suppressed.
- **"What did we discuss yesterday?"** → Rule 5 continuation-class query.
- **"What projects am I working on?"** → Rule 8 exposes project + workflow.
- **"Do you remember my preferences?"** → semantic engine scores 0 for all
  items; preference stage alone recovers the stored preference (Bug C trace).
- **"Continue the previous discussion."** → Rule 5 suppresses preferences,
  exposes workflow/project.

Bug probes after fix:

```
BUG-B trace:  old-pref id=…  contained in results: True   total retrieved: 8
BUG-C trace:  preference found via preference stage: True (semantic matches: [])
BUG-D trace:  returned Conversation 14…5 (newest first), previously 0…9
BUG-E trace:  semantic=ON ids=[quantum] vs semantic=OFF ids=[] → no collision
BUG-A trace:  after 1st write [id1] vs after 2nd write [id1, id2] → fresh
```

## 4. Hallucination boundary (Part 8)

Verified for all 5 test queries: every retrieved item id is present in the
store (`mgr.get_recent_context(n=1000)`); retrieval never invents content.
The visibility layer can only suppress or pass through retrieved items — it
cannot synthesize memory text into the prompt.

## 5. Files modified

Application code:

- `app/memory/controller/facade.py` — `clear_retrievals()` after every typed
  write (Bug A).
- `app/memory/controller/retriever.py` — cache key includes flags (Bug E);
  `_retrieve_recent` newest-first + `None` filter (Bug D); `_retrieve_semantic`
  full-store hydration (Bug B); `_retrieve_preferences` full-store type scan
  (Bug C); `retrieve_semantic_only` full-store hydration.
- `app/memory/context.py` — new `get(id)` and `get_by_type(type, n)`;
  deterministic `(created_at, id)` sort.
- `app/memory/manager.py` — new `get_context_item(id)` and
  `get_context_items_by_type(type, n)`.

Test code:

- `tests/memory/test_phase118_retrieval_stability.py` — NEW regression suite
  (5 tests, one per fix).

## 6. Regression tests (Part 10)

| Test | Pins |
|------|------|
| `test_bug_a_retrieve_fresh_after_write` | write then retrieve returns fresh results |
| `test_bug_b_semantic_hit_beyond_recent_cache` | semantic hit older than recent-100 found |
| `test_bug_c_preference_beyond_recent_50` | preference older than recent-50 found |
| `test_bug_d_recent_stage_returns_newest_first` | recent stage returns newest slice, newest first |
| `test_bug_e_cache_key_respects_include_flags` | cache respects include_* flags |

## 7. Final test results

- Memory/personality/gambit suites: **408 passed**.
- Controller/retriever-adjacent suites: **137 passed**.
- Phase 11.8 regression suite: **5 passed**.
- Full suite: **1192 passed, 0 failed** (149.4 s). The 4 OCR tests previously
  failing in this environment now pass.

## 8. Production-stability confirmation

- Retrieval is deterministic and local; no network, no embeddings.
- Writes always invalidate the retrieval cache → reads are fresh.
- Semantic and preference recovery no longer depend on recency windows.
- Every item surfaced to the prompt exists in the store (hallucination
  boundary enforced).
- No git commit made, per phase policy.

## 9. Recommendation log

1. **Commit.** Phase 11.5–11.8 work remains uncommitted; commit after review.
2. **Refresh-recent window drift:** the recent cache is write-hydrated and
   bounded at 100; the semantic/preference stages now bypass it, so consider
   making the recent stage read the store directly when cache staleness vs
   freshness is preferred over speed.
3. **CI OCR.** Install an OCR engine to make the 4 OCR tests stable on CI.
