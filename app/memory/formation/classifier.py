"""Phase 8.2 — Deterministic Memory Classifier.

Classifies a completed interaction (user message + assistant response)
into typed memory candidates:

    preference, project, workflow, tool, knowledge

Conversation turns and successfully-read documents are persisted by the
caller (the orchestrator) and by the existing document persistence path —
this classifier focuses on the *additional* long-term memories that should
be formed automatically from normal conversation.

The classifier is purely rule-based and local: no LLM calls, no network
access, no embeddings.  Everything is deterministic.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOISE_PHRASES = frozenset(
    {
        "hello", "hi", "hey", "yo", "hola", "hiya",
        "good morning", "good afternoon", "good evening", "good night",
        "thanks", "thank you", "thanks a lot", "thanks so much", "thx", "ty",
        "ok", "okay", "ok ok", "kk", "k",
        "yes", "yeah", "yep", "yup", "yah", "ok yes",
        "no", "nope", "nah", "not really",
        "sure", "sure thing", "got it", "roger", "understood", "copy",
        "great", "awesome", "nice", "cool", "perfect", "good", "fine", "ok good",
        "done", "all good", "no problem", "no worries", "sounds good", "sounds great",
        "well done", "good job", "nice work", "agreed", "right", "right on",
        "bye", "goodbye", "see you", "good luck", "welcome", "lol", "haha",
        "hehe", "hmm", "um", "oh", "oh ok", "ok cool", "cool ok", "alright",
        "okie", "okay okay", "sweet", "cheers", "brb", "g2g", "ttyl",
    }
)

# Short words that only ever signal acknowledgement (used to catch 1-2 word
# replies that the phrase list does not enumerate).
_SHORT_NOISE_WORDS = frozenset(
    {
        "ok", "okay", "kk", "k", "sure", "yes", "yeah", "yep", "yup", "yah",
        "no", "nope", "nah", "hi", "hey", "yo", "thx", "ty", "thanks", "great",
        "awesome", "nice", "cool", "fine", "good", "done", "lol", "haha",
        "hmm", "um", "oh", "sweet", "cheers", "bye", "right", "roger", "got",
    }
)

# Developer tools / frameworks that turn "I use X" into a TOOL memory.
# OS names, IDEs, and languages intentionally stay in the preference bucket.
_DEV_TOOL_NAMES = frozenset(
    {
        "git", "github", "gitlab", "bitbucket", "docker", "docker-compose",
        "kubernetes", "k8s", "helm", "terraform", "ansible", "jenkins",
        "fastapi", "flask", "django", "rails", "spring", "express", "nest",
        "next", "nextjs", "nuxt", "sveltekit", "remix", "gatsby", "hugo",
        "react", "angular", "vue", "svelte", "jquery", "htmx",
        "node", "nodejs", "deno", "bun", "php", "laravel",
        "npm", "yarn", "pnpm", "pip", "pipenv", "poetry", "conda",
        "make", "cmake", "gradle", "maven", "bazel", "cargo",
        "tensorflow", "pytorch", "jupyter", "jupyterlab",
        "redis", "postgresql", "postgres", "mysql", "mongodb", "sqlite",
        "cockroachdb", "dynamodb", "graphql", "grpc", "rest", "tailwind",
        "bootstrap", "sass", "less", "styled-components",
        "webpack", "vite", "rollup", "esbuild", "eslint", "prettier",
        "pytest", "jest", "vitest", "cypress", "playwright", "selenium",
        "kafka", "rabbitmq", "celery", "airflow", "spark", "hadoop",
        "openai", "groq", "huggingface", "transformers", "ollama", "llama",
        "fastapi", "uvicorn", "gunicorn", "nginx", "apache", "linux", "unix",
    }
)

_HABIT_ADVERBS = (
    "always", "usually", "typically", "often", "sometimes", "generally",
    "normally", "mostly", "regularly", "really", "definitely",
)

# Subjects that make a "X is Y" sentence conversational rather than factual.
_BANNED_SUBJECT_STARTS = (
    "this", "that", "these", "those", "it", "its", "it's",
    "i", "you", "we", "they", "he", "she", "my", "your", "our", "their",
    "there", "here", "who", "what", "why", "how", "which", "when", "where",
)

# Small stopword set used for the response-echo confirmation signal.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "if", "of", "to", "for", "on",
        "with", "at", "by", "from", "in", "out", "over", "under", "is", "are",
        "was", "were", "be", "been", "being", "have", "has", "had", "do",
        "does", "did", "will", "would", "could", "should", "may", "might",
        "shall", "can", "i", "you", "we", "they", "he", "she", "it", "my",
        "your", "our", "their", "his", "her", "its", "this", "that", "these",
        "those", "there", "here", "then", "than", "so", "just", "very",
        "really", "also", "use", "using", "about", "into", "through", "during",
        "before", "after", "not", "no", "yes", "what", "which", "who", "whom",
        "why", "how", "when", "where", "me", "him", "us", "them", "am",
    }
)


# ---------------------------------------------------------------------------
# Classification result
# ---------------------------------------------------------------------------


@dataclass
class Classification:
    """A typed memory candidate extracted from a user message."""

    memory_type: str
    content: str
    importance_kind: str
    confidence: float
    reason: str
    tags: list[str] = field(default_factory=list)
    entity: str | None = None


# ---------------------------------------------------------------------------
# Pattern library
# ---------------------------------------------------------------------------

_PREFERENCE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            r"\bi\s+(?:really\s+|definitely\s+|kind\s+of\s+|sort\s+of\s+)?"
            r"(?:like|love|prefer|enjoy|hate|dislike)\s+(.+)$",
            re.IGNORECASE,
        ),
        "stated preference",
    ),
    (
        re.compile(r"\bmy\s+favou?rite\s+(.+?)\s+(?:is|are)\s+(.+)$", re.IGNORECASE),
        "favourite statement",
    ),
    (
        re.compile(
            r"\bi\s+(?:" + "|".join(rf"{a}\s+" for a in _HABIT_ADVERBS) + r")?"
            r"use\s+(.+)$",
            re.IGNORECASE,
        ),
        "tool-like preference",
    ),
    (
        re.compile(
            r"\bi\s+(?:am|'m)\s+(?:a|an)\s+(.+?\s+(?:user|developer|fan|enthusiast|person))$",
            re.IGNORECASE,
        ),
        "identity preference",
    ),
    (
        re.compile(r"\bi\s+(?:do\s+not|don't|dont)\s+(?:like|prefer)\s+(.+)$", re.IGNORECASE),
        "negative preference",
    ),
    (
        re.compile(r"\bi'?d\s+(?:rather|prefer)\s+(.+)$", re.IGNORECASE),
        "stated preference",
    ),
]

_PROJECT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            r"\bi'?m\s+(?:building|creating|developing|making|designing|architecting|"
            r"implementing|working\s+on|starting|launching|shipping)\s+(.+)$",
            re.IGNORECASE,
        ),
        "active project",
    ),
    (
        re.compile(
            r"\bmy\s+(.+?)\s+(?:project|app|application|startup|product|software)\s+"
            r"(?:is|will|should|aims|uses|focuses)\s+(.+)$",
            re.IGNORECASE,
        ),
        "project detail",
    ),
    (
        re.compile(r"\bproject\s+(?:named|called)\s+([\w][\w\s-]*)$", re.IGNORECASE),
        "project name",
    ),
    (
        re.compile(
            r"\bthe\s+(.+?)\s+project\s+(?:is|will|uses|needs|should|aims)\s+(.+)$",
            re.IGNORECASE,
        ),
        "project description",
    ),
]

_WORKFLOW_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"\bmy\s+workflow\s+is\s+(.+)$", re.IGNORECASE),
        "stated workflow",
    ),
    (
        re.compile(
            r"\bi\s+(?:" + "|".join(rf"{a}\s+" for a in _HABIT_ADVERBS) + r")"
            r"(?!use\b)(.+)$",
            re.IGNORECASE,
        ),
        "habitual workflow",
    ),
    (
        re.compile(
            r"\bwhen\s+(?:i|we|you)\s+(?:debug|build|test|code|write|review|refactor|"
            r"develop|run|deploy|work|troubleshoot|investigate)\s+(.+)$",
            re.IGNORECASE,
        ),
        "conditional workflow",
    ),
    (
        re.compile(r"\bi\s+(?:start|begin)\s+(?:by|with|from)\s+(.+)$", re.IGNORECASE),
        "starting routine",
    ),
    (
        re.compile(
            r"\bi\s+follow(?:ing)?\s+(?:this|the|a)?\s*(?:workflow|process|routine|steps?|method)"
            r"[:.]?\s*(.+)$",
            re.IGNORECASE,
        ),
        "followed process",
    ),
]

_KNOWLEDGE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"\b(?P<subject>[\w][\w\s]{1,60}?)\s+(?:is|are)\s+(?P<value>.+)$", re.IGNORECASE),
        "factual copula",
    ),
    (
        re.compile(r"\b(?P<subject>[\w][\w\s]{1,60}?)\s+(?:was|were)\s+(?P<value>.+)$", re.IGNORECASE),
        "historical fact",
    ),
    (
        re.compile(
            r"\b(?P<subject>[\w][\w\s]{1,60}?)\s+(?:means?|stands\s+for|refers\s+to)\s+(?P<value>.+)$",
            re.IGNORECASE,
        ),
        "definition",
    ),
    (
        re.compile(r"\b(?P<subject>[\w][\w\s]{1,60}?)\s+uses\s+(?P<value>.+)$", re.IGNORECASE),
        "technology fact",
    ),
]


def _clean(text: str) -> str:
    """Trim and strip trailing sentence punctuation."""
    return re.sub(r"\s+", " ", text).strip().rstrip(".!?;,")


def _is_noise(text: str) -> bool:
    """True when the message is obvious conversation filler / emoji-only."""
    stripped = " ".join(text.strip().lower().split())
    if not stripped:
        return True

    alnum = re.sub(r"[^\w\s]", "", stripped)
    if not alnum.strip():
        return True  # emoji-only / symbol-only

    core = stripped.rstrip(".!?;,")
    if core in _NOISE_PHRASES:
        return True

    words = core.split()
    if len(words) <= 2 and all(w in _SHORT_NOISE_WORDS for w in words):
        return True

    return False


class MemoryClassifier:
    """Rule-based classifier that maps a user message to a typed memory."""

    def classify(
        self,
        user_message: str,
        assistant_response: str = "",
    ) -> Classification | None:
        """Return a typed memory candidate, or None when nothing is worth storing.

        The assistant response is inspected only to strengthen confidence via
        echo-confirmation; it never creates a typed memory on its own.
        """
        if not user_message or not isinstance(user_message, str):
            return None

        text = _clean(user_message)
        if _is_noise(text):
            return None

        is_question = text.rstrip().endswith("?")

        tool = self._detect_tool(text)
        if tool:
            return tool

        preference = self._detect_preference(text)
        if preference:
            return preference

        # Questions do not form typed memories (they are not statements).
        if is_question:
            return None

        project = self._detect_project(text)
        if project:
            return project

        workflow = self._detect_workflow(text)
        if workflow:
            return workflow

        knowledge = self._detect_knowledge(text)
        if knowledge:
            return knowledge

        return None

    # ------------------------------------------------------------------
    # Per-type detectors
    # ------------------------------------------------------------------

    def _detect_tool(self, text: str) -> Classification | None:
        """"I use Docker", "I always use Git", "My default stack is FastAPI"."""
        use_match = re.search(
            r"\bi\s+(?:" + "|".join(rf"{a}\s+" for a in _HABIT_ADVERBS) + r")?"
            r"use\s+([a-zA-Z0-9_.+-]+)",
            text,
            re.IGNORECASE,
        )
        if use_match:
            entity = use_match.group(1).strip(".,;:()").lower()
            if entity in _DEV_TOOL_NAMES:
                habitual = any(
                    re.search(rf"\b{a}\s+", text, re.IGNORECASE) for a in _HABIT_ADVERBS
                )
                return Classification(
                    memory_type="tool",
                    content=text,
                    importance_kind="frequent_skill" if habitual else "tool_output",
                    confidence=1.0,
                    reason=f"tool usage: {entity}",
                    tags=["tool", entity],
                    entity=entity,
                )

        stack_match = re.search(
            r"\bmy\s+(?:default|go-to|preferred)\s+(?:tool|stack|framework|library)\s+"
            r"(?:is|are)\s+([a-zA-Z0-9_.+-]+)",
            text,
            re.IGNORECASE,
        )
        if stack_match:
            entity = stack_match.group(1).strip(".,;:()").lower()
            if entity in _DEV_TOOL_NAMES:
                return Classification(
                    memory_type="tool",
                    content=text,
                    importance_kind="frequent_skill",
                    confidence=1.0,
                    reason=f"preferred stack: {entity}",
                    tags=["tool", entity],
                    entity=entity,
                )

        return None

    def _detect_preference(self, text: str) -> Classification | None:
        """"I like C++", "I prefer VS Code", "I use Windows", favourite IDE."""
        for pattern, reason in _PREFERENCE_PATTERNS:
            match = pattern.search(text)
            if match:
                return Classification(
                    memory_type="preference",
                    content=text,
                    importance_kind="user_preference",
                    confidence=1.0,
                    reason=reason,
                    tags=["preference"],
                )
        return None

    def _detect_project(self, text: str) -> Classification | None:
        """"I'm building Samaktha", "I'm working on CAP", "My drone project...".
        """
        for pattern, reason in _PROJECT_PATTERNS:
            match = pattern.search(text)
            if match:
                return Classification(
                    memory_type="project",
                    content=text,
                    importance_kind="user_preference",
                    confidence=1.0,
                    reason=reason,
                    tags=["project", "knowledge"],
                )
        return None

    def _detect_workflow(self, text: str) -> Classification | None:
        """"My workflow is...", "I always...", "When debugging I...".
        """
        for pattern, reason in _WORKFLOW_PATTERNS:
            match = pattern.search(text)
            if match:
                return Classification(
                    memory_type="workflow",
                    content=text,
                    importance_kind="successful_workflow",
                    confidence=0.8,
                    reason=reason,
                    tags=["workflow"],
                )
        return None

    def _detect_knowledge(self, text: str) -> Classification | None:
        """Declarative factual statements: "Samaktha is built with FastAPI."."""
        for pattern, reason in _KNOWLEDGE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            subject = match.group("subject").strip()
            value = match.group("value").strip()
            if not subject or not value:
                continue
            if subject.lower().split()[0] in _BANNED_SUBJECT_STARTS:
                continue
            # A factual claim needs a substantive predicate.
            if len(value.split()) < 2:
                continue
            return Classification(
                memory_type="knowledge",
                content=text,
                importance_kind="successful_workflow",
                confidence=0.8,
                reason=reason,
                tags=["knowledge"],
            )
        return None

    # ------------------------------------------------------------------
    # Confidence confirmation via the assistant's response
    # ------------------------------------------------------------------

    def confirm(self, classification: Classification, assistant_response: str) -> float:
        """Boost confidence when the assistant echoed the detected entity.

        The assistant response is inspected to satisfy the formation
        pipeline's "inspect the user message + inspect the assistant response"
        step without ever inventing memories from generated text.
        """
        if not assistant_response or classification.entity is None:
            return classification.confidence

        lowered = assistant_response.lower()
        if classification.entity in lowered:
            return 1.0

        significant = {
            t
            for t in re.findall(r"[a-z0-9+]+", classification.content.lower())
            if len(t) > 2 and t not in _STOPWORDS
        }
        if significant and any(t in lowered for t in significant):
            return max(classification.confidence, 0.9)

        return classification.confidence
