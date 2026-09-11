"""quality.py -- Memory Quality Engine.

Quality is a composite of INDEPENDENT properties; the breakdown is always
exposed, never hidden behind a single number.

    quality = provenance_quality
            + evidence_quality
            + consistency
            + confidence
            + freshness
            + retrieval_reliability

Each component is computed separately so a reviewer can see WHY a memory
scores as it does.
"""

from __future__ import annotations

from dataclasses import dataclass

QUALITY_ALGORITHM_VERSION = "qual-1.0"


@dataclass
class QualityBreakdown:
    provenance_quality: float
    evidence_quality: float
    consistency: float
    confidence: float
    freshness: float
    retrieval_reliability: float

    @property
    def overall(self) -> float:
        # Equal-weight composite; the breakdown stays visible.
        comps = [self.provenance_quality, self.evidence_quality,
                 self.consistency, self.confidence, self.freshness,
                 self.retrieval_reliability]
        return round(sum(comps) / len(comps), 4)

    def to_dict(self) -> dict:
        return {
            "provenance_quality": self.provenance_quality,
            "evidence_quality": self.evidence_quality,
            "consistency": self.consistency,
            "confidence": self.confidence,
            "freshness": self.freshness,
            "retrieval_reliability": self.retrieval_reliability,
            "overall_quality": self.overall,
        }


def score(memory: dict, verified: bool = False,
          contradicts_any: bool = False,
          retrieved_ok: int = 0, retrieved_total: int = 0,
          algorithm_version: str = QUALITY_ALGORITHM_VERSION) -> QualityBreakdown:
    """Compute a memory's quality breakdown.

    memory: dict with keys content_hash (evidence), confidence, importance,
    updated_at, status. Deterministic for the same inputs.
    """
    if algorithm_version != QUALITY_ALGORITHM_VERSION:
        raise ValueError(f"Unknown quality algorithm version: {algorithm_version}")

    # provenance_quality: verified provenance outranks a bare source.
    provenance_quality = 0.9 if verified else (0.5 if memory.get("source_id") else 0.1)

    # evidence_quality: presence of a content hash + source is the evidence.
    has_hash = bool(memory.get("content_hash"))
    evidence_quality = (0.6 + (0.3 if has_hash else 0.0) +
                        (0.1 if memory.get("source_id") else 0.0))

    # consistency: contradicts_any lowers it.
    consistency = 0.4 if contradicts_any else 0.9

    confidence = float(memory.get("confidence", 0.0))

    # freshness from updated_at age.
    from .classify import staleness
    st = staleness(memory.get("updated_at", ""))
    freshness = {"FRESH": 1.0, "AGING": 0.7, "STALE": 0.4, "OBSOLETE": 0.15}.get(st, 0.5)

    # retrieval_reliability: ratio of successful retrievals over attempts.
    retrieval_reliability = (retrieved_ok / retrieved_total) if retrieved_total else 0.5

    return QualityBreakdown(
        provenance_quality=round(min(1.0, provenance_quality), 4),
        evidence_quality=round(min(1.0, evidence_quality), 4),
        consistency=round(consistency, 4),
        confidence=round(min(1.0, confidence), 4),
        freshness=round(freshness, 4),
        retrieval_reliability=round(retrieval_reliability, 4),
    )
