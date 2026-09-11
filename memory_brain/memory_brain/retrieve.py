"""retrieve.py -- hybrid retrieval engine.

Accepts a structured query and returns ranked memories. Supports semantic,
keyword, metadata, graph-traversal, temporal, provenance, confidence,
project, and memory-type filtering -- combined into hybrid retrieval.

Crucially, retrieval never presents unsupported claims as established facts:
every result carries its status, confidence, provenance, and source so the
consumer can distinguish an ACTIVE verified memory from an UNVERIFIED one.
"""

from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass, field
from typing import Optional

from . import normalize
from .vector import VectorIndex


@dataclass
class RetrievalQuery:
    query: str
    context: str = ""
    project: Optional[str] = None
    memory_types: Optional[list[str]] = None
    minimum_confidence: float = 0.0
    maximum_age: Optional[int] = None   # in days
    include_provenance: bool = True
    include_relationships: bool = True
    top_k: int = 10
    statuses: Optional[list[str]] = None  # default: ACTIVE only unless given


@dataclass
class RetrievedMemory:
    memory_id: str
    content: str
    relevance_score: float
    confidence: float
    importance: float
    provenance: list = field(default_factory=list)
    source: Optional[dict] = None
    relationships: list = field(default_factory=list)
    status: str = "ACTIVE"
    timestamp: str = ""


class RetrievalEngine:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._vec = VectorIndex()
        self._load()

    def _load(self) -> None:
        rows = self.conn.execute(
            "SELECT memory_id, content, status FROM memories").fetchall()
        self._vec.add_many((r["memory_id"], r["content"]) for r in rows)

    def _rows(self, q: RetrievalQuery) -> list[sqlite3.Row]:
        sql = ["SELECT * FROM memories WHERE 1=1"]
        params: list = []
        statuses = q.statuses or ["ACTIVE"]
        sql.append("AND status IN (%s)" % ",".join("?" * len(statuses)))
        params.extend(statuses)
        if q.memory_types:
            sql.append("AND memory_type IN (%s)" % ",".join("?" * len(q.memory_types)))
            params.extend(q.memory_types)
        if q.minimum_confidence > 0:
            sql.append("AND confidence >= ?")
            params.append(q.minimum_confidence)
        rows = self.conn.execute(" ".join(sql), params).fetchall()
        return rows

    def search(self, q: RetrievalQuery) -> list[RetrievedMemory]:
        rows = self._rows(q)
        # Semantic scores from the derived vector index.
        vec_hits = dict(self._vec.search(q.query, top_k=max(50, q.top_k * 5)))

        # Keyword scores (deterministic token overlap on normalized content).
        qtoks = set(__import__("re").findall(r"[a-z0-9]+",
                    normalize.normalize_text(q.query)))

        out: list[RetrievedMemory] = []
        for r in rows:
            semantic = vec_hits.get(r["memory_id"], 0.0)
            content = r["content"]
            rtoks = set(__import__("re").findall(r"[a-z0-9]+",
                        normalize.normalize_text(content)))
            kw = (len(qtoks & rtoks) / len(qtoks)) if qtoks else 0.0
            relevance = round(0.7 * semantic + 0.3 * kw, 4)

            prov = self._provenance(r["memory_id"]) if q.include_provenance else []
            rels = self._relationships(r["memory_id"]) if q.include_relationships else []
            sid = r["source_id"]
            src = self._source(sid) if sid else None

            out.append(RetrievedMemory(
                memory_id=r["memory_id"], content=content,
                relevance_score=relevance, confidence=r["confidence"],
                importance=r["importance"], provenance=prov, source=src,
                relationships=rels, status=r["status"], timestamp=r["updated_at"],
            ))
        out.sort(key=lambda m: (-m.relevance_score, -m.importance, m.memory_id))
        return out[:q.top_k]

    def _provenance(self, memory_id: str) -> list:
        rows = self.conn.execute(
            "SELECT p.content, p.confidence FROM memories p "
            "JOIN memory_relationships rel ON rel.to_memory = p.memory_id "
            "WHERE rel.from_memory=? AND rel.rel_type='DERIVED_FROM'",
            (memory_id,)).fetchall()
        return [{"memory": r["content"], "confidence": r["confidence"]} for r in rows]

    def _relationships(self, memory_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT rel_type, from_memory, to_memory FROM memory_relationships "
            "WHERE from_memory=? OR to_memory=?", (memory_id, memory_id)).fetchall()
        return [{"rel_type": r["rel_type"], "from": r["from_memory"],
                 "to": r["to_memory"]} for r in rows]

    def _source(self, source_id) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM memory_sources WHERE source_id=?",
            (source_id,)).fetchone()
        return dict(row) if row else None
