import logging
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)

from app.fileparsers.base import DocumentParser, ParseResult


class MarkdownParser(DocumentParser):
    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in (".md", ".markdown")

    def parse(self, path: Path) -> ParseResult:
        logger.info("MarkdownParser: START path=%s", path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            logger.info("MarkdownParser: SUCCESS — text_len=%d", len(text))
            return ParseResult(
                ok=True,
                text=text,
                title=path.stem,
                metadata={
                    "source_path": str(path),
                    "file_size": path.stat().st_size,
                    "format": path.suffix.lower(),
                    "parser": "markdown",
                },
            )
        except Exception as e:
            logger.warning("MarkdownParser: parse raised %s: %s\n%s", type(e).__name__, e, traceback.format_exc())
            return ParseResult(ok=False, error=f"Failed to read markdown file: {e}")


class TxtParser(DocumentParser):
    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() == ".txt"

    def parse(self, path: Path) -> ParseResult:
        logger.info("TxtParser: START path=%s", path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            logger.info("TxtParser: SUCCESS — text_len=%d", len(text))
            return ParseResult(
                ok=True,
                text=text,
                title=path.stem,
                metadata={
                    "source_path": str(path),
                    "file_size": path.stat().st_size,
                    "format": path.suffix.lower(),
                    "parser": "txt",
                },
            )
        except Exception as e:
            logger.warning("TxtParser: parse raised %s: %s\n%s", type(e).__name__, e, traceback.format_exc())
            return ParseResult(ok=False, error=f"Failed to read text file: {e}")