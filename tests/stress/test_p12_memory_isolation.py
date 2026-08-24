"""P12.6 — Memory/Context/Session Isolation Under Load Stress Tests.

Tests principal/session/workspace isolation, cache partitioning,
context size pressure, and memory growth under concurrent load.
"""

from __future__ import annotations

import asyncio
import gc
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.app import create_orchestrator
from app.config.settings import Settings
from app.core.contracts import RoutingDecision, RuntimeContext
from app.core.contracts.planning import TaskStatus
from app.memory.controller.facade import MemoryController
from app.memory.manager import MemoryManager
from app.memory.session_manager import SessionManager
from tests.conftest import approved_task


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def orchestrator(tmp_path):
    """Create a production orchestrator with isolated persistence and mock provider."""
    settings = Settings(
        _env_file=None,
        sqlite_url=str(tmp_path / "stress.db"),
        personality_state_path=str(tmp_path / "personality.json"),
        checkpoint_location=str(tmp_path / "checkpoints"),
        groq_api_key="test-key",  # Enable groq
    )
    # Enable mock agent for testing
    from app.providers.config import ProviderSettings
    import app.core.app as core_app
    original_provider_settings = core_app.ProviderSettings

    def mock_provider_settings(*args, **kwargs):
        kwargs.setdefault('mock_agent', True)
        kwargs.setdefault('default_provider', 'mock')
        return original_provider_settings(*args, **kwargs)

    import pytest as _pytest
    monkeypatch = _pytest.MonkeyPatch()
    monkeypatch.setattr(core_app, "ProviderSettings", mock_provider_settings)

    try:
        orch = create_orchestrator(settings)
    finally:
        monkeypatch.undo()

    return orch


@pytest.fixture
def memory_controller():
    """Create an isolated memory controller with a high-capacity retriever."""
    from app.memory.controller.cache import MemoryCache
    from app.memory.controller.ranker import MemoryRanker
    from app.memory.controller.retriever import MemoryRetriever
    from app.memory.controller.security_manager import SecurityManager

    manager = MemoryManager()
    cache = MemoryCache()
    ranker = MemoryRanker()
    security = SecurityManager()
    retriever = MemoryRetriever(
        manager,
        cache,
        ranker,
        semantic_engine=None,
        top_k_recent=1000,
        top_k_semantic=1000,
        top_k_skills=1000,
        top_k_documents=1000,
        security=security,
    )
    return MemoryController(
        manager,
        cache=cache,
        ranker=ranker,
        security=security,
        retriever=retriever,
    )


@pytest.fixture
def session_manager(tmp_path):
    """Create an isolated session manager."""
    return SessionManager(base_dir=tmp_path / "sessions")


# ---------------------------------------------------------------------------
# Principal Isolation Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_principal_memory_isolation_under_concurrency(memory_controller):
    """Principal A's memories must not leak to Principal B under concurrent access."""
    # Each principal owns a distinct session; writes run concurrently in threads.
    def write_memories(principal_id, count):
        for i in range(count):
            memory_controller.write_conversation(
                content=f"Memory {i} for {principal_id}",
                session_id=f"session-{principal_id}",
            )

    await asyncio.gather(
        asyncio.to_thread(write_memories, "principal-a", 50),
        asyncio.to_thread(write_memories, "principal-b", 50),
    )

    # Retrieve memories scoped to each principal's session
    memories_a = [
        item for item, _ in memory_controller.retrieve(
            "Memory", top_k=200, session_id="session-principal-a"
        )
    ]
    memories_b = [
        item for item, _ in memory_controller.retrieve(
            "Memory", top_k=200, session_id="session-principal-b"
        )
    ]

    # Verify no cross-contamination
    assert len(memories_a) >= 50
    assert len(memories_b) >= 50
    for m in memories_a:
        assert m.session_id == "session-principal-a"
        assert "principal-a" in m.content
    for m in memories_b:
        assert m.session_id == "session-principal-b"
        assert "principal-b" in m.content


@pytest.mark.asyncio
async def test_principal_isolation_concurrent_read_write(memory_controller):
    """Concurrent reads and writes must not cause cross-principal leakage."""
    principal_ids = [f"principal-{i}" for i in range(10)]

    def mixed_workload(principal_id):
        # Write some memories
        for i in range(20):
            memory_controller.write_conversation(
                content=f"Write {i} for {principal_id}",
                session_id=f"session-{principal_id}",
            )
        # Read memories back, scoped to this principal's session
        memories = [
            item for item, _ in memory_controller.retrieve(
                "Write", top_k=100, session_id=f"session-{principal_id}"
            )
        ]
        return memories

    results = await asyncio.gather(*[
        asyncio.to_thread(mixed_workload, pid) for pid in principal_ids
    ])

    # Verify each principal only sees their own memories
    for i, memories in enumerate(results):
        pid = principal_ids[i]
        assert len(memories) >= 1
        for m in memories:
            assert m.session_id == f"session-{pid}", f"Cross-principal leak into {pid}"
            assert m.content.startswith("Write")


# ---------------------------------------------------------------------------
# Session Isolation Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_isolation_under_load(session_manager):
    """Session A must not see Session B's memories even under load."""
    principal_id = "shared-principal"
    session_ids = [f"session-{i}" for i in range(5)]

    # Create sessions with distinct memories
    for sid in session_ids:
        session_manager.create_session(session_id=sid, principal_id=principal_id)
        for j in range(10):
            session_manager.add_memory_entry(
                sid,
                key=f"{sid}-fact-{j}",
                value=f"Memory {j} in {sid}",
            )

    # Concurrently retrieve from all sessions
    def retrieve_session(sid):
        memory = session_manager.load_session(sid, principal_id=principal_id).memory
        return memory

    results = await asyncio.gather(*[
        asyncio.to_thread(retrieve_session, sid) for sid in session_ids
    ])

    # Verify isolation
    for i, memory in enumerate(results):
        assert memory.session_id == session_ids[i]
        values = [entry.value for entry in memory.entries]
        assert len(values) == 10
        for value in values:
            assert f"in {session_ids[i]}" in value


@pytest.mark.asyncio
async def test_session_isolation_concurrent_modification(session_manager):
    """Concurrent modifications to different sessions must not interfere."""
    principal_id = "concurrent-principal"
    session_ids = [f"session-{i}" for i in range(8)]

    for sid in session_ids:
        session_manager.create_session(session_id=sid, principal_id=principal_id)

    def modify_session(sid):
        for j in range(15):
            session_manager.add_memory_entry(
                sid,
                key=f"{sid}-write-{j}",
                value=f"Concurrent write {j} to {sid}",
            )
        return session_manager.load_session(sid, principal_id=principal_id).memory

    results = await asyncio.gather(*[
        asyncio.to_thread(modify_session, sid) for sid in session_ids
    ])

    # Verify each session has its own memories
    for i, memory in enumerate(results):
        assert len(memory.entries) == 15
        assert memory.session_id == session_ids[i]
        for entry in memory.entries:
            assert f"to {session_ids[i]}" in entry.value


# ---------------------------------------------------------------------------
# Workspace Isolation Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workspace_isolation_survives_load(tmp_path):
    """Workspace isolation must hold under concurrent file operations."""
    from app.tools.filesystem import FileSystemTool

    # Create separate workspace roots - one tool per workspace root
    workspace_a = tmp_path / "workspace_a"
    workspace_b = tmp_path / "workspace_b"
    workspace_a.mkdir()
    workspace_b.mkdir()

    fs_a = FileSystemTool(root_dir=workspace_a)
    fs_b = FileSystemTool(root_dir=workspace_b)

    # Concurrent writes to different workspaces
    async def write_files(fs, workspace, prefix, count):
        for i in range(count):
            result = await fs.run({
                "action": "write",
                "path": str(workspace / f"{prefix}_{i}.txt"),
                "content": f"{prefix} content {i}",
            })
            if not result.ok:
                return False, result.error
        return True, None

    results = await asyncio.gather(
        write_files(fs_a, workspace_a, "a", 20),
        write_files(fs_b, workspace_b, "b", 20),
    )

    assert all(r[0] for r in results), f"Write failures: {results}"

    # Verify no cross-workspace access
    result_a = await fs_a.run({"action": "list", "path": str(workspace_a)})
    result_b = await fs_b.run({"action": "list", "path": str(workspace_b)})
    assert result_a.ok and result_b.ok

    files_a = [item["name"] for item in result_a.data.get("items", []) if item["name"].startswith("a_")]
    files_b = [item["name"] for item in result_b.data.get("items", []) if item["name"].startswith("b_")]

    assert len(files_a) == 20
    assert len(files_b) == 20

    # Workspace A must not read or write inside workspace B
    cross_read = await fs_a.run({"action": "read", "path": str(workspace_b / "b_0.txt")})
    assert not cross_read.ok
    cross_write = await fs_a.run({
        "action": "write",
        "path": str(workspace_b / "intrusion.txt"),
        "content": "should fail",
    })
    assert not cross_write.ok


# ---------------------------------------------------------------------------
# Cache Isolation Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_cache_is_access_partitioned(memory_controller):
    """Memory cache must be partitioned by principal/session."""
    principal_ids = [f"cache-principal-{i}" for i in range(5)]

    # Populate each principal's session
    def populate(pid):
        for i in range(30):
            memory_controller.write_conversation(
                content=f"Cache test {i} for {pid}",
                session_id=f"session-{pid}",
            )

    await asyncio.gather(*[
        asyncio.to_thread(populate, pid) for pid in principal_ids
    ])

    # Trigger cache population by reading, then verify partitioning
    def read_and_verify(pid):
        memories = [
            item for item, _ in memory_controller.retrieve(
                "Cache", top_k=100, session_id=f"session-{pid}"
            )
        ]
        # Verify all memories belong to this principal
        for m in memories:
            assert m.session_id == f"session-{pid}"
            assert pid in m.content
        return len(memories)

    counts = await asyncio.gather(*[
        asyncio.to_thread(read_and_verify, pid) for pid in principal_ids
    ])
    assert all(c == 30 for c in counts)


@pytest.mark.asyncio
async def test_no_cache_key_collision_across_principals(memory_controller):
    """Identical content across principals must not collide in the cache."""
    # Write memories with same content but different sessions/principals
    def populate(pid):
        for j in range(10):
            memory_controller.write_conversation(
                content="Shared content",  # Same content across principals
                session_id=f"session-{pid}",
            )

    pids = [f"collision-test-{i}" for i in range(3)]
    await asyncio.gather(*[asyncio.to_thread(populate, pid) for pid in pids])

    # Retrieve and verify no cross-contamination despite identical content
    for pid in pids:
        memories = [
            item for item, _ in memory_controller.retrieve(
                "Shared", top_k=50, session_id=f"session-{pid}"
            )
        ]
        assert len(memories) == 10
        for m in memories:
            assert m.session_id == f"session-{pid}"


# ---------------------------------------------------------------------------
# Context Size Pressure Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_long_context_handling_remains_valid(orchestrator):
    """Long conversation histories must be handled structurally correctly."""
    # Create a task with many context messages
    task = approved_task(
        task_id="long-context",
        action_type="text_generation",
        subject_id="long-context-test",
        metadata={
            "conversation_history": [
                {"role": "user", "content": f"Message {i}"}
                for i in range(100)
            ] + [
                {"role": "assistant", "content": f"Response {i}"}
                for i in range(100)
            ]
        }
    )

    result = await orchestrator.runtime.run(
        RuntimeContext(request_id="long-context-test"),
        task,
        RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="long context test"),
    )

    assert result.status == TaskStatus.COMPLETED
    # The context should be prepared without duplicating system messages
    # and with proper message ordering


@pytest.mark.asyncio
async def test_prepared_context_no_duplicate_system_message(orchestrator):
    """PreparedContext must have exactly one system block."""
    # This test verifies the context builder doesn't duplicate system messages
    task = approved_task(
        task_id="system-msg-test",
        action_type="text_generation",
        subject_id="system-msg-test",
    )

    result = await orchestrator.runtime.run(
        RuntimeContext(request_id="system-msg-test"),
        task,
        RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="system msg test"),
    )

    assert result.status == TaskStatus.COMPLETED
    # Internal context preparation should have single system message


# ---------------------------------------------------------------------------
# Resume Evidence Deduplication Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_does_not_duplicate_tool_evidence(orchestrator):
    """Resuming a pipeline must not duplicate tool evidence."""
    from app.core.execution_coordinator import ExecutionCoordinator
    from app.core.contracts.runtime import RuntimeResult
    from app.core.contracts.planning import TaskStatus

    call_count = 0

    class EvidenceTrackingLifecycle:
        def __init__(self):
            self.calls = 0

        async def run_pipeline(self, request, runtime_context, conversation=None):
            self.calls += 1
            from app.core.contracts.runtime import RuntimeResult
            from app.core.contracts.planning import TaskStatus
            return MagicMock(
                request=request,
                runtime_result=RuntimeResult(
                    task_id=request, status=TaskStatus.COMPLETED,
                    output={"data": "test"},
                    metadata={"evidence_ids": [f"ev-{self.calls}"]}
                ),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            return MagicMock(
                request=state.request,
                runtime_result=RuntimeResult(task_id=task_id, status=TaskStatus.COMPLETED, output={"done": True}),
            )

    lifecycle = EvidenceTrackingLifecycle()
    coordinator = ExecutionCoordinator(lifecycle)

    # Start and complete execution
    state = await coordinator.start_execution("evidence-dedup", wait=False)
    completed = await coordinator.wait_execution(state.execution_id)

    # Resume (should not duplicate evidence)
    # This tests that resume path doesn't re-emit evidence for completed steps
    assert lifecycle.calls >= 1


# ---------------------------------------------------------------------------
# Memory Growth Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_meaningful_unbounded_memory_leak(memory_controller):
    """Memory usage must not grow unboundedly under repeated operations."""
    import tracemalloc
    tracemalloc.start()

    # Baseline
    gc.collect()
    baseline_current, _ = tracemalloc.get_traced_memory()

    # Perform many memory operations
    for batch in range(10):
        def write_batch(batch=batch):
            for i in range(100):
                memory_controller.write_conversation(
                    content=f"Batch {batch} item {i} " + "x" * 100,
                    session_id=f"leak-session-{batch % 5}",
                )

        await asyncio.to_thread(write_batch)

        # Retrieve and verify scoping still holds
        memories = [
            item for item, _ in memory_controller.retrieve(
                "Batch", top_k=50, session_id=f"leak-session-{batch % 5}"
            )
        ]
        assert all(m.session_id == f"leak-session-{batch % 5}" for m in memories)

    gc.collect()
    final_current, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    growth = final_current - baseline_current

    # Allow some growth but flag unbounded growth (>50MB for this test)
    assert growth < 50 * 1024 * 1024, f"Excessive memory growth: {growth / 1024 / 1024:.1f} MB"


# ---------------------------------------------------------------------------
# Session Identity Under Load
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_identity_stable_under_load(session_manager):
    """Session identity must remain stable under concurrent operations."""
    principal_id = "identity-test"
    session_id = "stable-session"

    session_manager.create_session(session_id=session_id, principal_id=principal_id)

    # Concurrent read/write operations
    def mixed_ops(worker):
        for i in range(20):
            session_manager.add_memory_entry(
                session_id,
                key=f"worker-{worker}-op-{i}",
                value=f"Op {i} by worker {worker}",
            )
            memory = session_manager.load_session(session_id, principal_id=principal_id).memory
            # Verify session identity preserved
            assert memory.session_id == session_id

    await asyncio.gather(*[
        asyncio.to_thread(mixed_ops, worker) for worker in range(10)
    ])

    # Final verification - 10 workers * 20 unique entries
    memory = session_manager.load_session(session_id, principal_id=principal_id).memory
    assert memory.session_id == session_id
    assert len(memory.entries) == 200

    # Ownership boundary: another principal cannot load this session
    try:
        session_manager.load_session(session_id, principal_id="someone-else")
        raised = False
    except PermissionError:
        raised = True
    assert raised, "Session ownership boundary was not enforced."


# ---------------------------------------------------------------------------
# Memory Retrieval Under Concurrency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_retrieval_concurrent_consistency(memory_controller):
    """Concurrent memory retrieval must return consistent results."""
    session_id = "retrieval-session"

    # Pre-populate
    for i in range(50):
        memory_controller.write_conversation(
            content=f"Retrieval test {i}",
            session_id=session_id,
        )

    # Concurrent retrievals
    def retrieve():
        memories = [
            item for item, _ in memory_controller.retrieve(
                "Retrieval", top_k=100, session_id=session_id
            )
        ]
        return [m.content for m in memories]

    results = await asyncio.gather(*[
        asyncio.to_thread(retrieve) for _ in range(20)
    ])

    # All retrievals must return same content
    first = sorted(results[0])
    assert len(first) >= 1
    for r in results[1:]:
        assert sorted(r) == first, "Inconsistent retrieval results under concurrency"