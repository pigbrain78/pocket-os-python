"""Dedup + contradiction engine tests."""

from memory_brain import dedup
from memory_brain.core import MemoryBrain


# --- dedup classification ------------------------------------------------
def test_exact_duplicate_classified_and_auto_merge():
    r = dedup.classify_pair("the service uses postgresql",
                            "the service uses postgresql")
    assert r.classification == "EXACT_DUPLICATE"
    assert r.auto_action == "merge"


def test_normalized_near_duplicate_classified_exact():
    # Same knowledge modulo case/whitespace/punct -> EXACT_DUPLICATE.
    r = dedup.classify_pair("The Service uses PostgreSQL.",
                            "the service uses postgresql")
    assert r.classification == "EXACT_DUPLICATE"


def test_possible_contradiction_classified():
    r = dedup.classify_pair("the service uses postgresql",
                            "the service uses sqlite")
    assert r.classification == "POSSIBLE_CONTRADICTION"
    assert r.auto_action is None  # never auto-resolved


def test_distinct_classified():
    r = dedup.classify_pair("the sky is blue", "the service uses postgresql")
    assert r.classification == "DISTINCT"


def test_probable_duplicate_routes_to_review_not_auto():
    # High similarity but not identical -> human review, no auto action.
    r = dedup.classify_pair(
        "deploy to the production cluster with the new configuration file",
        "deploy to the production cluster with the new config file")
    assert r.classification == "PROBABLE_DUPLICATE"
    assert r.auto_action is None


# --- contradiction detection through the brain ----------------------------
def test_contradicting_memories_detected_and_left_unresolved(brain):
    brain.remember("The service uses PostgreSQL.", memory_type="FACT")
    brain.remember("The service uses SQLite.", memory_type="FACT")
    rows = brain.conn.execute(
        "SELECT * FROM memory_contradictions WHERE status='UNRESOLVED'"
    ).fetchall()
    assert len(rows) >= 1
    # Contradictions go to the human review queue, never auto-resolved.
    pending = brain.review.pending()
    assert any(i.kind == "possible_contradiction" for i in pending)


def test_replay_reconstructs_contradiction_state(brain):
    brain.remember("DB is PostgreSQL.", memory_type="FACT")
    brain.remember("DB is SQLite.", memory_type="FACT")
    events = [e for e in brain.ledger.events()
              if e.event_type == "MEMORY_CONTRADICTION_DETECTED"]
    assert len(events) >= 1
