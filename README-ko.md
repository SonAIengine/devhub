<div align="center">

# devhub

**개발자 커뮤니티를 위한 통합 비동기 Python 클라이언트**

Dev.to · Bluesky · Twitter/X · Reddit — 하나의 인터페이스, 하나의 데이터 모델.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

[English](README.md) · 한국어

</div>

---

## 왜 devhub인가?

프로젝트를 Dev.to에 올리고, Bluesky에 공유하고, Reddit에서 토론하고, 트윗하고 싶다면 — 네 개의 SDK를 각각 배워야 합니다:

```python
# Twitter — OAuth 1.0a, tweepy, Status 객체
client = tweepy.Client(bearer_token="...")
tweets = client.search_recent_tweets("MCP server", max_results=10)
for tweet in tweets.data:
    print(tweet.text)  # tweet.public_metrics["like_count"]

# Reddit — OAuth2, asyncpraw, Submission 객체
reddit = asyncpraw.Reddit(client_id="...", client_secret="...", user_agent="...")
subreddit = await reddit.subreddit("Python")
async for submission in subreddit.hot(limit=10):
    print(submission.title)  # submission.score, submission.num_comments

# Bluesky — AT Protocol, atproto, dict 응답
client = AtClient()
client.login("handle", "app-password")
feed = client.get_timeline(limit=10)
for item in feed.feed:
    print(item.post.record.text)  # 완전히 다른 구조

# Dev.to — REST API, 공식 SDK 없음, httpx로 직접 호출
resp = await httpx.get("https://dev.to/api/articles", params={"top": 7})
for article in resp.json():
    print(article["title"])  # article["positive_reactions_count"]
```

SDK 4개. 인증 방식 4개. 데이터 형식 4개. "인기 글 가져오기" 방법 4개.

**devhub는 이걸 하나로 만듭니다:**

```python
from devhub import Hub

async with Hub.from_env() as hub:
    posts = await hub.get_trending(limit=10)

    for post in posts:
        print(f"[{post.platform}] {post.title} ({post.score}점, 댓글 {post.comment_count}개)")
        # [reddit] Show HN: I built a graph-based tool search (342점, 댓글 87개)
        # [devto] Building MCP Servers in Python (156점, 댓글 23개)
        # [bluesky] just shipped v2 of my cli tool... (89점, 댓글 12개)
```

어떤 플랫폼이든 같은 `Post` 객체. 같은 `.score`. 같은 `.comment_count`.

## 설치

```bash
pip install "devhub[all]"          # 전체 플랫폼

pip install "devhub[devto]"        # Dev.to만 (추가 의존성 없음, httpx 사용)
pip install "devhub[bluesky]"      # + atproto
pip install "devhub[twitter]"      # + twikit (읽기) + tweepy (쓰기)
pip install "devhub[twitter-read]" # + twikit만 (무료 읽기)
pip install "devhub[twitter-write]"# + tweepy만 (공식 쓰기)
pip install "devhub[reddit]"       # + asyncpraw
```

## 빠른 시작

### 1. API 키 설정

`.env.example`을 `.env`로 복사하고 사용할 플랫폼만 입력:

```env
# Dev.to — https://dev.to/settings/extensions
DEVTO_API_KEY=your_key

# Bluesky — https://bsky.app/settings → App Passwords
BLUESKY_HANDLE=yourname.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx

# Twitter/X 읽기 (twikit, 무료) — X 계정 로그인
TWITTER_USERNAME=...
TWITTER_EMAIL=...
TWITTER_PASSWORD=...

# Twitter/X 쓰기 (tweepy, 공식 API) — https://developer.x.com/en/portal/dashboard
TWITTER_API_KEY=...
TWITTER_API_SECRET=...
TWITTER_ACCESS_TOKEN=...
TWITTER_ACCESS_SECRET=...

# Reddit — https://www.reddit.com/prefs/apps (script 타입)
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USERNAME=...
REDDIT_PASSWORD=...
```

**사용하는 플랫폼만 설정하세요.** API 키가 있는 플랫폼만 활성화되고, 나머지는 에러 없이 건너뜁니다.

### 2. 멀티 플랫폼 검색

```python
import asyncio
from devhub import Hub

async def main():
    async with Hub.from_env() as hub:
        # 어떤 플랫폼이 활성화됐나?
        print(hub.platforms)  # ["devto", "reddit", "bluesky"]

        # 모든 활성 플랫폼에서 병렬 검색
        posts = await hub.search("MCP server python", limit=5)

        for post in posts:
            print(f"[{post.platform}] {post.title}")
            print(f"  {post.url}")
            print(f"  score={post.score}, comments={post.comment_count}")

asyncio.run(main())
```

출력:
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

### 3. 단일 플랫폼 사용

```python
from devhub import DevTo

async with DevTo(api_key="your_key") as devto:
    # 읽기
    trending = await devto.get_trending(limit=10)
    results = await devto.search("fastapi tutorial", limit=5)
    post = await devto.get_post("1234567")
    comments = await devto.get_comments("1234567")

    # 글 작성
    result = await devto.write_post(
        title="TIL: Stateful MCP 서버 만들기",
        body="오늘 MCP 서버에서 상태를 유지하는 방법을 배웠습니다...",
        tags=["python", "mcp", "til"],
    )
    print(result.url)  # https://dev.to/yourname/til-stateful-mcp-abc

    # 댓글
    result = await devto.write_comment(
        post_id="1234567",
        body="좋은 글이네요! 저도 FastMCP로 비슷한 거 만들어봤습니다.",
    )
```

### 4. 크로스포스팅

```python
from devhub import Hub, Post

async with Hub.from_env() as hub:
    post = Post(
        title="Python으로 MCP 서버 만들기",
        body="MCP 서버 구축 실전 가이드...",
        tags=["python", "mcp", "ai"],
    )

    results = await hub.publish(post, platforms=["devto", "bluesky"])

    for platform, result in results.items():
        if result.success:
            print(f"[{platform}] 발행 완료: {result.url}")
        else:
            print(f"[{platform}] 실패: {result.error}")
```

## 데이터 모델

모든 플랫폼이 같은 타입을 반환합니다:

```python
from devhub import Post, Comment, PostResult, UserProfile, RateLimit

# ── Post ──────────────────────────────────────
post.id                 # 플랫폼 내부 ID
post.platform           # "devto" | "bluesky" | "twitter" | "reddit"
post.title              # Twitter/Bluesky는 빈 문자열
post.body               # 본문
post.author             # 사용자명
post.url                # 퍼머링크
post.tags               # ["python", "mcp"]
post.score              # 추천수/좋아요
post.comment_count      # 댓글 수
post.created_at         # datetime
post.raw                # 플랫폼 원본 응답 (항상 보존)

# ── Comment ───────────────────────────────────
comment.id              # 댓글 ID
comment.post_id         # 소속 게시글 ID
comment.body            # 댓글 내용
comment.author          # 작성자
comment.parent_id       # 빈 문자열 = 최상위, 값 있음 = 대댓글
comment.score           # 추천수

# ── PostResult (쓰기 결과) ────────────────────
result.success          # True/False
result.url              # 생성된 콘텐츠 URL
result.post_id          # 생성된 콘텐츠 ID
result.error            # 실패 시 에러 메시지

# ── RateLimit ─────────────────────────────────
limit.remaining         # 남은 API 호출 수
limit.limit             # 윈도우당 최대 호출 수
limit.reset_at          # 리셋 시각
```

## 플랫폼별 특성

devhub는 각 플랫폼의 고유 규칙을 존중합니다:

```python
# Reddit — subreddit 지정 필수
await reddit.write_post(title="...", body="...", subreddit="r/Python")

# Dev.to — 태그가 노출에 중요
await devto.write_post(title="...", body="...", tags=["python", "webdev", "tutorial"])

# Twitter — 하이브리드: twikit으로 무료 읽기, tweepy로 공식 쓰기
# 읽기: API 키 없이 가능 (X 계정 로그인 사용)
trending = await twitter.get_trending(limit=10)
# 쓰기: 공식 API 키 필요, 280자 제한 적용
await twitter.write_post(body="이 MCP 서버 접근법 한번 봐보세요...")

# Bluesky — 스레드 지원
await bluesky.write_post(body="긴 글을 스레드로...", thread=True)
```

플랫폼 고유 파라미터는 `**kwargs`로 전달. 공통 파라미터(`title`, `body`, `tags`)는 표준화.

## 새 플랫폼 추가

`PlatformAdapter`를 구현하고 레지스트리에 등록:

```python
from devhub.base import PlatformAdapter
from devhub.types import Post, Comment, PostResult

class Mastodon(PlatformAdapter):
    name = "mastodon"

    def is_configured(self) -> bool:
        return bool(os.getenv("MASTODON_ACCESS_TOKEN"))

    async def get_trending(self, limit=20) -> list[Post]: ...
    async def search(self, query, limit=10) -> list[Post]: ...
    async def get_post(self, post_id) -> Post: ...
    async def get_comments(self, post_id) -> list[Comment]: ...
    async def write_post(self, **kwargs) -> PostResult: ...
    async def write_comment(self, post_id, body) -> PostResult: ...
    async def upvote(self, post_id) -> PostResult: ...
```

등록하면 `Hub`에서 자동으로 사용 가능 — `hub.search()`에 Mastodon 결과 포함, `hub.publish()`로 게시 가능.

## 아키텍처

```
devhub/
├── __init__.py      # Public API exports
├── types.py         # Post, Comment, UserProfile, PostResult, RateLimit
├── hub.py           # Hub — 멀티 플랫폼 오케스트레이터
├── base.py          # PlatformAdapter ABC
├── devto.py         # Dev.to (httpx 직접 — 공식 SDK 없음)
├── bluesky.py       # Bluesky (atproto)
├── twitter.py       # Twitter/X (twikit 읽기 + tweepy 쓰기 하이브리드)
└── reddit.py        # Reddit (asyncpraw)
```

### 설계 원칙

- **Async-first**: 모든 I/O가 `async/await`. Sync wrapper 없음.
- **Adapter 패턴**: 모든 플랫폼이 같은 ABC 구현. 새 플랫폼 = 파일 하나, 기존 코드 변경 없음.
- **`raw` 필드**: 플랫폼 원본 응답 항상 보존. 통합 모델에 없는 필드가 필요하면 `post.raw["필드명"]`으로 접근.
- **환경변수 기반 활성화**: 복잡한 설정 파일 없음. 환경변수 설정된 플랫폼만 활성화.
- **글로벌 상태 없음**: 각 어댑터가 자체 연결 관리. `Hub`는 `asyncio.gather()`로 병렬 호출.

## 활용 사례

- **크로스포스팅 봇** — Dev.to + Bluesky + Twitter에 한 번에 게시
- **소셜 대시보드** — 개발자 커뮤니티 트렌딩 게시글 통합 조회
- **MCP 서버** — [gwanjong-mcp](https://github.com/SonAIengine/gwanjong-mcp)가 devhub를 플랫폼 레이어로 사용
- **분석** — 통합 데이터 모델로 플랫폼 간 참여도 추적
- **커뮤니티 참여** — 내 프로젝트 관련 토론을 모든 플랫폼에서 검색

## 기존 대안과의 비교

| | [Ayrshare](https://www.ayrshare.com/) | [barkr](https://github.com/aitorres/barkr) | **devhub** |
|---|---|---|---|
| 가격 | 유료 SaaS | 무료 | **무료** |
| Dev.to | X | X | **O** |
| Reddit 읽기/쓰기 | 쓰기만 | X | **O** |
| Bluesky | O | O | **O** |
| 트렌딩/검색 (읽기) | X | X | **O** |
| 전체 Async | X | X | **O** |
| 통합 데이터 모델 | 플랫폼 원본 | 텍스트만 | **Post/Comment 통합** |
| 오픈소스 | X | O | **O** |

## 개발

```bash
git clone https://github.com/SonAIengine/devhub-social.git
cd devhub
pip install -e ".[all,dev]"

pytest                    # 테스트
mypy devhub/              # 타입 체크
ruff check devhub/        # 린트
```

## 라이선스

[MIT](LICENSE)
