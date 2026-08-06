"""Phase 12.2 — BraveSearchProvider adapter tests (no real network).

Every failure mode the phase requires is exercised against an httpx
MockTransport: config, normalization, auth, rate limit, retry, timeout,
malformed JSON, and suggestions.
"""

import httpx
import pytest

from app.internet.brave import BraveSearchProvider
from app.internet.models import (
    SearchAuthError,
    SearchConfigError,
    SearchHTTPError,
    SearchProviderError,
    SearchRateLimitError,
    SearchTimeoutError,
)

WEB_PAYLOAD = {
    "web": {
        "results": [
            {
                "title": "Python 3.13 Documentation",
                "url": "https://docs.python.org/3.13/",
                "description": "Official python version 3.13 reference",
                "meta_url": {"scheme": "https", "netloc": "docs.python.org", "host": "docs.python.org"},
                "age": "2024-10-07",
            },
            {
                "title": "Python downloads",
                "url": "https://www.python.org/downloads/",
                "description": "python.org download page",
                "meta_url": {"scheme": "https", "netloc": "www.python.org", "host": "www.python.org"},
                "page_age": "2025-01-01",
            },
        ]
    }
}

NEWS_PAYLOAD = {
    "news": {
        "results": [
            {
                "title": "Python 3.13 released today",
                "url": "https://news.example/article",
                "description": "The python version shipped",
                "source": {"name": "Tech News", "url": "https://news.example"},
                "publish_time": "2025-06-01T10:00:00Z",
            }
        ]
    }
}


def _provider(handler, api_key="test-key", max_retries=2):
    transport = httpx.MockTransport(handler)
    return BraveSearchProvider(
        api_key=api_key,
        transport=transport,
        max_retries=max_retries,
        timeout=5.0,
    )


@pytest.mark.asyncio
async def test_missing_api_key_raises_config_error():
    provider = BraveSearchProvider(api_key="")
    assert not provider.is_configured()
    with pytest.raises(SearchConfigError):
        await provider.search("python")


@pytest.mark.asyncio
async def test_web_results_are_normalized():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == "test-key"
        return httpx.Response(200, json=WEB_PAYLOAD)

    response = await _provider(handler).search("python 3.13", max_results=2)
    assert response.source == "brave"
    assert response.total == 2
    first = response.results[0]
    assert first.title == "Python 3.13 Documentation"
    assert first.url == "https://docs.python.org/3.13/"
    assert first.domain == "docs.python.org"
    assert first.provider == "brave"
    assert first.published_at == "2024-10-07"
    assert first.retrieved_at


@pytest.mark.asyncio
async def test_news_results_are_normalized():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "news/search" in request.url.path
        return httpx.Response(200, json=NEWS_PAYLOAD)

    response = await _provider(handler).news("python 3.13", max_results=1)
    assert response.category == "news"
    assert response.results[0].published_at == "2025-06-01"


@pytest.mark.asyncio
async def test_401_maps_to_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(401, json={"error": "unauthorized"})

    with pytest.raises(SearchAuthError):
        await _provider(handler).search("python")


@pytest.mark.asyncio
async def test_429_maps_to_rate_limit_error():
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(429, json={"error": "rate limited"})

    with pytest.raises(SearchRateLimitError):
        await _provider(handler).search("python")


@pytest.mark.asyncio
async def test_5xx_is_retried_then_fails():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        calls["count"] += 1
        return httpx.Response(503, json={"error": "down"})

    provider = _provider(handler, max_retries=2)
    with pytest.raises(SearchHTTPError) as exc_info:
        await provider.search("python")
    assert exc_info.value.status_code == 503
    assert calls["count"] == 3


@pytest.mark.asyncio
async def test_5xx_retry_then_success():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(500, json={})
        return httpx.Response(200, json=WEB_PAYLOAD)

    provider = _provider(handler, max_retries=2)
    response = await provider.search("python 3.13", max_results=1)
    assert response.total == 2
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_malformed_json_maps_to_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(200, content=b"not-json{{", headers={"content-type": "application/json"})

    with pytest.raises(SearchProviderError):
        await _provider(handler).search("python")


@pytest.mark.asyncio
async def test_timeout_maps_to_timeout_error():
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        raise httpx.ReadTimeout("timed out")

    with pytest.raises(SearchTimeoutError):
        await _provider(handler).search("python")


@pytest.mark.asyncio
async def test_suggestions_extracted_from_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={**WEB_PAYLOAD, "suggestions": ["python 3.13", "python download"]},
        )

    suggestions = await _provider(handler).suggestions("python")
    assert suggestions == ["python 3.13", "python download"]


@pytest.mark.asyncio
async def test_suggestions_failure_returns_empty():
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(401)

    assert await _provider(handler).suggestions("python") == []
