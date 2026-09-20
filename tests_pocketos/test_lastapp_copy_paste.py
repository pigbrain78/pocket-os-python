import base64
from io import BytesIO

import pytest

import LASTAPP_COPY_PASTE as lastapp


@pytest.fixture()
def client(tmp_path, monkeypatch):
    service = lastapp.PocketOSService(
        human_principals={"alice"},
        human_credentials={"alice": "ok"},
        upload_dir=str(tmp_path),
    )
    monkeypatch.setattr(lastapp, "service", service)
    lastapp.app.config.update(TESTING=True)
    with lastapp.app.test_client() as client:
        yield client, service


def test_capture_route_is_idempotent_and_updates_diagnostics(client):
    http, _ = client
    payload = {"capture_id": "1", "title": "Note", "content": "Remember this"}
    first = http.post("/api/pocket/captures", json=payload)
    second = http.post("/api/pocket/captures", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.get_json() == second.get_json()

    diagnostics = http.get("/api/pocket/diagnostics").get_json()
    assert diagnostics["capture_count"] == 1
    assert diagnostics["event_count"] == 1
    assert diagnostics["capture_events"][0]["event_type"] == "decision.proposed"


def test_council_routes_support_evaluate_and_ratify(client):
    http, _ = client

    auth = http.post("/api/pocket/authenticate", json={"principal": "alice", "credential": "ok"})
    assert auth.status_code == 200
    token = auth.get_json()["session_token"]

    proposal = http.post(
        "/api/pocket/council/proposals",
        json={
            "decision_id": "DEC-42",
            "content": {"title": "Ship it"},
            "originating_source": "human",
            "requested_capability": "deploy",
        },
    )
    assert proposal.status_code == 201
    proposal_body = proposal.get_json()
    proposal_hash = proposal_body["proposal"]["content_hash"]

    evaluation = http.post(
        "/api/pocket/council/DEC-42/evaluate",
        json={"policy": {"required_evidence": ["ticket"]}, "evidence": {"ticket": "ABC-123"}},
    )
    assert evaluation.status_code == 200
    assert evaluation.get_json()["canonical_state"] == "AWAITING_HUMAN_RATIFICATION"

    ratified = http.post(
        "/api/pocket/council/DEC-42/ratify",
        json={"principal": "alice", "proposal_hash": proposal_hash},
        headers={"Authorization": "Bearer " + token},
    )
    assert ratified.status_code == 200
    assert ratified.get_json()["canonical_state"] == "RATIFIED"

    state = http.get("/api/pocket/council/DEC-42/state")
    assert state.status_code == 200
    assert state.get_json()["canonical_state"] == "RATIFIED"


def test_council_routes_reject_invalid_auth_and_stale_hash(client):
    http, _ = client
    proposal = http.post(
        "/api/pocket/council/proposals",
        json={
            "decision_id": "DEC-77",
            "content": {"title": "Review"},
            "originating_source": "human",
            "requested_capability": "deploy",
        },
    )
    assert proposal.status_code == 201
    proposal_hash = proposal.get_json()["proposal"]["content_hash"]
    evaluation = http.post("/api/pocket/council/DEC-77/evaluate", json={"policy": {}, "evidence": {}})
    assert evaluation.status_code == 200

    bad_auth = http.post(
        "/api/pocket/council/DEC-77/ratify",
        json={"principal": "alice", "proposal_hash": proposal_hash},
        headers={"Authorization": "******"},
    )
    assert bad_auth.status_code == 403
    assert bad_auth.get_json()["error"] == "UNVERIFIED_HUMAN_AUTHORITY"

    auth = http.post("/api/pocket/authenticate", json={"principal": "alice", "credential": "ok"})
    token = auth.get_json()["session_token"]
    stale = http.post(
        "/api/pocket/council/DEC-77/ratify",
        json={"principal": "alice", "proposal_hash": "not-the-real-hash"},
        headers={"Authorization": "Bearer " + token},
    )
    assert stale.status_code == 409
    assert stale.get_json()["error"] == "PROPOSAL_HASH_MISMATCH"


def test_council_state_unknown_decision_is_not_found(client):
    http, _ = client
    response = http.get("/api/pocket/council/UNKNOWN/state")
    assert response.status_code == 404
    assert response.get_json()["error"] == "UNKNOWN_DECISION"


def test_state_hash_stays_json_serializable_after_evaluation():
    service = lastapp.PocketOSService(human_principals={"alice"}, human_credentials={"alice": "ok"})
    proposal = service.council_propose(
        {
            "decision_id": "DEC-100",
            "content": {"title": "Collect evidence"},
            "originating_source": "human",
            "requested_capability": "memory.register",
        }
    )
    service.evaluate("DEC-100", {"policy": {"missing_information": ["approver"]}})

    assert proposal["state_hash"]
    assert len(service.council.state_hash()) == 64


def test_file_intake_route_accepts_base64_payload(client, tmp_path):
    http, _ = client
    encoded = base64.b64encode(b"hello world").decode()

    response = http.post(
        "/api/pocket/files/intake",
        json={"name": "notes.txt", "media_type": "text/plain", "source": "local", "data_b64": encoded},
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["name"] == "notes.txt"
    assert body["size"] == 11
    assert (tmp_path / "notes.txt").read_text() == "hello world"


def test_file_intake_route_accepts_multipart_upload(client, tmp_path):
    http, _ = client

    response = http.post(
        "/api/pocket/files/intake",
        data={"source": "local", "file": (BytesIO(b"image-bytes"), "photo.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["media_type"] == "image/png"
    assert (tmp_path / "photo.png").read_bytes() == b"image-bytes"


def test_file_intake_rejects_unsupported_extension(client):
    http, _ = client
    encoded = base64.b64encode(b"hello world").decode()

    response = http.post(
        "/api/pocket/files/intake",
        json={"name": "notes.exe", "media_type": "application/octet-stream", "source": "local", "data_b64": encoded},
    )

    assert response.status_code == 422
    assert response.get_json()["error"] == "UNSUPPORTED_EXTENSION"
