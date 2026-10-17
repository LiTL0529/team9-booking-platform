"""Cache for popular availability searches (ElastiCache Redis in AWS).

Keys embed a per-date generation number. Any event touching a date bumps its generation,
which makes every cached search for that date unreachable at once; old keys expire by TTL.
If Redis is slow or down the circuit opens and searches go straight to the database.
"""

from __future__ import annotations

import logging

from platform_common.resilience import CircuitBreaker, CircuitOpenError

log = logging.getLogger(__name__)


class AvailabilityCache:
    def __init__(self, url: str | None, ttl_seconds: int = 30):
        self._ttl = ttl_seconds
        self._redis = None
        self._breaker = CircuitBreaker("redis", failure_threshold=3, reset_timeout=10)
        if url:
            import redis

            self._redis = redis.Redis.from_url(url, socket_timeout=0.2, socket_connect_timeout=0.2)

    @property
    def enabled(self) -> bool:
        return self._redis is not None

    def _call(self, fn):
        if self._redis is None:
            return None
        try:
            return self._breaker.call(fn)
        except CircuitOpenError:
            return None
        except Exception:  # noqa: BLE001 - the cache must never break a search
            log.warning("redis unavailable; bypassing cache", exc_info=True)
            return None

    def _key(self, day: str, generation: int, parts: tuple) -> str:
        return f"avail:{day}:g{generation}:" + ":".join(str(p or "*") for p in parts)

    def get(self, day: str, parts: tuple) -> tuple[str, bytes | None] | tuple[None, None]:
        """Returns (key, cached JSON bytes or None). Bytes are served as-is, without re-serialising."""
        def lookup():
            generation = int(self._redis.get(f"avail:gen:{day}") or 0)
            key = self._key(day, generation, parts)
            return key, self._redis.get(key)

        result = self._call(lookup)
        return result if result else (None, None)

    def put(self, key: str | None, value: bytes) -> None:
        if key:
            self._call(lambda: self._redis.set(key, value, ex=self._ttl))

    def invalidate(self, day: str) -> None:
        self._call(lambda: self._redis.incr(f"avail:gen:{day}"))
