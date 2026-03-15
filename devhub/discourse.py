"""Discourse forum adapter via the official REST API."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from devhub.base import PlatformAdapter
from devhub.types import Comment, Post, PostResult, UserProfile


class Discourse(PlatformAdapter):
    """Async adapter for Discourse forums."""

    platform = "discourse"

    def __init__(
        self,
        base_url: str | None = None,
        base_urls: list[str] | None = None,
        api_key: str | None = None,
        api_username: str | None = None,
        default_category_id: str | None = None,
        default_base_url: str | None = None,
    ) -> None:
        raw_base_urls = base_urls or self._split_csv(os.getenv("DISCOURSE_BASE_URLS", ""))
        single_base_url = (base_url or os.getenv("DISCOURSE_BASE_URL", "")).rstrip("/")
        if single_base_url and single_base_url not in raw_base_urls:
            raw_base_urls.insert(0, single_base_url)
        self.base_urls = [url.rstrip("/") for url in raw_base_urls if url.strip()]
        self.api_key = api_key or os.getenv("DISCOURSE_API_KEY", "")
        self.api_username = api_username or os.getenv("DISCOURSE_API_USERNAME", "")
        self.default_category_id = default_category_id or os.getenv(
            "DISCOURSE_DEFAULT_CATEGORY_ID",
            "",
        )
        requested_default = (
            default_base_url or os.getenv("DISCOURSE_DEFAULT_BASE_URL", "")
        ).rstrip("/")
        self.default_base_url = requested_default or (self.base_urls[0] if self.base_urls else "")
        self._clients: dict[str, httpx.AsyncClient] = {}
        self.last_errors: dict[str, dict[str, str]] = {}

    async def connect(self) -> None:
        headers = {
            "Accept": "application/json",
            "Api-Key": self.api_key,
            "Api-Username": self.api_username,
        }
        self._clients = {
            base_url: httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30)
            for base_url in self.base_urls
        }

    async def close(self) -> None:
        await asyncio.gather(*(client.aclose() for client in self._clients.values()))
        self._clients = {}

    @property
    def client(self) -> httpx.AsyncClient:
        if not self.default_base_url:
            raise RuntimeError("Discourse adapter not configured with a base URL.")
        if self.default_base_url not in self._clients:
            raise RuntimeError("Discourse adapter not connected.")
        return self._clients[self.default_base_url]

    @classmethod
    def is_configured(cls) -> bool:
        has_base_url = bool(os.getenv("DISCOURSE_BASE_URL") or os.getenv("DISCOURSE_BASE_URLS"))
        return bool(
            has_base_url
            and os.getenv("DISCOURSE_API_KEY")
            and os.getenv("DISCOURSE_API_USERNAME")
        )

    @classmethod
    def setup_guide(cls) -> dict[str, Any]:
        return {
            "url": "https://meta.discourse.org/t/discourse-rest-api-documentation/22706",
            "steps": [
                "1. Discourse 관리자 계정으로 로그인",
                "2. Admin > API Keys 에서 API key 생성",
                "3. base URL 하나면 DISCOURSE_BASE_URL, 여러 개면 DISCOURSE_BASE_URLS(csv) 저장",
                "4. 새 topic 작성까지 하려면 기본 category ID를 선택적으로 설정",
            ],
            "required_keys": [
                "DISCOURSE_API_KEY",
                "DISCOURSE_API_USERNAME",
            ],
            "required_any": [["DISCOURSE_BASE_URL", "DISCOURSE_BASE_URLS"]],
            "optional_keys": [
                "DISCOURSE_DEFAULT_BASE_URL",
                "DISCOURSE_DEFAULT_CATEGORY_ID",
            ],
            "allowed_actions": ["comment", "post", "upvote"],
        }

    async def get_trending(self, *, limit: int = 20) -> list[Post]:
        if not self._clients:
            raise RuntimeError("Discourse adapter not connected.")
        per_site = max(1, limit)
        results = await asyncio.gather(
            *(self._get_trending_from_site(base_url, per_site) for base_url in self._clients),
            return_exceptions=True,
        )
        posts = self._merge_site_results("get_trending", results)
        posts.sort(key=lambda post: post.likes, reverse=True)
        return posts[:limit]

    async def search(self, query: str, *, limit: int = 20) -> list[Post]:
        if not self._clients:
            raise RuntimeError("Discourse adapter not connected.")
        per_site = max(1, limit)
        results = await asyncio.gather(
            *(self._search_site(base_url, query, per_site) for base_url in self._clients),
            return_exceptions=True,
        )
        posts = self._merge_site_results("search", results)
        posts.sort(key=lambda post: post.likes, reverse=True)
        return posts[:limit]

    async def get_post(self, post_id: str) -> Post:
        base_url, topic_id = self._decode_topic_ref(post_id)
        client = self._get_client(base_url)
        resp = await client.get(f"/t/{topic_id}.json")
        resp.raise_for_status()
        topic = resp.json()
        return self._topic_to_post(topic, base_url=base_url, full=True)

    async def get_comments(self, post_id: str, *, limit: int = 50) -> list[Comment]:
        base_url, topic_id = self._decode_topic_ref(post_id)
        client = self._get_client(base_url)
        resp = await client.get(f"/t/{topic_id}.json")
        resp.raise_for_status()
        topic = resp.json()
        posts = topic.get("post_stream", {}).get("posts", [])
        post_ids_by_number = {
            int(post["post_number"]): str(post["id"])
            for post in posts
            if post.get("post_number") is not None and post.get("id") is not None
        }
        comments: list[Comment] = []
        for post in posts[1 : limit + 1]:
            parent_number = post.get("reply_to_post_number")
            parent_id = (
                post_ids_by_number.get(int(parent_number))
                if parent_number is not None
                else None
            )
            comments.append(
                self._post_to_comment(
                    post,
                    topic_id=self._encode_topic_ref(base_url, str(topic["id"])),
                    parent_id=parent_id,
                )
            )
        return comments

    async def get_user(self, username: str) -> UserProfile:
        resp = await self.client.get(f"/u/{username}.json")
        resp.raise_for_status()
        user = resp.json().get("user", {})
        return UserProfile(
            id=str(user.get("id", "")),
            platform=self.platform,
            username=user.get("username", username),
            name=user.get("name", ""),
            bio=user.get("bio_raw", ""),
            url=f"{self.default_base_url}/u/{user.get('username', username)}",
            followers=(
                user.get("user_field_1", 0)
                if isinstance(user.get("user_field_1"), int)
                else 0
            ),
            raw=user,
        )

    async def write_post(
        self,
        title: str,
        body: str,
        *,
        tags: list[str] | None = None,
        **kwargs: object,
    ) -> PostResult:
        payload: dict[str, Any] = {"title": title, "raw": body}
        category = str(kwargs.get("category", self.default_category_id))
        target_base_url = str(kwargs.get("base_url", self.default_base_url)).rstrip("/")
        if not target_base_url:
            return PostResult(
                success=False,
                platform=self.platform,
                error="No Discourse base URL configured",
            )
        if category:
            payload["category"] = int(category)
        if tags:
            payload["tags[]"] = tags[:5]
        resp = await self._get_client(target_base_url).post("/posts.json", json=payload)
        if resp.status_code >= 400:
            return PostResult(success=False, platform=self.platform, error=resp.text)
        data = resp.json()
        return PostResult(
            success=True,
            platform=self.platform,
            post_id=self._encode_topic_ref(target_base_url, str(data.get("topic_id", ""))),
            url=f"{target_base_url}/t/{data.get('topic_slug', '')}/{data.get('topic_id', '')}",
        )

    async def write_comment(self, post_id: str, body: str) -> PostResult:
        base_url, topic_id = self._decode_topic_ref(post_id)
        resp = await self._get_client(base_url).post(
            "/posts.json",
            json={"topic_id": int(topic_id), "raw": body},
        )
        if resp.status_code >= 400:
            return PostResult(success=False, platform=self.platform, error=resp.text)
        data = resp.json()
        return PostResult(
            success=True,
            platform=self.platform,
            post_id=str(data.get("id", "")),
            url=(
                f"{base_url}/t/{data.get('topic_slug', '')}/"
                f"{data.get('topic_id', '')}/{data.get('post_number', '')}"
            ),
        )

    async def upvote(self, post_id: str) -> PostResult:
        base_url, topic_id = self._decode_topic_ref(post_id)
        client = self._get_client(base_url)
        topic_resp = await client.get(f"/t/{topic_id}.json")
        if topic_resp.status_code >= 400:
            return PostResult(success=False, platform=self.platform, error=topic_resp.text)
        topic = topic_resp.json()
        first_post = next(iter(topic.get("post_stream", {}).get("posts", [])), None)
        if first_post is None:
            return PostResult(success=False, platform=self.platform, error="Topic has no posts")
        resp = await client.post(
            "/post_actions",
            json={"id": int(first_post["id"]), "post_action_type_id": 2},
        )
        if resp.status_code >= 400:
            return PostResult(success=False, platform=self.platform, error=resp.text)
        return PostResult(success=True, platform=self.platform, post_id=str(first_post["id"]))

    async def _get_trending_from_site(self, base_url: str, limit: int) -> list[Post]:
        resp = await self._get_client(base_url).get("/latest.json", params={"page": 0})
        resp.raise_for_status()
        topics = resp.json().get("topic_list", {}).get("topics", [])
        return [self._topic_to_post(topic, base_url=base_url) for topic in topics[:limit]]

    async def _search_site(self, base_url: str, query: str, limit: int) -> list[Post]:
        resp = await self._get_client(base_url).get("/search.json", params={"q": query})
        resp.raise_for_status()
        topics = resp.json().get("topics", [])
        return [self._topic_to_post(topic, base_url=base_url) for topic in topics[:limit]]

    def _topic_to_post(self, topic: dict[str, Any], base_url: str, full: bool = False) -> Post:
        topic_id = str(topic["id"])
        slug = topic.get("slug", topic_id)
        raw_post = next(iter(topic.get("post_stream", {}).get("posts", [])), {}) if full else {}
        body = raw_post.get("raw", "") or topic.get("excerpt", "")
        tags = topic.get("tags", [])
        category = topic.get("category_id")
        if category is not None:
            tags = [*tags, f"category:{category}"]
        return Post(
            id=self._encode_topic_ref(base_url, topic_id),
            platform=self.platform,
            title=topic.get("title", ""),
            url=f"{base_url}/t/{slug}/{topic_id}",
            body=body,
            author=raw_post.get("username", topic.get("last_poster_username", "")),
            tags=tags,
            likes=topic.get("like_count", 0) or topic.get("views", 0),
            comments_count=max(0, topic.get("posts_count", 1) - 1),
            published_at=self._parse_datetime(topic.get("created_at")),
            raw={**topic, "base_url": base_url},
        )

    def _merge_site_results(
        self,
        operation: str,
        results: list[list[Post] | BaseException],
    ) -> list[Post]:
        posts: list[Post] = []
        errors: dict[str, str] = {}
        for base_url, result in zip(self._clients, results):
            if isinstance(result, list):
                posts.extend(result)
            elif isinstance(result, BaseException):
                errors[base_url] = str(result)
        self.last_errors[operation] = errors
        return posts

    def _post_to_comment(
        self,
        post: dict[str, Any],
        topic_id: str,
        parent_id: str | None = None,
    ) -> Comment:
        return Comment(
            id=str(post["id"]),
            platform=self.platform,
            body=post.get("raw", "") or post.get("cooked", ""),
            author=post.get("username", ""),
            post_id=topic_id,
            parent_id=parent_id,
            likes=post.get("actions_summary", [{}])[0].get("count", 0)
            if post.get("actions_summary")
            else 0,
            created_at=self._parse_datetime(post.get("created_at")),
            raw=post,
        )

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None

    def _get_client(self, base_url: str) -> httpx.AsyncClient:
        resolved = base_url.rstrip("/")
        if resolved not in self._clients:
            raise ValueError(f"Unknown Discourse base URL: {resolved}")
        return self._clients[resolved]

    def _decode_topic_ref(self, post_id: str) -> tuple[str, str]:
        marker = "::topic::"
        if marker in post_id:
            base_url, _, topic_id = post_id.partition(marker)
            if base_url and topic_id:
                return base_url.rstrip("/"), topic_id
        if not self.default_base_url:
            raise ValueError("Discourse post_id requires a configured base URL")
        return self.default_base_url, post_id

    @staticmethod
    def _encode_topic_ref(base_url: str, topic_id: str) -> str:
        return f"{base_url.rstrip('/')}::topic::{topic_id}"

    @staticmethod
    def _split_csv(value: str) -> list[str]:
        return [part.strip() for part in value.split(",") if part.strip()]
