"""Auth-hardening tests for the Pocket OS demo.

Verifies the hardened credential + session layer:

  * credentials are stored as PBKDF2 hashes (no plaintext "demo" in USERS)
  * the hash round-trips and rejects wrong/garbage values
  * login rejects wrong password and unknown usernames
  * sessions carry a server-issued expiry and /api/session/me reports TTL
  * expired sessions are rejected (server clock is authoritative)
  * logout revokes the token so it cannot be reused
  * permissions still gate consequential actions

Uses an in-process FastAPI TestClient so expiry/revocation can be driven
deterministically by mutating the module session registry.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import pytest
from fastapi.testclient import TestClient

import pocketos_demo.app as A

client = TestClient(A.app)


@pytest.fixture(autouse=True)
def _clean_sessions():
    with A._SESSION_LOCK:
        A._SESSIONS.clear()
    yield
    with A._SESSION_LOCK:
        A._SESSIONS.clear()


def _login(username="admin", password="demo"):
    r = client.post("/api/login", json={"username": username, "password": password})
    return r


# ---------------------------------------------------------------------------
# Credential hashing
# ---------------------------------------------------------------------------


def test_no_plaintext_password_stored():
    for username, user in A.USERS.items():
        assert "password_hash" in user
        assert user["password_hash"].startswith("pbkdf2_sha256$")
        # the plaintext demo password must never appear in the stored record
        assert "demo" not in user["password_hash"]
        assert "demo" not in str(user["permissions"])


def test_stored_hashes_verify_demo_password():
    for username, user in A.USERS.items():
        assert A._verify_password("demo", user["password_hash"]), username


def test_hash_round_trip_and_rejects():
    h = A._hash_password("a-strong-password")
    assert A._verify_password("a-strong-password", h)
    assert not A._verify_password("wrong", h)
    assert not A._verify_password("a-strong-password", "garbage-not-a-hash")
    # a valid-format hash with the wrong salt/algo content must not verify
    assert not A._verify_password("demo", "md5$1000$c2FsdA==$aGVsbG8=")


def test_passwords_salted_and_unique():
    # two hashes of the same password differ (unique salt per call)
    assert A._hash_password("demo") != A._hash_password("demo")


def test_dummy_hash_exists_for_timing_equalization():
    assert len(A._DUMMY_HASH.split("$")) == 4
    assert A._DUMMY_HASH.startswith("pbkdf2_sha256$")


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_success_issues_session_with_expiry():
    r = _login()
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["subject"] == "admin"
    assert body["expires_at"] > int(time.time())
    assert "ADMIN" in body["permissions"]


def test_login_wrong_password_rejected():
    assert _login(password="wrong").status_code == 401


def test_login_unknown_user_rejected():
    assert _login(username="ghost").status_code == 401


def test_session_me_reports_ttl():
    tok = _login().json()["token"]
    r = client.get("/api/session/me", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "admin"
    assert body["ttl_seconds"] > 0
    assert body["ttl_seconds"] <= A._SESSION_TTL


# ---------------------------------------------------------------------------
# Expiry (server clock authoritative)
# ---------------------------------------------------------------------------


def test_expired_session_is_rejected():
    tok = _login().json()["token"]
    # force the session to have expired
    with A._SESSION_LOCK:
        A._SESSIONS[tok]["expires_at"] = int(time.time()) - 1
    r = client.get("/api/session/me", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 401
    # an expired session must not be able to perform consequential actions
    r = client.post("/api/decisions/propose", headers={"Authorization": "Bearer " + tok},
                    json={"title": "should not pass"})
    assert r.status_code == 401
    # the expired session should be purged from the registry
    with A._SESSION_LOCK:
        assert tok not in A._SESSIONS


def test_fresh_session_not_expired():
    tok = _login().json()["token"]
    r = client.get("/api/session/me", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Revocation / logout
# ---------------------------------------------------------------------------


def test_logout_revokes_token():
    tok = _login().json()["token"]
    r = client.post("/api/logout", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200
    # the token must no longer be accepted
    r = client.get("/api/session/me", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 401
    r = client.post("/api/decisions/propose", headers={"Authorization": "Bearer " + tok},
                    json={"title": "revoked token"})
    assert r.status_code == 401


def test_revoked_session_marked_and_rejected():
    tok = _login().json()["token"]
    client.post("/api/logout", headers={"Authorization": "Bearer " + tok})
    # The revocation marker is retained (auditable) but the token must no
    # longer resolve to a live session.
    with A._SESSION_LOCK:
        assert A._SESSIONS[tok]["revoked"] is True
    assert A._valid_session(tok) is None
    r = client.get("/api/session/me", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Permissions still enforced
# ---------------------------------------------------------------------------


def test_permissions_still_gate_actions():
    # observer (READ only) cannot propose or ratify even with a live token
    obs = _login(username="observer").json()["token"]
    r = client.post("/api/decisions/propose", headers={"Authorization": "Bearer " + obs},
                    json={"title": "observer denied"})
    assert r.status_code == 403
    r = client.post("/api/decisions/D-CORPUS-1001/ratify", headers={"Authorization": "Bearer " + obs}, json={})
    assert r.status_code == 403


def test_admin_permissions_present():
    tok = _login(username="admin").json()["token"]
    r = client.get("/api/session/me", headers={"Authorization": "Bearer " + tok})
    perms = r.json()["permissions"]
    for p in ("RATIFY", "EXECUTE", "ADMIN"):
        assert p in perms
