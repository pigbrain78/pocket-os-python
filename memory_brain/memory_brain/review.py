"""review.py -- human review queue.

Items requiring a human decision live here: low-confidence memories, potential
contradictions, ambiguous merges, sensitive memories, high-impact decisions,
memory deletion requests, provenance conflicts, authority conflicts. Human
decisions become ledger events -- the queue is a governance gate, not a
suggestion box.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

from . import canonical
from .models import ReviewItem, _id, iso_now

# Decision verbs available to a reviewer.
DECISIONS = {"APPROVE", "REJECT", "MERGE", "SPLIT", "SUPERSEDE",
             "QUARANTINE", "REQUEST_MORE_EVIDENCE"}


class ReviewQueue:
    def __init__(self, conn: sqlite3.Connection, ledger):
        self.conn = conn
        self.ledger = ledger

    def enqueue(self, kind: str, ref: dict, item_id: Optional[str] = None) -> ReviewItem:
        item = ReviewItem(
            item_id=item_id or _id("rev"),
            kind=kind,
            ref_json=canonical.canonical_json(ref),
        )
        self.conn.execute(
            "INSERT INTO review_queue (item_id, kind, ref_json, status, "
            "created_at) VALUES (?,?,?,?,?)",
            (item.item_id, item.kind, item.ref_json, item.status, item.created_at))
        self.conn.commit()
        return item

    def pending(self) -> list[ReviewItem]:
        rows = self.conn.execute(
            "SELECT * FROM review_queue WHERE status='PENDING' ORDER BY created_at"
        ).fetchall()
        return [self._row(r) for r in rows]

    def _row(self, row: sqlite3.Row) -> ReviewItem:
        return ReviewItem(
            item_id=row["item_id"], kind=row["kind"], ref_json=row["ref_json"],
            status=row["status"], created_at=row["created_at"],
            decided_at=row["decided_at"], decided_by=row["decided_by"],
            decision_event_id=row["decision_event_id"])

    def decide(self, item_id: str, decision: str, decided_by: str,
               detail: Optional[dict] = None) -> ReviewItem:
        """Apply a human decision; it becomes a ledger event."""
        if decision not in DECISIONS:
            raise ValueError(f"Unknown decision: {decision}")
        row = self.conn.execute(
            "SELECT * FROM review_queue WHERE item_id=?",
            (item_id,)).fetchone()
        if row is None:
            raise KeyError(f"No review item {item_id}")
        if row["status"] != "PENDING":
            raise ValueError(f"Review item {item_id} already decided")

        # Human decision -> ledger event (authoritative).
        ev = self.ledger.append(
            "MEMORY_REVIEW_DECISION",
            {"item_id": item_id, "decision": decision, "decided_by": decided_by,
             "kind": row["kind"], "detail": detail or {}},
        )
        self.conn.execute(
            "UPDATE review_queue SET status=?, decided_at=?, decided_by=?, "
            "decision_event_id=? WHERE item_id=?",
            (decision, iso_now(), decided_by, ev.event_id, item_id))
        self.conn.commit()
        return self._row(self.conn.execute(
            "SELECT * FROM review_queue WHERE item_id=?", (item_id,)).fetchone())
