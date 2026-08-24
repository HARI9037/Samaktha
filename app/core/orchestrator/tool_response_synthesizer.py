"""Tool response synthesizer — Bug 2 fix.

Converts structured ToolResult data dicts into human-readable assistant
confirmation strings.  Called by the orchestrator as a *fallback* when
``_response_content()`` returns an empty string (i.e. when no LLM
text-generation task was scheduled, as is the case for WRITE_RESOURCE,
DELETE_RESOURCE, MOVE_RESOURCE, etc.).

Design constraints:
  - Tools continue returning only structured data (``ToolResult.data``).
  - The ``ResponseFormatter`` / ``IntentEngine`` remain unchanged.
  - The orchestrator calls ``synthesize_tool_response(output)`` and, if a
    non-empty string is returned, uses it as the ``raw_response`` fed to
    the formatter.
  - This module has NO side-effects, NO I/O, and NO LLM calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def synthesize_tool_response(output: Any) -> str:
    """Return a natural-language confirmation for a completed tool result.

    Returns an empty string when the output is not a recognisable tool
    result dict, so callers can safely use it as a fallback:

        content = _response_content(output) or synthesize_tool_response(output)

    Only *successful* tool results that describe a completed filesystem
    mutation are synthesized.  Read results, list results, and any output
    that already has a ``content`` / ``response`` key are left to the
    normal content path.
    """
    if not isinstance(output, dict):
        return ""

    # If the output already has textual content, nothing to synthesize.
    if output.get("content") or output.get("response"):
        return ""

    return (
        _synthesize_write(output)
        or _synthesize_delete(output)
        or _synthesize_move(output)
        or _synthesize_copy(output)
        or _synthesize_mkdir(output)
        or _synthesize_capability_result(output)
        or ""
    )


# ---------------------------------------------------------------------------
# Per-action synthesizers
# ---------------------------------------------------------------------------

def _synthesize_write(output: dict) -> str:
    """Synthesize a confirmation for a successful filesystem write."""
    path_str = output.get("path")
    fmt = output.get("format")
    written_bytes = output.get("written_bytes")

    # A write result always has "path" and "written_bytes".
    if not path_str or written_bytes is None:
        return ""

    path = Path(str(path_str))
    name = path.name

    lines = [f"✅ Created:\n{path_str}"]

    # Add useful metadata without exposing internal details.
    if fmt and fmt not in ("text",):
        # Only mention non-trivial formats (docx, pdf, xlsx, …).
        lines.append(f"Format: {fmt.upper()}")

    size_str = _human_bytes(int(written_bytes))
    if size_str:
        lines.append(f"Size: {size_str}")

    return "\n".join(lines)


def _synthesize_delete(output: dict) -> str:
    deleted = output.get("deleted")
    if deleted is None:
        return ""
    if isinstance(deleted, str):
        return f"✅ Deleted:\n{deleted}"
    return ""


def _synthesize_move(output: dict) -> str:
    src = output.get("source")
    dst = output.get("destination")
    if not src or not dst:
        return ""
    return f"✅ Moved:\n{src}\n→ {dst}"


def _synthesize_copy(output: dict) -> str:
    src = output.get("source")
    dst = output.get("destination")
    if not src or not dst:
        return ""
    return f"✅ Copied:\n{src}\n→ {dst}"


def _synthesize_mkdir(output: dict) -> str:
    created = output.get("created")
    if not created:
        return ""
    return f"✅ Directory created:\n{created}"


def _synthesize_capability_result(output: dict) -> str:
    """Render truthful non-filesystem tool outcomes without an LLM."""
    status = output.get("status")
    action = output.get("action")
    if status == "simulated":
        return (
            f"{str(action or 'Communication').capitalize()} was simulated locally. "
            "No external delivery occurred."
        )
    if status == "drafted":
        return "Draft created locally. No external delivery occurred."
    if "sent" in output:
        if output.get("sent") is True:
            return "Notification delivered by the local notification backend."
        return "The local notification backend did not deliver the notification."
    if output.get("written") is True:
        return "Clipboard content was written locally."
    message = output.get("message")
    if isinstance(message, str) and message:
        return message
    if action == "search" and isinstance(output.get("count"), int):
        return f"Search completed locally with {output['count']} result(s)."
    if action in {"list", "history", "agenda"} and isinstance(output.get("count"), int):
        return f"Local {action} completed with {output['count']} item(s)."
    if "output" in output and isinstance(output.get("output"), str):
        return output["output"] or "The command completed successfully with no output."
    return ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _human_bytes(n: int) -> str:
    """Return a compact human-readable byte count."""
    if n == 0:
        return ""
    if n < 1024:
        return f"{n} B"
    kb = n / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    return f"{kb / 1024:.1f} MB"
