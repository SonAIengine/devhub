"""Twitter/X hybrid adapter — twikit (free read) + tweepy (official write)."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from devhub.base import PlatformAdapter
from devhub.types import Comment, Post, PostResult, UserProfile

try:
    from twikit import Client as TwikitClient
except ImportError:
    TwikitClient = None  # noqa: N816

try:
    from tweepy.asynchronous import AsyncClient as TweepyAsyncClient
except ImportError:
    TweepyAsyncClient = None  # noqa: N816

logger = logging.getLogger(__name__)

_DEFAULT_COOKIE_PATH = Path.home() / ".devhub" / "twitter_cookies.json"

_TWEET_FIELDS = ["id", "text", "author_id", "created_at", "public_metrics"]
_USER_FIELDS = ["id", "name", "username", "description", "public_metrics", "profile_image_url"]


class Twitter(PlatformAdapter):
    """Hybrid async adapter for Twitter/X.

    Read operations use twikit (free, login-based) with tweepy fallback.
    Write operations use tweepy (official API v2) exclusively.
    """

    platform = "twitter"

    def __init__(
        self,
        # twikit (read)
        username: str | None = None,
        email: str | None = None,
        password: str | None = None,
        cookie_path: str | None = None,
        # tweepy (write + search)
        api_key: str | None = None,
        api_secret: str | None = None,
        access_token: str | None = None,
        access_secret: str | None = None,
        bearer_token: str | None = None,
    ) -> None:
        # twikit credentials
        self._tw_username = username or os.getenv("TWITTER_USERNAME", "")
        self._tw_email = email or os.getenv("TWITTER_EMAIL", "")
        self._tw_password = password or os.getenv("TWITTER_PASSWORD", "")
        self._cookie_path = Path(
            cookie_path or os.getenv("TWITTER_COOKIE_PATH") or str(_DEFAULT_COOKIE_PATH)
        )

        # tweepy credentials
        self._api_key = api_key or os.getenv("TWITTER_API_KEY", "")
        self._api_secret = api_secret or os.getenv("TWITTER_API_SECRET", "")
        self._access_token = access_token or os.getenv("TWITTER_ACCESS_TOKEN", "")
        self._access_secret = access_secret or os.getenv("TWITTER_ACCESS_SECRET", "")
        self._bearer_token = bearer_token or os.getenv("TWITTER_BEARER_TOKEN", "")

        # runtime clients (set in connect())
        self._twikit: Any | None = None
        self._tweepy: Any | None = None

    # -- lifecycle --

    async def connect(self) -> None:
        # twikit init
        if self._has_twikit_creds and TwikitClient is not None:
            try:
                client = TwikitClient("en-US")
                if self._cookie_path.exists():
                    client.load_cookies(str(self._cookie_path))
                    logger.info("twikit: loaded cookies from %s", self._cookie_path)
                else:
                    await client.login(
                        auth_info_1=self._tw_username,
                        auth_info_2=self._tw_email,
                        password=self._tw_password,
                    )
                    self._save_cookies(client)
                    logger.info("twikit: logged in and saved cookies")
                self._twikit = client
            except Exception:
                logger.warning("twikit login failed, read will fall back to tweepy", exc_info=True)
                self._twikit = None

        # tweepy init
        if self._has_tweepy_creds and TweepyAsyncClient is not None:
            self._tweepy = TweepyAsyncClient(
                bearer_token=self._bearer_token or None,
                consumer_key=self._api_key,
                consumer_secret=self._api_secret,
                access_token=self._access_token,
                access_token_secret=self._access_secret,
                wait_on_rate_limit=True,
            )

    async def close(self) -> None:
        if self._twikit is not None:
            try:
                self._save_cookies(self._twikit)
            except Exception:
                logger.warning("twikit: failed to save cookies on close", exc_info=True)
        self._twikit = None
        self._tweepy = None

    def _save_cookies(self, client: Any) -> None:
        self._cookie_path.parent.mkdir(parents=True, exist_ok=True)
        client.save_cookies(str(self._cookie_path))

    @property
    def _has_twikit_creds(self) -> bool:
        return bool(self._tw_username and self._tw_password)

    @property
    def _has_tweepy_creds(self) -> bool:
        oauth1_ok = bool(
            self._api_key and self._api_secret and self._access_token and self._access_secret
        )
        return oauth1_ok or bool(self._bearer_token)

    # -- configuration --

    @classmethod
    def is_configured(cls) -> bool:
        twikit_ok = bool(os.getenv("TWITTER_USERNAME") and os.getenv("TWITTER_PASSWORD"))
        tweepy_ok = bool(
            os.getenv("TWITTER_API_KEY")
            and os.getenv("TWITTER_API_SECRET")
            and os.getenv("TWITTER_ACCESS_TOKEN")
            and os.getenv("TWITTER_ACCESS_SECRET")
        )
        bearer_ok = bool(os.getenv("TWITTER_BEARER_TOKEN"))
        return twikit_ok or tweepy_ok or bearer_ok

    @classmethod
    def setup_guide(cls) -> dict[str, Any]:
        return {
            "url": "https://developer.x.com/en/portal/dashboard",
            "steps": [
                "1. https://developer.x.com/en/portal/dashboard 접속",
                "2. 프로젝트/앱 생성 (Free tier 가능)",
                "3. 'Keys and Tokens' 탭에서 API Key, API Secret 복사",
                "4. 'Authentication Tokens'에서 Access Token, Access Secret 생성 후 복사",
            ],
            "required_keys": [
                "TWITTER_API_KEY",
                "TWITTER_API_SECRET",
                "TWITTER_ACCESS_TOKEN",
                "TWITTER_ACCESS_SECRET",
            ],
            "allowed_actions": ["comment", "post"],
        }

    # -- read (twikit first, tweepy fallback) --

    async def get_trending(self, *, limit: int = 20) -> list[Post]:
        if self._twikit is not None:
            return await self._twikit_get_trending(limit=limit)
        if self._tweepy is not None:
            return await self._tweepy_get_trending(limit=limit)
        raise RuntimeError("Twitter adapter not connected — no read backend available.")

    async def search(self, query: str, *, limit: int = 20) -> list[Post]:
        if self._twikit is not None:
            return await self._twikit_search(query, limit=limit)
        if self._tweepy is not None:
            return await self._tweepy_search(query, limit=limit)
        raise RuntimeError("Twitter adapter not connected — no read backend available.")

    async def get_post(self, post_id: str) -> Post:
        if self._twikit is not None:
            return await self._twikit_get_post(post_id)
        if self._tweepy is not None:
            return await self._tweepy_get_post(post_id)
        raise RuntimeError("Twitter adapter not connected — no read backend available.")

    async def get_comments(self, post_id: str, *, limit: int = 50) -> list[Comment]:
        if self._twikit is not None:
            return await self._twikit_get_comments(post_id, limit=limit)
        if self._tweepy is not None:
            return await self._tweepy_get_comments(post_id, limit=limit)
        raise RuntimeError("Twitter adapter not connected — no read backend available.")

    async def get_user(self, username: str) -> UserProfile:
        if self._twikit is not None:
            return await self._twikit_get_user(username)
        if self._tweepy is not None:
            return await self._tweepy_get_user(username)
        raise RuntimeError("Twitter adapter not connected — no read backend available.")

    # -- write (tweepy only) --

    async def write_post(
        self,
        title: str,
        body: str,
        *,
        tags: list[str] | None = None,
        **kwargs: object,
    ) -> PostResult:
        if self._tweepy is None:
            return PostResult(
                success=False,
                platform=self.platform,
                error="Twitter write requires tweepy (official API). "
                "Set TWITTER_API_KEY/SECRET/ACCESS_TOKEN/SECRET.",
            )
        text = f"{title}\n\n{body}" if title else body
        hashtags = " ".join(f"#{t}" for t in (tags or []))
        if hashtags:
            text = f"{text}\n\n{hashtags}"
        try:
            resp = await self._tweepy.create_tweet(text=text[:280])
            tweet = resp.data
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=str(tweet["id"]) if tweet else "",
                url=f"https://x.com/i/status/{tweet['id']}" if tweet else "",
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    async def write_comment(self, post_id: str, body: str) -> PostResult:
        if self._tweepy is None:
            return PostResult(
                success=False,
                platform=self.platform,
                error="Twitter write requires tweepy (official API).",
            )
        try:
            resp = await self._tweepy.create_tweet(
                text=body[:280],
                in_reply_to_tweet_id=post_id,
            )
            tweet = resp.data
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=str(tweet["id"]) if tweet else "",
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    async def upvote(self, post_id: str) -> PostResult:
        if self._tweepy is None:
            return PostResult(
                success=False,
                platform=self.platform,
                error="Twitter write requires tweepy (official API).",
            )
        try:
            resp = await self._tweepy.like(tweet_id=post_id)
            liked = resp.data.get("liked", False) if resp.data else False
            return PostResult(success=liked, platform=self.platform, post_id=post_id)
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    # ── twikit read implementations ──────────────────────────────

    async def _twikit_get_trending(self, *, limit: int = 20) -> list[Post]:
        assert self._twikit is not None
        result = await self._twikit.search_tweet("lang:en -filter:retweets", "Top", count=limit)
        return [self._twikit_tweet_to_post(t) for t in result]

    async def _twikit_search(self, query: str, *, limit: int = 20) -> list[Post]:
        assert self._twikit is not None
        result = await self._twikit.search_tweet(
            f"{query} -filter:retweets", "Top", count=limit
        )
        return [self._twikit_tweet_to_post(t) for t in result]

    async def _twikit_get_post(self, post_id: str) -> Post:
        assert self._twikit is not None
        tweet = await self._twikit.get_tweet_by_id(post_id)
        if tweet is None:
            raise ValueError(f"Tweet not found: {post_id}")
        return self._twikit_tweet_to_post(tweet)

    async def _twikit_get_comments(self, post_id: str, *, limit: int = 50) -> list[Comment]:
        assert self._twikit is not None
        result = await self._twikit.search_tweet(
            f"conversation_id:{post_id}", "Top", count=limit
        )
        return [
            Comment(
                id=str(t.id),
                platform=self.platform,
                body=t.text or "",
                author=t.user.screen_name if t.user else "",
                post_id=post_id,
                created_at=_parse_twikit_datetime(t.created_at),
                raw={"id": t.id, "text": t.text},
            )
            for t in result
        ]

    async def _twikit_get_user(self, username: str) -> UserProfile:
        assert self._twikit is not None
        user = await self._twikit.get_user_by_screen_name(username)
        if user is None:
            raise ValueError(f"User not found: {username}")
        return UserProfile(
            id=str(user.id),
            platform=self.platform,
            username=user.screen_name or "",
            name=user.name or "",
            bio=user.description or "",
            url=f"https://x.com/{user.screen_name}",
            followers=user.followers_count or 0,
            raw={"id": user.id, "screen_name": user.screen_name},
        )

    def _twikit_tweet_to_post(self, tweet: Any) -> Post:
        return Post(
            id=str(tweet.id),
            platform=self.platform,
            title="",
            url=f"https://x.com/i/status/{tweet.id}",
            body=tweet.text or "",
            author=tweet.user.screen_name if tweet.user else "",
            likes=tweet.favorite_count or 0,
            comments_count=tweet.reply_count or 0,
            published_at=_parse_twikit_datetime(tweet.created_at),
            raw={"id": tweet.id, "text": tweet.text},
        )

    # ── tweepy read implementations (fallback) ───────────────────

    async def _tweepy_get_trending(self, *, limit: int = 20) -> list[Post]:
        assert self._tweepy is not None
        resp = await self._tweepy.search_recent_tweets(
            query="lang:en -is:retweet",
            max_results=min(max(limit, 10), 100),
            tweet_fields=_TWEET_FIELDS,
            expansions=["author_id"],
            user_fields=_USER_FIELDS,
        )
        return self._tweepy_response_to_posts(resp)

    async def _tweepy_search(self, query: str, *, limit: int = 20) -> list[Post]:
        assert self._tweepy is not None
        resp = await self._tweepy.search_recent_tweets(
            query=f"{query} -is:retweet",
            max_results=min(max(limit, 10), 100),
            tweet_fields=_TWEET_FIELDS,
            expansions=["author_id"],
            user_fields=_USER_FIELDS,
        )
        return self._tweepy_response_to_posts(resp)

    async def _tweepy_get_post(self, post_id: str) -> Post:
        assert self._tweepy is not None
        resp = await self._tweepy.get_tweet(
            id=post_id,
            tweet_fields=_TWEET_FIELDS,
            expansions=["author_id"],
            user_fields=_USER_FIELDS,
        )
        if not resp.data:
            raise ValueError(f"Tweet not found: {post_id}")
        users = {u.id: u for u in (resp.includes or {}).get("users", [])}
        return self._tweepy_tweet_to_post(resp.data, users)

    async def _tweepy_get_comments(self, post_id: str, *, limit: int = 50) -> list[Comment]:
        assert self._tweepy is not None
        resp = await self._tweepy.search_recent_tweets(
            query=f"conversation_id:{post_id}",
            max_results=min(max(limit, 10), 100),
            tweet_fields=_TWEET_FIELDS,
            expansions=["author_id"],
            user_fields=_USER_FIELDS,
        )
        if not resp.data:
            return []
        users = {u.id: u for u in (resp.includes or {}).get("users", [])}
        return [
            Comment(
                id=str(t.id),
                platform=self.platform,
                body=t.text,
                author=users[t.author_id].username if t.author_id and t.author_id in users else "",
                post_id=post_id,
                created_at=t.created_at,
                raw={"id": t.id, "text": t.text},
            )
            for t in resp.data
        ]

    async def _tweepy_get_user(self, username: str) -> UserProfile:
        assert self._tweepy is not None
        resp = await self._tweepy.get_user(username=username, user_fields=_USER_FIELDS)
        if not resp.data:
            raise ValueError(f"User not found: {username}")
        u = resp.data
        metrics = u.public_metrics or {}
        return UserProfile(
            id=str(u.id),
            platform=self.platform,
            username=u.username,
            name=u.name or "",
            bio=u.description or "",
            url=f"https://x.com/{u.username}",
            followers=metrics.get("followers_count", 0),
            raw={"id": u.id, "username": u.username},
        )

    # ── tweepy helpers ───────────────────────────────────────────

    def _tweepy_response_to_posts(self, resp: Any) -> list[Post]:
        if not resp.data:
            return []
        users = {u.id: u for u in (resp.includes or {}).get("users", [])}
        return [self._tweepy_tweet_to_post(t, users) for t in resp.data]

    def _tweepy_tweet_to_post(self, tweet: Any, users: dict[Any, Any]) -> Post:
        metrics = tweet.public_metrics or {}
        author = ""
        if tweet.author_id and tweet.author_id in users:
            author = users[tweet.author_id].username
        return Post(
            id=str(tweet.id),
            platform=self.platform,
            title="",
            url=f"https://x.com/i/status/{tweet.id}",
            body=tweet.text,
            author=author,
            likes=metrics.get("like_count", 0),
            comments_count=metrics.get("reply_count", 0),
            published_at=tweet.created_at if isinstance(tweet.created_at, datetime) else None,
            raw={"id": tweet.id, "text": tweet.text},
        )


def _parse_twikit_datetime(dt_str: str | None) -> datetime | None:
    """Parse twikit's datetime string format."""
    if not dt_str:
        return None
    try:
        # twikit uses Twitter's format: "Mon Jan 01 00:00:00 +0000 2024"
        return datetime.strptime(dt_str, "%a %b %d %H:%M:%S %z %Y")
    except (ValueError, TypeError):
        return None
