"""health.py -- per-subsystem health checks + the section-34 metrics.

Exposes health() for every subsystem and counters for observability
(ingestion rate, retrieval rate, duplicate rate, contradiction rate,
consolidation rate, verification rate, stale count, review queue size, ...).
"""

from __future__ import annotations

import sqlite3

from .models import iso_now


class Health:
    def __init__(self, conn: sqlite3.Connection, ledger):
        self.conn = conn
        self.ledger = ledger
        # In-memory counters (ephemeral coordination; not authoritative).
        self.counters = {
            "memory_ingestion_rate": 0,
            "memory_retrieval_rate": 0,
            "duplicate_rate": 0,
            "contradiction_rate": 0,
            "consolidation_rate": 0,
            "verification_rate": 0,
            "failed_ingestions": 0,
            "stale_memory_count": 0,
        }

    def _table_count(self, table: str) -> int:
        try:
            cur = self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}")
            return int(cur.fetchone()["n"])
        except sqlite3.Error:
            return -1

    def ledger_integrity(self) -> dict:
        try:
            self.ledger.verify_chain()
            return {"ok": True}
        except Exception:
            return {"ok": False, "error": "ledger chain broken"}

    def snapshot(self) -> dict:
        """Compute the observability snapshot."""
        self.counters["stale_memory_count"] = len(self.stale_memories())
        return {
            "health": "ok" if self.ledger_integrity()["ok"] else "degraded",
            "ledger": {
                "events": self.ledger.count(),
                "head_event_id": self.ledger.head_event_id,
                "integrity": self.ledger_integrity(),
            },
            "totals": {
                "memories": self._table_count("memories"),
                "sources": self._table_count("memory_sources"),
                "relationships": self._table_count("memory_relationships"),
                "contradictions": self._table_count("memory_contradictions"),
                "consolidations": self._table_count("memory_consolidations"),
                "review_queue_pending": self._pending_review_count(),
            },
            "metrics": dict(self.counters),
            "generated_at": iso_now(),
        }

    def _pending_review_count(self) -> int:
        cur = self.conn.execute(
            "SELECT COUNT(*) AS n FROM review_queue WHERE status='PENDING'")
        return int(cur.fetchone()["n"])

    def stale_memories(self) -> list[dict]:
        from .classify import staleness
        rows = self.conn.execute(
            "SELECT memory_id, updated_at, status FROM memories "
            "WHERE status='ACTIVE'").fetchall()
        out = []
        for r in rows:
            st = staleness(r["updated_at"])
            if st in ("STALE", "OBSOLETE"):
                out.append({"memory_id": r["memory_id"], "staleness": st})
        return out
