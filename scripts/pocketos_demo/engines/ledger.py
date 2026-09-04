"""Canonical, hash-chained, append-only ledger.

The ledger is the historical authority for Pocket OS. Records are appended and
each record's hash chains to the previous record's hash so the chain is
independently verifiable. The backend is authoritative; the frontend only ever
displays ledger state and never writes it directly.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Optional


def canonical(obj: Any) -> str:
    """Canonical, deterministic JSON serialization.

    Dict ordering is preserved as inserted (JSON object ordering does not
    change hashes across implementations of the same dict), and NaN / Infinity
    are rejected so they can never enter a hash body.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def hash_record(record: dict[str, Any]) -> str:
    """SHA-256 over the canonical form, excluding the self-referential
    ``hash`` field. Pure, deterministic, and identical whether the record's
    hash is empty or already filled — write and verify must agree."""
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LedgerVerification:
    """Result of a full-chain verification."""

    valid: bool
    broken_index: Optional[int] = None

    @property
    def intact(self) -> bool:
        return self.valid

    def view(self) -> dict[str, Any]:
        return {
            "intact": self.valid,
            "valid": self.valid,
            "broken_index": self.broken_index,
        }


def verify_chain(records: list[dict[str, Any]]) -> LedgerVerification:
    """Verify the whole chain: each record's stored hash matches its recomputed
    hash and its previous_hash matches the prior record's hash."""
    prev_hash: Optional[str] = None
    for i, rec in enumerate(records):
        if hash_record(rec) != rec.get("hash"):
            return LedgerVerification(valid=False, broken_index=i)
        if i > 0 and rec.get("previous_hash") != prev_hash:
            return LedgerVerification(valid=False, broken_index=i)
        prev_hash = rec.get("hash")
    return LedgerVerification(valid=True)


class Ledger:
    """Append-only, hash-chained record store persisted to a JSON file.

    The file is the durable source of truth across server restarts. It is
    authoritative over any client view.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._records: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if os.path.exists(self._path):
            with open(self._path) as fh:
                data = json.load(fh)
            self._records = data if isinstance(data, list) else data.get("records", [])
        else:
            self._records = []

    def _save(self) -> None:
        with open(self._path, "w") as fh:
            json.dump(self._records, fh)

    def records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def replace_records(self, records: list[dict[str, Any]]) -> None:
        """Replace the whole ledger (seed/reset path). Demo-only, demo-gated."""
        self._records = list(records)
        self._save()

    def append(self, event: str, source: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Append a canonical v2 event, hashed against the current head.

        Every authoritative mutation travels through this single path so it is
        recorded, chained, and verifiable.
        """
        head = self._records[-1] if self._records else None
        row: dict[str, Any] = {
            "sequence": len(self._records) + 1,
            "event": event,
            "timestamp": payload.get("timestamp", 0),
            "source": source,
            "schema_version": "v2",
            "kind": event.split(".")[0],
            "payload": payload,
            "previous_hash": head["hash"] if head else None,
            "hash": "",
        }
        row["hash"] = hash_record(row)
        self._records.append(row)
        self._save()
        return dict(row)
