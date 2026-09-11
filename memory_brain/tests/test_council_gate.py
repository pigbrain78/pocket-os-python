"""test_council_gate.py -- memory_brain council-gate integration tests.

Proves the memory_brain analogue of the Pocket OS invariant:

    an irreversible memory mutation (retract)
        ⇐ verified council quorum
    and nothing else.

A bare human review APPROVE is NOT authority on a council-gated brain. These
tests exercise the REAL council contract (imported from the Pocket OS tree) —
no mocks, no bypassed boundary.
"""

import os
import sys

# Ensure both the memory_brain package and the Pocket OS council contract are
# importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)            # .../memory_brain (top-level dir)
_WS = os.path.dirname(_ROOT)              # workspace root
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_WS, "scripts"))

# Demo signing must be on for the test harness to assemble quorums via the
# adapter's on-box helper.
os.environ["POCKETOS_COUNCIL_DEMO_SIGNING"] = "1"

import pytest

from memory_brain.core import MemoryBrain
from memory_brain import council as mbc


@pytest.fixture
def gated():
    """A council-gated in-memory brain."""
    b = MemoryBrain(":memory:", require_council_for_irreversible=True)
    yield b
    b.conn.close()


@pytest.fixture
def ungated():
    """Default brain (council gating off) — existing review path preserved."""
    b = MemoryBrain(":memory:")
    yield b
    b.conn.close()


def _make_retract_request(brain, content="a retractable fact", mtype="FACT"):
    mid = brain.remember(content, memory_type=mtype)["memory_id"]
    res = brain.retract(mid, "no longer true", "agent")
    return mid, res["item_id"]


def _quorum(memory_id, operation="retract"):
    """Assemble a valid 2-member quorum signature map for the candidate."""
    return {
        "council-a": mbc.sign_for_member("council-a", memory_id, operation),
        "council-b": mbc.sign_for_member("council-b", memory_id, operation),
    }


# ---------------------------------------------------------------------------
# Positive controls
# ---------------------------------------------------------------------------


def test_quorum_ratifies_irreversible_mutation(gated):
    mid, item_id = _make_retract_request(gated)
    out = gated.ratify_council(item_id, _quorum(mid))
    assert out["ratified"] is True
    assert gated.get(mid)["status"] == "RETRACTED"
    # Historical content still queryable.
    assert gated.get(mid)["content"] == "a retractable fact"


def test_ratified_event_recorded_on_ledger(gated):
    mid, item_id = _make_retract_request(gated)
    gated.ratify_council(item_id, _quorum(mid))
    evs = gated.ledger.events()
    types = [e.event_type for e in evs]
    assert "MEMORY_COUNCIL_RATIFIED" in types
    assert "MEMORY_RETRACTED" in types
    # Chain verifies after the ratified mutation.
    gated.verify.verify_chain()


# ---------------------------------------------------------------------------
# Boundary: bare human APPROVE is NOT authority
# ---------------------------------------------------------------------------


def test_bare_approve_does_not_mutate_gated(gated):
    mid, item_id = _make_retract_request(gated)
    out = gated.apply_review_decision(item_id, "APPROVE", "human-owner")
    assert out["applied"] is None
    assert out.get("council_required") is True
    # Memory is NOT retracted — a bare approve only PROPOSED.
    assert gated.get(mid)["status"] == "ACTIVE"


def test_ungated_brain_preserves_bare_approve_path(ungated):
    # Default (non-council-gated) brain: human APPROVE still applies retract.
    mid, item_id = _make_retract_request(ungated)
    out = ungated.apply_review_decision(item_id, "APPROVE", "human-owner")
    assert out["applied"]["retracted"] is True
    assert ungated.get(mid)["status"] == "RETRACTED"


def test_reject_on_gated_brain_never_mutates(gated):
    mid, item_id = _make_retract_request(gated)
    gated.apply_review_decision(item_id, "REJECT", "human-owner")
    assert gated.get(mid)["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Negative: quorum failures fail closed
# ---------------------------------------------------------------------------


def test_below_quorum_is_blocked(gated):
    mid, item_id = _make_retract_request(gated)
    siga = mbc.sign_for_member("council-a", mid, "retract")
    out = gated.ratify_council(item_id, {"council-a": siga})
    assert out["ratified"] is False
    assert gated.get(mid)["status"] == "ACTIVE"


def test_duplicate_signer_does_not_satisfy_quorum(gated):
    mid, item_id = _make_retract_request(gated)
    siga = mbc.sign_for_member("council-a", mid, "retract")
    out = gated.ratify_council(item_id, {"council-a": siga, "council-a2": siga})
    assert out["ratified"] is False
    assert gated.get(mid)["status"] == "ACTIVE"


def test_unknown_signer_is_rejected(gated):
    mid, item_id = _make_retract_request(gated)
    out = gated.ratify_council(item_id, {
        "council-a": "f" * 64, "council-evil": "f" * 64})
    assert out["ratified"] is False
    assert gated.get(mid)["status"] == "ACTIVE"


def test_invalid_hmac_is_rejected(gated):
    mid, item_id = _make_retract_request(gated)
    bad = {"council-a": "0" * 64, "council-b": "0" * 64}
    out = gated.ratify_council(item_id, bad)
    assert out["ratified"] is False
    assert gated.get(mid)["status"] == "ACTIVE"


def test_wrong_memory_id_binding_is_rejected(gated):
    # Signatures bound to a DIFFERENT memory must not ratify this one.
    mid_a, item_a = _make_retract_request(gated, content="fact A")
    # Create a second retract request for a second memory.
    mid_b, item_b = _make_retract_request(gated, content="fact B")
    # Signatures for memory B cannot ratify the item_A retraction.
    sigs_b = _quorum(mid_b)
    out = gated.ratify_council(item_a, sigs_b)
    assert out["ratified"] is False
    assert gated.get(mid_a)["status"] == "ACTIVE"


def test_wrong_operation_binding_is_rejected(gated):
    mid, item_id = _make_retract_request(gated)
    # Signatures computed for operation "delete" (a different candidate id)
    # must not ratify a retract request.
    sigs = {
        "council-a": mbc.sign_for_member("council-a", mid, "delete"),
        "council-b": mbc.sign_for_member("council-b", mid, "delete"),
    }
    out = gated.ratify_council(item_id, sigs)
    assert out["ratified"] is False
    assert gated.get(mid)["status"] == "ACTIVE"


def test_forged_authority_is_ignored(gated):
    mid, item_id = _make_retract_request(gated)
    # A caller passing a claimed authority string gets no weight.
    sigs = _quorum(mid)
    sigs["claimed_authority"] = "HUMAN"
    out = gated.ratify_council(item_id, sigs)
    # claimed_authority is not a member; quorum is unaffected and succeeds only
    # because council-a and council-b are present.
    assert out["ratified"] is True
    assert gated.get(mid)["status"] == "RETRACTED"


def test_non_council_required_op_cannot_be_ratified(gated):
    # A remember-type review item (op="remember") is NOT council-required;
    # ratify_council must refuse it rather than treat a non-irreversible op as
    # ratifiable. Build one via a sensitive LLM proposal that requires review.
    b = gated
    res = b.remember("sensitive llm proposal", memory_type="FACT",
                     sensitive=True, is_llm=True)
    assert res.get("requires_review") is True
    item_id = res["item_id"]
    out = b.ratify_council(item_id, _quorum("does-not-matter"))
    assert out["ratified"] is False
    assert out["reason"] and "not council-required" in out["reason"]


# ---------------------------------------------------------------------------
# Irreversibility + determinism
# ---------------------------------------------------------------------------


def test_ratified_retraction_is_terminal(gated):
    mid, item_id = _make_retract_request(gated)
    gated.ratify_council(item_id, _quorum(mid))
    assert gated.get(mid)["status"] == "RETRACTED"
    # A second retract request of the already-RETRACTED memory must not
    # re-activate it; it stays RETRACTED (history is immutable, not revived).
    res2 = gated.retract(mid, "trying again", "agent")
    assert res2.get("requires_review") is True
    # No ratification was supplied, so the memory must remain RETRACTED.
    assert gated.get(mid)["status"] == "RETRACTED"


def test_replay_is_deterministic(gated):
    mid, item_id = _make_retract_request(gated)
    gated.ratify_council(item_id, _quorum(mid))
    state1 = gated.ledger.replay()
    state2 = gated.ledger.replay()
    assert state1 == state2
    counts = state1.get("counts", {})
    assert counts.get("MEMORY_COUNCIL_RATIFIED") == 1
    assert counts.get("MEMORY_RETRACTED") == 1


# ---------------------------------------------------------------------------
# End-to-end chain proof
# ---------------------------------------------------------------------------


def test_full_council_chain(gated):
    """council signatures -> threshold verification -> ratified event ->
    memory mutation -> derived state updated -> evidence recorded."""
    mid, item_id = _make_retract_request(gated)
    # Signatures produced by distinct members over the bound candidate.
    sigs = {
        "council-a": mbc.sign_for_member("council-a", mid, "retract"),
        "council-b": mbc.sign_for_member("council-b", mid, "retract"),
    }
    # Threshold verification is authoritative.
    assert mbc.require_ratified(mid, "retract", sigs) is True
    # Ratification authorizes the mutation and records evidence on the ledger.
    out = gated.ratify_council(item_id, sigs)
    assert out["ratified"] is True
    # Derived projection reflects the authoritative state.
    assert gated.get(mid)["status"] == "RETRACTED"
    # Chain intact (tamper-evident).
    gated.verify.verify_chain()
    # The ratification event is present as evidence.
    types = [e.event_type for e in gated.ledger.events()]
    assert "MEMORY_COUNCIL_RATIFIED" in types
