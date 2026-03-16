"""Mastodon platform adapter — httpx async client, no extra SDK."""

from __future__ import annotations

import html
import os
import re
from datetime import datetime
from typing import Any

import httpx

from devhub.base import PlatformAdapter
from devhub.types import Comment, Post, PostResult, UserProfile


def _strip_html(text: str) -> str:
    """Strip HTML tags and decode entities to plain text."""
    # Replace <br> and </p> with newlines before stripping
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</p>\s*<p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO 8601 datetime string from Mastodon API."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


class Mastodon(PlatformAdapter):
    """Async adapter for Mastodon-compatible instances via REST API."""

    platform = "mastodon"

    def __init__(
        self,
        access_token: str | None = None,
        instance_url: str | None = None,
        username: str | None = None,
    ) -> None:
        self.access_token = access_token or os.getenv("MASTODON_ACCESS_TOKEN", "")
        self.instance_url = (
            instance_url or os.getenv("MASTODON_INSTANCE_URL", "https://mastodon.social")
        ).rstrip("/")
        self.username = username or os.getenv("MASTODON_USERNAME", "")
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle --

    async def connect(self) -> None:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        self._client = httpx.AsyncClient(
            base_url=self.instance_url,
            headers=headers,
            timeout=30.0,
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Mastodon adapter not connected.")
        return self._client

    # -- configuration --

    @classmethod
    def is_configured(cls) -> bool:
        return bool(
            os.getenv("MASTODON_ACCESS_TOKEN") and os.getenv("MASTODON_INSTANCE_URL")
        )

    @classmethod
    def setup_guide(cls) -> dict[str, Any]:
        return {
            "url": "https://mastodon.social/settings/applications",
            "steps": [
                "1. Mastodon 인스턴스 (예: mastodon.social) 계정 로그인",
                "2. 설정 → 개발 → 새 애플리케이션 생성",
                "3. 앱 이름 입력 (예: gwanjong)",
                "4. 권한 설정: read, write (최소 read:statuses, write:statuses, write:favourites)",
                "5. 저장 후 '액세스 토큰' 복사",
                "6. MASTODON_ACCESS_TOKEN, MASTODON_INSTANCE_URL, MASTODON_USERNAME 환경변수 설정",
            ],
            "required_keys": [
                "MASTODON_ACCESS_TOKEN",
                "MASTODON_INSTANCE_URL",
                "MASTODON_USERNAME",
            ],
            "allowed_actions": ["comment", "post", "upvote"],
        }

    # -- read --

    async def get_trending(self, *, limit: int = 20) -> list[Post]:
        """Fetch trending statuses from the instance."""
        resp = await self.client.get(
            "/api/v1/trends/statuses", params={"limit": min(limit, 40)}
        )
        resp.raise_for_status()
        return [self._status_to_post(s) for s in resp.json()]

    async def search(self, query: str, *, limit: int = 20) -> list[Post]:
        """Search statuses via Mastodon v2 search API."""
        resp = await self.client.get(
            "/api/v2/search",
            params={"q": query, "type": "statuses", "limit": min(limit, 40)},
        )
        resp.raise_for_status()
        data = resp.json()
        return [self._status_to_post(s) for s in data.get("statuses", [])]

    async def get_post(self, post_id: str) -> Post:
        """Get a single status by ID."""
        resp = await self.client.get(f"/api/v1/statuses/{post_id}")
        resp.raise_for_status()
        return self._status_to_post(resp.json())

    async def get_comments(self, post_id: str, *, limit: int = 50) -> list[Comment]:
        """Get descendants (replies) of a status."""
        resp = await self.client.get(f"/api/v1/statuses/{post_id}/context")
        resp.raise_for_status()
        data = resp.json()
        descendants = data.get("descendants", [])
        return [self._status_to_comment(s, post_id) for s in descendants[:limit]]

    async def get_user(self, username: str) -> UserProfile:
        """Lookup a user by acct (username or user@domain)."""
        resp = await self.client.get(
            "/api/v1/accounts/lookup", params={"acct": username}
        )
        resp.raise_for_status()
        acct = resp.json()
        return UserProfile(
            id=str(acct["id"]),
            platform=self.platform,
            username=acct.get("acct", acct.get("username", "")),
            name=acct.get("display_name", ""),
            bio=_strip_html(acct.get("note", "")),
            url=acct.get("url", ""),
            followers=acct.get("followers_count", 0),
            raw=acct,
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
        """Publish a new status. Title is prepended if provided."""
        text = f"{title}\n\n{body}" if title else body
        if tags:
            hashtags = " ".join(f"#{t.lstrip('#')}" for t in tags)
            text = f"{text}\n\n{hashtags}"
        text = text[:500]
        try:
            resp = await self.client.post(
                "/api/v1/statuses", json={"status": text}
            )
            resp.raise_for_status()
            status = resp.json()
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=str(status["id"]),
                url=status.get("url", ""),
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    async def write_comment(self, post_id: str, body: str) -> PostResult:
        """Reply to an existing status."""
        try:
            resp = await self.client.post(
                "/api/v1/statuses",
                json={"status": body[:500], "in_reply_to_id": post_id},
            )
            resp.raise_for_status()
            status = resp.json()
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=str(status["id"]),
                url=status.get("url", ""),
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    async def upvote(self, post_id: str) -> PostResult:
        """Favourite (like) a status."""
        try:
            resp = await self.client.post(
                f"/api/v1/statuses/{post_id}/favourite"
            )
            resp.raise_for_status()
            status = resp.json()
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=str(status["id"]),
                url=status.get("url", ""),
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    # -- helpers --

    def _status_to_post(self, status: dict[str, Any]) -> Post:
        """Convert a Mastodon status JSON to a unified Post."""
        content = _strip_html(status.get("content", ""))
        account = status.get("account", {})
        tags = [t.get("name", "") for t in status.get("tags", [])]

        return Post(
            id=str(status["id"]),
            platform=self.platform,
            title="",
            url=status.get("url", ""),
            body=content,
            author=account.get("acct", account.get("username", "")),
            tags=tags,
            likes=status.get("favourites_count", 0),
            comments_count=status.get("replies_count", 0),
            published_at=_parse_datetime(status.get("created_at")),
            raw=status,
        )

    def _status_to_comment(self, status: dict[str, Any], post_id: str) -> Comment:
        """Convert a Mastodon status JSON to a unified Comment."""
        content = _strip_html(status.get("content", ""))
        account = status.get("account", {})

        return Comment(
            id=str(status["id"]),
            platform=self.platform,
            body=content,
            author=account.get("acct", account.get("username", "")),
            post_id=post_id,
            parent_id=status.get("in_reply_to_id"),
            likes=status.get("favourites_count", 0),
            created_at=_parse_datetime(status.get("created_at")),
            raw=status,
        )
