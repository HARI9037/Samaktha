"""Phase 12.1/12.3 — SearchPolicy governance tests."""

from app.internet.policy import SearchPolicy


def test_ttl_for_news_is_shorter():
    policy = SearchPolicy()
    assert policy.ttl_for("web") == policy.ttl_seconds
    assert policy.ttl_for("news") == policy.news_ttl_seconds
    assert policy.ttl_for("news") < policy.ttl_for("web")


def test_category_allowlist():
    policy = SearchPolicy()
    assert policy.allows_category("web")
    assert policy.allows_category("news")
    assert not policy.allows_category("images")


def test_action_allowlist():
    policy = SearchPolicy()
    assert policy.allows_action("search")
    assert policy.allows_action("news")
    assert policy.allows_action("fetch")
    assert policy.allows_action("suggest")
    assert not policy.allows_action("hack")


def test_approval_required_default():
    assert SearchPolicy().require_approval is True


def test_authoritative_domains_present():
    policy = SearchPolicy()
    assert "docs.python.org" in policy.authoritative_domains
