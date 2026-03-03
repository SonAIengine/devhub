"""Tests for DevTo adapter with mocked httpx responses."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from devhub.devto import DevTo


@pytest.fixture
def sample_article():
    return {
        "id": 12345,
        "title": "Test Article",
        "description": "A test article",
        "url": "https://dev.to/test/test-article",
        "tag_list": "python, testing",
        "public_reactions_count": 42,
        "comments_count": 5,
        "published_at": "2024-01-15T10:00:00Z",
        "user": {"username": "testuser"},
    }


@pytest.fixture
def sample_comment():
    return {
        "id_code": "abc123",
        "body_html": "<p>Great article!</p>",
        "created_at": "2024-01-15T12:00:00Z",
        "user": {"username": "commenter"},
        "children": [],
    }


@pytest.fixture
def sample_user():
    return {
        "id": 67890,
        "username": "testuser",
        "name": "Test User",
        "summary": "A developer",
    }


def _mock_response(data, status_code=200):
    resp = httpx.Response(
        status_code=status_code,
        content=json.dumps(data).encode(),
        request=httpx.Request("GET", "https://dev.to/api/test"),
    )
    return resp


async def test_is_configured_false():
    with patch.dict("os.environ", {}, clear=True):
        assert DevTo.is_configured() is False


async def test_is_configured_true():
    with patch.dict("os.environ", {"DEVTO_API_KEY": "test-key"}):
        assert DevTo.is_configured() is True


async def test_get_trending(sample_article):
    async with DevTo(api_key="test") as devto:
        devto.client.get = AsyncMock(return_value=_mock_response([sample_article]))
        posts = await devto.get_trending(limit=5)
        assert len(posts) == 1
        assert posts[0].id == "12345"
        assert posts[0].title == "Test Article"
        assert posts[0].platform == "devto"
        assert posts[0].likes == 42
        assert "python" in posts[0].tags


async def test_search(sample_article):
    async with DevTo(api_key="test") as devto:
        devto.client.get = AsyncMock(return_value=_mock_response([sample_article]))
        posts = await devto.search("python")
        assert len(posts) == 1
        assert posts[0].title == "Test Article"


async def test_get_post(sample_article):
    async with DevTo(api_key="test") as devto:
        devto.client.get = AsyncMock(return_value=_mock_response(sample_article))
        post = await devto.get_post("12345")
        assert post.id == "12345"
        assert post.author == "testuser"


async def test_get_comments(sample_comment):
    async with DevTo(api_key="test") as devto:
        devto.client.get = AsyncMock(return_value=_mock_response([sample_comment]))
        comments = await devto.get_comments("12345")
        assert len(comments) == 1
        assert comments[0].id == "abc123"
        assert comments[0].body == "<p>Great article!</p>"


async def test_get_comments_nested():
    nested = {
        "id_code": "parent",
        "body_html": "Parent",
        "created_at": "2024-01-15T12:00:00Z",
        "user": {"username": "a"},
        "children": [
            {
                "id_code": "child",
                "body_html": "Child",
                "created_at": "2024-01-15T13:00:00Z",
                "user": {"username": "b"},
                "children": [],
            }
        ],
    }
    async with DevTo(api_key="test") as devto:
        devto.client.get = AsyncMock(return_value=_mock_response([nested]))
        comments = await devto.get_comments("1")
        assert len(comments) == 2
        assert comments[1].parent_id == "parent"


async def test_get_user(sample_user):
    async with DevTo(api_key="test") as devto:
        devto.client.get = AsyncMock(return_value=_mock_response(sample_user))
        user = await devto.get_user("testuser")
        assert user.username == "testuser"
        assert user.name == "Test User"


async def test_write_post():
    resp_data = {"id": 99, "url": "https://dev.to/test/new-post"}
    async with DevTo(api_key="test") as devto:
        devto.client.post = AsyncMock(return_value=_mock_response(resp_data, 201))
        result = await devto.write_post("Title", "Body", tags=["python"])
        assert result.success is True
        assert result.post_id == "99"


async def test_write_post_failure():
    async with DevTo(api_key="test") as devto:
        devto.client.post = AsyncMock(return_value=_mock_response({"error": "unauthorized"}, 401))
        result = await devto.write_post("Title", "Body")
        assert result.success is False
        assert result.error != ""


async def test_write_comment():
    resp_data = {"id_code": "xyz"}
    async with DevTo(api_key="test") as devto:
        devto.client.post = AsyncMock(return_value=_mock_response(resp_data, 201))
        result = await devto.write_comment("12345", "Nice!")
        assert result.success is True


async def test_upvote():
    resp_data = {"result": "create", "reactable_id": "12345"}
    async with DevTo(api_key="test") as devto:
        devto.client.post = AsyncMock(return_value=_mock_response(resp_data, 200))
        result = await devto.upvote("12345")
        assert result.success is True


async def test_context_manager():
    async with DevTo(api_key="test") as devto:
        assert devto._client is not None
    assert devto._client is None
