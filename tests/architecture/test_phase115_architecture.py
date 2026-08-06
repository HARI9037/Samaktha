"""Phase 11.5 — architecture validation for conversation intelligence hardening.

Static + behavioral proof that the Phase 11.5 hardening kept the architecture
rules intact:
    - no circular imports across the pipeline modules
    - the IntentEngine and the ResponseFormatter carry no provider dependency
    - no duplicated intent, formatter, or normalization logic (each concern has
      exactly one owner)
    - the comparison knowledge is split by ownership: alias->canonical mapping
      lives only in the IntentEngine, verified facts only in the formatter
    - the orchestrator does no intent-specific branching
    - formatting is a pure function that never mutates the evaluation or reaches
      into memory
"""

import importlib
import re
from pathlib import Path

import pytest

import app.core.orchestrator.engine as engine_module
import app.personality.intent_engine as intent_module
import app.personality.response_formatter as formatter_module
from app.personality import (
    KNOWN_AGENT_FACTS,
    ConversationIntent,
    IntentEngine,
    ResponseFormatter,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _source(module) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Import graph
# ---------------------------------------------------------------------------


def test_pipeline_modules_import_without_circular_imports():
    for name in (
        "app.conversation.models",
        "app.conversation",
        "app.personality.models",
        "app.personality.greeting",
        "app.personality.intent_engine",
        "app.personality.response_formatter",
        "app.personality",
        "app.core.orchestrator",
    ):
        module = importlib.import_module(name)
        assert module is not None


def test_conversation_package_has_no_personality_or_provider_imports():
    conversation_dir = REPO_ROOT / "app" / "conversation"
    for source in conversation_dir.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "app.personality" not in text, source.name
        assert "app.providers" not in text, source.name
        assert "intent_engine" not in text, source.name
        assert "response_formatter" not in text, source.name


# ---------------------------------------------------------------------------
# No provider / memory dependency inside the classifier and the formatter
# ---------------------------------------------------------------------------


def test_intent_engine_has_no_provider_or_memory_dependency():
    source = _source(intent_module)
    for banned in ("app.providers", "app.memory", "app.core", "app.conversation",
                   "response_formatter", "request("):
        assert banned not in source, banned
    assert "import re" in source
    assert "dataclass" in source


def test_response_formatter_has_no_provider_or_memory_dependency():
    source = _source(formatter_module)
    for banned in ("app.providers", "app.memory", "app.conversation",
                   "import app.core", "import app.shell", "import app.tui"):
        assert banned not in source, banned


def test_intent_engine_has_no_response_text():
    source = _source(intent_module)
    for banned in ("I'm Samaktha", "I am Samaktha", "GOODBYE_TEXT", "THANKS_TEXT",
                   "ARCHITECTURE_FALLBACK_TEXT", "VERSION_TEXT"):
        assert banned not in source, banned


# ---------------------------------------------------------------------------
# No duplicated logic
# ---------------------------------------------------------------------------


def test_formatter_does_not_duplicate_normalization_or_matching():
    source = _source(formatter_module)
    for banned in ("def normalize_text", "normalize_text(", "_phrase_patterns",
                   "_GREETING_PHRASES", "_CONTRACTION_MAP", "_KNOWN_AGENT_ALIASES",
                   "_boundary("):
        assert banned not in source, banned
    assert "def sanitize" in source


def test_intent_engine_does_not_duplicate_goal_parser_task_logic():
    source = _source(intent_module)
    for banned in ("app.core.gambit", "GoalIntent", "task_decomposer", "import GoalParser"):
        assert banned not in source, banned


def test_comparison_knowledge_has_single_owner_per_concern():
    intent_source = _source(intent_module)
    formatter_source = _source(formatter_module)
    # Alias -> canonical mapping belongs to the classifier only.
    assert "_KNOWN_AGENT_ALIASES" in intent_source
    assert "KNOWN_AGENT_FACTS" not in intent_source
    # Verified facts registry belongs to the formatter only.
    assert "KNOWN_AGENT_FACTS" in formatter_source
    assert "_KNOWN_AGENT_ALIASES" not in formatter_source
    # Every canonical alias the engine can produce is known to the formatter.
    engine = IntentEngine()
    for alias, canonical in (
        ("chatgpt", "ChatGPT"),
        ("claude", "Claude"),
        ("gemini", "Gemini"),
        ("github copilot", "GitHub Copilot"),
    ):
        result = engine.classify_detailed(f"compare samaktha to {alias}")
        assert result.comparison_target == canonical
        assert canonical in KNOWN_AGENT_FACTS


# ---------------------------------------------------------------------------
# Orchestrator has no intent-specific branching
# ---------------------------------------------------------------------------


def test_orchestrator_has_no_intent_specific_branching():
    source = _source(engine_module)
    # No enum-member access, no intent constants, no per-intent comparisons.
    assert not re.search(r"ConversationIntent\.\w", source)
    assert "COMPARISON" not in source
    assert "== ConversationIntent" not in source
    # The classification result is passed straight through, uniformly.
    assert "classify_detailed" in source


def test_orchestrator_wires_detailed_classification_uniformly():
    source = _source(engine_module)
    assert source.count("classify_detailed(") == 2


# ---------------------------------------------------------------------------
# Formatting purity (behavioral)
# ---------------------------------------------------------------------------


def test_formatting_is_deterministic_pure_function():
    formatter = ResponseFormatter()
    first = formatter.format(
        None, "raw", conversation_intent=ConversationIntent.COMPARISON,
        comparison_target="Claude",
    )
    second = formatter.format(
        None, "raw", conversation_intent=ConversationIntent.COMPARISON,
        comparison_target="Claude",
    )
    assert first == second
    assert "Claude" in first


@pytest.mark.parametrize(
    "intent,expected",
    [
        (ConversationIntent.UNKNOWN, "I can't determine that from my available knowledge."),
        (
            ConversationIntent.COMPARISON,
            "There is no objective benchmark.",
        ),
    ],
)
def test_uncertainty_paths_are_stable_without_content(intent, expected):
    formatter = ResponseFormatter()
    text = formatter.format(None, "", conversation_intent=intent)
    assert text == expected
