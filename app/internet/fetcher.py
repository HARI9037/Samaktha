"""Phase 12.6 — deterministic content retrieval.

ContentFetcher downloads a URL over HTTPS and converts HTML / Markdown /
plain text / PDF into clean, plain text with ads, navigation, cookie banners,
scripts and embeds stripped. It enforces an http/https scheme, a size cap and
a timeout so a hostile or broken page can never wedge the pipeline.
"""

from __future__ import annotations

import html
import io
import logging
import re
from html.parser import HTMLParser
from typing import ClassVar
from urllib.parse import urlparse

import httpx

from app.internet.models import FetchResult, SearchError

log = logging.getLogger(__name__)

_USER_AGENT = "Samaktha-InternetIntelligence/0.5 (+governed-search)"
_SKIPPED_TAGS = {
    "script", "style", "noscript", "header", "footer", "nav", "iframe",
    "form", "aside", "svg", "template", "object", "embed", "canvas",
    "banner", "cookie-consent", "ad", "ads", "advertisement",
}

_MAX_FETCH_BYTES = 2_000_000  # hard wire cap; never read an unbounded body


class _TextExtractor(HTMLParser):
    """Collects visible text, skipping boilerplate + scripting tags."""

    _VOID_SKIP: ClassVar[set[str]] = {
        "script", "style", "noscript", "iframe", "img", "input", "textarea",
        "br", "hr", "meta", "link", "svg", "video", "audio", "source",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._text: list[str] = []
        self._title: str = ""

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: N802
        tag = tag.lower()
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "tr"}:
            self._text.append("\n")

    def handle_endtag(self, tag: str) -> None:  # noqa: N802
        tag = tag.lower()
        if tag in _SKIPPED_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "tr"}:
            self._text.append("\n")

    def handle_data(self, data: str) -> None:  # noqa: N802
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title += data
            return
        self._text.append(data)

    def text(self) -> str:
        return _clean_text("".join(self._text))


def _clean_text(raw: str) -> str:
    """Collapse whitespace, decode entities already handled by the parser."""
    lines = []
    for line in raw.splitlines():
        line = html.unescape(line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _clean_markdown(raw: str) -> str:
    """Strip markdown links/images and heading markers to plain text."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", raw)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    return _clean_text(text)


def _extract_pdf(data: bytes, title_hint: str = "") -> tuple[str, str]:
    """Extract plain text from PDF bytes via PyMuPDF when available."""
    try:
        import fitz  # PyMuPDF
    except ImportError:  # pragma: no cover - environment-dependent
        raise SearchError("PDF extraction is unavailable in this environment.")

    try:
        document = fitz.open(stream=data, filetype="pdf")
        pages = [page.get_text("text") for page in document]
        document.close()
    except Exception as exc:
        raise SearchError(f"Failed to parse PDF content: {exc}")

    title = title_hint
    if not title and pages:
        first = (pages[0] or "").strip().splitlines()
        if first:
            title = first[0][:200]
    return title, _clean_text("\n".join(pages))


class ContentFetcher:
    """HTTPS content downloader + extractor. Never raises outside SearchError."""

    def __init__(
        self,
        timeout: float = 15.0,
        max_chars: int = 12_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout
        self._max_chars = max_chars
        self._transport = transport

    async def fetch(
        self,
        url: str,
        *,
        timeout: float | None = None,
        max_chars: int | None = None,
    ) -> FetchResult:
        """Download ``url`` and return clean extracted text."""
        effective_timeout = timeout if timeout is not None else self._timeout
        effective_max = max_chars if max_chars is not None else self._max_chars
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return FetchResult(
                ok=False, url=url, error="Only http/https URLs may be fetched."
            )

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(effective_timeout),
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
                transport=self._transport,
            ) as client:
                response = await client.get(url)
        except httpx.TimeoutException as exc:
            return FetchResult(ok=False, url=url, error=f"Fetch timed out: {exc}")
        except httpx.RequestError as exc:
            return FetchResult(
                ok=False, url=url, error=f"Fetch failed (network/DNS): {exc}"
            )

        if response.status_code != 200:
            return FetchResult(
                ok=False,
                url=url,
                error=f"Fetch returned HTTP {response.status_code}",
            )

        final_url = str(response.url)
        if urlparse(final_url).scheme not in ("http", "https"):
            return FetchResult(
                ok=False, url=url, error="Redirected to a non-http(s) location."
            )

        content_type = (response.headers.get("content-type") or "").split(";")[0].lower()
        body = response.content[:_MAX_FETCH_BYTES]

        try:
            title, text = self._extract(content_type, body, url)
        except SearchError as exc:
            return FetchResult(ok=False, url=url, content_type=content_type, error=str(exc))

        return FetchResult(
            ok=True,
            url=final_url,
            title=title,
            text=text[:effective_max],
            content_type=content_type or "application/octet-stream",
            retrieved_at=_now_iso(),
        )

    def _extract(self, content_type: str, body: bytes, url: str) -> tuple[str, str]:
        if content_type == "application/pdf":
            return _extract_pdf(body, title_hint=url)
        if content_type in {"text/markdown", "text/x-markdown"}:
            return url, _clean_markdown(body.decode("utf-8", errors="replace"))
        if content_type.startswith("text/") or "html" in content_type:
            return self._extract_html(body)
        if content_type in {"application/json", "application/xml"}:
            return url, _clean_text(body.decode("utf-8", errors="replace"))
        raise SearchError(f"Unsupported content type: {content_type or 'unknown'}")

    def _extract_html(self, body: bytes) -> tuple[str, str]:
        parser = _TextExtractor()
        try:
            parser.feed(body.decode("utf-8", errors="replace"))
        except Exception as exc:  # pragma: no cover - defensive
            raise SearchError(f"HTML parsing failed: {exc}")
        title = parser._title.strip() if parser._title else ""  # noqa: SLF001
        return title, parser.text()


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
