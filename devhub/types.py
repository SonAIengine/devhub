"""Unified data models for all platform adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Post:
    """Platform-agnostic post representation."""

    id: str
    platform: str
    title: str
    url: str
    body: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)
    likes: int = 0
    comments_count: int = 0
    published_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Comment:
    """Platform-agnostic comment representation."""

    id: str
    platform: str
    body: str
    author: str = ""
    post_id: str = ""
    parent_id: str | None = None
    likes: int = 0
    created_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class UserProfile:
    """Platform-agnostic user profile."""

    id: str
    platform: str
    username: str
    name: str = ""
    bio: str = ""
    url: str = ""
    followers: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class PostResult:
    """Result of a write operation (post/comment/upvote)."""

    success: bool
    platform: str
    post_id: str = ""
    url: str = ""
    error: str = ""


@dataclass(frozen=True)
class RateLimit:
    """Rate limit info returned by a platform."""

    platform: str
    limit: int = 0
    remaining: int = 0
    reset_at: datetime | None = None
