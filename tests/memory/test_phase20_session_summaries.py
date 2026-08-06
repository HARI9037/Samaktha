"""Phase 20 regression tests for deterministic session summaries."""

from app.memory.session_manager import SessionManager


def test_session_save_populates_topic_summary(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=lambda: "2026-08-03T10:00:00+00:00")
    session = manager.create_session(title="Phase 19 Review")
    manager.add_memory_entry(session.session_id, "topic", "governance architecture", "fact")
    manager.add_memory_entry(session.session_id, "plan", "planned phase 20", "fact")

    loaded = manager.load_session(session.session_id)
    assert loaded.metadata.topic_summary
    assert "Phase 19 Review" in loaded.metadata.topic_summary
    assert "fact: topic" in loaded.metadata.topic_summary


def test_session_markdown_includes_topics(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=lambda: "2026-08-03T10:00:00+00:00")
    session = manager.create_session(title="Memory audit")
    manager.add_memory_entry(session.session_id, "topic", "previous session retrieval", "fact")

    markdown = (tmp_path / "sessions" / session.session_id / "session_memory.md").read_text(encoding="utf-8")
    assert "Topics:" in markdown
    assert "previous session retrieval" in markdown
