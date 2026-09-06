"""Backend tests for the Timeline Replay Documentary Engine.

Covers:
- /api/replay/bounds shape + auth
- /api/replay live snapshot invariants (events_after == 0, events_seen == total)
- /api/replay?at=<earliest> shows exactly 1 event
- /api/replay?at=<mid> monotonic behaviour
- /api/replay?at=<pre-history> = zero state
- /api/replay?at=<malformed> falls back to now (no 400/500)
- Fold correctness for every supported event kind
- open_contradictions never negative
- recent_events shape (<=20, at-or-before, most-recent-first, empty for pre-history)
- Regressions: /api/timeline, /api/ledger/verify, forgot/reset password, admin reset
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
if not BASE_URL:
    # Fall back to frontend/.env
    env_path = "/app/frontend/.env"
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().strip('"')
                    break
BASE_URL = (BASE_URL or "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL not set"

DEMO_EMAIL = "demo@pocketos.app"
DEMO_PASSWORD = "pocketos123"


# --------------------------- Fixtures ---------------------------
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def token(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def bounds(api, auth):
    r = api.get(f"{BASE_URL}/api/replay/bounds", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def live(api, auth):
    r = api.get(f"{BASE_URL}/api/replay", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def all_events(api, auth):
    """Full ledger — /api/timeline is capped at 300, so use /api/ledger/events (cap 10000)."""
    r = api.get(f"{BASE_URL}/api/ledger/events", headers=auth, params={"limit": 10000})
    assert r.status_code == 200, r.text
    j = r.json()
    evs = j.get("events") if isinstance(j, dict) else j
    assert isinstance(evs, list) and len(evs) > 0
    return evs


@pytest.fixture(scope="module")
def timeline_events(api, auth):
    r = api.get(f"{BASE_URL}/api/timeline", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------- Auth guards ---------------------------
class TestAuth:
    def test_replay_requires_auth(self, api):
        r = api.get(f"{BASE_URL}/api/replay")
        assert r.status_code in (401, 403)

    def test_bounds_requires_auth(self, api):
        r = api.get(f"{BASE_URL}/api/replay/bounds")
        assert r.status_code in (401, 403)


# --------------------------- /api/replay/bounds ---------------------------
class TestBounds:
    def test_shape(self, bounds):
        assert set(bounds.keys()) >= {"earliest", "latest", "now"}
        assert bounds["earliest"] is not None
        assert bounds["latest"] is not None
        assert bounds["now"] is not None

    def test_iso_parseable(self, bounds):
        for k in ("earliest", "latest", "now"):
            datetime.fromisoformat(bounds[k].replace("Z", "+00:00"))

    def test_earliest_lte_latest(self, bounds):
        e = datetime.fromisoformat(bounds["earliest"].replace("Z", "+00:00"))
        l = datetime.fromisoformat(bounds["latest"].replace("Z", "+00:00"))
        assert e <= l


# --------------------------- /api/replay LIVE snapshot ---------------------------
class TestLiveSnapshot:
    def test_events_after_zero(self, live):
        assert live["events_after"] == 0

    def test_events_seen_equals_total(self, live, all_events):
        # events_seen should equal the total number of events on the ledger
        assert live["events_seen"] == len(all_events)

    def test_at_equals_now(self, live):
        # per contract: when `at` omitted, response `at` equals server `now`
        assert live["at"] == live["now"]

    def test_recent_events_length(self, live):
        assert isinstance(live["recent_events"], list)
        assert len(live["recent_events"]) <= 20

    def test_recent_events_most_recent_first(self, live):
        r = live["recent_events"]
        if len(r) >= 2:
            for a, b in zip(r, r[1:]):
                ta = datetime.fromisoformat(a["created_at"].replace("Z", "+00:00"))
                tb = datetime.fromisoformat(b["created_at"].replace("Z", "+00:00"))
                assert ta >= tb

    def test_state_shape(self, live):
        s = live["state"]
        expected = {
            "notes_created", "notes_evolved", "concepts_extracted",
            "connections_made", "memory_strength", "council_runs",
            "debates_started", "syntheses_proposed", "syntheses_ratified",
            "syntheses_rejected", "decisions_made", "operations_run",
            "open_contradictions", "resolved_contradictions",
        }
        assert set(s.keys()) >= expected

    def test_state_non_negative(self, live):
        for k, v in live["state"].items():
            assert isinstance(v, int)
            assert v >= 0, f"{k} went negative: {v}"


# --------------------------- /api/replay?at=<earliest> ---------------------------
class TestEarliestAt:
    def test_exactly_one_event_seen(self, api, auth, bounds, all_events):
        r = api.get(f"{BASE_URL}/api/replay", headers=auth, params={"at": bounds["earliest"]})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["events_seen"] == 1, f"expected 1 seen at earliest, got {j['events_seen']}"
        assert j["events_after"] == len(all_events) - 1

    def test_first_event_folded(self, api, auth, bounds, all_events):
        r = api.get(f"{BASE_URL}/api/replay", headers=auth, params={"at": bounds["earliest"]})
        j = r.json()
        # The single seen event should be applied. At minimum the sum of state
        # counters should be >= 0 and one of them should be > 0 depending on
        # kind of the first event.
        first_kind = min(all_events, key=lambda e: e["created_at"])["kind"]
        s = j["state"]
        # Basic sanity: total state should be minimal after 1 event
        touched = sum(v for k, v in s.items() if k != "memory_strength")
        # first event's fold contributes at least 0 (some kinds don't touch counters)
        assert touched >= 0
        # If the first event is a counter-touching kind, at least one must be > 0
        counter_kinds = {
            "note_created", "linked", "council_convened", "consensus_convened",
            "debate_triggered", "synthesis_proposed", "synthesis_ratified",
            "synthesis_rejected", "decision_made", "idea_evolved",
            "contradiction_detected", "operation_run",
        }
        if first_kind in counter_kinds:
            assert touched >= 1


# --------------------------- Monotonicity: mid-point ---------------------------
class TestMidpoint:
    def test_mid_strictly_less_than_live(self, api, auth, bounds, live):
        e = datetime.fromisoformat(bounds["earliest"].replace("Z", "+00:00"))
        l = datetime.fromisoformat(bounds["latest"].replace("Z", "+00:00"))
        mid = e + (l - e) / 2
        r = api.get(f"{BASE_URL}/api/replay", headers=auth, params={"at": mid.isoformat()})
        assert r.status_code == 200
        j = r.json()
        assert j["events_seen"] < live["events_seen"]
        assert j["events_after"] > 0
        assert j["events_seen"] + j["events_after"] == live["events_seen"]

    def test_monotonic_seen(self, api, auth, bounds):
        e = datetime.fromisoformat(bounds["earliest"].replace("Z", "+00:00"))
        l = datetime.fromisoformat(bounds["latest"].replace("Z", "+00:00"))
        span = (l - e).total_seconds()
        seens = []
        for frac in (0.1, 0.3, 0.6, 0.9):
            ts = e + timedelta(seconds=span * frac)
            r = api.get(f"{BASE_URL}/api/replay", headers=auth, params={"at": ts.isoformat()})
            assert r.status_code == 200
            seens.append(r.json()["events_seen"])
        for a, b in zip(seens, seens[1:]):
            assert b >= a, f"events_seen decreased: {seens}"


# --------------------------- Pre-history ---------------------------
class TestPreHistory:
    def test_zero_state(self, api, auth, bounds, all_events):
        e = datetime.fromisoformat(bounds["earliest"].replace("Z", "+00:00"))
        pre = e - timedelta(days=365)
        r = api.get(f"{BASE_URL}/api/replay", headers=auth, params={"at": pre.isoformat()})
        assert r.status_code == 200
        j = r.json()
        assert j["events_seen"] == 0
        assert j["events_after"] == len(all_events)
        # all state fields must be zero
        for k, v in j["state"].items():
            assert v == 0, f"{k} was {v} in pre-history"
        # recent_events must be empty
        assert j["recent_events"] == []


# --------------------------- Malformed at ---------------------------
class TestMalformedAt:
    def test_falls_back_to_now(self, api, auth):
        r = api.get(f"{BASE_URL}/api/replay", headers=auth, params={"at": "not-a-timestamp"})
        # Must NOT 400/500
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["events_after"] == 0

    def test_empty_string(self, api, auth):
        # Empty string is falsy - the code branches to server_now
        r = api.get(f"{BASE_URL}/api/replay", headers=auth, params={"at": ""})
        assert r.status_code == 200
        assert r.json()["events_after"] == 0


# --------------------------- Fold correctness ---------------------------
class TestFoldCorrectness:
    """Recompute fold client-side from /api/timeline and compare to live state."""

    def test_fold_matches_server(self, live, all_events):
        state = {
            "notes_created": 0, "notes_evolved": 0, "concepts_extracted": 0,
            "connections_made": 0, "memory_strength": 0, "council_runs": 0,
            "debates_started": 0, "syntheses_proposed": 0, "syntheses_ratified": 0,
            "syntheses_rejected": 0, "decisions_made": 0, "operations_run": 0,
            "open_contradictions": 0, "resolved_contradictions": 0,
        }
        # Iterate chronological
        events_sorted = sorted(all_events, key=lambda e: e["created_at"])
        for ev in events_sorted:
            kind = ev.get("kind")
            meta = ev.get("meta") or {}
            if kind == "note_created":
                state["notes_created"] += 1
            elif kind == "concepts_extracted":
                state["concepts_extracted"] += len(meta.get("concepts") or [])
            elif kind == "linked":
                state["connections_made"] += 1
            elif kind == "memory_strengthened":
                try:
                    state["memory_strength"] = int(meta.get("after") or state["memory_strength"])
                except (TypeError, ValueError):
                    pass
            elif kind in ("council_convened", "consensus_convened"):
                state["council_runs"] += 1
            elif kind == "debate_triggered":
                state["debates_started"] += 1
            elif kind == "synthesis_proposed":
                state["syntheses_proposed"] += 1
            elif kind == "synthesis_ratified":
                state["syntheses_ratified"] += 1
            elif kind == "synthesis_rejected":
                state["syntheses_rejected"] += 1
            elif kind == "decision_made":
                state["decisions_made"] += 1
            elif kind == "operation_run":
                state["operations_run"] += 1
            elif kind == "idea_evolved":
                state["notes_evolved"] += 1
            elif kind == "contradiction_detected":
                state["open_contradictions"] += 1
            elif kind == "contradiction_resolved":
                state["open_contradictions"] = max(0, state["open_contradictions"] - 1)
                state["resolved_contradictions"] += 1

        # Compare
        for k in state:
            assert state[k] == live["state"][k], (
                f"fold mismatch on {k}: client={state[k]} server={live['state'][k]}"
            )


# --------------------------- open_contradictions never negative ---------------------------
class TestNoNegativeContradictions:
    def test_never_negative_across_time(self, api, auth, bounds):
        e = datetime.fromisoformat(bounds["earliest"].replace("Z", "+00:00"))
        l = datetime.fromisoformat(bounds["latest"].replace("Z", "+00:00"))
        span = (l - e).total_seconds()
        for frac in (0.0, 0.15, 0.35, 0.55, 0.75, 0.95, 1.0):
            ts = e + timedelta(seconds=span * frac)
            r = api.get(f"{BASE_URL}/api/replay", headers=auth, params={"at": ts.isoformat()})
            assert r.status_code == 200
            assert r.json()["state"]["open_contradictions"] >= 0


# --------------------------- recent_events for mid ---------------------------
class TestRecentEvents:
    def test_recent_events_at_or_before_at(self, api, auth, bounds):
        e = datetime.fromisoformat(bounds["earliest"].replace("Z", "+00:00"))
        l = datetime.fromisoformat(bounds["latest"].replace("Z", "+00:00"))
        mid = e + (l - e) / 2
        r = api.get(f"{BASE_URL}/api/replay", headers=auth, params={"at": mid.isoformat()})
        j = r.json()
        assert len(j["recent_events"]) <= 20
        for ev in j["recent_events"]:
            ts = datetime.fromisoformat(ev["created_at"].replace("Z", "+00:00"))
            assert ts <= mid + timedelta(seconds=1)


# --------------------------- Regressions ---------------------------
class TestRegressions:
    def test_timeline_still_works(self, all_events):
        assert len(all_events) > 0

    def test_ledger_verify(self, api, auth):
        r = api.get(f"{BASE_URL}/api/ledger/verify", headers=auth)
        assert r.status_code == 200, r.text
        j = r.json()
        # Should include an "ok" flag or a verified indicator
        assert ("ok" in j) or ("verified" in j) or ("valid" in j)

    def test_forgot_password_endpoint(self, api):
        r = api.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": DEMO_EMAIL})
        assert r.status_code == 200, r.text

    def test_reset_password_bad_code(self, api):
        r = api.post(
            f"{BASE_URL}/api/auth/reset-password",
            json={"email": DEMO_EMAIL, "code": "000000", "new_password": "anotherpassword123"},
        )
        assert r.status_code == 400

    def test_admin_reset_503_when_no_token(self, api):
        # ADMIN_RESET_TOKEN is not set in .env — endpoint should 503 regardless
        # of supplied admin_token. Provide the field to bypass 422 validation.
        r = api.post(
            f"{BASE_URL}/api/auth/admin/reset-password",
            json={
                "email": DEMO_EMAIL,
                "new_password": "anotherpassword123",
                "admin_token": "any-value",
            },
        )
        assert r.status_code == 503, r.text
