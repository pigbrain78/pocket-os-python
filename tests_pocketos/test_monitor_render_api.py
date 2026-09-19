import json

import pytest

from scripts import monitor_render_api as monitor


class _Response:
    def __init__(self, status: int, payload: dict[str, object]):
        self.status = status
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_check_health_retries_before_success():
    calls = {"count": 0}
    sleeps: list[float] = []

    def opener(request, timeout):
        calls["count"] += 1
        if calls["count"] < 3:
            raise TimeoutError("timed out")
        return _Response(200, {"status": "healthy", "integrity": "INTACT", "release": "r1", "records": 7})

    result = monitor.check_health(
        "https://example.invalid/api/v1/health",
        timeout=30,
        attempts=3,
        retry_delay=10,
        opener=opener,
        sleeper=sleeps.append,
    )

    assert result == {
        "ok": True,
        "url": "https://example.invalid/api/v1/health",
        "release": "r1",
        "records": 7,
        "attempt": 3,
    }
    assert sleeps == [10, 10]


def test_check_health_raises_on_unhealthy_payload():
    def opener(request, timeout):
        return _Response(200, {"status": "healthy", "integrity": "COMPROMISED"})

    with pytest.raises(RuntimeError, match="unhealthy response"):
        monitor.check_health(
            "https://example.invalid/api/v1/health",
            attempts=1,
            opener=opener,
        )
