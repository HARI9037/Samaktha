"""Pure memory speech acts. Payloads are data, never policy or file requests."""
import re

_STORE = re.compile(r"^\s*(?:please\s+)?(?:remember\s+(?:that\b\s*|this(?:\s+for\s+later)?\s*:\s*)|(?:save|store|keep)\s+this\s+(?:in\s+(?:your\s+)?memory|for\s+later)\s*:\s*|don't\s+forget\s+that\b\s*|make\s+a\s+note\s+in\s+your\s+memory\s+that\b\s*)", re.I)

def store_payload(request: str) -> str | None:
    match = _STORE.match(request)
    return request[match.end():] if match else None

def ambiguous_store(request: str) -> bool:
    return bool(re.match(r"^\s*(?:please\s+)?remember\s+(?:my|this|that)\b", request, re.I)) and store_payload(request) is None and not request.rstrip().endswith("?")

def recall_target(request: str) -> str | None:
    """None is not this grammar; empty is deliberate browse."""
    text = " ".join(request.split()).strip(" .?!")
    if re.fullmatch(r"(?:search\s+(?:your\s+|my\s+)?(?:memory|memories)|(?:show|list)\s+(?:me\s+)?(?:recent\s+)?memories|show\s+what\s+you\s+remember|what\s+memories\s+do\s+you\s+have)", text, re.I):
        return ""
    patterns = (
        r"^(?:please\s+)?(?:search|look\s+in|find\s+in)\s+(?:through\s+)?(?:(?:your|my|the)\s+)?(?:memory|memories)\s+(?:for|about)\s+(.+)$",
        r"^(?:do\s+you\s+remember|(?:tell\s+me\s+)?what\s+do\s+you\s+remember\s+about|recall)\s+(.+)$",
        r"^what\s+(?:was|is|were)\s+(.+?)\s+I\s+asked\s+you\s+to\s+remember$",
        r"^what\s+(.+?)\s+did\s+I\s+ask\s+you\s+to\s+remember$",
        r"^what\s+did\s+I\s+tell\s+you\s+(?:about\s+)?(.+?)(?:\s+was|\s+is)?$",
        r"^what\s+(?:was|is|are)\s+(my\s+.+)$",
        r"^what\s+(?:was|is)\s+(the\s+.*\b(?:codeword|identifier|validation\s+code))$",
    )
    for pattern in patterns:
        match = re.match(pattern, text, re.I)
        if match:
            target = re.sub(r"^(?:my|the|our)\s+", "", match.group(1), flags=re.I)
            if target.casefold() in {"me", "profile", "preferences", "coding preferences", "about me"}:
                return None
            return target
    return None
