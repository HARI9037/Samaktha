"""Phase 12.5 — ResultRanker deterministic-ranking tests."""

from datetime import datetime, timedelta, timezone

from app.internet.models import SearchResponse, SearchResult
from app.internet.ranker import ResultRanker

_TODAY = datetime.now(timezone.utc).date()


def _result(title, url, description, domain, published=None):
    return SearchResult(
        title=title,
        url=url,
        description=description,
        domain=domain,
        published_at=published,
    )


def _make_response(*results):
    return SearchResponse(query="python version", results=list(results), source="test")


def test_rank_is_deterministic():
    results = [
        _result("B", "https://b.example", "unrelated text", "b.example"),
        _result("A", "https://a.example", "python version guide", "a.example"),
    ]
    first = ResultRanker().rank(_make_response(*results))
    second = ResultRanker().rank(_make_response(*results))
    assert [r.url for r in first.results] == [r.url for r in second.results]


def test_relevance_dominates_ordering():
    relevant = _result(
        "Python 3.13 release", "https://docs.python.org/x",
        "python version 3.13 release notes", "docs.python.org",
        published=str(_TODAY),
    )
    irrelevant = _result(
        "Cooking recipes", "https://cook.example",
        "bread and butter recipes for dinner", "cook.example",
        published=str(_TODAY),
    )
    ranked = ResultRanker().rank(_make_response(irrelevant, relevant))
    assert ranked.results[0].url == "https://docs.python.org/x"


def test_authoritative_domain_wins_on_tie():
    doc = _result(
        "Python 3.13", "https://docs.python.org/3.13/",
        "python 3.13 documentation reference", "docs.python.org",
    )
    blog = _result(
        "Python 3.13", "https://random-blog.example/post",
        "python 3.13 documentation reference", "random-blog.example",
    )
    ranked = ResultRanker().rank(_make_response(blog, doc))
    assert ranked.results[0].url == "https://docs.python.org/3.13/"


def test_freshness_boosts_recent_results():
    old = _result(
        "Python news", "https://news.example/old",
        "python version update announcement", "news.example",
        published=str(_TODAY - timedelta(days=700)),
    )
    fresh = _result(
        "Python news", "https://news.example/fresh",
        "python version update announcement", "news.example",
        published=str(_TODAY - timedelta(days=2)),
    )
    ranked = ResultRanker().rank(_make_response(old, fresh))
    assert ranked.results[0].url == "https://news.example/fresh"


def test_duplicate_titles_are_collapsed():
    first = _result(
        "Python 3.13 released", "https://a.example/1",
        "python version 3.13 released", "a.example",
    )
    duplicate = _result(
        "Python 3.13 Released!", "https://a.example/2",
        "python version 3.13 released", "a.example",
    )
    ranked = ResultRanker().rank(_make_response(first, duplicate))
    urls = [r.url for r in ranked.results]
    assert "https://a.example/1" in urls
    assert "https://a.example/2" not in urls
    kept = next(r for r in ranked.results if r.url == "https://a.example/1")
    assert kept.duplicate_of is None
    assert "https://a.example/1" in [r.url for r in ranked.results]


def test_result_cap_respects_policy():
    results = [
        _result(f"Title {i}", f"https://d{i}.example", f"python version {i}", f"d{i}.example")
        for i in range(10)
    ]
    ranked = ResultRanker().rank(_make_response(*results))
    assert len(ranked.results) == 5


def test_results_without_url_are_dropped():
    orphan = SearchResult(title="x", url="", domain="")
    good = _result("Python 3.13", "https://docs.python.org/x", "python version", "docs.python.org")
    ranked = ResultRanker().rank(_make_response(orphan, good))
    assert len(ranked.results) == 1
    assert ranked.results[0].url == "https://docs.python.org/x"


def test_each_result_gets_a_score():
    ranked = ResultRanker().rank(
        _make_response(
            _result("Python 3.13", "https://docs.python.org/x", "python version", "docs.python.org")
        )
    )
    assert ranked.results[0].score is not None
