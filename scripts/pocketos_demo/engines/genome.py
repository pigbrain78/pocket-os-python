"""Genome trait engine.

Each trait is a scalar the genome panel renders. Traits must discriminate (the
demo genome is not a saturation scoreboard) and none may peg at 99.
"""

from __future__ import annotations

from dataclasses import dataclass

GENOME_TRAITS: tuple[str, ...] = (
    "recall",
    "reasoning",
    "focus",
    "agency",
    "integrity",
    "synthesis",
)


@dataclass(frozen=True)
class Trait:
    name: str
    score: int  # 0..100


def genome_traits(base: dict[str, int] | None = None) -> list[Trait]:
    """Return the six trait scores. base overrides (demo tamper applies a
    delta) and every score is clamped to 0..100."""
    defaults = {
        "recall": 92,
        "reasoning": 84,
        "focus": 71,
        "agency": 63,
        "integrity": 96,
        "synthesis": 77,
    }
    if base:
        defaults.update(base)
    traits = []
    for name in GENOME_TRAITS:
        value = defaults[name]
        if not isinstance(value, int):
            raise TypeError(f"trait {name} score must be an int")
        value = max(0, min(100, value))
        traits.append(Trait(name=name, score=value))
    return traits
