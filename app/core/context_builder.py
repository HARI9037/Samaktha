"""Phase AI-OS — Context Builder.

Converts raw tool outputs into a structured, chunked prompt context string
that is passed to the LLM as the final reasoning stage. Never forwards raw
file paths or file names to the provider—only extracted content.
"""
from __future__ import annotations

from typing import Any


_MAX_CONTENT_CHARS = 12_000   # max chars from any single tool output injected into context
_CHUNK_SEPARATOR = "\n\n" + "─" * 60 + "\n\n"

_SYSTEM_PROMPT = """\
You are a tool-augmented AI assistant. You have access to tools that execute \
on the user's machine. When a tool produces output, that output is a trusted \
execution result.

Rules:
- NEVER say you cannot access local files or folders — the tool has already \
done so on your behalf.
- ALWAYS base your answer on the actual tool output provided below.
- NEVER mention OCR, PyMuPDF, pdfplumber, parsers, or any internal tooling. \
The document content you receive is the final extracted text.
- If the document content is empty, respond: "The document appears to contain \
no readable text."
- If the tool returned a valid result, do NOT generate generic ChatGPT-style \
disclaimers about being unable to access files.
- Be honest — if the document text is empty or the tool returned an error, \
say so directly. Do not fabricate content."""


class ContextBuilder:
    """Assembles structured context from tool execution outputs for LLM consumption."""

    def build(
        self,
        user_request: str,
        tool_outputs: list[dict[str, Any]],
        memory_results: str | None = None,
    ) -> str:
        """
        Produce a single context string from:
          - user_request: the original user message
          - tool_outputs: list of dicts collected from workflow task results
          - memory_results: optional memory retrieval string

        Returns a formatted prompt context string.
        """
        parts: list[str] = []

        if memory_results and memory_results.strip():
            parts.append(f"[MEMORY CONTEXT]\n{memory_results.strip()[:4000]}")

        for output in tool_outputs:
            chunk = self._format_output(output)
            if chunk:
                parts.append(chunk)

        if not parts:
            return user_request

        context_block = _CHUNK_SEPARATOR.join(parts)
        return (
            f"[TOOL OUTPUT — Trusted execution result]\n\n"
            f"{context_block}\n\n"
            f"[USER REQUEST]\n{user_request}"
        )

    def build_messages(
        self,
        user_request: str,
        tool_outputs: list[dict[str, Any]],
        memory_results: str | None = None,
    ) -> list[dict[str, str]]:
        """Build a list of chat messages (system + user) for the provider API."""
        user_content = self.build(user_request, tool_outputs, memory_results)
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    def _format_output(self, output: dict[str, Any]) -> str:
        """Convert a single tool output dict into a readable context section."""
        if not isinstance(output, dict):
            return ""

        # DocumentTool output (nested "result" key)
        if "result" in output and isinstance(output["result"], dict):
            r = output["result"]
            path = output.get("path", "document")
            text = str(r.get("text", ""))[:_MAX_CONTENT_CHARS]
            pages = r.get("page_count", "?")
            meta = r.get("metadata", {})
            ocr_used = meta.get("ocr_used")
            lines = [f"[DOCUMENT CONTENT — {path} ({pages} pages)]"]
            if text:
                lines.append(text)
            else:
                lines.append("[No text content extracted.]")
            return "\n".join(lines)

        # PDF / file text extraction
        if "text" in output:
            path = output.get("path", "document")
            pages = output.get("page_count", "?")
            content = str(output["text"])[:_MAX_CONTENT_CHARS]
            return f"[PDF CONTENT — {path} ({pages} pages)]\n{content}"

        # File system read
        if "content" in output:
            path = output.get("path", "file")
            content = str(output["content"])[:_MAX_CONTENT_CHARS]
            return f"[FILE CONTENT — {path}]\n{content}"

        # Directory listing
        if "items" in output:
            path = output.get("path", "directory")
            items = output.get("items", [])
            listing_lines = []
            for item in items[:200]:
                icon = "📁" if item.get("is_dir") else "📄"
                size = f" ({item.get('size', 0)} bytes)" if not item.get("is_dir") else ""
                listing_lines.append(f"  {icon} {item.get('name', '?')}{size}")
            return f"[DIRECTORY LISTING — {path}]\n" + "\n".join(listing_lines)

        # Memory results
        if "memories" in output:
            memories = str(output.get("memories", ""))[:4000]
            return f"[MEMORY RESULTS — query: {output.get('query', '?')}]\n{memories}"

        # Windows process listing
        if "processes" in output:
            procs = output.get("processes", [])[:30]
            lines = [f"  • {p.get('name', '?')} (PID: {p.get('pid', '?')})" for p in procs]
            return f"[RUNNING PROCESSES ({len(procs)} shown)]\n" + "\n".join(lines)

        # Terminal command output
        if "stdout" in output:
            cmd = output.get("command", "terminal")
            out = str(output["stdout"])[:2000]
            return f"[COMMAND OUTPUT — {cmd}]\n{out}"

        return ""

    def needs_llm(self, intent: str, tool_outputs: list[dict[str, Any]]) -> bool:
        """Decide whether the assembled context still requires LLM reasoning.

        Pure filesystem listing or simple exists checks may not need an LLM.
        """
        _NO_LLM_INTENTS = {"list_directory"}
        if intent in _NO_LLM_INTENTS and tool_outputs:
            return False
        return True
