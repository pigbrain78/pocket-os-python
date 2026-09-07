"""ledger.py -- append-only hash-chained event store.

The authoritative history of the Memory Second Brain. Every memory operation
-- creation, correction, supersession, merge, retraction, contradiction,
consolidation, verification -- appends one event. Events are immutable and
hash-chained: each event's event_hash is a domain-tagged SHA-256 digest over
its canonicalized content plus previous_event_hash, so any tamper breaks the
chain. Nothing in this module ever edits or deletes a written event.

replay() reconstructs the current state by applying events in order, so the
entire memory state is derivable from the ledger alone.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Optional

from . import canonical, schema
from .models import LedgerEvent, _id, iso_now

# Event types understood by the replay state machine.
COMMIT_EVENT_TYPES = {
    "MEMORY_CREATED",
    "MEMORY_CORRECTED",
    "MEMORY_SUPERSEDED",
    "MEMORY_RETRACTED",
    "MEMORY_ARCHIVED",
    "MEMORY_CONTRADICTION_DETECTED",
    "MEMORY_CONTRADICTION_RESOLVED",
    "MEMORY_CONSOLIDATED",
    "MEMORY_MERGED",
    "MEMORY_VERIFIED",
    "MEMORY_REVIEW_DECISION",
    "MEMORY_QUARANTINED",
    "MEMORY_COUNCIL_RATIFIED",
}


class LedgerIntegrityError(Exception):
    """Raised when a ledger verification fails (tamper / broken chain)."""


class Ledger:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        schema.load_schema(conn)

    # -- chain head -------------------------------------------------------
    def _head(self) -> Optional[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT event_id, event_hash FROM ledger_events "
            "ORDER BY rowid DESC LIMIT 1"
        )
        return cur.fetchone()

    @property
    def head_event_id(self) -> Optional[str]:
        row = self._head()
        return row["event_id"] if row else None

    @property
    def head_hash(self) -> Optional[str]:
        row = self._head()
        return row["event_hash"] if row else None

    def count(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) AS n FROM ledger_events")
        return int(cur.fetchone()["n"])

    # -- append -----------------------------------------------------------
    def _compute_hash(self, event_id: str, timestamp: str, event_type: str,
                      payload: dict, previous: Optional[str],
                      algorithm_version: str) -> str:
        """Canonical digest over full event content + previous hash."""
        body = {
            "event_id": event_id,
            "timestamp": timestamp,
            "event_type": event_type,
            "payload": payload,
            "previous_event_hash": previous,
            "algorithm_version": algorithm_version,
        }
        return canonical.digest(body, canonical.LEDGER_EVENT)

    def append(self, event_type: str, payload: dict,
               timestamp: Optional[str] = None,
               event_id: Optional[str] = None,
               algorithm_version: str = "1") -> LedgerEvent:
        """Append one immutable event and return it.

        payload must be canonically serializable (dict/list/str/int/float/
        bool/None). The event_hash chains onto the current head.
        """
        # Canonicalizability guard: fail before writing anything.
        canonical.canonical_json(payload)

        ts = timestamp or iso_now()
        eid = event_id or _id("evt")
        prev = self.head_hash

        # Serialize writes so concurrent appends cannot interleave and break
        # the chain (single-process SQLite with a busy timeout).
        with self.conn:
            # Re-read head inside the transaction to be race-safe.
            cur = self.conn.execute(
                "SELECT event_hash FROM ledger_events ORDER BY rowid DESC LIMIT 1"
            )
            row = cur.fetchone()
            prev = row["event_hash"] if row else None

            event_hash = self._compute_hash(eid, ts, event_type, payload, prev,
                                            algorithm_version)
            self.conn.execute(
                "INSERT INTO ledger_events "
                "(event_id, timestamp, event_type, payload, previous_event_hash,"
                " event_hash, algorithm_version) VALUES (?,?,?,?,?,?,?)",
                (eid, ts, event_type, canonical.canonical_json(payload),
                 prev, event_hash, algorithm_version),
            )
        return LedgerEvent(eid, ts, event_type, payload, prev, event_hash,
                           algorithm_version)

    # -- read -------------------------------------------------------------
    def get(self, event_id: str) -> Optional[LedgerEvent]:
        cur = self.conn.execute(
            "SELECT * FROM ledger_events WHERE event_id = ?", (event_id,))
        row = cur.fetchone()
        if row is None:
            return None
        import json as _json
        payload = _json.loads(row["payload"])
        return LedgerEvent(row["event_id"], row["timestamp"], row["event_type"],
                           payload, row["previous_event_hash"], row["event_hash"],
                           row["algorithm_version"])

    def events(self) -> list[LedgerEvent]:
        cur = self.conn.execute(
            "SELECT * FROM ledger_events ORDER BY rowid ASC")
        return [self._row_to_event(r) for r in cur.fetchall()]

    def _row_to_event(self, row: sqlite3.Row) -> LedgerEvent:
        import json as _json
        return LedgerEvent(row["event_id"], row["timestamp"], row["event_type"],
                           _json.loads(row["payload"]), row["previous_event_hash"],
                           row["event_hash"], row["algorithm_version"])

    # -- verification -----------------------------------------------------
    def verify_chain(self) -> None:
        """Verify the full hash chain from genesis. Raise on any tamper."""
        rows = self.conn.execute(
            "SELECT * FROM ledger_events ORDER BY rowid ASC").fetchall()
        prev: Optional[str] = None
        for row in rows:
            ev = self._row_to_event(row)
            expect = self._compute_hash(
                ev.event_id, ev.timestamp, ev.event_type, ev.payload,
                ev.previous_event_hash, ev.algorithm_version)
            if expect != ev.event_hash:
                raise LedgerIntegrityError(
                    f"event_hash mismatch at {ev.event_id}")
            if ev.previous_event_hash != prev:
                raise LedgerIntegrityError(
                    f"chain break at {ev.event_id}: expected prev "
                    f"{prev!r}, got {ev.previous_event_hash!r}")
            prev = ev.event_hash

    def replay(self, start_event: Optional[str] = None,
               end_event: Optional[str] = None,
               applier: Optional[Callable[[dict, dict], dict]] = None,
               initial_state: Optional[dict] = None) -> dict:
        """Replay the ledger into a derived state.

        state is a dict. If ``applier`` is given it is called as
        applier(state, event) to fold each event into state; otherwise a
        default reducer that records event types into a ``counts`` map and the
        last payload per event id is used. Replaying the same ledger with the
        same applier and algorithm versions yields the same state
        (determinism).
        """
        state = dict(initial_state) if initial_state else {}
        events = self.events()
        started = start_event is None
        for ev in events:
            if not started:
                if ev.event_id == start_event:
                    started = True
                else:
                    continue
            if applier is not None:
                applier(state, ev)
            else:
                state.setdefault("counts", {})
                state["counts"][ev.event_type] = state["counts"].get(ev.event_type, 0) + 1
                state.setdefault("last_payloads", {})
                state["last_payloads"][ev.event_id] = ev.payload
                state["last_event_id"] = ev.event_id
            if end_event is not None and ev.event_id == end_event:
                break
        return state
