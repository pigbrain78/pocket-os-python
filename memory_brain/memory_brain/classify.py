"""classify.py -- memory typing, confidence, and importance.

Confidence is four SEPARATE components (source/extraction/inference/current)
that are never collapsed into one meaningless number -- see models.Confidence.

Importance is an INDEPENDENT score that never overrides provenance: a highly
important memory can still be wrong. It factors recency, frequency, project
relevance, dependency count, user designation, and downstream usage, but these
only rank a memory's salience, never its truth status.
"""

from __future__ import annotations

import datetime
from typing import Optional

from .models import Confidence, MEMORY_TYPES

CLASSIFICATION_ALGORITHM_VERSION = "class-1.0"

# Deterministic keyword -> type hints for a lightweight local classifier.
# In production this can be an LLM advisory pass, but the *final* type is
# assigned by deterministic rules below -- the LLM is never authoritative.
_KEYWORD_TYPE_HINTS: list[tuple[str, str]] = [
    ("i prefer", "PREFERENCE"), ("prefer", "PREFERENCE"), ("i like", "PREFERENCE"),
    ("we decided", "DECISION"), ("decision", "DECISION"),
    ("must", "REQUIREMENT"), ("required", "REQUIREMENT"), ("requires", "REQUIREMENT"),
    ("goal", "GOAL"), ("objective", "GOAL"),
    ("plan", "PLAN"),
    ("task", "TASK"), ("todo", "TASK"),
    ("project", "PROJECT"),
    ("lesson", "LESSON"), ("learned", "LESSON"),
    ("failure", "FAILURE"), ("failed", "FAILURE"), ("broke", "FAILURE"),
    ("success", "SUCCESS"), ("succeeded", "SUCCESS"),
    ("rule", "RULE"), ("policy", "POLICY"), ("constraint", "CONSTRAINT"),
    ("hypothesis", "HYPOTHESIS"), ("we think", "HYPOTHESIS"), ("maybe", "HYPOTHESIS"),
    ("insight", "INSIGHT"),
    ("uses", "FACT"), ("is built on", "FACT"), ("runs on", "FACT"),
]

_DEFAULT_TYPE = "FACT"


def guess_memory_type(content: str,
                      algorithm_version: str = CLASSIFICATION_ALGORITHM_VERSION) -> str:
    """Deterministic keyword-based type hint. Falls back to FACT."""
    if algorithm_version != CLASSIFICATION_ALGORITHM_VERSION:
        raise ValueError(f"Unknown classification algorithm version: {algorithm_version}")
    low = content.lower()
    for kw, mtype in _KEYWORD_TYPE_HINTS:
        if kw in low:
            return mtype
    return _DEFAULT_TYPE


def score_importance(content: str, memory_type: str,
                     recency_days: Optional[int] = None,
                     user_designated: bool = False,
                     downstream_uses: int = 0,
                     dependency_count: int = 0,
                     security_significant: bool = False,
                     governance_significant: bool = False,
                     decision_impact: float = 0.0) -> float:
    """Compute an independent importance score in [0, 1].

    Importance ranks salience only; it is orthogonal to correctness. The score
    is bounded and deterministic given the same inputs.
    """
    score = 0.2  # baseline salience

    # Recency factor (most recent decays importance least within a horizon).
    if recency_days is not None:
        score += max(0.0, 0.15 * (1.0 - min(recency_days, 365) / 365.0))

    if user_designated:
        score += 0.2
    score += min(0.2, downstream_uses * 0.05)
    score += min(0.15, dependency_count * 0.05)
    if security_significant:
        score += 0.1
    if governance_significant:
        score += 0.1
    score += min(0.1, max(0.0, decision_impact))
    return round(min(1.0, max(0.0, score)), 4)


def staleness(updated_at: str, ttl_days: float = 180.0) -> str:
    """Map an age to FRESH / AGING / STALE / OBSOLETE (never auto-deletes)."""
    from .models import STALENESS
    updated = datetime.datetime.fromisoformat(updated_at)
    now = datetime.datetime.now(updated.tzinfo)
    age_days = (now - updated).total_seconds() / 86400.0
    if age_days < ttl_days * 0.5:
        return "FRESH"
    if age_days < ttl_days:
        return "AGING"
    if age_days < ttl_days * 2:
        return "STALE"
    return "OBSOLETE"
