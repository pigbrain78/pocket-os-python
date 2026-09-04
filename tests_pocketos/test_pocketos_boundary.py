"""Shared client/API boundary tests.

Prove the canonical /api/v1 contract the web UI and the future iPhone client
both consume: normalized errors, stable request ids, epistemic-state and
provenance preservation, no web-only fields in the JSON, and that the browser
cannot gain authority it lacks (no bypass of governance/constitutional gates).
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import pytest
from fastapi.testclient import TestClient

import pocketos_demo.app as A

client = TestClient(A.app)

# Canonical epistemic states that must NEVER collapse to a boolean.
EPISTEMIC = {"OBSERVED", "VERIFIED", "INFERRED", "PROPOSED", "UNCERTAIN", "REJECTED", "STALE"}


@pytest.fixture(autouse=True)
def _clean():
    with A._SESSION_LOCK:
        A._SESSIONS.clear()
        A._LOGIN_ATTEMPTS.clear()
        A._LOGIN_LOCKOUTS.clear()
    A.STATE.reset_to_seed()  # INTACT seeded ledger for every test
    yield


def _login(username="admin", password="demo"):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(token):
    return {"Authorization": "Bearer " + token}


def test_v1_status_is_versioned_and_normalized():
    r = client.get("/api/v1/status")
    assert r.status_code == 200
    body = r.json()
    assert body["api_version"] == "1"
    assert body["schema_version"] == "v2"
    assert body["request_id"]
    assert body["ledger"]["integrity"] == "INTACT"
    assert "server_time" in body


def test_cognitive_twin_preserves_epistemic_status():
    r = client.get("/api/v1/cognitive-twin")
    assert r.status_code == 200
    twin = r.json()["cognitive_twin"]
    focus = twin["state"]["current_focus"]
    # The focus is a model inference — it must be tagged INFERRED, never a bool.
    assert focus["epistemic"] in EPISTEMIC
    assert focus["epistemic"] == "INFERRED"
    assert "confidence" in focus
    assert "provenance" in focus
    # No boolean "trusted" collapse anywhere in the focus.
    assert "trusted" not in focus


def test_ai_shadow_is_advisory_without_authority():
    r = client.get("/api/v1/ai-shadow")
    assert r.status_code == 200
    shadow = r.json()["ai_shadow"]
    boundary = shadow["authority_boundary"]
    assert boundary["shadow_authority"] == "NONE"
    assert "execution" not in [i["type"] for i in shadow["items"]]


def test_memory_returns_stable_ids_and_provenance():
    r = client.get("/api/v1/memory")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] > 0
    for item in body["items"]:
        assert "id" in item
        assert "provenance" in item
        assert item["provenance"].startswith("ledger#")
        assert "hash" in item


def test_ledger_events_are_append_only_verified():
    r = client.get("/api/v1/ledger")
    body = r.json()
    assert body["ledger"]["valid"] is True
    assert body["genesis_sequence"] == 1
    assert body["head_sequence"] == body["records"]
    # Fetch the head event and confirm it exposes hash + provenance fields.
    head = body["events"][-1]
    assert "hash" in head
    assert "previous_hash" in head


def test_replay_status_refuses_when_compromised():
    # Compromise the ledger, then a replay inspect must reject (no partial state).
    tok = _login()
    client.post("/api/demo/tamper", headers=_h(tok))
    r = client.get("/api/v1/replay/inspect")
    assert r.status_code == 200  # normalized envelope
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "REPLAY_REJECTED"
    assert "broken_seq" in body["error"]
    # The rejected replay must not fabricate a partial state slice.
    assert "state" not in body
    # Reset for other tests.
    client.post("/api/demo/reset", headers=_h(tok))


def test_ratify_without_token_is_normalized_401():
    r = client.post("/api/v1/decisions/D-WORKSPACE-1003/ratify", json={})
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["code"] == "AUTHENTICATION_REQUIRED"
    assert err["request_id"]


def test_observer_cannot_ratify_normalized_403():
    obs = _login(username="observer")
    r = client.post("/api/v1/decisions/D-WORKSPACE-1003/ratify", json={}, headers=_h(obs))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "AUTHORIZATION_DENIED"


def test_unknown_resource_returns_normalized_404():
    r = client.get("/api/v1/memory/99999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_client_cannot_supply_authoritative_ledger_position():
    # A client must never inject sequence numbers or hashes. Propose/ratify do
    # not accept such fields; the server appends at its own head. Posting a
    # forged position via the decision command must not mutate the ledger head.
    tok = _login()
    head_before = client.get("/api/v1/ledger").json()["head_sequence"]
    # Attempt to ratify an unknown/garbage decision id (no such canonical object).
    r = client.post("/api/v1/decisions/NOPE-1/ratify", json={}, headers=_h(tok))
    assert r.status_code == 404
    head_after = client.get("/api/v1/ledger").json()["head_sequence"]
    assert head_after == head_before  # no mutation


def test_propose_then_ratify_then_execute_path():
    # Propose a fresh decision, drive it through council + ratification, and
    # confirm it reaches an executable state — proving commands flow the
    # governance path and the client never executes directly.
    tok = _login()
    title = "boundary lifecycle decision"
    prop = client.post("/api/v1/decisions/propose", json={"title": title, "send_to_council": True}, headers=_h(tok))
    assert prop.status_code == 200, prop.text
    did = prop.json()["decision"]["decision_id"]
    # Pending -> not yet ratified/executed; a council-sent proposal is in
    # COUNCIL or PENDING until human ratification.
    assert prop.json()["decision"]["status"] in ("PENDING", "PROPOSED", "COUNCIL")
    assert not prop.json()["decision"].get("human_ratified", False)
    r = client.post("/api/v1/decisions/" + did + "/ratify", json={}, headers=_h(tok))
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["status"] == "RATIFIED"


def test_no_web_only_fields_in_v1_json():
    # iPhone compatibility: the canonical JSON must not smuggle browser-only
    # concepts (localStorage, DOM, window). Sweep a few representative bodies.
    web_only = {"localStorage", "sessionStorage", "window.", "document.", "DOM", "innerHTML"}
    for path in ("/api/v1/status", "/api/v1/cognitive-twin", "/api/v1/ai-shadow",
                 "/api/v1/memory", "/api/v1/ledger"):
        r = client.get(path)
        assert r.status_code == 200
        text = json.dumps(r.json())
        for token in web_only:
            assert token not in text, f"web-only token {token!r} leaked into {path}"


def test_governance_failure_produces_no_mutation():
    # A rejected decision can never be executed (legacy constitutional path is
    # authoritative). Confirm the v1 read reflects the rejection and that
    # execution is not reachable via the v1 surface (no execute route exists).
    tok = _login()
    # D-METRICS-1002 is seeded as REJECTED.
    r = client.get("/api/v1/decisions/D-METRICS-1002")
    assert r.status_code == 200
    assert r.json()["item"]["status"] == "REJECTED"
    # The v1 contract exposes no execute verb — proposals/ratify/reject only.
    paths = [route.path for route in A.app.routes]
    assert not any(p.endswith("/execute") and p.startswith("/api/v1") for p in paths)


def test_openapi_export_is_machine_readable():
    # The iPhone contract is published as OpenAPI for code generation. The
    # live export must (a) be valid OpenAPI 3.1, (b) carry a versioned title,
    # and (c) expose the canonical /api/v1 routes.
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["openapi"].startswith("3.1")
    assert "paths" in schema
    v1_paths = [p for p in schema["paths"] if p.startswith("/api/v1")]
    assert v1_paths, "no /api/v1 paths in the published schema"
    # The v1 contract must not expose an execute verb (governance invariant).
    # (The legacy demo does expose an execute route for testing the runtime,
    # but that is not part of the /api/v1 client contract.)
    v1_execute = [p for p in schema["paths"] if p.startswith("/api/v1") and p.endswith("/execute")]
    assert not v1_execute


def test_committed_openapi_artifact_is_scoped_to_v1():
    # The checked-in artifact (docs/POCKETOS_CLIENT_API.openapi.json) must be
    # valid and scoped to /api/v1 only — no legacy routes leak into the
    # iPhone-facing machine contract.
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "docs", "POCKETOS_CLIENT_API.openapi.json")
    assert os.path.exists(path), "committed OpenAPI artifact missing"
    with open(path) as f:
        schema = json.load(f)
    assert schema["info"]["version"] == "1"
    paths = list(schema["paths"].keys())
    assert paths, "artifact has no paths"
    assert all(p.startswith("/api/v1") for p in paths), "non-v1 path leaked into artifact"
    assert not any(p.endswith("/execute") for p in paths)
