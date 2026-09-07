"""Ledger integrity, immutability, and replay tests."""

import sqlite3

import pytest
from memory_brain.ledger import Ledger, LedgerIntegrityError
from memory_brain import canonical
from memory_brain.core import MemoryBrain


def _fresh_ledger():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return Ledger(conn), conn


# --- append-only immutability -------------------------------------------
def test_append_creates_chained_events():
    led, _ = _fresh_ledger()
    e1 = led.append("MEMORY_CREATED", {"content": "a"})
    e2 = led.append("MEMORY_CREATED", {"content": "b"})
    assert e1.event_hash != e2.event_hash
    assert e2.previous_event_hash == e1.event_hash
    assert led.count() == 2


def test_verify_chain_passes_on_pristine_ledger():
    led, _ = _fresh_ledger()
    for i in range(10):
        led.append("EVENT", {"i": i})
    led.verify_chain()  # should not raise


def test_tamper_detection_event_payload():
    """Modifying a historical payload must break the chain."""
    led, conn = _fresh_ledger()
    led.append("MEMORY_CREATED", {"content": "original"})
    led.append("MEMORY_CREATED", {"content": "second"})
    # Silently rewrite the first event's payload (simulating tamper).
    conn.execute(
        "UPDATE ledger_events SET payload=? WHERE event_id=?",
        (canonical.canonical_json({"content": "TAMPERED"}),
         led.events()[0].event_id))
    conn.commit()
    with pytest.raises(LedgerIntegrityError):
        led.verify_chain()


def test_tamper_detection_chain_break():
    led, conn = _fresh_ledger()
    led.append("MEMORY_CREATED", {"content": "a"})
    e2 = led.append("MEMORY_CREATED", {"content": "b"})
    led.append("MEMORY_CREATED", {"content": "c"})
    # Break the chain by pointing e3's previous at a non-head value.
    conn.execute(
        "UPDATE ledger_events SET previous_event_hash='deadbeef' "
        "WHERE event_id=?", (e2.event_id,))
    conn.commit()
    with pytest.raises(LedgerIntegrityError):
        led.verify_chain()


def test_replay_deterministic():
    led, _ = _fresh_ledger()
    for i in range(5):
        led.append("MEMORY_CREATED", {"i": i})
    s1 = led.replay()
    s2 = led.replay()
    assert s1 == s2
    assert s1["counts"]["MEMORY_CREATED"] == 5


def test_replay_window():
    led, _ = _fresh_ledger()
    e1 = led.append("MEMORY_CREATED", {"i": 1})
    e2 = led.append("MEMORY_CREATED", {"i": 2})
    e3 = led.append("MEMORY_CREATED", {"i": 3})
    s = led.replay(start_event=e1.event_id, end_event=e2.event_id)
    # start inclusive, end inclusive by event_id match
    assert s["counts"]["MEMORY_CREATED"] == 2


def test_replay_with_applier():
    led, _ = _fresh_ledger()
    led.append("MEMORY_CREATED", {"val": 1})
    led.append("MEMORY_CREATED", {"val": 2})

    def applier(state, ev):
        state["total"] = state.get("total", 0) + ev.payload["val"]

    s = led.replay(applier=applier)
    assert s["total"] == 3


# --- memory immutability via the brain ----------------------------------
def test_supersede_appends_not_rewrites(brain):
    a = brain.remember("DB is PostgreSQL", memory_type="FACT")["memory_id"]
    ev_count_before = brain.ledger.count()
    b = brain.remember("DB is now SQLite", memory_type="FACT",
                       supersedes=a)["memory_id"]
    # Two new ledger events (one superseding creation).
    assert brain.ledger.count() >= ev_count_before + 1
    # Original still queryable, now SUPERSEDED.
    orig = brain.get(a)
    assert orig["status"] == "SUPERSEDED"
    assert orig["content"] == "DB is PostgreSQL"
    # New memory links back.
    assert brain.get(b)["status"] == "ACTIVE"


def test_historical_memory_never_disappears(brain):
    a = brain.remember("fact one", memory_type="FACT")["memory_id"]
    brain.remember("fact two", memory_type="FACT")
    # Retraction is governed (review) -- approve it, then it applies.
    res = brain.retract(a, "no longer true", "agent")
    brain.apply_review_decision(res["item_id"], "APPROVE", "human-owner")
    # Retracted memory still present and queryable.
    assert brain.get(a) is not None
    assert brain.get(a)["status"] == "RETRACTED"
    # Replay from ledger recovers both events.
    events = brain.ledger.events()
    assert any(e.event_type == "MEMORY_RETRACTED" for e in events)


def test_retract_requires_review_for_irreversible(brain):
    a = brain.remember("to retract", memory_type="FACT")["memory_id"]
    # Default brain requires human review for retraction (governance gate).
    res = brain.retract(a, "x", "human")
    assert res.get("requires_review") is True
    # Memory NOT yet retracted (still ACTIVE) until a human decides.
    assert brain.get(a)["status"] == "ACTIVE"
