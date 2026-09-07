"""models.py -- typed records for the Memory Second Brain.

Deliberately dependency-free (no pydantic) so the core stays deterministic and
testable anywhere. api.py may map these onto pydantic models at the boundary.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def iso_now() -> str:
    """Deterministic ISO-8601 UTC timestamp with microsecond precision."""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# --- Memory status / type constants -------------------------------------
MEMORY_STATUSES = {
    "ACTIVE", "SUPERSEDED", "CONTRADICTED", "RETRACTED",
    "ARCHIVED", "QUARANTINED", "UNVERIFIED",
}

MEMORY_TYPES = {
    "FACT", "BELIEF", "PREFERENCE", "DECISION", "REQUIREMENT", "GOAL",
    "PLAN", "TASK", "PROJECT", "PERSON", "ORGANIZATION", "CONCEPT",
    "DOCUMENT", "EVENT", "OBSERVATION", "LESSON", "FAILURE", "SUCCESS",
    "SKILL", "PROCEDURE", "RULE", "POLICY", "CONSTRAINT", "RELATIONSHIP",
    "QUESTION", "HYPOTHESIS", "INSIGHT", "SUMMARY", "SYSTEM_STATE",
}

# Provenance transformation kinds (never an inference disguised as a fact).
PROVENANCE_KINDS = {
    "SOURCE", "OBSERVATION", "EXTRACTION", "INFERENCE",
    "INTERPRETATION", "VERIFICATION",
}

# Dedup classification of candidate pairs.
DEDUP_CLASS = {
    "EXACT_DUPLICATE", "PROBABLE_DUPLICATE", "RELATED",
    "POSSIBLE_CONTRADICTION", "DISTINCT",
}

# Staleness states.
STALENESS = {"FRESH", "AGING", "STALE", "OBSOLETE"}


@dataclass
class Source:
    source_id: str = field(default_factory=lambda: _id("src"))
    source_type: str = "document"
    external_ref: Optional[str] = None
    author: Optional[str] = None
    observed_at: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "external_ref": self.external_ref,
            "author": self.author,
            "observed_at": self.observed_at,
            "extra": self.extra,
        }


@dataclass
class Confidence:
    """Four separated confidence components -- never collapsed."""

    source: float = 0.0
    extraction: float = 0.0
    inference: float = 0.0

    @property
    def current(self) -> float:
        # Deterministic combination; kept as a *derived* view, components retained.
        if self.inference > 0:
            return round(0.5 * self.source + 0.3 * self.extraction + 0.2 * self.inference, 4)
        return round(0.7 * self.source + 0.3 * self.extraction, 4)

    def to_dict(self) -> dict:
        return {
            "source_confidence": self.source,
            "extraction_confidence": self.extraction,
            "inference_confidence": self.inference,
            "current_confidence": self.current,
        }


@dataclass
class MemoryRecord:
    memory_id: str
    memory_type: str
    content: str
    status: str
    confidence: Confidence
    importance: float
    created_at: str
    updated_at: str
    event_id: str
    content_hash: str
    source_id: Optional[str] = None
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    normalized_content: Optional[str] = None


@dataclass
class LedgerEvent:
    event_id: str
    timestamp: str
    event_type: str
    payload: dict
    previous_event_hash: Optional[str]
    event_hash: str
    algorithm_version: str = "1"


@dataclass
class Relationship:
    rel_id: str
    from_memory: str
    to_memory: str
    rel_type: str
    created_at: str
    event_id: str


@dataclass
class ReviewItem:
    item_id: str
    kind: str
    ref_json: str
    status: str = "PENDING"
    created_at: str = field(default_factory=iso_now)
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    decision_event_id: Optional[str] = None
