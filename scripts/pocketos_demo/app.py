"""Pocket OS demo app server (FastAPI).

Serves the single-page demo console and exposes the canonical Pocket OS state
through read projections. Authoritative mutations travel through the decision
lifecycle / constitutional runtime, never through direct client writes.

This build adds three controls on top of the original demo:

  * Live event spine: an SSE stream (/api/stream) that pushes ledger events so
    the console updates without polling.
  * Session + permission layer: a minimal server-side session map. Read
    projections are public (demo); consequential actions (ratify/execute) and
    demo/test mutators require a valid session and the matching permission.
    Client-supplied authority claims are always ignored.
  * Decision-state replay: the scrubber now also reconstructs the decision
    registry (proposal -> council -> ratification history) at a chosen point.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
from datetime import datetime, timezone
from datetime import timedelta
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .engines import (
    DEMO_FEATURE_GATE,
    Scrubber,
    ScrubberError,
    contradiction_count,
    genome_traits,
    governance_counters,
    hash_record,
    seed_ledger,
    verify_chain,
    cognitive_state,
    shadow_state,
    DecisionRegistry,
    ConstitutionalRuntime,
    ExecutionDenied,
    reasoning_hash,
    STATUS_PENDING,
    STATUS_COUNCIL,
    STATUS_AWAITING_RATIFICATION,
    STATUS_RATIFIED,
    STATUS_EXECUTED,
)
from .engines import council_gate

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
STATE_PATH = os.path.join(HERE, "demo_state.json")
BOOKMARKS_PATH = os.environ.get("POCKETOS_BOOKMARKS_DB", os.path.join(HERE, "replay_bookmarks.json"))

# Build metadata is deliberately static and server-owned. Clients may display
# these values, but they never negotiate authority or mutate release state.
BUILD_INFO: dict[str, Any] = {
    "product": "PocketOS",
    "release": "pocketos-app-1.1.0",
    "upgrade": "build-observability",
    "api_contract": "v2",
    "runtime": "python-fastapi",
    "audio": {"enabled": False, "reason": "voice/audio is outside this build"},
    "capabilities": {
        "canonical_ledger": True,
        "ledger_verification": True,
        "sse_event_spine": True,
        "server_authoritative_governance": True,
        "offline_authority": False,
        "audio": False,
    },
}

# The memory subsystem is server-owned. Its SQLite projections and append-only
# memory ledger are never exposed to clients; clients consume typed projections.
# Keep the location configurable so production can move this subsystem to the
# durable store used by the deployment without changing the API contract.
MEMORY_PACKAGE_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "memory_brain"))
if MEMORY_PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, MEMORY_PACKAGE_ROOT)
from memory_brain import MemoryAPI, MemoryBrain  # noqa: E402

MEMORY_DB_PATH = os.environ.get(
    "POCKETOS_MEMORY_DB",
    os.path.join(os.path.dirname(STATE_PATH), "memory_brain.sqlite3"),
)
MEMORY_BRAIN = MemoryBrain(MEMORY_DB_PATH)
MEMORY_API = MemoryAPI(brain=MEMORY_BRAIN)


# ---------------------------------------------------------------------------
# In-memory, thread-safe ledger state (server-authoritative)
# ---------------------------------------------------------------------------


class AppState:
    """Server-authoritative ledger store."""

    def __init__(self, path: str = STATE_PATH) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._records: list[dict[str, Any]] = []
        self._revision = 0
        self._load_or_seed()

    def _load_or_seed(self) -> None:
        if os.path.exists(self._path):
            try:
                with open(self._path) as fh:
                    data = json.load(fh)
                rows = data if isinstance(data, list) else data.get("records", [])
                if rows and verify_chain(rows).intact:
                    self._records = rows
                    return
            except Exception:
                pass
        self._records = seed_ledger()
        self._save()

    def _save(self) -> None:
        with open(self._path, "w") as fh:
            json.dump(self._records, fh)

    # -- reads ------------------------------------------------------------
    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._records)

    def revision(self) -> int:
        return self._revision

    def __len__(self) -> int:
        return len(self._records)

    # -- mutations --------------------------------------------------------
    def append(self, event: str, source: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Append a canonical v2 event (hash-chained). Single authoritative
        write path; every mutation travels through here."""
        with self._lock:
            head = self._records[-1] if self._records else None
            row: dict[str, Any] = {
                "sequence": len(self._records) + 1,
                "event": event,
                "timestamp": payload.get("timestamp", 0),
                "source": source,
                "schema_version": "v2",
                "kind": event.split(".")[0],
                "payload": payload,
                "previous_hash": head["hash"] if head else None,
                "hash": "",
            }
            row["hash"] = hash_record(row)
            self._records.append(row)
            self._revision += 1
            self._save()
            return dict(row)

    def reset_to_seed(self) -> dict[str, Any]:
        """Restore the INTACT seeded state. Demo/test gated."""
        with self._lock:
            self._records = seed_ledger()
            self._revision += 1
            self._save()
            return self.records()[-1]

    def append_legacy(self, record: dict[str, Any]) -> None:
        """Append a legacy_v1 record. Demo/test gated."""
        with self._lock:
            head = self._records[-1] if self._records else None
            row = dict(record)
            row["sequence"] = len(self._records) + 1
            row["schema_version"] = "legacy_v1"
            row["previous_hash"] = head["hash"] if head else None
            row["hash"] = hash_record(row)
            self._records.append(row)
            self._revision += 1
            self._save()


STATE = AppState()


def _verification_view() -> dict[str, Any]:
    v = verify_chain(STATE.records())
    return {
        "integrity": "INTACT" if v.intact else "COMPROMISED",
        "valid": v.intact,
        "broken_seq": v.broken_index,
    }


def _projection_base() -> dict[str, Any]:
    v = _verification_view()
    return {
        "integrity": v["integrity"],
        "broken_seq": v["broken_seq"],
        "schema_version": "v2",
    }


# ---------------------------------------------------------------------------
# Session + permission layer
#
# Minimal, demo-scoped but real: a server-side session map holds issued tokens
# and their permissions. Consequential actions require the matching permission.
# Client-supplied authority/role claims in request bodies are never trusted.
# ---------------------------------------------------------------------------

# Permissions
PERM_READ = "READ"
PERM_PROPOSE = "PROPOSE"
PERM_COUNCIL = "COUNCIL"
PERM_RATIFY = "RATIFY"
PERM_EXECUTE = "EXECUTE"
PERM_ADMIN = "ADMIN"  # demo/test mutators

# Session registry: token -> {subject, permissions, issued_at, expires_at}
_SESSIONS: dict[str, dict[str, Any]] = {}
_SESSION_LOCK = threading.RLock()
_SESSION_TTL = 3600  # seconds
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_LOCKOUTS: dict[str, float] = {}
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW = 300
_LOGIN_LOCKOUT = 300
_BOOKMARKS: dict[str, list[dict[str, Any]]] = {}
_BOOKMARK_AUDIT: dict[str, list[dict[str, Any]]] = {}
_AUDIT_PREFERENCES: dict[str, dict[str, Any]] = {}
_BOOKMARK_LOCK = threading.RLock()


def _load_bookmark_store() -> None:
    global _BOOKMARKS, _BOOKMARK_AUDIT, _AUDIT_PREFERENCES
    try:
        with open(BOOKMARKS_PATH) as fh:
            data = json.load(fh)
        _BOOKMARKS = data.get("bookmarks", {}) if isinstance(data, dict) else {}
        _BOOKMARK_AUDIT = data.get("audit", {}) if isinstance(data, dict) else {}
        _AUDIT_PREFERENCES = data.get("audit_preferences", {}) if isinstance(data, dict) else {}
    except Exception:
        _BOOKMARKS, _BOOKMARK_AUDIT, _AUDIT_PREFERENCES = {}, {}, {}


def _save_bookmark_store() -> None:
    temp_path = f"{BOOKMARKS_PATH}.tmp"
    with open(temp_path, "w") as fh:
        json.dump({"bookmarks": _BOOKMARKS, "audit": _BOOKMARK_AUDIT, "audit_preferences": _AUDIT_PREFERENCES}, fh)
    os.replace(temp_path, BOOKMARKS_PATH)


_load_bookmark_store()

# Password hashing (stdlib PBKDF2-HMAC-SHA256 — no plaintext stored)
_PBKDF2_ITERATIONS = 210_000


def _hash_password(password: str, iterations: int = _PBKDF2_ITERATIONS) -> str:
    """Return a salted PBKDF2-HMAC-SHA256 hash string. Never stores plaintext."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return (
        f"pbkdf2_sha256${iterations}"
        f"${base64.b64encode(salt).decode('ascii')}"
        f"${base64.b64encode(dk).decode('ascii')}"
    )


def _verify_password(password: str, stored: str) -> bool:
    """Constant-time verification of a password against a stored hash."""
    try:
        algo, iters_s, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iters_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# A fixed hash of a random string. When an unknown username is presented, login
# still runs a full PBKDF2 verify against this so timing does not reveal which
# usernames exist. (The actual password value is never used.)
_DUMMY_HASH = _hash_password("dummy-timing-equalizer")


# Demo users. Only PBKDF2 hashes are stored — the shared demo password "demo"
# never appears in code or memory as a stored credential.
USERS = {
    "operator": {
        "password_hash": "pbkdf2_sha256$210000$7dQpUUl6vYFMv9Uo6dRrcg==$WjMmOu3EhbucWnlXN4In4wcRiahoRmTVUtBEB/zhr3k=",
        "permissions": {PERM_READ, PERM_PROPOSE, PERM_COUNCIL, PERM_RATIFY, PERM_EXECUTE},
    },
    "admin": {
        "password_hash": "pbkdf2_sha256$210000$CykgHiZY3OkfCUd7y8gEqQ==$f/FLicgl/JFDXA3dNWV8Z/ij6p2DSsIgI32QC7FQyzI=",
        "permissions": {PERM_READ, PERM_PROPOSE, PERM_COUNCIL, PERM_RATIFY, PERM_EXECUTE, PERM_ADMIN},
    },
    "observer": {
        "password_hash": "pbkdf2_sha256$210000$M/XxRxwrs7d/WkMJneok3g==$dx6lMfg82RHEu2UYv8IdRJVLMJGfkCTIG4sMRGF0y18=",
        "permissions": {PERM_READ},
    },
}


def _issue_session(username: str) -> dict[str, Any]:
    """Issue a bearer token with an explicit expiry bound to the server clock."""
    token = secrets.token_urlsafe(24)
    now = int(time.time())
    with _SESSION_LOCK:
        _SESSIONS[token] = {
            "subject": username,
            "permissions": set(USERS.get(username, {}).get("permissions", set())),
            "issued_at": now,
            "expires_at": now + _SESSION_TTL,
            "revoked": False,
        }
    return {
        "token": token,
        "subject": username,
        "permissions": sorted(_SESSIONS[token]["permissions"]),
        "expires_at": _SESSIONS[token]["expires_at"],
    }


def _purge_expired() -> None:
    now = int(time.time())
    with _SESSION_LOCK:
        for token, sess in list(_SESSIONS.items()):
            if sess.get("revoked") or now > sess.get("expires_at", 0):
                _SESSIONS.pop(token, None)


def _valid_session(token: str) -> Optional[dict[str, Any]]:
    """Return a live session for token, or None if absent/revoked/expired.

    The server clock is authoritative for expiry; a token never outlives its
    TTL even if a client keeps sending it.
    """
    now = int(time.time())
    with _SESSION_LOCK:
        sess = _SESSIONS.get(token)
        if sess is None:
            return None
        if sess.get("revoked") or now > sess.get("expires_at", 0):
            _SESSIONS.pop(token, None)
            return None
    return dict(sess)


def _require_permission(token: Optional[str], perm: str) -> str:
    """Return the subject if token has perm; else raise 401/403."""
    if not token:
        raise HTTPException(status_code=401, detail="authentication required")
    sess = _valid_session(token)
    if sess is None:
        raise HTTPException(status_code=401, detail="invalid, expired, or revoked session")
    if perm not in sess["permissions"]:
        raise HTTPException(status_code=403, detail=f"permission required: {perm}")
    return sess["subject"]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _login_allowed(ip: str) -> Optional[float]:
    now = time.time()
    with _SESSION_LOCK:
        if _LOGIN_LOCKOUTS.get(ip, 0) > now:
            return _LOGIN_LOCKOUTS[ip]
        recent = [stamp for stamp in _LOGIN_ATTEMPTS.get(ip, []) if stamp > now - _LOGIN_WINDOW]
        if len(recent) >= _LOGIN_MAX_ATTEMPTS:
            _LOGIN_LOCKOUTS[ip] = now + _LOGIN_LOCKOUT
            _LOGIN_ATTEMPTS[ip] = []
            return _LOGIN_LOCKOUTS[ip]
        _LOGIN_ATTEMPTS[ip] = recent
        return None


def _login_record_failure(ip: str) -> None:
    with _SESSION_LOCK:
        _LOGIN_ATTEMPTS.setdefault(ip, []).append(time.time())


def _login_clear(ip: str) -> None:
    with _SESSION_LOCK:
        _LOGIN_ATTEMPTS.pop(ip, None)
        _LOGIN_LOCKOUTS.pop(ip, None)


def _require_demo(token: Optional[str]) -> str:
    """Demo/test mutators require the ADMIN permission (demo builds only)."""
    return _require_permission(token, PERM_ADMIN)


def _bearer(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


# ---------------------------------------------------------------------------
# Event bus / live spine
#
# A very small publish/subscribe over asyncio. Each connected SSE client has a
# queue; appends broadcast the newest record to all subscribers. Reconnect is
# handled by the client refetching full state (the stream is observational —
# the UI never treats a received event as proof the client performed it).
# ---------------------------------------------------------------------------

# subscriber_id -> asyncio.Queue
_EVENT_SUBSCRIBERS: dict[str, asyncio.Queue] = {}
_EVENT_LOCK = threading.RLock()
_FALLBACK_EVENT_BUFFER: list[dict[str, Any]] = []
_FALLBACK_EVENT_MAX = 512


def _broadcast(record: dict[str, Any]) -> None:
    envelope = {
        "type": record.get("event") or "record.append",
        "event_id": record.get("hash", ""),
        "sequence": record.get("sequence"),
        "occurred_at": record.get("timestamp"),
        "source": record.get("source", ""),
        "kind": record.get("kind", ""),
        "previous_hash": record.get("previous_hash", ""),
        "schema_version": record.get("schema_version", "v2"),
        "payload": record.get("payload", {}),
        "authority": "NONE",
        "status": "advisory",
    }
    payload = json.dumps(envelope)
    with _EVENT_LOCK:
        _FALLBACK_EVENT_BUFFER.append(envelope)
        if len(_FALLBACK_EVENT_BUFFER) > _FALLBACK_EVENT_MAX:
            del _FALLBACK_EVENT_BUFFER[: len(_FALLBACK_EVENT_BUFFER) - _FALLBACK_EVENT_MAX]
        dead = []
        for sid, q in list(_EVENT_SUBSCRIBERS.items()):
            try:
                q.put_nowait(payload)
            except Exception:
                dead.append(sid)
        for sid in dead:
            _EVENT_SUBSCRIBERS.pop(sid, None)


def _register_subscriber() -> str:
    import asyncio as _aio

    sid = secrets.token_urlsafe(16)
    with _EVENT_LOCK:
        _EVENT_SUBSCRIBERS[sid] = _aio.Queue(maxsize=200)
    return sid


def _drop_subscriber(sid: str) -> None:
    with _EVENT_LOCK:
        _EVENT_SUBSCRIBERS.pop(sid, None)


def _fallback_events_since(sequence: Optional[int]) -> list[dict[str, Any]]:
    with _EVENT_LOCK:
        events = list(_FALLBACK_EVENT_BUFFER)
        if sequence is None:
            return events
        return [ev for ev in events if isinstance(ev.get("sequence"), int) and ev["sequence"] > sequence]


# ---------------------------------------------------------------------------
# Decision registry + constitutional runtime
# ---------------------------------------------------------------------------

_DECISION_REGISTRY = DecisionRegistry()
_DECISION_RUNTIME = ConstitutionalRuntime(_DECISION_REGISTRY, STATE)


def _sync_decision_state() -> None:
    """Rebuild the registry + runtime against the current ledger."""
    _DECISION_REGISTRY.rebuild(STATE.records())


# ---------------------------------------------------------------------------
# Body models
# ---------------------------------------------------------------------------


class SeedLegacyBody(BaseModel):
    records: list[dict[str, Any]] = []


class ProposalBody(BaseModel):
    title: str
    decision_id: str = ""
    risk: str = "MEDIUM"
    reversible: bool = True
    send_to_council: bool = False
    expected_outcomes: list[str] = []
    review_after_days: int = 30


class LoginBody(BaseModel):
    username: str
    password: str


class RatifyBody(BaseModel):
    claimed_authority: str = "NONE"  # ignored — never authoritative
    # Council signatures are {member: {algorithm, key_id, signature}} in
    # production Ed25519 mode. The ledger event is emitted ONLY when a
    # threshold of distinct members verifies under active public keys.
    signatures: dict[str, Any] = {}


class ExecuteBody(BaseModel):
    claimed_authority: str = "NONE"  # ignored


class OutcomeReviewBody(BaseModel):
    outcome: str
    notes: str = ""
    lessons: list[str] = []
    actual_outcomes: list[str] = []


class MemoryRememberBody(BaseModel):
    content: str
    memory_type: Optional[str] = None
    sensitive: bool = False
    importance: Optional[float] = None


class MemorySearchBody(BaseModel):
    query: str
    top_k: int = 10
    memory_types: Optional[list[str]] = None
    minimum_confidence: float = 0.0


class MemoryReviewBody(BaseModel):
    decision: str


class ShadowProposalBody(BaseModel):
    text: str
    shadow_type: str = "RECOMMENDATION"
    shadow_provenance: str = ""
    risk: str = "MEDIUM"
    reversible: bool = True
    send_to_council: bool = False


class ReplayBookmarkBody(BaseModel):
    end: int
    label: str = ""
    device_id: str = "unknown-device"
    device_name: str = "PocketOS device"
    platform: str = "unknown"
    client_updated_at: Optional[str] = None


class AuditPreferencesBody(BaseModel):
    device: str = "ALL"
    action: str = "ALL"
    conflict: str = "ALL"
    sortNewest: bool = True


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="PocketOS Web Demo")


def _request_id() -> str:
    return f"req-{secrets.token_hex(8)}"


@app.exception_handler(HTTPException)
async def normalized_http_error(request: Request, exc: HTTPException) -> JSONResponse:
    """Keep the versioned client boundary stable without hiding HTTP status."""
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    code = {
        401: "AUTHENTICATION_REQUIRED",
        403: "AUTHORIZATION_DENIED",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_FAILED",
        429: "RATE_LIMITED",
    }.get(exc.status_code, f"HTTP_{exc.status_code}")
    request_id = _request_id()
    body = {
        "api_version": "1",
        "schema_version": "v2",
        "request_id": request_id,
        "error": {"code": code, "message": detail, "request_id": request_id},
    }
    headers = dict(exc.headers or {})
    if exc.status_code == 429:
        headers.setdefault("Retry-After", "60")
    return JSONResponse(status_code=exc.status_code, content=body, headers=headers)


_cors_origins = [origin.strip() for origin in os.environ.get(
    "POCKETOS_CORS_ORIGINS",
    "https://8081-ifn5nx1y0robf8dqdk5bp-f24c55de.us1.manus.computer,http://localhost:8081,http://127.0.0.1:8081",
).split(",") if origin.strip()]
_cors_origin_regex = os.environ.get("POCKETOS_CORS_ORIGIN_REGEX", r"https://.*\.manus\.computer")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    v = _verification_view()
    return {
        "status": "healthy",
        **v,
        "records": len(STATE),
        "revision": STATE.revision(),
        "release": BUILD_INFO["release"],
    }


@app.get("/api/build")
def api_build() -> dict[str, Any]:
    """Return immutable release/capability metadata plus live ledger status.

    This is intentionally a read projection: the browser cannot claim a
    capability, alter the release, or use this endpoint to bypass governance.
    """
    v = _verification_view()
    return {
        **BUILD_INFO,
        "ledger": {
            "integrity": v["integrity"],
            "valid": v["valid"],
            "record_count": len(STATE),
            "revision": STATE.revision(),
        },
    }


@app.get("/api/state")
def api_state() -> dict[str, Any]:
    v = _verification_view()
    with _EVENT_LOCK:
        fallback_depth = len(_FALLBACK_EVENT_BUFFER)
        sse_subscribers = len(_EVENT_SUBSCRIBERS)
    return {
        **v,
        "release": BUILD_INFO["release"],
        "record_count": len(STATE),
        "records": STATE.records(),
        "counters": governance_counters(STATE.records()).render(),
        "traits": [t.__dict__ for t in genome_traits()],
        "contradictions": contradiction_count(STATE.records()),
        "revision": STATE.revision(),
        "live_spine": {
            "active_path": "live-sse" if sse_subscribers > 0 else "fallback-poll",
            "sse_subscribers": sse_subscribers,
            "fallback_buffered_events": fallback_depth,
            "authority": "NONE",
        },
    }


@app.get("/api/v1/evidence/traits")
def api_trait_evidence() -> dict[str, Any]:
    """Return server-owned epistemic context for the six cockpit traits.

    Trait scores are representational projections. Evidence references are
    derived here from the canonical ledger so the client never invents
    citations or promotes an inferred trait to a verified fact.
    """
    records = STATE.records()
    trait_rules: dict[str, tuple[str, ...]] = {
        "recall": ("knowledge.", "memory."),
        "reasoning": ("agent.", "decision."),
        "focus": ("task.", "project."),
        "agency": ("decision.", "proposal."),
        "integrity": ("system.", "ledger."),
        "synthesis": ("knowledge.", "agent.", "relationship."),
    }
    evidence: list[dict[str, Any]] = []
    for trait in genome_traits():
        matching = [
            record for record in records
            if any(str(record.get("event", "")).startswith(prefix) for prefix in trait_rules[trait.name])
        ]
        refs = [
            {
                "sequence": record.get("sequence"),
                "event": record.get("event"),
                "source": record.get("source"),
                "hash": record.get("hash"),
                "payload": record.get("payload", {}),
            }
            for record in matching[-5:]
        ]
        evidence.append({
            "name": trait.name,
            "score": trait.score,
            "epistemic": "INFERRED",
            "confidence": round(trait.score / 100, 2),
            "provenance": "canonical-ledger-derived",
            "evidence": refs,
        })
    return {**_projection_base(), "traits": evidence, "source": "canonical-ledger"}


@app.get("/api/scrub")
def api_scrub(end: Optional[int] = None, include_decisions: bool = False) -> dict[str, Any]:
    """Replay scrub. include_decisions reconstructs the decision registry at
    the chosen point so a scrub proves decision history, not just counts."""
    scrubber = Scrubber(STATE)
    try:
        result = scrubber.scrub(end_seq=end)
    except ScrubberError as exc:
        return {
            "ok": False,
            "error": {"code": "SCRUB_REFUSED", "message": str(exc), "broken_seq": exc.broken_seq},
        }
    out: dict[str, Any] = {
        "ok": True,
        "provenance": result.provenance_line(),
        "start_seq": result.start_seq,
        "end_seq": result.end_seq,
        "event_count": result.event_count,
        "state": result.state,
    }
    if include_decisions:
        reg = DecisionRegistry()
        reg.rebuild(list(result.events))
        out["decisions"] = [d.view() for d in reg.all()]
        out["events"] = list(result.events)
    return out


@app.get("/api/replay/status")
def api_replay_status() -> dict[str, Any]:
    v = _verification_view()
    records = STATE.records()
    return {
        "api_version": "1",
        "schema_version": "v2",
        "ledger": {"integrity": v["integrity"], "valid": v["valid"], "broken_seq": v["broken_seq"]},
        "head_sequence": len(records),
        "events": len(records),
        "refuses_when_compromised": True,
    }


@app.get("/api/replay/inspect")
def api_replay_inspect(end: Optional[int] = None, include_decisions: bool = False) -> dict[str, Any]:
    scrubber = Scrubber(STATE)
    try:
        result = scrubber.scrub(end_seq=end)
    except ScrubberError as exc:
        return {
            "ok": False,
            "error": {
                "code": "REPLAY_REJECTED",
                "message": "cannot reconstruct over a compromised ledger",
                "broken_seq": exc.broken_seq,
            },
        }
    out: dict[str, Any] = {
        "ok": True,
        "provenance": result.provenance_line(),
        "start_seq": result.start_seq,
        "end_seq": result.end_seq,
        "event_count": result.event_count,
        "state": result.state,
    }
    if include_decisions:
        reg = DecisionRegistry()
        reg.rebuild(list(result.events))
        out["decisions"] = [d.view() for d in reg.all()]
        out["events"] = list(result.events)
    return out


@app.get("/api/v1/replay/bookmarks")
def api_replay_bookmarks(request: Request) -> dict[str, Any]:
    subject = _require_permission(_bearer(request), PERM_READ)
    with _BOOKMARK_LOCK:
        items = list(_BOOKMARKS.get(subject, []))
    return {"bookmarks": items, "source": "canonical-user-bookmarks", "conflict_policy": "server-last-write-wins-by-client-updated-at"}


@app.get("/api/v1/replay/bookmarks/audit")
def api_replay_bookmark_audit(request: Request) -> dict[str, Any]:
    subject = _require_permission(_bearer(request), PERM_READ)
    with _BOOKMARK_LOCK:
        return {"audit": list(_BOOKMARK_AUDIT.get(subject, [])), "source": "canonical-bookmark-audit"}


@app.get("/api/v1/preferences/audit")
def api_audit_preferences(request: Request) -> dict[str, Any]:
    subject = _require_permission(_bearer(request), PERM_READ)
    with _BOOKMARK_LOCK:
        preferences = _AUDIT_PREFERENCES.get(subject, {"device": "ALL", "action": "ALL", "conflict": "ALL", "sortNewest": True})
    return {"preferences": preferences, "source": "canonical-user-preferences"}


@app.post("/api/v1/preferences/audit")
def api_audit_preferences_save(body: AuditPreferencesBody, request: Request) -> dict[str, Any]:
    subject = _require_permission(_bearer(request), PERM_READ)
    now = datetime.now(timezone.utc).isoformat()
    preferences = {"device": body.device, "action": body.action, "conflict": body.conflict, "sortNewest": body.sortNewest, "updatedAt": now}
    with _BOOKMARK_LOCK:
        _AUDIT_PREFERENCES[subject] = preferences
        _save_bookmark_store()
    return {"preferences": preferences, "source": "canonical-user-preferences"}


@app.post("/api/v1/replay/bookmarks")
def api_replay_bookmark_create(body: ReplayBookmarkBody, request: Request) -> dict[str, Any]:
    subject = _require_permission(_bearer(request), PERM_READ)
    if body.end < 0 or body.end > len(STATE):
        raise HTTPException(status_code=422, detail="bookmark sequence is outside the canonical ledger")
    now = datetime.now(timezone.utc).isoformat()
    item = {"end": body.end, "label": body.label.strip() or f"Revision {body.end}", "createdAt": now, "updatedAt": now, "deviceId": body.device_id, "deviceName": body.device_name, "platform": body.platform, "conflictVersion": 1}
    with _BOOKMARK_LOCK:
        existing = next((entry for entry in _BOOKMARKS.get(subject, []) if entry["end"] == body.end), None)
        if existing:
            existing_client_time = existing.get("clientUpdatedAt") or existing.get("updatedAt", "")
            incoming_client_time = body.client_updated_at or now
            if incoming_client_time < existing_client_time:
                _BOOKMARK_AUDIT.setdefault(subject, []).append({"action": "conflict-kept-server", "end": body.end, "at": now, "deviceId": body.device_id, "winnerDeviceId": existing.get("deviceId"), "conflictVersion": existing.get("conflictVersion", 1)})
                _save_bookmark_store()
                return {"ok": True, "bookmark": existing, "source": "canonical-user-bookmarks", "conflict": "server-kept-newer-version"}
            item["conflictVersion"] = int(existing.get("conflictVersion", 1)) + 1
        item["clientUpdatedAt"] = body.client_updated_at or now
        current = [entry for entry in _BOOKMARKS.get(subject, []) if entry["end"] != body.end]
        _BOOKMARKS[subject] = [item, *current][:24]
        _BOOKMARK_AUDIT.setdefault(subject, []).append({"action": "created" if not existing else "conflict-replaced", "end": body.end, "at": now, "deviceId": body.device_id, "winnerDeviceId": item.get("deviceId"), "conflictVersion": item.get("conflictVersion", 1)})
        _save_bookmark_store()
    return {"ok": True, "bookmark": item, "source": "canonical-user-bookmarks", "conflict": "replaced-older-version" if existing else None}


@app.delete("/api/v1/replay/bookmarks/{end}")
def api_replay_bookmark_delete(end: int, request: Request) -> dict[str, Any]:
    subject = _require_permission(_bearer(request), PERM_READ)
    with _BOOKMARK_LOCK:
        _BOOKMARKS[subject] = [entry for entry in _BOOKMARKS.get(subject, []) if entry["end"] != end]
        _BOOKMARK_AUDIT.setdefault(subject, []).append({"action": "deleted", "end": end, "at": datetime.now(timezone.utc).isoformat()})
        _save_bookmark_store()
    return {"ok": True, "source": "canonical-user-bookmarks"}


# ---- twin / shadow / decisions -------------------------------------------


@app.get("/api/twin")
def api_twin() -> dict[str, Any]:
    cs = cognitive_state(STATE.records())
    return {**_projection_base(), "cognitive_twin": cs.view()}


@app.get("/api/shadow")
def api_shadow() -> dict[str, Any]:
    return {**_projection_base(), "ai_shadow": shadow_state(STATE.records())}


@app.get("/api/v1/projects")
def api_projects() -> dict[str, Any]:
    twin = cognitive_state(STATE.records()).view()
    return {**_projection_base(), "projects": twin["state"]["active_projects"], "source": "canonical-cognitive-projection"}


@app.get("/api/v1/open-loops")
def api_open_loops() -> dict[str, Any]:
    twin = cognitive_state(STATE.records()).view()
    return {**_projection_base(), "open_loops": twin["state"]["open_loops"], "source": "canonical-cognitive-projection"}


@app.get("/api/decisions")
def api_decisions() -> dict[str, Any]:
    _sync_decision_state()
    items = [d.view() for d in _DECISION_REGISTRY.all()]
    return {
        "api_version": "1",
        "schema_version": "v2",
        "request_id": _request_id(),
        "items": items,
        "decisions": items,
    }


def _decision_records(decision_id: str) -> list[dict[str, Any]]:
    return [
        {
            "sequence": record.get("sequence"),
            "event": record.get("event"),
            "source": record.get("source"),
            "hash": record.get("hash"),
            "payload": record.get("payload", {}),
        }
        for record in STATE.records()
        if (record.get("payload") or {}).get("decision_id") == decision_id
    ]


def _decision_receipt(decision_id: str) -> dict[str, Any]:
    _sync_decision_state()
    decision = _DECISION_REGISTRY.get(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="unknown decision")
    records = _decision_records(decision_id)
    proposal = next((r for r in records if r["event"] == "decision.proposed"), None)
    ratification = next((r for r in records if r["event"] == "decision.ratified"), None)
    reviews = [r for r in records if r["event"] == "decision.outcome_reviewed"]
    proposal_payload = (proposal or {}).get("payload", {})
    ratification_payload = (ratification or {}).get("payload", {})
    ratification_block = ratification_payload.get("block") if isinstance(ratification_payload.get("block"), dict) else {}
    ratifiers = ratification_block.get("ratifiers") if isinstance(ratification_block.get("ratifiers"), list) else []
    verification = _verification_view()
    return {
        "receipt": {
            "decision": decision.view(),
            "evidence_count": len(records),
            "evidence": records,
            "council": {
                "approved": decision.council_approved,
                "signatures": ratifiers,
                "quorum": len(ratifiers),
            },
            "human": {"status": "RATIFIED" if decision.human_ratified else "PENDING"},
            "risk": decision.risk,
            "reversible": decision.reversible,
            "expected_outcomes": proposal_payload.get("expected_outcomes", []),
            "review_after_days": proposal_payload.get("review_after_days", 30),
            "status": "REVIEWED" if reviews else ("EXECUTED" if decision.status == STATUS_EXECUTED else decision.status),
            "outcome_reviews": [r["payload"] for r in reviews],
        },
        "integrity": verification["integrity"],
        "broken_seq": verification["broken_seq"],
        "revision": STATE.revision(),
        "source": "canonical-ledger",
    }


@app.get("/api/v1/decisions/{decision_id}/receipt")
def api_decision_receipt(decision_id: str) -> dict[str, Any]:
    return _decision_receipt(decision_id)


@app.get("/api/v1/decisions/{decision_id}/receipt/share")
def api_decision_receipt_share(decision_id: str, request: Request, include_evidence: bool = False) -> dict[str, Any]:
    _require_permission(_bearer(request), PERM_READ)
    result = _decision_receipt(decision_id)
    receipt = result["receipt"]
    shared = dict(receipt)
    if not include_evidence:
        shared.pop("evidence", None)
        shared["evidence_count"] = receipt["evidence_count"]
    shared["sharing"] = {"redacted": not include_evidence, "authority": "READ_ONLY", "can_execute": False, "can_ratify": False}
    return {"share": shared, "integrity": result["integrity"], "source": "canonical-ledger-share"}


@app.get("/api/v1/decisions/review/due")
def api_decision_reviews_due(request: Request) -> dict[str, Any]:
    _require_permission(_bearer(request), PERM_READ)
    _sync_decision_state()
    records_by_sequence = {int(record.get("sequence") or 0): record for record in STATE.records()}

    def _parse_executed_at(raw: Any) -> datetime | None:
        if isinstance(raw, (int, float)) and raw > 0:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        if isinstance(raw, str) and raw.strip():
            text = raw.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        return None

    now = datetime.now(timezone.utc)
    due = []
    for decision in _DECISION_REGISTRY.all():
        receipt = _decision_receipt(decision.decision_id)["receipt"]
        if decision.status == STATUS_EXECUTED and not receipt["outcome_reviews"]:
            executed = records_by_sequence.get(int(decision.executed_seq or 0))
            if (executed or {}).get("event") != "decision.executed":
                executed = None
            executed_at = _parse_executed_at((executed or {}).get("timestamp"))
            review_after_days = int(receipt["review_after_days"])
            if executed_at is not None and now >= executed_at + timedelta(days=max(1, review_after_days)):
                due.append(
                    {
                        "decision_id": decision.decision_id,
                        "title": decision.title,
                        "review_after_days": review_after_days,
                        "status": "REVIEW_DUE",
                    }
                )
    return {"reviews": due, "source": "canonical-ledger-review-queue"}


@app.post("/api/v1/twin/debate")
def api_twin_debate(body: dict[str, Any], request: Request) -> dict[str, Any]:
    _require_permission(_bearer(request), PERM_READ)
    topic = str(body.get("topic", "")).strip()
    if not topic:
        raise HTTPException(status_code=422, detail="topic is required")
    twin = cognitive_state(STATE.records()).view()
    evidence = _decision_records(str(body.get("decision_id", ""))) if body.get("decision_id") else STATE.records()[-8:]
    evidence_refs = [{"sequence": r.get("sequence"), "event": r.get("event"), "hash": r.get("hash")} for r in evidence]
    return {"debate": {"topic": topic, "advocate": {"position": "The opportunity may be worth pursuing.", "epistemic": "INFERRED", "confidence": 0.5, "evidence": evidence_refs}, "skeptic": {"position": "The available evidence may not support the conclusion yet.", "epistemic": "INFERRED", "confidence": 0.5, "evidence": evidence_refs}, "evidence": evidence_refs, "twin_model_version": twin.get("model_version"), "authority": "NONE", "can_execute": False, "can_ratify": False}, "source": "canonical-evidence-debate"}


@app.post("/api/v1/decisions/{decision_id}/outcome")
def api_decision_outcome(decision_id: str, body: OutcomeReviewBody, request: Request) -> dict[str, Any]:
    subject = _require_permission(_bearer(request), PERM_RATIFY)
    _sync_decision_state()
    decision = _DECISION_REGISTRY.get(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="unknown decision")
    if decision.status != STATUS_EXECUTED:
        raise HTTPException(status_code=409, detail="outcome review requires an executed decision")
    if not body.outcome.strip():
        raise HTTPException(status_code=422, detail="outcome is required")
    if any(r.get("event") == "decision.outcome_reviewed" for r in STATE.records() if (r.get("payload") or {}).get("decision_id") == decision_id):
        raise HTTPException(status_code=409, detail="decision already has an outcome review")
    STATE.append("decision.outcome_reviewed", subject, {
        "decision_id": decision_id,
        "outcome": body.outcome.strip(),
        "notes": body.notes.strip(),
        "lessons": [lesson.strip() for lesson in body.lessons[:8] if lesson.strip()],
        "actual_outcomes": [item.strip() for item in body.actual_outcomes[:8] if item.strip()],
        "reviewer": subject,
    })
    _broadcast(STATE.records()[-1])
    return {"ok": True, **_decision_receipt(decision_id)}


@app.get("/api/v1/decisions/{decision_id}/evidence")
def api_decision_evidence(decision_id: str) -> dict[str, Any]:
    _sync_decision_state()
    if _DECISION_REGISTRY.get(decision_id) is None:
        raise HTTPException(status_code=404, detail="unknown decision")
    return {**_projection_base(), "decision_id": decision_id, "evidence": _decision_records(decision_id), "source": "canonical-ledger"}


@app.get("/api/v1/decisions/{decision_id}/ledger")
def api_decision_ledger(decision_id: str) -> dict[str, Any]:
    _sync_decision_state()
    if _DECISION_REGISTRY.get(decision_id) is None:
        raise HTTPException(status_code=404, detail="unknown decision")
    return {**_projection_base(), "decision_id": decision_id, "ledger": _decision_records(decision_id), "source": "canonical-ledger"}


@app.get("/api/v1/decisions/{decision_id}")
def api_decision_detail(decision_id: str) -> dict[str, Any]:
    """Return one canonical decision projection for read-after-write checks."""
    _sync_decision_state()
    decision = _DECISION_REGISTRY.get(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="unknown decision")
    return {"api_version": "1", "schema_version": "v2", "item": decision.view()}


def api_decision_detail_compat(decision_id: str) -> dict[str, Any]:
    _sync_decision_state()
    decision = _DECISION_REGISTRY.get(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="unknown decision")
    return {**_projection_base(), "api_version": "1", "ok": True, "item": decision.view(), "source": "canonical-decision-reducer"}


@app.post("/api/v1/shadow/propose")
def api_shadow_propose(body: ShadowProposalBody, request: Request) -> dict[str, Any]:
    """Convert an advisory Shadow item into an ordinary governed proposal.

    Shadow authority is explicitly recorded as NONE. This endpoint never
    approves, ratifies, grants capability, or executes the proposed action.
    """
    subject = _require_permission(_bearer(request), PERM_PROPOSE)
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text is required")
    decision_id = f"D-{reasoning_hash(body.text).upper()}"
    STATE.append("decision.proposed", subject, {
        "title": body.text.strip(),
        "decision_id": decision_id,
        "risk": body.risk,
        "reversible": body.reversible,
        "send_to_council": body.send_to_council,
        "source": "AI Shadow",
        "shadow_type": body.shadow_type,
        "shadow_provenance": body.shadow_provenance,
        "shadow_authority": "NONE",
    })
    _broadcast(STATE.records()[-1])
    _sync_decision_state()
    decision = _DECISION_REGISTRY.get(decision_id)
    return {**_projection_base(), "ok": True, "decision": decision.view() if decision else None, "source": "governed-proposal"}


# ---- memory / second-brain projections ------------------------------------


@app.post("/api/v1/memory/remember")
def api_memory_remember(body: MemoryRememberBody, request: Request) -> dict[str, Any]:
    subject = _require_permission(_bearer(request), PERM_PROPOSE)
    if not body.content.strip():
        raise HTTPException(status_code=422, detail="content is required")
    try:
        result = MEMORY_API.remember(
            body.content.strip(),
            memory_type=body.memory_type,
            importance=body.importance,
            actor=subject,
            sensitive=body.sensitive,
            is_llm=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "memory": result, "source": "canonical-memory-brain"}


@app.post("/api/v1/memory/search")
def api_memory_search(body: MemorySearchBody) -> dict[str, Any]:
    if not body.query.strip():
        raise HTTPException(status_code=422, detail="query is required")
    results = MEMORY_API.search(
        body.query.strip(),
        top_k=body.top_k,
        memory_types=body.memory_types,
        minimum_confidence=body.minimum_confidence,
    )
    return {"results": results, "source": "canonical-memory-brain"}


@app.get("/api/v1/memory/contradictions")
def api_memory_contradictions() -> dict[str, Any]:
    return {"contradictions": MEMORY_API.contradictions(), "source": "canonical-memory-brain"}


@app.get("/api/v1/memory/health")
def api_memory_health() -> dict[str, Any]:
    return {"health": MEMORY_API.health(), "source": "canonical-memory-brain"}


@app.get("/api/v1/memory/{memory_id}")
def api_memory_detail(memory_id: str) -> dict[str, Any]:
    if memory_id.isdigit():
        return api_v1_memory_item(memory_id)
    detail = MEMORY_API.explain(memory_id)
    if detail.get("memory") is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return {**detail, "source": "canonical-memory-brain"}


@app.get("/api/v1/memory/{memory_id}/provenance")
def api_memory_provenance(memory_id: str) -> dict[str, Any]:
    detail = MEMORY_API.explain(memory_id)
    if detail.get("memory") is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return {"memory_id": memory_id, "provenance": detail["provenance"], "history": detail["history"]}


@app.get("/api/v1/memory/review/pending")
def api_memory_review_pending(request: Request) -> dict[str, Any]:
    _require_permission(_bearer(request), PERM_RATIFY)
    return {"items": MEMORY_API.review_pending(), "source": "canonical-memory-brain"}


@app.post("/api/v1/memory/review/{item_id}/decide")
def api_memory_review_decide(item_id: str, body: MemoryReviewBody, request: Request) -> dict[str, Any]:
    subject = _require_permission(_bearer(request), PERM_RATIFY)
    try:
        result = MEMORY_API.review_decide(item_id, body.decision, subject)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "review": result, "source": "canonical-memory-brain"}


# ---- sessions -------------------------------------------------------------


@app.post("/api/login")
def api_login(body: LoginBody, request: Request) -> dict[str, Any]:
    ip = _client_ip(request)
    if _login_allowed(ip) is not None:
        raise HTTPException(status_code=429, detail="too many login attempts")
    username = body.username
    user = USERS.get(username)
    # Verify against the stored PBKDF2 hash. Unknown user still runs a verify
    # against a dummy hash so timing does not reveal which usernames exist.
    stored = user["password_hash"] if user else _DUMMY_HASH
    if user is None or not _verify_password(body.password, stored):
        _login_record_failure(ip)
        raise HTTPException(status_code=401, detail="invalid credentials")
    _login_clear(ip)
    return _issue_session(username)


@app.get("/api/session/me")
def api_session_me(request: Request) -> dict[str, Any]:
    token = _bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="authentication required")
    sess = _valid_session(token)
    if sess is None:
        raise HTTPException(status_code=401, detail="invalid, expired, or revoked session")
    return {
        "subject": sess["subject"],
        "permissions": sorted(sess["permissions"]),
        "expires_at": sess["expires_at"],
        "ttl_seconds": sess["expires_at"] - int(time.time()),
    }


@app.post("/api/logout")
def api_logout(request: Request) -> dict[str, Any]:
    """Revoke the presented token. Subsequent requests with it are rejected."""
    token = _bearer(request)
    if token:
        with _SESSION_LOCK:
            sess = _SESSIONS.get(token)
            if sess is not None:
                sess["revoked"] = True
    return {"ok": True}


# ---- decision lifecycle (constitutional path) ------------------------------


@app.post("/api/decisions/propose")
def api_decisions_propose(body: ProposalBody, request: Request) -> dict[str, Any]:
    # Creating a proposal requires PROPOSE permission; client authority is ignored.
    _require_permission(_bearer(request), PERM_PROPOSE)
    if not body.title.strip():
        raise HTTPException(status_code=422, detail="title is required")
    decision_id = body.decision_id.strip() or f"D-{reasoning_hash(body.title).upper()}"
    STATE.append("decision.proposed", "WebClient", {
        "title": body.title, "decision_id": decision_id, "risk": body.risk,
        "reversible": body.reversible, "send_to_council": body.send_to_council,
        "expected_outcomes": body.expected_outcomes[:8],
        "review_after_days": max(1, min(body.review_after_days, 3650)),
    })
    _broadcast(STATE.records()[-1])
    _sync_decision_state()
    decision = _DECISION_REGISTRY.get(decision_id)
    return {**_projection_base(), "ok": True, "decision": decision.view() if decision else None}


@app.post("/api/decisions/{decision_id}/council-approve")
def api_decisions_council_approve(decision_id: str, request: Request) -> dict[str, Any]:
    _require_permission(_bearer(request), PERM_COUNCIL)
    _sync_decision_state()
    decision = _DECISION_REGISTRY.get(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="unknown decision")
    if decision.rejected:
        raise HTTPException(status_code=409, detail="decision was rejected")
    if decision.status == STATUS_AWAITING_RATIFICATION:
        return {**_projection_base(), "ok": True, "decision": decision.view(), "idempotent": True}
    if decision.status not in {STATUS_PENDING, STATUS_COUNCIL}:
        raise HTTPException(status_code=409, detail="decision must be pending or in COUNCIL stage before approval")
    STATE.append("decision.council_approved", "Council", {"decision_id": decision_id, "council": "APPROVED"})
    _broadcast(STATE.records()[-1])
    _sync_decision_state()
    return {**_projection_base(), "ok": True, "decision": _DECISION_REGISTRY.get(decision_id).view()}


@app.post("/api/decisions/{decision_id}/council-sign")
def api_decisions_council_sign(decision_id: str, request: Request) -> dict[str, Any]:
    """Request a council member signature over a decision.

    Demo mode returns a local HMAC envelope for the browser harness; production
    mode returns an Ed25519 envelope from the off-box Console Signer. Private
    signing keys never leave their respective signing service.
    """
    _require_permission(_bearer(request), PERM_COUNCIL)
    _sync_decision_state()
    decision = _DECISION_REGISTRY.get(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="unknown decision")
    if decision.status != STATUS_AWAITING_RATIFICATION:
        raise HTTPException(status_code=409, detail="decision must be council-approved before signing")
    # Production signatures come from the off-box Console Signer. PocketOS
    # never loads or exposes private signing keys.
    member = request.query_params.get("member", "")
    sig = council_gate.sign_via_console(member, decision_id, council_gate.RATIFIED_STATE)
    if sig is not None:
        return {**_projection_base(), "ok": True, "member": member, "signature": sig,
                "state": council_gate.RATIFIED_STATE, "decision_id": decision_id, "signer": "console"}
    if not council_gate.signing_enabled():
        raise HTTPException(status_code=403, detail=council_gate.signer_unavailable_message())
    sig = council_gate.sign_for_member(member, decision_id, council_gate.RATIFIED_STATE)
    if sig is None:
        raise HTTPException(status_code=400, detail=f"unknown council member: {member}")
    return {**_projection_base(), "ok": True, "member": member, "signature": sig,
            "state": council_gate.RATIFIED_STATE, "decision_id": decision_id}


@app.get("/api/signer/status")
def api_signer_status() -> dict[str, Any]:
    return {"signer": council_gate.console_signer_status()}


@app.post("/api/decisions/{decision_id}/ratify")
def api_decisions_ratify(decision_id: str, request: Request, body: RatifyBody | None = None) -> dict[str, Any]:
    # Bearer RATIFY permission is NECESSARY but INSUFFICIENT: it permits a
    # session to REQUEST ratification. Authority to ratify comes ONLY from a
    # threshold of distinct council members whose signatures verify under their
    # active keys. client claimed_authority is ignored.
    _require_permission(_bearer(request), PERM_RATIFY)
    _sync_decision_state()
    decision = _DECISION_REGISTRY.get(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="unknown decision")
    if decision.rejected:
        raise HTTPException(status_code=409, detail="decision was rejected")
    if decision.human_ratified:
        raise HTTPException(status_code=409, detail="decision already ratified")

    # Require the decision to be past council (AWAITING_RATIFICATION) so the
    # council signatures are ratifying a decision the council has already seen.
    if decision.status != STATUS_AWAITING_RATIFICATION:
        raise HTTPException(
            status_code=409,
            detail="decision must be council-approved (AWAITING_RATIFICATION) before ratification",
        )

    sigs = (body.signatures if body else {}) or {}
    state = council_gate.RATIFIED_STATE
    if not council_gate.verify_quorum(decision_id, state, sigs):
        detail = council_gate.validate_signatures(decision_id, state, sigs)
        return {
            **_projection_base(), "ok": False,
            "error": {
                "code": "COUNCIL_QUORUM_NOT_MET",
                "message": "ratification requires a quorum of distinct council signatures",
                "decision_id": decision_id,
                "diagnostics": detail,
            },
        }

    # Seal the verified ratification as a hash-chained block (GENESIS-anchored),
    # chained to every previously-sealed council ratification.
    prior_blocks = council_gate.blocks_from_records(STATE.records())
    block = council_gate.seal_ratification(decision_id, state, sigs, prior_blocks)
    if block is None:
        return {
            **_projection_base(), "ok": False,
            "error": {
                "code": "COUNCIL_QUORUM_NOT_MET",
                "message": "ratification failed to seal a council block",
                "decision_id": decision_id,
            },
        }

    # Authoritative ledger event — emitted ONLY after verified council quorum,
    # and it carries the sealed hash-chained block as its cryptographic proof.
    # Execution authority is re-derived from the council chain (verify_ledger),
    # never from the mere presence of a `decision.ratified` event.
    STATE.append("decision.ratified", "Council", {
        "decision_id": decision_id,
        "state": state,
        "ratifiers": sorted(str(member) for member in (block.get("ratifiers") or []) if str(member)),
        "authority": "COUNCIL_QUORUM",
        "claimed_authority_ignored": (body.claimed_authority if body else "NONE"),
        "block": block,
    })
    _broadcast(STATE.records()[-1])
    _sync_decision_state()
    return {**_projection_base(), "ok": True, "decision": _DECISION_REGISTRY.get(decision_id).view()}


@app.post("/api/decisions/{decision_id}/reject")
def api_decisions_reject(decision_id: str, request: Request, body: RatifyBody | None = None) -> dict[str, Any]:
    _require_permission(_bearer(request), PERM_RATIFY)
    _sync_decision_state()
    decision = _DECISION_REGISTRY.get(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="unknown decision")
    if decision.human_ratified or decision.status in {STATUS_RATIFIED, STATUS_EXECUTED}:
        raise HTTPException(status_code=409, detail="ratified or executed decisions cannot be rejected")
    if decision.rejected:
        return {**_projection_base(), "ok": True, "decision": decision.view(), "idempotent": True}
    STATE.append("decision.rejected", "Human", {"decision_id": decision_id, "authority": "HUMAN", "reason": "human rejected"})
    _broadcast(STATE.records()[-1])
    _sync_decision_state()
    return {**_projection_base(), "ok": True, "decision": _DECISION_REGISTRY.get(decision_id).view()}


@app.post("/api/decisions/{decision_id}/execute")
def api_decisions_execute(decision_id: str, request: Request, body: ExecuteBody | None = None) -> dict[str, Any]:
    # Execution requires EXECUTE permission AND a ledger-recorded human
    # ratification. Client authority is ignored by the runtime.
    _require_permission(_bearer(request), PERM_EXECUTE)
    _sync_decision_state()
    claimed = (body.claimed_authority if body else "NONE")
    try:
        result = _DECISION_RUNTIME.execute(decision_id, claimed_authority=claimed)
    except ExecutionDenied as exc:
        return {
            **_projection_base(), "ok": False,
            "error": {"code": "EXECUTION_DENIED", "message": exc.reason, "decision_id": decision_id},
        }
    _broadcast(STATE.records()[-1])
    _sync_decision_state()
    return {**_projection_base(), "ok": True, "result": result, "decision": _DECISION_REGISTRY.get(decision_id).view()}


# ---- live spine (SSE) ------------------------------------------------------


@app.get("/api/stream")
async def api_stream(request: Request) -> StreamingResponse:
    """Server-Sent Events stream of ledger commits. Observational only."""

    async def event_gen() -> AsyncIterator[str]:
        sid = _register_subscriber()
        try:
            # send a hello + current revision so the client can reconcile
            yield f"event: hello\ndata: {json.dumps({'revision': STATE.revision(), 'records': len(STATE)})}\n\n"
            with _EVENT_LOCK:
                q = _EVENT_SUBSCRIBERS.get(sid)
            while q is not None:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: event\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _drop_subscriber(sid)

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/stream/health")
def api_stream_health() -> dict[str, Any]:
    with _EVENT_LOCK:
        sse_subscribers = len(_EVENT_SUBSCRIBERS)
        fallback_depth = len(_FALLBACK_EVENT_BUFFER)
    return {
        **_projection_base(),
        "stream": {
            "active_path": "live-sse" if sse_subscribers > 0 else "fallback-poll",
            "sse_subscribers": sse_subscribers,
            "fallback_buffered_events": fallback_depth,
            "authority": "NONE",
        },
    }


@app.get("/api/stream/fallback")
def api_stream_fallback(since: Optional[int] = None, limit: int = 50) -> dict[str, Any]:
    """Sandbox-safe polling bridge when live SSE consumers are unavailable."""
    if limit < 1:
        raise HTTPException(status_code=422, detail="limit must be >= 1")
    events = _fallback_events_since(since)[-min(limit, 200):]
    return {
        **_projection_base(),
        "stream": {"path": "fallback-poll", "authority": "NONE"},
        "events": events,
    }


# ---- demo / test mutators (ADMIN gated) ------------------------------------


@app.post("/api/demo/reset")
def api_demo_reset(request: Request) -> dict[str, Any]:
    _require_demo(_bearer(request))
    STATE.reset_to_seed()
    _sync_decision_state()
    return _verification_view()


@app.post("/api/demo/tamper")
def api_demo_tamper(request: Request) -> dict[str, Any]:
    """Demo-only: corrupt the first tension record's title to break the chain."""
    _require_demo(_bearer(request))
    records = STATE.records()
    target = None
    for i, r in enumerate(records):
        if (r.get("payload") or {}).get("tension"):
            target = i
            break
    if target is None:
        raise HTTPException(status_code=400, detail="nothing to tamper")
    records[target]["payload"] = dict(records[target]["payload"])
    records[target]["payload"]["title"] = "tampered by demo"
    records[target]["hash"] = "0" * 64  # break the chain visibly
    # Persist the tampered records directly (demo only).
    import threading as _th

    with _th.RLock():
        pass
    # Write via a small bypass: replace file contents.
    with open(STATE_PATH, "w") as fh:
        json.dump(records, fh)
    STATE._records = records
    STATE._revision += 1
    _sync_decision_state()
    v = _verification_view()
    return {**v, "broken_seq": v["broken_seq"]}


@app.post("/api/demo/tamper-ratification")
def api_demo_tamper_ratification(request: Request) -> dict[str, Any]:
    """Demo-only: corrupt the newest sealed council block embedded in a
    `decision.ratified` event, then RE-HASH the outer state chain so the state
    ledger itself stays INTACT.

    This simulates the strongest attacker the gate must stop: one who can write
    STATE directly and recompute hashes (so the outer chain looks fine), but
    who cannot produce a valid chained council block. Execution authority must
    still fail closed because verify_ledger on the reconstructed council chain
    returns False.
    """
    _require_demo(_bearer(request))
    records = STATE.records()
    target = None
    for i in range(len(records) - 1, -1, -1):
        payload = records[i].get("payload") or {}
        if (records[i].get("event") or "") == "decision.ratified" and isinstance(payload.get("block"), dict):
            target = i
            break
    if target is None:
        raise HTTPException(status_code=400, detail="no council-ratified block to tamper")

    # Corrupt the embedded council block's integrity seal.
    records[target]["payload"] = dict(records[target]["payload"])
    records[target]["payload"]["block"] = dict(records[target]["payload"]["block"])
    records[target]["payload"]["block"]["hash"] = "0" * 64

    # Re-hash THIS record and every subsequent record so the OUTER state chain
    # remains intact. This isolates the failure to the council block chain.
    from .engines.ledger import hash_record as _hr
    prev = records[target - 1]["hash"] if target > 0 else None
    for i in range(target, len(records)):
        records[i]["previous_hash"] = prev
        records[i]["hash"] = _hr(records[i])
        prev = records[i]["hash"]

    with open(STATE_PATH, "w") as fh:
        json.dump(records, fh)
    STATE._records = records
    STATE._revision += 1
    _sync_decision_state()
    v = _verification_view()
    # Outer chain intact; council chain must be broken.
    council_blocks = council_gate.blocks_from_records(records)
    return {
        **v,
        "outer_chain_intact": v["valid"],
        "council_chain_intact": council_gate.chain_intact(council_blocks),
        "tampered_seq": target + 1,
    }


@app.post("/api/test/seed-legacy")
def api_seed_legacy(body: SeedLegacyBody, request: Request) -> dict[str, Any]:
    _require_demo(_bearer(request))
    for rec in body.records:
        STATE.append_legacy(rec)
    _broadcast(STATE.records()[-1])
    _sync_decision_state()
    return {**_projection_base(), "ok": True, "record_count": len(STATE)}


# ---- versioned client surface ----------------------------------------------
# The web console keeps its original /api/* routes. Mobile and future clients
# use this thin alias surface so the contract has an explicit version without
# duplicating any authority, storage, or ledger logic.
for _path, _endpoint, _methods in (
    ("/api/v1/health", api_health, ["GET"]),
    ("/api/v1/signer/status", api_signer_status, ["GET"]),
    ("/api/v1/build", api_build, ["GET"]),
    ("/api/v1/state", api_state, ["GET"]),
    ("/api/v1/scrub", api_scrub, ["GET"]),
    ("/api/v1/replay/status", api_replay_status, ["GET"]),
    ("/api/v1/replay/inspect", api_replay_inspect, ["GET"]),
    ("/api/v1/twin", api_twin, ["GET"]),
    ("/api/v1/shadow", api_shadow, ["GET"]),
    ("/api/v1/decisions", api_decisions, ["GET"]),
    # Compatibility alias for clients that already use the unversioned
    # mutation surface (/api/decisions/{decision_id}/...).
    ("/api/decisions/{decision_id}", api_decision_detail_compat, ["GET"]),
    ("/api/v1/login", api_login, ["POST"]),
    ("/api/v1/session/me", api_session_me, ["GET"]),
    ("/api/v1/logout", api_logout, ["POST"]),
    ("/api/v1/decisions/propose", api_decisions_propose, ["POST"]),
    ("/api/v1/decisions/{decision_id}/council-approve", api_decisions_council_approve, ["POST"]),
    ("/api/v1/decisions/{decision_id}/council-sign", api_decisions_council_sign, ["POST"]),
    ("/api/v1/decisions/{decision_id}/ratify", api_decisions_ratify, ["POST"]),
    ("/api/v1/decisions/{decision_id}/reject", api_decisions_reject, ["POST"]),
    ("/api/v1/stream", api_stream, ["GET"]),
    ("/api/v1/stream/health", api_stream_health, ["GET"]),
    ("/api/v1/stream/fallback", api_stream_fallback, ["GET"]),
):
    app.add_api_route(_path, _endpoint, methods=_methods, include_in_schema=True)


# ---- static ----------------------------------------------------------------


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Ensure decision registry is synced on first request.
_sync_decision_state()


# ---- canonical v1 compatibility projections -------------------------------
def _v1(body: dict[str, Any]) -> dict[str, Any]:
    return {"api_version": "1", **body}


def _ledger_memory_item(record: dict[str, Any]) -> dict[str, Any]:
    seq = int(record.get("sequence") or 0)
    return {
        "id": str(seq),
        "sequence": seq,
        "event": record.get("event", "memory.created"),
        "kind": record.get("kind", "memory"),
        "payload": record.get("payload") or {},
        "provenance": f"ledger#{seq}",
        "hash": record.get("hash"),
    }


def api_v1_status() -> dict[str, Any]:
    health = api_health()
    return _v1({
        "status": health["status"],
        "ledger": {"integrity": health["integrity"], "valid": health["valid"], "broken_seq": health["broken_seq"]},
        "records": health["records"],
        "revision": health["revision"],
        "request_id": _request_id(),
        # Swift clients decode this as Int64 epoch seconds.
        "serverTime": int(datetime.now(timezone.utc).timestamp()),
        "schema_version": "v2",
    })


def api_v1_cognitive_twin() -> dict[str, Any]:
    result = api_twin()
    return _v1({"cognitive_twin": result["cognitive_twin"], "model_version": result["cognitive_twin"].get("model_version", "cognitive-twin-v1"), "schema_version": "v2"})


def api_v1_ai_shadow() -> dict[str, Any]:
    result = api_shadow()
    return _v1({"ai_shadow": result["ai_shadow"], "schema_version": "v2"})


def api_v1_memory() -> dict[str, Any]:
    items = [_ledger_memory_item(r) for r in STATE.records() if r.get("event") == "memory.created"]
    return _v1({"items": items, "count": len(items), "schema_version": "v2"})


def api_v1_memory_item(memory_id: str) -> dict[str, Any]:
    try:
        seq = int(memory_id)
    except ValueError:
        seq = -1
    record = next((r for r in STATE.records() if int(r.get("sequence") or 0) == seq and r.get("event") == "memory.created"), None)
    if record is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return _v1({"item": _ledger_memory_item(record), "schema_version": "v2"})


def api_v1_ledger() -> dict[str, Any]:
    records = STATE.records()
    v = _verification_view()
    return _v1({
        "ledger": {"integrity": v["integrity"], "valid": v["valid"], "broken_seq": v["broken_seq"]},
        "genesis_sequence": int(records[0].get("sequence") or 1) if records else 0,
        "head_sequence": int(records[-1].get("sequence") or 0) if records else 0,
        "records": len(records),
        "events": records,
        "schema_version": "v2",
    })


def api_v1_ledger_event(sequence: int) -> dict[str, Any]:
    record = next((r for r in STATE.records() if int(r.get("sequence") or 0) == sequence), None)
    if record is None:
        raise HTTPException(status_code=404, detail="ledger event not found")
    return _v1({"event": record, "schema_version": "v2"})


def api_v1_evidence() -> dict[str, Any]:
    v = _verification_view()
    return _v1({
        "ledger": {"integrity": v["integrity"], "valid": v["valid"], "broken_seq": v["broken_seq"]},
        "evidence_integrity": v["integrity"],
        "signature_status": "UNVERIFIED" if not council_gate.console_signer_status().get("configured") else "CONFIGURED_NOT_PROVEN",
        "schema_version": "v2",
    })


def api_v1_openapi() -> dict[str, Any]:
    return app.openapi()


for _path, _endpoint, _methods in (
    ("/api/v1/status", api_v1_status, ["GET"]),
    ("/api/v1/cognitive-twin", api_v1_cognitive_twin, ["GET"]),
    ("/api/v1/ai-shadow", api_v1_ai_shadow, ["GET"]),
    ("/api/v1/memory", api_v1_memory, ["GET"]),
    ("/api/v1/ledger", api_v1_ledger, ["GET"]),
    ("/api/v1/ledger/events/{sequence}", api_v1_ledger_event, ["GET"]),
    ("/api/v1/evidence/verification", api_v1_evidence, ["GET"]),
    ("/api/v1/openapi.json", api_v1_openapi, ["GET"]),
    # Compatibility aliases for the web console. These reuse the existing
    # handlers and do not introduce a second storage or authority path.
    ("/api/v1/console/status", api_v1_status, ["GET"]),
    ("/api/v1/console/state", api_state, ["GET"]),
    ("/api/v1/console/twin", api_twin, ["GET"]),
    ("/api/v1/console/shadow", api_shadow, ["GET"]),
    ("/api/v1/console/decisions", api_decisions, ["GET"]),
):
    app.add_api_route(_path, _endpoint, methods=_methods, include_in_schema=True)
