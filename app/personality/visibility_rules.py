"""Phase 9.2 — Deterministic memory-visibility rule detectors.

Pure string / timestamp logic. Every detector inspects the user message and
the metadata of already-retrieved memories (MemoryType, Importance, Recency,
Tags, Categories, source) and decides which memories are exposed. No LLM, no
embeddings, no retrieval, no prompts.

Rules 3-8 from the Phase 9.2 spec:

    3. Profile question     -> preference / workflow / project / knowledge / conversation
    4. Specific preference  -> only the matching preference
    5. Workflow continuation -> recent workflow / project memories (preferences suppressed)
    6. Document history      -> document memories only
    7. General technical     -> no memories
    8. Project status        -> project / workflow memories (no IDE preferences)

Rules 1-2 (greeting, identity) are owned by the MemoryVisibilityPolicy, which
holds the Identity/Greeting policies and applies them before this module runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from app.personality.models import MemoryVisibilityRule, PreferenceCategory

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^a-z0-9 ]")


@dataclass(frozen=True)
class MemoryView:
    """Normalized, read-only view of one retrieved memory item."""

    memory_id: str
    memory_type: str
    content: str
    tags: tuple[str, ...]
    entities: tuple[str, ...]
    source: str
    importance: float
    created_at: str
    last_accessed: str
    provenance: str = ""
    session_id: str = ""
    confidence: float = 0.0
    freshness: str = ""

    def is_project(self) -> bool:
        """Project memories are stored as knowledge tagged as a project."""
        return (
            self.memory_type == "project"
            or self.source == "project"
            or "project" in self.tags
        )


@dataclass(frozen=True)
class RuleMatch:
    """Outcome of rule detection: which rule matched and which memories it
    allows. ``rule_id`` is None when no rule matched (default pass-through)."""

    rule_id: str | None
    name: str | None
    allowed: list[MemoryView] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Item normalization
# ---------------------------------------------------------------------------


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize_item(item: Any) -> MemoryView | None:
    """Project an arbitrary retrieved item (MemoryItem, skill, DocumentRecord
    wrapper, ...) onto a MemoryView. Reads only the metadata it is given."""
    if item is None:
        return None
    meta = getattr(item, "metadata", None)
    if not isinstance(meta, dict):
        meta = {}
    memory_id = (
        getattr(item, "id", None)
        or getattr(item, "skill_id", None)
        or getattr(item, "document_id", None)
        or str(id(item))
    )
    return MemoryView(
        memory_id=str(memory_id),
        memory_type=str(meta.get("memory_type", "conversation")).strip().lower(),
        content=str(getattr(item, "content", "") or ""),
        tags=tuple(str(t).lower() for t in meta.get("tags", []) if t),
        entities=tuple(str(e).lower() for e in meta.get("entities", []) if e),
        source=str(meta.get("source", "") or "").lower(),
        importance=_to_float(meta.get("importance", 0.0)),
        created_at=str(meta.get("created_at", "") or ""),
        last_accessed=str(meta.get("last_accessed", "") or ""),
        provenance=str(meta.get("provenance", "") or ""),
        session_id=str(meta.get("session_id", "") or ""),
        confidence=_to_float(meta.get("confidence", 0.0)),
        freshness=str(meta.get("freshness", "") or ""),
    )


def _recency_key(view: MemoryView) -> str:
    """Sortable key: prefer last_accessed, fall back to created_at."""
    return view.last_accessed or view.created_at or ""


# ---------------------------------------------------------------------------
# Rule descriptors (spec numbering)
# ---------------------------------------------------------------------------

RULE_GREETING = MemoryVisibilityRule(
    rule_id="rule_1_greeting",
    name="greeting",
    description="Greeting turns expose no memories.",
)
RULE_IDENTITY = MemoryVisibilityRule(
    rule_id="rule_2_identity",
    name="identity_query",
    description="Identity questions expose no memories.",
)
RULE_PROFILE = MemoryVisibilityRule(
    rule_id="rule_3_profile",
    name="profile_question",
    description="Profile questions expose preference, workflow, project, "
    "knowledge and conversation memories.",
)
RULE_PREFERENCE = MemoryVisibilityRule(
    rule_id="rule_4_specific_preference",
    name="specific_preference",
    description="Specific preference questions expose only the matching "
    "preference memory.",
)
RULE_WORKFLOW = MemoryVisibilityRule(
    rule_id="rule_5_workflow_continuation",
    name="workflow_continuation",
    description="Workflow continuation exposes recent workflow and project "
    "memories; preferences are suppressed.",
)
RULE_DOCUMENT = MemoryVisibilityRule(
    rule_id="rule_6_document_history",
    name="document_history",
    description="Document-history questions expose document memories only.",
)
RULE_TECHNICAL = MemoryVisibilityRule(
    rule_id="rule_7_general_technical",
    name="general_technical",
    description="General technical questions expose no memories.",
)
RULE_PROJECT = MemoryVisibilityRule(
    rule_id="rule_8_project_status",
    name="project_status",
    description="Project-status questions expose project, workflow and "
    "knowledge memories; IDE preferences are suppressed.",
)

# ---------------------------------------------------------------------------
# Rule 3 — profile questions
# ---------------------------------------------------------------------------

_PROFILE_TYPES = frozenset({"preference", "workflow", "knowledge", "conversation"})

_PROFILE_QUESTION_RE = re.compile(
    r"\bwhat\s+do\s+you\s+know\s+about\s+me\b"
    r"|\bwhat\s+do\s+you\s+remember\s+about\s+me\b"
    r"|\bwhat\s+do\s+you\s+have\s+on\s+me\b"
    r"|\bwhat\s+information\s+do\s+you\s+have\s+about\s+me\b"
    r"|\bwhat\s+facts\s+do\s+you\s+know\s+about\s+me\b"
    r"|\bwhat\s+do\s+you\s+know\s+about\s+the\s+user\b"
    r"|\btell\s+me\s+about\s+me\b"
    r"|\bsummarize\s+my\s+(?:profile|preferences)\b",
    re.IGNORECASE,
)


def _detect_profile(message: str, items: list[MemoryView]) -> list[MemoryView] | None:
    if not _PROFILE_QUESTION_RE.search(message):
        return None
    return [view for view in items if view.memory_type in _PROFILE_TYPES]


# ---------------------------------------------------------------------------
# Rule 4 — specific preference questions
# ---------------------------------------------------------------------------

_PREFERENCE_QUESTION_RE = re.compile(
    r"\b(?:which|what)\b[^?]{0,40}?\b(?:do|does|would|did)\b[^?]{0,20}?\b"
    r"(?:prefer|preferred|use|used|like|enjoy|recommend|recommended)\b",
    re.IGNORECASE,
)
_PREFERENCE_FAVOURITE_RE = re.compile(
    r"\bwhat(?:'?s| is)?\s+(?:my|your|the)?\s*"
    r"(?:favourite|favorite|preferred|go-to|default)\s+",
    re.IGNORECASE,
)

_PREFERENCE_CATEGORIES: tuple[
    tuple[PreferenceCategory, tuple[str, ...], tuple[str, ...]], ...
] = (
    (
        PreferenceCategory.LANGUAGE,
        ("programming language", "coding language", "language", "languages", "lang"),
        (
            "python", "javascript", "typescript", "js", "ts", "java", "c++", "cpp",
            "c#", "csharp", "c", "go", "golang", "rust", "swift", "kotlin", "ruby",
            "php", "perl", "r", "scala", "haskell", "elixir", "clojure", "dart",
            "lua", "shell", "bash", "powershell", "sql",
        ),
    ),
    (
        PreferenceCategory.FRAMEWORK,
        ("framework", "frameworks", "web framework", "backend framework", "frontend framework"),
        (
            "fastapi", "flask", "django", "rails", "spring", "express", "nestjs",
            "next.js", "nextjs", "nuxt", "sveltekit", "remix", "gatsby", "hugo",
            "react", "angular", "vue", "svelte", "jquery", "htmx", "tailwind",
            "bootstrap",
        ),
    ),
    (
        PreferenceCategory.IDE,
        ("ide", "editor", "code editor", "text editor"),
        (
            "vscode", "vs code", "visual studio", "pycharm", "intellij", "webstorm",
            "neovim", "vim", "emacs", "sublime", "atom", "zed", "xcode",
            "android studio", "eclipse", "netbeans", "jetbrains",
        ),
    ),
    (
        PreferenceCategory.OPERATING_SYSTEM,
        ("os", "operating system"),
        (
            "windows", "linux", "macos", "mac", "ubuntu", "debian", "fedora",
            "arch", "manjaro", "pop os", "freebsd", "chrome os",
        ),
    ),
    (
        PreferenceCategory.TERMINAL,
        ("terminal", "shell", "command line", "cli"),
        (
            "bash", "zsh", "fish", "pwsh", "powershell", "cmd", "tmux", "iterm",
            "alacritty", "wezterm", "kitty", "ghostty", "warp",
        ),
    ),
    (
        PreferenceCategory.DATABASE,
        ("database", "databases", "db", "sql database"),
        (
            "postgresql", "postgres", "mysql", "sqlite", "mongodb", "redis",
            "dynamodb", "cassandra", "cockroachdb", "elasticsearch", "oracle",
        ),
    ),
    (
        PreferenceCategory.BROWSER,
        ("browser", "web browser"),
        ("chrome", "firefox", "safari", "edge", "brave", "opera", "arc", "vivaldi"),
    ),
    (
        PreferenceCategory.TOOL,
        ("tool", "tools", "stack", "dev stack", "library", "package manager"),
        (
            "git", "github", "gitlab", "docker", "kubernetes", "k8s", "terraform",
            "ansible", "jenkins", "npm", "yarn", "pnpm", "pip", "poetry", "cargo",
            "pytest", "jest", "vitest", "playwright", "cypress", "tensorflow",
            "pytorch", "jupyter", "kafka",
        ),
    ),
    (
        PreferenceCategory.THEME,
        ("theme", "color scheme", "colorscheme"),
        ("dark", "light", "monokai", "dracula", "nord", "gruvbox", "solarized", "tokyonight"),
    ),
)

# Words that carry no matching signal inside a preference question.
_QUESTION_NOISE = frozenset(
    {
        "which", "what", "when", "where", "who", "why", "how", "do", "does",
        "did", "would", "should", "i", "you", "we", "my", "your", "our", "the",
        "a", "an", "me", "prefer", "preferred", "preferring", "use", "used",
        "using", "like", "liked", "enjoy", "recommend", "recommended",
        "favourite", "favorite", "go", "to", "is", "are", "am", "was", "were",
        "be", "it", "its", "in", "on", "at", "with", "of", "for",
    }
)


def _significant_nouns(message: str) -> set[str]:
    text = _NON_WORD_RE.sub(" ", message.lower())
    words = _WHITESPACE_RE.split(text)
    return {
        word
        for word in words
        if len(word) >= 2 and word not in _QUESTION_NOISE
    }


def _detect_preference_category(message: str) -> PreferenceCategory | None:
    lowered = message.lower()
    for category, markers, _ in _PREFERENCE_CATEGORIES:
        if any(marker in lowered for marker in markers):
            return category
    return None


def _preference_match_terms(
    message: str, category: PreferenceCategory | None
) -> set[str]:
    terms: set[str] = set()
    if category is not None:
        for cat, _markers, vocab in _PREFERENCE_CATEGORIES:
            if cat == category:
                terms.update(vocab)
                break
    nouns = _significant_nouns(message)
    for _cat, markers, _vocab in _PREFERENCE_CATEGORIES:
        nouns.difference_update(markers)
    terms.update(nouns)
    return {term for term in terms if len(term) >= 2}


def _matches_any(view: MemoryView, terms: set[str]) -> bool:
    if not terms:
        return False
    haystack = (
        f"{view.content} {' '.join(view.tags)} {' '.join(view.entities)}"
    ).lower()
    return any(term in haystack for term in terms)


def _detect_specific_preference(
    message: str, items: list[MemoryView]
) -> list[MemoryView] | None:
    if not (
        _PREFERENCE_QUESTION_RE.search(message)
        or _PREFERENCE_FAVOURITE_RE.search(message)
    ):
        return None
    category = _detect_preference_category(message)
    terms = _preference_match_terms(message, category)
    return [
        view
        for view in items
        if view.memory_type == "preference" and _matches_any(view, terms)
    ]


# ---------------------------------------------------------------------------
# Rule 5 — workflow continuation
# ---------------------------------------------------------------------------

_WORKFLOW_CONTINUATION_RE = re.compile(
    r"\b(?:continue|resume|carry\s+on|keep\s+going|pick\s+up\s+where)\b"
    r"|\bwhere\s+did\s+(?:we|i)\s+stop\b"
    r"|\bwhere\s+did\s+i\s+leave\s+off\b"
    r"|\bwhat\s+was\s+(?:i|we)\s+working\s+on\b"
    r"|\bwhat\s+were\s+we\s+working\s+on\b"
    r"|\bnext\s+step\b"
    r"|\byesterday'?s\s+work\b"
    r"|\b(?:last|previous)\s+session\b",
    re.IGNORECASE,
)


def _detect_workflow_continuation(
    message: str, items: list[MemoryView]
) -> list[MemoryView] | None:
    if not _WORKFLOW_CONTINUATION_RE.search(message):
        return None
    allowed = [
        view
        for view in items
        if view.memory_type == "workflow" or view.is_project()
    ]
    allowed.sort(key=_recency_key, reverse=True)
    return allowed


# ---------------------------------------------------------------------------
# Rule 6 — document-history questions
# ---------------------------------------------------------------------------

_DOCUMENT_QUESTION_RE = re.compile(
    r"\b(?:which|what)\b[^?]{0,40}?\b(?:pdf|doc|document|file|paper)s?\b"
    r"[^?]{0,40}?\b(?:read|open|summariz|view)\b"
    r"|\b(?:which|what)\b[^?]{0,40}?\b(?:read|open|summariz|view)\b"
    r"[^?]{0,40}?\b(?:today|yesterday|recently)\b"
    r"|\b(?:list|show|find|search)\b[^?]{0,30}?\b(?:doc|document|pdf|file)s?"
    r"|\bread(?:ing)?\s+history|\bdoc\w*\s+history"
    r"|\b(?:recent|last)\s+(?:doc|document|pdf|file)s?",
    re.IGNORECASE,
)


def _detect_document_question(
    message: str, items: list[MemoryView]
) -> list[MemoryView] | None:
    if not _DOCUMENT_QUESTION_RE.search(message):
        return None
    return [view for view in items if view.memory_type == "document"]


# ---------------------------------------------------------------------------
# Rule 8 — project-status questions (checked before rule 7)
# ---------------------------------------------------------------------------

_PROJECT_STATUS_RE = re.compile(
    r"\b(?:what|whats|what'?s|how|hows|how'?s)\b[^?]{0,40}?progress"
    r"|\b(?:what|whats|what'?s|how|hows|how'?s)\b[^?]{0,40}?\bstatus\b"
    r"|\b(?:progress|status)\b[^?]{0,40}\b(?:of|on|report)\b"
    r"|\bwhere\s+are\s+we\b"
    r"|\bhow\s+is\b[^?]{0,40}\b(?:coming\s+along|going)\b",
    re.IGNORECASE,
)


def _detect_project_status(
    message: str, items: list[MemoryView]
) -> list[MemoryView] | None:
    if not _PROJECT_STATUS_RE.search(message):
        return None
    allowed = [
        view for view in items if view.is_project() or view.memory_type == "workflow"
    ]
    allowed.sort(key=_recency_key, reverse=True)
    return allowed


# ---------------------------------------------------------------------------
# Rule 7 — general technical questions (checked last)
# ---------------------------------------------------------------------------

_GENERAL_TECHNICAL_RE = re.compile(
    r"\b(?:explain|define|elaborate)\b"
    r"|\bwhat\s+(?:is|are)\s+(?:a|an|the)?\s*[a-z]"
    r"|\bwhat\s+(?:does|do)\b[^?]{0,30}\bmean\b"
    r"|\bhow\s+(?:does|do|to)\b"
    r"|\bhow\s+(?:is|are)\b[^?]{0,30}\b(?:defined|implemented|used|structured|built|created)\b"
    r"|\b(?:recursion|pointer|algorithm|data\s+structure|loop|function|syntax"
    r"|binary\s+search|binary\s+tree)\b",
    re.IGNORECASE,
)


def _detect_general_technical(
    message: str, items: list[MemoryView]
) -> list[MemoryView] | None:
    if not _GENERAL_TECHNICAL_RE.search(message):
        return None
    return []


# ---------------------------------------------------------------------------
# Detector registry
# ---------------------------------------------------------------------------

_DETECTORS: tuple[
    tuple[Callable[[str, list[MemoryView]], list[MemoryView] | None], MemoryVisibilityRule],
    ...,
] = (
    (_detect_profile, RULE_PROFILE),
    (_detect_specific_preference, RULE_PREFERENCE),
    (_detect_workflow_continuation, RULE_WORKFLOW),
    (_detect_document_question, RULE_DOCUMENT),
    (_detect_project_status, RULE_PROJECT),
    (_detect_general_technical, RULE_TECHNICAL),
)


def evaluate_visibility(message: str, items: list[MemoryView]) -> RuleMatch:
    """Apply rules 3-8 in priority order.

    The first matching rule wins. A rule that returns an empty list still
    applies (it exposes nothing). When no rule matches, all items pass through.
    """
    for detector, rule in _DETECTORS:
        allowed = detector(message, items)
        if allowed is None:
            continue
        return RuleMatch(rule_id=rule.rule_id, name=rule.name, allowed=allowed)
    return RuleMatch(rule_id=None, name=None, allowed=list(items))
