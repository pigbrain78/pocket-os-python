"""Backend tests for Snapshot Bookmarks feature.

Covers:
- GET /api/replay/bookmarks: empty list for fresh user, sorted `at` desc after inserts
- POST /api/replay/bookmarks: happy path, ISO normalization, UUID id
- POST validation: blank label, > 80 char label, malformed `at`, missing `at`
- POST cap: 41st bookmark rejected
- DELETE /api/replay/bookmarks/{id}: happy path, 404 for non-existent, isolation
- Auth-required (401/403 without Bearer)
- User isolation (fresh user gets [])
- Ledger independence: /api/replay?at=<mid> byte-identical before/after bookmark cycle
- Regression sanity: /api/replay, /api/replay/bounds, /api/timeline, /api/ledger/verify,
  forgot-password (known email 200), reset-password bad code (400), admin-reset (503 unset)
"""

import os
import uuid as uuid_lib
from datetime import datetime, timezone

import pytest
import requests


BASE_URL = os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
if not BASE_URL:
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
    r = api.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def bounds(api, auth):
    r = api.get(f"{BASE_URL}/api/replay/bounds", headers=auth)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(autouse=True)
def _clean_bookmarks_before(api, auth):
    """Delete any pre-existing bookmarks for demo user before each test in this
    module to guarantee a clean slate. Runs before AND after every test."""
    # before
    _wipe(api, auth)
    yield
    # after
    _wipe(api, auth)


def _wipe(api, auth):
    r = api.get(f"{BASE_URL}/api/replay/bookmarks", headers=auth)
    if r.status_code != 200:
        return
    for b in r.json():
        api.delete(f"{BASE_URL}/api/replay/bookmarks/{b['id']}", headers=auth)


# --------------------------- GET tests ---------------------------
class TestListBookmarks:
    """GET /api/replay/bookmarks"""

    def test_empty_for_fresh_user(self, api, auth):
        r = api.get(f"{BASE_URL}/api/replay/bookmarks", headers=auth)
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_sorted_desc_by_at(self, api, auth, bounds):
        """Create 3 bookmarks with distinct `at` values, expect newest first."""
        earliest = datetime.fromisoformat(bounds["earliest"].replace("Z", "+00:00"))
        latest = datetime.fromisoformat(bounds["latest"].replace("Z", "+00:00"))
        span = (latest - earliest).total_seconds()
        assert span > 0

        # Three timestamps: 20%, 50%, 80% along the ledger
        t20 = earliest.timestamp() + span * 0.2
        t50 = earliest.timestamp() + span * 0.5
        t80 = earliest.timestamp() + span * 0.8

        def iso(ts):
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        # Insert in a non-sorted order to prove server sorts (not insert order)
        for label, ts in [("mid", t50), ("early", t20), ("late", t80)]:
            r = api.post(
                f"{BASE_URL}/api/replay/bookmarks",
                headers=auth,
                json={"label": label, "at": iso(ts)},
            )
            assert r.status_code == 200, r.text

        r = api.get(f"{BASE_URL}/api/replay/bookmarks", headers=auth)
        assert r.status_code == 200
        arr = r.json()
        assert len(arr) == 3
        labels = [b["label"] for b in arr]
        assert labels == ["late", "mid", "early"], f"not desc-sorted: {labels}"

        # Also confirm actual `at` strictly monotonically decreasing
        ats = [b["at"] for b in arr]
        assert ats == sorted(ats, reverse=True)


# --------------------------- POST happy + validation ---------------------------
class TestCreateBookmark:
    """POST /api/replay/bookmarks"""

    def test_happy_path_returns_full_shape(self, api, auth):
        payload = {"label": "The day I decided X", "at": "2026-08-15T10:00:00Z"}
        r = api.post(f"{BASE_URL}/api/replay/bookmarks", headers=auth, json=payload)
        assert r.status_code == 200, r.text
        doc = r.json()
        # Contract fields
        for k in ("id", "user_id", "label", "at", "created_at"):
            assert k in doc, f"missing key {k}"
        assert doc["label"] == "The day I decided X"
        # id is a UUID string
        uuid_lib.UUID(doc["id"])
        # `at` normalized: parseable ISO with tz info; original was 'Z'
        parsed = datetime.fromisoformat(doc["at"].replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        # Should represent the same instant as 2026-08-15T10:00:00Z
        expected = datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc)
        assert parsed == expected

        # _id must NOT leak
        assert "_id" not in doc

    def test_label_trimmed(self, api, auth):
        r = api.post(
            f"{BASE_URL}/api/replay/bookmarks",
            headers=auth,
            json={"label": "  keep me  ", "at": "2026-08-15T10:00:00Z"},
        )
        assert r.status_code == 200
        assert r.json()["label"] == "keep me"

    def test_blank_label_rejected(self, api, auth):
        r = api.post(
            f"{BASE_URL}/api/replay/bookmarks",
            headers=auth,
            json={"label": "", "at": "2026-08-15T10:00:00Z"},
        )
        assert r.status_code == 400
        assert r.json().get("detail") == "Label is required"

    def test_whitespace_only_label_rejected(self, api, auth):
        r = api.post(
            f"{BASE_URL}/api/replay/bookmarks",
            headers=auth,
            json={"label": "   \t  ", "at": "2026-08-15T10:00:00Z"},
        )
        assert r.status_code == 400
        assert r.json().get("detail") == "Label is required"

    def test_label_over_80_chars_rejected(self, api, auth):
        r = api.post(
            f"{BASE_URL}/api/replay/bookmarks",
            headers=auth,
            json={"label": "x" * 81, "at": "2026-08-15T10:00:00Z"},
        )
        assert r.status_code == 400
        assert r.json().get("detail") == "Label must be 80 characters or fewer"

    def test_label_exactly_80_chars_ok(self, api, auth):
        r = api.post(
            f"{BASE_URL}/api/replay/bookmarks",
            headers=auth,
            json={"label": "x" * 80, "at": "2026-08-15T10:00:00Z"},
        )
        assert r.status_code == 200
        assert len(r.json()["label"]) == 80

    def test_malformed_at_rejected(self, api, auth):
        r = api.post(
            f"{BASE_URL}/api/replay/bookmarks",
            headers=auth,
            json={"label": "foo", "at": "not-a-date"},
        )
        assert r.status_code == 400
        assert r.json().get("detail") == "Invalid timestamp"

    def test_empty_at_rejected(self, api, auth):
        r = api.post(
            f"{BASE_URL}/api/replay/bookmarks",
            headers=auth,
            json={"label": "foo", "at": ""},
        )
        assert r.status_code == 400
        assert r.json().get("detail") == "Invalid timestamp"

    def test_missing_at_rejected(self, api, auth):
        r = api.post(
            f"{BASE_URL}/api/replay/bookmarks",
            headers=auth,
            json={"label": "foo"},
        )
        # Pydantic 422 for missing required field
        assert r.status_code in (400, 422)


class TestBookmarkCap:
    """Per-user cap of 40."""

    def test_41st_bookmark_rejected(self, api, auth):
        base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        for i in range(40):
            r = api.post(
                f"{BASE_URL}/api/replay/bookmarks",
                headers=auth,
                json={"label": f"b{i}", "at": (base.replace(minute=i)).isoformat()},
            )
            assert r.status_code == 200, f"insert {i} failed: {r.text}"

        # 41st should fail
        r = api.post(
            f"{BASE_URL}/api/replay/bookmarks",
            headers=auth,
            json={"label": "overflow", "at": "2026-08-15T10:00:00Z"},
        )
        assert r.status_code == 400
        assert r.json().get("detail") == "Bookmark limit reached (40). Delete some first."

        # Ensure list is exactly 40
        r = api.get(f"{BASE_URL}/api/replay/bookmarks", headers=auth)
        assert r.status_code == 200
        assert len(r.json()) == 40


# --------------------------- DELETE tests ---------------------------
class TestDeleteBookmark:
    def test_delete_happy(self, api, auth):
        r = api.post(
            f"{BASE_URL}/api/replay/bookmarks",
            headers=auth,
            json={"label": "to delete", "at": "2026-08-15T10:00:00Z"},
        )
        assert r.status_code == 200
        bid = r.json()["id"]

        r = api.delete(f"{BASE_URL}/api/replay/bookmarks/{bid}", headers=auth)
        assert r.status_code == 200
        assert r.json() == {"ok": True}

        # Verify gone
        r = api.get(f"{BASE_URL}/api/replay/bookmarks", headers=auth)
        assert not any(b["id"] == bid for b in r.json())

    def test_delete_nonexistent_returns_404(self, api, auth):
        r = api.delete(
            f"{BASE_URL}/api/replay/bookmarks/{uuid_lib.uuid4()}", headers=auth
        )
        assert r.status_code == 404


# --------------------------- Auth tests ---------------------------
class TestAuthRequired:
    def test_get_without_token(self, api):
        r = api.get(f"{BASE_URL}/api/replay/bookmarks")
        assert r.status_code in (401, 403)

    def test_post_without_token(self, api):
        r = api.post(
            f"{BASE_URL}/api/replay/bookmarks",
            json={"label": "x", "at": "2026-08-15T10:00:00Z"},
        )
        assert r.status_code in (401, 403)

    def test_delete_without_token(self, api):
        r = api.delete(f"{BASE_URL}/api/replay/bookmarks/anything")
        assert r.status_code in (401, 403)


# --------------------------- Isolation tests ---------------------------
class TestIsolation:
    """Bookmarks must be strictly user-scoped."""

    def _register(self, api):
        email = f"TEST_bm_{uuid_lib.uuid4().hex[:10]}@example.com"
        r = api.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": email, "password": "P@ssw0rd123!", "name": "BM Test"},
        )
        if r.status_code != 200:
            pytest.skip(f"register unavailable: {r.status_code} {r.text[:100]}")
        return r.json()["token"], email

    def test_fresh_user_sees_empty_list(self, api, auth):
        # demo user creates one
        r = api.post(
            f"{BASE_URL}/api/replay/bookmarks",
            headers=auth,
            json={"label": "demo-only", "at": "2026-08-15T10:00:00Z"},
        )
        assert r.status_code == 200

        # Fresh user should get []
        other_tok, _ = self._register(api)
        r = api.get(
            f"{BASE_URL}/api/replay/bookmarks",
            headers={"Authorization": f"Bearer {other_tok}"},
        )
        assert r.status_code == 200
        assert r.json() == []

    def test_cannot_delete_other_users_bookmark(self, api, auth):
        r = api.post(
            f"{BASE_URL}/api/replay/bookmarks",
            headers=auth,
            json={"label": "demo-only", "at": "2026-08-15T10:00:00Z"},
        )
        assert r.status_code == 200
        bid = r.json()["id"]

        other_tok, _ = self._register(api)
        r = api.delete(
            f"{BASE_URL}/api/replay/bookmarks/{bid}",
            headers={"Authorization": f"Bearer {other_tok}"},
        )
        assert r.status_code == 404

        # Verify demo still has it
        r = api.get(f"{BASE_URL}/api/replay/bookmarks", headers=auth)
        assert any(b["id"] == bid for b in r.json())


# --------------------------- Ledger independence ---------------------------
class TestLedgerIndependence:
    """Bookmarks must NOT modify the ledger. /api/replay?at=<mid> should be
    byte-identical before and after a full bookmark create-delete cycle."""

    def test_replay_fold_unchanged(self, api, auth, bounds):
        earliest = datetime.fromisoformat(bounds["earliest"].replace("Z", "+00:00"))
        latest = datetime.fromisoformat(bounds["latest"].replace("Z", "+00:00"))
        mid_ts = earliest.timestamp() + (latest - earliest).total_seconds() * 0.5
        mid_iso = datetime.fromtimestamp(mid_ts, tz=timezone.utc).isoformat()

        # Capture BEFORE. Use params= so `+` in the ISO is percent-encoded
        # (otherwise the server sees a space and falls back to server_now).
        r_before = api.get(
            f"{BASE_URL}/api/replay", headers=auth, params={"at": mid_iso}
        )
        assert r_before.status_code == 200
        before = r_before.json()

        # Also capture ledger/verify
        v_before = api.get(f"{BASE_URL}/api/ledger/verify", headers=auth)
        assert v_before.status_code == 200

        # Create then delete a bookmark
        r = api.post(
            f"{BASE_URL}/api/replay/bookmarks",
            headers=auth,
            json={"label": "cycle", "at": mid_iso},
        )
        assert r.status_code == 200
        bid = r.json()["id"]
        r = api.delete(f"{BASE_URL}/api/replay/bookmarks/{bid}", headers=auth)
        assert r.status_code == 200

        # Capture AFTER
        r_after = api.get(
            f"{BASE_URL}/api/replay", headers=auth, params={"at": mid_iso}
        )
        assert r_after.status_code == 200
        after = r_after.json()

        # `now` field can drift by seconds — compare state + counters + at + bounds.
        for k in ("state", "events_seen", "events_after", "at", "bounds"):
            assert before[k] == after[k], f"{k} changed: {before[k]} vs {after[k]}"

        # Ledger verify should still succeed with same ledger head hash
        v_after = api.get(f"{BASE_URL}/api/ledger/verify", headers=auth)
        assert v_after.status_code == 200
        # If verify returns a head/hash, it should be identical (bookmarks don't
        # append events). Compare all non-time fields.
        b_json = v_before.json()
        a_json = v_after.json()
        # Focus on fields that would change if new events appended
        for k in ("count", "head", "hash", "ok", "valid"):
            if k in b_json:
                assert b_json.get(k) == a_json.get(k), f"ledger verify.{k} drifted"


# --------------------------- Regression sanity ---------------------------
class TestRegressions:
    def test_replay_bounds_still_works(self, api, auth):
        r = api.get(f"{BASE_URL}/api/replay/bounds", headers=auth)
        assert r.status_code == 200
        b = r.json()
        assert "earliest" in b and "latest" in b and "now" in b

    def test_replay_live_still_works(self, api, auth):
        r = api.get(f"{BASE_URL}/api/replay", headers=auth)
        assert r.status_code == 200
        j = r.json()
        assert j["events_after"] == 0

    def test_timeline_still_works(self, api, auth):
        r = api.get(f"{BASE_URL}/api/timeline", headers=auth)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_ledger_verify_still_works(self, api, auth):
        r = api.get(f"{BASE_URL}/api/ledger/verify", headers=auth)
        assert r.status_code == 200

    def test_forgot_password_known_email(self, api):
        r = api.post(
            f"{BASE_URL}/api/auth/forgot-password",
            json={"email": DEMO_EMAIL},
        )
        assert r.status_code == 200

    def test_reset_password_bad_code(self, api):
        r = api.post(
            f"{BASE_URL}/api/auth/reset-password",
            json={"email": DEMO_EMAIL, "code": "000000", "new_password": "whatever123"},
        )
        assert r.status_code == 400

    def test_admin_reset_password_503_when_unset(self, api):
        r = api.post(
            f"{BASE_URL}/api/auth/admin/reset-password",
            json={
                "admin_token": "nonsense",
                "email": DEMO_EMAIL,
                "new_password": "whatever123",
            },
        )
        # Should be 503 (unset) or 401 (wrong token). We accept 503 per contract.
        assert r.status_code in (503, 401, 403)
