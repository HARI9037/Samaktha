from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core.contracts.memory import (
    DEFAULT_LOCAL_PRINCIPAL_ID,
    MemoryAccessContext,
    MemoryItem,
    MemoryScope,
)
from app.core.contracts.security import SecurityLevel
from app.memory.controller.facade import MemoryController
from app.memory.manager import MemoryManager
from app.memory.session_manager import SessionManager
from app.api.execute import _resolve_api_session
from fastapi import HTTPException


@pytest.fixture()
def controller(tmp_path):
    manager = MemoryManager()
    return MemoryController(manager)


def access(principal: str, session: str, level=SecurityLevel.LOW):
    return MemoryAccessContext(
        principal_id=principal,
        session_id=session,
        security_level=level,
    )


def contents(results):
    return [item.content for item, _score in results]


def test_access_context_requires_nonempty_principal():
    with pytest.raises(ValueError, match="principal_id"):
        MemoryAccessContext(principal_id=" ")


def test_legacy_memory_hydrates_safe_owner_and_scope():
    session = MemoryItem.model_validate({
        "content": "legacy session",
        "metadata": {"memory_type": "conversation", "session_id": "s1"},
    })
    preference = MemoryItem.model_validate({
        "content": "legacy preference",
        "metadata": {"memory_type": "preference"},
    })
    ambiguous = MemoryItem.model_validate({"content": "legacy ordinary"})
    assert (session.owner_id, session.scope, session.session_id) == (
        DEFAULT_LOCAL_PRINCIPAL_ID, MemoryScope.SESSION, "s1"
    )
    assert preference.scope is MemoryScope.USER
    assert ambiguous.scope is MemoryScope.USER
    assert ambiguous.scope is not MemoryScope.SYSTEM


def test_new_memory_write_has_owner_and_scope(controller):
    item = controller.write_conversation(
        "session fact", access_context=access("user-a", "session-a")
    )
    pref = controller.write_preference(
        "Prefer concise explanations", access_context=access("user-a", "session-a")
    )
    assert (item.owner_id, item.scope, item.session_id) == (
        "user-a", MemoryScope.SESSION, "session-a"
    )
    assert (pref.owner_id, pref.scope, pref.session_id) == (
        "user-a", MemoryScope.USER, None
    )


def test_session_and_user_scope_retrieval_matrix(controller):
    controller.write_conversation(
        "session-A secret ORANGE42", access_context=access("user-a", "session-a")
    )
    controller.write_preference(
        "Prefer concise explanations", access_context=access("user-a", "session-a")
    )

    same = contents(controller.retrieve("ORANGE42 concise", access_context=access("user-a", "session-a")))
    other_session = contents(controller.retrieve("ORANGE42 concise", access_context=access("user-a", "session-b")))
    other_user = contents(controller.retrieve("ORANGE42 concise", access_context=access("user-b", "session-a")))

    assert any("ORANGE42" in content for content in same)
    assert all("ORANGE42" not in content for content in other_session)
    assert any("concise" in content for content in other_session)
    assert all("ORANGE42" not in content and "concise" not in content for content in other_user)


def test_security_denied_memory_never_ranks(controller):
    item = controller.write_preference(
        "classified violet phrase",
        access_context=access("user-a", "session-a", SecurityLevel.HIGH),
        security_level=SecurityLevel.HIGH,
    )
    assert item.privacy_level is SecurityLevel.HIGH
    assert not controller.retrieve(
        "classified violet", access_context=access("user-a", "session-b")
    )


def test_warm_cache_does_not_cross_principal_or_session(controller):
    controller.write_conversation(
        "warm-cache secret", access_context=access("user-a", "session-a")
    )
    assert controller.retrieve(
        "warm-cache secret", access_context=access("user-a", "session-a")
    )
    assert not controller.retrieve(
        "warm-cache secret", access_context=access("user-a", "session-b")
    )
    assert not controller.retrieve(
        "warm-cache secret", access_context=access("user-b", "session-a")
    )


def test_foreign_memory_delete_is_rejected(controller):
    item = controller.write_conversation(
        "delete protected", access_context=access("user-a", "session-a")
    )
    assert controller.delete_memory(
        item.id, access_context=access("user-b", "session-a")
    ) is False
    assert controller.delete_memory(
        item.id, access_context=access("user-a", "session-a")
    ) is True


def test_session_metadata_ownership_and_legacy_migration(tmp_path):
    manager = SessionManager(base_dir=tmp_path)
    owned = manager.create_session(session_id="owned", principal_id="user-a")
    assert owned.metadata.principal_id == "user-a"
    with pytest.raises(PermissionError):
        manager.load_session("owned", principal_id="user-b")

    legacy_dir = tmp_path / "sessions" / "legacy"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "metadata.json").write_text(json.dumps({
        "session_id": "legacy", "created_at": "now", "updated_at": "now"
    }), encoding="utf-8")
    (legacy_dir / "session_memory.json").write_text(json.dumps({
        "session_id": "legacy"
    }), encoding="utf-8")
    # Seed the metadata-only index using the legacy payload.
    index = json.loads((tmp_path / "session_index.json").read_text(encoding="utf-8"))
    index["legacy"] = {
        "session_id": "legacy", "created_at": "now", "updated_at": "now"
    }
    (tmp_path / "session_index.json").write_text(json.dumps(index), encoding="utf-8")
    reloaded = SessionManager(base_dir=tmp_path).load_session("legacy")
    assert reloaded.metadata.principal_id == DEFAULT_LOCAL_PRINCIPAL_ID


def test_unknown_and_foreign_session_resolution(tmp_path):
    manager = SessionManager(base_dir=tmp_path)
    with pytest.raises(KeyError):
        manager.resolve_session("missing", principal_id="user-a", create_if_missing=False)
    manager.create_session(session_id="owned", principal_id="user-a")
    with pytest.raises(PermissionError):
        manager.resolve_session("owned", principal_id="user-b")


def test_unknown_api_session_is_rejected_and_missing_session_is_created(tmp_path):
    manager = SessionManager(base_dir=tmp_path)
    orchestrator = SimpleNamespace(_session_manager=manager)
    with pytest.raises(HTTPException) as unknown:
        _resolve_api_session(orchestrator, "arbitrary")
    assert unknown.value.status_code == 404
    assert _resolve_api_session(orchestrator, None) == "default"
    assert manager.session_exists("default")


def test_foreign_api_session_is_rejected(tmp_path):
    manager = SessionManager(base_dir=tmp_path)
    manager.create_session(session_id="foreign", principal_id="user-b")
    with pytest.raises(HTTPException) as foreign:
        _resolve_api_session(SimpleNamespace(_session_manager=manager), "foreign")
    assert foreign.value.status_code == 403
