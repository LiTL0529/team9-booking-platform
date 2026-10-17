import httpx
import pytest

from platform_common.resilience import CircuitBreaker, CircuitOpenError, ResilientClient, RetryableError, retry


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def failing():
    raise ValueError("boom")


def test_breaker_opens_after_threshold_and_half_opens_after_timeout():
    clock = FakeClock()
    breaker = CircuitBreaker("x", failure_threshold=2, reset_timeout=10, clock=clock)
    for _ in range(2):
        with pytest.raises(ValueError):
            breaker.call(failing)
    assert breaker.state == CircuitBreaker.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: "never")
    clock.now = 11
    assert breaker.state == CircuitBreaker.HALF_OPEN
    assert breaker.call(lambda: "ok") == "ok"
    assert breaker.state == CircuitBreaker.CLOSED


def test_half_open_failure_reopens_immediately():
    clock = FakeClock()
    breaker = CircuitBreaker("x", failure_threshold=3, reset_timeout=5, clock=clock)
    for _ in range(3):
        with pytest.raises(ValueError):
            breaker.call(failing)
    clock.now = 6
    with pytest.raises(ValueError):
        breaker.call(failing)
    assert breaker.state == CircuitBreaker.OPEN


def test_retry_gives_up_after_attempts():
    calls = []

    def flaky():
        calls.append(1)
        raise RetryableError("again")

    with pytest.raises(RetryableError):
        retry(flaky, attempts=3, base_delay=0)
    assert len(calls) == 3


def test_resilient_client_retries_5xx_then_succeeds():
    responses = iter([503, 503, 200])

    def handler(request):
        return httpx.Response(next(responses), json={"ok": True})

    client = ResilientClient("http://upstream", name="t", transport=httpx.MockTransport(handler), attempts=3)
    assert client.get("/x").status_code == 200


def test_resilient_client_does_not_retry_4xx():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404)

    client = ResilientClient("http://upstream", name="t", transport=httpx.MockTransport(handler))
    assert client.get("/x").status_code == 404
    assert len(calls) == 1
