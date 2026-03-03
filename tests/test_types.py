"""Tests for unified data models."""

from devhub.types import Comment, Post, PostResult, RateLimit, UserProfile


def test_post_defaults():
    p = Post(id="1", platform="test", title="Hello", url="https://example.com")
    assert p.id == "1"
    assert p.platform == "test"
    assert p.body == ""
    assert p.tags == []
    assert p.likes == 0
    assert p.raw == {}


def test_post_frozen():
    p = Post(id="1", platform="test", title="Hello", url="https://example.com")
    try:
        p.id = "2"  # type: ignore[misc]
        assert False, "Should be frozen"
    except AttributeError:
        pass


def test_comment_defaults():
    c = Comment(id="1", platform="test", body="Nice!")
    assert c.author == ""
    assert c.parent_id is None


def test_user_profile():
    u = UserProfile(id="1", platform="test", username="alice")
    assert u.name == ""
    assert u.followers == 0


def test_post_result():
    r = PostResult(success=True, platform="devto", post_id="42", url="https://dev.to/42")
    assert r.success is True
    assert r.error == ""


def test_rate_limit():
    rl = RateLimit(platform="devto", limit=30, remaining=25)
    assert rl.reset_at is None
