"""Phase 12.1/12.3/12.7 — InternetTool facade tests."""

import pytest

from app.internet.cache import SearchCache
from app.internet.models import (
    SearchRateLimitError,
    SearchResult,
    SearchResponse,
)
from app.internet.policy import SearchPolicy
from app.internet.provider import SearchProvider
from app.internet.tool import InternetTool
from app.internet.verifier import SearchVerifier


class FakeProvider(SearchProvider):
    name = "fake"

    def __init__(self, configured=True, response=None, raise_error=None):
        self._configured = configured
        self._response = response
        self._raise_error = raise_error
        self.search_calls = 0

    def is_configured(self):
        return self._configured

    async def search(self, query, *, max_results=5, timeout=None):
        self.search_calls += 1
        if self._raise_error is not None:
            raise self._raise_error
        response = self._response or SearchResponse(
            query=query,
            results=[
                SearchResult(
                    title="Python 3.13 released",
                    url="https://docs.python.org/3.13/",
                    description="Official python version 3.13 release",
                    domain="docs.python.org",
                )
            ],
            source="fake",
        )
        return response


def _args(**overrides):
    args = {"action": "search", "query": "latest python version", "_cap_permit": "ask_user"}
    args.update(overrides)
    return args


@pytest.mark.asyncio
async def test_refuses_without_cap_permit():
    tool = InternetTool(provider=FakeProvider())
    result = await tool.run({"action": "search", "query": "python"})
    assert not result.ok
    assert "governance" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_refuses_on_deny_permit():
    tool = InternetTool(provider=FakeProvider())
    result = await tool.run({"action": "search", "query": "python", "_cap_permit": "deny"})
    assert not result.ok
    assert "denied" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_unconfigured_provider_is_graceful():
    tool = InternetTool(provider=FakeProvider(configured=False))
    result = await tool.run(_args())
    assert not result.ok
    assert "provider" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_successful_search_shape():
    provider = FakeProvider()
    tool = InternetTool(provider=provider)
    result = await tool.run(_args())
    assert result.ok
    data = result.data
    assert data["internet"] is True
    assert data["action"] == "search"
    assert data["result_count"] == 1
    assert data["cached"] is False
    assert len(data["sources"]) == 1
    assert data["sources"][0]["url"] == "https://docs.python.org/3.13/"
    assert "verdict" in data["verification"]
    assert provider.search_calls == 1


@pytest.mark.asyncio
async def test_second_search_served_from_cache():
    provider = FakeProvider()
    tool = InternetTool(provider=provider, cache=SearchCache())
    first = await tool.run(_args())
    assert first.ok and first.data["cached"] is False
    second = await tool.run(_args())
    assert second.ok and second.data["cached"] is True
    assert provider.search_calls == 1


@pytest.mark.asyncio
async def test_provider_error_is_graceful():
    tool = InternetTool(provider=FakeProvider(raise_error=SearchRateLimitError("slow down")))
    result = await tool.run(_args())
    assert not result.ok
    assert "slow down" in (result.error or "")


@pytest.mark.asyncio
async def test_unsupported_action_rejected():
    tool = InternetTool(provider=FakeProvider())
    result = await tool.run({"action": "hack", "query": "x", "_cap_permit": "allow"})
    assert not result.ok


@pytest.mark.asyncio
async def test_disabled_policy_rejects_everything():
    policy = SearchPolicy(enabled=False)
    tool = InternetTool(provider=FakeProvider(), policy=policy)
    result = await tool.run(_args())
    assert not result.ok
    assert "disabled" in (result.error or "")


@pytest.mark.asyncio
async def test_empty_query_rejected():
    tool = InternetTool(provider=FakeProvider())
    result = await tool.run({"action": "search", "query": "  ", "_cap_permit": "allow"})
    assert not result.ok
    assert "query" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_disallowed_category_rejected():
    tool = InternetTool(provider=FakeProvider())
    result = await tool.run({"action": "images", "query": "x", "_cap_permit": "allow"})
    assert not result.ok


@pytest.mark.asyncio
async def test_fetch_action_runs_fetcher():
    from app.internet.fetcher import ContentFetcher
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<title>T</title><body>hi</body>", headers={"content-type": "text/html"})

    tool = InternetTool(
        provider=FakeProvider(),
        fetcher=ContentFetcher(
            transport=httpx.MockTransport(handler),
            skip_dns_validation=True,
        ),
    )
    result = await tool.run({"action": "fetch", "url": "https://x.example/a", "_cap_permit": "allow"})
    assert result.ok
    assert result.data["internet"] is True
    assert result.data["content"] == "hi"


@pytest.mark.asyncio
async def test_suggest_action():
    tool = InternetTool(provider=FakeProvider())
    result = await tool.run({"action": "suggest", "query": "python", "_cap_permit": "allow"})
    assert result.ok
    assert result.data["internet"] is True
    assert result.data["suggestions"] == []


@pytest.mark.asyncio
async def test_verifier_is_applied_to_results():
    provider = FakeProvider(
        response=SearchResponse(
            query="q",
            results=[
                SearchResult(title="Python 3.13", url="https://docs.python.org/1", description="x", domain="docs.python.org"),
                SearchResult(title="Python 3.13", url="https://www.python.org/2", description="x", domain="python.org"),
            ],
            source="fake",
        )
    )
    tool = InternetTool(provider=provider)
    result = await tool.run(_args())
    assert result.ok
    confidences = [r["confidence"] for r in result.data["results"]]
    assert any(c == "high" for c in confidences)
    verifier = SearchVerifier()
    assert result.data["verification"]["verdict"] in {"high", "medium", "low", "unknown"}


@pytest.mark.asyncio
async def test_news_action_routes_to_news():
    class NewsProvider(SearchProvider):
        name = "news-fake"
        news_calls = 0

        def is_configured(self):
            return True

        async def news(self, query, *, max_results=5, timeout=None):
            self.news_calls += 1
            return SearchResponse(query=query, category="news", source="news-fake")

        async def search(self, query, *, max_results=5, timeout=None):
            return SearchResponse(query=query, category="web", source="news-fake")

    provider = NewsProvider()
    tool = InternetTool(provider=provider)
    result = await tool.run(_args(action="news"))
    assert result.ok
    assert result.data["action"] == "news"
    assert provider.news_calls == 1
