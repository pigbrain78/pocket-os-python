from __future__ import annotations

import json
import os
import sys
import urllib.request

url = os.environ.get("POCKETOS_HEALTH_URL", "https://pocketos-canonical-api.onrender.com/api/v1/health")
request = urllib.request.Request(url, headers={"Accept": "application/json"})
try:
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode())
        if response.status != 200 or payload.get("status") != "healthy" or payload.get("integrity") != "INTACT":
            raise RuntimeError(f"unhealthy response: {response.status} {payload}")
        print(json.dumps({"ok": True, "url": url, "release": payload.get("release"), "records": payload.get("records")}))
except Exception as exc:
    print(json.dumps({"ok": False, "url": url, "error": str(exc)}))
    sys.exit(1)
