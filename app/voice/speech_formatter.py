"""Deterministic conversion of rich runtime text into natural speech."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class SpeechEmotion(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    CURIOUS = "curious"
    WARNING = "warning"
    THINKING = "thinking"
    SUCCESS = "success"
    ERROR = "error"


@dataclass
class SpeechFormatStats:
    words_spoken: int = 0
    markdown_cleaned: int = 0
    urls_skipped: int = 0
    code_blocks_skipped: int = 0
    tables_summarized: int = 0


class SpeechFormatter:
    """Format text after Runtime and immediately before TextToSpeech."""

    DEFAULT_ABBREVIATIONS = {
        "LLM": "Large Language Model",
        "GPU": "Graphics Processing Unit",
        "CPU": "Central Processing Unit",
        "STT": "speech recognition",
        "TTS": "text to speech",
        "VAD": "voice activity detection",
        "API": "A P I",
    }

    def __init__(
        self,
        profile=None,
        expand_numbers: bool = True,
        expand_abbreviations: bool = True,
        read_code: bool = False,
        read_urls: bool = False,
        read_tables: bool = False,
        read_lists: bool = True,
        abbreviations: dict[str, str] | None = None,
    ) -> None:
        self.profile = profile
        self.expand_numbers = expand_numbers
        self.expand_abbreviations = expand_abbreviations
        self.read_code = read_code
        self.read_urls = read_urls
        self.read_tables = read_tables
        self.read_lists = read_lists
        self.abbreviations = {**self.DEFAULT_ABBREVIATIONS, **(abbreviations or {})}
        self.stats = SpeechFormatStats()

    def format(self, text: str, emotion: SpeechEmotion = SpeechEmotion.NEUTRAL) -> str:
        original = text.strip()
        value = original
        if not value:
            return ""
        value = self._code(value)
        value = self._tables(value)
        value = self._urls(value)
        value = self._lists(value)
        value = re.sub(r"^#{1,6}\s*", "", value, flags=re.MULTILINE)
        value = re.sub(r"```[\w+-]*|`", "", value)
        value = re.sub(r"\*\*([^*]+)\*\*|__([^_]+)__", lambda m: m.group(1) or m.group(2), value)
        value = re.sub(r"[*_~]", "", value)
        if self.expand_abbreviations:
            for short, spoken in self.abbreviations.items():
                value = re.sub(rf"\b{re.escape(short)}\b", spoken, value)
        if self.expand_numbers:
            value = self._numbers(value)
        value = re.sub(r"\s+", " ", value).strip()
        if value and not value.endswith(('.', '!', '?')):
            value += "."
        if value != original:
            self.stats.markdown_cleaned += 1
        self.stats.words_spoken += len(value.split())
        if self.profile:
            value = self.profile.adjust(value, emotion)
        return value

    def _code(self, text: str) -> str:
        pattern = re.compile(r"```(?:[\w+-]+)?\s*(.*?)```", re.DOTALL)
        def replace(match):
            code = match.group(1).strip()
            if self.read_code and len(code) <= 120:
                return "The code is shown in the conversation."
            self.stats.code_blocks_skipped += 1
            return "I've generated some code. You can review it in the conversation."
        return pattern.sub(replace, text)

    def _tables(self, text: str) -> str:
        lines = text.splitlines()
        output: list[str] = []
        index = 0
        while index < len(lines):
            if "|" in lines[index] and index + 1 < len(lines) and re.search(r"\|?\s*:?-{2,}", lines[index + 1]):
                end = index
                while end < len(lines) and "|" in lines[end]:
                    end += 1
                self.stats.tables_summarized += 1
                output.append("The table summarizes information shown in the conversation.")
                index = end
            else:
                output.append(lines[index])
                index += 1
        return "\n".join(output)

    def _urls(self, text: str) -> str:
        pattern = r"(?:https?://|www\.)\S+|[\w.+-]+@[\w-]+\.[\w.-]+"
        def replace(match):
            self.stats.urls_skipped += 1
            if self.read_urls:
                return "the link shared in chat"
            return "the link has been shared in chat"
        return re.sub(pattern, replace, text)

    def _lists(self, text: str) -> str:
        if not self.read_lists:
            return re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
        items = re.findall(r"^\s*[-*+]\s+(.+)$", text, flags=re.MULTILINE)
        if len(items) < 2:
            return text
        text = re.sub(r"^\s*[-*+]\s+.+$", "", text, flags=re.MULTILINE)
        ordinal = ["First", "Second", "Finally"]
        return text + " " + " ".join(f"{ordinal[min(i, 2)]}, {item}." for i, item in enumerate(items))

    def _numbers(self, text: str) -> str:
        units = {"km": "kilometres", "kg": "kilograms", "%": "percent"}
        def number(match):
            value, unit = match.group(1), match.group(2)
            spoken = self._number_words(value)
            return f"{spoken} {units.get(unit, unit or '')}".strip()
        text = re.sub(r"\b(\d+(?:\.\d+)?)\s*(km|kg|%)(?=\s|$|[.,!?])", number, text)
        return re.sub(r"\b\d+(?:\.\d+)?\b", lambda m: self._number_words(m.group(0)), text)

    @staticmethod
    def _number_words(value: str) -> str:
        if "." in value:
            left, right = value.split(".", 1)
            return f"{SpeechFormatter._integer_words(int(left))} point {' '.join(SpeechFormatter._integer_words(int(d)) for d in right)}"
        if len(value) == 4 and value.startswith("20"):
            return f"twenty {SpeechFormatter._integer_words(int(value[2:]))}"
        return SpeechFormatter._integer_words(int(value))

    @staticmethod
    def _integer_words(value: int) -> str:
        small = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
        tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
        if value < 20: return small[value]
        if value < 100: return tens[value // 10] + (f"-{small[value % 10]}" if value % 10 else "")
        if value < 1000: return f"{small[value // 100]} hundred" + (f" {SpeechFormatter._integer_words(value % 100)}" if value % 100 else "")
        return str(value)
