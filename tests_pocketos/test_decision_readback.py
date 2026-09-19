import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import pocketos_demo.app as app_module


client = TestClient(app_module.app)


def _login() -> str:
    response = client.post("/api/login", json={"username": "admin", "password": "demo"})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def test_decision_readback_returns_canonical_reducer_projection():
    token = _login()
    headers = {"Authorization": f"Bearer {token}"}
    proposal = client.post(
        "/api/v1/decisions/propose",
        headers=headers,
        json={"title": "read-after-write probe", "risk": "LOW", "reversible": True},
    )
    assert proposal.status_code == 200, proposal.text
    decision_id = proposal.json()["decision"]["decision_id"]

    readback = client.get(f"/api/v1/decisions/{decision_id}")
    assert readback.status_code == 200, readback.text
    assert readback.json()["api_version"] == "1"
    assert readback.json()["item"]["decision_id"] == decision_id
    assert readback.json()["item"]["status"] == "PENDING"
    assert readback.json()["item"]["can_execute"] is False

    alias = client.get(f"/api/decisions/{decision_id}")
    assert alias.status_code == 200, alias.text
    assert alias.json()["item"]["decision_id"] == decision_id


def test_decision_readback_rejects_unknown_id():
    readback = client.get("/api/v1/decisions/D-DOES-NOT-EXIST")
    assert readback.status_code == 404
    assert "unknown decision" in readback.text

    alias = client.get("/api/decisions/D-DOES-NOT-EXIST")
    assert alias.status_code == 404
    assert "unknown decision" in alias.text
