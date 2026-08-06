"""Phase 12.9 — SearchCache TTL/determinism tests."""

import time

from app.internet.cache import SearchCache
from app.internet.models import SearchResponse


def _response(query: str, marker: str) -> SearchResponse:
    return SearchResponse(query=query, source="test", metadata={"marker": marker})


def test_roundtrip_get_put():
    cache = SearchCache()
    cache.put("web", "python 3.13", _response("python 3.13", "a"))
    hit = cache.get("web", "python 3.13")
    assert hit is not None
    assert hit.metadata["marker"] == "a"


def test_query_key_is_normalized_deterministically():
    cache = SearchCache()
    cache.put("web", "  Python! 3.13  ", _response("q", "a"))
    assert cache.get("web", "python 3.13") is not None
    assert cache.get("web", "PYTHON 3.13") is not None
    assert cache.get("web", "python 313") is None


def test_category_is_namespaced():
    cache = SearchCache()
    cache.put("web", "q", _response("q", "web"))
    assert cache.get("web", "q") is not None
    assert cache.get("news", "q") is None


def test_ttl_expiry():
    cache = SearchCache()
    cache.put("web", "q", _response("q", "a"), ttl_seconds=1)
    assert cache.get("web", "q") is not None
    time.sleep(1.2)
    assert cache.get("web", "q") is None


def test_invalidate_category():
    cache = SearchCache()
    cache.put("web", "q", _response("q", "a"))
    cache.put("news", "q", _response("q", "b"))
    removed = cache.invalidate(category="web")
    assert removed == 1
    assert cache.get("web", "q") is None
    assert cache.get("news", "q") is not None


def test_clear_removes_everything():
    cache = SearchCache()
    cache.put("web", "q1", _response("q1", "a"))
    cache.put("news", "q2", _response("q2", "b"))
    assert cache.clear() == 2
    assert cache.get("web", "q1") is None
    assert cache.get("news", "q2") is None


def test_stats_track_hits_misses():
    cache = SearchCache()
    cache.put("web", "q", _response("q", "a"))
    assert cache.get("web", "q") is not None
    assert cache.get("web", "missing") is None
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["stored"] == 1
    assert stats["live_entries"] == 1
