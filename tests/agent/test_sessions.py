"""Tests for Samaktha Agent Session Manager."""

from app.agent.config import AgentConfig
from app.agent.session import SessionManager

def test_create_session():
    config = AgentConfig()
    manager = SessionManager(config)
    state = manager.create_session()
    
    assert state.session_id.startswith("session-")
    assert state.selected_provider == "local"
    assert "created_at" in state.timestamps
    assert "last_active" in state.timestamps
    assert len(state.history) == 0

def test_get_session():
    config = AgentConfig()
    manager = SessionManager(config)
    state = manager.create_session()
    
    # Retrieve should update last_active
    retrieved = manager.get_session(state.session_id)
    assert retrieved is not None
    assert retrieved.session_id == state.session_id
    
    missing = manager.get_session("non-existent")
    assert missing is None

def test_archive_and_resume_session():
    config = AgentConfig()
    manager = SessionManager(config)
    state = manager.create_session()
    sid = state.session_id
    
    # Archive
    archived = manager.archive_session(sid)
    assert archived is True
    assert manager.get_session(sid) is None
    
    # Resume
    resumed = manager.resume_session(sid)
    assert resumed is not None
    assert resumed.session_id == sid
    assert manager.get_session(sid) is not None
