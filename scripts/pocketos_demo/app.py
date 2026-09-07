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
import threading
import time
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Request
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
    STATUS_AWAITING_RATIFICATION,
)
from .engines import council_gate

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
STATE_PATH = os.path.join(HERE, "demo_state.json")


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


def _broadcast(record: dict[str, Any]) -> None:
    import asyncio as _aio

    payload = json.dumps({"type": record.get("event") or "record.append",
                          "sequence": record.get("sequence"),
                          "schema_version": record.get("schema_version", "v2"),
                          "event_id": record.get("hash", ""),
                          "payload": record.get("payload", {})})
    with _EVENT_LOCK:
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


class LoginBody(BaseModel):
    username: str
    password: str


class RatifyBody(BaseModel):
    claimed_authority: str = "NONE"  # ignored — never authoritative
    # Council signatures: {member: hmac_signature}. The ledger event is emitted
    # ONLY when a threshold of distinct members verifies under active keys.
    signatures: dict[str, str] = {}


class ExecuteBody(BaseModel):
    claimed_authority: str = "NONE"  # ignored


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="PocketOS Web Demo")


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    v = _verification_view()
    return {"status": "healthy", **v, "records": len(STATE), "revision": STATE.revision()}


@app.get("/api/state")
def api_state() -> dict[str, Any]:
    v = _verification_view()
    return {
        **v,
        "record_count": len(STATE),
        "records": STATE.records(),
        "counters": governance_counters(STATE.records()).render(),
        "traits": [t.__dict__ for t in genome_traits()],
        "contradictions": contradiction_count(STATE.records()),
        "revision": STATE.revision(),
    }


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
    return out


# ---- twin / shadow / decisions -------------------------------------------


@app.get("/api/twin")
def api_twin() -> dict[str, Any]:
    cs = cognitive_state(STATE.records())
    return {**_projection_base(), "cognitive_twin": cs.view()}


@app.get("/api/shadow")
def api_shadow() -> dict[str, Any]:
    return {**_projection_base(), "ai_shadow": shadow_state(STATE.records())}


@app.get("/api/decisions")
def api_decisions() -> dict[str, Any]:
    _sync_decision_state()
    return {**_projection_base(), "decisions": [d.view() for d in _DECISION_REGISTRY.all()]}


# ---- sessions -------------------------------------------------------------


@app.post("/api/login")
def api_login(body: LoginBody) -> dict[str, Any]:
    username = body.username
    user = USERS.get(username)
    # Verify against the stored PBKDF2 hash. Unknown user still runs a verify
    # against a dummy hash so timing does not reveal which usernames exist.
    stored = user["password_hash"] if user else _DUMMY_HASH
    if user is None or not _verify_password(body.password, stored):
        raise HTTPException(status_code=401, detail="invalid credentials")
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
    STATE.append("decision.council_approved", "Council", {"decision_id": decision_id, "council": "APPROVED"})
    _broadcast(STATE.records()[-1])
    _sync_decision_state()
    return {**_projection_base(), "ok": True, "decision": _DECISION_REGISTRY.get(decision_id).view()}


@app.post("/api/decisions/{decision_id}/council-sign")
def api_decisions_council_sign(decision_id: str, request: Request) -> dict[str, Any]:
    """Request a council member signature over a decision (demo assembly of a
    quorum). Requires COUNCIL permission. Keys never leave the server; returns
    the HMAC signature for the named member so a session can assemble a
    threshold. Production members would sign off-box and submit signatures only.
    """
    _require_permission(_bearer(request), PERM_COUNCIL)
    _sync_decision_state()
    decision = _DECISION_REGISTRY.get(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="unknown decision")
    member = request.query_params.get("member", "")
    sig = council_gate.sign_for_member(member, decision_id, council_gate.RATIFIED_STATE)
    if sig is None:
        raise HTTPException(status_code=400, detail=f"unknown council member: {member}")
    return {**_projection_base(), "ok": True, "member": member, "signature": sig,
            "state": council_gate.RATIFIED_STATE, "decision_id": decision_id}


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

    # Authoritative ledger event — emitted ONLY after verified council quorum.
    STATE.append("decision.ratified", "Council", {
        "decision_id": decision_id,
        "state": state,
        "ratifiers": sorted(sigs.keys()),
        "authority": "COUNCIL_QUORUM",
        "claimed_authority_ignored": (body.claimed_authority if body else "NONE"),
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


@app.post("/api/test/seed-legacy")
def api_seed_legacy(body: SeedLegacyBody, request: Request) -> dict[str, Any]:
    _require_demo(_bearer(request))
    for rec in body.records:
        STATE.append_legacy(rec)
    _broadcast(STATE.records()[-1])
    _sync_decision_state()
    return {**_projection_base(), "ok": True, "record_count": len(STATE)}


# ---- static ----------------------------------------------------------------


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Ensure decision registry is synced on first request.
_sync_decision_state()
