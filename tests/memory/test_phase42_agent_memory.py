import pytest

from app.memory.agent_memory import AgentMemoryStore

def test_agent_memory_store_success_failure():
    store = AgentMemoryStore()
    
    store.record_agent_success("a1", "Agent 1", "planner", 100.0)
    store.record_agent_success("a1", "Agent 1", "planner", 150.0)
    store.record_agent_failure("a1", "Agent 1", "planner", 50.0)
    
    stats = store.get_agent_statistics("a1")
    assert stats is not None
    assert stats.executions == 3
    assert stats.successes == 2
    assert stats.failures == 1
    assert stats.total_duration_ms == 300.0
    
    # confidence = success / total = 2 / 3 = 0.666...
    assert round(stats.confidence_score, 2) == 0.67

def test_agent_memory_empty_confidence():
    store = AgentMemoryStore()
    record = store._ensure_record("a2", "Agent 2", "analyst")
    assert record.executions == 0
    assert record.confidence_score == 1.0

def test_agent_memory_get_all():
    store = AgentMemoryStore()
    store.record_agent_success("b", "B", "r", 1)
    store.record_agent_success("a", "A", "r", 1)
    
    all_stats = store.get_all_statistics()
    assert len(all_stats) == 2
    assert all_stats[0].agent_id == "a"
    assert all_stats[1].agent_id == "b"
