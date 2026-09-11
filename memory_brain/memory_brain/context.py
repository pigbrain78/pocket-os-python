"""context.py -- Context Builder.

Instead of handing agents raw search results, generate a structured, grounded
context package: authoritative facts vs uncertainties vs contradictions vs
recent changes, each with provenance and source references. This is the
standard memory interface for ecosystem agents (SAIL, Ralph5 Ultra, Igor,
PocketOS, ACE, KIP, ...).
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from typing import Optional

from . import canonical
from .models import iso_now


@dataclass
class ContextPackage:
    context_id: str
    query: str
    facts: list = field(default_factory=list)
    uncertainties: list = field(default_factory=list)
    contradictions: list = field(default_factory=list)
    recent_changes: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    generated_at: str = field(default_factory=iso_now)
    context_hash: str = ""

    def finalize(self) -> "ContextPackage":
        self.context_hash = canonical.digest(
            self._hash_body(), canonical.CONTEXT_PACKAGE)
        return self

    def _hash_body(self) -> dict:
        return {
            "context_id": self.context_id,
            "query": self.query,
            "facts": self.facts,
            "uncertainties": self.uncertainties,
            "contradictions": self.contradictions,
            "recent_changes": self.recent_changes,
            "sources": self.sources,
            "generated_at": self.generated_at,
        }

    def to_dict(self) -> dict:
        self.finalize()
        return self._hash_body() | {"context_hash": self.context_hash}

    @classmethod
    def build(cls, query: str, memories: list, project: Optional[str] = None) -> "ContextPackage":
        """Assemble a context package from retrieved memories.

        memories: list of objects exposing memory_id, content, confidence,
        status, provenance, source, relationships, timestamp.
        """
        facts, uncertainties, sources = [], [], []
        contradictions, recent = [], []
        ctx_id = "ctx_" + canonical.digest(
            {"q": query, "t": iso_now()}, "memory.contextid")[:16]

        for m in memories:
            # Only ACTIVE, verified memories are "authoritative facts".
            is_verified = any(getattr(p, "kind", None) == "VERIFICATION"
                              for p in m.provenance) or _prov_verified(m)
            conf = m.confidence
            if m.status == "ACTIVE" and conf >= 0.7 and is_verified:
                facts.append({
                    "memory_id": m.memory_id, "content": m.content,
                    "confidence": conf, "importance": m.importance,
                    "status": m.status,
                })
            elif m.status == "ACTIVE" and conf < 0.7:
                uncertainties.append({
                    "memory_id": m.memory_id, "content": m.content,
                    "confidence": conf, "reason": "low confidence",
                })
            else:
                uncertainties.append({
                    "memory_id": m.memory_id, "content": m.content,
                    "status": m.status, "reason": "non-active status",
                })
            if m.source:
                sources.append(m.source)
            # Contradictions are flagged by the engine and surfaced here.
            for rel in m.relationships:
                if rel.get("rel_type") == "CONTRADICTS":
                    contradictions.append({
                        "memory_id": m.memory_id,
                        "contradicts": rel.get("to") or rel.get("from"),
                    })

        pkg = cls(context_id=ctx_id, query=query, facts=facts,
                  uncertainties=uncertainties, contradictions=contradictions,
                  sources=sources)
        return pkg.finalize()


def _prov_verified(m) -> bool:
    # If provenance came back as plain dicts (retrieval layer), check kinds.
    try:
        return any(getattr(p, "kind", p.get("kind")) == "VERIFICATION"
                   for p in m.provenance)
    except Exception:
        return False
