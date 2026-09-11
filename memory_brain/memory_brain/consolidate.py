"""consolidate.py -- reproducible memory consolidation.

Combining related memories into a canonical memory NEVER rewrites the originals.
Original records are preserved and remain queryable; the consolidated memory
carries links to every input memory plus a reproducible record of the
operation (algorithm version, agent, reason, confidence). Re-running the same
consolidation with the same inputs and algorithm version produces identical
output (determinism).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import canonical

CONSOLIDATION_ALGORITHM_VERSION = "cons-1.0"


@dataclass
class ConsolidationSpec:
    memory_ids: list[str]
    contents: list[str]
    reason: str
    agent: Optional[str] = None
    algorithm_version: str = CONSOLIDATION_ALGORITHM_VERSION


@dataclass
class ConsolidationResult:
    consolidation_id: str
    output_content: str
    input_memories: list[str]
    algorithm_version: str
    reason: str
    agent: Optional[str]
    confidence: float
    reason_summary: str


def build_canonical_content(spec: ConsolidationSpec) -> str:
    """Deterministically synthesize the canonical consolidated memory.

    Concatenates the source contents into one structured statement so the
    output is reproducible from the same inputs (no LLM nondeterminism here --
    if an LLM summary is wanted it must be a separate, explicitly-labeled
    INTERPRETATION memory, not the deterministic consolidation).
    """
    body = "\n".join(f"- {c.strip()}" for c in spec.contents)
    return f"[consolidated {len(spec.contents)} memories]\n{body}"


def run(spec: ConsolidationSpec) -> ConsolidationResult:
    if spec.algorithm_version != CONSOLIDATION_ALGORITHM_VERSION:
        raise ValueError(f"Unknown consolidation algorithm version: {spec.algorithm_version}")
    if len(spec.memory_ids) != len(spec.contents) or not spec.contents:
        raise ValueError("consolidation requires parallel memory_ids and contents")

    output = build_canonical_content(spec)
    # Deterministic consolidation id from the canonical output + inputs.
    digest = canonical.digest({
        "output": output,
        "inputs": spec.memory_ids,
        "algorithm": spec.algorithm_version,
    }, "memory.consolidation")
    consolidation_id = f"cons_{digest[:16]}"
    # Confidence is the provenance-weighted mean; kept as its own figure.
    return ConsolidationResult(
        consolidation_id=consolidation_id,
        output_content=output,
        input_memories=list(spec.memory_ids),
        algorithm_version=spec.algorithm_version,
        reason=spec.reason,
        agent=spec.agent,
        confidence=0.0,  # set by caller from source confidences
        reason_summary=spec.reason,
    )
