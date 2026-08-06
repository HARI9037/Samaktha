"""Phase 12.7 — SearchVerifier multi-source verification tests."""

from datetime import datetime, timedelta, timezone

from app.internet.models import SearchConfidence, SearchResponse, SearchResult
from app.internet.verifier import SearchVerifier

_TODAY = datetime.now(timezone.utc).date()


def _result(title, url, domain, published=None):
    return SearchResult(
        title=title,
        url=url,
        description="python version announcement",
        domain=domain,
        published_at=published or str(_TODAY),
    )


def _response(*results):
    return SearchResponse(query="q", results=list(results), source="test")


def test_no_results_is_unknown():
    report = SearchVerifier().verify(_response())
    assert report.verdict == SearchConfidence.UNKNOWN
    assert report.notes


def test_agreement_across_authoritative_sources_is_high():
    results = [
        _result("Python 3.13 released", "https://docs.python.org/1", "docs.python.org"),
        _result("Python 3.13 released", "https://www.python.org/2", "python.org"),
        _result("Python 3.13 released", "https://example.org/3", "example.org"),
    ]
    report = SearchVerifier().verify(_response(*results))
    assert report.verdict == SearchConfidence.HIGH
    assert report.agreeing_sources >= 2


def test_single_source_is_low():
    report = SearchVerifier().verify(
        _response(_result("Python 3.13", "https://blog.example/1", "blog.example"))
    )
    assert report.verdict == SearchConfidence.LOW


def test_conflicting_sources_is_low():
    results = [
        _result("Python 3.13 released", "https://a.example/1", "a.example"),
        _result("Python 4.0 released", "https://b.example/2", "b.example"),
        _result("Python 4.0 released", "https://c.example/3", "c.example"),
    ]
    report = SearchVerifier().verify(_response(*results))
    assert report.verdict == SearchConfidence.LOW
    assert report.conflicting_sources > 0


def test_stale_but_agreeing_is_medium():
    results = [
        _result("Python 3.13 released", "https://docs.python.org/1", "docs.python.org",
                published=str(_TODAY - timedelta(days=600))),
        _result("Python 3.13 released", "https://www.python.org/2", "python.org",
                published=str(_TODAY - timedelta(days=700))),
    ]
    report = SearchVerifier().verify(_response(*results))
    assert report.verdict == SearchConfidence.MEDIUM


def test_apply_stamps_confidence_per_result():
    results = [
        _result("Python 3.13 released", "https://docs.python.org/1", "docs.python.org"),
        _result("Python 3.13 released", "https://www.python.org/2", "python.org"),
    ]
    response = SearchResponse(query="q", results=results, source="test")
    report = SearchVerifier().verify(response)
    stamped = SearchVerifier().apply(response, report)
    for result in stamped.results:
        assert result.confidence in {
            SearchConfidence.HIGH,
            SearchConfidence.MEDIUM,
            SearchConfidence.LOW,
        }


def test_non_dominant_result_is_low():
    results = [
        _result("Python 3.13 released", "https://docs.python.org/1", "docs.python.org"),
        _result("Python 3.13 released", "https://www.python.org/2", "python.org"),
        _result("Unrelated story", "https://c.example/3", "c.example"),
    ]
    report = SearchVerifier().verify(_response(*results))
    assert report.per_result["https://c.example/3"] == SearchConfidence.LOW
