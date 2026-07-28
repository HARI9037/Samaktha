import logging
import traceback
from pathlib import Path

from app.fileparsers.base import DocumentParser, ParseResult

logger = logging.getLogger(__name__)


class HtmlParser(DocumentParser):
    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in (".html", ".htm")

    def parse(self, path: Path) -> ParseResult:
        logger.info("HtmlParser: START path=%s", path)
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            logger.warning("HtmlParser: BeautifulSoup not installed — %s: %s", type(e).__name__, e)
            return ParseResult(ok=False, error="BeautifulSoup is not installed.")

        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            soup = BeautifulSoup(raw, "html.parser")

            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()

            text = soup.get_text(separator="\n", strip=True)
            title = path.stem
            title_tag = soup.find("title")
            if title_tag and title_tag.get_text(strip=True):
                title = title_tag.get_text(strip=True)

            logger.info("HtmlParser: SUCCESS — text_len=%d", len(text))
            return ParseResult(
                ok=True,
                text=text,
                title=title,
                metadata={
                    "source_path": str(path),
                    "file_size": path.stat().st_size,
                    "format": path.suffix.lower(),
                    "parser": "html",
                },
            )
        except Exception as e:
            logger.warning("HtmlParser: parse raised %s: %s\n%s", type(e).__name__, e, traceback.format_exc())
            return ParseResult(ok=False, error=f"Failed to parse HTML file: {e}")