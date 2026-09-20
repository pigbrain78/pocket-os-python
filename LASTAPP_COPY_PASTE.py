"""Single-file Pocket OS backend for LastApp.

Paste this entire file into LastApp. Install Flask first if needed:
    pip install flask
Run:
    python LASTAPP_COPY_PASTE.py

Set POCKET_HUMANS to a comma-separated allow-list before production use, e.g.
    POCKET_HUMANS=alice,bob python LASTAPP_COPY_PASTE.py
To enable ratification authentication, also set POCKET_HUMAN_CREDENTIALS, e.g.
    POCKET_HUMAN_CREDENTIALS=alice:s3cret,bob:pa55 python LASTAPP_COPY_PASTE.py
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from flask import Flask, jsonify, request


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {name: _jsonable(getattr(value, name)) for name in value.__dataclass_fields__}
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class CouncilError(Exception):
    pass


class AuthorityError(CouncilError):
    pass


class InvalidTransition(CouncilError):
    pass


class StaleDecision(CouncilError):
    pass


class DuplicateEvent(CouncilError):
    pass


class FileIntakeError(ValueError):
    pass


class Verdict(str, Enum):
    APPROVED_FOR_RATIFICATION = "APPROVED_FOR_RATIFICATION"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class DecisionState(str, Enum):
    PROPOSED = "PROPOSED"
    COUNCIL_APPROVED = "COUNCIL_APPROVED"
    COUNCIL_REJECTED = "COUNCIL_REJECTED"
    COUNCIL_DEFERRED = "COUNCIL_DEFERRED"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    AWAITING_HUMAN_RATIFICATION = "AWAITING_HUMAN_RATIFICATION"
    RATIFIED = "RATIFIED"
    HUMAN_REJECTED = "HUMAN_REJECTED"
    GOVERNANCE_AUTHORIZED = "GOVERNANCE_AUTHORIZED"
    LEASED = "LEASED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    EVIDENCED = "EVIDENCED"
    LEDGERED = "LEDGERED"


@dataclass(frozen=True)
class Proposal:
    decision_id: str
    content: Mapping[str, Any]
    originating_source: str
    requested_capability: str
    risk_level: str = "UNKNOWN"
    reversibility: str = "UNKNOWN"
    expected_side_effects: tuple[str, ...] = ()
    version: int = 1
    content_hash: str = ""

    def __post_init__(self):
        if not self.content_hash:
            object.__setattr__(self, "content_hash", digest(dict(self.content)))

    def snapshot(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "content": dict(self.content),
            "originating_source": self.originating_source,
            "requested_capability": self.requested_capability,
            "risk_level": self.risk_level,
            "reversibility": self.reversibility,
            "expected_side_effects": list(self.expected_side_effects),
            "version": self.version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class Event:
    event_id: str
    event_type: str
    decision_id: str
    payload: Mapping[str, Any]
    sequence: int
    event_hash: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "decision_id": self.decision_id,
            "payload": dict(self.payload),
            "sequence": self.sequence,
            "event_hash": self.event_hash,
        }


@dataclass(frozen=True)
class CouncilEvaluation:
    decision_id: str
    verdict: Verdict
    confidence: float
    risk_level: str
    reversibility: str
    evidence_required: tuple[str, ...]
    evidence_present: tuple[str, ...]
    contradictions: tuple[str, ...]
    policy_conflicts: tuple[str, ...]
    reasoning_summary: str
    dissent: tuple[str, ...]
    missing_information: tuple[str, ...]
    recommended_next_step: str
    evaluated_at: int
    evaluator_identity: str
    input_hash: str
    output_hash: str = ""

    def __post_init__(self):
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0,1]")
        if not self.output_hash:
            raw = {
                field: (getattr(self, field).value if isinstance(getattr(self, field), Enum) else getattr(self, field))
                for field in self.__dataclass_fields__
                if field != "output_hash"
            }
            object.__setattr__(self, "output_hash", digest(raw))

    def snapshot(self) -> dict[str, Any]:
        return _jsonable(self)


class HumanAuthority:
    def __init__(self, principals, credentials=None):
        self._principals = set(filter(None, principals))
        self._credentials = {str(key): str(value) for key, value in (credentials or {}).items()}
        self._sessions = {}

    def authenticate(self, principal, credential):
        expected = self._credentials.get(principal)
        if principal not in self._principals or not credential or expected is None:
            raise AuthorityError("UNVERIFIED_HUMAN_AUTHORITY")
        if not secrets.compare_digest(expected, str(credential)):
            raise AuthorityError("UNVERIFIED_HUMAN_AUTHORITY")
        token = secrets.token_urlsafe(24)
        self._sessions[token] = principal
        return token

    def validate(self, token, principal):
        return bool(token and self._sessions.get(token) == principal)


class CanonicalCouncil:
    identity = "pocket-os-council:v1"

    def __init__(self, authority):
        self.authority = authority
        self.events = []
        self._ids = set()
        self._proposals = {}
        self._evaluations = {}

    def _emit(self, event_type, decision_id, payload):
        normalized_payload = _jsonable(payload)
        event_id = digest({"type": event_type, "decision_id": decision_id, "payload": normalized_payload})
        if event_id in self._ids:
            raise DuplicateEvent("DUPLICATE_EVENT")
        previous = self.events[-1].event_hash if self.events else "0" * 64
        event_hash = digest(
            {
                "event_id": event_id,
                "event_type": event_type,
                "decision_id": decision_id,
                "payload": normalized_payload,
                "previous": previous,
            }
        )
        event = Event(event_id, event_type, decision_id, dict(normalized_payload), len(self.events), event_hash)
        self.events.append(event)
        self._ids.add(event_id)
        return event

    def propose(self, proposal):
        if proposal.decision_id in self._proposals:
            raise DuplicateEvent("DUPLICATE_PROPOSAL")
        self._proposals[proposal.decision_id] = proposal
        return self._emit("decision.proposed", proposal.decision_id, {"proposal": proposal.snapshot()})

    def evaluate(self, decision_id, canonical_state=None, evidence=None, policy=None):
        proposal = self._proposals.get(decision_id)
        if proposal is None:
            raise CouncilError("UNKNOWN_DECISION")
        canonical_state, evidence, policy = canonical_state or {}, evidence or {}, policy or {}
        required = tuple(sorted(map(str, policy.get("required_evidence", ()))))
        present = tuple(sorted(map(str, evidence.keys())))
        missing = tuple(x for x in required if x not in evidence)
        contradictions = tuple(sorted(map(str, policy.get("contradictions", ()))))
        conflicts = tuple(sorted(map(str, policy.get("policy_conflicts", ()))))
        unknown = tuple(sorted(map(str, policy.get("missing_information", ()))))
        dissent = tuple(sorted(map(str, policy.get("dissent", ()))))
        if missing:
            verdict, reason, next_step = Verdict.NEEDS_EVIDENCE, "Required evidence is missing.", "REQUEST_EVIDENCE"
        elif unknown:
            verdict, reason, next_step = Verdict.NEEDS_CLARIFICATION, "Required information is unknown.", "REQUEST_CLARIFICATION"
        elif conflicts:
            verdict, reason, next_step = Verdict.REJECTED, "A governing policy conflict was identified.", "STOP"
        elif contradictions:
            verdict, reason, next_step = Verdict.DEFERRED, "Contradictory inputs require review.", "REVIEW_CONTRADICTIONS"
        else:
            verdict, reason, next_step = (
                Verdict.APPROVED_FOR_RATIFICATION,
                "Inputs satisfy Council evaluation criteria; human ratification remains required.",
                "REQUEST_HUMAN_RATIFICATION",
            )
        evaluation = CouncilEvaluation(
            decision_id,
            verdict,
            0.5 if (missing or unknown or contradictions or dissent) else 0.91,
            proposal.risk_level,
            proposal.reversibility,
            required,
            present,
            contradictions,
            conflicts,
            reason,
            dissent,
            unknown,
            next_step,
            int(time.time()),
            self.identity,
            digest(
                {
                    "proposal": proposal.snapshot(),
                    "state": canonical_state,
                    "evidence": evidence,
                    "policy": policy,
                    "config": self.identity,
                }
            ),
        )
        self._evaluations[decision_id] = evaluation
        event_type = {
            Verdict.APPROVED_FOR_RATIFICATION: "decision.council_approved",
            Verdict.REJECTED: "decision.council_rejected",
            Verdict.DEFERRED: "decision.council_deferred",
            Verdict.NEEDS_EVIDENCE: "decision.evidence_requested",
            Verdict.NEEDS_CLARIFICATION: "decision.council_deferred",
        }[verdict]
        self._emit(event_type, decision_id, {"evaluation": evaluation.snapshot()})
        return evaluation

    def state(self, decision_id):
        transitions = {
            "decision.proposed": DecisionState.PROPOSED,
            "decision.council_approved": DecisionState.AWAITING_HUMAN_RATIFICATION,
            "decision.council_rejected": DecisionState.COUNCIL_REJECTED,
            "decision.council_deferred": DecisionState.COUNCIL_DEFERRED,
            "decision.evidence_requested": DecisionState.NEEDS_EVIDENCE,
            "decision.ratified": DecisionState.RATIFIED,
            "decision.rejected": DecisionState.HUMAN_REJECTED,
            "governance.authorized": DecisionState.GOVERNANCE_AUTHORIZED,
            "capability.lease.granted": DecisionState.LEASED,
            "execution.started": DecisionState.EXECUTING,
            "execution.completed": DecisionState.EXECUTED,
            "evidence.attached": DecisionState.EVIDENCED,
            "ledger.write.confirmed": DecisionState.LEDGERED,
        }
        current = None
        for event in self.events:
            if event.decision_id == decision_id:
                current = transitions.get(event.event_type, current)
        if current is None:
            raise CouncilError("UNKNOWN_DECISION")
        return current

    def ratify(self, decision_id, principal, session_token, proposal_hash, context=""):
        if self.state(decision_id) is not DecisionState.AWAITING_HUMAN_RATIFICATION:
            raise InvalidTransition("HUMAN_RATIFICATION_REQUIRED")
        if not self.authority.validate(session_token, principal):
            raise AuthorityError("UNVERIFIED_HUMAN_AUTHORITY")
        if self._proposals[decision_id].content_hash != proposal_hash:
            raise StaleDecision("PROPOSAL_HASH_MISMATCH")
        return self._emit(
            "decision.ratified",
            decision_id,
            {"principal": principal, "context": context, "proposal_hash": proposal_hash},
        )

    def state_hash(self):
        return digest(
            [{"type": e.event_type, "decision_id": e.decision_id, "payload": e.payload} for e in self.events]
        )


MAX_FILE_BYTES = 25 * 1024 * 1024
ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".pdf", ".png", ".jpg", ".jpeg"}
ALLOWED_MEDIA_BY_EXTENSION = {
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".csv": {"text/csv", "text/plain"},
    ".json": {"application/json", "text/plain"},
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def ingest_file(data, name, media_type, source, destination):
    return _store_file_in_directory(data, name, media_type, source, Path(destination).resolve())


def _store_file_in_directory(data, name, media_type, source, destination: Path):
    clean = Path(name or "").name
    clean = _SAFE_NAME.sub("_", clean).strip("._ ")[:180]
    if not clean:
        raise FileIntakeError("INVALID_FILENAME")
    extension = Path(clean).suffix.lower()
    media_type = (media_type or mimetypes.guess_type(clean)[0] or "application/octet-stream").lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise FileIntakeError("UNSUPPORTED_EXTENSION")
    if media_type not in ALLOWED_MEDIA_BY_EXTENSION[extension]:
        raise FileIntakeError("UNSUPPORTED_MEDIA_TYPE")
    if source not in {"local", "icloud"}:
        raise FileIntakeError("INVALID_SOURCE")
    if len(data) > MAX_FILE_BYTES:
        raise FileIntakeError("FILE_TOO_LARGE")
    destination.mkdir(parents=True, exist_ok=True)
    final = (destination / clean).resolve(strict=False)
    if final.parent != destination:
        raise FileIntakeError("INVALID_FILENAME")
    fd = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(final, flags, 0o600)
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(data)
    except FileExistsError as exc:
        raise FileIntakeError("FILE_ALREADY_EXISTS") from exc
    except Exception:
        if fd is not None:
            os.close(fd)
        final.unlink(missing_ok=True)
        raise
    return {
        "name": clean,
        "path": str(final),
        "media_type": media_type,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "source": source,
    }


class PocketOSService:
    def __init__(self, human_principals=None, upload_dir="uploads", human_credentials=None):
        self.council = CanonicalCouncil(HumanAuthority(human_principals or set(), human_credentials or {}))
        self.upload_dir = upload_dir
        self.capture_results = {}
        self.capture_events = []

    def authenticate(self, principal, credential):
        token = self.council.authority.authenticate(str(principal), credential)
        return {"principal": str(principal), "session_token": token}

    def capture(self, body):
        capture_id, title, content = str(body["capture_id"]), str(body["title"]), str(body["content"])
        if capture_id in self.capture_results:
            return self.capture_results[capture_id]
        if not title.strip() or not content.strip():
            raise ValueError("EMPTY_CAPTURE")
        decision_id = "CAP-" + capture_id
        event = self.council.propose(
            Proposal(
                decision_id,
                {"title": title, "content": content, "type": str(body.get("item_type", "observation"))},
                str(body.get("source", "human")),
                "memory.register",
            )
        )
        result = {
            "capture_id": capture_id,
            "decision_id": decision_id,
            "status": "PROPOSED",
            "canonical_state": self.council.state(decision_id).value,
            "state_hash": self.council.state_hash(),
            "event_id": event.event_id,
        }
        self.capture_results[capture_id] = result
        self.capture_events.append(event.snapshot())
        return result

    def council_propose(self, body):
        content = body.get("content")
        if not isinstance(content, Mapping):
            raise ValueError("CONTENT_OBJECT_REQUIRED")
        decision_id = str(body.get("decision_id") or f"DEC-{len(self.council._proposals) + 1}")
        proposal = Proposal(
            decision_id=decision_id,
            content=content,
            originating_source=str(body.get("originating_source", "human")),
            requested_capability=str(body.get("requested_capability", "general")),
            risk_level=str(body.get("risk_level", "UNKNOWN")),
            reversibility=str(body.get("reversibility", "UNKNOWN")),
            expected_side_effects=tuple(map(str, body.get("expected_side_effects", ()))),
            version=int(body.get("version", 1)),
            content_hash=str(body.get("content_hash", "")),
        )
        event = self.council.propose(proposal)
        return {
            "proposal": proposal.snapshot(),
            "event": event.snapshot(),
            "canonical_state": self.council.state(decision_id).value,
            "state_hash": self.council.state_hash(),
        }

    def evaluate(self, decision_id, body):
        evaluation = self.council.evaluate(
            decision_id,
            canonical_state=body.get("canonical_state"),
            evidence=body.get("evidence"),
            policy=body.get("policy"),
        )
        return {
            "evaluation": evaluation.snapshot(),
            "canonical_state": self.council.state(decision_id).value,
            "state_hash": self.council.state_hash(),
        }

    def ratify(self, decision_id, body, session_token=None):
        principal = str(body["principal"])
        proposal_hash = str(body["proposal_hash"])
        if not session_token:
            raise AuthorityError("UNVERIFIED_HUMAN_AUTHORITY")
        event = self.council.ratify(
            decision_id,
            principal,
            session_token,
            proposal_hash,
            context=str(body.get("context", "")),
        )
        return {
            "decision_id": decision_id,
            "event": event.snapshot(),
            "canonical_state": self.council.state(decision_id).value,
            "state_hash": self.council.state_hash(),
        }

    def intake(self, data, name, media_type, source):
        return _store_file_in_directory(data, name, media_type, source, Path(self.upload_dir).resolve())

    def diagnostics(self):
        return {
            "state_hash": self.council.state_hash(),
            "event_count": len(self.council.events),
            "capture_count": len(self.capture_results),
            "capture_events": self.capture_events,
        }


def _parse_credential_map(value: str) -> dict[str, str]:
    result = {}
    for item in filter(None, (part.strip() for part in value.split(","))):
        principal, separator, credential = item.partition(":")
        if separator and principal and credential:
            result[principal] = credential
    return result


app = Flask(__name__)
service = PocketOSService(
    human_principals=set(filter(None, os.getenv("POCKET_HUMANS", "").split(","))),
    upload_dir=os.getenv("POCKET_UPLOAD_DIR", "uploads"),
    human_credentials=_parse_credential_map(os.getenv("POCKET_HUMAN_CREDENTIALS", "")),
)


def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("JSON_OBJECT_REQUIRED")
    return value


def bearer_token():
    value = request.headers.get("Authorization", "")
    if value.lower().startswith("bearer "):
        return value.split(None, 1)[1].strip()
    return ""


def read_uploaded_file(uploaded) -> bytes:
    length = uploaded.content_length
    if length is not None and length > MAX_FILE_BYTES:
        raise FileIntakeError("FILE_TOO_LARGE")
    chunks = []
    total = 0
    while True:
        chunk = uploaded.stream.read(min(1024 * 1024, MAX_FILE_BYTES - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_BYTES:
            raise FileIntakeError("FILE_TOO_LARGE")
        chunks.append(chunk)
    return b"".join(chunks)


def error_response(exc):
    message = exc.args[0] if exc.args else ""
    if isinstance(exc, FileIntakeError):
        code = 422
    elif isinstance(exc, AuthorityError):
        code = 403
    elif isinstance(exc, (DuplicateEvent, InvalidTransition, StaleDecision)):
        code = 409
    elif isinstance(exc, CouncilError) and message == "UNKNOWN_DECISION":
        code = 404
    else:
        code = 400
    if isinstance(exc, KeyError):
        error = "MISSING_REQUIRED_FIELD"
    elif isinstance(message, str) and message.isupper():
        error = message
    else:
        error = "INVALID_REQUEST"
    return jsonify(error=error), code


@app.get("/api/pocket/diagnostics")
def diagnostics():
    return jsonify(service.diagnostics()), 200


@app.post("/api/pocket/captures")
def captures():
    try:
        return jsonify(service.capture(body())), 201
    except (CouncilError, KeyError, ValueError) as exc:
        return error_response(exc)


@app.post("/api/pocket/authenticate")
@app.post("/api/pocket/council/authenticate")
def authenticate():
    try:
        payload = body()
        return jsonify(service.authenticate(payload["principal"], payload.get("credential"))), 200
    except (CouncilError, KeyError, ValueError) as exc:
        return error_response(exc)


@app.post("/api/pocket/council/proposals")
@app.post("/api/pocket/council/propose")
def council_propose():
    try:
        return jsonify(service.council_propose(body())), 201
    except (CouncilError, KeyError, ValueError) as exc:
        return error_response(exc)


@app.post("/api/pocket/council/<decision_id>/evaluate")
def council_evaluate(decision_id):
    try:
        return jsonify(service.evaluate(decision_id, body())), 200
    except (CouncilError, KeyError, ValueError) as exc:
        return error_response(exc)


@app.get("/api/pocket/council/<decision_id>/state")
def council_state(decision_id):
    try:
        return jsonify({"decision_id": decision_id, "canonical_state": service.council.state(decision_id).value}), 200
    except CouncilError as exc:
        return error_response(exc)


@app.post("/api/pocket/council/<decision_id>/ratify")
def council_ratify(decision_id):
    try:
        return jsonify(service.ratify(decision_id, body(), bearer_token())), 200
    except (CouncilError, KeyError, ValueError) as exc:
        return error_response(exc)


@app.post("/api/pocket/files/intake")
def files_intake():
    try:
        if "file" in request.files:
            uploaded = request.files["file"]
            payload = request.form
            result = service.intake(
                read_uploaded_file(uploaded),
                uploaded.filename,
                uploaded.mimetype,
                payload.get("source", "local"),
            )
        else:
            payload = body()
            raw = payload.get("data_b64") or payload.get("content_b64")
            if not raw:
                raise ValueError("FILE_DATA_REQUIRED")
            try:
                decoded = base64.b64decode(raw, validate=True)
            except Exception as exc:
                raise ValueError("INVALID_BASE64") from exc
            result = service.intake(
                decoded,
                payload.get("name"),
                payload.get("media_type"),
                payload.get("source", "local"),
            )
        return jsonify(result), 201
    except (CouncilError, FileIntakeError, KeyError, ValueError) as exc:
        return error_response(exc)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
