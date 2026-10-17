"""Timeouts, limited retries and a circuit breaker for direct service-to-service calls.

These live in the template instead of a service mesh (see the scope exclusions).
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx

log = logging.getLogger(__name__)
T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    pass


class CircuitBreaker:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, name: str, *, failure_threshold: int = 5, reset_timeout: float = 30.0, clock=time.monotonic):
        self.name = name
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at = 0.0
        self._state = self.CLOSED

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == self.OPEN and self._clock() - self._opened_at >= self._reset_timeout:
                self._state = self.HALF_OPEN
            return self._state

    def call(self, fn: Callable[[], T]) -> T:
        if self.state == self.OPEN:
            raise CircuitOpenError(f"circuit '{self.name}' is open")
        try:
            result = fn()
        except Exception:
            self._record_failure()
            raise
        self._record_success()
        return result

    def _record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == self.HALF_OPEN or self._failures >= self._failure_threshold:
                if self._state != self.OPEN:
                    log.warning("circuit '%s' opened after %d failures", self.name, self._failures)
                self._state = self.OPEN
                self._opened_at = self._clock()

    def _record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state = self.CLOSED


class RetryableError(RuntimeError):
    pass


def retry(fn: Callable[[], T], *, attempts: int = 3, base_delay: float = 0.1, retry_on=(RetryableError,)) -> T:
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retry_on:
            if attempt == attempts:
                raise
            time.sleep(base_delay * (2 ** (attempt - 1)) * (0.5 + random.random()))  # noqa: S311 - jitter, not crypto
    raise AssertionError("unreachable")


class ResilientClient:
    """httpx client with a timeout, retries on transient failures and a circuit breaker."""

    def __init__(
        self,
        base_url: str,
        *,
        name: str,
        timeout: float = 2.0,
        attempts: int = 3,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self._client = httpx.Client(base_url=base_url, timeout=timeout, headers=headers, transport=transport)
        self._attempts = attempts
        self.breaker = CircuitBreaker(name, failure_threshold=failure_threshold, reset_timeout=reset_timeout)

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        def once() -> httpx.Response:
            try:
                response = self._client.request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise RetryableError(str(exc)) from exc
            if response.status_code >= 500:
                raise RetryableError(f"upstream returned {response.status_code}")
            return response

        return self.breaker.call(lambda: retry(once, attempts=self._attempts))

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def close(self) -> None:
        self._client.close()
