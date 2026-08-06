"""Phase 12.6 — ContentFetcher tests (no real network — httpx MockTransport)."""

import httpx
import pytest

from app.internet.fetcher import ContentFetcher

HTML_PAGE = (
    "<html><head><title>Example Page</title></head><body>"
    "<nav>Navigation links</nav>"
    "<script>alert('x')</script>"
    "<div><p>Hello world.</p><p>Second paragraph.</p></div>"
    "<footer>Footer stuff</footer>"
    "</body></html>"
)


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "html.example":
        return httpx.Response(
            200,
            content=HTML_PAGE.encode("utf-8"),
            headers={"content-type": "text/html; charset=utf-8"},
        )
    if request.url.host == "markdown.example":
        return httpx.Response(
            200,
            content=b"# Title\n\n[link](https://example.com) text",
            headers={"content-type": "text/markdown"},
        )
    if request.url.host == "missing.example":
        return httpx.Response(404)
    if request.url.host == "error.example":
        return httpx.Response(500)
    if request.url.host == "pdf.example":
        return httpx.Response(
            200,
            content=b"%PDF-1.4 not-a-real-pdf",
            headers={"content-type": "application/pdf"},
        )
    return httpx.Response(200, content=b"plain", headers={"content-type": "text/plain"})


@pytest.fixture
def fetcher():
    transport = httpx.MockTransport(_handler)
    return ContentFetcher(transport=transport)


@pytest.mark.asyncio
async def test_html_extracts_clean_text_and_title(fetcher):
    result = await fetcher.fetch("https://html.example/page")
    assert result.ok
    assert result.title == "Example Page"
    assert "Hello world." in result.text
    assert "Second paragraph." in result.text
    assert "alert" not in result.text
    assert "Navigation links" not in result.text
    assert "Footer stuff" not in result.text


@pytest.mark.asyncio
async def test_markdown_strips_link_syntax(fetcher):
    result = await fetcher.fetch("https://markdown.example/page")
    assert result.ok
    assert result.text == "Title\nlink text"
    assert "link" in result.text


@pytest.mark.asyncio
async def test_plain_text_passthrough(fetcher):
    result = await fetcher.fetch("https://text.example/plain")
    assert result.ok
    assert result.text == "plain"


@pytest.mark.asyncio
async def test_http_404_is_a_graceful_error(fetcher):
    result = await fetcher.fetch("https://missing.example/x")
    assert not result.ok
    assert "404" in (result.error or "")


@pytest.mark.asyncio
async def test_pdf_parse_failure_is_graceful(fetcher):
    result = await fetcher.fetch("https://pdf.example/doc")
    assert not result.ok
    assert result.error


@pytest.mark.asyncio
async def test_non_http_scheme_is_rejected(fetcher):
    result = await fetcher.fetch("file:///etc/passwd")
    assert not result.ok
    assert "http" in (result.error or "")


@pytest.mark.asyncio
async def test_network_error_is_graceful():
    def raise_error(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        raise httpx.ConnectError("boom")

    fetcher = ContentFetcher(transport=httpx.MockTransport(raise_error))
    result = await fetcher.fetch("https://down.example/x")
    assert not result.ok
    assert result.error
