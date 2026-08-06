"""Phase 11.8 — Retrieval-stability regression tests.

Each test pins one bug found during the memory-retrieval stabilization
audit (Phase 11.8).  One regression test per fix:

    Bug A — write-then-retrieve freshness: the retrieval cache was only
            invalidated on some write paths, so a second retrieve after a
            new write could return a stale cached list.
    Bug B — semantic hits outside the recent-100 cache window were silently
            dropped because the semantic stage only re-materialized items
            found in the cached recent list.
    Bug C — preferences were scanned only from recent-50 memories, so a
            preference written before many unrelated conversations was
            invisible even though the full store still held it.
    Bug D — the recent stage returned the OLDEST cached slice (cache is
            insertion-ordered oldest-first) instead of the newest.
    Bug E — the retrieval cache key omitted the include_* flags, so calls
            with different flags collided on the same cached result.
"""

import re

from app.memory.controller.facade import MemoryController
from app.memory.manager import MemoryManager
from app.memory.store import InMemoryStore


def build():
    mgr = MemoryManager(store=InMemoryStore())
    return mgr, MemoryController(mgr)


def _ids(results):
    return {str(getattr(item, "id", None)) for item, _ in results}


def _contents(results):
    return [str(getattr(item, "content", "")) for item, _ in results]


def _item_contents(items):
    return [str(getattr(item, "content", "")) for item in items]


def _conv_number(content: str) -> int:
    return int(re.search(r"Conversation (\d+)", content).group(1))


# ---------------------------------------------------------------------------
# Bug A — write invalidation of the retrieval cache
# ---------------------------------------------------------------------------


def test_bug_a_retrieve_fresh_after_write():
    mgr, ctl = build()
    ctl.write_conversation("Talk about linux")

    first = ctl.retrieve(query="about", top_k=5)
    first_ids = _ids(first)

    pref = ctl.write_preference("User prefers Linux over Windows")
    second = ctl.retrieve(query="about", top_k=5)
    second_ids = _ids(second)

    assert first_ids != second_ids, "retrieve returned stale cached results after a write"
    assert pref.id in second_ids, "newly written preference missing from fresh retrieval"


# ---------------------------------------------------------------------------
# Bug B — semantic hits beyond the recent-100 cache window
# ---------------------------------------------------------------------------


def test_bug_b_semantic_hit_beyond_recent_cache():
    mgr, ctl = build()
    old = ctl.write_preference("User strongly prefers Go for systems programming")
    for i in range(120):
        ctl.write_conversation(f"Filler conversation number {i} about unrelated trivia")

    # Drop caches so the recent-100 window cannot mask the old item.
    ctl.clear_cache()

    results = ctl.retrieve(query="Go systems programming language preference", top_k=8)
    assert old.id in _ids(results), "semantic hit outside the recent-100 window was dropped"


# ---------------------------------------------------------------------------
# Bug C — preferences scanned only from recent-50 memories
# ---------------------------------------------------------------------------


def test_bug_c_preference_beyond_recent_50():
    mgr, ctl = build()
    old = ctl.write_preference("User prefers Vim over Emacs")
    for i in range(60):
        ctl.write_conversation(f"Another filler conversation {i}")
    ctl.clear_cache()

    # The query deliberately shares no tokens with the preference content, so
    # only the preference stage (not semantic search) can recover it.
    semantic = ctl.retriever._semantic.search("Do you remember my preferences", top_k=10)
    assert not semantic, "test premise broken: query unexpectedly matched semantically"

    results = ctl.retrieve(query="Do you remember my preferences", top_k=8)
    assert old.id in _ids(results), "old preference invisible because recent-50 scan missed it"


# ---------------------------------------------------------------------------
# Bug D — recent stage returned the oldest slice of the cache
# ---------------------------------------------------------------------------


def test_bug_d_recent_stage_returns_newest_first():
    mgr, ctl = build()
    for i in range(15):
        ctl.write_conversation(f"Conversation {i}")

    # Cache is populated and NOT cleared: this is the path that used to
    # return the oldest cached slice.
    recent = ctl.retriever._retrieve_recent(session_id=None)
    numbers = {_conv_number(c) for c in _item_contents(recent)}

    assert numbers == set(range(5, 15)), (
        f"recent stage returned stale slice {sorted(numbers)} instead of the newest 10"
    )
    assert _conv_number(_item_contents(recent)[0]) == 14, "newest item not first"


# ---------------------------------------------------------------------------
# Bug E — retrieval cache key omitted the include_* flags
# ---------------------------------------------------------------------------


def test_bug_e_cache_key_respects_include_flags():
    mgr, ctl = build()
    ctl.write_conversation("Unrelated recent chat about weather")
    for i in range(20):
        ctl.write_conversation(f"Filler number {i} with totally random trivia")
    ctl.write_conversation("Old deep note about quantum entanglement research")
    ctl.clear_cache()

    on = ctl.retrieve(
        query="quantum entanglement",
        top_k=5,
        include_recent=False,
        include_semantic=True,
    )
    off = ctl.retrieve(
        query="quantum entanglement",
        top_k=5,
        include_recent=False,
        include_semantic=False,
    )

    assert _ids(on) != _ids(off), "retrieval cache collided across different include_* flags"
    assert any("quantum" in c for c in _contents(on)), "semantic stage did not return the hit"
    assert len(off) == 0, "disabled semantic stage still returned results"
