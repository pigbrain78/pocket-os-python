"""Pocket OS credibility/hardening pass tests.

Covers ONLY the surgically patched surfaces (Jan 2026 pass):
- POST /api/decisions no longer randomizes referenced_notes / influenced_agents /
  affected_projects / produced_tasks
- GET /api/cognitive-dna returns bounded score + confidence + evidence per trait
- POST /api/twin/predict returns structured MODEL PREDICTION shape
- GET /api/shadow returns DESCRIPTIVE MODEL kind + description
- POST /api/admin/cleanup-test-notes is idempotent + records ledger event
- Ledger integrity preserved after cleanup
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://thinking-replay.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

DEMO_EMAIL = "demo@pocketos.app"
DEMO_PW = "pocketos123"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PW}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------
# Decisions — no more fabricated metrics
# ------------------------------------------------------------------
class TestDecisionsCredibility:
    """POST /api/decisions must return evidence-backed counts (no random.randint)."""

    def test_decision_on_note_uses_real_signals(self, auth):
        # Create a source note with unique concepts
        stamp = int(time.time())
        note_payload = {
            "title": f"CRED_ Vector Cache {stamp}",
            "text": "Vector cache warmup schema for pipeline runtime governance architecture.",
        }
        r = requests.post(f"{API}/notes", headers=auth, json=note_payload, timeout=90)
        assert r.status_code == 200, r.text
        src_note = r.json()["note"]
        src_id = src_note["id"]
        src_concepts = src_note.get("concepts") or []

        # Peer notes sharing at least one concept with the source
        peer_count = 0
        if src_concepts:
            peer_resp = requests.get(f"{API}/notes", headers=auth, timeout=30)
            assert peer_resp.status_code == 200
            peers = peer_resp.json()
            for p in peers:
                if p["id"] == src_id:
                    continue
                pc = p.get("concepts") or []
                if any(c in pc for c in src_concepts):
                    peer_count += 1

        # Create decision on this note
        d = requests.post(
            f"{API}/decisions",
            headers=auth,
            json={"title": f"CRED_ Adopt vector cache {stamp}", "context": "Reduce cold path", "note_id": src_id},
            timeout=30,
        )
        assert d.status_code == 200, d.text
        dec = d.json()

        # No council convened => influenced_agents == 0
        assert dec["influenced_agents"] == 0, f"expected 0 influenced_agents, got {dec['influenced_agents']}"
        # Downstream artifacts default to 0
        assert dec["affected_projects"] == 0, f"expected 0 affected_projects, got {dec['affected_projects']}"
        assert dec["produced_tasks"] == 0, f"expected 0 produced_tasks, got {dec['produced_tasks']}"
        # referenced_notes = real shared-concept peer count
        assert dec["referenced_notes"] == peer_count, (
            f"expected referenced_notes={peer_count} (peers sharing concept), got {dec['referenced_notes']}"
        )

    def test_decision_after_council_reflects_agent_count(self, auth):
        stamp = int(time.time())
        r = requests.post(
            f"{API}/notes",
            headers=auth,
            json={"title": f"CRED_ Council Guard {stamp}", "text": "Governance sandbox review provenance audit runtime."},
            timeout=90,
        )
        assert r.status_code == 200
        note_id = r.json()["note"]["id"]

        # Convene council on the note
        c = requests.post(f"{API}/notes/{note_id}/council", headers=auth, timeout=120)
        assert c.status_code == 200
        responses = c.json().get("responses", [])
        agents = {resp["agent"] for resp in responses}

        d = requests.post(
            f"{API}/decisions",
            headers=auth,
            json={"title": f"CRED_ Council-driven decision {stamp}", "note_id": note_id},
            timeout=30,
        )
        assert d.status_code == 200, d.text
        dec = d.json()

        assert dec["influenced_agents"] == len(agents), (
            f"expected influenced_agents={len(agents)} (distinct council agents), got {dec['influenced_agents']}"
        )
        assert dec["affected_projects"] == 0
        assert dec["produced_tasks"] == 0

    def test_decision_without_note_has_zero_signals(self, auth):
        stamp = int(time.time())
        d = requests.post(
            f"{API}/decisions",
            headers=auth,
            json={"title": f"CRED_ Standalone {stamp}", "context": "no source note"},
            timeout=30,
        )
        assert d.status_code == 200, d.text
        dec = d.json()
        assert dec["referenced_notes"] == 0
        assert dec["influenced_agents"] == 0
        assert dec["affected_projects"] == 0
        assert dec["produced_tasks"] == 0


# ------------------------------------------------------------------
# Cognitive DNA — schema, bounded score, confidence, evidence
# ------------------------------------------------------------------
class TestCognitiveDNA:
    def test_dna_shape_and_bounds(self, auth):
        r = requests.get(f"{API}/cognitive-dna", headers=auth, timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()

        # Top-level shape
        for k in ("traits", "total_signals", "notes_analyzed", "disclaimer"):
            assert k in j, f"missing top-level key {k}"
        assert isinstance(j["traits"], list) and len(j["traits"]) >= 6
        assert isinstance(j["total_signals"], int)
        assert isinstance(j["notes_analyzed"], int)
        assert isinstance(j["disclaimer"], str) and len(j["disclaimer"]) > 0

        for t in j["traits"]:
            # Per-trait keys
            for k in ("trait", "score", "confidence", "evidence", "evidence_count", "counter_signal"):
                assert k in t, f"trait {t.get('trait')} missing {k}"

            # Score bounded 20..95
            assert isinstance(t["score"], int), f"score not int for {t['trait']}"
            assert 20 <= t["score"] <= 95, f"score {t['score']} out of [20,95] for {t['trait']}"
            assert t["score"] not in (99, 100), f"unbounded score {t['score']}"

            # Confidence bounded 0.15..0.9
            assert isinstance(t["confidence"], (int, float))
            assert 0.15 <= t["confidence"] <= 0.9, f"confidence {t['confidence']} out of [0.15,0.9]"

            # Evidence list + count
            assert isinstance(t["evidence"], list)
            for ev in t["evidence"]:
                assert "id" in ev and "title" in ev
            assert isinstance(t["evidence_count"], int) and t["evidence_count"] >= 0

            # counter_signal is None or a dict with trait+hits+note
            cs = t["counter_signal"]
            assert cs is None or (isinstance(cs, dict) and {"trait", "hits", "note"} <= set(cs.keys()))


# ------------------------------------------------------------------
# Cognitive Twin — MODEL PREDICTION schema
# ------------------------------------------------------------------
class TestTwinPredict:
    def test_twin_returns_structured_prediction(self, auth):
        r = requests.post(
            f"{API}/twin/predict",
            headers=auth,
            json={"question": "What would I probably prioritize next?"},
            timeout=120,
        )
        assert r.status_code == 200, r.text
        j = r.json()

        # New schema — old {answer: str} shape is gone
        assert "answer" not in j, "twin still returns legacy {answer} shape"
        for k in ("prediction", "confidence", "evidence", "evidence_count", "counter_signal", "reasoning", "kind"):
            assert k in j, f"twin missing {k}"

        assert j["kind"] == "MODEL PREDICTION"
        assert isinstance(j["prediction"], str) and len(j["prediction"]) > 3
        assert isinstance(j["confidence"], (int, float))
        assert 0.0 <= j["confidence"] <= 0.9, f"confidence {j['confidence']} outside 0..0.9"
        assert isinstance(j["evidence"], list)
        for ev in j["evidence"]:
            assert "kind" in ev and "id" in ev and "title" in ev
        assert isinstance(j["evidence_count"], int) and j["evidence_count"] >= 0
        assert j["counter_signal"] is None or isinstance(j["counter_signal"], str)
        assert isinstance(j["reasoning"], str)


# ------------------------------------------------------------------
# AI Shadow — DESCRIPTIVE MODEL
# ------------------------------------------------------------------
class TestShadowDescriptive:
    def test_shadow_has_kind_and_description(self, auth):
        r = requests.get(f"{API}/shadow", headers=auth, timeout=120)
        assert r.status_code == 200
        j = r.json()
        assert "insights" in j
        assert "top_patterns" in j
        assert j.get("kind") == "DESCRIPTIVE MODEL", f"kind={j.get('kind')}"
        assert isinstance(j.get("description"), str) and len(j["description"]) > 0


# ------------------------------------------------------------------
# Cleanup endpoint — idempotent + ledger event
# ------------------------------------------------------------------
class TestCleanup:
    def test_cleanup_idempotent_and_ledger_event(self, auth):
        # Seed one obvious TEST_ artifact to ensure first call has something to delete
        stamp = int(time.time())
        seed = requests.post(
            f"{API}/notes",
            headers=auth,
            json={"title": f"TEST_ ephemeral cleanup {stamp}", "text": "seed for cleanup test"},
            timeout=60,
        )
        assert seed.status_code == 200

        first = requests.post(f"{API}/admin/cleanup-test-notes", headers=auth, timeout=60)
        assert first.status_code == 200, first.text
        f1 = first.json()
        assert "deleted" in f1 and "titles" in f1
        assert isinstance(f1["deleted"], int) and f1["deleted"] >= 1
        assert isinstance(f1["titles"], list)

        # Idempotent — second call should find nothing
        second = requests.post(f"{API}/admin/cleanup-test-notes", headers=auth, timeout=60)
        assert second.status_code == 200
        f2 = second.json()
        assert f2["deleted"] == 0, f"cleanup not idempotent — 2nd call deleted {f2['deleted']}"
        assert f2["titles"] == []

    def test_ledger_verifies_and_has_cleanup_event(self, auth):
        # Ensure ledger integrity intact after cleanup
        v = requests.get(f"{API}/ledger/verify", headers=auth, timeout=30)
        assert v.status_code == 200, v.text
        j = v.json()
        assert j.get("verified") is True, f"ledger not verified: {j}"
        assert j.get("breaks") == [], f"ledger breaks present: {j.get('breaks')}"

        # test_data_cleaned event appears in filtered feed
        e = requests.get(f"{API}/ledger/events", headers=auth, params={"kinds": "test_data_cleaned"}, timeout=30)
        assert e.status_code == 200
        events = e.json() if isinstance(e.json(), list) else e.json().get("events", [])
        assert isinstance(events, list) and len(events) >= 1, "no test_data_cleaned event found in ledger"
        assert all(ev.get("kind") == "test_data_cleaned" for ev in events)
