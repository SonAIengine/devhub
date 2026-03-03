"""Reddit platform adapter — asyncpraw."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from devhub.base import PlatformAdapter
from devhub.types import Comment, Post, PostResult, UserProfile

try:
    import asyncpraw
except ImportError:  # pragma: no cover
    asyncpraw = None  # noqa: N816


class Reddit(PlatformAdapter):
    """Async adapter for Reddit via asyncpraw."""

    platform = "reddit"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        username: str | None = None,
        password: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.client_id = client_id or os.getenv("REDDIT_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("REDDIT_CLIENT_SECRET", "")
        self.username = username or os.getenv("REDDIT_USERNAME", "")
        self.password = password or os.getenv("REDDIT_PASSWORD", "")
        self.user_agent = user_agent or os.getenv("REDDIT_USER_AGENT", "devhub/0.1.0")
        self._reddit: Any = None

    # -- lifecycle --

    async def connect(self) -> None:
        if asyncpraw is None:
            raise ImportError("Install asyncpraw: pip install 'devhub[reddit]'")
        self._reddit = asyncpraw.Reddit(
            client_id=self.client_id,
            client_secret=self.client_secret,
            username=self.username,
            password=self.password,
            user_agent=self.user_agent,
        )

    async def close(self) -> None:
        if self._reddit:
            await self._reddit.close()
            self._reddit = None

    @property
    def reddit(self) -> Any:
        if self._reddit is None:
            raise RuntimeError("Reddit adapter not connected.")
        return self._reddit

    # -- configuration --

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET"))

    # -- read --

    async def get_trending(self, *, limit: int = 20) -> list[Post]:
        subreddit = await self.reddit.subreddit("all")
        posts: list[Post] = []
        async for submission in subreddit.hot(limit=limit):
            posts.append(self._submission_to_post(submission))
        return posts

    async def search(self, query: str, *, limit: int = 20) -> list[Post]:
        subreddit = await self.reddit.subreddit("all")
        posts: list[Post] = []
        async for submission in subreddit.search(query, sort="relevance", limit=limit):
            posts.append(self._submission_to_post(submission))
        return posts

    async def get_post(self, post_id: str) -> Post:
        submission = await self.reddit.submission(post_id, fetch=True)
        return self._submission_to_post(submission)

    async def get_comments(self, post_id: str, *, limit: int = 50) -> list[Comment]:
        submission = await self.reddit.submission(post_id, fetch=False)
        submission.comment_sort = "top"
        await submission.load()
        await submission.comments.replace_more(limit=0)
        comments: list[Comment] = []
        for c in submission.comments.list()[:limit]:
            comments.append(
                Comment(
                    id=c.id,
                    platform=self.platform,
                    body=c.body,
                    author=c.author.name if c.author else "[deleted]",
                    post_id=post_id,
                    parent_id=getattr(c, "parent_id", None),
                    likes=c.score,
                    created_at=datetime.fromtimestamp(c.created_utc, tz=timezone.utc),
                    raw={"id": c.id, "body": c.body},
                )
            )
        return comments

    async def get_user(self, username: str) -> UserProfile:
        redditor = await self.reddit.redditor(username, fetch=True)
        return UserProfile(
            id=redditor.id,
            platform=self.platform,
            username=redditor.name,
            name=redditor.name,
            bio="",
            url=f"https://www.reddit.com/user/{redditor.name}",
            followers=redditor.link_karma + redditor.comment_karma,
            raw={"id": redditor.id, "name": redditor.name},
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
        try:
            subreddit_name = str(kwargs.get("subreddit", "test"))
            sub = await self.reddit.subreddit(subreddit_name)
            submission = await sub.submit(title=title, selftext=body)
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=submission.id,
                url=f"https://www.reddit.com{submission.permalink}",
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    async def write_comment(self, post_id: str, body: str) -> PostResult:
        try:
            submission = await self.reddit.submission(post_id, fetch=True)
            comment = await submission.reply(body)
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=comment.id,
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    async def upvote(self, post_id: str) -> PostResult:
        try:
            submission = await self.reddit.submission(post_id, fetch=True)
            await submission.upvote()
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=post_id,
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    # -- helpers --

    def _submission_to_post(self, s: Any) -> Post:
        return Post(
            id=s.id,
            platform=self.platform,
            title=s.title,
            url=f"https://www.reddit.com{s.permalink}",
            body=s.selftext if s.is_self else "",
            author=s.author.name if s.author else "[deleted]",
            tags=[],
            likes=s.score,
            comments_count=s.num_comments,
            published_at=datetime.fromtimestamp(s.created_utc, tz=timezone.utc),
            raw={"id": s.id, "title": s.title, "permalink": s.permalink},
        )
