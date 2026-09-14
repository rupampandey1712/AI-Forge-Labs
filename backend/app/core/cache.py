"""Cache with graceful degradation.

WHY Redis *and* an in-process fallback: the game must run on a laptop with no
infrastructure, but the caching lessons (and the "Redis is unavailable"
incident in the War Room) need a real Redis path to exist. The interface is
identical, so nothing above this file knows which is active.

WHY a cache is safe to lose: everything stored here is derivable from the
database. If Redis vanishes mid-request we serve a slower but correct response.
Any cache whose loss changes *correctness* is not a cache — it is a database
with no durability, and that is the distinction the Architecture missions probe.
"""

from __future__ import annotations

import contextlib
import json
import time
from functools import lru_cache
from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class InMemoryCache:
    """TTL dict. Per-process, so it is wrong under multiple workers — which is
    exactly why it is the *fallback* and Redis is the real answer."""

    def __init__(self, max_entries: int = 5000) -> None:
        self._data: dict[str, tuple[float, str]] = {}
        self._max = max_entries

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at and expires_at < time.time():
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        if len(self._data) >= self._max:
            # Crude eviction: drop the oldest tenth. Good enough for a fallback;
            # a real LRU here would be optimising the path we do not want used.
            for stale in sorted(self._data, key=lambda k: self._data[k][0])[: self._max // 10]:
                self._data.pop(stale, None)
        self._data[key] = (time.time() + ttl_seconds if ttl_seconds else 0.0, value)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._data.pop(key, None)

    async def clear_prefix(self, prefix: str) -> int:
        doomed = [k for k in self._data if k.startswith(prefix)]
        for key in doomed:
            self._data.pop(key, None)
        return len(doomed)

    async def close(self) -> None:
        self._data.clear()


class RedisCache:
    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
        self._healthy = True

    async def ping(self) -> bool:
        try:
            await self._redis.ping()
            self._healthy = True
        except Exception:
            self._healthy = False
        return self._healthy

    async def get(self, key: str) -> str | None:
        try:
            return await self._redis.get(key)
        except Exception as exc:
            log.warning("cache.get_failed", key=key, error=str(exc)[:120])
            return None  # a cache miss, not an error

    async def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        try:
            await self._redis.set(key, value, ex=ttl_seconds or None)
        except Exception as exc:
            log.warning("cache.set_failed", key=key, error=str(exc)[:120])

    async def delete(self, *keys: str) -> None:
        try:
            if keys:
                await self._redis.delete(*keys)
        except Exception as exc:
            log.warning("cache.delete_failed", error=str(exc)[:120])

    async def clear_prefix(self, prefix: str) -> int:
        """SCAN, never KEYS.

        ``KEYS *`` blocks the single-threaded Redis event loop for the whole
        scan — a genuine, famous production outage, and one of the Debugging
        Dungeon scenarios.
        """
        removed = 0
        try:
            async for key in self._redis.scan_iter(match=f"{prefix}*", count=200):
                await self._redis.delete(key)
                removed += 1
        except Exception as exc:
            log.warning("cache.clear_prefix_failed", error=str(exc)[:120])
        return removed

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._redis.aclose()


Cache = RedisCache | InMemoryCache


def build_cache(cfg: Settings | None = None) -> Cache:
    cfg = cfg or get_settings()
    if not cfg.cache_enabled or not cfg.redis_url:
        return InMemoryCache()
    try:
        return RedisCache(cfg.redis_url)
    except Exception as exc:
        log.warning("cache.redis_unavailable", error=str(exc)[:200])
        return InMemoryCache()


@lru_cache(maxsize=1)
def get_cache() -> Cache:
    return build_cache()


async def cached_json(key: str, ttl_seconds: int, producer, *, cache: Cache | None = None) -> Any:
    """Read-through JSON cache helper."""
    cache = cache or get_cache()
    raw = await cache.get(key)
    if raw is not None:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            await cache.delete(key)
    value = await producer()
    await cache.set(key, json.dumps(value, default=str), ttl_seconds)
    return value
