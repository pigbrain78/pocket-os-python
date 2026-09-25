import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent / "pocketos_src"
sys.path.insert(0, str(ROOT))
os.environ.setdefault("POCKETOS_COUNCIL_DEMO_SIGNING", "1")
os.environ.setdefault("POCKETOS_PRODUCTION_SIGNING_ENABLED", "0")

from fastapi.testclient import TestClient
from scripts.pocketos_demo.app import app

client = TestClient(app)

for path in ["/api/v1/health", "/api/v1/build", "/api/v1/state", "/api/v1/twin", "/api/v1/shadow", "/api/v1/decisions", "/api/v1/evidence/traits"]:
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code, response.text)
    assert isinstance(response.json(), dict)

assert client.get("/api/health").status_code == 200
assert client.post("/api/v1/memory/search", json={"query": "anything"}).status_code == 200
assert client.post("/api/v1/memory/remember", json={"content": "unauthorized capture"}).status_code == 401
assert client.get("/api/v1/projects").status_code == 200
assert client.get("/api/v1/open-loops").status_code == 200
assert client.post("/api/v1/shadow/propose", json={"text": "review this recommendation"}).status_code == 401
assert client.get("/api/v1/decisions").status_code == 200
trait_evidence = client.get("/api/v1/evidence/traits").json()["traits"]
assert len(trait_evidence) == 6 and all(item["epistemic"] == "INFERRED" for item in trait_evidence)
assert client.post("/api/v1/decisions/D-unknown/council-approve").status_code == 401
assert client.post("/api/v1/decisions/D-unknown/ratify", json={"signatures": {}}).status_code == 401
assert client.post("/api/v1/decisions/D-unknown/council-sign?member=council-a").status_code == 401
assert client.get("/api/v1/decisions/D-unknown/evidence").status_code == 404
assert client.get("/api/v1/decisions/D-unknown/ledger").status_code == 404
assert client.get("/api/v1/decisions/D-unknown/receipt").status_code == 404
assert client.post("/api/v1/decisions/D-unknown/outcome", json={"outcome": "no"}).status_code == 401
assert client.get("/api/v1/scrub?end=-1&include_decisions=true").json().get("ok") is False
assert client.get("/api/v1/scrub?end=999999&include_decisions=true").json().get("ok") in {True, False}
assert client.get("/api/v1/replay/bookmarks").status_code == 401
login = client.post("/api/v1/login", json={"username": "operator", "password": "demo"})
assert login.status_code == 200
token = login.json()["token"]
auth_headers = {"Authorization": f"Bearer {token}"}
admin_login = client.post("/api/v1/login", json={"username": "admin", "password": "demo"})
assert admin_login.status_code == 200
assert client.post("/api/demo/reset", headers={"Authorization": f"Bearer {admin_login.json()['token']}"}).status_code == 200
decisions_before = client.get("/api/v1/decisions", headers=auth_headers).json()["decisions"]
pending = next(item for item in decisions_before if item["decision_id"] == "D-WORKSPACE-1003")
assert pending["status"] == "PENDING"
assert client.post("/api/v1/decisions/D-WORKSPACE-1003/council-sign?member=council-a", headers=auth_headers).status_code == 409
approved = client.post("/api/v1/decisions/D-WORKSPACE-1003/council-approve", headers=auth_headers)
assert approved.status_code == 200 and approved.json()["decision"]["status"] == "AWAITING_RATIFICATION"
sig_a = client.post("/api/v1/decisions/D-WORKSPACE-1003/council-sign?member=council-a", headers=auth_headers)
sig_b = client.post("/api/v1/decisions/D-WORKSPACE-1003/council-sign?member=council-b", headers=auth_headers)
assert sig_a.status_code == 200 and sig_b.status_code == 200
ratified = client.post("/api/v1/decisions/D-WORKSPACE-1003/ratify", headers=auth_headers, json={"signatures": {"council-a": sig_a.json()["signature"], "council-b": sig_b.json()["signature"]}, "claimed_authority": "NONE"})
assert ratified.status_code == 200 and ratified.json()["ok"] is True
executed = client.post("/api/v1/decisions/D-WORKSPACE-1003/execute", headers=auth_headers, json={"claimed_authority": "NONE"})
assert executed.status_code == 200 and executed.json()["ok"] is True
receipt = client.get("/api/v1/decisions/D-WORKSPACE-1003/receipt", headers=auth_headers)
assert receipt.status_code == 200 and receipt.json()["receipt"]["status"] == "EXECUTED"
review = client.post("/api/v1/decisions/D-WORKSPACE-1003/outcome", headers=auth_headers, json={"outcome": "verified", "lessons": ["review early"]})
assert review.status_code == 200 and review.json()["receipt"]["status"] == "REVIEWED"
assert client.post("/api/v1/decisions/D-WORKSPACE-1003/outcome", headers=auth_headers, json={"outcome": "duplicate"}).status_code == 409
assert client.post("/api/v1/decisions/D-WORKSPACE-1003/reject", headers=auth_headers).status_code == 409
bookmark = client.post("/api/v1/replay/bookmarks", headers=auth_headers, json={"end": 1, "label": "Initial snapshot", "device_id": "device-a", "device_name": "Test phone", "platform": "ios", "client_updated_at": "2026-09-11T10:00:00+00:00"})
assert bookmark.status_code == 200
assert client.get("/api/v1/replay/bookmarks", headers=auth_headers).json()["bookmarks"][0]["end"] == 1
newer = client.post("/api/v1/replay/bookmarks", headers=auth_headers, json={"end": 1, "label": "Newer snapshot", "device_id": "device-b", "device_name": "Test laptop", "platform": "web", "client_updated_at": "2026-09-11T11:00:00+00:00"})
assert newer.status_code == 200 and newer.json()["bookmark"]["deviceName"] == "Test laptop"
older = client.post("/api/v1/replay/bookmarks", headers=auth_headers, json={"end": 1, "label": "Stale snapshot", "device_id": "device-a", "device_name": "Test phone", "platform": "ios", "client_updated_at": "2026-09-11T09:00:00+00:00"})
assert older.status_code == 200 and older.json()["conflict"] == "server-kept-newer-version"
audit = client.get("/api/v1/replay/bookmarks/audit", headers=auth_headers)
assert audit.status_code == 200 and any(item["action"] == "conflict-replaced" for item in audit.json()["audit"])
assert client.get("/api/v1/preferences/audit").status_code == 401
saved_preferences = client.post("/api/v1/preferences/audit", headers=auth_headers, json={"device": "device-b", "action": "created", "conflict": "NONE", "sortNewest": False})
assert saved_preferences.status_code == 200 and saved_preferences.json()["preferences"]["sortNewest"] is False
assert client.get("/api/v1/preferences/audit", headers=auth_headers).json()["preferences"]["device"] == "device-b"
assert client.delete("/api/v1/replay/bookmarks/1", headers=auth_headers).status_code == 200
replay = client.get("/api/v1/scrub?include_decisions=true").json()
assert isinstance(replay.get("events"), list)
assert client.get("/api/v1/build").json()["release"] == "pocketos-app-1.1.0"
assert client.get("/api/v1/build").json()["ledger"]["integrity"] == "INTACT"

paths = {route.path for route in app.routes}
assert "/api/v1/health" in paths
assert "/api/v1/build" in paths
assert "/api/v1/stream" in paths
assert "/api/v1/scrub" in paths
assert "/api/v1/replay/bookmarks/audit" in paths
assert "/api/v1/preferences/audit" in paths
assert "/api/v1/evidence/traits" in paths
assert "/api/v1/decisions/{decision_id}/receipt" in paths
assert "/api/v1/decisions/{decision_id}/outcome" in paths
assert not any(path.startswith("/api/v1/decisions/") and path.endswith("/execute") for path in paths)
print("PocketOS /api/v1 surface verified")
