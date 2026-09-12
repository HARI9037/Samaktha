"""Deterministic resource syntax; parsing never grants filesystem access."""
from __future__ import annotations

import ctypes
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ResourceOperation(StrEnum):
    FILE_CREATE = "file_create"
    FILE_WRITE = "file_write"
    FILE_UPDATE = "file_update"
    DIRECTORY_CREATE = "directory_create"


@dataclass(frozen=True)
class ResourceWrite:
    paths: tuple[str, ...]
    content: str | None
    operation: ResourceOperation
    location: str | None = None
    overwrite: bool = False

    def arguments(self) -> dict:
        args = {"operation": self.operation, "overwrite": self.overwrite}
        if self.paths:
            args["path"] = self.paths[0]
            args["format"] = "directory" if self.operation == ResourceOperation.DIRECTORY_CREATE else Path(self.paths[0]).suffix.lower().lstrip(".") or "text"
        if self.location:
            args["target_root"] = self.location
        if self.content is not None:
            args["content"] = self.content
        return args


_VERB = re.compile(r"^\s*(?:please\s+)?(create|make|write|save|generate|update|overwrite)\b", re.I)
_BODY = re.compile(
    r"\b(?:with\s+(?:the\s+)?(?:content|text)|containing|saying|content|text)\b[ \t]*(?:(?:of|is)\b[ \t]*|:[ \t]*)?"
    r"|\band\s+(?:write|put)\s+", re.I,
)
_PATH = re.compile(r'''"([^"\n]+)"|'([^'\n]+)'|([^\s,"']+\.[a-zA-Z0-9]+)(?=$|[\s,])''')


def parse_resource_write(request: str) -> ResourceWrite | None:
    verb = _VERB.search(request)
    if not verb:
        return None
    if re.match(r"\s*(?:an?\s+)?(?:note|task|contact|calendar|event|reminder|email|message)\b(?!\.)", request[verb.end():], re.I):
        return None
    # First separate payload so punctuation/paths inside content are never targets.
    body = _BODY.search(request, verb.end())
    header = request[:body.start()] if body else request
    # "text file" is a format descriptor, not a payload delimiter.
    if body and re.match(r"(?:text|content)\s+file\b", request[body.start():], re.I):
        body = _BODY.search(request, body.end() + len("file"))
        header = request[:body.start()] if body else request
    location_match = re.search(
        r"\b(?:on|in)\s+(?:(?:my|the)\s+)?(Desktop|Documents|workspace)\b"
        r'''|\bin\s+("[^"\n]+"|'[^'\n]+'|[a-zA-Z]:[\\/][^\n]+?)(?=\s+(?:with|called|named)\b|$)''', header, re.I,
    )
    location = None
    path_header = header
    if location_match:
        location = (location_match.group(1) or location_match.group(2)).strip().strip("\"'")
        path_header = header[:location_match.start()] + header[location_match.end():]
    paths = tuple((m.group(1) or m.group(2) or m.group(3)).rstrip(",") for m in _PATH.finditer(path_header))
    if not paths:
        lexical = re.search(r"\b(?:called|named|as)\s+(\S+)\s*$", path_header, re.I)
        if lexical:
            paths = (lexical.group(1).strip("\"'"),)
    explicit = re.search(r"\b(?:file|document|csv|markdown|save\s+(?:this\s+)?as)\b", path_header, re.I)
    if not paths and not explicit:
        return None
    content = None
    if body:
        content = request[body.end():]
        if content.startswith("\r\n"):
            content = content[2:]
        elif content.startswith("\n"):
            content = content[1:]
        if re.match(r"and\s+put\b", body.group(), re.I):
            content = re.sub(r"\s+in\s+it\s*$", "", content, flags=re.I)
        if len(content) >= 2 and content[0] in "\"'" and content[-1] == content[0]:
            content = content[1:-1]
    elif verb.group(1).lower() in {"create", "make"} or re.search(r"\bempty\b", header, re.I):
        content = ""
    operation = {"create": "file_create", "make": "file_create", "update": "file_update"}.get(verb.group(1).lower(), "file_write")
    if re.match(r"\s*(?:an?\s+)?(?:empty\s+)?(?:folder|directory)\b", path_header[verb.end():], re.I):
        operation = "directory_create"
    return ResourceWrite(paths, content, ResourceOperation(operation), location,
                         overwrite=verb.group(1).lower() == "overwrite")


def known_location(name: str) -> Path:
    """Read Windows Known Folder location (including redirected folders)."""
    if os.name == "nt":
        buffer = ctypes.create_unicode_buffer(32768)
        folder_id = {"desktop": 0x10, "documents": 0x05}[name.lower()]
        result = ctypes.windll.shell32.SHGetFolderPathW(None, folder_id, None, 0, buffer)
        if result != 0 or not buffer.value:
            raise ValueError(f"Windows could not resolve {name}; specify an explicit path.")
        return Path(buffer.value)
    return Path.home() / name.capitalize()


def resolve_resource_path(raw: str, workspace: Path, location: str | None = None) -> str:
    # Never expand variables/devices/drive-relative names here: P7 must reject them.
    if any(c in raw for c in ("%", "$", "\x00")) or raw.startswith(("~", "\\\\")) or re.match(r"^[a-z]:[^\\/]", raw, re.I):
        return raw
    path = Path(raw)
    if not path.is_absolute():
        root = workspace
        if location and location.lower() != "workspace":
            root = known_location(location) if location.lower() in {"desktop", "documents"} else Path(location)
            if not root.is_absolute():
                root = workspace / root
        path = root / path
    try:
        return str(path.resolve(strict=False))
    except RuntimeError as exc:
        raise ValueError("Destination contains an unresolvable path loop") from exc
