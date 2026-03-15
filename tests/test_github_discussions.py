"""Tests for GitHub Discussions adapter with mocked GraphQL/REST responses."""

import json
from unittest.mock import AsyncMock, patch

import httpx

from devhub.github_discussions import GitHubDiscussions


def _mock_response(data, status_code=200):
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(data).encode(),
        request=httpx.Request("POST", "https://api.github.com/graphql"),
    )


async def test_is_configured_false():
    with patch.dict("os.environ", {}, clear=True):
        assert GitHubDiscussions.is_configured() is False


async def test_is_configured_true():
    with patch.dict(
        "os.environ",
        {
            "GITHUB_TOKEN": "token",
            "GITHUB_DISCUSSIONS_REPOS": "openai/openai-python",
        },
    ):
        assert GitHubDiscussions.is_configured() is True


async def test_get_trending():
    payload = {
        "data": {
            "repository": {
                "discussions": {
                    "nodes": [
                        {
                            "id": "D_1",
                            "title": "MCP patterns",
                            "body": "body",
                            "url": "https://github.com/openai/openai-python/discussions/1",
                            "upvoteCount": 9,
                            "comments": {"totalCount": 3},
                            "createdAt": "2026-03-15T00:00:00Z",
                            "author": {"login": "alice"},
                            "category": {"id": "cat_1", "name": "Ideas", "isAnswerable": False},
                        }
                    ]
                }
            }
        }
    }
    async with GitHubDiscussions(token="token", repositories=["openai/openai-python"]) as gh:
        gh.client.post = AsyncMock(return_value=_mock_response(payload))
        posts = await gh.get_trending(limit=5)
        assert len(posts) == 1
        assert posts[0].platform == "github_discussions"
        assert posts[0].author == "alice"
        assert posts[0].tags == ["Ideas"]


async def test_get_comments_flattens_replies():
    payload = {
        "data": {
            "node": {
                "comments": {
                    "nodes": [
                        {
                            "id": "C_1",
                            "body": "parent",
                            "createdAt": "2026-03-15T00:00:00Z",
                            "upvoteCount": 2,
                            "author": {"login": "alice"},
                            "replies": {
                                "nodes": [
                                    {
                                        "id": "C_2",
                                        "body": "reply",
                                        "createdAt": "2026-03-15T00:10:00Z",
                                        "upvoteCount": 1,
                                        "author": {"login": "bob"},
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        }
    }
    async with GitHubDiscussions(token="token", repositories=["openai/openai-python"]) as gh:
        gh.client.post = AsyncMock(return_value=_mock_response(payload))
        comments = await gh.get_comments("D_1")
        assert len(comments) == 2
        assert comments[0].id == "C_1"
        assert comments[1].parent_id == "C_1"


async def test_write_post_requires_repo_and_category():
    async with GitHubDiscussions(token="token", repositories=["openai/openai-python"]) as gh:
        result = await gh.write_post("Title", "Body")
        assert result.success is False
        assert "DEFAULT_REPO" in result.error


async def test_write_comment():
    payload = {"data": {"addDiscussionComment": {"comment": {"id": "C_99", "url": "https://x"}}}}
    async with GitHubDiscussions(token="token", repositories=["openai/openai-python"]) as gh:
        gh.client.post = AsyncMock(return_value=_mock_response(payload))
        result = await gh.write_comment("D_1", "Nice")
        assert result.success is True
        assert result.post_id == "C_99"


async def test_upvote():
    payload = {"data": {"addReaction": {"subject": {"id": "D_1"}}}}
    async with GitHubDiscussions(token="token", repositories=["openai/openai-python"]) as gh:
        gh.client.post = AsyncMock(return_value=_mock_response(payload))
        result = await gh.upvote("D_1")
        assert result.success is True
        assert result.post_id == "D_1"
