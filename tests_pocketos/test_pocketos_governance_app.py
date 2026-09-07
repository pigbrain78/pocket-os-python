"""Application-level governance negative tests for the Pocket OS clients.

These exercise the REAL backend contract over HTTP (no mocks), proving the
authority boundary holds from the client's vantage point:

  * the UI/client can never make an unratified/rejected decision executable
  * forged claimed_authority grants nothing
  * UI "EXECUTE permission" is not execution authority (server re-validates)
  * ratifying via client/local state change is impossible (needs a recorded event)
  * the Cognitive Twin and AI Shadow projections are structurally non-authoritative

Each test runs against the live demo server (POCKETOS_BASE_URL), resetting to a
known seed first so assertions are deterministic. The tests drive state through
the real propose / council / ratify / reject / execute endpoints exactly as a
client would.
"""

import json
import os
import uuid

import pytest
import httpx

BASE = os.environ.get("POCKETOS_BASE_URL", "http://127.0.0.1:8787")
ADMIN = {"username": "admin", "password": "demo"}
OBSERVER = {"username": "observer", "password": "demo"}


@pytest.fixture()
def client():
    return httpx.Client(base_url=BASE, timeout=10.0)


@pytest.fixture()
def seeded(client):
    """Admin session with the ledger reset to a deterministic seed."""
    r = client.post("/api/login", json=ADMIN)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    reset = client.post("/api/demo/reset", headers=_auth(token))
    assert reset.status_code == 200, reset.text
    return token


def _auth(token: str) -> dict:
    return {"Authorization": "Bearer " + token}


def _propose(client, token: str, send_to_council: bool = False) -> str:
    r = client.post("/api/decisions/propose",
                    headers=_auth(token),
                    json={"title": "neg " + uuid.uuid4().hex[:8],
                          "send_to_council": send_to_council})
    assert r.status_code == 200, r.text
    return r.json()["decision"]["decision_id"]


def _council_approve(client, token: str, did: str):
    r = client.post(f"/api/decisions/{did}/council-approve", headers=_auth(token), json={})
    assert r.status_code == 200, r.text


def _ratify(client, token: str, did: str):
    """Ratify through the REAL council contract: assemble a quorum of distinct
    member signatures via /council-sign, then submit them to /ratify. Bearer
    RATIFY permission alone is insufficient — quorum is required."""
    sigs = {}
    for member in ("council-a", "council-b"):  # QUORUM = 2 distinct members
        r = client.post(f"/api/decisions/{did}/council-sign",
                        headers=_auth(token), params={"member": member})
        assert r.status_code == 200, r.text
        sigs[member] = r.json()["signature"]
    r = client.post(f"/api/decisions/{did}/ratify",
                    headers=_auth(token), json={"signatures": sigs})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.text
    return r


def _decisions(client) -> list[dict]:
    r = client.get("/api/decisions")
    assert r.status_code == 200, r.text
    return r.json()["decisions"]


def _decision(client, did: str) -> dict:
    for d in _decisions(client):
        if d["decision_id"] == did:
            return d
    raise AssertionError(f"decision {did} not found")


def _execution_denied_body(resp):
    body = resp.json()
    assert body.get("ok") is False, f"expected denial, got {body}"
    return body["error"]["code"]


# ---------------------------------------------------------------------------
# 1. The client cannot execute a pending decision.
# ---------------------------------------------------------------------------


def test_client_cannot_execute_pending(client, seeded):
    did = _propose(client, seeded, send_to_council=False)
    d = _decision(client, did)
    assert d["status"] == "PENDING"
    assert d["can_execute"] is False

    # A client that THINKS it can execute (operator has EXECUTE perm) must still
    # be denied because the decision is not human-ratified.
    r = client.post(f"/api/decisions/{did}/execute", headers=_auth(seeded), json={})
    assert r.status_code == 200
    assert _execution_denied_body(r) == "EXECUTION_DENIED"
    assert "not human-ratified" in r.json()["error"]["message"]


# ---------------------------------------------------------------------------
# 2. The client cannot execute a rejected decision.
# ---------------------------------------------------------------------------


def test_client_cannot_execute_rejected(client, seeded):
    did = _propose(client, seeded, send_to_council=False)
    reject = client.post(f"/api/decisions/{did}/reject", headers=_auth(seeded), json={})
    assert reject.status_code == 200, reject.text
    d = _decision(client, did)
    assert d["rejected"] is True
    assert d["can_execute"] is False

    r = client.post(f"/api/decisions/{did}/execute", headers=_auth(seeded), json={})
    assert r.status_code == 200
    assert _execution_denied_body(r) == "EXECUTION_DENIED"
    assert "rejected" in r.json()["error"]["message"]


# ---------------------------------------------------------------------------
# 3. Forging claimed_authority never grants execution.
# ---------------------------------------------------------------------------


def test_client_cannot_execute_by_forging_authority(client, seeded):
    # Take a fully council-approved, ratifiable decision but do NOT ratify it.
    did = _propose(client, seeded, send_to_council=True)
    d = _decision(client, did)
    # send_to_council proposes into AWAITING_RATIFICATION (still unratified).
    assert d["can_execute"] is False
    assert d["human_ratified"] is False

    # The strongest possible forgery — claim HUMAN authority — must be ignored.
    r = client.post(f"/api/decisions/{did}/execute",
                    headers=_auth(seeded),
                    json={"claimed_authority": "HUMAN"})
    assert r.status_code == 200
    assert _execution_denied_body(r) == "EXECUTION_DENIED"
    assert "not human-ratified" in r.json()["error"]["message"]


# ---------------------------------------------------------------------------
# 4. EXECUTE permission is not execution authority (server re-validates).
# ---------------------------------------------------------------------------


def test_execute_permission_is_not_execution_authority(client, seeded):
    # operator has EXECUTE permission; that alone must never execute anything.
    op = client.post("/api/login", json={"username": "operator", "password": "demo"}).json()["token"]
    me = client.get("/api/session/me", headers=_auth(op)).json()
    assert "EXECUTE" in me["permissions"]

    did = _propose(client, seeded, send_to_council=False)  # still PENDING
    r = client.post(f"/api/decisions/{did}/execute", headers=_auth(op), json={})
    assert r.status_code == 200
    assert _execution_denied_body(r) == "EXECUTION_DENIED"


# ---------------------------------------------------------------------------
# 5. A client cannot ratify by mutating local/client state.
# ---------------------------------------------------------------------------


def test_client_cannot_ratify_by_client_state_change(client, seeded):
    did = _propose(client, seeded, send_to_council=False)
    # A client cannot simply declare the decision ratified by replaying a local
    # state change through execute; only a recorded decision.ratified event,
    # which only the server's ratify endpoint appends, advances the decision.
    before = len(client.get("/api/state").json()["records"])

    # observer (READ-only) cannot ratify at all.
    obs = client.post("/api/login", json=OBSERVER).json()["token"]
    r = client.post(f"/api/decisions/{did}/ratify", headers=_auth(obs), json={})
    assert r.status_code == 403

    # Even admin, who CAN ratify, cannot make execute work without the ratify
    # event actually being recorded through the real path.
    ex = client.post(f"/api/decisions/{did}/execute", headers=_auth(seeded), json={})
    assert _execution_denied_body(ex) == "EXECUTION_DENIED"

    after = len(client.get("/api/state").json()["records"])
    assert before == after  # the denied path appended nothing


# ---------------------------------------------------------------------------
# 6. The Cognitive Twin's inferences are never authoritative/executable.
# ---------------------------------------------------------------------------


def test_cognitive_twin_inference_is_not_authoritative(client):
    twin = client.get("/api/twin").json()
    focus = twin["cognitive_twin"]["state"]["current_focus"]
    # The current focus is an inference; it must not be presented as fact.
    assert focus["epistemic"] == "INFERRED"
    # A twin belief id is not a decision id and can never execute.
    r = client.post("/api/decisions/twin-belief-1/execute", json={})
    # No decision → not found / 404 (or 401 without a session); never a success.
    assert r.status_code != 200


# ---------------------------------------------------------------------------
# 7. AI Shadow recommendations are never executable.
# ---------------------------------------------------------------------------


def test_ai_shadow_recommendation_is_not_executable(client, seeded):
    shadow = client.get("/api/shadow").json()["ai_shadow"]
    # Structural boundary: no authority, cannot execute/ratify.
    boundary = shadow["authority_boundary"]
    assert boundary["shadow_authority"] == "NONE"
    assert boundary["shadow_can_execute"] is False
    assert boundary["shadow_can_ratify"] is False
    assert "HUMAN_RATIFICATION" in boundary["execution_requires"]
    # Every item carries authority NONE and advisory status.
    for item in shadow["items"]:
        assert item["authority"] == "NONE"
        assert item["status"] == "advisory"

    did = _propose(client, seeded, send_to_council=True)
    # Full council + human ratification required; the shadow alone grants nothing.
    _council_approve(client, seeded, did)
    # A shadow item id is not a real ratified decision.
    r = client.post("/api/decisions/shadow-recommendation-1/execute",
                    headers=_auth(seeded), json={})
    assert r.status_code == 200
    assert _execution_denied_body(r) == "EXECUTION_DENIED"


# ---------------------------------------------------------------------------
# Positive control: the chain is not a blanket block. A real council-approved +
# human-ratified decision CAN execute exactly once.
# ---------------------------------------------------------------------------


def test_positive_control_ratified_decision_executes_once(client, seeded):
    did = _propose(client, seeded, send_to_council=True)
    _council_approve(client, seeded, did)
    _ratify(client, seeded, did)
    d = _decision(client, did)
    assert d["status"] == "RATIFIED"
    assert d["human_ratified"] is True
    assert d["can_execute"] is True

    r1 = client.post(f"/api/decisions/{did}/execute", headers=_auth(seeded), json={})
    assert r1.status_code == 200
    assert r1.json()["ok"] is True
    assert r1.json()["result"]["executed"] is True

    # Exactly once: a second execution must be denied.
    r2 = client.post(f"/api/decisions/{did}/execute", headers=_auth(seeded), json={})
    assert r2.json()["ok"] is False
    assert _execution_denied_body(r2) == "EXECUTION_DENIED"
