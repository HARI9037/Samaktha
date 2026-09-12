"""DDGS SearchProvider contract tests (deterministic; no live network)."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import time
from types import SimpleNamespace

import pytest
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from app.internet.ddgs import DDGSSearchProvider
from app.internet.models import (
    SearchAuthError,
    SearchConfigError,
    SearchHTTPError,
    SearchNetworkError,
    SearchProviderError,
    SearchRateLimitError,
    SearchTimeoutError,
    SearchUnknownError,
)
from app.internet.ranker import ResultRanker
from app.internet.tool import InternetTool
from app.diagnostics import DiagnosticStatus, SystemDiagnostics
from app.internet.brave import BraveSearchProvider
from app.internet.searxng import SearXNGSearchProvider


class FakeDDGS:
    def __init__(self, *, text_results=None, news_results=None, failure=None) -> None:
        self.text_results = [] if text_results is None else text_results
        self.news_results = [] if news_results is None else news_results
        self.failure = failure
        self.calls: list[tuple[str, str, dict]] = []

    def text(self, query: str, **kwargs):
        self.calls.append(("text", query, kwargs))
        if self.failure is not None:
            raise self.failure
        return self.text_results

    def news(self, query: str, **kwargs):
        self.calls.append(("news", query, kwargs))
        if self.failure is not None:
            raise self.failure
        return self.news_results


def _provider(client: FakeDDGS, *, timeout: float = 10.0):
    constructor_calls: list[dict] = []

    def factory(**kwargs):
        constructor_calls.append(kwargs)
        return client

    return DDGSSearchProvider(timeout=timeout, client_factory=factory), constructor_calls


def _failure_log(caplog: pytest.LogCaptureFixture) -> str:
    matches = [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.internet.ddgs"
        and record.getMessage().startswith("DDGS failure:")
    ]
    assert len(matches) == 1
    return matches[0]


def _assert_failure_log(
    caplog: pytest.LogCaptureFixture,
    *,
    category: str,
    stage: str,
    exception_type: str,
    mapped_error_type: str,
) -> None:
    rendered = _failure_log(caplog)
    assert "provider=ddgs" in rendered
    assert "backend=duckduckgo" in rendered
    assert f"category={category}" in rendered
    assert f"failure_stage={stage}" in rendered
    assert f"exception_type={exception_type}" in rendered
    assert f"mapped_error_type={mapped_error_type}" in rendered
    assert "private query" not in rendered
    assert "SECRET" not in rendered


def test_ddgs_requires_no_api_key_or_endpoint() -> None:
    provider = DDGSSearchProvider()
    assert provider.is_configured() is True
    assert not hasattr(provider, "api_key")
    assert not hasattr(provider, "endpoint_origin")


@pytest.mark.asyncio
async def test_general_search_uses_text_and_normalizes_results() -> None:
    client = FakeDDGS(
        text_results=[
            {
                "title": " Python documentation ",
                "href": "https://docs.python.org/3/",
                "body": "Official language documentation.",
                "ignored": "provider-private",
            }
        ]
    )
    provider, constructor_calls = _provider(client)

    response = await provider.search("python", max_results=5)

    assert client.calls == [("text", "python", {"max_results": 5, "backend": "duckduckgo"})]
    assert constructor_calls == [{"timeout": 10, "verify": True}]
    assert response.source == "ddgs"
    assert response.category == "web"
    assert response.total == 1
    result = response.results[0]
    assert result.title == "Python documentation"
    assert result.url == "https://docs.python.org/3/"
    assert result.description == "Official language documentation."
    assert result.domain == "docs.python.org"
    assert result.provider == "ddgs"
    assert result.published_at is None
    assert result.score is None
    assert result.source_id == ""
    assert result.rank is None
    assert result.meta == {}


@pytest.mark.asyncio
async def test_news_search_uses_news_and_preserves_only_supported_metadata() -> None:
    client = FakeDDGS(
        news_results=[
            {
                "date": "2026-08-25T12:30:00+00:00",
                "title": "Current news",
                "body": "A current report.",
                "url": "https://news.example/report",
                "image": "https://untrusted.example/image.png",
                "source": "Example News",
            }
        ]
    )
    provider, _ = _provider(client)

    response = await provider.news("current report", max_results=3)

    assert client.calls == [("news", "current report", {"max_results": 3, "backend": "duckduckgo"})]
    assert response.category == "news"
    assert response.results[0].published_at == "2026-08-25"
    assert response.results[0].meta == {"publisher": "Example News"}
    assert "image" not in response.results[0].meta


@pytest.mark.asyncio
async def test_missing_optional_fields_are_not_fabricated() -> None:
    provider, _ = _provider(
        FakeDDGS(text_results=[{"href": "https://example.test/item"}])
    )
    result = (await provider.search("item")).results[0]
    assert result.title == ""
    assert result.description == ""
    assert result.published_at is None
    assert result.score is None
    assert result.meta == {}


@pytest.mark.asyncio
async def test_results_are_bounded_and_unsafe_urls_are_omitted() -> None:
    items = [
        {"title": "x" * 900, "href": "https://example.test/a", "body": "y" * 8_000},
        {"title": "bad", "href": "javascript:alert(1)", "body": "bad"},
        {"title": "credentials", "href": "https://user:pass@example.test/", "body": "bad"},
    ] + [
        {"title": f"item {index}", "href": f"https://example.test/{index}", "body": "ok"}
        for index in range(30)
    ]
    provider, _ = _provider(FakeDDGS(text_results=items))
    response = await provider.search("bounded", max_results=999)
    assert len(response.results) == 20
    assert len(response.results[0].title) == 500
    assert len(response.results[0].description) == 4_000
    assert all(result.url.startswith("https://") for result in response.results)


@pytest.mark.asyncio
async def test_duplicate_canonical_urls_are_deduplicated_by_existing_ranker() -> None:
    provider, _ = _provider(
        FakeDDGS(
            text_results=[
                {"title": "One", "href": "https://example.test/a?utm_source=x", "body": "first"},
                {"title": "Two", "href": "https://example.test/a", "body": "second"},
            ]
        )
    )
    ranked = ResultRanker().rank(await provider.search("example"))
    assert len(ranked.results) == 1
    assert ranked.results[0].source_id
    assert ranked.results[0].rank == 1


@pytest.mark.asyncio
async def test_empty_results_reach_internet_tool_as_typed_empty_outcome() -> None:
    provider, _ = _provider(FakeDDGS())
    result = await InternetTool(provider=provider).run(
        {"action": "search", "query": "nothing", "_cap_permit": "allow"}
    )
    assert result.ok is False
    assert result.metadata["failure_type"] == "empty"


@pytest.mark.asyncio
async def test_query_length_is_bounded_before_ddgs_is_called() -> None:
    client = FakeDDGS()
    provider, _ = _provider(client)
    result = await InternetTool(provider=provider).run(
        {"action": "search", "query": "x" * 10_000, "_cap_permit": "allow"}
    )
    assert result.ok is False
    assert "maximum" in (result.error or "")
    assert client.calls == []


@pytest.mark.asyncio
async def test_malformed_provider_collection_is_typed() -> None:
    provider, _ = _provider(FakeDDGS(text_results={"not": "a list"}))
    with pytest.raises(SearchProviderError, match="unsupported"):
        await provider.search("malformed")


@pytest.mark.asyncio
async def test_normalization_failure_has_bounded_internal_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider, _ = _provider(FakeDDGS(text_results={"not": "a list"}))
    with caplog.at_level(logging.WARNING, logger="app.internet.ddgs"):
        with pytest.raises(SearchProviderError) as exc_info:
            await provider.search("private query")
    assert exc_info.value.__cause__ is None
    _assert_failure_log(
        caplog,
        category="web",
        stage="normalization",
        exception_type="SearchProviderError",
        mapped_error_type="SearchProviderError",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        (TimeoutException("SECRET timeout details"), SearchTimeoutError),
        (RatelimitException("SECRET rate details"), SearchRateLimitError),
        (DDGSException("HTTP 401 SECRET"), SearchAuthError),
        (DDGSException("HTTP 503 SECRET"), SearchHTTPError),
        (DDGSException("connection reset SECRET"), SearchNetworkError),
        (DDGSException("provider internals SECRET"), SearchUnknownError),
    ],
)
async def test_ddgs_failures_are_typed_and_sanitized(failure, error_type) -> None:
    provider, _ = _provider(FakeDDGS(failure=failure))
    with pytest.raises(error_type) as exc_info:
        await provider.search("private query")
    rendered = str(exc_info.value)
    assert "SECRET" not in rendered
    assert "private query" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        (TimeoutException("SECRET timeout details"), SearchTimeoutError),
        (RatelimitException("SECRET rate details"), SearchRateLimitError),
        (DDGSException("HTTP 503 SECRET"), SearchHTTPError),
        (OSError("SECRET network details"), SearchNetworkError),
        (DDGSException("SECRET provider internals"), SearchUnknownError),
    ],
)
async def test_provider_call_failure_logs_safe_stage_and_preserves_cause(
    failure: Exception,
    error_type: type[Exception],
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider, _ = _provider(FakeDDGS(failure=failure))
    with caplog.at_level(logging.WARNING, logger="app.internet.ddgs"):
        with pytest.raises(error_type) as exc_info:
            await provider.search("private query")
    assert exc_info.value.__cause__ is failure
    _assert_failure_log(
        caplog,
        category="web",
        stage="provider_call",
        exception_type=type(failure).__name__,
        mapped_error_type=error_type.__name__,
    )


@pytest.mark.asyncio
async def test_news_failure_records_news_provider_call_stage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure = DDGSException("SECRET news failure")
    provider, _ = _provider(FakeDDGS(failure=failure))
    with caplog.at_level(logging.WARNING, logger="app.internet.ddgs"):
        with pytest.raises(SearchUnknownError):
            await provider.news("private query")
    _assert_failure_log(
        caplog,
        category="news",
        stage="provider_call",
        exception_type="DDGSException",
        mapped_error_type="SearchUnknownError",
    )


@pytest.mark.asyncio
async def test_internet_tool_keeps_user_error_sanitized_while_log_has_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider, _ = _provider(
        FakeDDGS(failure=DDGSException("SECRET private query provider internals"))
    )
    with caplog.at_level(logging.WARNING, logger="app.internet.ddgs"):
        result = await InternetTool(provider=provider).run(
            {
                "action": "search",
                "query": "private query",
                "_cap_permit": "allow",
            }
        )
    assert result.ok is False
    assert result.error == "DDGS search provider failed."
    assert result.metadata["failure_type"] == "unknown"
    _assert_failure_log(
        caplog,
        category="web",
        stage="provider_call",
        exception_type="DDGSException",
        mapped_error_type="SearchUnknownError",
    )


@pytest.mark.asyncio
async def test_constructor_failure_records_construction_stage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure = RuntimeError("SECRET constructor failure")

    def broken_factory(**_kwargs):
        raise failure

    provider = DDGSSearchProvider(client_factory=broken_factory)
    with caplog.at_level(logging.WARNING, logger="app.internet.ddgs"):
        with pytest.raises(SearchUnknownError) as exc_info:
            await provider.search("private query")
    assert exc_info.value.__cause__ is failure
    _assert_failure_log(
        caplog,
        category="web",
        stage="client_construction",
        exception_type="RuntimeError",
        mapped_error_type="SearchUnknownError",
    )


@pytest.mark.asyncio
async def test_method_selection_failure_records_stage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure = AttributeError("SECRET method selection")

    class BrokenClient:
        @property
        def text(self):
            raise failure

    provider = DDGSSearchProvider(client_factory=lambda **_kwargs: BrokenClient())
    with caplog.at_level(logging.WARNING, logger="app.internet.ddgs"):
        with pytest.raises(SearchUnknownError) as exc_info:
            await provider.search("private query")
    assert exc_info.value.__cause__ is failure
    _assert_failure_log(
        caplog,
        category="web",
        stage="method_selection",
        exception_type="AttributeError",
        mapped_error_type="SearchUnknownError",
    )


@pytest.mark.asyncio
async def test_outer_timeout_is_bounded_and_sanitized() -> None:
    class SlowDDGS(FakeDDGS):
        def text(self, query: str, **kwargs):
            self.calls.append(("text", query, kwargs))
            time.sleep(0.05)
            return []

    provider, _ = _provider(SlowDDGS(), timeout=0.01)
    with pytest.raises(SearchTimeoutError, match="timed out"):
        await provider.search("slow")


@pytest.mark.asyncio
async def test_outer_timeout_records_safe_provider_call_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class SlowDDGS(FakeDDGS):
        def text(self, query: str, **kwargs):
            self.calls.append(("text", query, kwargs))
            time.sleep(0.05)
            return []

    provider, _ = _provider(SlowDDGS(), timeout=0.01)
    with caplog.at_level(logging.WARNING, logger="app.internet.ddgs"):
        with pytest.raises(SearchTimeoutError) as exc_info:
            await provider.search("private query")
    assert isinstance(exc_info.value.__cause__, TimeoutError)
    _assert_failure_log(
        caplog,
        category="web",
        stage="provider_call",
        exception_type="TimeoutError",
        mapped_error_type="SearchTimeoutError",
    )


@pytest.mark.asyncio
async def test_no_results_found_remains_empty_and_is_not_logged_as_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider, _ = _provider(FakeDDGS(failure=DDGSException("No results found.")))
    with caplog.at_level(logging.WARNING, logger="app.internet.ddgs"):
        response = await provider.search("private query")
    assert response.results == []
    assert response.total == 0
    assert not [
        record
        for record in caplog.records
        if record.name == "app.internet.ddgs"
        and record.getMessage().startswith("DDGS failure:")
    ]


@pytest.mark.asyncio
async def test_provider_failure_makes_one_call_and_never_auto_falls_back() -> None:
    client = FakeDDGS(failure=DDGSException("provider failure"))
    provider, _ = _provider(client)
    with pytest.raises(SearchUnknownError):
        await provider.search("one operation")
    assert len(client.calls) == 1


def test_zero_key_ddgs_configuration_does_not_depend_on_dynamic_module_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None if name == "ddgs" else None)
    provider = DDGSSearchProvider()
    assert provider.is_configured() is True


@pytest.mark.asyncio
async def test_missing_dependency_fails_at_adapter_boundary_without_fake_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    original_import = builtins.__import__

    def missing_ddgs(name, *args, **kwargs):
        if name == "ddgs":
            raise ImportError("simulated missing declared dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_ddgs)
    provider = DDGSSearchProvider()
    with pytest.raises(SearchConfigError, match="dependency is unavailable"):
        await provider.search("query", max_results=1)


@pytest.mark.asyncio
async def test_import_failure_is_typed_logged_and_chained(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import builtins

    original_import = builtins.__import__

    def missing_ddgs(name, *args, **kwargs):
        if name == "ddgs":
            raise ImportError("SECRET missing dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_ddgs)
    provider = DDGSSearchProvider()
    with caplog.at_level(logging.WARNING, logger="app.internet.ddgs"):
        with pytest.raises(SearchConfigError) as exc_info:
            await provider.search("private query")
    assert isinstance(exc_info.value.__cause__, ImportError)
    _assert_failure_log(
        caplog,
        category="web",
        stage="dependency_import",
        exception_type="ImportError",
        mapped_error_type="SearchConfigError",
    )


@pytest.mark.parametrize("timeout", [0, -1, 61, float("inf"), float("nan"), "bad"])
def test_invalid_timeout_fails_as_configuration(timeout) -> None:
    with pytest.raises(SearchConfigError):
        DDGSSearchProvider(timeout=timeout)


@pytest.mark.asyncio
async def test_health_is_offline_and_does_not_execute_a_search() -> None:
    client = FakeDDGS(failure=AssertionError("health must not search"))
    provider, _ = _provider(client)
    assert await provider.health() is True
    assert client.calls == []


def _diagnostic_rows(provider):
    orchestrator = SimpleNamespace(
        internet_tool=SimpleNamespace(provider=provider)
    )
    return {
        row.label: row
        for row in SystemDiagnostics(orchestrator=orchestrator)._search_checks()
    }


def test_ddgs_diagnostics_need_no_endpoint_or_key_and_do_not_probe() -> None:
    client = FakeDDGS(failure=AssertionError("diagnostics must not search"))
    provider, _ = _provider(client)
    rows = _diagnostic_rows(provider)
    assert rows["Provider"].detail == "DDGS"
    assert rows["Configured"].status == DiagnosticStatus.OK
    assert rows["Health"].status == DiagnosticStatus.OK
    assert "live search not probed" in rows["Health"].detail
    assert "Endpoint" not in rows
    assert client.calls == []


def test_searxng_endpoint_diagnostics_remain_provider_specific() -> None:
    rows = _diagnostic_rows(SearXNGSearchProvider(base_url=""))
    assert rows["Provider"].detail == "SearXNG"
    assert rows["Configured"].status == DiagnosticStatus.WARN
    assert rows["Endpoint"].detail == "not configured"


def test_brave_key_configuration_diagnostics_remain_truthful() -> None:
    missing = _diagnostic_rows(BraveSearchProvider(api_key=""))
    configured = _diagnostic_rows(BraveSearchProvider(api_key="test-key"))
    assert missing["Configured"].status == DiagnosticStatus.WARN
    assert configured["Configured"].status == DiagnosticStatus.OK
    assert "Endpoint" not in missing


def test_ddgs_diagnostics_report_zero_key_configuration_without_module_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    rows = _diagnostic_rows(DDGSSearchProvider())
    assert rows["Provider"].detail == "DDGS"
    assert rows["Configured"].status == DiagnosticStatus.OK
    assert rows["Health"].status == DiagnosticStatus.OK
