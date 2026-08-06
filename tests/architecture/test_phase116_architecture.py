"""Phase 11.6 — architecture validation for conversation experience continuity.

Static + behavioral proof that the Phase 11.6 additions kept the architecture
rules intact:
    - no circular imports across the pipeline modules
    - the StyleController owns all wording variation and carries no dependency
      on personality engines, providers, memory, conversation, or core
    - the ResponseFormatter never duplicates the variation tables or the
      variant wording strings
    - the orchestrator passes the continuity hooks uniformly, with no
      intent-specific branching
    - the conversation package still has no personality/provider imports
"""

import importlib
import re
from pathlib import Path

import app.core.orchestrator.engine as engine_module
import app.personality.response_formatter as formatter_module
import app.personality.style_controller as style_module

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
        "app.personality.style_controller",
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
        assert "style_controller" not in text, source.name


# ---------------------------------------------------------------------------
# StyleController owns wording variation and has no dependencies
# ---------------------------------------------------------------------------


def test_style_controller_has_no_dependencies():
    source = _source(style_module)
    for banned in (
        "from app.", "import app.", "app.providers", "app.memory",
        "app.conversation", "app.core", "app.personality",
    ):
        assert banned not in source, banned
    assert "class StyleController" in source
    assert "_GREETING_VARIANTS" in source
    assert "OPENING_CONNECTORS" in source


def test_style_controller_has_no_response_text_from_other_owners():
    source = _source(style_module)
    for banned in ("I'm Samaktha", "Sreehari R Nair", "GOODBYE_TEXT =", "THANKS_TEXT ="):
        assert banned not in source, banned


# ---------------------------------------------------------------------------
# Formatter does not duplicate variation logic or wording
# ---------------------------------------------------------------------------


def test_formatter_owns_no_variation_tables():
    source = _source(formatter_module)
    for banned in (
        "_GREETING_VARIANTS",
        "_OPENING_CONNECTORS",
        "_GOODBYE_VARIANTS",
        "_THANKS_VARIANTS",
        "_RECALL_PREAMBLE_VARIANTS",
        "OPENING_CONNECTORS =",
    ):
        assert banned not in source, banned


def test_uncertainty_wording_lives_only_in_style_controller():
    source = _source(formatter_module)
    for variant in (
        "I don't know that yet.",
        "I can't determine that from what I know.",
        "I don't have enough information to answer that.",
    ):
        assert variant not in source, variant


def test_formatter_style_wiring_has_no_provider_or_memory_dependency():
    source = _source(formatter_module)
    for banned in (
        "app.providers", "app.memory", "app.conversation", "import app.core",
    ):
        assert banned not in source, banned
    assert "style_controller" in source
    assert "UNCERTAIN_MEMORY_VARIANTS" in source
    assert "CANT_DETERMINE_VARIANTS" in source


# ---------------------------------------------------------------------------
# Orchestrator passes continuity hooks uniformly (no intent branching)
# ---------------------------------------------------------------------------


def test_orchestrator_passes_continuity_hooks_uniformly():
    source = _source(engine_module)
    assert source.count("conversation_turn") == 2
    assert source.count("previous_opening") == 2
    assert source.count("last_opening") == 4
    assert not re.search(r"ConversationIntent\.\w", source)
    assert "== ConversationIntent" not in source


# ---------------------------------------------------------------------------
# Behavioral: orchestrated pipeline stays deterministic and pure
# ---------------------------------------------------------------------------


def test_formatter_turn_inputs_are_pure_and_deterministic():
    from app.personality import ConversationIntent, ResponseFormatter

    formatter = ResponseFormatter()
    first = formatter.format(
        None,
        "The build finished.",
        conversation_intent=ConversationIntent.UNKNOWN,
        turn=4,
        previous_opening="Different.",
    )
    second = formatter.format(
        None,
        "The build finished.",
        conversation_intent=ConversationIntent.UNKNOWN,
        turn=4,
        previous_opening="Different.",
    )
    assert first == second
