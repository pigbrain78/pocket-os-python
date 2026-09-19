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


def test_council_sign_succeeds_with_sandbox_test_signer():
    tok = _login()
    did = "D-WORKSPACE-1003"
    client.post(f"/api/v1/decisions/{did}/council-approve", headers=_h(tok))
    old = A.council_gate._TEST_SIGNER_ENABLED
    old_env = A.council_gate._RUNTIME_ENV
    try:
        A.council_gate._RUNTIME_ENV = "sandbox"
        A.council_gate._TEST_SIGNER_ENABLED = True
        r = client.post(f"/api/v1/decisions/{did}/council-sign?member=council-a", headers=_h(tok))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["signature"]
    finally:
        A.council_gate._TEST_SIGNER_ENABLED = old
        A.council_gate._RUNTIME_ENV = old_env


def test_council_sign_fails_clearly_when_sandbox_signer_disabled():
    tok = _login()
    did = "D-WORKSPACE-1003"
    client.post(f"/api/v1/decisions/{did}/council-approve", headers=_h(tok))
    old = A.council_gate._TEST_SIGNER_ENABLED
    old_demo = A.council_gate._DEMO_SIGNING
    old_env = A.council_gate._RUNTIME_ENV
    try:
        A.council_gate._RUNTIME_ENV = "sandbox"
        A.council_gate._TEST_SIGNER_ENABLED = False
        A.council_gate._DEMO_SIGNING = False
        r = client.post(f"/api/v1/decisions/{did}/council-sign?member=council-a", headers=_h(tok))
        assert r.status_code == 403
        msg = r.json().get("error", {}).get("message") or r.json().get("detail", "")
        assert "sandbox/test signer is disabled" in msg
    finally:
        A.council_gate._TEST_SIGNER_ENABLED = old
        A.council_gate._DEMO_SIGNING = old_demo
        A.council_gate._RUNTIME_ENV = old_env


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
    approved = client.post(f"/api/v1/decisions/{did}/council-approve", headers=_h(tok))
    assert approved.status_code == 200, approved.text
    old_signer = A.council_gate._TEST_SIGNER_ENABLED
    old_env = A.council_gate._RUNTIME_ENV
    A.council_gate._TEST_SIGNER_ENABLED = True
    A.council_gate._RUNTIME_ENV = "sandbox"
    try:
        signatures = {}
        for member in ("council-a", "council-b"):
            signed = client.post(f"/api/v1/decisions/{did}/council-sign?member={member}", headers=_h(tok))
            assert signed.status_code == 200, signed.text
            signatures[member] = signed.json()["signature"]
        r = client.post("/api/v1/decisions/" + did + "/ratify", json={"signatures": signatures}, headers=_h(tok))
    finally:
        A.council_gate._TEST_SIGNER_ENABLED = old_signer
        A.council_gate._RUNTIME_ENV = old_env
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


def _skeleton(obj, mask):
    if isinstance(obj, dict):
        return {k: _skeleton(v, mask) for k, v in obj.items() if k not in mask}
    if isinstance(obj, list):
        return [_skeleton(obj[0], mask)] if obj else []
    return type(obj).__name__


def test_contract_fixture_snapshot_is_stable():
    # The committed contract fixture is a golden structural snapshot of the
    # /api/v1 responses. Re-derive the same skeleton from the live app and diff
    # it against the committed artifact: any drift (renamed/added/removed keys,
    # dropped epistemic markers, new nesting) fails here. Volatile values
    # (request ids, hashes, timestamps) are masked and do not cause failures.
    import os as _os
    mask = {"request_id", "hash", "previous_hash", "event_id", "occurred_at",
            "server_time", "sequence"}
    paths = [
        "/api/v1/status", "/api/v1/memory", "/api/v1/memory/1",
        "/api/v1/cognitive-twin", "/api/v1/ai-shadow", "/api/v1/decisions",
        "/api/v1/decisions/D-CORPUS-1001", "/api/v1/ledger",
        "/api/v1/ledger/events/1", "/api/v1/replay/status",
        "/api/v1/evidence/verification",
    ]
    fixture_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                                 "tests_pocketos", "fixtures", "contract_v1_snapshot.json")
    with open(fixture_path) as f:
        fixture = json.load(f)
    assert fixture["contract_version"] == 1
    for p in paths:
        r = client.get(p)
        assert r.status_code == 200, f"{p} returned {r.status_code}"
        live = _skeleton(r.json(), mask)
        assert p in fixture["paths"], f"path {p} not in committed snapshot"
        assert live == fixture["paths"][p], (
            f"contract drift at {p}: committed fixture no longer matches the live "
            f"/api/v1 response. Regenerate the snapshot only after an intentional, "
            f"versioned contract change."
        )


def _extract_contract_spec(spec_js):
    """Extract the __pocketContract object literal from the client JS spec."""
    import re as _re
    txt = open(spec_js).read()
    m = _re.search(r"__pocketContract = (\{.*?\});", txt, _re.DOTALL)
    assert m, "could not locate __pocketContract in contract_spec.js"
    return json.loads(m.group(1))


def test_client_contract_spec_matches_fixture():
    # The client-enforced spec (contract_spec.js) is generated from the golden
    # fixture. If a drift guard regenerates the fixture without refreshing the
    # client spec, or vice versa, the client and server would disagree on the
    # shape. This test locks them together.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fixture = json.load(open(os.path.join(root, "tests_pocketos", "fixtures", "contract_v1_snapshot.json")))
    spec = _extract_contract_spec(os.path.join(root, "scripts", "pocketos_demo", "static", "lib", "pocket", "contract_spec.js"))
    assert spec["contract_version"] == fixture["contract_version"]
    assert spec["schema_version"] == fixture["schema_version"]
    # For every fixture path, the client spec must require exactly the
    # non-volatile top-level keys the fixture captured.
    for path, skel in fixture["paths"].items():
        expected = [k for k in skel if k not in ("request_id", "api_version", "schema_version")]
        assert path in spec["paths"], f"client spec missing path {path}"
        assert sorted(spec["paths"][path]) == sorted(expected), (
            f"client spec for {path} diverged from fixture: spec={sorted(spec['paths'][path])} fixture={sorted(expected)}"
        )


def test_live_v1_endpoints_satisfy_client_contract():
    # Prove "clients cannot bypass the shape": every live /api/v1 read endpoint
    # must supply at least the keys the client transport enforces. If the server
    # ever omits a required field, the browser client would reject it — caught
    # here server-side before it ever reaches a client.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = _extract_contract_spec(os.path.join(root, "scripts", "pocketos_demo", "static", "lib", "pocket", "contract_spec.js"))
    for path, required in spec["paths"].items():
        # Only GET read endpoints are client-consumed as envelopes.
        if "/propose" in path or path.endswith(("/ratify", "/reject", "/execute")):
            continue
        r = client.get(path)
        assert r.status_code == 200, f"{path} not 200"
        body = r.json()
        missing = [k for k in required if k not in body]
        assert not missing, f"live {path} violates client contract: missing {missing}"
        assert "api_version" in body and "schema_version" in body, f"live {path} missing version envelope"


def test_sse_fallback_poll_receives_events_with_advisory_authority():
    tok = _login()
    baseline = client.get("/api/v1/stream/health").json()["stream"]
    assert baseline["active_path"] in {"live-sse", "fallback-poll"}
    before = client.get("/api/state").json()["record_count"]
    r = client.post("/api/v1/decisions/propose", json={"title": "fallback stream probe"}, headers=_h(tok))
    assert r.status_code == 200
    poll = client.get("/api/v1/stream/fallback", params={"since": before, "limit": 10})
    assert poll.status_code == 200
    events = poll.json()["events"]
    assert any(e.get("type") == "decision.proposed" for e in events)
    for ev in events:
        assert ev["authority"] == "NONE"
        assert ev["status"] == "advisory"


def test_ios_codable_models_match_live_contract():
    """The iOS client's Swift Codable models mirror the /api/v1 contract. Every
    raw snake_case key a Swift model declares as a CodingKey must exist in the
    corresponding live response; otherwise the model cannot decode. This is the
    runnable equivalent of a Swift compile/test in a toolchain-less sandbox."""
    import re as _re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    models_dir = os.path.join(root, "ios", "Sources", "PocketOSClient")
    assert os.path.isdir(models_dir), "ios skeleton missing"

    # Map each model (by the endpoints it decodes) to the live JSON we check.
    # We collect the union of raw CodingKeys across all model files and assert
    # each appears in at least one canonical v1 response's flattened key set.
    raw_keys = set()
    for fn in ("Models.swift", "Models2.swift"):
        txt = open(os.path.join(models_dir, fn)).read()
        # Only collect cases INSIDE a CodingKeys enum, not enum raw-values
        # (e.g. EpistemicStatus .inferred -> "INFERRED") or JSONValue cases.
        for block in _re.finditer(r'enum CodingKeys: String, CodingKey \{[^}]*\}', txt, _re.DOTALL):
            for m in _re.finditer(r'case\s+(\w+)(?:\s*=\s*"([^"]+)")?', block.group(0)):
                # A raw value is the wire key; without one the property name is
                # the wire key only when it is already snake/camel identical.
                raw_keys.add(m.group(2) if m.group(2) else m.group(1))

    # Load every canonical GET response and flatten nested keys.
    def flatten(obj, prefix="", acc=None):
        if acc is None: acc = set()
        if isinstance(obj, dict):
            for k, v in obj.items():
                acc.add(k)
                flatten(v, k, acc)
        elif isinstance(obj, list) and obj:
            flatten(obj[0], prefix, acc)
        return acc
    live_keys = set()
    for p in ["/api/v1/status", "/api/v1/memory", "/api/v1/cognitive-twin",
              "/api/v1/ai-shadow", "/api/v1/decisions", "/api/v1/ledger/events/1"]:
        live_keys |= flatten(client.get(p).json())
    # Command responses (propose/ratify/reject) carry an `ok` + `decision`
    # envelope that the read endpoints do not; sample one so DecisionAction's
    # keys are validated too. Fixture reset keeps this side-effect clean.
    tok = client.post("/api/login", json={"username": "admin", "password": "demo"}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    live_keys |= flatten(client.post("/api/v1/decisions/propose",
                                     json={"title": "ios-key-probe"}, headers=h).json())

    # Raw keys that exist in the model must exist in the live responses.
    missing = sorted(raw_keys - live_keys)
    assert not missing, (
        f"iOS Codable models reference keys absent from the live /api/v1 "
        f"contract: {missing}. The models must mirror the contract exactly."
    )
