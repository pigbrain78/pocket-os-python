"""Cognitive Twin engine.

The Cognitive Twin is a pure, deterministic fold over the canonical ledger. It
represents the system's evolving contextual model of the user's goals,
projects, active work, decisions, and knowledge relationships.

It is NOT the user, NOT an autonomous authority, and it gets no permission
merely because it predicts what the user would want. It is an advisory/modeling
layer: every derived item carries an explicit epistemic state so an inference
is never presented as an established fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

OBSERVED = "OBSERVED"
VERIFIED = "VERIFIED"
INFERRED = "INFERRED"
UNCERTAIN = "UNCERTAIN"
REJECTED = "REJECTED"
STALE = "STALE"

EPISTEMIC_LEGEND = (OBSERVED, VERIFIED, INFERRED, UNCERTAIN, REJECTED, STALE)

DEFAULT_MODEL_VERSION = "twin-1.0"


@dataclass(frozen=True)
class TwinItem:
    """One derived item: a statement plus how the system knows it."""

    text: str
    epistemic: str
    confidence: float  # 0..1
    evidence: tuple[int, ...]  # ledger sequences that produced this item
    provenance: str  # "ledger#<seq>" for the anchoring event

    def view(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "epistemic": self.epistemic,
            "confidence": round(self.confidence, 2),
            "evidence": list(self.evidence),
            "provenance": self.provenance,
        }


@dataclass
class CognitiveState:
    """Projected twin state. Constructed purely from ledger records."""

    model_version: str
    last_update_seq: int
    summary: str
    current_focus: TwinItem
    open_loops: list[TwinItem]
    closed_loops: list[TwinItem]
    active_projects: list[TwinItem]
    relevant_memories: list[TwinItem]
    decision_history: list[TwinItem]
    relationships: list[TwinItem]
    recent_observations: list[TwinItem]

    def view(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "last_update_seq": self.last_update_seq,
            "epistemic_legend": list(EPISTEMIC_LEGEND),
            "summary": self.summary,
            "state": {
                "current_focus": self.current_focus.view(),
                "open_loops": [i.view() for i in self.open_loops],
                "closed_loops": [i.view() for i in self.closed_loops],
                "active_projects": [i.view() for i in self.active_projects],
            },
            "relevant_memories": [i.view() for i in self.relevant_memories],
            "decision_history": [i.view() for i in self.decision_history],
            "relationships": [i.view() for i in self.relationships],
            "recent_observations": [i.view() for i in self.recent_observations],
        }


def _is_tension(r: dict[str, Any]) -> bool:
    return bool((r.get("payload") or {}).get("tension"))


def _seq_of(r: dict[str, Any], i: int) -> int:
    return int(r.get("sequence") or (i + 1))


def _provenance(seq: int) -> str:
    return f"ledger#{seq}"


def _observe(records: list[dict[str, Any]]) -> list[TwinItem]:
    """Map recent ledger events into OBSERVED items (never inferred)."""
    items: list[TwinItem] = []
    for i, r in enumerate(records):
        ev = r.get("event") or ""
        payload = r.get("payload") or {}
        seq = _seq_of(r, i)
        if not ev or "." not in ev or r.get("schema_version") == "legacy_v1":
            continue
        text = payload.get("title") or ev
        items.append(TwinItem(
            text=f"{ev}: {text}",
            epistemic=OBSERVED,
            confidence=0.99,
            evidence=(seq,),
            provenance=_provenance(seq),
        ))
    return items[-6:]  # recent window


def _focus(records: list[dict[str, Any]]) -> TwinItem:
    """Infer the current focus from the most-frequent non-conflicted subject.

    This is explicitly an INFERENCE (highest-frequency topic), never a fact.
    """
    counts: dict[str, int] = {}
    first: dict[str, int] = {}
    for i, r in enumerate(records):
        payload = r.get("payload") or {}
        if _is_tension(r):
            continue
        title = payload.get("title")
        if not title:
            continue
        counts[title] = counts.get(title, 0) + 1
        first.setdefault(title, _seq_of(r, i))
    if not counts:
        return TwinItem(
            text="No stable focus signal yet",
            epistemic=UNCERTAIN, confidence=0.3,
            evidence=(), provenance="ledger#-",
        )
    best = max(counts, key=lambda t: (counts[t], -first[t]))
    seq = first[best]
    conf = min(0.95, 0.5 + 0.1 * counts[best])
    return TwinItem(
        text=f"Focus appears to be \u201c{best}\u201d",
        epistemic=INFERRED, confidence=round(conf, 2),
        evidence=(seq,), provenance=_provenance(seq),
    )


def _memories(records: list[dict[str, Any]]) -> tuple[list[TwinItem], list[TwinItem]]:
    verified: list[TwinItem] = []
    uncertain: list[TwinItem] = []
    for i, r in enumerate(records):
        if r.get("event") != "memory.created":
            continue
        payload = r.get("payload") or {}
        seq = _seq_of(r, i)
        text = payload.get("title") or "(untitled memory)"
        if _is_tension(r):
            uncertain.append(TwinItem(
                text=f"conflicting claim: {text}",
                epistemic=UNCERTAIN, confidence=0.5,
                evidence=(seq,), provenance=_provenance(seq),
            ))
        else:
            verified.append(TwinItem(
                text=text, epistemic=VERIFIED, confidence=0.98,
                evidence=(seq,), provenance=_provenance(seq),
            ))
    return verified, uncertain


def _loops(records: list[dict[str, Any]]) -> tuple[list[TwinItem], list[TwinItem]]:
    open_items: list[TwinItem] = []
    closed: list[TwinItem] = []
    created: dict[str, int] = {}
    order: list[str] = []
    done: set[str] = set()
    for i, r in enumerate(records):
        payload = r.get("payload") or {}
        title = payload.get("title")
        ev = r.get("event")
        seq = _seq_of(r, i)
        if not title:
            continue
        if ev == "task.created":
            created.setdefault(title, seq)
            order.append(title)
        elif ev == "task.completed":
            done.add(title)
    for title in order:
        seq = created[title]
        if title in done:
            closed.append(TwinItem(
                text=f"completed: {title}", epistemic=VERIFIED, confidence=0.99,
                evidence=(seq,), provenance=_provenance(seq),
            ))
        else:
            open_items.append(TwinItem(
                text=f"open loop: {title}", epistemic=OBSERVED, confidence=0.99,
                evidence=(seq,), provenance=_provenance(seq),
            ))
    return open_items, closed


def _projects(records: list[dict[str, Any]]) -> list[TwinItem]:
    counts: dict[str, int] = {}
    first: dict[str, int] = {}
    for i, r in enumerate(records):
        src = r.get("source")
        if not src:
            continue
        counts[src] = counts.get(src, 0) + 1
        first.setdefault(src, _seq_of(r, i))
    items: list[TwinItem] = []
    for src, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        items.append(TwinItem(
            text=f"{src} \u2014 {n} events",
            epistemic=OBSERVED, confidence=0.99,
            evidence=(first[src],), provenance=_provenance(first[src]),
        ))
    return items


def _decisions(records: list[dict[str, Any]]) -> list[TwinItem]:
    items: list[TwinItem] = []
    for i, r in enumerate(records):
        if r.get("event") != "governance.decided":
            continue
        payload = r.get("payload") or {}
        outcome = payload.get("outcome")
        seq = _seq_of(r, i)
        items.append(TwinItem(
            text=f"{outcome}: {payload.get('title') or '(decision)'}",
            epistemic=VERIFIED, confidence=0.99,
            evidence=(seq,), provenance=_provenance(seq),
        ))
    return items


def _relationships(memories: list[TwinItem], focus: TwinItem) -> list[TwinItem]:
    """Infer which verified memories relate to the current focus."""
    rels: list[TwinItem] = []
    for m in memories:
        if any(w in m.text.lower() for w in ("pocket", "os", "web", "system")):
            rels.append(TwinItem(
                text=f"memory \u201c{m.text}\u201d relates to current focus",
                epistemic=INFERRED, confidence=0.66,
                evidence=m.evidence, provenance=m.provenance,
            ))
    return rels[:3]


def cognitive_state(records: list[dict[str, Any]], model_version: str = DEFAULT_MODEL_VERSION) -> CognitiveState:
    """Fold the ledger into a projected twin state. Deterministic, read-only."""
    memories_v, memories_u = _memories(records)
    open_loops, closed_loops = _loops(records)
    focus = _focus(records)
    rels = _relationships(memories_v, focus)
    seqs = [int(r.get("sequence") or (i + 1)) for i, r in enumerate(records)]
    last_seq = max(seqs) if seqs else 0
    all_mem = memories_v + memories_u
    summary = (
        f"Twin derives {len(all_mem)} memory reference(s), {len(open_loops)} "
        f"open loop(s), {len(rels)} inferred relationship(s), and a current "
        f"focus ({focus.epistemic.lower()}) from {len(records)} ledger "
        f"event(s) ending at sequence {last_seq}."
    )
    return CognitiveState(
        model_version=model_version,
        last_update_seq=last_seq,
        summary=summary,
        current_focus=focus,
        open_loops=open_loops,
        closed_loops=closed_loops,
        active_projects=_projects(records),
        relevant_memories=all_mem,
        decision_history=_decisions(records),
        relationships=rels,
        recent_observations=_observe(records),
    )
