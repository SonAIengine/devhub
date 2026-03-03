"""Tests for Hub orchestrator."""

from unittest.mock import AsyncMock

import pytest

from devhub.hub import Hub
from devhub.types import Post, PostResult


class FakeAdapter:
    platform = "fake"

    async def connect(self):
        pass

    async def close(self):
        pass

    @classmethod
    def is_configured(cls):
        return True

    async def get_trending(self, *, limit=20):
        return [
            Post(id="1", platform="fake", title="Trending", url="https://fake.com/1", likes=10)
        ]

    async def search(self, query, *, limit=20):
        return [
            Post(id="2", platform="fake", title=f"Search: {query}", url="https://fake.com/2", likes=5)
        ]

    async def write_post(self, title, body, *, tags=None, **kwargs):
        return PostResult(success=True, platform="fake", post_id="99")


async def test_hub_search():
    hub = Hub(adapters=[FakeAdapter()])
    async with hub:
        results = await hub.search("python")
        assert len(results) == 1
        assert results[0].title == "Search: python"


async def test_hub_get_trending():
    hub = Hub(adapters=[FakeAdapter()])
    async with hub:
        results = await hub.get_trending()
        assert len(results) == 1
        assert results[0].title == "Trending"


async def test_hub_publish():
    hub = Hub(adapters=[FakeAdapter()])
    async with hub:
        results = await hub.publish("Title", "Body")
        assert len(results) == 1
        assert results[0].success is True


async def test_hub_publish_filter_platforms():
    hub = Hub(adapters=[FakeAdapter()])
    async with hub:
        results = await hub.publish("Title", "Body", platforms=["nonexistent"])
        assert len(results) == 0


async def test_hub_multiple_adapters():
    a1 = FakeAdapter()
    a1.platform = "alpha"
    a2 = FakeAdapter()
    a2.platform = "beta"
    hub = Hub(adapters=[a1, a2])
    async with hub:
        results = await hub.search("test")
        assert len(results) == 2


async def test_hub_merge_sorts_by_likes():
    a1 = FakeAdapter()
    a1.platform = "low"
    a1.search = AsyncMock(return_value=[
        Post(id="1", platform="low", title="Low", url="", likes=1)
    ])
    a2 = FakeAdapter()
    a2.platform = "high"
    a2.search = AsyncMock(return_value=[
        Post(id="2", platform="high", title="High", url="", likes=100)
    ])
    hub = Hub(adapters=[a1, a2])
    async with hub:
        results = await hub.search("test")
        assert results[0].likes == 100
        assert results[1].likes == 1


async def test_hub_platform_names():
    hub = Hub(adapters=[FakeAdapter()])
    assert hub.platform_names == ["fake"]


async def test_hub_handles_adapter_error():
    failing = FakeAdapter()
    failing.search = AsyncMock(side_effect=RuntimeError("API down"))
    hub = Hub(adapters=[FakeAdapter(), failing])
    async with hub:
        results = await hub.search("python")
        assert len(results) == 1
