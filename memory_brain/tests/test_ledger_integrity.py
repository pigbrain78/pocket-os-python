import hashlib
import json

import pytest
from memory_brain import (
    ChainCompromisedError,
    LedgerEntry,
    verify_ledger_integrity,
)


def _entry_hash(previous_hash: str, payload: dict, timestamp: float) -> str:
    hash_input = f"{previous_hash}{json.dumps(payload)}{timestamp}".encode()
    return hashlib.sha256(hash_input).hexdigest()


def test_verify_ledger_integrity_passes_for_valid_chain():
    e0 = LedgerEntry(
        index=0,
        timestamp=1.0,
        payload={"event": "genesis"},
        previous_hash="",
        current_hash="genesis-hash",
    )
    e1 = LedgerEntry(
        index=1,
        timestamp=2.0,
        payload={"event": "next"},
        previous_hash=e0.current_hash,
        current_hash=_entry_hash(e0.current_hash, {"event": "next"}, 2.0),
    )

    assert verify_ledger_integrity([e0, e1]) is True


def test_verify_ledger_integrity_raises_on_previous_hash_mismatch():
    e0 = LedgerEntry(
        index=0,
        timestamp=1.0,
        payload={"event": "genesis"},
        previous_hash="",
        current_hash="genesis-hash",
    )
    e1 = LedgerEntry(
        index=1,
        timestamp=2.0,
        payload={"event": "next"},
        previous_hash="wrong-prev-hash",
        current_hash=_entry_hash("wrong-prev-hash", {"event": "next"}, 2.0),
    )

    with pytest.raises(ChainCompromisedError, match="Previous hash does not match current hash"):
        verify_ledger_integrity([e0, e1])


def test_verify_ledger_integrity_raises_on_current_hash_mismatch():
    e0 = LedgerEntry(
        index=0,
        timestamp=1.0,
        payload={"event": "genesis"},
        previous_hash="",
        current_hash="genesis-hash",
    )
    e1 = LedgerEntry(
        index=1,
        timestamp=2.0,
        payload={"event": "next"},
        previous_hash=e0.current_hash,
        current_hash="bad-current-hash",
    )

    with pytest.raises(ChainCompromisedError, match="Current hash does not match recomputed hash"):
        verify_ledger_integrity([e0, e1])
