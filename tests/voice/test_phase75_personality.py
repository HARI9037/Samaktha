"""Phase 7.5 speech formatting and personality tests."""

import ast
from pathlib import Path

from app.voice.personality import GreetingEngine, PersonalityEngine, PersonalityProfile
from app.voice.speech_formatter import SpeechFormatter, SpeechEmotion


def test_markdown_is_converted_to_speech():
    formatter = SpeechFormatter()
    result = formatter.format("# Installation\n\n**Important**")
    assert result == "Installation Important."
    assert "#" not in result and "**" not in result


def test_urls_are_not_read_character_by_character():
    formatter = SpeechFormatter()
    result = formatter.format("Visit https://example.com")
    assert result == "Visit the link has been shared in chat."
    assert formatter.stats.urls_skipped == 1


def test_code_is_summarized():
    formatter = SpeechFormatter()
    result = formatter.format("Here is code:\n```python\ndef hello():\n    print('hi')\n```")
    assert "review it in the conversation" in result
    assert formatter.stats.code_blocks_skipped == 1


def test_tables_are_summarized():
    formatter = SpeechFormatter()
    result = formatter.format("| Name | Value |\n| --- | --- |\n| A | 1 |")
    assert "table summarizes" in result
    assert formatter.stats.tables_summarized == 1


def test_numbers_and_abbreviations_are_expanded():
    formatter = SpeechFormatter()
    result = formatter.format("The LLM uses a GPU in 2026 and 5 km.")
    assert "Large Language Model" in result
    assert "Graphics Processing Unit" in result
    assert "twenty twenty-six" in result
    assert "five kilometres" in result


def test_emotion_is_provider_agnostic_metadata():
    formatter = SpeechFormatter()
    assert formatter.format("Done", SpeechEmotion.SUCCESS) == "Done."


def test_personality_profiles_rotate_confirmations_deterministically():
    engine = PersonalityEngine(PersonalityProfile.CORE)
    assert engine.confirmation() == "Sure."
    assert engine.confirmation() == "Absolutely."
    engine.profile = PersonalityProfile.MINIMAL
    assert engine.confirmation() == "One moment."


def test_greetings_do_not_repeat_identically():
    engine = GreetingEngine()
    assert engine.greeting(10) == "Good morning."
    assert engine.greeting(10) == "Hello."
    assert engine.greeting(23) == "You're up late."
    assert engine.greeting(10, returning=True) == "Welcome back."


def test_voice_architecture_remains_isolated():
    forbidden = ("app.core.cap", "app.core.gambit", "app.workflow", "app.runtime", "app.providers", "app.tools", "app.security", "app.memory")
    root = Path(__file__).parents[2] / "app" / "voice"
    violations = []
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            module = node.module if isinstance(node, ast.ImportFrom) else ""
            if module and module.startswith(forbidden):
                violations.append((str(path), module))
    assert violations == []
