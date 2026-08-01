"""Pocket OS backend tests - covers auth, seed, console, timeline, graph, notes/council/evolve, decisions, health, twin, shadow"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://thinking-replay.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

DEMO_EMAIL = "demo@pocketos.app"
DEMO_PW = "pocketos123"


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PW}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---- Auth ----
class TestAuth:
    def test_login_success(self):
        r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PW}, timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert "token" in j and "user" in j and j["user"]["email"] == DEMO_EMAIL

    def test_login_bad_password(self):
        r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": "wrong"}, timeout=30)
        assert r.status_code == 401

    def test_me(self, auth):
        r = requests.get(f"{API}/auth/me", headers=auth, timeout=30)
        assert r.status_code == 200
        assert r.json()["email"] == DEMO_EMAIL

    def test_register_new_user(self):
        email = f"test_{int(time.time())}@example.com"
        r = requests.post(f"{API}/auth/register", json={"email": email, "password": "testpass1", "name": "Test User"}, timeout=30)
        assert r.status_code == 200, r.text
        assert "token" in r.json()


# ---- Console ----
class TestConsole:
    def test_console(self, auth):
        r = requests.get(f"{API}/console", headers=auth, timeout=60)
        assert r.status_code == 200
        j = r.json()
        for key in ["brain_activity", "inbox", "new_knowledge", "council_recommendations", "pocket_score", "focus"]:
            assert key in j, f"missing {key}"
        assert "compounding" in j["pocket_score"]


# ---- Timeline ----
class TestTimeline:
    def test_timeline(self, auth):
        r = requests.get(f"{API}/timeline", headers=auth, timeout=30)
        assert r.status_code == 200
        events = r.json()
        assert isinstance(events, list) and len(events) > 0
        assert "kind" in events[0] and "created_at" in events[0]


# ---- Graph ----
class TestGraph:
    def test_graph(self, auth):
        r = requests.get(f"{API}/graph", headers=auth, timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert "nodes" in j and "edges" in j
        assert len(j["nodes"]) > 0


# ---- Notes / Council / Evolve ----
class TestNotes:
    def test_list_notes(self, auth):
        r = requests.get(f"{API}/notes", headers=auth, timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_note_and_verify(self, auth):
        payload = {"text": "TEST_ Adopt vector search for note retrieval to improve recall.", "title": "TEST_ Vector Search"}
        r = requests.post(f"{API}/notes", headers=auth, json=payload, timeout=90)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "note" in j and "memory" in j
        assert j["memory"]["after"] >= j["memory"]["before"]
        note_id = j["note"]["id"]

        # Verify persistence
        r2 = requests.get(f"{API}/notes/{note_id}", headers=auth, timeout=30)
        assert r2.status_code == 200
        assert r2.json()["note"]["id"] == note_id

    def test_council(self, auth):
        notes = requests.get(f"{API}/notes", headers=auth, timeout=30).json()
        note_id = notes[0]["id"]
        r = requests.post(f"{API}/notes/{note_id}/council", headers=auth, timeout=120)
        assert r.status_code == 200
        responses = r.json()["responses"]
        assert len(responses) == 5
        agent_names = {x["agent"] for x in responses}
        assert {"Research", "Architect", "Critic", "Planner", "Documentation Steward"} <= agent_names

    def test_evolve(self, auth):
        notes = requests.get(f"{API}/notes", headers=auth, timeout=30).json()
        note_id = notes[0]["id"]
        r = requests.post(f"{API}/notes/{note_id}/evolve", headers=auth,
                         json={"text": "Refined version of the idea."}, timeout=60)
        assert r.status_code == 200
        assert r.json()["stage"] in ["Idea", "Refined", "Merged", "Implemented", "Shipped", "Revenue"]


# ---- Decisions ----
class TestDecisions:
    def test_create_decision(self, auth):
        r = requests.post(f"{API}/decisions", headers=auth,
                         json={"title": "TEST_ Adopt strict typing", "context": "Reduce runtime errors"}, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["number"] >= 1
        assert d["affected_projects"] >= 3


# ---- Health Dashboard ----
class TestHealth:
    def test_health(self, auth):
        r = requests.get(f"{API}/health-dashboard", headers=auth, timeout=30)
        assert r.status_code == 200
        j = r.json()
        for k in ["overall", "density", "coverage", "freshness", "duplicate_risk", "unlinked", "totals"]:
            assert k in j


# ---- Twin ----
class TestTwin:
    def test_twin(self, auth):
        r = requests.post(f"{API}/twin/predict", headers=auth,
                         json={"question": "What should I focus on next quarter?"}, timeout=120)
        assert r.status_code == 200
        assert isinstance(r.json().get("answer"), str) and len(r.json()["answer"]) > 5


# ---- Shadow ----
class TestShadow:
    def test_shadow(self, auth):
        r = requests.get(f"{API}/shadow", headers=auth, timeout=120)
        assert r.status_code == 200
        j = r.json()
        assert "insights" in j and "top_patterns" in j
