"""Tests for Discourse adapter with mocked httpx responses."""

import json
from unittest.mock import AsyncMock, patch

import httpx

from devhub.discourse import Discourse


def _mock_response(data, status_code=200):
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(data).encode(),
        request=httpx.Request("GET", "https://forum.example.com/test"),
    )


async def test_is_configured_false():
    with patch.dict("os.environ", {}, clear=True):
        assert Discourse.is_configured() is False


async def test_is_configured_true():
    with patch.dict(
        "os.environ",
        {
            "DISCOURSE_BASE_URL": "https://forum.example.com",
            "DISCOURSE_API_KEY": "key",
            "DISCOURSE_API_USERNAME": "alice",
        },
    ):
        assert Discourse.is_configured() is True


async def test_is_configured_true_with_base_urls_only():
    with patch.dict(
        "os.environ",
        {
            "DISCOURSE_BASE_URLS": "https://forum-a.example.com,https://forum-b.example.com",
            "DISCOURSE_API_KEY": "key",
            "DISCOURSE_API_USERNAME": "alice",
        },
    ):
        assert Discourse.is_configured() is True


async def test_get_trending():
    payload = {
        "topic_list": {
            "topics": [
                {
                    "id": 101,
                    "title": "MCP deployment tips",
                    "slug": "mcp-deployment-tips",
                    "excerpt": "short",
                    "tags": ["mcp"],
                    "category_id": 7,
                    "like_count": 4,
                    "posts_count": 3,
                    "created_at": "2026-03-15T00:00:00Z",
                    "last_poster_username": "alice",
                }
            ]
        }
    }
    async with Discourse(
        base_url="https://forum.example.com",
        api_key="key",
        api_username="alice",
    ) as discourse:
        discourse.client.get = AsyncMock(return_value=_mock_response(payload))
        posts = await discourse.get_trending(limit=5)
        assert len(posts) == 1
        assert posts[0].platform == "discourse"
        assert posts[0].comments_count == 2


async def test_get_trending_merges_multiple_instances():
    payload_a = {
        "topic_list": {
            "topics": [
                {
                    "id": 101,
                    "title": "Forum A",
                    "slug": "forum-a",
                    "like_count": 1,
                    "posts_count": 2,
                }
            ]
        }
    }
    payload_b = {
        "topic_list": {
            "topics": [
                {
                    "id": 202,
                    "title": "Forum B",
                    "slug": "forum-b",
                    "like_count": 9,
                    "posts_count": 4,
                }
            ]
        }
    }
    async with Discourse(
        base_urls=["https://forum-a.example.com", "https://forum-b.example.com"],
        api_key="key",
        api_username="alice",
        default_base_url="https://forum-a.example.com",
    ) as discourse:
        discourse._clients = {
            "https://forum-a.example.com": AsyncMock(
                get=AsyncMock(return_value=_mock_response(payload_a))
            ),
            "https://forum-b.example.com": AsyncMock(
                get=AsyncMock(return_value=_mock_response(payload_b))
            ),
        }
        posts = await discourse.get_trending(limit=5)
        assert len(posts) == 2
        assert posts[0].title == "Forum B"
        assert posts[0].id == "https://forum-b.example.com::topic::202"


async def test_get_comments_maps_parent_post_id():
    payload = {
        "id": 101,
        "post_stream": {
            "posts": [
                {"id": 900, "post_number": 1, "username": "op", "raw": "root"},
                {
                    "id": 901,
                    "post_number": 2,
                    "username": "alice",
                    "raw": "first reply",
                    "actions_summary": [{"count": 3}],
                },
                {
                    "id": 902,
                    "post_number": 3,
                    "username": "bob",
                    "raw": "reply to first",
                    "reply_to_post_number": 2,
                    "actions_summary": [{"count": 1}],
                },
            ]
        },
    }
    async with Discourse(
        base_url="https://forum.example.com",
        api_key="key",
        api_username="alice",
    ) as discourse:
        discourse.client.get = AsyncMock(return_value=_mock_response(payload))
        comments = await discourse.get_comments("101")
        assert len(comments) == 2
        assert comments[0].id == "901"
        assert comments[1].parent_id == "901"


async def test_get_comments_accepts_composite_topic_id():
    payload = {
        "id": 101,
        "post_stream": {
            "posts": [
                {"id": 900, "post_number": 1, "username": "op", "raw": "root"},
                {"id": 901, "post_number": 2, "username": "alice", "raw": "reply"},
            ]
        },
    }
    async with Discourse(
        base_urls=["https://forum.example.com", "https://forum2.example.com"],
        api_key="key",
        api_username="alice",
        default_base_url="https://forum2.example.com",
    ) as discourse:
        discourse._clients = {
            "https://forum.example.com": AsyncMock(
                get=AsyncMock(return_value=_mock_response(payload))
            ),
            "https://forum2.example.com": AsyncMock(
                get=AsyncMock(side_effect=AssertionError("wrong client selected"))
            ),
        }
        comments = await discourse.get_comments("https://forum.example.com::topic::101")
        assert len(comments) == 1
        assert comments[0].post_id == "https://forum.example.com::topic::101"


async def test_write_post():
    payload = {"topic_id": 101, "topic_slug": "mcp-thread"}
    async with Discourse(
        base_url="https://forum.example.com",
        api_key="key",
        api_username="alice",
    ) as discourse:
        discourse.client.post = AsyncMock(return_value=_mock_response(payload, 200))
        result = await discourse.write_post("Title", "Body")
        assert result.success is True
        assert result.post_id == "https://forum.example.com::topic::101"


async def test_write_comment():
    payload = {"id": 901, "topic_id": 101, "topic_slug": "mcp-thread", "post_number": 2}
    async with Discourse(
        base_url="https://forum.example.com",
        api_key="key",
        api_username="alice",
    ) as discourse:
        discourse.client.post = AsyncMock(return_value=_mock_response(payload, 200))
        result = await discourse.write_comment("101", "Helpful answer")
        assert result.success is True
        assert result.post_id == "901"


async def test_upvote():
    topic_payload = {
        "post_stream": {
            "posts": [{"id": 900, "post_number": 1, "username": "op", "raw": "root"}]
        }
    }
    async with Discourse(
        base_url="https://forum.example.com",
        api_key="key",
        api_username="alice",
    ) as discourse:
        discourse.client.get = AsyncMock(return_value=_mock_response(topic_payload))
        discourse.client.post = AsyncMock(return_value=_mock_response({"ok": True}, 200))
        result = await discourse.upvote("101")
        assert result.success is True
        assert result.post_id == "900"
