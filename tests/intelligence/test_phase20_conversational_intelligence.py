"""Phase 20 conversational intelligence regressions."""

from app.intelligence.retrieval import RetrievalEngine
from app.memory.controller.facade import MemoryController
from app.memory.manager import MemoryManager
from app.memory.session_manager import SessionManager
from app.personality import IntentEngine
from app.personality.models import ConversationIntent


def _sessions(tmp_path):
    return SessionManager(base_dir=tmp_path, clock=lambda: "2026-08-03T10:00:00+00:00")


def test_previous_session_queries_classify_as_memory_recall():
    engine = IntentEngine()
    for phrase in (
        "what did we discuss in the previous session",
        "continue where we left off",
        "summarize previous session",
        "what were we working on",
    ):
        assert engine.classify(phrase) == ConversationIntent.MEMORY_RECALL


def test_cross_session_retrieval_prefers_session_summary(tmp_path):
    sessions = _sessions(tmp_path)
    first = sessions.create_session(session_id="session-a", title="Phase 19 Review")
    sessions.add_memory_entry(first.session_id, "topic", "Compared Samaktha with Hermes and OpenClaw", "fact")
    sessions.update_metadata(first.session_id, summary="Reviewed governance architecture")
    controller = MemoryController(MemoryManager())
    retrieval = RetrievalEngine(controller, session_manager=sessions)

    bundle = retrieval.assemble_context("what did we discuss in the previous session", session_id="session-b")
    assert any(item.source == "session_summary" for item in bundle.evidence)
    assert any("Reviewed governance architecture" in item.content or "Phase 19 Review" in item.content for item in bundle.evidence)


def test_retrieval_provenance_is_available(tmp_path):
    sessions = _sessions(tmp_path)
    session = sessions.create_session(session_id="session-a")
    sessions.add_memory_entry(session.session_id, "topic", "Planned Phase 20", "fact")
    controller = MemoryController(MemoryManager())
    retrieval = RetrievalEngine(controller, session_manager=sessions)

    result = retrieval.retrieve("continue previous conversation", session_id="session-b")
    evidence = result.evidence[0]
    assert evidence.provenance
    assert evidence.confidence >= 0
