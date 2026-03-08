"""Abstract base class for all platform adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from typing_extensions import Self

from devhub.types import Comment, Post, PostResult, UserProfile


class PlatformAdapter(ABC):
    """Base interface every platform adapter must implement.

    Usage::

        async with MyAdapter(api_key="...") as adapter:
            posts = await adapter.get_trending(limit=10)
    """

    platform: str = "unknown"

    # -- plugin metadata --

    @classmethod
    def setup_guide(cls) -> dict[str, Any]:
        """Return onboarding guide for this platform.

        Subclasses should override to provide platform-specific setup info::

            {
                "url": "https://...",
                "steps": ["1. ...", "2. ..."],
                "required_keys": ["API_KEY"],
                "allowed_actions": ["comment", "post"],
            }
        """
        return {
            "url": "",
            "steps": [],
            "required_keys": [],
            "allowed_actions": ["comment"],
        }

    # -- lifecycle --

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def connect(self) -> None:
        """Initialize HTTP clients or SDK sessions."""

    async def close(self) -> None:
        """Tear down resources."""

    # -- configuration --

    @classmethod
    @abstractmethod
    def is_configured(cls) -> bool:
        """Return True when all required env vars are present."""
        ...

    # -- read --

    @abstractmethod
    async def get_trending(self, *, limit: int = 20) -> list[Post]:
        """Fetch trending / hot posts."""
        ...

    @abstractmethod
    async def search(self, query: str, *, limit: int = 20) -> list[Post]:
        """Full-text search across the platform."""
        ...

    @abstractmethod
    async def get_post(self, post_id: str) -> Post:
        """Get a single post by its platform-specific ID."""
        ...

    @abstractmethod
    async def get_comments(self, post_id: str, *, limit: int = 50) -> list[Comment]:
        """List comments on a post."""
        ...

    @abstractmethod
    async def get_user(self, username: str) -> UserProfile:
        """Fetch a user profile."""
        ...

    # -- write --

    @abstractmethod
    async def write_post(
        self,
        title: str,
        body: str,
        *,
        tags: list[str] | None = None,
        **kwargs: object,
    ) -> PostResult:
        """Publish a new post / article."""
        ...

    @abstractmethod
    async def write_comment(self, post_id: str, body: str) -> PostResult:
        """Add a comment to a post."""
        ...

    @abstractmethod
    async def upvote(self, post_id: str) -> PostResult:
        """Like / upvote / heart a post."""
        ...
