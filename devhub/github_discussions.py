"""GitHub Discussions adapter via the official GraphQL API."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx

from devhub.base import PlatformAdapter
from devhub.types import Comment, Post, PostResult, UserProfile

_BASE = "https://api.github.com"


class GitHubDiscussions(PlatformAdapter):
    """Async adapter for GitHub Discussions via GraphQL."""

    platform = "github_discussions"

    def __init__(
        self,
        token: str | None = None,
        repositories: list[str] | None = None,
        default_repo: str | None = None,
        category_id: str | None = None,
    ) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN", "")
        raw_repos = repositories or self._split_csv(os.getenv("GITHUB_DISCUSSIONS_REPOS", ""))
        self.repositories = [repo for repo in raw_repos if "/" in repo]
        self.default_repo = default_repo or os.getenv("GITHUB_DISCUSSIONS_DEFAULT_REPO", "")
        self.category_id = category_id or os.getenv("GITHUB_DISCUSSIONS_CATEGORY_ID", "")
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._client = httpx.AsyncClient(base_url=_BASE, headers=headers, timeout=30)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "GitHubDiscussions adapter not connected. "
                "Use `async with GitHubDiscussions() as gh:`"
            )
        return self._client

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("GITHUB_TOKEN") and os.getenv("GITHUB_DISCUSSIONS_REPOS"))

    @classmethod
    def setup_guide(cls) -> dict[str, Any]:
        return {
            "url": "https://github.com/settings/tokens",
            "steps": [
                "1. GitHub personal access token 생성 (classic 또는 fine-grained)",
                "2. public repository면 public_repo, private면 repo 권한 부여",
                "3. 읽을 저장소 목록을 owner/repo 형식으로 GITHUB_DISCUSSIONS_REPOS에 저장",
                "4. 글 작성까지 하려면 기본 저장소와 카테고리 ID를 추가로 설정",
            ],
            "required_keys": ["GITHUB_TOKEN", "GITHUB_DISCUSSIONS_REPOS"],
            "optional_keys": [
                "GITHUB_DISCUSSIONS_DEFAULT_REPO",
                "GITHUB_DISCUSSIONS_CATEGORY_ID",
                "GITHUB_USERNAME",
            ],
            "allowed_actions": ["comment", "post", "upvote"],
        }

    async def get_trending(self, *, limit: int = 20) -> list[Post]:
        posts: list[Post] = []
        per_repo = max(1, min(limit, 10))
        for repo in self.repositories:
            owner, name = repo.split("/", 1)
            data = await self._graphql(
                """
                query($owner: String!, $name: String!, $limit: Int!) {
                  repository(owner: $owner, name: $name) {
                    discussions(first: $limit, orderBy: {field: UPDATED_AT, direction: DESC}) {
                      nodes {
                        id
                        title
                        body
                        url
                        upvoteCount
                        comments { totalCount }
                        createdAt
                        author { login }
                        category { id name isAnswerable }
                      }
                    }
                  }
                }
                """,
                {"owner": owner, "name": name, "limit": per_repo},
            )
            discussions = data["repository"]["discussions"]["nodes"] if data["repository"] else []
            posts.extend(self._to_post(node, repo) for node in discussions)
        posts.sort(key=lambda p: p.likes, reverse=True)
        return posts[:limit]

    async def search(self, query: str, *, limit: int = 20) -> list[Post]:
        filters = " ".join(f"repo:{repo}" for repo in self.repositories)
        search_query = f"{query} is:public archived:false {filters} type:discussion".strip()
        data = await self._graphql(
            """
            query($query: String!, $limit: Int!) {
              search(query: $query, type: DISCUSSION, first: $limit) {
                nodes {
                  ... on Discussion {
                    id
                    title
                    body
                    url
                    upvoteCount
                    comments { totalCount }
                    createdAt
                    author { login }
                    repository { nameWithOwner }
                    category { id name isAnswerable }
                  }
                }
              }
            }
            """,
            {"query": search_query, "limit": limit},
        )
        nodes = [node for node in data["search"]["nodes"] if node]
        return [self._to_post(node, node["repository"]["nameWithOwner"]) for node in nodes]

    async def get_post(self, post_id: str) -> Post:
        data = await self._graphql(
            """
            query($id: ID!) {
              node(id: $id) {
                ... on Discussion {
                  id
                  title
                  body
                  url
                  upvoteCount
                  comments { totalCount }
                  createdAt
                  author { login }
                  repository { nameWithOwner }
                  category { id name isAnswerable }
                }
              }
            }
            """,
            {"id": post_id},
        )
        node = data["node"]
        if node is None:
            raise ValueError(f"Discussion not found: {post_id}")
        return self._to_post(node, node["repository"]["nameWithOwner"])

    async def get_comments(self, post_id: str, *, limit: int = 50) -> list[Comment]:
        data = await self._graphql(
            """
            query($id: ID!, $limit: Int!) {
              node(id: $id) {
                ... on Discussion {
                  comments(first: $limit) {
                    nodes {
                      id
                      body
                      createdAt
                      upvoteCount
                      author { login }
                      replies(first: 20) {
                        nodes {
                          id
                          body
                          createdAt
                          upvoteCount
                          author { login }
                        }
                      }
                    }
                  }
                }
              }
            }
            """,
            {"id": post_id, "limit": limit},
        )
        discussion = data["node"]
        if discussion is None:
            return []

        comments: list[Comment] = []
        for node in discussion["comments"]["nodes"]:
            comments.append(self._to_comment(node, post_id))
            for reply in node.get("replies", {}).get("nodes", []):
                comments.append(self._to_comment(reply, post_id, parent_id=node["id"]))
        return comments[:limit]

    async def get_user(self, username: str) -> UserProfile:
        resp = await self.client.get(f"/users/{username}")
        resp.raise_for_status()
        data = resp.json()
        return UserProfile(
            id=str(data["id"]),
            platform=self.platform,
            username=data.get("login", username),
            name=data.get("name", ""),
            bio=data.get("bio", ""),
            url=data.get("html_url", ""),
            followers=data.get("followers", 0),
            raw=data,
        )

    async def write_post(
        self,
        title: str,
        body: str,
        *,
        tags: list[str] | None = None,
        **kwargs: object,
    ) -> PostResult:
        repo = str(kwargs.get("repository", self.default_repo))
        category_id = str(kwargs.get("category_id", self.category_id))
        if not repo:
            return PostResult(
                success=False,
                platform=self.platform,
                error=(
                    "GitHub Discussions write requires "
                    "GITHUB_DISCUSSIONS_DEFAULT_REPO or repository=..."
                ),
            )
        if not category_id:
            return PostResult(
                success=False,
                platform=self.platform,
                error=(
                    "GitHub Discussions write requires "
                    "GITHUB_DISCUSSIONS_CATEGORY_ID or category_id=..."
                ),
            )
        owner, name = repo.split("/", 1)
        repository_id = await self._get_repository_id(owner, name)
        payload = await self._graphql(
            """
            mutation($repositoryId: ID!, $categoryId: ID!, $title: String!, $body: String!) {
              createDiscussion(
                input: {
                  repositoryId: $repositoryId,
                  categoryId: $categoryId,
                  title: $title,
                  body: $body
                }
              ) {
                discussion { id url }
              }
            }
            """,
            {
                "repositoryId": repository_id,
                "categoryId": category_id,
                "title": title,
                "body": body,
            },
        )
        discussion = payload["createDiscussion"]["discussion"]
        return PostResult(
            success=True,
            platform=self.platform,
            post_id=discussion["id"],
            url=discussion["url"],
        )

    async def write_comment(self, post_id: str, body: str) -> PostResult:
        payload = await self._graphql(
            """
            mutation($discussionId: ID!, $body: String!) {
              addDiscussionComment(input: {discussionId: $discussionId, body: $body}) {
                comment { id url }
              }
            }
            """,
            {"discussionId": post_id, "body": body},
        )
        comment = payload["addDiscussionComment"]["comment"]
        return PostResult(
            success=True,
            platform=self.platform,
            post_id=comment["id"],
            url=comment.get("url", ""),
        )

    async def upvote(self, post_id: str) -> PostResult:
        payload = await self._graphql(
            """
            mutation($subjectId: ID!) {
              addReaction(input: {subjectId: $subjectId, content: THUMBS_UP}) {
                reaction { content }
                subject { id }
              }
            }
            """,
            {"subjectId": post_id},
        )
        return PostResult(
            success=True,
            platform=self.platform,
            post_id=payload["addReaction"]["subject"]["id"],
        )

    async def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        resp = await self.client.post("/graphql", json={"query": query, "variables": variables})
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            messages = ", ".join(
                error.get("message", "unknown error") for error in payload["errors"]
            )
            raise ValueError(messages)
        return payload["data"]

    async def _get_repository_id(self, owner: str, name: str) -> str:
        data = await self._graphql(
            """
            query($owner: String!, $name: String!) {
              repository(owner: $owner, name: $name) { id }
            }
            """,
            {"owner": owner, "name": name},
        )
        repository = data["repository"]
        if repository is None:
            raise ValueError(f"Repository not found: {owner}/{name}")
        return repository["id"]

    def _to_post(self, data: dict[str, Any], repo: str) -> Post:
        return Post(
            id=data["id"],
            platform=self.platform,
            title=data.get("title", ""),
            url=data.get("url", ""),
            body=data.get("body", ""),
            author=(data.get("author") or {}).get("login", ""),
            tags=[data["category"]["name"]] if data.get("category") else [repo],
            likes=data.get("upvoteCount", 0),
            comments_count=(data.get("comments") or {}).get("totalCount", 0),
            published_at=self._parse_datetime(data.get("createdAt")),
            raw={"repository": repo, "category": data.get("category", {})},
        )

    def _to_comment(
        self,
        data: dict[str, Any],
        post_id: str,
        parent_id: str | None = None,
    ) -> Comment:
        return Comment(
            id=data["id"],
            platform=self.platform,
            body=data.get("body", ""),
            author=(data.get("author") or {}).get("login", ""),
            post_id=post_id,
            parent_id=parent_id,
            likes=data.get("upvoteCount", 0),
            created_at=self._parse_datetime(data.get("createdAt")),
            raw=data,
        )

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _split_csv(value: str) -> list[str]:
        return [part.strip() for part in value.split(",") if part.strip()]
