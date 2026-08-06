"""VoiceOutputFormatter for Phase 14.4.

Formats runtime output for voice consumption.
Summarizes tool output, cleans markdown, removes URLs/code/tables,
and preserves meaning for TTS consumption.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.voice.speech_formatter import SpeechFormatter, SpeechEmotion

log = logging.getLogger(__name__)


class VoiceOutputFormatter:
    """Formats runtime output for voice consumption.

    - Summarizes large tool output
    - Cleans markdown
    - Removes URLs, code blocks, tables
    - Preserves meaning for TTS
    - Never speaks raw PDFs, JSON, or internal events
    """

    def __init__(
        self,
        speech_formatter: Optional[SpeechFormatter] = None,
        max_output_length: int = 500,
    ) -> None:
        self._formatter = speech_formatter or SpeechFormatter()
        self._max_output_length = max_output_length

    def format(
        self,
        text: str,
        emotion: SpeechEmotion = SpeechEmotion.NEUTRAL,
        is_tool_output: bool = False,
    ) -> str:
        """Format text for voice output."""
        if not text:
            return ""

        if is_tool_output:
            text = self._summarize_tool_output(text)

        text = self._clean_for_voice(text)
        text = self._truncate(text)

        spoken = self._formatter.format(text, emotion)
        return spoken or ""

    def _summarize_tool_output(self, text: str) -> str:
        """Summarize large tool output for voice."""
        lines = text.strip().split("\n")
        if len(lines) <= 3:
            return text
        summary_lines = []
        for line in lines[:3]:
            cleaned = self._clean_for_voice(line)
            if cleaned:
                summary_lines.append(cleaned)
        if len(lines) > 3:
            summary_lines.append(f"... {len(lines)} more lines")
        return ". ".join(summary_lines)

    def _clean_for_voice(self, text: str) -> str:
        """Remove elements that are hard to speak."""
        text = self._remove_urls(text)
        text = self._remove_code_blocks(text)
        text = self._remove_tables(text)
        text = self._remove_markdown_formatting(text)
        text = self._remove_json(text)
        text = text.strip()
        return text

    def _remove_urls(self, text: str) -> str:
        return re.sub(r"https?://\S+", "", text)

    def _remove_code_blocks(self, text: str) -> str:
        text = re.sub(r"```[\s\S]*?```", "", text)
        text = re.sub(r"`[^`]+`", "", text)
        return text

    def _remove_tables(self, text: str) -> str:
        lines = text.split("\n")
        filtered = []
        for line in lines:
            if "|" in line and "---" in line:
                continue
            if line.strip().startswith("|") and line.strip().endswith("|"):
                continue
            filtered.append(line)
        return "\n".join(filtered)

    def _remove_markdown_formatting(self, text: str) -> str:
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)
        text = re.sub(r"_(.*)_", r"\1", text)
        text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
        return text

    def _remove_json(self, text: str) -> str:
        text = re.sub(r"\{[^{}]*\}", "", text)
        text = re.sub(r"\[[^\]]*\]", "", text)
        return text

    def _truncate(self, text: str) -> str:
        if len(text) > self._max_output_length:
            return text[:self._max_output_length].rsplit(" ", 1)[0] + "..."
        return text