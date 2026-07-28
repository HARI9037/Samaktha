"""Phase 4.5 tests — ContextMemoryStore behavior."""
import pytest
from app.core.contracts.memory import MemoryItem, MemoryType
from app.memory.context import ContextMemoryStore


def make_item(content: str, category: MemoryType = MemoryType.CONTEXT, **meta) -> MemoryItem:
    return MemoryItem(content=content, category=category, metadata=meta)


def test_save_and_search():
    store = ContextMemoryStore()
    store.save_context(make_item("parallel workflow execution succeeded", MemoryType.EXECUTION))
    store.save_context(make_item("python script failed due to syntax error", MemoryType.FAILURE_PATTERN))

    results = store.search_context("workflow execution")
    assert len(results) >= 1
    assert results[0].item.category == MemoryType.EXECUTION


def test_type_filter():
    store = ContextMemoryStore()
    store.save_context(make_item("python skill automation", MemoryType.SKILL))
    store.save_context(make_item("python execution workflow", MemoryType.EXECUTION))

    skill_results = store.search_context("python", memory_type=MemoryType.SKILL)
    ids = [r.item.category for r in skill_results]
    assert all(c == MemoryType.SKILL for c in ids)


def test_delete_memory():
    store = ContextMemoryStore()
    item = make_item("test workflow context")
    store.save_context(item)
    assert len(store) == 1

    store.delete_memory(item.id)
    assert len(store) == 0
    results = store.search_context("test workflow")
    assert results == []


def test_update_memory():
    store = ContextMemoryStore()
    item = make_item("initial content about execution")
    store.save_context(item)

    item.content = "updated content about parallel execution workflow"
    store.update_memory(item)

    results = store.search_context("parallel execution workflow")
    assert len(results) >= 1
    assert results[0].item.content == "updated content about parallel execution workflow"


def test_get_recent_context():
    import time
    store = ContextMemoryStore()
    for i in range(5):
        store.save_context(make_item(f"context item number {i}"))
        time.sleep(0.001)

    recent = store.get_recent_context(n=3)
    assert len(recent) == 3


def test_search_returns_scores():
    store = ContextMemoryStore()
    store.save_context(make_item("highly relevant semantic python automation skill"))
    store.save_context(make_item("unrelated database configuration"))

    results = store.search_context("python automation skill")
    assert len(results) >= 1
    for r in results:
        assert r.score > 0.0
        assert isinstance(r.matched_features, list)


def test_memory_does_not_import_runtime():
    """Architecture check: Memory layer must not import Runtime."""
    import app.memory.context as ctx_mod
    import sys
    for mod_name in sys.modules:
        if mod_name.startswith("app.runtime") and mod_name in sys.modules:
            # Ensure context module didn't pull it in
            pass
    # Check source has no runtime imports
    import inspect
    src = inspect.getsource(ctx_mod)
    assert "app.runtime" not in src
    assert "app.workflow" not in src
