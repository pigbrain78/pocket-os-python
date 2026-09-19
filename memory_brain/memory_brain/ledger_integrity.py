"""Standalone ledger entry hash-chain integrity verification utilities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


class ChainCompromisedError(Exception):
    """Raised when the ledger's cryptographic hash chain is broken."""

    def __init__(self, index: int, message: str):
        super().__init__(f"Ledger compromised at index {index}: {message}")
        self.index = index


@dataclass
class LedgerEntry:
    index: int
    timestamp: float
    payload: dict
    previous_hash: str
    current_hash: str


def verify_ledger_integrity(entries: list[LedgerEntry]) -> bool:
    """Verify the integrity of the ledger entries."""
    for i in range(1, len(entries)):
        prev_entry = entries[i - 1]
        curr_entry = entries[i]

        if prev_entry.current_hash != curr_entry.previous_hash:
            raise ChainCompromisedError(
                curr_entry.index,
                "Previous hash does not match current hash",
            )

        hash_input = (
            f"{curr_entry.previous_hash}"
            f"{json.dumps(curr_entry.payload)}"
            f"{curr_entry.timestamp}"
        ).encode()
        computed_hash = hashlib.sha256(hash_input).hexdigest()

        if curr_entry.current_hash != computed_hash:
            raise ChainCompromisedError(
                curr_entry.index,
                "Current hash does not match recomputed hash",
            )

    return True
