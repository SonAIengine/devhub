"""Stack Overflow (Stack Exchange API v2.3) platform adapter."""

from __future__ import annotations

import html
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from devhub.base import PlatformAdapter
from devhub.types import Comment, Post, PostResult, UserProfile

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.stackexchange.com/2.3"


def _strip_html(text: str) -> str:
    """HTML 태그 제거 + HTML 엔티티 디코딩 → 플레인 텍스트."""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _epoch_to_dt(epoch: int | None) -> datetime | None:
    """Unix epoch → timezone-aware datetime."""
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


class StackOverflow(PlatformAdapter):
    """Async adapter for Stack Overflow via Stack Exchange API v2.3."""

    platform = "stackoverflow"

    def __init__(
        self,
        api_key: str | None = None,
        access_token: str | None = None,
        tags: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("STACKOVERFLOW_API_KEY", "")
        self.access_token = access_token or os.getenv("STACKOVERFLOW_ACCESS_TOKEN", "")
        self.default_tags = (
            tags or os.getenv("STACKOVERFLOW_TAGS", "")
        )
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle --

    async def connect(self) -> None:
        if httpx is None:
            raise ImportError("Install httpx: pip install httpx")
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={"Accept-Encoding": "gzip"},
            timeout=30.0,
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("StackOverflow adapter not connected.")
        return self._client

    # -- configuration --

    @classmethod
    def is_configured(cls) -> bool:
        # Read endpoints work without any key; API key just raises rate limit.
        return True

    @classmethod
    def setup_guide(cls) -> dict[str, Any]:
        return {
            "url": "https://stackapps.com/apps/oauth/register",
            "steps": [
                "1. https://stackapps.com/apps/oauth/register 접속 (Stack Exchange 계정 필요)",
                "2. Application Name, Description 입력",
                "3. OAuth Domain에 localhost 입력 (개인 사용)",
                "4. 등록 후 'Key' 값 복사 → STACKOVERFLOW_API_KEY",
                "5. (선택) OAuth 인증으로 access_token 발급 → STACKOVERFLOW_ACCESS_TOKEN",
                "6. STACKOVERFLOW_TAGS에 모니터링할 태그 설정 (예: python,llm,mcp)",
            ],
            "required_keys": ["STACKOVERFLOW_API_KEY"],
            "allowed_actions": ["comment", "upvote"],
        }

    # -- internal helpers --

    def _base_params(self) -> dict[str, str]:
        """모든 요청에 공통으로 붙는 파라미터."""
        params: dict[str, str] = {"site": "stackoverflow"}
        if self.api_key:
            params["key"] = self.api_key
        return params

    def _auth_params(self) -> dict[str, str]:
        """Write 요청에 추가되는 인증 파라미터."""
        params = self._base_params()
        if self.access_token:
            params["access_token"] = self.access_token
        return params

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """GET 요청 + quota 경고."""
        merged = self._base_params()
        if params:
            merged.update(params)
        resp = await self.client.get(path, params=merged)
        resp.raise_for_status()
        data = resp.json()
        self._check_quota(data)
        return data

    async def _post(self, path: str, data: dict[str, str] | None = None) -> dict[str, Any]:
        """POST 요청 (write operations)."""
        if not self.access_token:
            raise PermissionError(
                "STACKOVERFLOW_ACCESS_TOKEN 필요 (write operations)"
            )
        form = self._auth_params()
        if data:
            form.update(data)
        resp = await self.client.post(path, data=form)
        resp.raise_for_status()
        result = resp.json()
        self._check_quota(result)
        return result

    def _check_quota(self, data: dict[str, Any]) -> None:
        """quota_remaining이 낮으면 경고 로그."""
        remaining = data.get("quota_remaining")
        if remaining is not None and remaining < 50:
            logger.warning(
                "Stack Exchange API quota 부족: %d remaining", remaining
            )

    # -- mapping --

    def _question_to_post(self, q: dict[str, Any]) -> Post:
        """Stack Exchange question dict → Post."""
        owner = q.get("owner", {})
        tags = q.get("tags", [])
        body = _strip_html(q.get("body", ""))

        return Post(
            id=str(q["question_id"]),
            platform=self.platform,
            title=html.unescape(q.get("title", "")),
            url=q.get("link", f"https://stackoverflow.com/questions/{q['question_id']}"),
            body=body,
            author=owner.get("display_name", ""),
            tags=tags,
            likes=q.get("score", 0),
            comments_count=q.get("answer_count", 0),
            published_at=_epoch_to_dt(q.get("creation_date")),
            raw=q,
        )

    def _answer_to_comment(self, a: dict[str, Any], post_id: str) -> Comment:
        """Stack Exchange answer dict → Comment."""
        owner = a.get("owner", {})

        return Comment(
            id=str(a["answer_id"]),
            platform=self.platform,
            body=_strip_html(a.get("body", "")),
            author=owner.get("display_name", ""),
            post_id=post_id,
            parent_id=None,
            likes=a.get("score", 0),
            created_at=_epoch_to_dt(a.get("creation_date")),
            raw=a,
        )

    # -- read --

    async def get_trending(self, *, limit: int = 20) -> list[Post]:
        params: dict[str, str] = {
            "order": "desc",
            "sort": "hot",
            "pagesize": str(min(limit, 100)),
            "filter": "withbody",
        }
        if self.default_tags:
            params["tagged"] = self.default_tags.replace(",", ";")

        data = await self._get("/questions", params)
        return [self._question_to_post(q) for q in data.get("items", [])]

    async def search(self, query: str, *, limit: int = 20) -> list[Post]:
        params: dict[str, str] = {
            "q": query,
            "order": "desc",
            "sort": "relevance",
            "pagesize": str(min(limit, 100)),
            "filter": "withbody",
        }
        data = await self._get("/search/advanced", params)
        return [self._question_to_post(q) for q in data.get("items", [])]

    async def get_post(self, post_id: str) -> Post:
        data = await self._get(
            f"/questions/{post_id}",
            {"filter": "withbody"},
        )
        items = data.get("items", [])
        if not items:
            raise ValueError(f"Question not found: {post_id}")
        return self._question_to_post(items[0])

    async def get_comments(self, post_id: str, *, limit: int = 50) -> list[Comment]:
        data = await self._get(
            f"/questions/{post_id}/answers",
            {
                "order": "desc",
                "sort": "votes",
                "pagesize": str(min(limit, 100)),
                "filter": "withbody",
            },
        )
        return [
            self._answer_to_comment(a, post_id) for a in data.get("items", [])
        ]

    async def get_user(self, username: str) -> UserProfile:
        # username은 user_id (숫자) 또는 display_name 가능.
        # Stack Exchange API는 user_id로 조회하므로 숫자가 아니면 검색 시도.
        if username.isdigit():
            data = await self._get(f"/users/{username}")
        else:
            data = await self._get(
                "/users",
                {"inname": username, "pagesize": "1", "sort": "reputation", "order": "desc"},
            )
        items = data.get("items", [])
        if not items:
            raise ValueError(f"User not found: {username}")
        u = items[0]
        return UserProfile(
            id=str(u["user_id"]),
            platform=self.platform,
            username=str(u["user_id"]),
            name=u.get("display_name", ""),
            bio=u.get("about_me", ""),
            url=u.get("link", f"https://stackoverflow.com/users/{u['user_id']}"),
            followers=u.get("reputation", 0),
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
        try:
            form: dict[str, str] = {"title": title, "body": body}
            if tags:
                form["tags"] = ";".join(tags)
            data = await self._post("/questions/add", form)
            items = data.get("items", [])
            if not items:
                return PostResult(
                    success=False,
                    platform=self.platform,
                    error=data.get("error_message", "No item returned"),
                )
            q = items[0]
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=str(q["question_id"]),
                url=q.get("link", ""),
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    async def write_comment(self, post_id: str, body: str) -> PostResult:
        try:
            data = await self._post(
                f"/questions/{post_id}/answers",
                {"body": body},
            )
            items = data.get("items", [])
            if not items:
                return PostResult(
                    success=False,
                    platform=self.platform,
                    error=data.get("error_message", "No item returned"),
                )
            a = items[0]
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=str(a["answer_id"]),
                url=f"https://stackoverflow.com/a/{a['answer_id']}",
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))

    async def upvote(self, post_id: str) -> PostResult:
        try:
            data = await self._post(f"/questions/{post_id}/upvote")
            return PostResult(
                success=True,
                platform=self.platform,
                post_id=post_id,
            )
        except Exception as exc:
            return PostResult(success=False, platform=self.platform, error=str(exc))
