from __future__ import annotations

import json
import os
import sys
import time
import urllib.request


DEFAULT_URL = "https://pocketos-canonical-api.onrender.com/api/v1/health"


def _request_health(url: str, timeout: float, opener=urllib.request.urlopen) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with opener(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode())
        if response.status != 200 or payload.get("status") != "healthy" or payload.get("integrity") != "INTACT":
            raise RuntimeError(f"unhealthy response: {response.status} {payload}")
        return {
            "ok": True,
            "url": url,
            "release": payload.get("release"),
            "records": payload.get("records"),
        }


def check_health(
    url: str,
    *,
    timeout: float = 20,
    attempts: int = 1,
    retry_delay: float = 0,
    opener=urllib.request.urlopen,
    sleeper=time.sleep,
) -> dict[str, object]:
    last_error = "unknown error"
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            result = _request_health(url, timeout, opener=opener)
            result["attempt"] = attempt
            return result
        except Exception as exc:
            last_error = str(exc)
            if attempt < max(attempts, 1) and retry_delay > 0:
                sleeper(retry_delay)
    raise RuntimeError(last_error)


def main() -> int:
    url = os.environ.get("POCKETOS_HEALTH_URL", DEFAULT_URL)
    timeout = float(os.environ.get("POCKETOS_HEALTH_TIMEOUT", "20"))
    attempts = int(os.environ.get("POCKETOS_HEALTH_ATTEMPTS", "3"))
    retry_delay = float(os.environ.get("POCKETOS_HEALTH_RETRY_DELAY", "5"))
    try:
        print(json.dumps(check_health(
            url,
            timeout=timeout,
            attempts=attempts,
            retry_delay=retry_delay,
        )))
        return 0
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "url": url,
            "attempts": attempts,
            "error": str(exc),
        }))
        return 1


if __name__ == "__main__":
    sys.exit(main())
