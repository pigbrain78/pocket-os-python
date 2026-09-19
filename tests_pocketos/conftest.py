"""Shared fixtures that isolate tests against the canonical PocketOS ledger.

Every server-touching test mutates the same durable ledger. This fixture resets
that ledger before each test when the server is reachable, while remaining a
no-op for pure in-process tests when the server is offline.
"""
from __future__ import annotations

import os

import httpx
import pytest

BASE = os.environ.get("POCKETOS_BASE_URL", "http://127.0.0.1:8787")
_CREDS = {"username": "admin", "password": "demo"}


def _reset_ledger() -> None:
    """Reset the live ledger to the seeded state.

    Network unavailability is intentionally ignored so pure unit suites can run
    without a server. Once a server responds, authentication and reset errors
    are surfaced instead of silently disabling test isolation.
    """
    try:
        with httpx.Client(base_url=BASE, timeout=5.0) as client:
            login = client.post("/api/login", json=_CREDS)
            login.raise_for_status()
            token = login.json().get("token")
            if not token:
                raise RuntimeError("PocketOS login response did not contain a token")
            reset = client.post(
                "/api/demo/reset",
                headers={"Authorization": "Bearer " + token},
            )
            reset.raise_for_status()
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError):
        # No server: in-process tests remain runnable and server-backed tests
        # still fail at their own explicit request/assertion boundary.
        return


@pytest.fixture(autouse=True)
def _clean_ledger():
    """Start each test from the seeded ledger when the server is available."""
    _reset_ledger()
    yield
