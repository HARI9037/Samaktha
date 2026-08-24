"""Phase 10C + 11.3 + 11.5 + 11.6 — Deterministic Response Formatter.

The final presentation layer of the production runtime. It turns the raw
provider output of one interaction into the natural response the user sees,
for both the API and the TUI, so both surfaces always surface identical text.

The formatter is a pure, stateless, provider-independent function of a
ConversationIntent (produced by the Phase 11.3 IntentEngine), the structured
personality data (the PersonalityEvaluation, which already carries the
greeting kind, the profile capabilities, the visible memories and the
visibility summary) plus the raw provider text. It performs no retrieval, no
planning, no storage access, no LLM calls, and — critically — no raw-text
matching of its own: it switches ONLY on the ConversationIntent enum.

Deterministic behaviors:
    - GREETING      -> a short welcome (never a memory dump)
    - WHO_ARE_YOU / CREATOR -> the creator answer
    - WHAT_ARE_YOU  -> a natural description of what Samaktha is
    - CAPABILITIES / HELP -> a natural capability list
    - MEMORY_RECALL -> a direct recall answer or the uncertainty line
    - DELETE_MEMORY -> a confirmation
    - ARCHITECTURE  -> the provider's explanation or an honest subsystem answer
    - VERSION       -> the Samaktha version
    - THANKS        -> a brief acknowledgment
    - GOODBYE       -> a farewell
    - COMPARISON    -> a deterministic comparison for Samaktha-known agents,
      the no-hallucination uncertainty line for unknown targets, or the
      no-evidence line when no target is identifiable
    - everything else -> the raw text, sanitized so no internal identifiers
      (memory ids, UUIDs, ``allow:`` labels, subsystem names) ever leak out.

Phase 11.5 hardening guarantees:
    - the no-hallucination comparison policy: known agents get only their
      verified facts from a curated registry; unknown targets get the exact
      uncertainty line; nothing is ever fabricated about an external system
    - the uncertainty policy: memory with no verified basis and unanswerable
      questions resolve to the deterministic uncertainty lines, never to
      invented answers
    - consistent formatting: uniform bullets, no duplicated paragraphs, no
      empty markdown emphasis (``****``), no stray ``*``, and no missing list
      labels left behind when internal tokens are stripped

Phase 11.6 additions (all opt-in via the optional ``turn`` and
``previous_opening`` keyword arguments):
    - ``StyleController``-driven wording variation: greetings, closings,
      uncertainty lines, and the memory-recall preamble rotate deterministically
      by conversation turn; ``turn`` left None keeps every legacy string exact
    - duplicate-response prevention: when a response opens with the same
      paragraph as ``previous_opening``, a deterministic connector is prefixed
    - natural memory wording: recall never exposes memory ids, visibility
      rules, ``allow:`` labels, UUIDs, storage details, or the retrieval
      pipeline — only the remembered content
"""

from __future__ import annotations

import re
from typing import Any

from app.personality.models import (
    ConversationIntent,
    GreetingKind,
    IdentityProfile,
    PersonalityEvaluation,
)
from app.personality.conversation_memory_synthesizer import ConversationMemorySynthesizer
from app.personality.style_controller import (
    CANT_DETERMINE_VARIANTS,
    GOODBYE_VARIANTS,
    STYLE_CONTROLLER,
    THANKS_VARIANTS,
    UNCERTAIN_MEMORY_VARIANTS,
)
from app.runtime.execution_truth import enforce_execution_truth

CREATOR_IDENTITY_TEXT = (
    "I was designed and built by Sreehari R Nair as part of the Samaktha project."
)
WHAT_ARE_YOU_TEXT = (
    "I am Samaktha, a local-first AI operating system built around CAP, GAMBIT, "
    "Runtime, Memory, and Tool orchestration: a governance-first pipeline that "
    "plans my steps, decides what is safe, and executes them through a secure "
    "local runtime that remembers across sessions."
)
HELP_TEXT = (
    "I can plan and execute multi-step tasks with governance approval, read "
    "and summarize files, documents, and projects, write and refactor code, "
    "run commands through approved tools, and remember preferences, projects, "
    "and workflows across sessions. What would you like me to do?"
)
UNCERTAIN_MEMORY_TEXT = UNCERTAIN_MEMORY_VARIANTS[0]
CANT_DETERMINE_TEXT = CANT_DETERMINE_VARIANTS[0]
NO_COMPARISON_EVIDENCE_TEXT = "There is no objective benchmark."
UNKNOWN_AGENT_COMPARISON_TEXT = "There is no objective benchmark for {agent}."
GREETING_HEY_TEXT = "Hey. Good to see you again."
MEMORY_DELETED_TEXT = "I've removed those preferences from my long-term memory."
MEMORY_DELETE_UNCERTAIN_TEXT = "I couldn't find any stored memories to remove, so nothing was deleted."
DENIED_BY_USER_TEXT = "Operation cancelled.\nPermission denied by user."
SENSITIVE_OUTPUT_TEXT = "I can't share that — the output contained sensitive data."
GOODBYE_TEXT = GOODBYE_VARIANTS[0]
THANKS_TEXT = THANKS_VARIANTS[0]
ARCHITECTURE_FALLBACK_TEXT = (
    "I work as a pipeline of specialized subsystems. CAP decides whether each "
    "action is safe, GAMBIT plans my steps, a workflow engine executes them "
    "through a secure runtime, and a local memory controller lets me remember "
    "across sessions."
)

# Phase 11.5 — no-hallucination comparison policy. Curated, verified facts about
# Samaktha-known external systems, authored deterministically. These are the ONLY
# external-system claims the formatter ever makes; everything else resolves to an
# uncertainty line. Facts are deliberately generic (category + maker) so nothing
# is fabricated about capabilities, features, or architecture we cannot verify.
KNOWN_AGENT_FACTS = {
    "ChatGPT": "is a cloud-hosted conversational AI assistant made by OpenAI.",
    "Claude": "is a cloud-hosted conversational AI assistant made by Anthropic.",
    "Gemini": "is a cloud-hosted conversational AI assistant made by Google.",
    "GitHub Copilot": "is a code-assistance tool that lives inside an editor.",
    "Llama": "is an open-weight family of large language models from Meta.",
    "Mistral": "is a company that publishes open and hosted language models.",
    "DeepSeek": "is a company that publishes open-weight language models.",
}

COMPARISON_PREAMBLE = (
    "I'm Samaktha. Structured comparison"
)
COMPARISON_CLOSING = (
    "Conclusion: the best choice depends on the task and available evidence."
)


def _detect_version() -> str:
    from app import __version__

    return __version__


SAMAKTHA_VERSION = _detect_version()
VERSION_TEXT = f"I am Samaktha, version {SAMAKTHA_VERSION} of the Samaktha project."

_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_BLOCKED_BY_CAP_RE = re.compile(r"\[BLOCKED BY CAP\][^\n]*", re.IGNORECASE)
_CAP_TOKEN_RE = re.compile(r"\bCAP\b")
_GAMBIT_TOKEN_RE = re.compile(r"\bGAMBIT\b")

# Internal names that must never reach the user in ordinary conversation.
_BANNED_PHRASES = (
    "MemoryController",
    "PromptComposer",
    "PromptComposition",
    "VisibilityPolicy",
    "BehaviorDecision",
    "ReflectionReport",
    "MemoryVisibilityPolicy",
    "PersonalityEngine",
    "WorkflowEngine",
    "memory_id",
    "allow:",
    "retrieval score",
    "workflow node",
    "memory controller",
    "memory controller ",
    "Memory Controller",
    "execution_report",
    "response_model",
    "raw_output",
    "tool_result",
    "model_id",
    "task_id",
    "plan_id",
    "workflow_id",
    "session_id",
)

_GREETING_BY_KIND = {
    GreetingKind.GOOD_MORNING: "Good morning! How can I help you today?",
    GreetingKind.GOOD_AFTERNOON: "Good afternoon! How can I help you today?",
    GreetingKind.GOOD_EVENING: "Good evening! How can I help you today?",
    GreetingKind.HOW_ARE_YOU: "I'm doing well, thanks. How can I help you today?",
    GreetingKind.WHATS_UP: "Not much — how can I help you today?",
}


def _coerce_evaluation(evaluation: Any) -> PersonalityEvaluation | None:
    """Accept a PersonalityEvaluation, its model_dump dict, or None."""
    if evaluation is None:
        return None
    if isinstance(evaluation, PersonalityEvaluation):
        return evaluation
    if isinstance(evaluation, dict):
        try:
            return PersonalityEvaluation.model_validate(evaluation)
        except Exception:
            return None
    return None


def _coerce_intent(intent: ConversationIntent | str | None) -> ConversationIntent:
    """Accept a ConversationIntent, its string value, or None."""
    if intent is None:
        return ConversationIntent.UNKNOWN
    if isinstance(intent, ConversationIntent):
        return intent
    try:
        return ConversationIntent(intent)
    except ValueError:
        return ConversationIntent.UNKNOWN


def _report_confirms_memory_deletion(execution_report: dict | None) -> bool:
    """True only when a completed memory tool result shows something was deleted.

    The DELETE_MEMORY confirmation is an execution claim, so it must never be
    asserted without runtime evidence that a memory-delete tool actually
    removed at least one item.
    """
    if not execution_report:
        return False
    for result in execution_report.get("tool_results") or []:
        if not isinstance(result, dict) or result.get("status") != "completed":
            continue
        output = result.get("output")
        if not isinstance(output, dict):
            continue
        action = output.get("action")
        if action == "delete":
            if output.get("deleted") or (
                isinstance(output.get("count"), (int, float)) and output["count"] > 0
            ):
                return True
        elif action == "delete_type":
            if isinstance(output.get("deleted"), (int, float)) and output["deleted"] > 0:
                return True
        elif action == "delete_session":
            if output.get("deleted") is True:
                return True
        elif action == "delete_all":
            memories = output.get("memories")
            if isinstance(memories, dict) and any(
                isinstance(value, (int, float)) and value > 0
                for value in memories.values()
            ):
                return True
            if isinstance(output.get("sessions"), (int, float)) and output["sessions"] > 0:
                return True
    return False


class ResponseFormatter:
    """Deterministic final presentation layer for one interaction response."""

    def __init__(
        self,
        profile: IdentityProfile | None = None,
        capability_registry: object | None = None,
    ) -> None:
        self._profile = profile
        self._capability_registry = capability_registry
        self._synthesizer = ConversationMemorySynthesizer()

    def format(
        self,
        evaluation: PersonalityEvaluation | dict | None,
        raw_response: str,
        *,
        conversation_intent: ConversationIntent | str | None = None,
        comparison_target: str | None = None,
        turn: int | None = None,
        previous_opening: str | None = None,
        sources: list[dict] | None = None,
        execution_report: dict | None = None,
    ) -> str:
        """Format the raw provider response for the user.

        Switches only on the given ConversationIntent — never on raw text.
        ``comparison_target`` carries the canonical name extracted by the
        IntentEngine for COMPARISON requests; the formatter never parses it out
        of the raw text itself. Identical inputs always produce an identical
        string.

        Phase 11.6: ``turn`` (conversation turn) and ``previous_opening``
        (last response's first paragraph) are optional and opt-in. When both
        are None every legacy string is byte-identical to earlier phases.

        Phase 12.8: ``sources`` is an optional list of SourceMetadata-style
        dicts. When provided, the formatter deterministically appends a
        ``Sources:`` block so internet-sourced answers always attribute their
        claims — the LLM is never trusted to remember to cite.
        """
        intent = _coerce_intent(conversation_intent)
        evaluation = _coerce_evaluation(evaluation)

        if intent == ConversationIntent.GREETING:
            kind = evaluation.greeting.kind if evaluation is not None else None
            return self._greeting(kind, turn)
        if intent in (ConversationIntent.WHO_ARE_YOU, ConversationIntent.CREATOR):
            return CREATOR_IDENTITY_TEXT
        if intent == ConversationIntent.WHAT_ARE_YOU:
            return WHAT_ARE_YOU_TEXT
        if intent in (ConversationIntent.CAPABILITIES, ConversationIntent.HELP):
            return self._capabilities(evaluation)
        if intent == ConversationIntent.MEMORY_RECALL:
            return self._memory_recall(evaluation, turn)
        if intent == ConversationIntent.DELETE_MEMORY:
            if _report_confirms_memory_deletion(execution_report):
                return MEMORY_DELETED_TEXT
            return MEMORY_DELETE_UNCERTAIN_TEXT
        if intent == ConversationIntent.ARCHITECTURE:
            if raw_response and raw_response.strip():
                return STYLE_CONTROLLER.vary_opening(
                    raw_response, previous_opening, turn)
            return ARCHITECTURE_FALLBACK_TEXT
        if intent == ConversationIntent.VERSION:
            return VERSION_TEXT
        if intent == ConversationIntent.THANKS:
            return STYLE_CONTROLLER.vary_closing(THANKS_TEXT, turn)
        if intent == ConversationIntent.GOODBYE:
            return STYLE_CONTROLLER.vary_closing(GOODBYE_TEXT, turn)
        if intent == ConversationIntent.COMPARISON:
            return self._comparison(comparison_target)
        # Phase 11.5 uncertainty policy: a request that cannot be classified and
        # produced no content must not be answered with an invented response.
        if intent == ConversationIntent.UNKNOWN:
            if not raw_response or not raw_response.strip():
                return STYLE_CONTROLLER.vary_uncertainty(CANT_DETERMINE_TEXT, turn)
            text = self.sanitize(raw_response)
            if sources:
                text = self._append_sources(text, sources)
            text = enforce_execution_truth(text, execution_report)
            return STYLE_CONTROLLER.vary_opening(text, previous_opening, turn)
        text = self.sanitize(raw_response)
        if sources:
            text = self._append_sources(text, sources)
        text = enforce_execution_truth(text, execution_report)
        return STYLE_CONTROLLER.vary_opening(text, previous_opening, turn)

    def format_error(self, error: str | None) -> str:
        """Format an internal error message into natural user-facing text."""
        if not error:
            return ""
        lowered = error.lower()
        if any(
            token in lowered
            for token in ("governance", "cap governance", "blocked by cap")
        ):
            return DENIED_BY_USER_TEXT
        return self.sanitize(error)

    @staticmethod
    def _append_sources(text: str, sources: list[dict]) -> str:
        """Deterministically append a ``Sources:`` attribution block.

        Phase 12.8 — the final presentation layer guarantees that every
        internet-sourced answer carries its citations regardless of what the
        provider emitted. Empty or malformed entries are skipped; the block is
        only added when at least one valid source exists.
        """
        valid = [
            s for s in sources
            if isinstance(s, dict) and s.get("url") and (s.get("title") or s.get("domain"))
        ]
        if not valid:
            return text

        lines = [f"- {s.get('title') or s.get('domain')} — {s['url']}" for s in valid]
        block = "Sources:\n" + "\n".join(lines)
        stripped = text.rstrip()
        return stripped + "\n\n" + block if stripped else block

    @staticmethod
    def opening_paragraph(text: str) -> str:
        """The first paragraph of a response (used to track repeated openings).

        Exposed so the orchestrator can record the previous response's opening
        in the session's short-lived conversation state for Phase 11.6
        duplicate-response prevention. Pure and stateless.
        """
        return STYLE_CONTROLLER.opening_paragraph(text)

    @staticmethod
    def _greeting(kind: GreetingKind | None, turn: int | None = None) -> str:
        base = _GREETING_BY_KIND.get(kind, GREETING_HEY_TEXT)
        return STYLE_CONTROLLER.vary_greeting(base, turn)

    def _capabilities(self, evaluation: PersonalityEvaluation | None) -> str:
        if self._capability_registry is not None:
            entries = self._capability_registry.advertised_entries()
            if entries:
                bullets: list[str] = []
                for entry in entries:
                    actions = ", ".join(entry.supported_actions)
                    if entry.availability.value == "simulated":
                        qualifier = "simulated locally; no external delivery"
                    elif entry.availability.value == "local_only":
                        qualifier = "local only"
                    else:
                        qualifier = "production ready"
                    bullets.append(
                        f"- {entry.domain}: {qualifier}"
                        + (f" ({actions})" if actions else "")
                    )
                return "Here's what I can help with:\n" + "\n".join(bullets)
        if evaluation is not None and evaluation.profile is not None:
            capabilities = list(evaluation.profile.capabilities)
            if capabilities:
                bullets = "\n".join(f"- {cap}" for cap in capabilities)
                return f"Here's what I can help with:\n{bullets}"
        return HELP_TEXT

    def _memory_recall(
        self,
        evaluation: PersonalityEvaluation | None,
        turn: int | None = None,
    ) -> str:
        if evaluation is None:
            return STYLE_CONTROLLER.vary_uncertainty(UNCERTAIN_MEMORY_TEXT, turn)
        items = [memory for memory in evaluation.visible_memories if memory.content]
        if not items:
            return STYLE_CONTROLLER.vary_uncertainty(UNCERTAIN_MEMORY_TEXT, turn)
        if evaluation.visibility_summary is not None or len(items) > 1:
            return self._synthesizer.synthesize(evaluation, mode="auto")
        return items[0].content

    @staticmethod
    def _comparison(target: str | None) -> str:
        """Render a deterministic comparison under the no-hallucination policy.

        - no target  -> the no-evidence uncertainty line
        - known agent -> the preamble + that agent's verified fact + a neutral
          closing (never fabricated capabilities, features, or architecture)
        - unknown target -> the exact "not enough verified information" line
        """
        if not target:
            return NO_COMPARISON_EVIDENCE_TEXT
        fact = KNOWN_AGENT_FACTS.get(target)
        if fact is None:
            return "\n\n".join(
                (
                    COMPARISON_PREAMBLE,
                    UNKNOWN_AGENT_COMPARISON_TEXT.format(agent=target),
                    COMPARISON_CLOSING,
                )
            )
        return "\n\n".join(
            (
                COMPARISON_PREAMBLE,
                f"{target} {fact}",
                COMPARISON_CLOSING,
            )
        )

    @staticmethod
    def sanitize(text: str) -> str:
        """Strip internal identifiers and subsystem names from free text."""
        if not text:
            return ""
        cleaned = _BLOCKED_BY_CAP_RE.sub(SENSITIVE_OUTPUT_TEXT, text)
        for phrase in _BANNED_PHRASES:
            cleaned = cleaned.replace(phrase, "")
            cleaned = cleaned.replace(phrase.lower(), "")
        cleaned = _UUID_RE.sub("", cleaned)
        cleaned = _CAP_TOKEN_RE.sub("", cleaned)
        cleaned = _GAMBIT_TOKEN_RE.sub("", cleaned)
        lines = []
        for line in cleaned.splitlines():
            line = re.sub(r" {2,}", " ", line).strip()
            if not line:
                continue
            line = _clean_markdown(line)
            line = re.sub(r" {2,}", " ", line).strip()
            if not line:
                continue
            line = _clean_bullet_labels(line)
            if line:
                lines.append(line)
        return "\n".join(lines)


def _clean_markdown(line: str) -> str:
    """Remove empty emphasis markers left by internal-token stripping.

    Stripping a token from ``**CAP**`` leaves ``****`` (rendered as blank
    emphasis), from ``**CAP:**`` leaves ``**:**`` (an empty bold label), and
    from ``*CAP*`` leaves a dangling ``**``. Collapse only emphasis that wraps
    nothing (or at most a couple of punctuation/whitespace artifacts), never
    legitimate italic spans; then drop asterisks only when the line is left
    unbalanced (corrupt). Balanced emphasis and ordinary asterisks such as
    ``2 * 3`` survive unless the line is unbalanced.
    """
    line = re.sub(r"\*\*[\W_]{0,3}\*\*", "", line)
    line = re.sub(r"\*[\W_]{0,3}\*", "", line)
    if line.count("*") % 2 == 1:
        line = line.replace("*", "")
    return line


def _clean_bullet_labels(line: str) -> str:
    """Repair list items whose label was stripped with the internal token.

    ``- CAP: foo`` loses its label to ``- : foo``; restore the bullet marker so
    the item keeps its shape instead of rendering as a missing label. Drop list
    markers that are left entirely empty.
    """
    line = re.sub(r"^(-\s*|\d+\.\s*)[:.,]+\s*", r"\1", line)
    line = re.sub(r"^-\s*$", "", line)
    line = re.sub(r"^\d+\.\s*$", "", line)
    return line.strip()
