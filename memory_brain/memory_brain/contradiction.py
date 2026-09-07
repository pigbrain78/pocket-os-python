"""contradiction.py -- explicit contradiction analysis.

When two memories conflict, they are never left as two unrelated records and
never silently resolved. The engine:
  1. records the relationship (A CONTRADICTS B) and a ledger event,
  2. evaluates recency, provenance strength, confidence, and source authority,
  3. decides either ACTIVE+SUPERSEDED (with strong evidence) or UNRESOLVED.

Unresolved contradictions remain visible and route to the human review queue.
Every resolution is a human-approved ledger event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

CONTRADICTION_ALGORITHM_VERSION = "contra-1.0"


@dataclass
class ContradictionAssessment:
    conflict: bool
    reason: str
    recommendation: Optional[str]  # None (leave unresolved) or one side memory_id


def _confidence_value(c: dict) -> float:
    return float(c.get("current_confidence", c.get("source_confidence", 0.0)))


def assess(claim_a: str, claim_b: str,
           meta_a: Optional[dict] = None, meta_b: Optional[dict] = None,
           algorithm_version: str = CONTRADICTION_ALGORITHM_VERSION) -> ContradictionAssessment:
    """Heuristic contradiction assessment between two claims.

    A full production engine may consult an LLM advisory layer, but the final
    decision is deterministic from the supplied metadata and never bypasses
    governance. This local rule engine is the deterministic fallback.
    """
    if algorithm_version != CONTRADICTION_ALGORITHM_VERSION:
        raise ValueError(f"Unknown contradiction algorithm version: {algorithm_version}")

    meta_a = meta_a or {}
    meta_b = meta_b or {}
    conf_a = _confidence_value(meta_a)
    conf_b = _confidence_value(meta_b)

    # Deterministic polarity heuristic (mirrors dedup's antonym table but
    # returns the conflict verdict rather than a dedup classification).
    from .dedup import _possible_contradiction
    conflict = _possible_contradiction(claim_a, claim_b)

    if not conflict:
        return ContradictionAssessment(False, "no conflicting polarity detected", None)

    reason_parts = [f"conflicting claims detected (conf A={conf_a}, B={conf_b})"]

    # Recency: newer claim tends to supersede an older one.
    ts_a = meta_a.get("created_at")
    ts_b = meta_b.get("created_at")
    if ts_a and ts_b:
        if ts_a >= ts_b:
            reason_parts.append("A is newer or equal")
        else:
            reason_parts.append("B is newer")

    # Source authority: verified provenance outranks unverified.
    verified_a = bool(meta_a.get("verified"))
    verified_b = bool(meta_b.get("verified"))

    # Strong evidence = one side strictly more authoritative on BOTH axes and
    # clearly higher confidence. Otherwise leave unresolved for human review.
    def _stronger(i) -> bool:
        return conf_a - conf_b >= 0.2 if i == "A" else conf_b - conf_a >= 0.2

    if verified_a and not verified_b and _stronger("A"):
        reason_parts.append("A verified + higher confidence -> recommend A")
        return ContradictionAssessment(True, "; ".join(reason_parts), "A")
    if verified_b and not verified_a and _stronger("B"):
        reason_parts.append("B verified + higher confidence -> recommend B")
        return ContradictionAssessment(True, "; ".join(reason_parts), "B")
    if verified_a and verified_b and _stronger("A"):
        reason_parts.append("both verified, A higher confidence -> recommend A")
        return ContradictionAssessment(True, "; ".join(reason_parts), "A")
    if verified_a and verified_b and _stronger("B"):
        reason_parts.append("both verified, B higher confidence -> recommend B")
        return ContradictionAssessment(True, "; ".join(reason_parts), "B")

    reason_parts.append("no decisive authority -> UNRESOLVED, requires human review")
    return ContradictionAssessment(True, "; ".join(reason_parts), None)
