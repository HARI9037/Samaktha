"""P1.4 — session & state lifecycle tests.

Covers the P1.4 checklist:
- Conversation state persistence policy (ephemeral by design, durable record
  lives in SessionManager session memory).
- State pruning (SessionManager cache bound; ConversationStateManager
  max-sessions + idle pruning; ReminderScheduler completed-history pruning).
- Memory lifecycle boundaries (rotation → archive; cache eviction → reload).
- Expiration/archival rules (history rotation, completed-reminder retention).
- Memory growth bounded (LRU eviction on all three stores).
- Restart behavior (reload from disk after eviction; archive survives restart;
  durable pruning survives restart).
"""

from datetime import datetime, timezone, timedelta

from app.conversation.state_manager import ConversationStateManager
from app.memory.session_manager import SessionManager
from app.memory.session_models import SessionHistoryEntry
from app.tools.reminder import Reminder, ReminderScheduler


def _history_entry(index: int) -> SessionHistoryEntry:
    return SessionHistoryEntry(
        id=f"evt-{index}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        role="user",
        content=f"message {index}",
    )


def _reminder(reminder_id: str, completed: bool = True, due_in_seconds: float = 0):
    return Reminder(
        reminder_id=reminder_id,
        title=f"Reminder {reminder_id}",
        due_at=datetime.now(timezone.utc) + timedelta(seconds=due_in_seconds),
        completed=completed,
    )


# ---------------------------------------------------------------------------
# SessionManager — cache bounding / lifecycle boundaries
# ---------------------------------------------------------------------------


def test_session_cache_is_bounded_and_evicts_lru(tmp_path):
    manager = SessionManager(base_dir=tmp_path, max_cached_sessions=3)
    for i in range(5):
        manager.create_session(session_id=f"s{i}")

    assert len(manager._cache) <= 3
    # Oldest sessions evicted first (LRU).
    assert "s0" not in manager._cache
    assert "s1" not in manager._cache
    assert "s4" in manager._cache


def test_evicted_session_reloads_from_disk(tmp_path):
    manager = SessionManager(base_dir=tmp_path, max_cached_sessions=2)
    session = manager.create_session(session_id="s0")
    manager.append_history("s0", _history_entry(1))
    # Force eviction of s0.
    manager.create_session(session_id="s1")
    manager.create_session(session_id="s2")
    assert "s0" not in manager._cache

    reloaded = manager.load_session("s0")
    assert len(reloaded.memory.history) == 1
    assert reloaded.memory.history[0].content == "message 1"


def test_prune_cache_returns_count(tmp_path):
    manager = SessionManager(base_dir=tmp_path, max_cached_sessions=3)
    for i in range(6):
        manager.create_session(session_id=f"s{i}")
    before = len(manager._cache)
    assert before == 3
    assert manager.prune_cache() == 0

    manager._max_cached_sessions = 1
    removed = manager.prune_cache()
    assert removed == 2
    assert len(manager._cache) == 1


def test_unbounded_cache_when_configured(tmp_path):
    manager = SessionManager(base_dir=tmp_path, max_cached_sessions=None)
    for i in range(10):
        manager.create_session(session_id=f"s{i}")
    assert len(manager._cache) == 10


# ---------------------------------------------------------------------------
# SessionManager — history rotation / archival rules
# ---------------------------------------------------------------------------


def test_history_rotation_archives_and_survives_restart(tmp_path):
    manager = SessionManager(base_dir=tmp_path, max_history_entries=2)
    manager.create_session(session_id="rot")
    for i in range(5):
        manager.append_history("rot", _history_entry(i))

    assert len(manager.load_session("rot").memory.history) == 2

    fresh = SessionManager(base_dir=tmp_path, max_history_entries=2)
    archived = fresh.load_archived_history("rot")
    assert [e.content for e in archived] == ["message 0", "message 1", "message 2"]


# ---------------------------------------------------------------------------
# ConversationStateManager — bounded + pruning + persistence policy
# ---------------------------------------------------------------------------


def test_conversation_state_bounded_evicts_lru():
    manager = ConversationStateManager(max_sessions=2)
    manager.record_command("first", session_id="a")
    manager.record_command("second", session_id="b")
    manager.record_command("third", session_id="c")

    assert len(manager._states) == 2
    assert manager.has_state("a") is False
    assert manager.has_state("b") is True
    assert manager.has_state("c") is True


def test_prune_idle_drops_stale_states():
    manager = ConversationStateManager()
    manager.record_command("first", session_id="a")
    manager.record_command("second", session_id="b")

    fresh = datetime.now(timezone.utc)
    stale = fresh - timedelta(minutes=10)
    manager._states["a"].updated_at = stale.isoformat()

    removed = manager.prune_idle(max_age_seconds=300)
    assert removed == 1
    assert manager.has_state("a") is False
    assert manager.has_state("b") is True


def test_conversation_state_is_ephemeral_on_restart():
    manager = ConversationStateManager()
    manager.record_command("hello", session_id="s1")
    assert manager.has_state("s1")

    fresh = ConversationStateManager()
    assert fresh.has_state("s1") is False
    assert fresh.get_state("s1").last_command is None


# ---------------------------------------------------------------------------
# ReminderScheduler — completed-history pruning (durable)
# ---------------------------------------------------------------------------


def test_prune_completed_keeps_newest(tmp_path):
    scheduler = ReminderScheduler(
        db_path=str(tmp_path / "p.db"), keep_completed=3
    )
    for i in range(5):
        scheduler.add_reminder(_reminder(f"r{i}"))
        scheduler.save_reminder(scheduler.get_reminder(f"r{i}"))

    remaining = {r.id for r in scheduler.list_reminders()}
    assert remaining == {"r2", "r3", "r4"}
    assert scheduler.prune_completed() == 0

    fresh = ReminderScheduler(db_path=str(tmp_path / "p.db"), keep_completed=3)
    assert {r.id for r in fresh.list_reminders()} == {"r2", "r3", "r4"}


def test_scheduler_auto_prunes_on_save(tmp_path):
    scheduler = ReminderScheduler(
        db_path=str(tmp_path / "auto.db"), keep_completed=2
    )
    for i in range(4):
        scheduler.add_reminder(_reminder(f"r{i}"))
        scheduler.save_reminder(scheduler.get_reminder(f"r{i}"))

    completed = scheduler.list_reminders(completed=True)
    assert len(completed) == 2
    assert {r.id for r in completed} == {"r2", "r3"}


def test_active_jobs_never_pruned(tmp_path):
    scheduler = ReminderScheduler(
        db_path=str(tmp_path / "mix.db"), keep_completed=2
    )
    scheduler.add_reminder(_reminder("done1"))
    scheduler.add_reminder(_reminder("done2"))
    scheduler.add_reminder(_reminder("done3"))
    scheduler.add_reminder(_reminder("pending", completed=False, due_in_seconds=3600))

    scheduler.prune_completed()
    assert scheduler.get_reminder("pending") is not None
    assert scheduler.get_reminder("done1") is None
    assert {r.id for r in scheduler.list_reminders()} == {"done2", "done3", "pending"}


def test_disabled_pruning_keeps_all(tmp_path):
    scheduler = ReminderScheduler(
        db_path=str(tmp_path / "off.db"), keep_completed=None
    )
    for i in range(10):
        scheduler.add_reminder(_reminder(f"r{i}"))
        scheduler.save_reminder(scheduler.get_reminder(f"r{i}"))

    assert len(scheduler.list_reminders(completed=True)) == 10
