"""Hacker News platform adapter — Firebase API (read) + web scraping (write)."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from devhub.base import PlatformAdapter
from devhub.types import Comment, Post, PostResult, UserProfile

logger = logging.getLogger(__name__)

HN_FIREBASE = "https://hacker-news.firebaseio.com/v0"
HN_ALGOLIA = "https://hn.algolia.com/api/v1"
HN_WEB = "https://news.ycombinator.com"


def _strip_html(text: str) -> str:
    """Strip HN HTML tags (<p>, <a>, <i>, <code>, etc.) to plain text."""
    if not text:
        return ""
    # <p> → newline
    text = re.sub(r"<p>", "\n\n", text)
    # <a href="...">text</a> → text (url)
    text = re.sub(r'<a\s+href="([^"]*)"[^>]*>([^<]*)</a>', r"\2 (\1)", text)
    # strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _ts_to_dt(ts: int | None) -> datetime | None:
    """Unix timestamp → datetime (UTC)."""
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


class HackerNews(PlatformAdapter):
    """Async adapter for Hacker News via Firebase/Algolia APIs + web auth."""

    platform = "hackernews"

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.username = username or os.getenv("HN_USERNAME", "")
        self.password = password or os.getenv("HN_PASSWORD", "")
        self._http: httpx.AsyncClient | None = None
        self._auth_cookie: str | None = None

    # -- lifecycle --

    async def connect(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
        self._auth_cookie = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("HackerNews adapter not connected.")
        return self._http

    # -- configuration --

    @classmethod
    def is_configured(cls) -> bool:
        # Read operations always work; consider configured if username is set (write ready)
        return bool(os.getenv("HN_USERNAME"))

    @classmethod
    def setup_guide(cls) -> dict[str, Any]:
        return {
            "url": "https://news.ycombinator.com/newsguidelines.html",
            "steps": [
                "1. https://news.ycombinator.com/login 접속",
                "2. 'Create Account' 클릭하여 계정 생성",
                "3. 사용자명과 비밀번호를 환경변수에 설정",
                "4. 참고: 댓글 작성에는 최소 카르마가 필요할 수 있음",
            ],
            "required_keys": ["HN_USERNAME", "HN_PASSWORD"],
            "allowed_actions": ["comment", "post", "upvote"],
        }

    # -- auth (lazy login) --

    async def _ensure_auth(self) -> None:
        """Login to HN web and cache the auth cookie. Raises on failure."""
        if self._auth_cookie:
            return
        if not self.username or not self.password:
            raise RuntimeError("HN_USERNAME and HN_PASSWORD required for write operations")

        resp = await self.http.post(
            f"{HN_WEB}/login",
            data={"acct": self.username, "pw": self.password},
            follow_redirects=False,
        )
        cookie = resp.cookies.get("user")
        if not cookie:
            # Some HN responses redirect with Set-Cookie
            for header_val in resp.headers.get_list("set-cookie"):
                if header_val.startswith("user="):
                    cookie = header_val.split(";")[0].split("=", 1)[1]
                    break
        if not cookie:
            raise RuntimeError("HN login failed — check HN_USERNAME/HN_PASSWORD")
        self._auth_cookie = cookie
        logger.debug("HN login successful for %s", self.username)

    def _auth_cookies(self) -> dict[str, str]:
        """Return cookies dict for authenticated requests."""
        if not self._auth_cookie:
            raise RuntimeError("Not authenticated")
        return {"user": self._auth_cookie}

    # -- read --

    async def get_trending(self, *, limit: int = 20) -> list[Post]:
        resp = await self.http.get(f"{HN_FIREBASE}/topstories.json")
        resp.raise_for_status()
        story_ids: list[int] = resp.json()[:limit]

        # batch fetch items concurrently
        tasks = [self._fetch_item(sid) for sid in story_ids]
        items = await asyncio.gather(*tasks, return_exceptions=True)

        posts = []
        for item in items:
            if isinstance(item, dict) and item.get("type") == "story":
                posts.append(self._item_to_post(item))
        return posts

    async def search(self, query: str, *, limit: int = 20) -> list[Post]:
        resp = await self.http.get(
            f"{HN_ALGOLIA}/search",
            params={"query": query, "tags": "story", "hitsPerPage": limit},
        )
        resp.raise_for_status()
        data = resp.json()

        posts = []
        for hit in data.get("hits", []):
            posts.append(self._algolia_hit_to_post(hit))
        return posts

    async def get_post(self, post_id: str) -> Post:
        item = await self._fetch_item(int(post_id))
        if not item:
            raise ValueError(f"Post not found: {post_id}")
        return self._item_to_post(item)

    async def get_comments(self, post_id: str, *, limit: int = 50) -> list[Comment]:
        # Use Algolia items endpoint which returns the full comment tree
        resp = await self.http.get(f"{HN_ALGOLIA}/items/{post_id}")
        resp.raise_for_status()
        data = resp.json()

        comments: list[Comment] = []
        self._flatten_children(data.get("children", []), post_id, comments)
        return comments[:limit]

    async def get_user(self, username: str) -> UserProfile:
        resp = await self.http.get(f"{HN_FIREBASE}/user/{username}.json")
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise ValueError(f"User not found: {username}")

        return UserProfile(
            id=data.get("id", username),
            platform=self.platform,
            username=data.get("id", username),
            name=data.get("id", ""),
            bio=_strip_html(data.get("about", "")),
            url=f"{HN_WEB}/user?id={username}",
            followers=0,  # HN doesn't expose follower counts
            raw=data,
        )

    # -- write --

    async def write_post(
        self,
        title: str,
        body: str,
        *,
        tags: list[str] | None = None,
        url: str = "",
        **kwargs: object,
    ) -> PostResult:
        await self._ensure_auth()
        try:
            data: dict[str, str] = {"title": title}
            if url:
                data["url"] = url
            else:
                data["text"] = body

            resp = await self.http.post(
                f"{HN_WEB}/r",
                data=data,
                cookies=self._auth_cookies(),
                follow_redirects=False,
            )
            # Successful submission redirects to the new item
            if resp.status_code in (301, 302):
                location = resp.headers.get("location", "")
                # extract item id from redirect URL like "item?id=12345"
                match = re.search(r"id=(\d+)", location)
                item_id = match.group(1) if match else ""
                return PostResult(
                    success=True,
                    platform=self.platform,
                    post_id=item_id,
                    url=f"{HN_WEB}/item?id={item_id}" if item_id else "",
                )
            # If redirected to /newest, submission likely succeeded
            if resp.status_code == 200 or "newest" in resp.headers.get("location", ""):
                return PostResult(
                    success=True,
                    platform=self.platform,
                    url="",
                )
            return PostResult(
                success=False,
                platform=self.platform,
                error=f"Unexpected response: {resp.status_code}",
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    async def write_comment(self, post_id: str, body: str) -> PostResult:
        await self._ensure_auth()
        try:
            # First, get the HMAC token from the item page
            hmac = await self._get_hmac(post_id)

            data: dict[str, str] = {
                "parent": post_id,
                "text": body,
            }
            if hmac:
                data["hmac"] = hmac

            resp = await self.http.post(
                f"{HN_WEB}/comment",
                data=data,
                cookies=self._auth_cookies(),
                follow_redirects=False,
            )
            if resp.status_code in (200, 301, 302):
                return PostResult(
                    success=True,
                    platform=self.platform,
                    post_id=post_id,
                    url=f"{HN_WEB}/item?id={post_id}",
                )
            return PostResult(
                success=False,
                platform=self.platform,
                error=f"Comment failed: {resp.status_code}",
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    async def upvote(self, post_id: str) -> PostResult:
        await self._ensure_auth()
        try:
            resp = await self.http.get(
                f"{HN_WEB}/vote",
                params={"id": post_id, "how": "up"},
                cookies=self._auth_cookies(),
                follow_redirects=True,
            )
            if resp.status_code == 200:
                return PostResult(
                    success=True,
                    platform=self.platform,
                    post_id=post_id,
                )
            return PostResult(
                success=False,
                platform=self.platform,
                error=f"Upvote failed: {resp.status_code}",
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    # -- helpers --

    async def _fetch_item(self, item_id: int) -> dict[str, Any]:
        """Fetch a single item from Firebase API."""
        resp = await self.http.get(f"{HN_FIREBASE}/item/{item_id}.json")
        resp.raise_for_status()
        return resp.json() or {}

    async def _get_hmac(self, item_id: str) -> str:
        """Fetch the HMAC token from an item page (needed for comment submission)."""
        try:
            resp = await self.http.get(
                f"{HN_WEB}/item?id={item_id}",
                cookies=self._auth_cookies(),
            )
            match = re.search(r'name="hmac"\s+value="([^"]+)"', resp.text)
            return match.group(1) if match else ""
        except Exception:
            logger.debug("Failed to fetch HMAC for item %s", item_id)
            return ""

    def _item_to_post(self, item: dict[str, Any]) -> Post:
        """Convert a Firebase HN item to a Post."""
        item_id = str(item.get("id", ""))
        title = item.get("title", "")
        # HN stories can have a url (link) or text (Ask HN, Show HN)
        body = _strip_html(item.get("text", ""))
        url = item.get("url", f"{HN_WEB}/item?id={item_id}")

        return Post(
            id=item_id,
            platform=self.platform,
            title=title,
            url=url,
            body=body,
            author=item.get("by", ""),
            tags=self._extract_tags(title),
            likes=item.get("score", 0),
            comments_count=item.get("descendants", 0),
            published_at=_ts_to_dt(item.get("time")),
            raw=item,
        )

    def _algolia_hit_to_post(self, hit: dict[str, Any]) -> Post:
        """Convert an Algolia search hit to a Post."""
        item_id = hit.get("objectID", "")
        title = hit.get("title", "")
        url = hit.get("url") or f"{HN_WEB}/item?id={item_id}"
        body = _strip_html(hit.get("story_text", "") or "")

        created = None
        if hit.get("created_at"):
            try:
                created = datetime.fromisoformat(hit["created_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return Post(
            id=item_id,
            platform=self.platform,
            title=title,
            url=url,
            body=body,
            author=hit.get("author", ""),
            tags=self._extract_tags(title),
            likes=hit.get("points", 0),
            comments_count=hit.get("num_comments", 0),
            published_at=created,
            raw=hit,
        )

    def _flatten_children(
        self,
        children: list[dict[str, Any]],
        post_id: str,
        out: list[Comment],
        parent_id: str | None = None,
    ) -> None:
        """Recursively flatten Algolia comment tree into a list."""
        for child in children:
            if child.get("type") not in ("comment",):
                continue
            child_id = str(child.get("id", ""))
            created = None
            if child.get("created_at"):
                try:
                    created = datetime.fromisoformat(
                        child["created_at"].replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError):
                    pass

            out.append(
                Comment(
                    id=child_id,
                    platform=self.platform,
                    body=_strip_html(child.get("text", "")),
                    author=child.get("author", ""),
                    post_id=post_id,
                    parent_id=parent_id,
                    likes=child.get("points") or 0,
                    created_at=created,
                    raw=child,
                )
            )
            # recurse into nested children
            if child.get("children"):
                self._flatten_children(child["children"], post_id, out, child_id)

    @staticmethod
    def _extract_tags(title: str) -> list[str]:
        """Extract common HN prefixes as tags (Show HN, Ask HN, etc.)."""
        tags: list[str] = []
        lower = title.lower()
        if lower.startswith("show hn"):
            tags.append("show-hn")
        elif lower.startswith("ask hn"):
            tags.append("ask-hn")
        elif lower.startswith("tell hn"):
            tags.append("tell-hn")
        elif lower.startswith("launch hn"):
            tags.append("launch-hn")
        return tags
