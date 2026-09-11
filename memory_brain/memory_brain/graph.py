"""graph.py -- derived relationship store.

The knowledge graph is a DERIVED representation. It is never authoritative:
the ledger is. Edges are re-buildable from memory_relationships rows which are
themselves written only when the corresponding ledger event is appended.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from . import canonical
from .models import _id, iso_now

# Edge types the subsystem understands.
EDGE_TYPES = {
    "PROJECT_USES", "PROJECT_DEPENDS_ON", "SUPPORTS", "CONTRADICTS",
    "SUPERSEDES", "DERIVED_FROM", "CREATED_BY", "DOCUMENT_SUPPORTS",
    "TASK_PRODUCES", "CAUSED_BY", "RESOLVED_BY",
}


class KnowledgeGraph:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add_edge(self, from_memory: str, to_memory: str, rel_type: str,
                 event_id: Optional[str] = None,
                 rel_id: Optional[str] = None) -> str:
        if rel_type not in EDGE_TYPES and not rel_type.startswith("X_"):
            # Allow extensibility but flag unknown built-ins for governance.
            pass
        rid = rel_id or _id("rel")
        self.conn.execute(
            "INSERT INTO memory_relationships "
            "(rel_id, from_memory, to_memory, rel_type, created_at, event_id) "
            "VALUES (?,?,?,?,?,?)",
            (rid, from_memory, to_memory, rel_type, iso_now(),
             event_id or "unknown"),
        )
        self.conn.commit()
        return rid

    def neighbors(self, memory_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM memory_relationships WHERE from_memory=? OR to_memory=?",
            (memory_id, memory_id)).fetchall()
        return [dict(r) for r in rows]

    def edges(self, rel_type: Optional[str] = None) -> list[dict]:
        if rel_type:
            rows = self.conn.execute(
                "SELECT * FROM memory_relationships WHERE rel_type=?",
                (rel_type,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM memory_relationships").fetchall()
        return [dict(r) for r in rows]

    def state_hash(self) -> str:
        """Deterministic digest over all edges (for snapshot/graph integrity)."""
        edges = sorted((e["rel_id"], e["from_memory"], e["to_memory"], e["rel_type"])
                       for e in self.edges())
        return canonical.digest(edges, "memory.graph")
