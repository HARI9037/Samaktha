"""Post-P14 SearXNG SearchProvider contract tests (no live network)."""

from __future__ import annotations

import inspect

import httpx
import pytest

from app.internet.models import (
    SearchConfigError,
    SearchHTTPError,
    SearchNetworkError,
    SearchProviderError,
    SearchRateLimitError,
    SearchTimeoutError,
)
from app.internet.searxng import SearXNGSearchProvider


PAYLOAD = {
    "results": [
        {
            "title": "OpenAI documentation",
            "url": "https://platform.openai.com/docs/",
            "content": "Official documentation",
            "engine": "example",
            "engines": ["example", "second"],
            "score": 3.5,
            "publishedDate": "2026-08-01T12:30:00Z",
            "category": "general",
            "ignored": {"provider_specific": True},
        },
        {"title": "Malformed: no URL"},
        {"title": "Malformed scheme", "url": "javascript:alert(1)"},
        {
            "title": "Python",
            "url": "https://www.python.org/",
            "content": "Python",
        },
    ],
    "untrusted_extra": {"does_not": "matter"},
}


def _provider(handler, **overrides) -> SearXNGSearchProvider:
    options = {
        "base_url": "http://127.0.0.1:8080",
        "timeout": 4.0,
        "max_retries": 0,
        "transport": httpx.MockTransport(handler),
    }
    options.update(overrides)
    return SearXNGSearchProvider(**options)


def test_missing_url_is_unconfigured_without_public_fallback() -> None:
    provider = SearXNGSearchProvider(base_url="")
    assert provider.is_configured() is False
    assert provider.endpoint_origin is None


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8080", "http://localhost:8080", "https://search.example.com"],
)
def test_trusted_http_and_https_endpoints_are_accepted(url: str) -> None:
    provider = SearXNGSearchProvider(base_url=url)
    assert provider.is_configured() is True


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/search",
        "ftp://search.example.com",
        "gopher://search.example.com",
        "data:text/plain,search",
        "javascript:alert(1)",
        "ws://search.example.com",
        "wss://search.example.com",
        "https://user:password@search.example.com",
        "not a url",
        "https:///missing-host",
        "https://search.example.com/?target=http://127.0.0.1",
        "https://search.example.com/#fragment",
    ],
)
def test_untrusted_or_ambiguous_endpoints_are_rejected(url: str) -> None:
    with pytest.raises(SearchConfigError):
        SearXNGSearchProvider(base_url=url)


@pytest.mark.asyncio
async def test_unconfigured_search_fails_truthfully_without_http() -> None:
    provider = SearXNGSearchProvider(base_url="")
    with pytest.raises(SearchConfigError, match="SAMAKTHA_SEARXNG_URL"):
        await provider.search("OpenAI")


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "category"), [("search", "general"), ("news", "news")])
async def test_request_uses_documented_search_json_contract(
    method: str, category: str
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=PAYLOAD)

    provider = _provider(handler, base_url="https://search.example.com/base")
    response = await getattr(provider, method)(
        "OpenAI & host=https://attacker.example", max_results=1, timeout=2.0
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.scheme == "https"
    assert request.url.host == "search.example.com"
    assert request.url.path == "/base/search"
    assert request.url.params["q"] == "OpenAI & host=https://attacker.example"
    assert request.url.params["format"] == "json"
    assert request.url.params["categories"] == category
    assert set(request.headers) >= {"host", "accept"}
    assert "authorization" not in request.headers
    assert "x-api-key" not in request.headers
    assert response.category == ("web" if method == "search" else "news")
    assert len(response.results) == 1


@pytest.mark.asyncio
async def test_response_is_bounded_and_normalized_conservatively() -> None:
    provider = _provider(lambda _request: httpx.Response(200, json=PAYLOAD))
    response = await provider.search("OpenAI", max_results=5)

    assert response.source == "searxng"
    assert response.total == 2
    assert len(response.results) == 2
    first = response.results[0]
    assert first.title == "OpenAI documentation"
    assert first.url == "https://platform.openai.com/docs/"
    assert first.description == "Official documentation"
    assert first.domain == "platform.openai.com"
    assert first.provider == "searxng"
    assert first.published_at == "2026-08-01"
    assert first.score == 3.5
    assert first.retrieved_at
    assert first.meta == {"engine": "example", "engines": ["example", "second"]}


@pytest.mark.asyncio
async def test_empty_and_extra_fields_are_supported() -> None:
    provider = _provider(
        lambda _request: httpx.Response(
            200, json={"results": [], "answers": ["ignored"], "number_of_results": 10}
        )
    )
    response = await provider.search("nothing")
    assert response.results == []
    assert response.total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (403, SearchConfigError),
        (429, SearchRateLimitError),
        (400, SearchHTTPError),
        (500, SearchHTTPError),
    ],
)
async def test_http_failures_are_typed_without_provider_body_leak(
    status: int, error_type: type[Exception]
) -> None:
    sentinel = "SEARXNG-RAW-BODY-MUST-NOT-LEAK"
    provider = _provider(
        lambda request: httpx.Response(status, text=sentinel, request=request)
    )
    with pytest.raises(error_type) as exc_info:
        await provider.search("secret query")
    assert sentinel not in str(exc_info.value)
    assert "secret query" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_retryable_5xx_and_429_are_bounded() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        status = 429 if calls == 1 else 503
        return httpx.Response(status, request=request)

    provider = _provider(handler, max_retries=2)
    with pytest.raises(SearchHTTPError):
        await provider.search("OpenAI")
    assert calls == 3


@pytest.mark.asyncio
async def test_nonretryable_4xx_has_no_retry_storm() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, request=request)

    with pytest.raises(SearchHTTPError):
        await _provider(handler, max_retries=5).search("OpenAI")
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        (httpx.ReadTimeout("timeout"), SearchTimeoutError),
        (httpx.ConnectError("network"), SearchNetworkError),
    ],
)
async def test_transport_failures_are_sanitized(failure, error_type) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise failure

    with pytest.raises(error_type) as exc_info:
        await _provider(handler).search("secret query")
    assert "secret query" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_malformed_or_oversized_json_is_rejected() -> None:
    malformed = _provider(
        lambda request: httpx.Response(
            200,
            content=b"not-json",
            headers={"content-type": "application/json"},
            request=request,
        )
    )
    with pytest.raises(SearchProviderError):
        await malformed.search("OpenAI")

    oversized = _provider(
        lambda request: httpx.Response(200, content=b"x" * 129, request=request),
        max_response_bytes=128,
    )
    with pytest.raises(SearchProviderError, match="size limit"):
        await oversized.search("OpenAI")


@pytest.mark.asyncio
async def test_health_and_suggestions_are_bounded_and_documented() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"results": []})

    provider = _provider(handler)
    assert await provider.health() is True
    assert calls == 1
    assert await provider.suggestions("OpenAI") == []
    assert calls == 1
    assert await SearXNGSearchProvider(base_url="").health() is False


def test_tls_verification_is_not_disabled() -> None:
    source = inspect.getsource(SearXNGSearchProvider)
    assert "verify=False" not in source
    assert "follow_redirects=False" in source

