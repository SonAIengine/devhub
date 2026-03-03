"""Dev.to (Forem) platform adapter — httpx only, no external SDK."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx

from devhub.base import PlatformAdapter
from devhub.types import Comment, Post, PostResult, UserProfile

_BASE = "https://dev.to/api"


class DevTo(PlatformAdapter):
    """Async adapter for the Dev.to / Forem v1 API."""

    platform = "devto"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("DEVTO_API_KEY", "")
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle --

    async def connect(self) -> None:
        headers: dict[str, str] = {"Accept": "application/vnd.forem.api-v1+json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        self._client = httpx.AsyncClient(base_url=_BASE, headers=headers, timeout=30)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("DevTo adapter not connected. Use `async with DevTo() as d:`")
        return self._client

    # -- configuration --

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("DEVTO_API_KEY"))

    # -- read --

    async def get_trending(self, *, limit: int = 20) -> list[Post]:
        resp = await self.client.get("/articles", params={"top": 7, "per_page": limit})
        resp.raise_for_status()
        return [self._to_post(a) for a in resp.json()]

    async def search(self, query: str, *, limit: int = 20) -> list[Post]:
        resp = await self.client.get(
            "/articles", params={"tag": query, "per_page": limit}
        )
        resp.raise_for_status()
        return [self._to_post(a) for a in resp.json()]

    async def get_post(self, post_id: str) -> Post:
        resp = await self.client.get(f"/articles/{post_id}")
        resp.raise_for_status()
        return self._to_post(resp.json())

    async def get_comments(self, post_id: str, *, limit: int = 50) -> list[Comment]:
        resp = await self.client.get(
            "/comments", params={"a_id": post_id, "per_page": limit}
        )
        resp.raise_for_status()
        comments: list[Comment] = []
        self._flatten_comments(resp.json(), post_id, comments)
        return comments

    async def get_user(self, username: str) -> UserProfile:
        resp = await self.client.get("/users/by_username", params={"url": username})
        resp.raise_for_status()
        u = resp.json()
        return UserProfile(
            id=str(u["id"]),
            platform=self.platform,
            username=u.get("username", ""),
            name=u.get("name", ""),
            bio=u.get("summary", ""),
            url=f"https://dev.to/{u.get('username', '')}",
            raw=u,
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
        published = bool(kwargs.get("published", True))
        payload: dict[str, Any] = {
            "article": {
                "title": title,
                "body_markdown": body,
                "published": published,
                "tags": (tags or [])[:4],
            }
        }
        resp = await self.client.post("/articles", json=payload)
        if resp.status_code == 201:
            data = resp.json()
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=str(data["id"]),
                url=data.get("url", ""),
            )
        return PostResult(
            success=False,
            platform=self.platform,
            error=resp.text,
        )

    async def write_comment(self, post_id: str, body: str) -> PostResult:
        payload = {
            "comment": {
                "body_markdown": body,
                "commentable_id": int(post_id),
                "commentable_type": "Article",
            }
        }
        resp = await self.client.post("/comments", json=payload)
        if resp.status_code == 201:
            data = resp.json()
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=data.get("id_code", ""),
            )
        return PostResult(success=False, platform=self.platform, error=resp.text)

    async def upvote(self, post_id: str) -> PostResult:
        resp = await self.client.post(
            "/reactions",
            params={
                "category": "like",
                "reactable_id": int(post_id),
                "reactable_type": "Article",
            },
        )
        if resp.status_code == 200:
            data = resp.json()
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=str(data.get("reactable_id", post_id)),
            )
        return PostResult(success=False, platform=self.platform, error=resp.text)

    # -- helpers --

    def _to_post(self, data: dict[str, Any]) -> Post:
        tag_list = data.get("tags") or data.get("tag_list") or []
        if isinstance(tag_list, str):
            tag_list = [t.strip() for t in tag_list.split(",") if t.strip()]

        published_at = None
        if ts := data.get("published_at"):
            try:
                published_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return Post(
            id=str(data["id"]),
            platform=self.platform,
            title=data.get("title", ""),
            url=data.get("url", ""),
            body=data.get("body_markdown") or data.get("description", ""),
            author=data.get("user", {}).get("username", ""),
            tags=tag_list,
            likes=data.get("public_reactions_count", 0),
            comments_count=data.get("comments_count", 0),
            published_at=published_at,
            raw=data,
        )

    def _flatten_comments(
        self,
        nodes: list[dict[str, Any]],
        post_id: str,
        out: list[Comment],
        parent_id: str | None = None,
    ) -> None:
        for node in nodes:
            created_at = None
            if ts := node.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass

            out.append(
                Comment(
                    id=node.get("id_code", ""),
                    platform=self.platform,
                    body=node.get("body_html", ""),
                    author=node.get("user", {}).get("username", ""),
                    post_id=post_id,
                    parent_id=parent_id,
                    created_at=created_at,
                    raw=node,
                )
            )
            if children := node.get("children"):
                self._flatten_comments(children, post_id, out, node.get("id_code"))
