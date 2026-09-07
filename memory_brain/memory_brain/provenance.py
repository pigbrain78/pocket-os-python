"""provenance.py -- provenance chain tracking.

Every memory must answer where it came from, when it was observed, who/what
supplied it, what transformation occurred, and whether it has been verified.
Transformations are typed and never conflated: SOURCE -> OBSERVATION ->
EXTRACTION -> INFERENCE -> MEMORY. An inference is never stored as an original
fact. Each link records the producing agent/model so every hop is traceable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from . import canonical
from .models import _id, iso_now


@dataclass
class ProvenanceLink:
    kind: str  # SOURCE/OBSERVATION/EXTRACTION/INFERENCE/INTERPRETATION/VERIFICATION
    label: str
    actor: Optional[str] = None
    model: Optional[str] = None
    source_ref: Optional[str] = None
    observed_at: Optional[str] = None
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "actor": self.actor,
            "model": self.model,
            "source_ref": self.source_ref,
            "observed_at": self.observed_at,
            "detail": self.detail,
        }


def provenance_digest(links: list[ProvenanceLink]) -> str:
    """Deterministic digest over the provenance chain (immutable, audit)."""
    payload = [l.to_dict() for l in links]
    return canonical.digest(payload, canonical.PROVENANCE)


class Provenance:
    def __init__(self, links: Optional[list[ProvenanceLink]] = None):
        self.links: list[ProvenanceLink] = list(links or [])
        self._validate()

    def _validate(self) -> None:
        from .models import PROVENANCE_KINDS
        for l in self.links:
            if l.kind not in PROVENANCE_KINDS:
                raise ValueError(f"Unknown provenance kind: {l.kind}")

    def add(self, kind: str, label: str, **kw) -> "Provenance":
        self.links.append(ProvenanceLink(kind=kind, label=label, **kw))
        self._validate()
        return self

    def to_dict(self) -> list[dict]:
        return [l.to_dict() for l in self.links]

    def digest(self) -> str:
        return provenance_digest(self.links)

    @property
    def verified(self) -> bool:
        """True only if an explicit VERIFICATION link exists (else UNVERIFIED)."""
        return any(l.kind == "VERIFICATION" for l in self.links)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Provenance links={len(self.links)} verified={self.verified}>"
