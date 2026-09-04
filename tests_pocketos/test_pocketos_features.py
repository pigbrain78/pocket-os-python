"""Feature-verification tests for the Pocket OS live event spine, the session
+ permission layer, and decision-state replay.

These exercise the newly-added controls over the live demo server (which the
suite harness starts / is already running at POCKETOS_BASE_URL). They prove:

  * the SSE stream pushes ledger events without polling
  * consequential endpoints require a session with the matching permission and
    client-supplied authority is never trusted
  * the replay scrubber reconstructs decision/ratification history, not just
    event counts
"""

import json
import os
import threading
import time
import urllib.request

import pytest
import httpx

BASE = os.environ.get("POCKETOS_BASE_URL", "http://127.0.0.1:8787")
ADMIN = {"username": "admin", "password": "demo"}
OBSERVER = {"username": "observer", "password": "demo"}


@pytest.fixture()
def client():
    return httpx.Client(base_url=BASE, timeout=10.0)


def _login(client: httpx.Client, user: dict):
    r = client.post("/api/login", json=user)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _reset(client: httpx.Client, token: str):
    r = client.post("/api/demo/reset", headers={"Authorization": "Bearer " + token})
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Session + permission layer
# ---------------------------------------------------------------------------


def test_consequential_endpoint_requires_auth(client):
    r = client.post("/api/decisions/propose", json={"title": "no token"})
    assert r.status_code == 401


def test_observer_cannot_propose(client):
    token = _login(client, OBSERVER)
    r = client.post("/api/decisions/propose",
                    headers={"Authorization": "Bearer " + token},
                    json={"title": "observer should be denied"})
    assert r.status_code == 403


def test_observer_cannot_ratify(client):
    # observer has READ only; ratify is gated to RATIFY permission
    token = _login(client, OBSERVER)
    r = client.post("/api/decisions/D-CORPUS-1001/ratify",
                    headers={"Authorization": "Bearer " + token},
                    json={})
    assert r.status_code == 403


def test_client_claimed_authority_is_ignored(client):
    # A valid session with PROPOSE may create a proposal, but claiming a higher
    # authority (e.g. EXECUTE or HUMAN) grants nothing the server does not
    # authorize independently.
    token = _login(client, ADMIN)
    r = client.post("/api/decisions/propose",
                    headers={"Authorization": "Bearer " + token},
                    json={"title": "claimed authority", "send_to_council": True})
    assert r.status_code == 200
    decision_id = r.json()["decision"]["decision_id"]
    # A freshly proposed decision is COUNCIL, unratified. Even claiming HUMAN
    # authority, execute must be denied by the constitutional runtime.
    ex = client.post(f"/api/decisions/{decision_id}/execute",
                     headers={"Authorization": "Bearer " + token},
                     json={"claimed_authority": "HUMAN"})
    assert ex.status_code == 200
    body = ex.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "EXECUTION_DENIED"


def test_demo_mutators_require_admin(client):
    # tamper is gated to ADMIN; an observer token cannot tamper.
    token = _login(client, OBSERVER)
    r = client.post("/api/demo/tamper", headers={"Authorization": "Bearer " + token})
    assert r.status_code == 403


def test_session_me_returns_permissions(client):
    token = _login(client, ADMIN)
    r = client.get("/api/session/me", headers={"Authorization": "Bearer " + token})
    assert r.status_code == 200
    perms = r.json()["permissions"]
    assert "RATIFY" in perms and "EXECUTE" in perms


def test_invalid_token_rejected(client):
    r = client.get("/api/session/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Decision-state replay (scrubber reconstructs decision history)
# ---------------------------------------------------------------------------


def test_scrub_reconstructs_decision_registry(client):
    admin = _login(client, ADMIN)
    _reset(client, admin)
    # full scrub -> decision registry rebuilt from all events
    r = client.get("/api/scrub", params={"include_decisions": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "decisions" in body
    ids = {d["decision_id"]: d for d in body["decisions"]}
    assert ids["D-CORPUS-1001"]["status"] == "RATIFIED"
    assert ids["D-CORPUS-1001"]["human_ratified"] is True
    assert ids["D-METRICS-1002"]["status"] == "REJECTED"


def test_scrub_midpoint_excludes_later_decisions(client):
    admin = _login(client, ADMIN)
    _reset(client, admin)
    # propose a decision (appends an event), then scrub to just before it so
    # the reconstructed registry excludes the late proposal.
    r = client.post("/api/decisions/propose",
                    headers={"Authorization": "Bearer " + admin},
                    json={"title": "late scrub decision", "send_to_council": False})
    assert r.status_code == 200
    late_id = r.json()["decision"]["decision_id"]
    # seed is 25 records; the proposal is seq 26. scrub to 25 -> excludes it.
    r = client.get("/api/scrub", params={"end": 25, "include_decisions": "true"})
    assert r.status_code == 200
    ids = {d["decision_id"] for d in r.json()["decisions"]}
    assert late_id not in ids
    assert "D-CORPUS-1001" in ids


def test_scrub_refuses_over_compromised_chain(client):
    admin = _login(client, ADMIN)
    _reset(client, admin)
    client.post("/api/demo/tamper", headers={"Authorization": "Bearer " + admin})
    r = client.get("/api/scrub", params={"include_decisions": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "SCRUB_REFUSED"
    assert body["error"]["broken_seq"] is not None
    _reset(client, admin)


# ---------------------------------------------------------------------------
# Live event spine (SSE)
# ---------------------------------------------------------------------------


def test_sse_pushes_ledger_event(client):
    """Open an SSE stream, perform an authorized append, and assert the pushed
    event arrives with the matching sequence — proving the spine pushes without
    polling."""
    admin = _login(client, ADMIN)
    _reset(client, admin)
    before = client.get("/api/state").json()["record_count"]

    got: dict = {}

    def consume():
        req = urllib.request.Request(BASE + "/api/stream")
        with urllib.request.urlopen(req, timeout=15) as resp:
            for raw in resp:
                line = raw.decode("utf-8").strip()
                if line.startswith("data:"):
                    data = line[5:].strip()
                    try:
                        msg = json.loads(data)
                    except Exception:
                        continue
                    if msg.get("revision") is not None and "records" in msg:
                        # hello — records baseline; keep reading for events
                        continue
                    got["event"] = msg
                    break

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    time.sleep(0.5)  # let the subscriber register

    # perform an authorized append via a fresh proposal
    r = client.post("/api/decisions/propose",
                    headers={"Authorization": "Bearer " + admin},
                    json={"title": "sse probe event", "send_to_council": False})
    assert r.status_code == 200
    new_seq = r.json()["decision"]["proposal_seq"]

    t.join(timeout=10)
    assert not t.is_alive(), "SSE stream did not push an event"
    assert got, "no SSE event received"
    assert got["event"]["type"] == "decision.proposed"
    assert got["event"]["sequence"] == new_seq
    assert client.get("/api/state").json()["record_count"] == before + 1
    _reset(client, admin)
