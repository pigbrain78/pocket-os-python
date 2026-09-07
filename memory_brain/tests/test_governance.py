"""Governance gate tests: LLM is advisory, human-in-the-loop for mutations."""

from memory_brain.core import MemoryBrain


def test_llm_mutation_routes_to_review_not_auto():
    """An LLM advisory actor may not auto-commit a supersession."""
    b = MemoryBrain(":memory:")
    a = b.remember("DB is PostgreSQL", memory_type="FACT")["memory_id"]
    res = b.remember("DB is now SQLite", memory_type="FACT",
                     supersedes=a, actor="llm", is_llm=True)
    assert res.get("requires_review") is True
    assert b.get(a)["status"] == "ACTIVE"   # nothing authoritative changed yet


def test_llm_approve_applies_supersession():
    """Human APPROVE of the review item applies the governed supersession."""
    b = MemoryBrain(":memory:")
    a = b.remember("DB is PostgreSQL", memory_type="FACT")["memory_id"]
    res = b.remember("DB is now SQLite", memory_type="FACT",
                     supersedes=a, actor="llm", is_llm=True)
    item_id = res["item_id"]
    out = b.apply_review_decision(item_id, "APPROVE", "human-owner")
    assert out["status"] == "APPROVE"
    assert out["applied"]["committed"] is True
    assert b.get(a)["status"] == "SUPERSEDED"
    # Decision + supersession are each a ledger event (auditable).
    types = [e.event_type for e in b.ledger.events()]
    assert "MEMORY_REVIEW_DECISION" in types
    assert "MEMORY_SUPERSEDED" in types


def test_llm_reject_leaves_state_unchanged():
    b = MemoryBrain(":memory:")
    a = b.remember("DB is PostgreSQL", memory_type="FACT")["memory_id"]
    res = b.remember("DB is now SQLite", memory_type="FACT",
                     supersedes=a, actor="llm", is_llm=True)
    out = b.apply_review_decision(res["item_id"], "REJECT", "human-owner")
    assert out["status"] == "REJECT"
    assert out["applied"] is None
    assert b.get(a)["status"] == "ACTIVE"


def test_sensitive_llm_proposal_requires_review():
    b = MemoryBrain(":memory:")
    res = b.remember("sensitive credential detail", memory_type="FACT",
                     actor="llm", is_llm=True, sensitive=True)
    assert res.get("requires_review") is True


def test_allow_auto_commit_enables_llm_mutation():
    b = MemoryBrain(":memory:", allow_auto_commit=True)
    a = b.remember("DB is PostgreSQL", memory_type="FACT")["memory_id"]
    res = b.remember("DB is now SQLite", memory_type="FACT",
                     supersedes=a, actor="llm", is_llm=True)
    assert res.get("committed") is True


def test_retract_is_irreversible_and_gated(brain):
    mid = brain.remember("to retract", memory_type="FACT")["memory_id"]
    res = brain.retract(mid, "no longer true", "agent")
    assert res.get("requires_review") is True
    assert brain.get(mid)["status"] == "ACTIVE"
    # Approve -> retraction applies.
    out = brain.apply_review_decision(res["item_id"], "APPROVE", "human-owner")
    assert out["applied"]["retracted"] is True
    assert brain.get(mid)["status"] == "RETRACTED"
    # Historical memory still queryable after retraction.
    assert brain.get(mid)["content"] == "to retract"


def test_retract_reject_leaves_active():
    brain = MemoryBrain(":memory:")
    mid = brain.remember("keep me", memory_type="FACT")["memory_id"]
    res = brain.retract(mid, "maybe not", "agent")
    out = brain.apply_review_decision(res["item_id"], "REJECT", "human-owner")
    assert out["status"] == "REJECT"
    assert brain.get(mid)["status"] == "ACTIVE"
