"""Conservative lexical gate over already scoped/scored memory candidates."""
import re

_STOP = frozenset("a an the my your our is was are were i you me of to for about that this it in on and".split())

def tokens(text):
    return {t for t in re.findall(r"\w+(?:[-.]\w+)*", text.casefold()) if t not in _STOP}

def strong_fact_matches(query, candidates):
    target = tokens(query)
    if not target:
        return []
    matches = []
    for item, score in candidates:
        metadata = getattr(item, "metadata", {}) or {}
        if metadata.get("memory_type") not in {"knowledge", "preference", "project"}:
            continue
        if metadata.get("source_authority") == "derived_from_memory_evidence":
            continue
        if target <= tokens(item.content):
            matches.append((item, float(score)))
    return sorted(matches, key=lambda pair: (-pair[1], str(pair[0].id)))
