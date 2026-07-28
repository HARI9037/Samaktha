"""Phase 5.5 tests — Private Memory.

Validates:
- Privacy flags
- Retention behavior (temporary, private, normal)
"""
from app.core.contracts.memory import MemoryItem, MemoryType
from app.core.contracts.security import SecurityLevel
from app.memory.context import ContextMemoryStore


def test_memory_temporary_retention_policy():
    store = ContextMemoryStore()
    
    temp_item = MemoryItem(content="temp", retention_policy="temporary")
    store.save_context(temp_item)
    
    # Should not be saved at all
    assert len(store) == 0
    results = store.search_context("temp")
    assert len(results) == 0


def test_memory_private_retention_policy():
    store = ContextMemoryStore()
    
    private_item = MemoryItem(
        content="my secret password is foo",
        retention_policy="private",
        privacy_level=SecurityLevel.HIGH,
        sensitive=True,
    )
    normal_item = MemoryItem(content="normal info")
    
    store.save_context(private_item)
    store.save_context(normal_item)
    
    assert len(store) == 2
    
    # By default, private items are filtered out in search
    search_results = store.search_context("secret")
    assert len(search_results) == 0
    
    # But they can be retrieved if explicitly requested
    private_search_results = store.search_context("secret", allow_private=True)
    assert len(private_search_results) == 1
    
    # Same for get_recent_context
    recent = store.get_recent_context()
    assert len(recent) == 1
    assert recent[0].content == "normal info"
    
    recent_all = store.get_recent_context(allow_private=True)
    assert len(recent_all) == 2
