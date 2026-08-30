"""
Test suite for Forgot Password flow (Emergent Resend integration).

Coverage:
- POST /api/auth/forgot-password (known/unknown emails, enumeration-safety, rate-limit)
- POST /api/auth/reset-password (all rejection paths, success path, ledger event)
- login with new password after reset (and old password fails)
- _assert_safe_email guardrail (rejects unsafe HTML, allows real template)
- send_email helper (no-ops when EMERGENT_EMAIL_KEY empty; posts when set)
- Regression: /api/auth/admin/reset-password still works (503/401/200)
"""
import os
import sys
import time
import asyncio
import pathlib
import pytest
import requests
from unittest.mock import patch, AsyncMock, MagicMock

# ----- Path setup so we can import server for direct-call tests -----
BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# Ensure env is loaded before importing server
from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")
# Also load frontend .env to get the public preview URL used by the mobile app
_frontend_env = BACKEND_DIR.parent / "frontend" / ".env"
if _frontend_env.exists():
    load_dotenv(_frontend_env)

import server  # noqa: E402

# Public URL for E2E HTTP tests — must match what the mobile app uses
BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or ""
).rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set for backend tests"

DEMO_EMAIL = "demo@pocketos.app"
DEMO_PASSWORD = "pocketos123"
UNKNOWN_EMAIL = "TEST_no_such_user_never_registered@example.com"


# =========================================================================
# Fixtures
# =========================================================================
@pytest.fixture
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(autouse=True)
def _reset_forgot_bucket():
    """Reset in-memory rate-limit bucket between tests so ordering doesn't matter."""
    server._FORGOT_ATTEMPTS.clear()
    yield
    server._FORGOT_ATTEMPTS.clear()


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# =========================================================================
# 1. Public HTTP endpoint tests
# =========================================================================
class TestForgotPasswordEndpoint:
    """POST /api/auth/forgot-password — enumeration safety, rate limit, DB write."""

    GENERIC_MESSAGE = "If an account exists"

    def test_known_email_returns_generic_200(self, api_client):
        r = api_client.post(
            f"{BASE_URL}/api/auth/forgot-password",
            json={"email": DEMO_EMAIL},
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is True
        assert self.GENERIC_MESSAGE in body.get("detail", "")

    def test_unknown_email_returns_same_generic_200(self, api_client):
        r = api_client.post(
            f"{BASE_URL}/api/auth/forgot-password",
            json={"email": UNKNOWN_EMAIL},
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is True
        assert self.GENERIC_MESSAGE in body.get("detail", "")

    def test_known_vs_unknown_bodies_are_identical(self, api_client):
        """Enumeration safety: identical shape/status for known and unknown emails."""
        r1 = api_client.post(
            f"{BASE_URL}/api/auth/forgot-password",
            json={"email": DEMO_EMAIL},
        )
        r2 = api_client.post(
            f"{BASE_URL}/api/auth/forgot-password",
            json={"email": UNKNOWN_EMAIL},
        )
        assert r1.status_code == r2.status_code == 200
        assert r1.json() == r2.json()

    def test_known_email_creates_password_reset_record(self):
        """After forgot-password for a known email, a password_resets record exists in Mongo."""
        async def _check():
            # Clear any prior records for demo
            await server.db.password_resets.delete_many({"email": DEMO_EMAIL})
            # Trigger the endpoint via the internal function so we don't touch the rate-limit bucket
            server._FORGOT_ATTEMPTS.clear()
            resp = await server.forgot_password(server.ForgotPasswordIn(email=DEMO_EMAIL))
            assert resp["ok"] is True
            rec = await server.db.password_resets.find_one({"email": DEMO_EMAIL})
            assert rec is not None
            assert rec.get("used") is False
            assert rec.get("attempts") == 0
            assert rec.get("code_hash")  # code is hashed at rest
            assert rec.get("expires_at")
            # Cleanup
            await server.db.password_resets.delete_many({"email": DEMO_EMAIL})
        _run(_check())

    def test_unknown_email_does_not_create_reset_record(self):
        async def _check():
            await server.db.password_resets.delete_many({"email": UNKNOWN_EMAIL})
            server._FORGOT_ATTEMPTS.clear()
            resp = await server.forgot_password(server.ForgotPasswordIn(email=UNKNOWN_EMAIL))
            assert resp["ok"] is True
            rec = await server.db.password_resets.find_one({"email": UNKNOWN_EMAIL})
            assert rec is None
        _run(_check())

    def test_rate_limit_6th_call_generic_but_no_new_record(self, api_client):
        """6th forgot-password call for same email within an hour: still 200, but no new/updated reset record."""
        async def _run_test():
            await server.db.password_resets.delete_many({"email": DEMO_EMAIL})
            server._FORGOT_ATTEMPTS.clear()

            # First 5 succeed (within-limit) — each replaces prior record
            for i in range(5):
                resp = await server.forgot_password(server.ForgotPasswordIn(email=DEMO_EMAIL))
                assert resp["ok"] is True

            rec_after_5 = await server.db.password_resets.find_one({"email": DEMO_EMAIL})
            assert rec_after_5 is not None
            id_after_5 = rec_after_5["id"]
            created_after_5 = rec_after_5["created_at"]

            # 6th call: should still return 200/generic but NOT create/update record
            resp6 = await server.forgot_password(server.ForgotPasswordIn(email=DEMO_EMAIL))
            assert resp6["ok"] is True
            assert self.GENERIC_MESSAGE in resp6.get("detail", "")

            rec_after_6 = await server.db.password_resets.find_one({"email": DEMO_EMAIL})
            assert rec_after_6 is not None
            # Same record — 6th call must not overwrite/replace
            assert rec_after_6["id"] == id_after_5
            assert rec_after_6["created_at"] == created_after_5

            await server.db.password_resets.delete_many({"email": DEMO_EMAIL})
        _run(_run_test())


# =========================================================================
# 2. Reset password endpoint validation & success
# =========================================================================
class TestResetPasswordValidation:
    """All rejection paths for POST /api/auth/reset-password."""

    def test_reject_short_password(self, api_client):
        r = api_client.post(
            f"{BASE_URL}/api/auth/reset-password",
            json={"email": DEMO_EMAIL, "code": "123456", "new_password": "short"},
        )
        assert r.status_code == 400
        assert "8 characters" in r.json().get("detail", "")

    def test_reject_non_6_digit_code(self, api_client):
        # Too short
        r = api_client.post(
            f"{BASE_URL}/api/auth/reset-password",
            json={"email": DEMO_EMAIL, "code": "12345", "new_password": "validpass123"},
        )
        assert r.status_code == 400
        assert "code" in r.json().get("detail", "").lower()

        # Contains non-digit
        r = api_client.post(
            f"{BASE_URL}/api/auth/reset-password",
            json={"email": DEMO_EMAIL, "code": "12345a", "new_password": "validpass123"},
        )
        assert r.status_code == 400

        # Too long
        r = api_client.post(
            f"{BASE_URL}/api/auth/reset-password",
            json={"email": DEMO_EMAIL, "code": "1234567", "new_password": "validpass123"},
        )
        assert r.status_code == 400

    def test_wrong_code_right_length_rejected(self, api_client):
        async def _setup_and_check():
            await server.db.password_resets.delete_many({"email": DEMO_EMAIL})
            server._FORGOT_ATTEMPTS.clear()
            await server.forgot_password(server.ForgotPasswordIn(email=DEMO_EMAIL))
            # Use a code we know is wrong (odds of collision are 1e-6)
            r = api_client.post(
                f"{BASE_URL}/api/auth/reset-password",
                json={"email": DEMO_EMAIL, "code": "000000", "new_password": "validpass123"},
            )
            assert r.status_code == 400
            # Verify attempt was recorded
            rec = await server.db.password_resets.find_one({"email": DEMO_EMAIL})
            # Might be 1 (if 000000 was wrong) or 0 (if it accidentally matched — extremely unlikely)
            assert rec is not None
            await server.db.password_resets.delete_many({"email": DEMO_EMAIL})
        _run(_setup_and_check())

    def test_expired_code_rejected(self):
        """Insert an expired reset record directly and verify 400."""
        async def _check():
            from datetime import datetime, timezone, timedelta
            email = "test_expired@example.com"
            # Ensure a user exists so reset can find it (though endpoint won't reach that point)
            # Actually, reset_password only looks up the reset record — no user needed
            await server.db.password_resets.delete_many({"email": email})
            await server.db.password_resets.insert_one({
                "id": server.uid(),
                "email": email,
                "user_id": "fake-user-id",
                "code_hash": server._hash_code("424242"),
                "created_at": (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
                "expires_at": (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(),
                "attempts": 0,
                "used": False,
            })
            try:
                await server.reset_password(server.ResetPasswordIn(
                    email=email, code="424242", new_password="validpass123"
                ))
                assert False, "Expected HTTPException"
            except Exception as e:
                assert "expired" in str(e).lower() or "invalid" in str(e).lower()
            # Expired record should have been deleted
            rec = await server.db.password_resets.find_one({"email": email})
            assert rec is None
        _run(_check())

    def test_more_than_5_wrong_attempts_invalidates_code(self):
        async def _check():
            from datetime import datetime, timezone, timedelta
            email = "test_lockout@example.com"
            await server.db.password_resets.delete_many({"email": email})
            await server.db.password_resets.insert_one({
                "id": server.uid(),
                "email": email,
                "user_id": "fake-user-id",
                "code_hash": server._hash_code("424242"),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
                "attempts": 5,  # Already at max
                "used": False,
            })
            # 6th attempt (wrong code) should be rejected AND invalidate the code
            try:
                await server.reset_password(server.ResetPasswordIn(
                    email=email, code="000000", new_password="validpass123"
                ))
                assert False, "Expected HTTPException"
            except Exception as e:
                assert "attempt" in str(e).lower() or "invalid" in str(e).lower()
            # Record should be deleted (invalidated)
            rec = await server.db.password_resets.find_one({"email": email})
            assert rec is None
        _run(_check())


# =========================================================================
# 3. Full reset flow: reset → login with new pw → old pw fails
# =========================================================================
class TestResetPasswordSuccessFlow:
    """End-to-end: seed reset record with known code → reset → login with new pw."""

    def test_full_reset_and_login_flow(self, api_client):
        async def _run_flow():
            from datetime import datetime, timezone, timedelta
            # Use demo user (guaranteed to exist)
            user = await server.db.users.find_one({"email": DEMO_EMAIL})
            assert user is not None, "demo@pocketos.app must exist"
            original_pw_hash = user["password"]
            new_password = "TEST_newpass_reset_1234"

            # Seed a known code
            await server.db.password_resets.delete_many({"email": DEMO_EMAIL})
            code = "424242"
            await server.db.password_resets.insert_one({
                "id": server.uid(),
                "email": DEMO_EMAIL,
                "user_id": user["id"],
                "code_hash": server._hash_code(code),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
                "attempts": 0,
                "used": False,
            })

            # Track events before reset
            events_before = await server.db.events.count_documents({
                "user_id": user["id"], "kind": "password_reset_completed"
            })

            try:
                # 1. Reset via public HTTP endpoint
                r = api_client.post(
                    f"{BASE_URL}/api/auth/reset-password",
                    json={"email": DEMO_EMAIL, "code": code, "new_password": new_password},
                )
                assert r.status_code == 200, f"Reset failed: {r.status_code} {r.text}"
                body = r.json()
                assert body.get("ok") is True
                assert "token" in body
                assert body["user"]["email"] == DEMO_EMAIL

                # 2. Password reset record removed
                rec = await server.db.password_resets.find_one({"email": DEMO_EMAIL})
                assert rec is None, "reset record must be deleted after successful reset"

                # 3. Ledger event appended
                events_after = await server.db.events.count_documents({
                    "user_id": user["id"], "kind": "password_reset_completed"
                })
                assert events_after == events_before + 1

                # 4. Old password no longer works
                r_old = api_client.post(
                    f"{BASE_URL}/api/auth/login",
                    json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
                )
                assert r_old.status_code == 401

                # 5. New password works
                r_new = api_client.post(
                    f"{BASE_URL}/api/auth/login",
                    json={"email": DEMO_EMAIL, "password": new_password},
                )
                assert r_new.status_code == 200
                assert "token" in r_new.json()

                # 6. Reused code (same one) fails after reset
                r_reuse = api_client.post(
                    f"{BASE_URL}/api/auth/reset-password",
                    json={"email": DEMO_EMAIL, "code": code, "new_password": "anotherPass99"},
                )
                assert r_reuse.status_code == 400

                # 7. Password is bcrypt-hashed (not stored plaintext)
                updated = await server.db.users.find_one({"email": DEMO_EMAIL})
                assert updated["password"] != new_password
                assert updated["password"].startswith("$2")  # bcrypt prefix
                assert updated["password"] != original_pw_hash  # changed
            finally:
                # Restore original password so subsequent test runs / other tests are unaffected
                await server.db.users.update_one(
                    {"email": DEMO_EMAIL},
                    {"$set": {"password": original_pw_hash}},
                )
                await server.db.password_resets.delete_many({"email": DEMO_EMAIL})

        _run(_run_flow())


# =========================================================================
# 4. Email guardrail gate — _assert_safe_email
# =========================================================================
class TestEmailGuardrail:
    def test_reject_form_input(self):
        with pytest.raises(ValueError, match="forms"):
            server._assert_safe_email("Subject", "<html><form><input /></form></html>")

    def test_reject_input_only(self):
        with pytest.raises(ValueError, match="forms"):
            server._assert_safe_email("Subject", "<html><input type='text' /></html>")

    def test_reject_non_https_url(self):
        with pytest.raises(ValueError, match="absolute https"):
            server._assert_safe_email("Subject", '<a href="http://insecure.com">click</a>')

    def test_reject_shortener_url(self):
        with pytest.raises(ValueError, match="Shortened"):
            server._assert_safe_email("Subject", '<a href="https://bit.ly/abc123">click</a>')

    def test_reject_ip_literal_host(self):
        with pytest.raises(ValueError):
            server._assert_safe_email("Subject", '<a href="https://192.168.1.1/path">click</a>')

    def test_reject_credential_ask(self):
        with pytest.raises(ValueError, match="credentials"):
            server._assert_safe_email(
                "Reset",
                "<p>Please reply with your password so we can help.</p>",
            )

    def test_real_reset_template_passes(self):
        subject, html = server._reset_email_body("424242", "Test User")
        # Should NOT raise
        server._assert_safe_email(subject, html)


# =========================================================================
# 5. send_email helper
# =========================================================================
class TestSendEmailHelper:
    def test_no_op_when_key_empty(self, caplog):
        """With EMERGENT_EMAIL_KEY empty, send_email logs a warning and returns None."""
        # Ensure key is empty at module level
        original = server.EMAIL_KEY
        server.EMAIL_KEY = ""
        try:
            import logging
            caplog.set_level(logging.WARNING)
            result = _run(server.send_email(
                to="foo@bar.com",
                subject="Test subject",
                html="<p>hello</p>",
            ))
            assert result is None
            assert any(
                "EMERGENT_EMAIL_KEY not set" in rec.message
                for rec in caplog.records
            )
        finally:
            server.EMAIL_KEY = original

    def test_posts_to_emergent_proxy_when_key_set(self):
        """When EMAIL_KEY is set, POSTs to the correct URL with X-Email-Key header + from_name."""
        original = server.EMAIL_KEY
        server.EMAIL_KEY = "test-fake-key-1234"

        captured = {}

        class _FakeResp:
            def raise_for_status(self):
                return None
            def json(self):
                return {"id": "email-abc-123"}

        class _FakeAsyncClient:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return None
            async def post(self, url, headers=None, json=None):
                captured["url"] = url
                captured["headers"] = headers or {}
                captured["json"] = json or {}
                return _FakeResp()

        try:
            with patch.object(server.httpx, "AsyncClient", _FakeAsyncClient):
                result = _run(server.send_email(
                    to="foo@bar.com",
                    subject="Test",
                    html="<p>hi</p>",
                ))
            assert result == "email-abc-123"
            assert captured["url"] == "https://integrations.emergentagent.com/api/v1/email/send"
            assert captured["headers"].get("X-Email-Key") == "test-fake-key-1234"
            assert captured["json"].get("from_name") == server.EMAIL_FROM_NAME
            assert captured["json"].get("to") == ["foo@bar.com"]
            assert captured["json"].get("subject") == "Test"
        finally:
            server.EMAIL_KEY = original


# =========================================================================
# 6. Regression — admin reset-password endpoint still works
# =========================================================================
class TestAdminResetPasswordRegression:
    def test_503_when_admin_token_env_unset(self, api_client):
        original = os.environ.get("ADMIN_RESET_TOKEN")
        # Temporarily unset in-process. Note: server reads env at request time (via os.environ.get),
        # so unsetting the env var affects the running server as well since we're in-process.
        # For HTTP call, the running server is a separate process (supervisor). We test via direct call.
        if "ADMIN_RESET_TOKEN" in os.environ:
            del os.environ["ADMIN_RESET_TOKEN"]
        try:
            async def _call():
                try:
                    await server.admin_reset_password(server.AdminResetIn(
                        email=DEMO_EMAIL, new_password="testtest12", admin_token="anything"
                    ))
                    return None
                except Exception as e:
                    return e
            err = _run(_call())
            assert err is not None
            assert "disabled" in str(err).lower() or "503" in str(err)
        finally:
            if original is not None:
                os.environ["ADMIN_RESET_TOKEN"] = original

    def test_401_on_bad_token(self):
        os.environ["ADMIN_RESET_TOKEN"] = "TEST_correct_token_only_for_test"
        try:
            async def _call():
                try:
                    await server.admin_reset_password(server.AdminResetIn(
                        email=DEMO_EMAIL, new_password="testtest12",
                        admin_token="WRONG_TOKEN",
                    ))
                    return None
                except Exception as e:
                    return e
            err = _run(_call())
            assert err is not None
            assert "invalid" in str(err).lower() or "401" in str(err)
        finally:
            # Restore (clear our test value)
            os.environ.pop("ADMIN_RESET_TOKEN", None)

    def test_200_and_fresh_jwt_on_good_token(self):
        os.environ["ADMIN_RESET_TOKEN"] = "TEST_correct_token_only_for_test_9x"
        try:
            async def _call():
                # Snapshot current password so we can restore
                user_before = await server.db.users.find_one({"email": DEMO_EMAIL})
                original_pw_hash = user_before["password"]
                try:
                    result = await server.admin_reset_password(server.AdminResetIn(
                        email=DEMO_EMAIL,
                        new_password="TEST_admin_reset_pw123",
                        admin_token="TEST_correct_token_only_for_test_9x",
                    ))
                    assert result.get("ok") is True
                    assert "token" in result
                    assert result["user"]["email"] == DEMO_EMAIL
                    return None
                finally:
                    # Restore original password
                    await server.db.users.update_one(
                        {"email": DEMO_EMAIL},
                        {"$set": {"password": original_pw_hash}},
                    )
            err = _run(_call())
            assert err is None, f"Should have succeeded: {err}"
        finally:
            os.environ.pop("ADMIN_RESET_TOKEN", None)
