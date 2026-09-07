"""AI Shadow engine.

The AI Shadow is the continuous advisory intelligence alongside the user. It
observes permitted Pocket OS context and emits observations, warnings,
insights, and proposed actions. It can NEVER execute, approve, ratify, or
become a second source of truth.

Every shadow item is advisory and carries an explicit authority of NONE. To act
on a recommendation, the user turns it into a proposal which enters the normal
governance path. The shadow's authority is always NONE; it never silently
becomes an execution agent or a governance authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

OBSERVATION = "OBSERVATION"
INSIGHT = "INSIGHT"
WARNING = "WARNING"
OPPORTUNITY = "OPPORTUNITY"
QUESTION = "QUESTION"
RECOMMENDATION = "RECOMMENDATION"
PROPOSAL = "PROPOSAL"

SHADOW_TYPES = (OBSERVATION, INSIGHT, WARNING, OPPORTUNITY, QUESTION, RECOMMENDATION, PROPOSAL)


@dataclass(frozen=True)
class ShadowItem:
    """One advisory item from the AI Shadow. Authority is always NONE."""

    type: str
    text: str
    confidence: float  # 0..1
    evidence: tuple[int, ...]  # ledger sequences
    provenance: str
    status: str = "advisory"
    authority: str = "NONE"
    next_step: str = ""

    def view(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "text": self.text,
            "confidence": round(self.confidence, 2),
            "evidence": list(self.evidence),
            "provenance": self.provenance,
            "status": self.status,
            "authority": self.authority,
            "next_step": self.next_step,
        }


def _evidence(records: list[dict[str, Any]], *preds: Callable[[dict[str, Any]], bool]) -> tuple[int, ...]:
    """Return ledger sequences of records matching predicates, capped at 3."""
    out: list[int] = []
    for i, r in enumerate(records):
        seq = int(r.get("sequence") or (i + 1))
        if all(p(r) for p in preds):
            out.append(seq)
        if len(out) >= 3:
            break
    return tuple(out)


def _provenance_of(records: list[dict[str, Any]], seqs: tuple[int, ...]) -> str:
    if not seqs:
        return "ledger#-"
    for i, r in enumerate(records):
        if int(r.get("sequence") or (i + 1)) == seqs[0]:
            return f"ledger#{seqs[0]} ({r.get('event')})"
    return f"ledger#{seqs[0]}"


def shadow_state(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold ledger into the AI Shadow advisory state. Authority always NONE."""
    open_tasks = _evidence(records, lambda r: r.get("event") == "task.created")
    tensions = _evidence(records, lambda r: bool((r.get("payload") or {}).get("tension")))
    items = [
        ShadowItem(
            type=OBSERVATION,
            text="Shadow observes active project work with open task loops.",
            confidence=0.91,
            evidence=open_tasks,
            provenance=_provenance_of(records, open_tasks),
            next_step="Review open task loops.",
        ).view(),
    ]
    if tensions:
        items.append(ShadowItem(
            type=WARNING,
            text="Shadow detects conflicting state claims in memory.",
            confidence=0.93,
            evidence=tensions,
            provenance=_provenance_of(records, tensions),
            next_step="Reconcile conflicting memory claims.",
        ).view())
    else:
        items.append(ShadowItem(
            type=INSIGHT,
            text="Shadow finds no conflicting claims; state appears coherent.",
            confidence=0.88,
            evidence=(),
            provenance="ledger#-",
            next_step="None.",
        ).view())
    items.append(ShadowItem(
        type=PROPOSAL,
        text="Shadow proposes reviewing current project dependencies.",
        confidence=0.79,
        evidence=_evidence(records, lambda r: r.get("event", "").startswith("knowledge.")),
        provenance="ledger#-",
        next_step="Send to council for review.",
    ).view())
    return {
        "types": list(SHADOW_TYPES),
        "items": items,
        "authority_boundary": {
            "shadow_can_execute": False,
            "shadow_can_ratify": False,
            "shadow_authority": "NONE",
            "execution_requires": ["COUNCIL_CONSENSUS", "HUMAN_RATIFICATION"],
        },
    }
