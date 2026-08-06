"""Phase 11.4 — deterministic Reference Resolver."""

from app.conversation import (
    ConversationState,
    ReferenceKind,
    ReferenceResolver,
)


def _state(**overrides) -> ConversationState:
    base = ConversationState()
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_no_reference_is_passthrough() -> None:
    resolver = ReferenceResolver()
    result = resolver.resolve("Read profile.pdf", ConversationState())
    assert result.resolved is False
    assert result.request == "Read profile.pdf"
    assert result.original_request == "Read profile.pdf"


def test_empty_request_is_passthrough() -> None:
    resolver = ReferenceResolver()
    result = resolver.resolve("   ", ConversationState())
    assert result.resolved is False
    assert result.request == ""


def test_summarize_it_resolves_active_document() -> None:
    resolver = ReferenceResolver()
    result = resolver.resolve("Summarize it", _state(active_document="profile.pdf"))
    assert result.resolved is True
    assert result.kind == ReferenceKind.DOCUMENT
    assert result.resource == "profile.pdf"
    assert result.request == "Summarize profile.pdf"


def test_read_it_resolves_active_code_file() -> None:
    resolver = ReferenceResolver()
    result = resolver.resolve("Read it", _state(active_code_file="src/main.py"))
    assert result.resolved is True
    assert result.kind == ReferenceKind.CODE_FILE
    assert result.request == "Read src/main.py"


def test_save_it_resolves_generated_text() -> None:
    resolver = ReferenceResolver()
    result = resolver.resolve(
        "Save it", _state(last_generated_text="hello world")
    )
    assert result.resolved is True
    assert result.kind == ReferenceKind.GENERATED_TEXT
    assert result.resource == "hello world"
    assert result.request == "Save the generated text"


def test_run_it_resolves_generated_script() -> None:
    resolver = ReferenceResolver()
    result = resolver.resolve(
        "Run it", _state(last_generated_text="print(1)")
    )
    assert result.resolved is True
    assert result.kind == ReferenceKind.GENERATED_TEXT
    assert result.request == "Run the generated script"


def test_run_it_falls_back_to_last_command() -> None:
    resolver = ReferenceResolver()
    result = resolver.resolve(
        "Run it", _state(last_command="install dependencies")
    )
    assert result.resolved is True
    assert result.kind == ReferenceKind.COMMAND
    assert result.request == "Run the previous command"


def test_open_first_result_resolves_search_results() -> None:
    resolver = ReferenceResolver()
    result = resolver.resolve(
        "Open the first result",
        _state(last_search_results=["a.txt", "b.txt"]),
    )
    assert result.resolved is True
    assert result.kind == ReferenceKind.SEARCH_RESULT
    assert result.request == "Open a.txt"


def test_continue_resolves_last_command() -> None:
    resolver = ReferenceResolver()
    result = resolver.resolve(
        "continue", _state(last_command="Read profile.pdf")
    )
    assert result.resolved is True
    assert result.kind == ReferenceKind.COMMAND
    assert result.request == "continue Read profile.pdf"


def test_keep_going_resolves_last_resource() -> None:
    resolver = ReferenceResolver()
    result = resolver.resolve(
        "keep going", _state(last_resource="C:\\work\\project")
    )
    assert result.resolved is True
    assert result.request == "keep going C:\\work\\project"


def test_named_project_directory_repository() -> None:
    resolver = ReferenceResolver()
    state = _state(
        active_project="project-x",
        active_directory="C:\\work",
        active_repository="repo-y",
    )
    r1 = resolver.resolve("Review the project", state)
    assert r1.kind == ReferenceKind.PROJECT and r1.request == "Review project-x"
    r2 = resolver.resolve("List the directory", state)
    assert r2.kind == ReferenceKind.DIRECTORY and r2.request == "List C:\\work"
    r3 = resolver.resolve("Clone the repository", state)
    assert r3.kind == ReferenceKind.REPOSITORY and r3.request == "Clone repo-y"


def test_named_document_phrases() -> None:
    resolver = ReferenceResolver()
    state = _state(active_document="profile.pdf")
    assert resolver.resolve("Read the previous file", state).request == "Read profile.pdf"
    assert resolver.resolve("Show the same file", state).request == "Show profile.pdf"
    assert resolver.resolve("Summarize this document", state).request == "Summarize profile.pdf"


def test_self_reference_is_never_rewritten() -> None:
    resolver = ReferenceResolver()
    state = _state(active_document="profile.pdf", last_command="Read profile.pdf")
    assert resolver.resolve("delete this conversation", state).resolved is False
    assert resolver.resolve("forget my memory", state).resolved is False
    assert resolver.resolve("summarize this session", state).resolved is False


def test_unknown_reference_with_empty_state_is_passthrough() -> None:
    resolver = ReferenceResolver()
    result = resolver.resolve("Summarize it", ConversationState())
    assert result.resolved is False
    assert result.request == "Summarize it"


def test_fallback_precedence_without_document() -> None:
    resolver = ReferenceResolver()
    result = resolver.resolve(
        "Summarize it", _state(last_generated_text="some generated text")
    )
    assert result.kind == ReferenceKind.GENERATED_TEXT


def test_resolver_is_pure_and_never_mutates_state() -> None:
    resolver = ReferenceResolver()
    state = _state(active_document="profile.pdf")
    snapshot = state.model_dump()
    resolver.resolve("Summarize it", state)
    resolver.resolve("delete this conversation", state)
    assert state.model_dump() == snapshot
