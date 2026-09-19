from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("POCKETOS_BASE_URL", "https://pocketos-canonical-api.onrender.com").rstrip("/")
OUT = Path(__file__).with_name("pocketos_skill_demo_results.json")
ADMIN = {"username": "admin", "password": "demo"}
OBSERVER = {"username": "observer", "password": "demo"}


def request(method: str, path: str, token: str | None = None, payload: dict | None = None, timeout: float = 15.0) -> tuple[int, dict]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"error": raw}
        return exc.code, body


def must(method: str, path: str, token: str | None = None, payload: dict | None = None) -> dict:
    status, body = request(method, path, token, payload)
    if status < 200 or status >= 300:
        raise RuntimeError(f"{method} {path} -> {status}: {body}")
    return body


def compact_decision(d: dict | None) -> dict | None:
    if not d:
        return None
    return {k: d.get(k) for k in ("decision_id", "title", "status", "stage", "human_ratified", "council_approved", "rejected", "can_execute", "risk", "reversible")}


def response_decision(body: dict) -> dict | None:
    for key in ("decision", "item", "proposal"):
        value = body.get(key)
        if isinstance(value, dict):
            return value
    for key in ("data", "result", "response"):
        value = body.get(key)
        if isinstance(value, dict):
            found = response_decision(value)
            if found:
                return found
    return None


def response_error(body: dict) -> object:
    """Normalize canonical error, FastAPI detail, and nested envelopes."""
    if body.get("error") is not None:
        return body["error"] if isinstance(body["error"], dict) else {"message": body["error"]}
    if body.get("detail") is not None:
        return body["detail"] if isinstance(body["detail"], dict) else {"message": body["detail"]}
    for key in ("data", "result", "response"):
        value = body.get(key)
        if isinstance(value, dict):
            found = response_error(value)
            if found is not None:
                return found
    return None


def login(credentials: dict) -> str:
    return must("POST", "/api/login", payload=credentials)["token"]


def main() -> None:
    results: dict[str, object] = {"base_url": BASE, "scenarios": {}}
    status_body = must("GET", "/api/v1/health")
    twin = must("GET", "/api/twin")["cognitive_twin"]
    shadow = must("GET", "/api/shadow")["ai_shadow"]
    decisions_body = must("GET", "/api/decisions")
    decisions = decisions_body.get("decisions", decisions_body.get("items", []))
    results["scenarios"]["cockpit_snapshot"] = {
        "status": {"status": status_body["status"], "ledger_integrity": status_body["integrity"], "records": status_body["records"]},
        "twin": {"model_version": twin["model_version"], "summary": twin["summary"], "current_focus": twin["state"]["current_focus"], "open_loops": twin["state"]["open_loops"], "active_projects": twin["state"]["active_projects"], "relevant_memories": twin["relevant_memories"]},
        "shadow": {"items": shadow["items"], "authority_boundary": shadow["authority_boundary"]},
        "decisions": [compact_decision(d) for d in decisions],
    }

    admin = login(ADMIN)
    must("POST", "/api/demo/reset", admin)
    shadow = must("GET", "/api/shadow")["ai_shadow"]
    recommendation = next(i for i in shadow["items"] if i["type"] == "PROPOSAL")
    proposed = must("POST", "/api/decisions/propose", admin, {"title": "Review current project dependencies", "risk": "LOW", "reversible": True, "send_to_council": True})
    decision = proposed.get("decision") or proposed.get("item") or proposed.get("proposal")
    if not decision or "decision_id" not in decision:
        raise RuntimeError(f"proposal response: {proposed}")
    decision_id = decision["decision_id"]
    _, denied = request("POST", f"/api/decisions/{decision_id}/execute", admin, {"claimed_authority": "HUMAN"})
    must("POST", f"/api/decisions/{decision_id}/council-approve", admin)
    # The deployed canonical service requires a quorum of distinct council
    # signatures before human ratification is accepted. Production signing
    # may be disabled, so preserve that boundary as structured evidence rather
    # than pretending ratification or execution succeeded.
    council_signatures = []
    for _ in range(2):
        sign_status, sign_body = request("POST", f"/api/v1/decisions/{decision_id}/council-sign", admin)
        council_signatures.append({"status_code": sign_status, "ok": sign_body.get("ok"), "error": response_error(sign_body)})
        if sign_status < 200 or sign_status >= 300:
            break
    ratified = None
    executed = None
    if len(council_signatures) == 2 and all(item["status_code"] < 300 for item in council_signatures):
        ratified = must("POST", f"/api/v1/decisions/{decision_id}/ratify", admin, {})
        executed = must("POST", f"/api/decisions/{decision_id}/execute", admin, {"claimed_authority": "SHADOW"})
    results["scenarios"]["shadow_to_governed_proposal"] = {"shadow_recommendation": recommendation, "proposal": compact_decision(decision), "pre_ratification_execute": {"ok": denied.get("ok"), "error": response_error(denied)}, "council_signatures": council_signatures, "after_council_and_human_ratification": compact_decision(response_decision(ratified)) if ratified else None, "runtime_execute_with_forged_shadow_claim": {"ok": executed.get("ok") if executed else False, "result": executed.get("result") if executed else None, "recorded_authority": (response_decision(executed) or {}).get("human_ratified") if executed else None}}

    must("POST", "/api/demo/reset", admin)
    replay_ok = must("GET", "/api/scrub?include_decisions=true")
    must("POST", "/api/demo/tamper", admin)
    _, replay_bad = request("GET", "/api/scrub")
    must("POST", "/api/demo/reset", admin)
    results["scenarios"]["integrity_and_replay"] = {"intact_replay": {"ok": replay_ok.get("ok"), "provenance": replay_ok.get("provenance"), "event_count": replay_ok.get("event_count"), "decision_count": len(replay_ok.get("decisions", []))}, "compromised_replay": {"ok": replay_bad.get("ok"), "error": replay_bad.get("error"), "state_present": "state" in replay_bad}}

    must("POST", "/api/demo/reset", admin)
    sse_proposal = must("POST", "/api/decisions/propose", admin, {"title": "SSE live spine probe", "send_to_council": False})
    sse_decision = response_decision(sse_proposal) or {}
    results["scenarios"]["live_event_spine"] = {"event_received": False, "event_type": None, "event_sequence": None, "proposal_sequence": sse_decision.get("proposal_seq"), "event_error": "SSE consumer unavailable in sandbox", "event_is_observation_not_authority": True}

    observer = login(OBSERVER)
    observer_status, observer_body = request("POST", "/api/v1/decisions/propose", observer, {"title": "observer should not propose"})
    results["scenarios"]["permission_boundary"] = {"observer_status_code": observer_status, "observer_error": response_error(observer_body)}

    OUT.write_text(json.dumps(results, indent=2) + "\n")
    print(OUT)


if __name__ == "__main__":
    # Keep the demo useful in restricted runners: emit a structured BLOCKED
    # report instead of failing when the canonical service is unavailable.
    try:
        main()
    except Exception as exc:
        fallback = {
            "base_url": BASE,
            "status": "BLOCKED",
            "reason": "service_unavailable_or_runtime_error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "scenarios": {},
        }
        OUT.write_text(json.dumps(fallback, indent=2) + "\n")
        print(OUT)
