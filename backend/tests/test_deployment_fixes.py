"""Verification tests for deployment-agent-flagged fixes:
FIX #1: httpx present, backend cold-starts
FIX #2: login screen has empty inputs (verified via frontend inspection separately)
FIX #3: Account deletion end-to-end (register -> login -> DELETE -> re-login must 401)
REGRESSION: /api/ledger/verify still returns verified=true for demo user
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")

DEMO_EMAIL = "demo@pocketos.app"
DEMO_PASSWORD = "pocketos123"


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- FIX #1: Backend cold-start / basic reachability ----------
class TestBackendColdStart:
    def test_httpx_in_requirements(self):
        with open("/app/backend/requirements.txt") as f:
            content = f.read()
        assert "httpx==" in content, "httpx must be pinned in requirements.txt"
        assert "httpx==0.28.1" in content, "httpx should be pinned to 0.28.1"

    def test_server_module_imports(self):
        import subprocess
        r = subprocess.run(
            ["python", "-c", "import server"],
            cwd="/app/backend",
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f"server import failed: {r.stderr}"

    def test_auth_me_unauthorized_returns_401_or_403(self, api_client):
        # No auth header -> FastAPI HTTPBearer emits 403; invalid token -> 401.
        # Either proves backend is up on 8001 and enforcing auth.
        r_noauth = api_client.get(f"{BASE_URL}/api/auth/me")
        assert r_noauth.status_code in (401, 403), \
            f"expected 401/403, got {r_noauth.status_code}: {r_noauth.text[:200]}"
        r_bad = api_client.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert r_bad.status_code == 401, \
            f"invalid token must yield 401, got {r_bad.status_code}: {r_bad.text[:200]}"


# ---------- FIX #2: Login form NOT prefilled ----------
class TestLoginNotPrefilled:
    def test_login_useState_empty(self):
        with open("/app/frontend/app/auth/login.tsx") as f:
            content = f.read()
        assert 'useState("")' in content or "useState('')" in content, \
            "email/password useState must be empty string"
        # No demo credentials pre-filled
        assert "demo@pocketos.app" not in content, "login.tsx must not contain hard-coded demo email"
        assert "pocketos123" not in content, "login.tsx must not contain hard-coded demo password"


# ---------- FIX #3: Account Deletion end-to-end ----------
class TestAccountDeletion:
    email = f"delete-test-{uuid.uuid4().hex[:10]}@pocketos.app"
    password = "TempPass_123!"
    name = "Delete Test User"
    token = None
    user_id = None

    def test_1_register_temp_user(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/auth/register", json={
            "email": self.__class__.email,
            "password": self.__class__.password,
            "name": self.__class__.name,
        })
        assert r.status_code == 200, f"register failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert "token" in data and "user" in data
        assert data["user"]["email"] == self.__class__.email
        self.__class__.token = data["token"]
        self.__class__.user_id = data["user"]["id"]

    def test_2_login_temp_user_works(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": self.__class__.email,
            "password": self.__class__.password,
        })
        assert r.status_code == 200, f"login before delete failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert data["user"]["id"] == self.__class__.user_id

    def test_3_delete_account(self, api_client):
        assert self.__class__.token
        r = api_client.delete(
            f"{BASE_URL}/api/auth/account",
            headers={"Authorization": f"Bearer {self.__class__.token}"},
        )
        assert r.status_code == 200, f"delete failed: {r.status_code} {r.text[:200]}"
        body = r.json()
        assert body.get("deleted") is True
        assert body.get("user_id") == self.__class__.user_id

    def test_4_relogin_should_fail_401(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": self.__class__.email,
            "password": self.__class__.password,
        })
        assert r.status_code == 401, f"re-login must be 401 after delete, got {r.status_code}"

    def test_5_notes_with_stale_token_401(self, api_client):
        assert self.__class__.token
        r = api_client.get(
            f"{BASE_URL}/api/notes",
            headers={"Authorization": f"Bearer {self.__class__.token}"},
        )
        # User is gone; token must fail auth
        assert r.status_code == 401, f"notes with deleted-user token must 401, got {r.status_code}"


# ---------- REGRESSION: /api/ledger/verify for demo user ----------
class TestLedgerVerifyRegression:
    def test_demo_ledger_verify(self, api_client):
        # login demo
        r = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": DEMO_EMAIL, "password": DEMO_PASSWORD,
        })
        assert r.status_code == 200, f"demo login broken: {r.status_code} {r.text[:200]}"
        token = r.json()["token"]

        v = api_client.get(
            f"{BASE_URL}/api/ledger/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert v.status_code == 200, f"ledger/verify status {v.status_code}"
        body = v.json()
        assert body.get("verified") is True, f"ledger not verified: {body}"
        assert body.get("breaks") == [], f"ledger breaks not empty: {body.get('breaks')}"
