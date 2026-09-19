import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import chrysalis_pocketos_bridge as bridge


def test_bridge_submits_validated_mutation_as_proposal_only(tmp_path, monkeypatch):
    source = tmp_path / "sample.py"
    source.write_text("def enabled(flag):\n    return flag == True\n", encoding="utf-8")
    calls = []

    def fake_request(path, *, method="GET", payload=None, token=None):
        calls.append((path, method, payload, token))
        if path == "/api/login":
            return {"token": "server-token"}
        assert path == "/api/v1/decisions/propose"
        assert method == "POST"
        assert token == "server-token"
        assert payload["send_to_council"] is True
        assert payload["reversible"] is True
        assert "Chrysalis mutation review" in payload["title"]
        return {
            "ok": True,
            "decision": {
                "decision_id": payload["decision_id"],
                "status": "COUNCIL",
                "stage": "PROPOSAL",
                "council_approved": False,
                "human_ratified": False,
                "can_execute": False,
            },
        }

    monkeypatch.setattr(bridge, "request_json", fake_request)
    result = bridge.submit("SimplifyBooleanExpressions", source, "admin", "demo")

    assert result["proposal_only"] is True
    assert result["manifest"]["changed"] is True
    assert result["manifest"]["source_hash"]
    assert result["manifest"]["output_hash"]
    assert result["decision"]["status"] == "COUNCIL"
    assert result["decision"]["human_ratified"] is False
    assert result["decision"]["can_execute"] is False
    assert [call[0] for call in calls] == ["/api/login", "/api/v1/decisions/propose"]


def test_bridge_refuses_noop_mutation(tmp_path, monkeypatch):
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(bridge, "request_json", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network call")))

    try:
        bridge.submit("SimplifyBooleanExpressions", source, "admin", "demo")
    except ValueError as exc:
        assert "produced no validated change" in str(exc)
    else:
        raise AssertionError("noop mutation should not create a proposal")
