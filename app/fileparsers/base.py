from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class ParseResult:
    def __init__(
        self,
        ok: bool,
        text: str = "",
        title: Optional[str] = None,
        page_count: int = 0,
        tables: Optional[list] = None,
        sections: Optional[list] = None,
        images: Optional[list] = None,
        metadata: Optional[dict] = None,
        error: Optional[str] = None,
    ):
        self.ok = ok
        self.text = text
        self.title = title
        self.page_count = page_count
        self.tables = tables or []
        self.sections = sections or []
        self.images = images or []
        self.metadata = metadata or {}
        self.error = error


class DocumentParser(ABC):
    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        ...

    @abstractmethod
    def parse(self, path: Path) -> ParseResult:
        ...