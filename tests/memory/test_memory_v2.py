import asyncio
import os
import shutil
import pytest
from app.memory.sqlite_store import SQLiteStore
from app.memory.manager import MemoryManager
from app.memory.models import MemoryEntry
from app.memory.repository import MemoryRepository
from app.core.cap.context_engine import ContextEngine
from app.core.contracts.conversation import ContextRequest, ConversationMessage, MessageRole

DB_PATH = 'data/memory.db'
TMP_DB_PATH = 'data/memory_test.db'

@pytest.fixture(scope="function", autouse=True)
def clean_test_db():
    # set up a temp db file
    if os.path.exists(TMP_DB_PATH):
        os.remove(TMP_DB_PATH)
    yield
    if os.path.exists(TMP_DB_PATH):
        os.remove(TMP_DB_PATH)


def get_manager():
    store = SQLiteStore(db_path=TMP_DB_PATH)
    repo = MemoryRepository(store=store)
    return MemoryManager(repository=repo)


def test_sqlite_store_initializes():
    store = SQLiteStore(db_path=TMP_DB_PATH)
    entries = store.list_entries()
    assert isinstance(entries, list)
    assert len(entries) == 0

@pytest.mark.asyncio
async def test_write_and_read_across_managers():
    mgr1 = get_manager()
    await mgr1.write("name", "Samaktha", "project")
    # mgr2 simulates a new app instance
    mgr2 = get_manager()
    record = await mgr2.read("name")
    assert record is not None
    assert record.key == "name"
    assert record.content == "Samaktha"
    assert record.category.value == "project"

@pytest.mark.asyncio
async def test_delete_works():
    mgr = get_manager()
    await mgr.write("key1", "to-delete")
    assert await mgr.read("key1") is not None
    await mgr.delete("key1")
    assert await mgr.read("key1") is None

@pytest.mark.asyncio
async def test_search_works():
    mgr = get_manager()
    await mgr.write("k1", "hello samaktha", "project")
    await mgr.write("k2", "not found", "preference")
    await mgr.write("k3", "Samaktha AI core", "workflow")
    results = await mgr.search("samaktha")
    keys = {r.key for r in results}
    assert "k1" in keys and "k3" in keys and "k2" not in keys

@pytest.mark.asyncio
async def test_categories_filter():
    mgr = get_manager()
    await mgr.write("c1", "value1", "conversation")
    await mgr.write("c2", "value2", "preference")
    await mgr.write("c3", "value3", "conversation")
    conv_results = await mgr.search(category="conversation")
    pref_results = await mgr.search(category="preference")
    assert len(conv_results) == 2 and all(r.category.value == "conversation" for r in conv_results)
    assert len(pref_results) == 1 and pref_results[0].category.value == "preference"

@pytest.mark.asyncio
async def test_cap_context_engine_reads_memory():
    mgr = get_manager()
    await mgr.write("user.memory", "persistent", "internal")
    engine = ContextEngine(memory_reader=mgr)
    request = ContextRequest(
        session_id="session12",
        user_id="user11",
        messages=[ConversationMessage(role=MessageRole.USER, content="recall memory")],
        memory_keys=["user.memory"]
    )
    context = await engine.build(request)
    assert len(context.retrieved_memories) == 1
    assert context.retrieved_memories[0].key == "user.memory"
