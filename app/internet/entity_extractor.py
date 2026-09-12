"""Entity extraction from search result snippets.

Provides deterministic, provider-independent extraction of answer entities
(LLM models, AI agents, products, etc.) from verified search evidence snippets.
Never fabricates entities — only extracts what is explicitly present in snippets.
"""

from __future__ import annotations

import re
from typing import Any

# Known entity names/prefixes - these are the entities we want to extract
_KNOWN_LLM_MODELS = frozenset({
    "gpt-5", "gpt-4", "gpt-4o", "gpt-4-turbo", "gpt-3.5", "chatgpt",
    "claude 4", "claude 3.5", "claude 3", "claude 4 opus", "claude 4 sonnet", "claude 3.5 sonnet", "claude 3 opus", "claude 3 sonnet", "claude 3 haiku",
    "gemini 2.0", "gemini 1.5", "gemini 1.0", "gemini 2.0 flash", "gemini 1.5 pro", "gemini 1.5 flash", "gemini pro", "gemini ultra", "gemini nano",
    "llama 4", "llama 3.1", "llama 3", "llama 2", "llama 4 400b", "llama 3.1 405b", "llama 3.1 70b", "llama 3.1 8b", "llama 3 70b", "llama 3 8b",
    "mistral large 2", "mistral large", "mistral medium", "mistral small", "mistral 7b", "mixtral 8x7b", "mixtral 8x22b",
    "deepseek v3", "deepseek v2", "deepseek coder", "deepseek llm", "deepseek 67b", "deepseek 33b",
    "qwen 2.5", "qwen 2", "qwen 1.5", "qwen 2.5 72b", "qwen 2.5 32b", "qwen 2.5 14b", "qwen 2.5 7b", "qwen 2.5 3b", "qwen 2.5 0.5b",
    "yi 34b", "yi 6b", "yi 1.5",
    "phi 3", "phi 3.5", "phi 3 mini", "phi 3 medium", "phi 3.5 mini",
    "falcon 180b", "falcon 40b", "falcon 7b",
    "mpt 30b", "mpt 7b",
    "bloom 176b", "bloom 7b",
    "opt 175b", "opt 66b", "opt 30b", "opt 13b", "opt 6.7b", "opt 2.7b", "opt 1.3b", "opt 350m", "opt 125m",
    "galactica 120b", "galactica 30b", "galactica 6.7b", "galactica 1.3b",
    "palm 2", "palm", "lamda", "bard",
})

_KNOWN_AGENTS = frozenset({
    "autogpt", "babyagi", "langchain", "langgraph", "crewai", "autogen",
    "semantic kernel", "haystack", "llama-index", "llamaindex", "guidance",
    "instructor", "marvin", "openinterpreter", "gpt-engineer", "aider",
    "copilot", "github copilot", "codex", "cursor", "windsurf",
})

_KNOWN_ENTITIES = _KNOWN_LLM_MODELS | _KNOWN_AGENTS

# Common words that are NOT entities
_GENERIC_WORDS = frozenset({
    "the", "and", "or", "but", "for", "with", "from", "this", "that", "these", "those",
    "model", "models", "system", "platform", "tool", "api", "service", "company", "team",
    "project", "version", "release", "update", "latest", "new", "best", "top", "guide",
    "review", "comparison", "benchmark", "leaderboard", "august", "2026", "2025", "2024",
    "openai", "anthropic", "google", "meta", "microsoft", "amazon", "ibm", "nvidia",
    "released", "announced", "launched", "features", "capabilities", "abilities", "improved",
    "enhanced", "native", "available", "variant", "variants", "two", "first", "most",
    "capable", "yet", "their", "with", "enhanced", "coding", "abilities", "opus", "sonnet",
    "flash", "pro", "ultra", "nano", "large", "medium", "small", "mini", "base", "turbo",
})


def _normalize_entity(name: str) -> str:
    """Normalize extracted entity name."""
    name = name.strip(" .,;:()[]{}")
    # Remove trailing generic words
    words = name.split()
    while words and words[-1].lower() in _GENERIC_WORDS:
        words.pop()
    while words and words[0].lower() in _GENERIC_WORDS:
        words.pop(0)
    return " ".join(words).strip()


def _is_known_entity(name: str) -> bool:
    """Check if name matches a known entity (case-insensitive, fuzzy)."""
    name_lower = name.lower().strip()
    # Exact match
    if name_lower in _KNOWN_ENTITIES:
        return True
    # Prefix match for versioned entities
    for known in _KNOWN_ENTITIES:
        if name_lower.startswith(known) or known.startswith(name_lower):
            return True
    return False


def extract_entities_from_snippets(
    results: list[dict[str, Any]],
    *,
    max_entities: int = 10,
    domain_hint: str | None = None,
    format_intent: str | None = None,
) -> list[str]:
    """Extract answer entities from search result snippets.

    Args:
        results: List of search result dicts with 'title', 'description', 'url' keys.
        max_entities: Maximum number of entities to return.
        domain_hint: Optional hint about the domain (e.g., "LLM", "AI agent").
        format_intent: Optional format intent ("names_only", "descriptions", etc.).

    Returns:
        List of extracted entity names, deduplicated and ranked by confidence.
    """
    if not results:
        return []

    candidates: dict[str, int] = {}  # entity -> confidence score

    for result in results:
        if not isinstance(result, dict):
            continue

        title = result.get("title", "") or ""
        description = result.get("description", "") or ""

        # Search in both title and description
        for text in (title, description):
            if not text:
                continue

            # Strategy 1: Look for known entities directly in text
            text_lower = text.lower()
            for known in _KNOWN_ENTITIES:
                if known in text_lower:
                    # Find the actual casing in the original text
                    idx = text_lower.index(known)
                    # Extract with surrounding context to get proper casing
                    start = max(0, idx - 2)
                    end = min(len(text), idx + len(known) + 20)
                    snippet = text[start:end]
                    # Try to extract the entity with proper casing
                    for word in snippet.split():
                        if word.lower() == known.split()[0]:
                            # Found the start, now extract the full entity
                            entity = _extract_entity_from_text(text, idx, known)
                            if entity:
                                entity = _normalize_entity(entity)
                                if entity and _is_valid_entity(entity):
                                    candidates[entity] = max(candidates.get(entity, 0), 10)
                                    break

            # Strategy 2: Pattern-based extraction for "Name Version" formats
            # Matches: "GPT-5", "Claude 4", "Gemini 2.0", "Llama 3.1 405B", etc.
            # Stop at punctuation or common stop words
            version_pattern = re.compile(
                r"\b([A-Z][A-Za-z0-9\-\.]+(?:\s+[A-Za-z0-9\-\.]+){0,2}\s+\d+(?:\.\d+)?[Bb]?)(?=\s*[.,;:]|\s+(?:is|was|has|have|with|from|the|and|or|based|features?|offers?|provides?|uses?|for|in|on|at|by|as|of|to|a|an|the|launch|released|announced|features?|improved|enhanced|native|available|variant|variants|two|first|most|capable|yet|their|with|coding|abilities|opus|sonnet|flash|pro|ultra|nano|large|medium|small|mini|base|turbo)\b|$)"
            )
            for match in version_pattern.finditer(text):
                entity = _normalize_entity(match.group(1))
                if _is_valid_entity(entity):
                    # Boost if it's a known entity
                    confidence = 10 if _is_known_entity(entity) else 5
                    # Extra boost if in title
                    if title and entity.lower() in title.lower():
                        confidence += 5
                    candidates[entity] = max(candidates.get(entity, 0), confidence)

            # Strategy 3: Quoted names
            quoted_pattern = re.compile(r"[\"']([A-Z][A-Za-z0-9\-\.]+(?:\s+[A-Za-z0-9\-\.]+){0,2}(?:\s+\d+(?:\.\d+)?[Bb]?)?)[\"']")
            for match in quoted_pattern.finditer(text):
                entity = _normalize_entity(match.group(1))
                if _is_valid_entity(entity):
                    confidence = 8 if _is_known_entity(entity) else 4
                    candidates[entity] = max(candidates.get(entity, 0), confidence)

    # Sort by confidence, then by name for determinism
    sorted_entities = sorted(
        candidates.items(),
        key=lambda x: (-x[1], x[0])
    )

    entities = [entity for entity, _ in sorted_entities]

    return entities[:max_entities]


def _extract_entity_from_text(text: str, start_idx: int, known: str) -> str | None:
    """Extract full entity name from text starting at known position."""
    # Look ahead to capture version numbers
    remaining = text[start_idx:]
    # Match "Name Version" pattern - known entity followed by optional version
    # Known already matches the base name, so just check for version suffix
    # Escape the known entity for regex
    known_escaped = re.escape(known)
    # Pattern: known entity followed by optional version (space + digits)
    pattern = rf"{known_escaped}(?:\s+\d+(?:\.\d+)?[Bb]?)?"
    match = re.match(pattern, remaining, re.IGNORECASE)
    if match:
        return match.group(0)
    return None


def _is_valid_entity(name: str) -> bool:
    """Check if extracted string looks like a valid entity name."""
    if not name or len(name) < 2:
        return False
    if len(name) > 80:
        return False
    # Must start with letter
    if not name[0].isalpha():
        return False
    # Should not be all caps (likely acronym) unless known
    if name.isupper() and len(name) > 5 and not _is_known_entity(name):
        return False
    # Should not be generic words
    if name.lower() in _GENERIC_WORDS:
        return False
    # Must have at least one known prefix or version number
    first_word = name.split()[0].lower()
    has_known_prefix = first_word in {k.split()[0] for k in _KNOWN_ENTITIES}
    has_version = bool(re.search(r"\d+(?:\.\d+)?[Bb]?$", name))
    return has_known_prefix or has_version


def extract_entities_for_fallback(
    results: list[dict[str, Any]],
    *,
    requested_count: int = 5,
    domain_hint: str | None = None,
) -> tuple[list[str], str | None]:
    """Extract entities specifically for the degraded fallback.

    Returns:
        Tuple of (entity_list, fallback_message_or_none).
        If entities extracted, fallback_message is None.
        If no entities could be extracted, fallback_message explains why.
    """
    entities = extract_entities_from_snippets(
        results,
        max_entities=requested_count,
        domain_hint=domain_hint,
    )

    if entities:
        return entities, None

    return [], "Search succeeded, but I couldn't extract specific model names from the verified results."


def infer_domain_hint(query: str) -> str | None:
    """Infer domain hint from user query."""
    query_lower = query.lower()
    if any(kw in query_lower for kw in ("llm", "large language model", "language model", "gpt", "model")):
        return "LLM"
    if any(kw in query_lower for kw in ("agent", "ai agent", "assistant", "autonomous")):
        return "AI agent"
    if any(kw in query_lower for kw in ("gemini", "google")):
        return "Gemini"
    if any(kw in query_lower for kw in ("gpt", "openai")):
        return "GPT"
    return None


def infer_format_intent(query: str) -> str | None:
    """Infer output format intent from user query."""
    query_lower = query.lower()
    if any(kw in query_lower for kw in ("names only", "just names", "only names", "list names")):
        return "names_only"
    if any(kw in query_lower for kw in ("descriptions", "short descriptions", "with descriptions", "describe")):
        return "descriptions"
    if any(kw in query_lower for kw in ("compare", "comparison", "vs", "versus")):
        return "comparison"
    if any(kw in query_lower for kw in ("sources", "citations", "references")):
        return "sources"
    return None


def infer_requested_count(query: str, default: int = 5) -> int:
    """Infer requested count from user query."""
    query_lower = query.lower()
    # Look for "top N", "N models", "N llms", etc.
    match = re.search(r"\b(top|first|best)\s+(\d+)\b", query_lower)
    if match:
        return int(match.group(2))
    match = re.search(r"\b(\d+)\s+(llms?|models?|agents?|results?)\b", query_lower)
    if match:
        return int(match.group(1))
    return default