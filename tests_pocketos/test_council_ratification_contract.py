"""Layer B — Cryptographic ratification contract suite (council_ratification.py).

These tests exercise the canonical cryptographic primitive DIRECTLY (pure
stdlib, no server) and prove the 15 contract guarantees the Pocket OS backend
now enforces:

   1. valid quorum -> PASS
   2. below-threshold signatures -> BLOCK
   3. duplicate signer does not satisfy quorum
   4. unknown signer -> BLOCK
   5. invalid HMAC -> BLOCK
   6. modified decision -> BLOCK
   7. modified target state -> BLOCK
   8. wrong decision ID -> BLOCK
   9. forged claimed authority -> BLOCK   (server-side, over HTTP)
  10. valid quorum -> authoritative ledger event (over HTTP)
  11. valid quorum -> can_execute (over HTTP)
  12. no quorum -> no ratification event (over HTTP)
  13. already executed -> second execution blocked (over HTTP)
  14. ledger verification -> PASS
  15. ledger tampering -> verification failure

Plus one end-to-end application test proving the complete chain:
council signatures -> threshold verification -> authoritative ratification ->
Pocket OS ledger -> can_execute -> execution -> evidence.

The unit-level tests (1-8, 14-15) import the contract module directly. The
over-HTTP tests (9-13, end-to-end) run against the live demo server.
"""

import importlib
import json
import os
import sys
import uuid

import pytest
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from pocketos_demo.engines import council_ratification as council
from pocketos_demo.engines import council_gate

BASE = os.environ.get("POCKETOS_BASE_URL", "http://127.0.0.1:8787")
ADMIN = {"username": "admin", "password": "demo"}

# Demo council members (mirror council_gate registry).
MEMBER_KEYS = {
    "council-a": bytes.fromhex("aa" * 32),
    "council-b": bytes.fromhex("bb" * 32),
    "council-c": bytes.fromhex("cc" * 32),
}


@pytest.fixture()
def reg():
    return council.new_registry(MEMBER_KEYS)


def _sig(reg, member, cid, state):
    _, key = council.active_key(reg, member)
    return council.sign(cid, state, member, key)


# ---------------------------------------------------------------------------
# Unit-level contract tests (pure, no server)
# ---------------------------------------------------------------------------


def test_1_valid_quorum_passes(reg):
    cid, st = "c-1", "RATIFIED"
    sigs = {
        "council-a": _sig(reg, "council-a", cid, st),
        "council-b": _sig(reg, "council-b", cid, st),
    }
    assert council.verify_ratification(cid, st, sigs, reg) is True


def test_2_below_threshold_signatures_block(reg):
    cid, st = "c-2", "RATIFIED"
    one = {"council-a": _sig(reg, "council-a", cid, st)}
    assert council.verify_ratification(cid, st, one, reg) is False


def test_3_duplicate_signer_does_not_satisfy_quorum(reg):
    cid, st = "c-3", "RATIFIED"
    # Same signature submitted under two member names is still ONE distinct
    # verified member (the duplicate fails under the other member's key).
    a = _sig(reg, "council-a", cid, st)
    dup = {"council-a": a, "council-b": a}
    assert council.verify_ratification(cid, st, dup, reg) is False


def test_4_unknown_signer_blocks(reg):
    cid, st = "c-4", "RATIFIED"
    # Add a fake member with a bogus key; verify() rejects unknown/unauthorized.
    intruder_reg = council.new_registry(
        {**MEMBER_KEYS, "intruder": bytes.fromhex("ee" * 32)})
    # intruder is NOT in the live registry `reg`, so its signature fails there.
    sigs = {
        "council-a": _sig(reg, "council-a", cid, st),
        "intruder": _sig(intruder_reg, "intruder", cid, st),
    }
    assert council.verify_ratification(cid, st, sigs, reg) is False


def test_5_invalid_hmac_blocks(reg):
    cid, st = "c-5", "RATIFIED"
    bad = "0" * 64  # not a real HMAC
    sigs = {"council-a": bad, "council-b": _sig(reg, "council-b", cid, st)}
    assert council.verify_ratification(cid, st, sigs, reg) is False


def test_6_modified_decision_blocks(reg):
    cid, st = "c-6", "RATIFIED"
    sigs = {
        "council-a": _sig(reg, "council-a", cid, st),
        "council-b": _sig(reg, "council-b", cid, st),
    }
    # Signatures bound to c-6; trying to ratify c-6-TAMPERED must fail.
    assert council.verify_ratification(cid + "-TAMPERED", st, sigs, reg) is False


def test_7_modified_target_state_blocks(reg):
    cid = "c-7"
    sigs = {
        "council-a": _sig(reg, "council-a", cid, "RATIFIED"),
        "council-b": _sig(reg, "council-b", cid, "RATIFIED"),
    }
    # Signatures were for RATIFIED; trying to ratify into PROMOTED (or any other
    # state) must fail because the signed payload differs.
    assert council.verify_ratification(cid, "PROMOTED", sigs, reg) is False


def test_8_wrong_decision_id_blocks(reg):
    cid = "c-8"
    sigs = {
        "council-a": _sig(reg, "council-a", cid, "RATIFIED"),
        "council-b": _sig(reg, "council-b", cid, "RATIFIED"),
    }
    assert council.verify_ratification("c-8-wrong", "RATIFIED", sigs, reg) is False


def test_14_ledger_verification_passes(reg):
    cid, st = "c-14", "RATIFIED"
    sigs = {
        "council-a": _sig(reg, "council-a", cid, st),
        "council-b": _sig(reg, "council-b", cid, st),
    }
    ok, ledger = council.ratify(cid, st, sigs, reg, [])
    assert ok is True
    assert len(ledger) == 1
    assert council.verify_ledger(ledger) is True
    assert ledger[0]["prev_hash"] == "GENESIS"


def test_15_ledger_tampering_fails(reg):
    cid, st = "c-15", "RATIFIED"
    sigs = {
        "council-a": _sig(reg, "council-a", cid, st),
        "council-b": _sig(reg, "council-b", cid, st),
    }
    ok, ledger = council.ratify(cid, st, sigs, reg, [])
    assert ok is True
    tampered = [dict(b) for b in ledger]
    tampered[0]["state"] = "PROMOTED"  # edit a committed block
    assert council.verify_ledger(tampered) is False


# ---------------------------------------------------------------------------
# Server-level contract tests (live Pocket OS demo, real endpoints)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    return httpx.Client(base_url=BASE, timeout=10.0)


@pytest.fixture()
def seeded(client):
    r = client.post("/api/login", json=ADMIN)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    reset = client.post("/api/demo/reset", headers=_auth(token))
    assert reset.status_code == 200, reset.text
    return token


def _auth(token):
    return {"Authorization": "Bearer " + token}


def _propose_council(client, token, title):
    r = client.post("/api/decisions/propose", headers=_auth(token),
                    json={"title": title, "send_to_council": True})
    assert r.status_code == 200, r.text
    did = r.json()["decision"]["decision_id"]
    r2 = client.post(f"/api/decisions/{did}/council-approve", headers=_auth(token), json={})
    assert r2.status_code == 200, r2.text
    return did


def _quorum(client, token, did):
    """Assemble a 2-member quorum via /council-sign."""
    sigs = {}
    for member in ("council-a", "council-b"):
        r = client.post(f"/api/decisions/{did}/council-sign",
                        headers=_auth(token), params={"member": member})
        assert r.status_code == 200, r.text
        sigs[member] = r.json()["signature"]
    return sigs


def _decisions(client):
    r = client.get("/api/decisions")
    assert r.status_code == 200, r.text
    return r.json()["decisions"]


def _decision(client, did):
    for d in _decisions(client):
        if d["decision_id"] == did:
            return d
    raise AssertionError(f"decision {did} not found")


# --- 9. forged claimed authority -> BLOCK (server-level) ---


def test_9_forged_claimed_authority_blocks(client, seeded):
    did = _propose_council(client, seeded, "forged auth " + uuid.uuid4().hex[:6])
    # No council signatures — only a forged HUMAN claim. Must be denied with
    # COUNCIL_QUORUM_NOT_MET (bearer RATIFY is insufficient).
    r = client.post(f"/api/decisions/{did}/ratify",
                    headers=_auth(seeded),
                    json={"claimed_authority": "HUMAN", "signatures": {}})
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["error"]["code"] == "COUNCIL_QUORUM_NOT_MET"


# --- 10. valid quorum -> authoritative ledger event (server-level) ---


def test_10_valid_quorum_records_authoritative_event(client, seeded):
    did = _propose_council(client, seeded, "quorum event " + uuid.uuid4().hex[:6])
    # Measure the ledger delta around the ratify call itself (propose and
    # council-approve already appended events above).
    before = len(client.get("/api/state").json()["records"])
    sigs = _quorum(client, seeded, did)
    r = client.post(f"/api/decisions/{did}/ratify",
                    headers=_auth(seeded), json={"signatures": sigs})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    after = len(client.get("/api/state").json()["records"])
    assert after == before + 1  # exactly ONE authoritative event appended

    # The recorded event is the authoritative ratification.
    state = client.get("/api/state").json()
    last = state["records"][-1]
    assert last["event"] == "decision.ratified"
    assert last["source"] == "Council"
    assert sorted(last["payload"]["ratifiers"]) == ["council-a", "council-b"]
    assert last["payload"]["authority"] == "COUNCIL_QUORUM"


# --- 11. valid quorum -> can_execute (server-level) ---


def test_11_valid_quorum_enables_execution(client, seeded):
    did = _propose_council(client, seeded, "quorum exec " + uuid.uuid4().hex[:6])
    sigs = _quorum(client, seeded, did)
    r = client.post(f"/api/decisions/{did}/ratify",
                    headers=_auth(seeded), json={"signatures": sigs})
    assert r.json()["ok"] is True
    d = _decision(client, did)
    assert d["status"] == "RATIFIED"
    assert d["human_ratified"] is True
    assert d["can_execute"] is True


# --- 12. no quorum -> no ratification event (server-level) ---


def test_12_no_quorum_no_ratification_event(client, seeded):
    did = _propose_council(client, seeded, "no quorum " + uuid.uuid4().hex[:6])
    # Measure the ledger delta around the ratify denial itself.
    before = len(client.get("/api/state").json()["records"])
    # Submit only ONE signature (below QUORUM=2).
    r1 = client.post(f"/api/decisions/{did}/council-sign",
                     headers=_auth(seeded), params={"member": "council-a"})
    sig = r1.json()["signature"]
    r = client.post(f"/api/decisions/{did}/ratify",
                    headers=_auth(seeded), json={"signatures": {"council-a": sig}})
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["error"]["code"] == "COUNCIL_QUORUM_NOT_MET"
    after = len(client.get("/api/state").json()["records"])
    assert after == before  # denial appended nothing
    assert _decision(client, did)["status"] != "RATIFIED"


# --- 13. already executed -> second execution blocked (server-level) ---


def test_13_second_execution_blocked(client, seeded):
    did = _propose_council(client, seeded, "once only " + uuid.uuid4().hex[:6])
    sigs = _quorum(client, seeded, did)
    client.post(f"/api/decisions/{did}/ratify", headers=_auth(seeded), json={"signatures": sigs})
    r1 = client.post(f"/api/decisions/{did}/execute", headers=_auth(seeded), json={})
    assert r1.json()["ok"] is True
    assert r1.json()["result"]["executed"] is True
    r2 = client.post(f"/api/decisions/{did}/execute", headers=_auth(seeded), json={})
    assert r2.json()["ok"] is False
    assert r2.json()["error"]["code"] == "EXECUTION_DENIED"


# --- End-to-end: full chain through the real backend ---


def test_end_to_end_council_chain(client, seeded):
    """council signatures -> threshold verification -> authoritative
    ratification -> Pocket OS ledger -> can_execute -> execution -> evidence."""
    title = "e2e chain " + uuid.uuid4().hex[:6]
    did = _propose_council(client, seeded, title)

    # 1. Two distinct council members sign.
    sigs = _quorum(client, seeded, did)
    assert len(sigs) == 2

    # 2. Threshold verification happens server-side; ratify emits the event.
    r = client.post(f"/api/decisions/{did}/ratify",
                    headers=_auth(seeded), json={"signatures": sigs})
    assert r.json()["ok"] is True
    d = _decision(client, did)
    assert d["status"] == "RATIFIED"
    assert d["can_execute"] is True

    # 3. Execution proceeds and records evidence.
    ex = client.post(f"/api/decisions/{did}/execute", headers=_auth(seeded), json={})
    assert ex.json()["ok"] is True
    assert ex.json()["result"]["executed"] is True
    d = _decision(client, did)
    assert d["status"] == "EXECUTED"
    assert d["executed_seq"] is not None

    # 4. The ledger records the full chain of events.
    state = client.get("/api/state").json()
    events = [r["event"] for r in state["records"]]
    assert "decision.proposed" in events
    assert "decision.council_approved" in events
    assert "decision.ratified" in events
    assert "decision.executed" in events
    assert state["integrity"] == "INTACT"


# ---------------------------------------------------------------------------
# Production key isolation (module-level gate)
# ---------------------------------------------------------------------------


def _reload_gate():
    """Re-import council_gate so the env-driven signing gate re-evaluates."""
    # Pop the module so the env var is read fresh on import.
    sys.modules.pop("pocketos_demo.engines.council_gate", None)
    import pocketos_demo.engines.council_gate as cg
    return cg


def test_16_production_default_disables_onbox_signing():
    """Production default (no POCKETOS_COUNCIL_DEMO_SIGNING): signing keys are
    not loaded and sign_for_member returns None — no raw key is reachable via
    the server-side signing helper."""
    os.environ.pop("POCKETOS_COUNCIL_DEMO_SIGNING", None)
    cg = _reload_gate()
    assert cg.signing_enabled() is False
    assert cg.sign_for_member("council-a", "x", "RATIFIED") is None
    # Verification still works in production (off-box signatures only).
    assert cg.verify_quorum("x", "RATIFIED", {}) is False  # no sigs -> no quorum


def test_17_demo_mode_enables_onbox_signing_only_for_harness():
    """Demo signing mode (POCKETOS_COUNCIL_DEMO_SIGNING=1) powers the local
    test harness and browser demo only."""
    os.environ["POCKETOS_COUNCIL_DEMO_SIGNING"] = "1"
    cg = _reload_gate()
    assert cg.signing_enabled() is True
    sig = cg.sign_for_member("council-a", "x", "RATIFIED")
    assert sig is not None
    # Restore production default for the rest of the process.
    os.environ.pop("POCKETOS_COUNCIL_DEMO_SIGNING", None)
    _reload_gate()


# ---------------------------------------------------------------------------
# Off-box signer utility (scripts/council_signer.py)
# ---------------------------------------------------------------------------


def _run_signer(*args):
    """Run the standalone off-box signer CLI and return its stdout JSON."""
    import subprocess
    out = subprocess.check_output(
        ["python3", os.path.join(ROOT_DIR, "scripts", "council_signer.py"), *args],
        stderr=subprocess.DEVNULL)
    return json.loads(out)


def test_18_offbox_signer_matches_contract_signature(tmp_path):
    """A signature produced by the standalone off-box signer must byte-match
    the authoritative council contract (same canonical payload + key)."""
    import subprocess
    keyfile = tmp_path / "member.key"
    keyfile.write_text("aa" * 32)  # 64 hex chars
    out = _run_signer("--candidate", "D-SIGN-1", "--state", "RATIFIED",
                      "--member", "council-a", "--key-file", str(keyfile))
    assert out["mode"] == "sign"
    assert out["signature"] == council.sign("D-SIGN-1", "RATIFIED", "council-a",
                                            bytes.fromhex("aa" * 32))


def test_19_offbox_signer_quorum_accepted(tmp_path):
    """Two members signing off-box must form a quorum the contract accepts."""
    a = tmp_path / "a.key"; a.write_text("aa" * 32)
    b = tmp_path / "b.key"; b.write_text("bb" * 32)
    sa = _run_signer("--candidate", "D-SIGN-2", "--state", "RATIFIED",
                     "--member", "council-a", "--key-file", str(a))["signature"]
    sb = _run_signer("--candidate", "D-SIGN-2", "--state", "RATIFIED",
                     "--member", "council-b", "--key-file", str(b))["signature"]
    reg = council.new_registry({"council-a": bytes.fromhex("aa" * 32),
                                "council-b": bytes.fromhex("bb" * 32)})
    assert council.verify_ratification("D-SIGN-2", "RATIFIED",
                                       {"council-a": sa, "council-b": sb}, reg)


def test_20_offbox_signer_show_payload_requires_no_key():
    """--show-payload prints the exact canonical JSON without any key."""
    import subprocess
    out = subprocess.check_output(
        ["python3", os.path.join(ROOT_DIR, "scripts", "council_signer.py"),
         "--candidate", "D-SIGN-3", "--state", "RATIFIED",
         "--member", "council-a", "--show-payload"])
    payload = out.decode().strip().splitlines()[0]
    assert json.loads(payload) == {"candidate_id": "D-SIGN-3",
                                   "ratifier": "council-a", "state": "RATIFIED"}
