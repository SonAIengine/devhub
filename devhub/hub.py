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

    # -- factory --

    @classmethod
    def from_env(cls) -> Hub:
        """Build a Hub with every adapter whose env vars are present."""
        from devhub.bluesky import Bluesky
        from devhub.devto import DevTo
        from devhub.reddit import Reddit
        from devhub.twitter import Twitter

        adapters: list[PlatformAdapter] = []
        for adapter_cls in (DevTo, Bluesky, Twitter, Reddit):
            if adapter_cls.is_configured():
                adapters.append(adapter_cls())
        return cls(adapters)

    # -- lifecycle --

    async def __aenter__(self) -> Self:
        await asyncio.gather(*(a.connect() for a in self.adapters))
        return self

    async def __aexit__(self, *_: object) -> None:
        await asyncio.gather(*(a.close() for a in self.adapters))

    # -- read (fan-out) --

    async def get_trending(self, *, limit: int = 20) -> list[Post]:
        """Fetch trending posts from all active platforms."""
        results = await asyncio.gather(
            *(a.get_trending(limit=limit) for a in self.adapters),
            return_exceptions=True,
        )
        return self._merge_posts(results)

    async def search(self, query: str, *, limit: int = 20) -> list[Post]:
        """Search across all active platforms in parallel."""
        results = await asyncio.gather(
            *(a.search(query, limit=limit) for a in self.adapters),
            return_exceptions=True,
        )
        return self._merge_posts(results)

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
        out: list[PostResult] = []
        for r in results:
            if isinstance(r, PostResult):
                out.append(r)
            elif isinstance(r, BaseException):
                out.append(PostResult(success=False, platform="unknown", error=str(r)))
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
    def _merge_posts(results: list[list[Post] | BaseException]) -> list[Post]:
        merged: list[Post] = []
        for r in results:
            if isinstance(r, list):
                merged.extend(r)
        merged.sort(key=lambda p: p.likes, reverse=True)
        return merged
