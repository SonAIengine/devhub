"""Twitter/X platform adapter — tweepy v4 AsyncClient."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from devhub.base import PlatformAdapter
from devhub.types import Comment, Post, PostResult, UserProfile

try:
    from tweepy.asynchronous import AsyncClient as TweepyAsyncClient
except ImportError:  # pragma: no cover
    TweepyAsyncClient = None  # noqa: N816

_TWEET_FIELDS = ["id", "text", "author_id", "created_at", "public_metrics"]
_USER_FIELDS = ["id", "name", "username", "description", "public_metrics", "profile_image_url"]


class Twitter(PlatformAdapter):
    """Async adapter for Twitter/X API v2 via tweepy."""

    platform = "twitter"

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        access_token: str | None = None,
        access_secret: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("TWITTER_API_KEY", "")
        self.api_secret = api_secret or os.getenv("TWITTER_API_SECRET", "")
        self.access_token = access_token or os.getenv("TWITTER_ACCESS_TOKEN", "")
        self.access_secret = access_secret or os.getenv("TWITTER_ACCESS_SECRET", "")
        self._client: Any = None

    # -- lifecycle --

    async def connect(self) -> None:
        if TweepyAsyncClient is None:
            raise ImportError("Install tweepy: pip install 'devhub[twitter]'")
        self._client = TweepyAsyncClient(
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_secret,
            wait_on_rate_limit=True,
        )

    async def close(self) -> None:
        self._client = None

    @property
    def client(self) -> Any:
        if self._client is None:
            raise RuntimeError("Twitter adapter not connected.")
        return self._client

    # -- configuration --

    @classmethod
    def is_configured(cls) -> bool:
        return bool(
            os.getenv("TWITTER_API_KEY")
            and os.getenv("TWITTER_API_SECRET")
            and os.getenv("TWITTER_ACCESS_TOKEN")
            and os.getenv("TWITTER_ACCESS_SECRET")
        )

    # -- read --

    async def get_trending(self, *, limit: int = 20) -> list[Post]:
        resp = await self.client.search_recent_tweets(
            query="lang:en -is:retweet",
            max_results=min(max(limit, 10), 100),
            tweet_fields=_TWEET_FIELDS,
            expansions=["author_id"],
            user_fields=_USER_FIELDS,
        )
        return self._response_to_posts(resp)

    async def search(self, query: str, *, limit: int = 20) -> list[Post]:
        resp = await self.client.search_recent_tweets(
            query=f"{query} -is:retweet",
            max_results=min(max(limit, 10), 100),
            tweet_fields=_TWEET_FIELDS,
            expansions=["author_id"],
            user_fields=_USER_FIELDS,
        )
        return self._response_to_posts(resp)

    async def get_post(self, post_id: str) -> Post:
        resp = await self.client.get_tweet(
            id=post_id,
            tweet_fields=_TWEET_FIELDS,
            expansions=["author_id"],
            user_fields=_USER_FIELDS,
        )
        if not resp.data:
            raise ValueError(f"Tweet not found: {post_id}")
        users = {u.id: u for u in (resp.includes or {}).get("users", [])}
        return self._tweet_to_post(resp.data, users)

    async def get_comments(self, post_id: str, *, limit: int = 50) -> list[Comment]:
        resp = await self.client.search_recent_tweets(
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

    async def get_user(self, username: str) -> UserProfile:
        resp = await self.client.get_user(username=username, user_fields=_USER_FIELDS)
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

    # -- write --

    async def write_post(
        self,
        title: str,
        body: str,
        *,
        tags: list[str] | None = None,
        **kwargs: object,
    ) -> PostResult:
        text = f"{title}\n\n{body}" if title else body
        hashtags = " ".join(f"#{t}" for t in (tags or []))
        if hashtags:
            text = f"{text}\n\n{hashtags}"
        try:
            resp = await self.client.create_tweet(text=text[:280])
            tweet = resp.data
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=str(tweet.id) if tweet else "",
                url=f"https://x.com/i/status/{tweet.id}" if tweet else "",
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    async def write_comment(self, post_id: str, body: str) -> PostResult:
        try:
            resp = await self.client.create_tweet(
                text=body[:280],
                in_reply_to_tweet_id=post_id,
            )
            tweet = resp.data
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=str(tweet.id) if tweet else "",
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    async def upvote(self, post_id: str) -> PostResult:
        try:
            resp = await self.client.like(tweet_id=post_id)
            liked = resp.data.get("liked", False) if resp.data else False
            return PostResult(
                success=liked,
                platform=self.platform,
                post_id=post_id,
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    # -- helpers --

    def _response_to_posts(self, resp: Any) -> list[Post]:
        if not resp.data:
            return []
        users = {u.id: u for u in (resp.includes or {}).get("users", [])}
        return [self._tweet_to_post(t, users) for t in resp.data]

    def _tweet_to_post(self, tweet: Any, users: dict[Any, Any]) -> Post:
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
