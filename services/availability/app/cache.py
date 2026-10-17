"""Cache for popular availability searches (ElastiCache Redis in AWS).

Two kinds of entries, chosen so that the steady stream of bookings does not keep emptying the cache:

* Searches for one merchant embed a generation number per (date, merchant). An event for that
  merchant and date bumps it, so those searches are fresh right after a change, while other
  merchants' cached searches are untouched.
* Searches across all merchants change with every booking anywhere, so they are not invalidated;
  they live for a few seconds only. This is the bounded staleness the read model already accepts:
  the Booking Service stays the authority and answers 409 if a customer picks a slot just taken.

If Redis is slow or down the circuit opens and searches go straight to the database.
"""

from __future__ import annotations

import logging

from platform_common.resilience import CircuitBreaker, CircuitOpenError

log = logging.getLogger(__name__)
ALL = "all"


class AvailabilityCache:
    def __init__(self, url: str | None, ttl_seconds: int = 30, cross_merchant_ttl_seconds: int = 5):
        self._ttl = ttl_seconds
        self._cross_ttl = cross_merchant_ttl_seconds
        self._redis = None
        self._breaker = CircuitBreaker("redis", failure_threshold=3, reset_timeout=10)
        if url:
            import redis

            self._redis = redis.Redis.from_url(
                # TLS handshakes on a busy 0.25 vCPU task can exceed 200 ms; reads on a warm connection stay fast
                url, socket_timeout=0.5, socket_connect_timeout=1.0, health_check_interval=30
            )

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

    @staticmethod
    def _suffix(parts: tuple) -> str:
        return ":".join(str(p if p is not None else "*") for p in parts)

    def get(self, day: str, merchant_id: object | None, parts: tuple) -> tuple[str, bytes | None] | tuple[None, None]:
        """Returns (key, cached JSON bytes or None). Bytes are served as-is, without re-serialising."""
        if merchant_id is None:
            key = f"avail:{day}:{ALL}:{self._suffix(parts)}"
            result = self._call(lambda: (key, self._redis.get(key)))
        else:
            def lookup():
                generation = int(self._redis.get(f"avail:gen:{day}:{merchant_id}") or 0)
                key = f"avail:{day}:{merchant_id}:g{generation}:{self._suffix(parts)}"
                return key, self._redis.get(key)

            result = self._call(lookup)
        return result if result else (None, None)

    def put(self, key: str | None, value: bytes) -> None:
        if key:
            ttl = self._cross_ttl if f":{ALL}:" in key else self._ttl
            self._call(lambda: self._redis.set(key, value, ex=ttl))

    def invalidate(self, day: str, merchant_id: object) -> None:
        self._call(lambda: self._redis.incr(f"avail:gen:{day}:{merchant_id}"))
