<div align="center">

# devhub

**Unified async Python client for developer communities.**

Dev.to · Bluesky · Twitter/X · Reddit — one interface, one data model.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

English · [한국어](README-ko.md)

</div>

---

## Why devhub?

You want to post your project on Dev.to, share it on Bluesky, discuss it on Reddit, and tweet about it. That means learning four different SDKs:

```python
# Twitter — OAuth 1.0a, tweepy, Status objects
client = tweepy.Client(bearer_token="...")
tweets = client.search_recent_tweets("MCP server", max_results=10)
for tweet in tweets.data:
    print(tweet.text)  # tweet.text, tweet.public_metrics["like_count"]

# Reddit — OAuth2, asyncpraw, Submission objects
reddit = asyncpraw.Reddit(client_id="...", client_secret="...", user_agent="...")
subreddit = await reddit.subreddit("Python")
async for submission in subreddit.hot(limit=10):
    print(submission.title)  # submission.score, submission.num_comments

# Bluesky — AT Protocol, atproto, dict responses
client = AtClient()
client.login("handle", "app-password")
feed = client.get_timeline(limit=10)
for item in feed.feed:
    print(item.post.record.text)  # completely different structure

# Dev.to — REST API, no official SDK, raw httpx
resp = await httpx.get("https://dev.to/api/articles", params={"top": 7})
for article in resp.json():
    print(article["title"])  # article["positive_reactions_count"], article["comments_count"]
```

Four SDKs. Four auth flows. Four data shapes. Four ways to say "get trending posts."

**devhub makes them all the same:**

```python
from devhub import Hub

async with Hub.from_env() as hub:
    posts = await hub.get_trending(limit=10)

    for post in posts:
        print(f"[{post.platform}] {post.title} ({post.score} likes, {post.comment_count} comments)")
        # [reddit] Show HN: I built a graph-based tool search (342 likes, 87 comments)
        # [devto] Building MCP Servers in Python (156 likes, 23 comments)
        # [bluesky] just shipped v2 of my cli tool... (89 likes, 12 comments)
```

Same `Post` object. Same `.score`. Same `.comment_count`. Regardless of platform.

## Install

```bash
pip install "devhub[all]"          # All platforms

pip install "devhub[devto]"        # Dev.to only (no extra deps, uses httpx)
pip install "devhub[bluesky]"      # + atproto
pip install "devhub[twitter]"      # + tweepy
pip install "devhub[reddit]"       # + asyncpraw
```

## Quick Start

### 1. Set up API keys

Copy `.env.example` to `.env` and fill in the platforms you want:

```env
# Dev.to — https://dev.to/settings/extensions
DEVTO_API_KEY=your_key

# Bluesky — https://bsky.app/settings → App Passwords
BLUESKY_HANDLE=yourname.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx

# Twitter/X — https://developer.x.com/en/portal/dashboard
TWITTER_API_KEY=...
TWITTER_API_SECRET=...
TWITTER_ACCESS_TOKEN=...
TWITTER_ACCESS_SECRET=...

# Reddit — https://www.reddit.com/prefs/apps (script type)
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USERNAME=...
REDDIT_PASSWORD=...
```

**Only set the platforms you use.** devhub activates platforms with valid keys and silently skips the rest.

### 2. Search across platforms

```python
import asyncio
from devhub import Hub

async def main():
    async with Hub.from_env() as hub:
        # Which platforms are active?
        print(hub.platforms)  # ["devto", "reddit", "bluesky"]

        # Search all active platforms in parallel
        posts = await hub.search("MCP server python", limit=5)

        for post in posts:
            print(f"[{post.platform}] {post.title}")
            print(f"  {post.url}")
            print(f"  score={post.score}, comments={post.comment_count}")
            print()

asyncio.run(main())
```

Output:
```
[reddit] Best MCP servers for developer productivity?
  https://reddit.com/r/MCP/comments/abc123
  score=234, comments=67

[devto] How I Built an MCP Server for My University Portal
  https://dev.to/sonaiengine/how-i-built-an-mcp-server-1a2b
  score=89, comments=12

[bluesky] anyone using MCP servers with claude? been experimenting...
  https://bsky.app/profile/dev.bsky.social/post/xyz789
  score=45, comments=8
```

### 3. Use a single platform

```python
from devhub import DevTo

async with DevTo(api_key="your_key") as devto:
    # Read
    trending = await devto.get_trending(limit=10)
    results = await devto.search("fastapi tutorial", limit=5)
    post = await devto.get_post("1234567")
    comments = await devto.get_comments("1234567")

    # Write
    result = await devto.write_post(
        title="TIL: Building Stateful MCP Servers",
        body="Today I learned that MCP servers can maintain state...",
        tags=["python", "mcp", "til"],
    )
    print(result.url)  # https://dev.to/yourname/til-building-stateful-mcp-servers-abc

    # Comment
    result = await devto.write_comment(
        post_id="1234567",
        body="Great writeup! I've been doing something similar with FastMCP.",
    )
```

### 4. Cross-post

```python
from devhub import Hub, Post

async with Hub.from_env() as hub:
    post = Post(
        title="Building MCP Servers in Python",
        body="A practical guide to building MCP servers...",
        tags=["python", "mcp", "ai"],
    )

    results = await hub.publish(post, platforms=["devto", "bluesky"])

    for platform, result in results.items():
        if result.success:
            print(f"[{platform}] Published: {result.url}")
        else:
            print(f"[{platform}] Failed: {result.error}")
```

## Data Models

Every platform returns the same types:

```python
from devhub import Post, Comment, PostResult, UserProfile, RateLimit

# ── Post ──────────────────────────────────────
post = Post(
    id="abc123",                    # Platform-specific ID
    platform="reddit",              # "devto" | "bluesky" | "twitter" | "reddit"
    title="Best MCP servers?",      # Empty for Twitter/Bluesky
    body="What MCP servers...",     # Full text content
    author="username",
    url="https://reddit.com/...",
    tags=["mcp", "python"],
    score=234,                      # Upvotes / likes / reactions
    comment_count=67,
    created_at=datetime(2026, 3, 1),
    raw={...},                      # Original platform response (always preserved)
)

# ── Comment ───────────────────────────────────
comment = Comment(
    id="comment_456",
    platform="reddit",
    post_id="abc123",
    body="Try graph-tool-call, it solved this for me.",
    author="helpful_dev",
    parent_id="",                   # Empty = top-level, filled = nested reply
    score=42,
    created_at=datetime(2026, 3, 1),
)

# ── PostResult (write operations) ─────────────
result = PostResult(
    success=True,
    platform="devto",
    url="https://dev.to/you/your-post-abc",
    post_id="7890",
    error="",                       # Empty on success
)

# ── RateLimit ─────────────────────────────────
limit = RateLimit(
    platform="reddit",
    remaining=97,                   # API calls left
    limit=100,                      # Max per window
    reset_at=datetime(2026, 3, 1, 12, 10),
)
```

## Platform-Specific Features

Each platform has conventions that devhub respects:

```python
# Reddit — subreddit is required for posts
await reddit.write_post(title="...", body="...", subreddit="r/Python")

# Dev.to — tags are important for discoverability
await devto.write_post(title="...", body="...", tags=["python", "webdev", "tutorial"])

# Twitter — respects 280-char limit, auto-truncates body
await twitter.write_post(body="Check out this MCP server approach...")

# Bluesky — supports thread creation
await bluesky.write_post(body="Long post as a thread...", thread=True)
```

Platform-specific parameters go through `**kwargs`. Common parameters (`title`, `body`, `tags`) are standardized.

## Adding a New Platform

Implement `PlatformAdapter` and register it:

```python
from devhub.base import PlatformAdapter
from devhub.types import Post, Comment, PostResult

class Mastodon(PlatformAdapter):
    name = "mastodon"

    def is_configured(self) -> bool:
        return bool(os.getenv("MASTODON_ACCESS_TOKEN"))

    async def get_trending(self, limit=20) -> list[Post]:
        # Your implementation here
        ...

    async def search(self, query, limit=10) -> list[Post]: ...
    async def get_post(self, post_id) -> Post: ...
    async def get_comments(self, post_id) -> list[Comment]: ...
    async def write_post(self, **kwargs) -> PostResult: ...
    async def write_comment(self, post_id, body) -> PostResult: ...
    async def upvote(self, post_id) -> PostResult: ...
```

Once registered in the adapter registry, it works with `Hub` automatically — `hub.search()` will include Mastodon results, `hub.publish()` can target it.

## Architecture

```
devhub/
├── __init__.py      # Public API exports
├── types.py         # Post, Comment, UserProfile, PostResult, RateLimit
├── hub.py           # Hub class — multi-platform orchestrator
├── base.py          # PlatformAdapter ABC
├── devto.py         # Dev.to (httpx direct — no official SDK exists)
├── bluesky.py       # Bluesky (atproto)
├── twitter.py       # Twitter/X (tweepy)
└── reddit.py        # Reddit (asyncpraw)
```

### Design Decisions

- **Async-first**: All I/O is `async/await`. No sync wrappers — keeps the API clean and performant.
- **Adapter pattern**: Every platform implements the same ABC. Adding a platform means one file, zero changes to existing code.
- **`raw` field on every model**: Platform responses are always preserved. When the unified model doesn't cover a field, you can always fall back to `post.raw["platform_specific_field"]`.
- **Environment-based activation**: No complex config files. Set env vars for the platforms you want. Miss one? That platform is silently skipped.
- **No global state**: Each adapter instance manages its own connection. `Hub` uses `asyncio.gather()` for parallel platform calls.

## Use Cases

- **Cross-posting bots** — publish to Dev.to + Bluesky + Twitter from one script
- **Social dashboards** — aggregate trending posts from all developer communities
- **MCP servers** — [gwanjong-mcp](https://github.com/SonAIengine/gwanjong-mcp) uses devhub as its platform layer
- **Analytics** — track engagement across platforms with a unified data model
- **Community engagement** — search all platforms for discussions about your project

## Development

```bash
git clone https://github.com/SonAIengine/devhub.git
cd devhub
pip install -e ".[all,dev]"

pytest                    # Tests
mypy devhub/              # Type check
ruff check devhub/        # Lint
```

## License

[MIT](LICENSE)
