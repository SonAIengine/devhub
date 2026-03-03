"""Bluesky (AT Protocol) platform adapter — atproto SDK."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from devhub.base import PlatformAdapter
from devhub.types import Comment, Post, PostResult, UserProfile

try:
    from atproto import AsyncClient, models
except ImportError:  # pragma: no cover
    AsyncClient = None  # noqa: N816
    models = None  # noqa: N816


class Bluesky(PlatformAdapter):
    """Async adapter for the Bluesky social network via AT Protocol."""

    platform = "bluesky"

    def __init__(
        self,
        handle: str | None = None,
        app_password: str | None = None,
    ) -> None:
        self.handle = handle or os.getenv("BLUESKY_HANDLE", "")
        self.app_password = app_password or os.getenv("BLUESKY_APP_PASSWORD", "")
        self._client: Any = None

    # -- lifecycle --

    async def connect(self) -> None:
        if AsyncClient is None:
            raise ImportError("Install atproto: pip install 'devhub[bluesky]'")
        self._client = AsyncClient()
        if self.handle and self.app_password:
            await self._client.login(self.handle, self.app_password)

    async def close(self) -> None:
        self._client = None

    @property
    def client(self) -> Any:
        if self._client is None:
            raise RuntimeError("Bluesky adapter not connected.")
        return self._client

    # -- configuration --

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("BLUESKY_HANDLE") and os.getenv("BLUESKY_APP_PASSWORD"))

    # -- read --

    async def get_trending(self, *, limit: int = 20) -> list[Post]:
        resp = await self.client.app.bsky.feed.search_posts(
            params=models.AppBskyFeedSearchPosts.Params(
                q="*",
                limit=min(limit, 100),
                sort="top",
            )
        )
        return [self._post_view_to_post(p) for p in resp.posts]

    async def search(self, query: str, *, limit: int = 20) -> list[Post]:
        resp = await self.client.app.bsky.feed.search_posts(
            params=models.AppBskyFeedSearchPosts.Params(
                q=query,
                limit=min(limit, 100),
                sort="top",
            )
        )
        return [self._post_view_to_post(p) for p in resp.posts]

    async def get_post(self, post_id: str) -> Post:
        resp = await self.client.app.bsky.feed.get_posts(
            params=models.AppBskyFeedGetPosts.Params(uris=[post_id])
        )
        if not resp.posts:
            raise ValueError(f"Post not found: {post_id}")
        return self._post_view_to_post(resp.posts[0])

    async def get_comments(self, post_id: str, *, limit: int = 50) -> list[Comment]:
        resp = await self.client.get_post_thread(uri=post_id, depth=6)
        comments: list[Comment] = []
        thread = resp.thread
        if hasattr(thread, "replies") and thread.replies:
            self._flatten_thread(thread.replies, post_id, comments)
        return comments[:limit]

    async def get_user(self, username: str) -> UserProfile:
        profile = await self.client.get_profile(actor=username)
        return UserProfile(
            id=profile.did,
            platform=self.platform,
            username=profile.handle,
            name=profile.display_name or "",
            bio=profile.description or "",
            url=f"https://bsky.app/profile/{profile.handle}",
            followers=profile.followers_count or 0,
            raw={"did": profile.did, "handle": profile.handle},
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
        try:
            result = await self.client.send_post(text=text[:300])
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=result.uri,
                url=self._uri_to_url(result.uri),
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    async def write_comment(self, post_id: str, body: str) -> PostResult:
        try:
            posts_resp = await self.client.app.bsky.feed.get_posts(
                params=models.AppBskyFeedGetPosts.Params(uris=[post_id])
            )
            if not posts_resp.posts:
                return PostResult(
                    success=False, platform=self.platform, error="Parent post not found"
                )
            parent = posts_resp.posts[0]
            reply_ref = models.AppBskyFeedPost.ReplyRef(
                parent=models.ComAtprotoRepoStrongRef.Main(uri=parent.uri, cid=parent.cid),
                root=models.ComAtprotoRepoStrongRef.Main(uri=parent.uri, cid=parent.cid),
            )
            result = await self.client.send_post(text=body[:300], reply_to=reply_ref)
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=result.uri,
                url=self._uri_to_url(result.uri),
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    async def upvote(self, post_id: str) -> PostResult:
        try:
            posts_resp = await self.client.app.bsky.feed.get_posts(
                params=models.AppBskyFeedGetPosts.Params(uris=[post_id])
            )
            if not posts_resp.posts:
                return PostResult(
                    success=False, platform=self.platform, error="Post not found"
                )
            post = posts_resp.posts[0]
            result = await self.client.like(uri=post.uri, cid=post.cid)
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=result.uri,
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    # -- helpers --

    def _post_view_to_post(self, pv: Any) -> Post:
        record = pv.record
        text = record.text if hasattr(record, "text") else str(record)
        created = None
        if hasattr(record, "created_at") and record.created_at:
            try:
                created = datetime.fromisoformat(record.created_at.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return Post(
            id=pv.uri,
            platform=self.platform,
            title="",
            url=self._uri_to_url(pv.uri),
            body=text,
            author=pv.author.handle if pv.author else "",
            likes=pv.like_count or 0,
            comments_count=pv.reply_count or 0,
            published_at=created,
            raw={"uri": pv.uri, "cid": pv.cid},
        )

    def _flatten_thread(
        self,
        replies: list[Any],
        post_id: str,
        out: list[Comment],
        parent_id: str | None = None,
    ) -> None:
        for reply in replies:
            if not hasattr(reply, "post"):
                continue
            record = reply.post.record
            text = record.text if hasattr(record, "text") else str(record)
            out.append(
                Comment(
                    id=reply.post.uri,
                    platform=self.platform,
                    body=text,
                    author=reply.post.author.handle if reply.post.author else "",
                    post_id=post_id,
                    parent_id=parent_id,
                    raw={"uri": reply.post.uri, "cid": reply.post.cid},
                )
            )
            if hasattr(reply, "replies") and reply.replies:
                self._flatten_thread(reply.replies, post_id, out, reply.post.uri)

    @staticmethod
    def _uri_to_url(uri: str) -> str:
        # at://did:plc:xxx/app.bsky.feed.post/rkey → bsky.app URL
        parts = uri.replace("at://", "").split("/")
        if len(parts) >= 3:
            did, _, rkey = parts[0], parts[1], parts[2]
            return f"https://bsky.app/profile/{did}/post/{rkey}"
        return ""
