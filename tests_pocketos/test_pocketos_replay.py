"""Pocket OS replay / scrubber engine tests.

Verifies the deterministic reconstruction of ledger state and the core
invariant: the scrubber refuses to reconstruct over a broken (compromised)
chain and never produces a half-reconstructed state.
"""

import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from pocketos_demo.engines import (
    Ledger,
    seed_ledger,
    verify_chain,
    Scrubber,
    ScrubberError,
    hash_record,
)


def _fresh_ledger():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(path)
    lg = Ledger(path)
    lg.replace_records(seed_ledger())
    return lg, path


def _intact_ledger():
    return _fresh_ledger()[0]


def _tampered_records():
    recs = seed_ledger()
    recs[3]["payload"] = dict(recs[3]["payload"])
    recs[3]["payload"]["title"] = "tampered"
    return recs


# ---------------------------------------------------------------------------
# Intact reconstruction
# ---------------------------------------------------------------------------


def test_scrub_reconstructs_to_head():
    lg, path = _fresh_ledger()
    result = Scrubber(lg).scrub()
    assert result.event_count == len(lg)
    assert result.end_seq == len(lg)
    os.remove(path)


def test_scrub_head_has_provenance():
    lg, path = _fresh_ledger()
    result = Scrubber(lg).scrub()
    assert "Reconstructed from ledger events" in result.provenance_line()
    os.remove(path)


def test_scrub_is_deterministic():
    lg, path = _fresh_ledger()
    a = Scrubber(lg).scrub()
    b = Scrubber(lg).scrub()
    assert a.state == b.state
    assert a.event_count == b.event_count
    os.remove(path)


def test_scrub_to_midpoint_counts_kinds():
    lg, path = _fresh_ledger()
    result = Scrubber(lg).scrub(end_seq=8)
    counts = result.state["counts"]
    assert sum(counts.values()) == 8
    os.remove(path)


def test_scrub_invalid_end_raises():
    lg, path = _fresh_ledger()
    for bad in (-1, len(lg) + 5, "7", 2.5):
        try:
            Scrubber(lg).scrub(end_seq=bad)
        except (ScrubberError, TypeError):
            continue
        raise AssertionError(f"invalid end_seq {bad!r} must not produce a result")
    os.remove(path)


# ---------------------------------------------------------------------------
# Compromised chain refusal
# ---------------------------------------------------------------------------


def test_scrub_refuses_tampered_chain():
    lg, path = _fresh_ledger()
    lg.replace_records(_tampered_records())
    try:
        Scrubber(lg).scrub()
    except ScrubberError as e:
        assert "compromised" in str(e)
    else:
        raise AssertionError("scrubber must refuse a broken chain")
    os.remove(path)


def test_scrub_error_carries_broken_seq():
    lg, path = _fresh_ledger()
    lg.replace_records(_tampered_records())
    try:
        Scrubber(lg).scrub()
    except ScrubberError as e:
        assert e.broken_seq is not None
    else:
        raise AssertionError("broken_seq must be reported")
    os.remove(path)


def test_scrub_tampered_reports_correct_broken_index():
    lg, path = _fresh_ledger()
    recs = seed_ledger()
    recs[6]["hash"] = "0" * 64
    lg.replace_records(recs)
    try:
        Scrubber(lg).scrub()
    except ScrubberError as e:
        assert e.broken_seq == 7  # 0-indexed 6 -> 1-based sequence 7
    os.remove(path)


def test_reset_restores_replay():
    lg, path = _fresh_ledger()
    lg.replace_records(_tampered_records())
    try:
        Scrubber(lg).scrub()
    except ScrubberError:
        pass
    else:
        raise AssertionError("tampered chain must refuse")
    lg.replace_records(seed_ledger())
    result = Scrubber(lg).scrub()
    assert result.event_count == len(lg)
    os.remove(path)


def test_scrub_kind_counts_match_events():
    # The reconstructed kind counts must equal a straight scan of the same
    # events — the fold never double-counts and never drops a v2 event.
    lg, path = _fresh_ledger()
    result = Scrubber(lg).scrub()
    counts = result.state["counts"]
    from collections import Counter

    expected = Counter(r.get("event", "").split(".")[0] for r in lg.records())
    assert counts == dict(expected)
    os.remove(path)


def test_scrub_skips_legacy_records_in_fold():
    # legacy_v1 records carry no event type/kind. The fold skips them rather
    # than crashing on a None/missing event — this joint surfaced only in the
    # browser.
    lg, path = _fresh_ledger()
    recs = lg.records()
    head = recs[-1]
    legacy = {
        "sequence": len(recs) + 1,
        "id": "legacy-1",
        "schema_version": "legacy_v1",
        "consensus": 70,
        "tension": None,
        "kind": None,
        "previous_hash": head["hash"],
    }
    legacy["hash"] = hash_record(legacy)
    recs.append(legacy)
    lg.replace_records(recs)
    result = Scrubber(lg).scrub()
    assert result.event_count == len(recs)
    os.remove(path)
