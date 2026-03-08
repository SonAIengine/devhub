"""Platform adapter registry — built-in + entry_points plugin discovery."""

from __future__ import annotations

import importlib.metadata
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devhub.base import PlatformAdapter

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "devhub.adapters"

# built-in adapter paths (lazy import)
_BUILTINS: dict[str, str] = {
    "devto": "devhub.devto:DevTo",
    "bluesky": "devhub.bluesky:Bluesky",
    "twitter": "devhub.twitter:Twitter",
    "reddit": "devhub.reddit:Reddit",
}

_cache: dict[str, type[PlatformAdapter]] | None = None


def _load_class(dotted: str) -> type[PlatformAdapter]:
    """'module.path:ClassName' 형식에서 클래스를 로드."""
    module_path, _, class_name = dotted.partition(":")
    module = __import__(module_path, fromlist=[class_name])
    return getattr(module, class_name)


def get_adapter_classes() -> dict[str, type[PlatformAdapter]]:
    """모든 어댑터 클래스 반환 (built-in + entry_points). 캐싱됨."""
    global _cache
    if _cache is not None:
        return _cache

    registry: dict[str, type[PlatformAdapter]] = {}

    # 1. built-in adapters
    for name, dotted in _BUILTINS.items():
        try:
            registry[name] = _load_class(dotted)
        except Exception:
            logger.debug("built-in adapter %s 로드 실패", name, exc_info=True)

    # 2. entry_points plugins
    try:
        eps = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        # Python 3.9 fallback
        eps = importlib.metadata.entry_points().get(ENTRY_POINT_GROUP, [])

    for ep in eps:
        try:
            cls = ep.load()
            registry[ep.name] = cls
        except Exception:
            logger.warning("plugin %s 로드 실패", ep.name, exc_info=True)

    _cache = registry
    return registry


def get_adapter_class(platform: str) -> type[PlatformAdapter]:
    """특정 플랫폼의 어댑터 클래스 반환. 없으면 KeyError."""
    classes = get_adapter_classes()
    if platform not in classes:
        raise KeyError(
            f"'{platform}' 어댑터 없음. 사용 가능: {list(classes.keys())}"
        )
    return classes[platform]


def get_configured_adapters() -> list[PlatformAdapter]:
    """환경변수가 설정된 어댑터만 인스턴스화하여 반환."""
    adapters = []
    for name, cls in get_adapter_classes().items():
        try:
            if cls.is_configured():
                adapters.append(cls())
        except Exception:
            logger.debug("%s is_configured 체크 실패", name, exc_info=True)
    return adapters


def clear_cache() -> None:
    """레지스트리 캐시 초기화 (테스트용)."""
    global _cache
    _cache = None
