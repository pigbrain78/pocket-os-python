"""api.py -- typed API surface over the MemoryBrain facade.

Implements the integration contract for ecosystem agents:
    remember() recall() search() verify() explain() link()
    consolidate() supersede() retract() export()
backed by FastAPI endpoints when the web framework is present, or by plain
functions otherwise (so the contract is usable headlessly).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

from .core import MemoryBrain
from .retrieve import RetrievalEngine, RetrievalQuery
from .context import ContextPackage
from . import canonical


def _ctx(memory_id: str, brain: MemoryBrain) -> str:
    mem = brain.get(memory_id)
    return mem["content"] if mem else ""


class MemoryAPI:
    """The standard integration surface (works without a web framework)."""

    def __init__(self, brain: Optional[MemoryBrain] = None,
                 db_path: str = ":memory:"):
        self.brain = brain or MemoryBrain(db_path)
        self.retrieval = RetrievalEngine(self.brain.conn)

    # --- core ops (the shared contract) -------------------------------
    def remember(self, content: str, **kw) -> dict:
        return self.brain.remember(content, **kw)

    def recall(self, query: str, top_k: int = 10, **kw) -> list[dict]:
        rq = RetrievalQuery(query=query, top_k=top_k, **kw)
        return [asdict(m) for m in self.retrieval.search(rq)]

    def search(self, query: str, **kw) -> list[dict]:
        return self.recall(query, **kw)

    def verify(self, target: str = "chain", memory_id: Optional[str] = None) -> dict:
        if target == "chain":
            return self.brain.verify.verify_chain()
        if target == "memory":
            return self.brain.verify.verify_memory(memory_id)
        if target == "provenance":
            return self.brain.verify.verify_provenance(memory_id)
        raise ValueError(f"Unknown verify target: {target}")

    def explain(self, memory_id: str) -> dict:
        """Return the full provenance + source + history of a memory."""
        return {
            "memory": self.brain.get(memory_id),
            "provenance": self.brain.provenance(memory_id),
            "history": self.brain.history(memory_id),
        }

    def link(self, from_memory: str, to_memory: str, rel_type: str,
             event_id: Optional[str] = None) -> str:
        ev = self.brain.ledger.append(
            "MEMORY_LINKED",
            {"from": from_memory, "to": to_memory, "rel_type": rel_type})
        return self.brain.graph.add_edge(from_memory, to_memory, rel_type,
                                         event_id=ev.event_id)

    def consolidate(self, memory_ids: list[str], reason: str,
                    actor: Optional[str] = None) -> dict:
        return self.brain.consolidate(memory_ids, reason, actor)

    def supersede(self, content: str, supersedes: str, **kw) -> dict:
        return self.brain.remember(content, supersedes=supersedes, **kw)

    def retract(self, memory_id: str, reason: str, actor: str) -> dict:
        return self.brain.retract(memory_id, reason, actor)

    def export(self, fmt: str = "json") -> str:
        """Export full memory state (ledger is authoritative)."""
        mems = self.brain.active_memories()
        events = [{"event_id": e.event_id, "event_type": e.event_type,
                   "timestamp": e.timestamp, "payload": e.payload,
                   "previous_event_hash": e.previous_event_hash,
                   "event_hash": e.event_hash}
                  for e in self.brain.ledger.events()]
        blob = {"memories": mems, "events": events}
        return json.dumps(blob, indent=2) if fmt == "json" else str(blob)

    def context(self, query: str, top_k: int = 10, **kw) -> dict:
        rq = RetrievalQuery(query=query, top_k=top_k, **kw)
        results = self.retrieval.search(rq)
        pkg = ContextPackage.build(query, results)
        return pkg.to_dict()

    def contradictions(self) -> list[dict]:
        rows = self.brain.conn.execute(
            "SELECT * FROM memory_contradictions WHERE status='UNRESOLVED'"
        ).fetchall()
        return [dict(r) for r in rows]

    def review_pending(self) -> list[dict]:
        items = self.brain.review.pending()
        return [{"item_id": i.item_id, "kind": i.kind, "ref": json.loads(i.ref_json)}
                for i in items]

    def review_decide(self, item_id: str, decision: str, decided_by: str) -> dict:
        item = self.brain.review.decide(item_id, decision, decided_by)
        return {"item_id": item.item_id, "status": item.status}

    def health(self) -> dict:
        return self.brain.health.snapshot()

    def integrity(self) -> dict:
        return self.brain.verify.verify_chain()


def build_fastapi(brain: Optional[MemoryBrain] = None):
    """Construct a FastAPI app exposing the typed endpoints (if fastapi is
    importable). Kept separate so the core never depends on the web layer."""
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    api = MemoryAPI(brain=brain)

    app = FastAPI(title="Memory Second Brain", version="1.0.0")

    class RememberBody(BaseModel):
        content: str
        memory_type: Optional[str] = None
        source_id: Optional[str] = None
        actor: Optional[str] = None
        is_llm: bool = False
        sensitive: bool = False
        supersedes: Optional[str] = None

    class SearchBody(BaseModel):
        query: str
        top_k: int = 10
        memory_types: Optional[list[str]] = None
        minimum_confidence: float = 0.0

    class ReviewBody(BaseModel):
        decision: str
        decided_by: str

    @app.post("/memory/remember")
    def _remember(body: RememberBody):
        return api.remember(body.content, memory_type=body.memory_type,
                            source_id=body.source_id, actor=body.actor,
                            is_llm=body.is_llm, sensitive=body.sensitive,
                            supersedes=body.supersedes)

    @app.post("/memory/search")
    def _search(body: SearchBody):
        return api.search(body.query, top_k=body.top_k,
                          memory_types=body.memory_types,
                          minimum_confidence=body.minimum_confidence)

    @app.get("/memory/{memory_id}")
    def _get(memory_id: str):
        mem = api.brain.get(memory_id)
        if mem is None:
            raise HTTPException(404, "not found")
        return mem

    @app.get("/memory/{memory_id}/provenance")
    def _prov(memory_id: str):
        return api.explain(memory_id).get("provenance", [])

    @app.post("/memory/review/{item_id}/decide")
    def _decide(item_id: str, body: ReviewBody):
        return api.review_decide(item_id, body.decision, body.decided_by)

    @app.get("/memory/contradictions")
    def _contradictions():
        return api.contradictions()

    @app.get("/memory/health")
    def _health():
        return api.health()

    return app
