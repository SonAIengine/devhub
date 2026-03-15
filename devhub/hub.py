"""Hub — multi-platform orchestrator."""

from __future__ import annotations

import asyncio

from typing_extensions import Self

from devhub.base import PlatformAdapter
from devhub.types import Post, PostResult


class Hub:
    """Aggregate multiple platform adapters behind one interface.

    Usage::

        async with Hub.from_env() as hub:
            results = await hub.search("python")
            await hub.publish("Title", "Body", tags=["python"])
    """

    def __init__(self, adapters: list[PlatformAdapter] | None = None) -> None:
        self.adapters: list[PlatformAdapter] = adapters or []
        self.last_errors: dict[str, dict[str, str | dict[str, str]]] = {}

    # -- factory --

    @classmethod
    def from_env(cls) -> Hub:
        """Build a Hub with every adapter whose env vars are present."""
        from devhub.registry import get_configured_adapters

        return cls(get_configured_adapters())

    # -- lifecycle --

    async def __aenter__(self) -> Self:
        await asyncio.gather(*(a.connect() for a in self.adapters))
        return self

    async def __aexit__(self, *_: object) -> None:
        await asyncio.gather(*(a.close() for a in self.adapters))

    # -- read (fan-out) --

    async def get_trending(self, *, limit: int = 20) -> list[Post]:
        """Fetch trending posts from all active platforms."""
        targets = list(self.adapters)
        results = await asyncio.gather(
            *(a.get_trending(limit=limit) for a in targets),
            return_exceptions=True,
        )
        posts, errors = self._collect_posts(targets, results, operation="get_trending")
        self.last_errors["get_trending"] = errors
        return posts

    async def search(self, query: str, *, limit: int = 20) -> list[Post]:
        """Search across all active platforms in parallel."""
        targets = list(self.adapters)
        results = await asyncio.gather(
            *(a.search(query, limit=limit) for a in targets),
            return_exceptions=True,
        )
        posts, errors = self._collect_posts(targets, results, operation="search")
        self.last_errors["search"] = errors
        return posts

    # -- write (fan-out) --

    async def publish(
        self,
        title: str,
        body: str,
        *,
        tags: list[str] | None = None,
        platforms: list[str] | None = None,
    ) -> list[PostResult]:
        """Publish to multiple platforms concurrently.

        Args:
            platforms: If given, only publish to these platform names.
        """
        targets = self._filter(platforms)
        results = await asyncio.gather(
            *(a.write_post(title, body, tags=tags) for a in targets),
            return_exceptions=True,
        )
        errors: dict[str, str] = {}
        out: list[PostResult] = []
        for adapter, r in zip(targets, results):
            if isinstance(r, PostResult):
                out.append(r)
            elif isinstance(r, BaseException):
                errors[adapter.platform] = str(r)
                out.append(PostResult(success=False, platform=adapter.platform, error=str(r)))
        self.last_errors["publish"] = errors
        return out

    # -- helpers --

    @property
    def platform_names(self) -> list[str]:
        return [a.platform for a in self.adapters]

    def _filter(self, names: list[str] | None) -> list[PlatformAdapter]:
        if names is None:
            return self.adapters
        return [a for a in self.adapters if a.platform in names]

    @staticmethod
    def _collect_posts(
        adapters: list[PlatformAdapter],
        results: list[list[Post] | BaseException],
        operation: str,
    ) -> tuple[list[Post], dict[str, str | dict[str, str]]]:
        merged: list[Post] = []
        errors: dict[str, str | dict[str, str]] = {}
        for adapter, r in zip(adapters, results):
            if isinstance(r, list):
                merged.extend(r)
                adapter_errors = getattr(adapter, "last_errors", {})
                if isinstance(adapter_errors, dict):
                    operation_errors = adapter_errors.get(operation, {})
                    if operation_errors:
                        errors[adapter.platform] = operation_errors
            elif isinstance(r, BaseException):
                errors[adapter.platform] = str(r)
        merged.sort(key=lambda p: p.likes, reverse=True)
        return merged, errors
