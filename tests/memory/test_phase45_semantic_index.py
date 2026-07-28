"""Phase 4.5 tests — SemanticIndex behavior."""
import pytest
from app.memory.semantic_index import SemanticIndex


def test_index_and_search_basic():
    idx = SemanticIndex()
    idx.index("a", "python code execution script", {"category": "skill"})
    idx.index("b", "database query sql postgres", {"category": "data"})
    idx.index("c", "python script automation tool", {"category": "skill"})

    results = idx.search("python script", top_k=10)
    ids = [r[0] for r in results]

    # Both python-related items should appear; database one should not
    assert "a" in ids
    assert "c" in ids
    assert "b" not in ids  # "python" and "script" don't appear in b


def test_ranking_is_deterministic():
    idx = SemanticIndex()
    for i in range(5):
        idx.index(f"item-{i}", f"machine learning model training {i}")

    r1 = idx.search("machine learning training")
    r2 = idx.search("machine learning training")
    assert r1 == r2


def test_score_decreases_with_lower_overlap():
    idx = SemanticIndex()
    idx.index("exact", "execute python workflow automation task")
    idx.index("partial", "automation task")
    idx.index("unrelated", "database sql query")

    results = idx.search("execute python workflow automation task", top_k=3)
    scores = {r[0]: r[1] for r in results}

    # exact match should outscore partial which should outscore (absent) unrelated
    assert scores["exact"] > scores.get("partial", 0.0)
    assert "unrelated" not in scores


def test_matched_features_populated():
    idx = SemanticIndex()
    idx.index("s1", "workflow execution scheduling parallel")

    results = idx.search("parallel scheduling", top_k=5)
    assert len(results) == 1
    _id, _score, matched = results[0]
    assert "parallel" in matched or "scheduling" in matched


def test_metadata_filter():
    idx = SemanticIndex()
    idx.index("skill-a", "python automation", {"category": "skill"})
    idx.index("context-b", "python environment", {"category": "context"})

    results = idx.search("python", top_k=10, filters={"category": "skill"})
    ids = [r[0] for r in results]
    assert "skill-a" in ids
    assert "context-b" not in ids


def test_remove_item():
    idx = SemanticIndex()
    idx.index("s1", "python task runner")
    idx.index("s2", "python workflow")

    idx.remove("s1")
    results = idx.search("python task runner")
    ids = [r[0] for r in results]
    assert "s1" not in ids


def test_idf_weights_rare_tokens_higher():
    idx = SemanticIndex()
    # "python" appears in all 3, "alchemy" only in 1
    idx.index("x", "python alchemy magic")
    idx.index("y", "python common task")
    idx.index("z", "python standard execution")

    results = idx.search("alchemy", top_k=3)
    assert len(results) == 1
    assert results[0][0] == "x"
