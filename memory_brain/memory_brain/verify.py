"""verify.py -- cryptographic and structural verification.

Exposes verify_chain(), verify_memory(), verify_provenance(),
verify_context(), and verify_snapshot() so any subsystem or agent can prove
the integrity of the ledger and its derived artifacts.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

from . import canonical, normalize


class VerificationError(Exception):
    """Raised when verification fails."""


class Verifier:
    def __init__(self, conn: sqlite3.Connection, ledger):
        self.conn = conn
        self.ledger = ledger

    def verify_chain(self) -> dict:
        """Verify the full ledger hash chain; return a report dict."""
        try:
            self.ledger.verify_chain()
            return {"ok": True, "events": self.ledger.count()}
        except Exception as e:  # LedgerIntegrityError
            raise VerificationError(str(e)) from e

    def verify_memory(self, memory_id: str) -> dict:
        """Recompute a memory's content_hash and confirm the committing event
        exists in the chain and the memory hash matches its stored value."""
        row = self.conn.execute(
            "SELECT * FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
        if row is None:
            raise VerificationError(f"memory {memory_id} not found")
        expect = normalize.content_hash(row["content"])
        if expect != row["content_hash"]:
            raise VerificationError(
                f"content_hash mismatch for {memory_id}: stored "
                f"{row['content_hash']}, recomputed {expect}")
        # Confirm the committing event is present and chained.
        ev = self.ledger.get(row["event_id"])
        if ev is None:
            raise VerificationError(
                f"committing event {row['event_id']} for {memory_id} missing")
        return {"ok": True, "memory_id": memory_id, "content_hash": expect,
                "committing_event": ev.event_id}

    def verify_provenance(self, memory_id: str) -> dict:
        """Ensure a memory has provenance and every source exists."""
        row = self.conn.execute(
            "SELECT * FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
        if row is None:
            raise VerificationError(f"memory {memory_id} not found")
        if not row["source_id"]:
            raise VerificationError(
                f"memory {memory_id} has no source (provenance missing)")
        src = self.conn.execute(
            "SELECT * FROM memory_sources WHERE source_id=?",
            (row["source_id"],)).fetchone()
        if src is None:
            raise VerificationError(
                f"memory {memory_id} source {row['source_id']} missing")
        return {"ok": True, "memory_id": memory_id, "source_id": row["source_id"]}

    def verify_context(self, package: dict) -> dict:
        """Recompute and confirm a context package hash."""
        body = dict(package)
        stored = body.pop("context_hash", None)
        digest = canonical.digest(body, canonical.CONTEXT_PACKAGE)
        if stored is not None and stored != digest:
            raise VerificationError("context package hash mismatch")
        return {"ok": True, "context_hash": digest}

    def verify_snapshot(self, snapshot: dict, current_memory_count: int) -> dict:
        """Confirm a snapshot's recorded memory count matches the ledger-derived
        count (a snapshot is never authoritative over the ledger)."""
        if int(snapshot.get("memory_count", -1)) != current_memory_count:
            raise VerificationError(
                f"snapshot memory_count {snapshot.get('memory_count')} does not "
                f"match ledger-derived {current_memory_count}")
        return {"ok": True, "snapshot_id": snapshot.get("snapshot_id")}
