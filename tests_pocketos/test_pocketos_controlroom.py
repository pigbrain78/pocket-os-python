"""Tests for the Pocket OS control-room engines: Cognitive Twin, AI Shadow,
and the decision lifecycle / constitutional runtime.

These exercise the epistemic-state discipline (an inference is never rendered
as a fact), the AI Shadow advisory boundary (authority is always NONE), and the
negative guarantees of the constitutional path:

  * browser cannot execute directly
  * AI Shadow cannot execute directly
  * Cognitive Twin cannot execute directly
  * rejected decisions cannot execute
  * unratified decisions cannot execute
  * client-side authority claims are ignored
  * an in-memory ratification-flag mutation is ignored (runtime re-derives
    truth from the ledger)
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from pocketos_demo.engines import (
    Ledger,
    seed_ledger,
    verify_chain,
    cognitive_state,
    shadow_state,
    DecisionRegistry,
    ConstitutionalRuntime,
    ExecutionDenied,
    NO_AUTHORITY,
    HUMAN_AUTHORITY,
    INFERRED,
    VERIFIED,
    UNCERTAIN,
)


def _fresh_ledger():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(path)
    lg = Ledger(path)
    lg.replace_records(seed_ledger())
    return lg, path


def _records():
    return seed_ledger()


def _count_kind(records, prefix):
    return sum(1 for r in records if (r.get("event") or "").startswith(prefix))


# ---------------------------------------------------------------------------
# Cognitive Twin
# ---------------------------------------------------------------------------


def test_twin_current_focus_is_inferred_not_verified():
    cs = cognitive_state(_records())
    assert cs.current_focus.epistemic == INFERRED
    assert 0.0 <= cs.current_focus.confidence <= 1.0
    assert cs.current_focus.provenance.startswith("ledger#")
    assert cs.current_focus.evidence


def test_twin_memories_are_verified_or_uncertain():
    cs = cognitive_state(_records())
    for m in cs.relevant_memories:
        assert m.epistemic in (VERIFIED, UNCERTAIN)


def test_twin_inference_carries_provenance_and_evidence():
    cs = cognitive_state(_records())
    for item in cs.decision_history + cs.relevant_memories + cs.active_projects:
        assert item.provenance.startswith("ledger#")
        assert item.evidence


def test_twin_recent_observations_are_observed():
    cs = cognitive_state(_records())
    for obs in cs.recent_observations:
        assert obs.epistemic == "OBSERVED"


def test_twin_never_presents_inference_as_fact():
    cs = cognitive_state(_records())
    all_items = (
        [cs.current_focus]
        + list(cs.open_loops)
        + list(cs.closed_loops)
        + list(cs.relevant_memories)
        + list(cs.decision_history)
        + list(cs.relationships)
        + list(cs.recent_observations)
    )
    assert all_items
    for it in all_items:
        assert it.epistemic in {"OBSERVED", "VERIFIED", "INFERRED", "UNCERTAIN", "REJECTED", "STALE"}


def test_twin_focus_is_hedged_not_asserted():
    cs = cognitive_state(_records())
    assert "appears" in cs.current_focus.text.lower()


# ---------------------------------------------------------------------------
# AI Shadow
# ---------------------------------------------------------------------------


def test_shadow_items_are_advisory_with_no_authority():
    sh = shadow_state(_records())
    assert sh["items"]
    for item in sh["items"]:
        assert item["authority"] == "NONE"


def test_shadow_boundary_forbids_execution_and_ratification():
    sh = shadow_state(_records())
    b = sh["authority_boundary"]
    assert b["shadow_can_execute"] is False
    assert b["shadow_can_ratify"] is False
    assert b["execution_requires"] == ["COUNCIL_CONSENSUS", "HUMAN_RATIFICATION"]


def test_shadow_detects_tension_warning():
    sh = shadow_state(_records())
    types = {i["type"] for i in sh["items"]}
    assert "WARNING" in types
    for item in sh["items"]:
        assert item["status"] == "advisory"


# ---------------------------------------------------------------------------
# Decision lifecycle / constitutional runtime
# ---------------------------------------------------------------------------


def test_seeded_decisions_restore_expected_statuses():
    recs = _records()
    assert _count_kind(recs, "decision.proposed") == 3
    reg = DecisionRegistry()
    reg.rebuild(recs)
    by_id = {d.decision_id: d for d in reg.all()}
    assert by_id["D-CORPUS-1001"].status == "RATIFIED"
    assert by_id["D-CORPUS-1001"].human_ratified is True
    assert by_id["D-METRICS-1002"].status == "REJECTED"
    assert by_id["D-METRICS-1002"].rejected is True
    assert by_id["D-WORKSPACE-1003"].status == "PENDING"


def test_rejected_decision_cannot_execute():
    lg, path = _fresh_ledger()
    reg = DecisionRegistry()
    reg.rebuild(lg.records())
    runtime = ConstitutionalRuntime(reg, lg)
    try:
        runtime.execute("D-METRICS-1002")
    except ExecutionDenied as e:
        assert "rejected" in e.reason
    else:
        raise AssertionError("rejected decision must not execute")
    os.remove(path)


def test_unratified_pending_decision_cannot_execute():
    lg, path = _fresh_ledger()
    reg = DecisionRegistry()
    reg.rebuild(lg.records())
    runtime = ConstitutionalRuntime(reg, lg)
    try:
        runtime.execute("D-WORKSPACE-1003")
    except ExecutionDenied as e:
        assert "not human-ratified" in e.reason
    else:
        raise AssertionError("unratified decision must not execute")
    os.remove(path)


def test_client_claimed_human_authority_is_ignored():
    lg, path = _fresh_ledger()
    reg = DecisionRegistry()
    reg.rebuild(lg.records())
    runtime = ConstitutionalRuntime(reg, lg)
    try:
        runtime.execute("D-WORKSPACE-1003", claimed_authority=HUMAN_AUTHORITY)
    except ExecutionDenied:
        pass
    else:
        raise AssertionError("client-claimed authority must be ignored")
    assert _count_kind(lg.records(), "decision.executed") == 0
    os.remove(path)


def test_shadow_cannot_execute_anything():
    sh = shadow_state(_records())
    for item in sh["items"]:
        assert item["authority"] == "NONE"
    lg, path = _fresh_ledger()
    reg = DecisionRegistry()
    reg.rebuild(lg.records())
    runtime = ConstitutionalRuntime(reg, lg)
    try:
        runtime.execute("shadow-recommendation-1")
    except ExecutionDenied:
        pass
    else:
        raise AssertionError("shadow-only id must not execute")
    os.remove(path)


def test_cognitive_twin_cannot_execute_anything():
    lg, path = _fresh_ledger()
    reg = DecisionRegistry()
    reg.rebuild(lg.records())
    runtime = ConstitutionalRuntime(reg, lg)
    try:
        runtime.execute("twin-belief-1")
    except ExecutionDenied:
        pass
    else:
        raise AssertionError("twin-only id must not execute")
    os.remove(path)


def test_ratified_decision_can_execute_once():
    lg, path = _fresh_ledger()
    reg = DecisionRegistry()
    reg.rebuild(lg.records())
    runtime = ConstitutionalRuntime(reg, lg)
    result = runtime.execute("D-CORPUS-1001")
    assert result["executed"] is True
    try:
        runtime.execute("D-CORPUS-1001")
    except ExecutionDenied as e:
        assert "already executed" in e.reason
    else:
        raise AssertionError("a decision must execute only once")
    os.remove(path)


def test_full_ratify_lifecycle_executes():
    lg, path = _fresh_ledger()
    reg = DecisionRegistry()
    reg.rebuild(lg.records())
    runtime = ConstitutionalRuntime(reg, lg)
    start = len(lg.records())

    rec = lg.append("decision.proposed", "WebClient", {
        "title": "Run nightly index", "decision_id": "D-INDEX-9",
        "risk": "LOW", "reversible": True, "send_to_council": True,
    })
    reg.ingest(rec)
    assert reg.get("D-INDEX-9").status == "COUNCIL"
    assert reg.get("D-INDEX-9").human_ratified is False

    rec = lg.append("decision.council_approved", "Council", {"decision_id": "D-INDEX-9"})
    reg.ingest(rec)
    assert reg.get("D-INDEX-9").status == "AWAITING_RATIFICATION"

    try:
        runtime.execute("D-INDEX-9")
    except ExecutionDenied:
        pass
    else:
        raise AssertionError("council-approved but unratified must not execute")

    rec = lg.append("decision.ratified", "Human", {"decision_id": "D-INDEX-9", "authority": "HUMAN"})
    reg.ingest(rec)
    assert reg.get("D-INDEX-9").human_ratified is True
    assert reg.get("D-INDEX-9").status == "RATIFIED"

    result = runtime.execute("D-INDEX-9")
    assert result["executed"] is True
    assert len(lg.records()) == start + 4
    assert _count_kind(lg.records(), "decision.executed") == 1
    os.remove(path)


def test_ratify_via_registry_requires_recorded_event():
    # A client mutating the in-memory Decision (setting human_ratified=True by
    # hand) must NOT grant execution — the runtime re-derives truth from the
    # ledger and only a recorded ratified event advances it.
    lg, path = _fresh_ledger()
    reg = DecisionRegistry()
    reg.rebuild(lg.records())
    runtime = ConstitutionalRuntime(reg, lg)
    d = reg.get("D-WORKSPACE-1003")
    d.human_ratified = True  # dishonest in-process bypass attempt
    try:
        runtime.execute("D-WORKSPACE-1003")
    except ExecutionDenied:
        pass
    else:
        raise AssertionError("runtime must not trust in-memory ratification flag")
    os.remove(path)


def test_decision_state_replay_reconstructs_registry():
    # Scrub to a midpoint and rebuild the decision registry from the scrubbed
    # events: it must reflect only the decisions proposed up to that point.
    lg, path = _fresh_ledger()
    # append a new proposal past the seed so the midpoint excludes it
    rec = lg.append("decision.proposed", "WebClient", {
        "title": "late proposal", "decision_id": "D-LATE", "risk": "LOW",
        "reversible": True, "send_to_council": False,
    })
    records = lg.records()
    seed_len = 25
    mid = seed_len  # scrub to the end of the seed (excludes D-LATE at 26)
    from pocketos_demo.engines import Scrubber

    scrub = Scrubber(lg).scrub(end_seq=mid)
    reg = DecisionRegistry()
    reg.rebuild(list(scrub.events))
    ids = [d.decision_id for d in reg.all()]
    assert "D-LATE" not in ids
    assert "D-CORPUS-1001" in ids
    os.remove(path)


def test_tampered_ledger_state_is_detected():
    recs = _records()
    recs[3]["payload"] = dict(recs[3]["payload"])
    recs[3]["payload"]["title"] = "spurious injected boot event"
    assert verify_chain(recs).intact is False
