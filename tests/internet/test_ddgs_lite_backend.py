"""DDGS SearchProvider live backend tests (lite backend verification)."""

from __future__ import annotations

import pytest

from app.internet.ddgs import DDGSSearchProvider


class TestDDGSLiteBackend:
    """Live tests that verify the 'lite' backend returns actual search results."""

    @pytest.mark.asyncio
    @pytest.mark.network
    async def test_ddgs_lite_backend_returns_results(self) -> None:
        """Verify 'lite' backend works and returns structured results."""
        # Use longer timeout for live network test
        provider = DDGSSearchProvider(backend="lite", timeout=30.0)
        results = await provider.search("test query", max_results=5)

        assert results.total > 0
        assert len(results.results) > 0
        for result in results.results:
            assert result.title, "Result must have a title"
            assert result.url, "Result must have a URL"
            assert result.description is not None, "Result must have a description"
            assert result.domain, "Result must have a domain"
            assert result.provider == "ddgs"
            assert result.url.startswith(("http://", "https://"))

    @pytest.mark.asyncio
    @pytest.mark.network
    async def test_ddgs_lite_backend_news_returns_results(self) -> None:
        """Verify 'lite' backend works for news search."""
        provider = DDGSSearchProvider(backend="lite", timeout=30.0)
        results = await provider.news("technology news", max_results=3)

        # News may return empty, but should not error
        assert results.category == "news"
        assert results.source == "ddgs"
        for result in results.results:
            assert result.title
            assert result.url
            # published_at may be None if the backend doesn't provide dates
            assert result.published_at is None or isinstance(result.published_at, str)

    @pytest.mark.asyncio
    @pytest.mark.network
    async def test_ddgs_default_backend_works(self) -> None:
        """Verify the default backend (from Settings) returns results."""
        from app.config.settings import Settings

        settings = Settings()
        provider = DDGSSearchProvider(backend=settings.ddgs_backend, timeout=30.0)
        results = await provider.search("test query", max_results=3)

        assert results.total > 0
        assert len(results.results) > 0
        for result in results.results:
            assert result.title
            assert result.url
            assert result.description is not None
            assert result.domain
            assert result.provider == "ddgs"