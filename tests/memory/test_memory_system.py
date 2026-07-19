import pytest
from datetime import datetime

from app.core.cap.context_engine import ContextEngine
from app.core.contracts.conversation import ContextRequest, ConversationMessage, MessageRole
from app.core.contracts.policy import PrivacyCategory
from app.memory import InMemoryStore, MemoryEntry, MemoryManager


def test_memory_entry_creation():
    entry = MemoryEntry(id="1", key="test.key", value="test value", category="internal")
    assert entry.key == "test.key"
    assert entry.value == "test value"
    assert isinstance(entry.created_at, datetime)
    assert isinstance(entry.updated_at, datetime)


def test_memory_store_write_read():
    store = InMemoryStore()
    entry = MemoryEntry(id="1", key="user.theme", value="dark", category="internal")
    store.store_entry(entry)
    
    retrieved = store.retrieve_entry("user.theme")
    assert retrieved is not None
    assert retrieved.value == "dark"


@pytest.mark.asyncio
async def test_memory_manager_operations():
    store = InMemoryStore()
    manager = MemoryManager(store)
    
    await manager.write("pref.lang", "en", "personal")
    
    record = await manager.read("pref.lang")
    assert record is not None
    assert record.key == "pref.lang"
    assert record.content == "en"
    assert record.category == PrivacyCategory.PERSONAL
    
    # Test update
    await manager.write("pref.lang", "es", "personal")
    record_updated = await manager.read("pref.lang")
    assert record_updated.content == "es"
    
    # Test search
    results = await manager.search("es")
    assert len(results) == 1
    assert results[0].key == "pref.lang"


@pytest.mark.asyncio
async def test_delete_operation():
    store = InMemoryStore()
    manager = MemoryManager(store)
    
    await manager.write("temp.data", "value")
    assert await manager.read("temp.data") is not None
    
    await manager.delete("temp.data")
    assert await manager.read("temp.data") is None


@pytest.mark.asyncio
async def test_cap_can_read_memory():
    store = InMemoryStore()
    manager = MemoryManager(store)
    await manager.write("user.name", "Alice")
    
    engine = ContextEngine(memory_reader=manager)
    request = ContextRequest(
        session_id="session1",
        user_id="user1",
        messages=[ConversationMessage(role=MessageRole.USER, content="what is my name?")],
        memory_keys=["user.name"]
    )
    
    context = await engine.build(request)
    assert len(context.retrieved_memories) == 1
    assert context.retrieved_memories[0].key == "user.name"
    assert context.retrieved_memories[0].content == "Alice"
