"""Phase 10.1 — Session file layout, JSON persistence, and markdown export.

Layout under the session-memory base directory::

    <base_dir>/
        session_index.json          (Session Index)
        sessions/
            <session_id>/
                metadata.json       (SessionMetadata)
                session_memory.json (SessionMemory — authoritative)
                session_memory.md   (human-readable export, never source of truth)

``session_memory.json`` is the machine-readable source of truth. The markdown
file is regenerated from it on every save and is never read back.

Phase 20.2   — Deterministic metadata extraction arrays and history log.
Phase 20.2.1 — Added schema_version, turn_number, render-only markdown.
Phase 20.2.2 — Atomic writes (write → fsync → rename), schema migration.
"""

from __future__ import annotations

import json
import os
import tempfile
import warnings
from pathlib import Path

from app.memory.session_models import SessionMemory, SessionMetadata

SESSION_INDEX_FILENAME = "session_index.json"
SESSIONS_DIRNAME = "sessions"
METADATA_FILENAME = "metadata.json"
SESSION_MEMORY_FILENAME = "session_memory.json"
SESSION_MEMORY_MD_FILENAME = "session_memory.md"

DEFAULT_BASE_DIR = "data/session_memory"


def sessions_dir(base_dir: str | Path) -> Path:
    return Path(base_dir) / SESSIONS_DIRNAME


def session_dir(base_dir: str | Path, session_id: str) -> Path:
    return sessions_dir(base_dir) / session_id


def metadata_path(base_dir: str | Path, session_id: str) -> Path:
    return session_dir(base_dir, session_id) / METADATA_FILENAME


def session_memory_json_path(base_dir: str | Path, session_id: str) -> Path:
    return session_dir(base_dir, session_id) / SESSION_MEMORY_FILENAME


def session_memory_md_path(base_dir: str | Path, session_id: str) -> Path:
    return session_dir(base_dir, session_id) / SESSION_MEMORY_MD_FILENAME


# ---------------------------------------------------------------------------
# Atomic JSON I/O
# ---------------------------------------------------------------------------


def write_json(path: Path, data: object) -> None:
    """Write deterministic, sorted, pretty-printed JSON **atomically**.

    Phase 20.2.2: uses a temp file in the same directory, fsyncs, then
    performs an atomic rename so a crash during the write can never leave
    a corrupted JSON file on disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    dir_ = path.parent
    fd, tmp_name = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        # Atomic on POSIX; best-effort on Windows (still much safer than a direct write).
        os.replace(tmp_name, path)
    except Exception:
        # Clean up the temp file if something went wrong before the rename.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_text_atomic(path: Path, text: str) -> None:
    """Write a text file atomically (temp + fsync + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_json(path: Path) -> object | None:
    """Read JSON; return None when the file does not exist."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------

# Current schema version — must match session_models.CURRENT_SCHEMA_VERSION.
_CURRENT_SCHEMA_VERSION = 1

# Deterministic defaults for every field added after the initial schema.
# Maps  schema_version → {field_name: default_value}.
_METADATA_FIELD_DEFAULTS: dict[int, dict[str, object]] = {
    # Fields added in Phase 20.2 (schema v0 → v1)
    1: {
        "tools_used": [],
        "providers_used": [],
        "files_created": [],
        "files_modified": [],
        "files_deleted": [],
        "approvals": [],
        "architecture_topics": [],
        "bugs_fixed": [],
        "repositories": [],
        "runtime_errors": [],
        "milestones": [],
        "topic_summary": [],
        "tags": [],
        "projects": [],
        "title": "",
        "summary": "",
        "message_count": 0,
        "schema_version": 1,
    },
}

_MEMORY_FIELD_DEFAULTS: dict[int, dict[str, object]] = {
    1: {
        "entries": [],
        "history": [],
        "next_turn_number": 1,
    },
}


def migrate_session_data(data: dict, *, kind: str) -> dict:
    """Upgrade a raw JSON dict to the current schema version.

    ``kind`` is either ``"metadata"`` or ``"memory"``.

    Rules
    -----
    - Fields that already exist are never overwritten.
    - Missing fields receive their deterministic defaults.
    - The function is idempotent: calling it twice gives the same result.
    - It never removes existing keys (forward-compatibility for unknown fields).

    Phase 20.2.2: called by ``read_json`` callers before constructing Pydantic
    models so existing sessions always load cleanly.
    """
    val = data.get("schema_version")
    try:
        current_version = int(val) if val is not None else 0
    except (TypeError, ValueError):
        current_version = 0
        
    target_version = _CURRENT_SCHEMA_VERSION

    if current_version == target_version:
        return data
        
    if current_version > target_version:
        return data

    field_defaults = (
        _METADATA_FIELD_DEFAULTS if kind == "metadata" else _MEMORY_FIELD_DEFAULTS
    )

    result = dict(data)
    # Apply defaults for every version from current+1 up to target.
    for v in range(current_version + 1, target_version + 1):
        for field, default in field_defaults.get(v, {}).items():
            if field not in result:
                # Deep-copy mutable defaults so they are not shared.
                result[field] = (
                    list(default) if isinstance(default, list)
                    else dict(default) if isinstance(default, dict)
                    else default
                )

    result["schema_version"] = target_version
    if current_version < target_version:
        warnings.warn(
            f"Session {data.get('session_id', '?')!r} migrated from schema "
            f"v{current_version} to v{target_version}.",
            category=UserWarning,
            stacklevel=4,
        )
    return result


# ---------------------------------------------------------------------------
# Markdown export (render-only — no intelligence)
# ---------------------------------------------------------------------------


def export_session_markdown(
    metadata: SessionMetadata, memory: SessionMemory
) -> str:
    """Deterministic human-readable export of a session.

    Always derived from the structured models; never parsed back.
    Contains no scanning logic, no heuristics, no analysis.
    Every value rendered here must already exist in the model fields.
    """
    lines = [
        f"# Session {metadata.session_id}",
        "",
        f"- Created: {metadata.created_at}",
        f"- Updated: {metadata.updated_at}",
        f"- Message count: {metadata.message_count}",
        f"- Schema version: {getattr(metadata, 'schema_version', 1)}",
    ]
    # Inline topics/tags/projects in header for compatibility and quick-scan readability
    if getattr(metadata, "topic_summary", None):
        lines.append(f"- Topics: {', '.join(metadata.topic_summary)}")
    if metadata.tags:
        lines.append(f"- Tags: {', '.join(metadata.tags)}")
    if metadata.projects:
        lines.append(f"- Projects: {', '.join(metadata.projects)}")
    lines += [
        "",
        "## Summary",
        metadata.summary or "_No summary yet._",
        "",
        "## Major Topics",
        ", ".join(metadata.topic_summary) if getattr(metadata, "topic_summary", None) else "_None_",
        "",
        "## Projects",
        ", ".join(metadata.projects) if metadata.projects else "_None_",
        "",
        "## Milestones",
        ", ".join(metadata.milestones) if getattr(metadata, "milestones", None) else "_None_",
        "",
        "## Architecture Decisions",
        ", ".join(metadata.architecture_topics) if getattr(metadata, "architecture_topics", None) else "_None_",
        "",
        "## Files Created",
        ", ".join(metadata.files_created) if getattr(metadata, "files_created", None) else "_None_",
        "",
        "## Files Modified",
        ", ".join(metadata.files_modified) if getattr(metadata, "files_modified", None) else "_None_",
        "",
        "## Tools Used",
        ", ".join(metadata.tools_used) if getattr(metadata, "tools_used", None) else "_None_",
        "",
        "## Providers Used",
        ", ".join(metadata.providers_used) if getattr(metadata, "providers_used", None) else "_None_",
        "",
        "## Errors Encountered",
        ", ".join(metadata.runtime_errors) if getattr(metadata, "runtime_errors", None) else "_None_",
        "",
        "## Bugs Fixed",
        ", ".join(metadata.bugs_fixed) if getattr(metadata, "bugs_fixed", None) else "_None_",
        "",
        "## Pending Work",
        "_None_",
        "",
        "## Conversation Timeline",
    ]

    if not getattr(memory, "history", None):
        lines.append("_No timeline available._")
    else:
        for event in sorted(memory.history, key=lambda e: e.turn_number):
            turn_label = f"T{event.turn_number}" if event.turn_number else ""
            lines.append(
                f"- **{event.timestamp}**"
                + (f" [{turn_label}]" if turn_label else "")
                + f" [{event.role.capitalize()}]"
                + f" {event.intent or 'chat'}"
                + f" (State: {event.execution_state or 'none'})"
            )
            if event.tool_calls:
                lines.append(f"  - Tools: {', '.join(event.tool_calls)}")

    lines.append("")
    lines.append("## Conversation Log")
    if not getattr(memory, "history", None):
        lines.append("_No conversation log._")
    else:
        for event in sorted(memory.history, key=lambda e: e.turn_number):
            turn_label = f" (T{event.turn_number})" if event.turn_number else ""
            lines.append(f"### {event.role.capitalize()}{turn_label} ({event.timestamp})")
            lines.append(event.content)
            lines.append("")

    lines.append("")
    lines.append("## Session Memory")
    if memory.entries:
        for entry in memory.entries:
            lines.append(f"- **{entry.key}** ({entry.category}): {entry.value}")
    else:
        lines.append("_No session memory entries._")

    return "\n".join(lines) + "\n"
