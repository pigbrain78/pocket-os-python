"""Pocket OS core engine tests.

Exercises the canonical hash-chained ledger, verification, seeds, governance
counters, and the genome. All pure over the seeded ledger — no server needed.
"""

import sys
import os
import math
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from pocketos_demo.engines import (
    canonical,
    hash_record,
    Ledger,
    verify_chain,
    seed_ledger,
    SEED_RECORDS,
    contradiction_count,
    governance_counters,
    genome_traits,
    GENOME_TRAITS,
    DEMO_FEATURE_GATE,
)


def _records():
    return seed_ledger()


# ---------------------------------------------------------------------------
# Canonicalization & hashing
# ---------------------------------------------------------------------------


def test_canonical_is_deterministic():
    a = {"b": 1, "a": 2, "c": [1, {"x": None, "y": True}]}
    b = {"c": [1, {"y": True, "x": None}], "a": 2, "b": 1}
    assert canonical(a) == canonical(b)


def test_canonical_rejects_nan():
    try:
        canonical({"x": float("nan")})
    except ValueError:
        return
    raise AssertionError("NaN must never enter a canonical serialization")


def test_canonical_is_compact_json():
    s = canonical({"a": [1, 2], "b": "x"})
    assert " " not in s
    assert "\n" not in s


def test_hash_record_excludes_own_hash_field():
    # hash must be a pure function of the body; whether hash is empty or filled
    # must not change the result.
    rec = {"sequence": 1, "event": "x", "payload": {"title": "t"}, "previous_hash": None, "hash": ""}
    h1 = hash_record(rec)
    rec["hash"] = h1
    assert hash_record(rec) == h1  # idempotent regardless of filled hash


def test_hash_record_changes_with_payload():
    a = hash_record({"sequence": 1, "payload": {"title": "one"}})
    b = hash_record({"sequence": 1, "payload": {"title": "two"}})
    assert a != b


def test_hash_is_sha256_hex():
    h = hash_record({"sequence": 1, "payload": {}})
    assert len(h) == 64
    int(h, 16)  # hex


def test_hash_order_stability():
    # two structurally identical dicts in different insertion order hash equal
    x = hash_record({"payload": {"title": "t", "note": "n"}})
    y = hash_record({"payload": {"note": "n", "title": "t"}})
    assert x == y


# ---------------------------------------------------------------------------
# Seed chain
# ---------------------------------------------------------------------------


def test_seed_is_intact():
    assert verify_chain(_records()).intact is True


def test_seed_has_expected_shape():
    recs = _records()
    assert recs
    for r in recs:
        assert r["hash"]
        assert r["schema_version"] == "v2"
        assert "sequence" in r


def test_seed_sequences_are_contiguous():
    for i, r in enumerate(_records()):
        assert r["sequence"] == i + 1


def test_seed_records_are_immutable_copies():
    a = seed_ledger()
    a[0]["payload"] = {"title": "tampered"}
    b = seed_ledger()
    assert b[0]["payload"] != {"title": "tampered"}


def test_contradiction_count_seed():
    # 4 web/saas tension-flagged memory records
    assert contradiction_count(_records()) == 4


def test_governance_counters_seed():
    c = governance_counters(_records())
    assert c.executed == 1
    assert c.denied == 1
    assert c.reversed == 1
    assert "denied" in c.render()


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------


def test_tamper_breaks_chain():
    recs = _records()
    recs[3]["payload"] = dict(recs[3]["payload"])
    recs[3]["payload"]["title"] = "tampered"
    v = verify_chain(recs)
    assert v.intact is False
    assert v.broken_index is not None


def test_hash_break_is_detected():
    recs = _records()
    recs[5]["hash"] = "0" * 64
    assert verify_chain(recs).intact is False


def test_previous_hash_break_is_detected():
    recs = _records()
    recs[6]["previous_hash"] = "f" * 64
    assert verify_chain(recs).intact is False


def test_verify_empty_chain_is_valid():
    assert verify_chain([]).intact is True


# ---------------------------------------------------------------------------
# Ledger store
# ---------------------------------------------------------------------------


def _temp_ledger():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(path)
    return Ledger(path), path


def test_ledger_append_chains_and_persists():
    lg, path = _temp_ledger()
    lg.replace_records(seed_ledger())
    n = len(lg)
    rec = lg.append("decision.proposed", "Test", {"title": "append probe", "decision_id": "T-1"})
    assert len(lg) == n + 1
    assert verify_chain(lg.records()).intact is True
    assert rec["sequence"] == n + 1
    assert rec["previous_hash"] == lg.records()[-2]["hash"]
    os.remove(path)


def test_ledger_reloads_from_file():
    lg, path = _temp_ledger()
    lg.replace_records(seed_ledger())
    lg2 = Ledger(path)
    assert len(lg2) == len(lg)
    assert verify_chain(lg2.records()).intact is True
    os.remove(path)


def test_ledger_legacy_append_keeps_chain_intact():
    lg, path = _temp_ledger()
    lg.replace_records(seed_ledger())
    head = lg.records()[-1]
    legacy = {
        "id": "legacy-1",
        "schema_version": "legacy_v1",
        "consensus": 70,
        "tension": None,
        "kind": None,
        "previous_hash": head["hash"],
    }
    legacy["hash"] = hash_record(legacy)
    recs = lg.records()
    recs.append(legacy)
    lg.replace_records(recs)
    assert verify_chain(lg.records()).intact is True
    os.remove(path)


def test_ledger_verify_rejects_tamper_after_reload():
    lg, path = _temp_ledger()
    lg.replace_records(seed_ledger())
    recs = lg.records()
    recs[2]["payload"] = dict(recs[2]["payload"])
    recs[2]["payload"]["title"] = "injected"
    recs[2]["hash"] = hash_record(recs[2])  # recompute would fix it...
    lg.replace_records(recs)
    # ...but the successor's previous_hash no longer matches, so still broken
    assert verify_chain(lg.records()).intact is False
    os.remove(path)


# ---------------------------------------------------------------------------
# Genome
# ---------------------------------------------------------------------------


def test_genome_six_distinct_traits():
    traits = genome_traits()
    assert len(traits) == 6
    names = [t.name for t in traits]
    assert names == list(GENOME_TRAITS)
    assert len(set(names)) == 6


def test_genome_scores_in_range_and_discriminate():
    scores = [t.score for t in genome_traits()]
    assert all(0 <= s <= 100 for s in scores)
    assert len(set(scores)) > 1  # must discriminate, not all equal


def test_genome_no_saturation():
    scores = [t.score for t in genome_traits()]
    assert 99 not in scores
    assert 100 not in scores


def test_genome_delta_clamps():
    traits = genome_traits(base={"recall": 150, "focus": -10})
    by = {t.name: t.score for t in traits}
    assert by["recall"] == 100
    assert by["focus"] == 0
