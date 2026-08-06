"""Phase 12.1 — core model + error-hierarchy tests."""

import pytest

from app.internet.models import (
    SearchAuthError,
    SearchCancelledError,
    SearchConfigError,
    SearchConfidence,
    SearchError,
    SearchHTTPError,
    SearchNetworkError,
    SearchProviderError,
    SearchRateLimitError,
    SearchResponse,
    SearchResult,
    SearchTimeoutError,
    SourceMetadata,
    VerificationReport,
)


def test_search_result_defaults_are_sane():
    result = SearchResult(title="t", url="https://example.com", domain="example.com")
    assert result.description == ""
    assert result.confidence == SearchConfidence.UNKNOWN
    assert result.duplicate_of is None
    assert result.score is None


def test_search_response_defaults():
    response = SearchResponse(query="q", source="brave")
    assert response.results == []
    assert response.total == 0
    assert response.cached is False
    assert response.error is None


def test_verification_report_defaults_to_unknown():
    report = VerificationReport()
    assert report.verdict == SearchConfidence.UNKNOWN
    assert report.per_result == {}
    assert report.notes == []


def test_source_metadata_roundtrip():
    meta = SourceMetadata(
        title="t",
        url="https://example.com/a",
        domain="example.com",
        confidence=SearchConfidence.HIGH,
    )
    dumped = meta.model_dump()
    assert dumped["confidence"] == "high"


def test_error_hierarchy_is_subclassed():
    errors = [
        SearchConfigError,
        SearchNetworkError,
        SearchTimeoutError,
        SearchRateLimitError,
        SearchAuthError,
        SearchProviderError,
        SearchCancelledError,
    ]
    for cls in errors:
        assert issubclass(cls, SearchError)


def test_timeout_error_is_also_network_error():
    assert issubclass(SearchTimeoutError, SearchNetworkError)


def test_http_error_carries_status_code():
    error = SearchHTTPError(429)
    assert error.status_code == 429
    assert "429" in str(error)


def test_errors_are_catchable_as_search_error():
    with pytest.raises(SearchError):
        raise SearchRateLimitError("too many requests")
