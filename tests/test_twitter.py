"""Tests for Twitter hybrid adapter — twikit (read) + tweepy (write)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from devhub.twitter import Twitter


# ── fixtures ─────────────────────────────────────────────────────


def _make_twikit_user(screen_name: str = "testuser", name: str = "Test User") -> SimpleNamespace:
    return SimpleNamespace(
        id="111",
        screen_name=screen_name,
        name=name,
        description="A developer",
        followers_count=100,
    )


def _make_twikit_tweet(
    tweet_id: str = "999",
    text: str = "Hello world",
    user: SimpleNamespace | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=tweet_id,
        text=text,
        user=user or _make_twikit_user(),
        favorite_count=42,
        reply_count=5,
        created_at="Mon Jan 15 10:00:00 +0000 2024",
    )


def _make_tweepy_tweet(
    tweet_id: int = 888,
    text: str = "Hello tweepy",
    author_id: int = 222,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=tweet_id,
        text=text,
        author_id=author_id,
        public_metrics={"like_count": 10, "reply_count": 2},
        created_at=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
    )


def _make_tweepy_user(user_id: int = 222, username: str = "tweepyuser") -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        username=username,
        name="Tweepy User",
        description="bio",
        public_metrics={"followers_count": 50},
    )


def _make_tweepy_response(
    data: object = None,
    includes: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(data=data, includes=includes)


# ── is_configured ────────────────────────────────────────────────


async def test_is_configured_none():
    with patch.dict("os.environ", {}, clear=True):
        assert Twitter.is_configured() is False


async def test_is_configured_twikit_only():
    env = {"TWITTER_USERNAME": "user", "TWITTER_PASSWORD": "pass"}
    with patch.dict("os.environ", env, clear=True):
        assert Twitter.is_configured() is True


async def test_is_configured_tweepy_only():
    env = {
        "TWITTER_API_KEY": "k",
        "TWITTER_API_SECRET": "s",
        "TWITTER_ACCESS_TOKEN": "t",
        "TWITTER_ACCESS_SECRET": "a",
    }
    with patch.dict("os.environ", env, clear=True):
        assert Twitter.is_configured() is True


async def test_is_configured_both():
    env = {
        "TWITTER_USERNAME": "user",
        "TWITTER_PASSWORD": "pass",
        "TWITTER_API_KEY": "k",
        "TWITTER_API_SECRET": "s",
        "TWITTER_ACCESS_TOKEN": "t",
        "TWITTER_ACCESS_SECRET": "a",
    }
    with patch.dict("os.environ", env, clear=True):
        assert Twitter.is_configured() is True


# ── read: twikit priority ───────────────────────────────────────


async def test_get_trending_uses_twikit():
    tw = Twitter()
    tw._twikit = MagicMock()
    tweet = _make_twikit_tweet()
    tw._twikit.search_tweet = AsyncMock(return_value=[tweet])

    posts = await tw.get_trending(limit=10)

    assert len(posts) == 1
    assert posts[0].id == "999"
    assert posts[0].body == "Hello world"
    assert posts[0].author == "testuser"
    assert posts[0].likes == 42
    assert posts[0].platform == "twitter"
    tw._twikit.search_tweet.assert_awaited_once()


async def test_search_uses_twikit():
    tw = Twitter()
    tw._twikit = MagicMock()
    tweet = _make_twikit_tweet()
    tw._twikit.search_tweet = AsyncMock(return_value=[tweet])

    posts = await tw.search("python", limit=5)

    assert len(posts) == 1
    assert posts[0].body == "Hello world"


async def test_get_post_uses_twikit():
    tw = Twitter()
    tw._twikit = MagicMock()
    tweet = _make_twikit_tweet(tweet_id="123")
    tw._twikit.get_tweet_by_id = AsyncMock(return_value=tweet)

    post = await tw.get_post("123")

    assert post.id == "123"
    assert post.url == "https://x.com/i/status/123"


async def test_get_post_twikit_not_found():
    tw = Twitter()
    tw._twikit = MagicMock()
    tw._twikit.get_tweet_by_id = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="not found"):
        await tw.get_post("999")


async def test_get_comments_uses_twikit():
    tw = Twitter()
    tw._twikit = MagicMock()
    reply = _make_twikit_tweet(tweet_id="200", text="Nice thread")
    tw._twikit.search_tweet = AsyncMock(return_value=[reply])

    comments = await tw.get_comments("100", limit=10)

    assert len(comments) == 1
    assert comments[0].post_id == "100"
    assert comments[0].body == "Nice thread"


async def test_get_user_uses_twikit():
    tw = Twitter()
    tw._twikit = MagicMock()
    user = _make_twikit_user()
    tw._twikit.get_user_by_screen_name = AsyncMock(return_value=user)

    profile = await tw.get_user("testuser")

    assert profile.username == "testuser"
    assert profile.followers == 100
    assert profile.url == "https://x.com/testuser"


async def test_get_user_twikit_not_found():
    tw = Twitter()
    tw._twikit = MagicMock()
    tw._twikit.get_user_by_screen_name = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="not found"):
        await tw.get_user("ghost")


# ── read: tweepy fallback ───────────────────────────────────────


async def test_get_trending_falls_back_to_tweepy():
    tw = Twitter()
    tw._twikit = None
    tw._tweepy = MagicMock()
    tweet = _make_tweepy_tweet()
    user = _make_tweepy_user()
    tw._tweepy.search_recent_tweets = AsyncMock(
        return_value=_make_tweepy_response(data=[tweet], includes={"users": [user]}),
    )

    posts = await tw.get_trending(limit=10)

    assert len(posts) == 1
    assert posts[0].id == "888"
    assert posts[0].author == "tweepyuser"
    tw._tweepy.search_recent_tweets.assert_awaited_once()


async def test_search_falls_back_to_tweepy():
    tw = Twitter()
    tw._twikit = None
    tw._tweepy = MagicMock()
    tw._tweepy.search_recent_tweets = AsyncMock(
        return_value=_make_tweepy_response(data=None),
    )

    posts = await tw.search("python")
    assert posts == []


async def test_get_post_falls_back_to_tweepy():
    tw = Twitter()
    tw._twikit = None
    tw._tweepy = MagicMock()
    tweet = _make_tweepy_tweet(tweet_id=777)
    user = _make_tweepy_user()
    tw._tweepy.get_tweet = AsyncMock(
        return_value=_make_tweepy_response(data=tweet, includes={"users": [user]}),
    )

    post = await tw.get_post("777")
    assert post.id == "777"


async def test_read_no_backend_raises():
    tw = Twitter()
    tw._twikit = None
    tw._tweepy = None

    with pytest.raises(RuntimeError, match="no read backend"):
        await tw.get_trending()


# ── write: tweepy only ──────────────────────────────────────────


async def test_write_post_success():
    tw = Twitter()
    tw._tweepy = MagicMock()
    tw._tweepy.create_tweet = AsyncMock(
        return_value=SimpleNamespace(data={"id": "500"}),
    )

    result = await tw.write_post("Title", "Body", tags=["python"])

    assert result.success is True
    assert result.post_id == "500"
    assert "500" in result.url


async def test_write_post_no_tweepy():
    tw = Twitter()
    tw._tweepy = None

    result = await tw.write_post("Title", "Body")

    assert result.success is False
    assert "tweepy" in result.error.lower()


async def test_write_post_exception():
    tw = Twitter()
    tw._tweepy = MagicMock()
    tw._tweepy.create_tweet = AsyncMock(side_effect=RuntimeError("rate limit"))

    result = await tw.write_post("Title", "Body")

    assert result.success is False
    assert "rate limit" in result.error


async def test_write_comment_success():
    tw = Twitter()
    tw._tweepy = MagicMock()
    tw._tweepy.create_tweet = AsyncMock(
        return_value=SimpleNamespace(data={"id": "600"}),
    )

    result = await tw.write_comment("100", "Nice post!")

    assert result.success is True
    assert result.post_id == "600"


async def test_write_comment_no_tweepy():
    tw = Twitter()
    tw._tweepy = None

    result = await tw.write_comment("100", "Nice!")

    assert result.success is False


async def test_upvote_success():
    tw = Twitter()
    tw._tweepy = MagicMock()
    tw._tweepy.like = AsyncMock(
        return_value=SimpleNamespace(data={"liked": True}),
    )

    result = await tw.upvote("100")

    assert result.success is True
    assert result.post_id == "100"


async def test_upvote_no_tweepy():
    tw = Twitter()
    tw._tweepy = None

    result = await tw.upvote("100")

    assert result.success is False


# ── cookie lifecycle ─────────────────────────────────────────────


async def test_connect_loads_cookies(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text("{}")

    with patch("devhub.twitter.TwikitClient") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.load_cookies = MagicMock()

        tw = Twitter(username="user", password="pass", cookie_path=str(cookie_file))
        await tw.connect()

        mock_client.load_cookies.assert_called_once_with(str(cookie_file))
        assert tw._twikit is mock_client


async def test_connect_login_and_save_cookies(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    # cookie file does NOT exist

    with patch("devhub.twitter.TwikitClient") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.login = AsyncMock()
        mock_client.save_cookies = MagicMock()

        tw = Twitter(username="user", password="pass", cookie_path=str(cookie_file))
        await tw.connect()

        mock_client.login.assert_awaited_once()
        mock_client.save_cookies.assert_called_once()


async def test_connect_twikit_login_failure_falls_back():
    with patch("devhub.twitter.TwikitClient") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.login = AsyncMock(side_effect=RuntimeError("login failed"))

        tw = Twitter(
            username="user",
            password="pass",
            cookie_path="/tmp/nonexistent_cookies.json",
            api_key="k",
            api_secret="s",
            access_token="t",
            access_secret="a",
        )
        await tw.connect()

        # twikit failed gracefully, tweepy is still available
        assert tw._twikit is None
        assert tw._tweepy is not None


async def test_close_saves_cookies():
    tw = Twitter()
    mock_client = MagicMock()
    mock_client.save_cookies = MagicMock()
    tw._twikit = mock_client
    tw._cookie_path = MagicMock()
    tw._cookie_path.parent.mkdir = MagicMock()

    await tw.close()

    mock_client.save_cookies.assert_called_once()
    assert tw._twikit is None


# ── twikit Tweet → Post conversion ──────────────────────────────


async def test_twikit_tweet_to_post_fields():
    tw = Twitter()
    tweet = _make_twikit_tweet(tweet_id="777", text="Test tweet")

    post = tw._twikit_tweet_to_post(tweet)

    assert post.id == "777"
    assert post.platform == "twitter"
    assert post.title == "Test tweet"
    assert post.body == "Test tweet"
    assert post.author == "testuser"
    assert post.likes == 42
    assert post.comments_count == 5
    assert post.url == "https://x.com/i/status/777"
    assert post.published_at is not None
    assert post.raw == {"id": "777", "text": "Test tweet"}


async def test_twikit_datetime_parsing():
    tw = Twitter()
    tweet = _make_twikit_tweet()
    post = tw._twikit_tweet_to_post(tweet)

    assert post.published_at is not None
    assert post.published_at.year == 2024
    assert post.published_at.month == 1


async def test_twikit_datetime_none():
    tw = Twitter()
    tweet = _make_twikit_tweet()
    tweet.created_at = None
    post = tw._twikit_tweet_to_post(tweet)

    assert post.published_at is None


async def test_twikit_tweet_missing_user():
    tw = Twitter()
    tweet = _make_twikit_tweet()
    tweet.user = None
    post = tw._twikit_tweet_to_post(tweet)

    assert post.author == ""


# ── context manager ──────────────────────────────────────────────


async def test_context_manager():
    with patch("devhub.twitter.TwikitClient", None), \
         patch("devhub.twitter.TweepyAsyncClient", None):
        async with Twitter() as tw:
            assert tw._twikit is None
            assert tw._tweepy is None
