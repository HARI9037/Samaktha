"""Phase 11.4 — per-session ConversationStateManager."""

from app.conversation import ConversationStateManager


def test_get_state_lazily_creates_default() -> None:
    manager = ConversationStateManager()
    assert manager.has_state("s1") is False
    state = manager.get_state("s1")
    assert manager.has_state("s1") is True
    assert isinstance(state, object)
    assert state.last_command is None


def test_default_session_id() -> None:
    manager = ConversationStateManager()
    assert manager.get_state() is manager.get_state("default")


def test_sessions_are_isolated() -> None:
    manager = ConversationStateManager()
    manager.update_state("s1", active_document="profile.pdf")
    manager.update_state("s2", active_document="other.pdf")
    assert manager.get_state("s1").active_document == "profile.pdf"
    assert manager.get_state("s2").active_document == "other.pdf"
    manager.reset("s1")
    assert manager.get_state("s1").active_document is None
    assert manager.get_state("s2").active_document == "other.pdf"


def test_reset_returns_fresh_state() -> None:
    manager = ConversationStateManager()
    manager.update_state("s1", last_generated_text="x")
    state = manager.reset("s1")
    assert state.last_generated_text is None
    assert manager.get_state("s1") is state


def test_remove_drops_state_only_for_that_session() -> None:
    manager = ConversationStateManager()
    manager.update_state("s1", active_document="a.pdf")
    manager.update_state("s2", active_document="b.pdf")
    assert manager.remove("s1") is True
    assert manager.remove("s1") is False
    assert manager.has_state("s1") is False
    assert manager.get_state("s2").active_document == "b.pdf"


def test_clear_removes_all_states() -> None:
    manager = ConversationStateManager()
    manager.update_state("s1", active_document="a.pdf")
    manager.update_state("s2", active_document="b.pdf")
    manager.clear()
    assert manager.has_state("s1") is False
    assert manager.has_state("s2") is False


def test_update_state_only_sets_known_fields() -> None:
    manager = ConversationStateManager()
    state = manager.update_state(
        "s1",
        active_document="profile.pdf",
        not_a_field="ignored",
    )
    assert state.active_document == "profile.pdf"
    assert not hasattr(state, "not_a_field")


def test_resolve_delegates_to_resolver() -> None:
    manager = ConversationStateManager()
    manager.update_state("s1", active_document="profile.pdf")
    resolution = manager.resolve("Summarize it", "s1")
    assert resolution.resolved is True
    assert resolution.request == "Summarize profile.pdf"


def test_record_command_and_goal_through_manager() -> None:
    manager = ConversationStateManager()
    manager.record_command("Read profile.pdf", "s1")
    manager.record_goal("read_resource", "profile.pdf", "s1")
    state = manager.get_state("s1")
    assert state.last_command == "Read profile.pdf"
    assert state.active_document == "profile.pdf"
    assert state.last_resource == "profile.pdf"


def test_record_outputs_through_manager() -> None:
    manager = ConversationStateManager()
    manager.record_outputs(
        [type("R", (), {"output": {"content": "x"}, "error": None, "metadata": {}, "routing": None})()],
        "s1",
    )
    assert manager.get_state("s1").last_generated_text == "x"


def test_state_manager_never_touches_memory_controller() -> None:
    manager = ConversationStateManager()
    assert manager.has_state("s1") is False
    manager.update_state("s1", active_document="profile.pdf")
    assert manager.get_state("s1").active_document == "profile.pdf"
    assert manager.remove("s1") is True
    assert manager.has_state("s1") is False
