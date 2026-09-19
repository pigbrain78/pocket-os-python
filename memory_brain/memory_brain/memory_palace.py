"""Hollow memory palace primitives for holding contradictory ideas safely."""

from __future__ import annotations

from typing import Dict, Iterable


class HollowMemoryPalace:
    """A container that stores contradictory ideas in isolated structures."""

    def __init__(self, VOID_ARCHITECT_PRIMUS: str):
        self.VOID_ARCHITECT_PRIMUS = VOID_ARCHITECT_PRIMUS
        self._negative_hollow_dimensions: Dict[int, str] = {}
        self._internal_universes: Dict[str, str] = {}

    def store_contradictory_ideas(self, ideas: Iterable[str]) -> Dict[int, str]:
        """Store ideas in negative-indexed dimensions."""
        self._negative_hollow_dimensions = {
            -(index + 1): str(idea) for index, idea in enumerate(ideas)
        }
        return dict(self._negative_hollow_dimensions)

    def separate_internal_universes(
        self, conflicting_beliefs: Iterable[str]
    ) -> Dict[str, str]:
        """Assign each belief to a dedicated internal universe."""
        self._internal_universes = {
            f"universe_{index + 1}": str(belief)
            for index, belief in enumerate(conflicting_beliefs)
        }
        return dict(self._internal_universes)

    def govern_geometry(self) -> Dict[str, object]:
        """Return the governed geometry metadata for the current palace state."""
        return {
            "VOID_ARCHITECT_PRIMUS": self.VOID_ARCHITECT_PRIMUS,
            "negative_hollow_dimensions": dict(self._negative_hollow_dimensions),
            "internal_universes": dict(self._internal_universes),
        }


class CreativeProfessional(HollowMemoryPalace):
    """Specialized palace user that can hold paradoxical worldviews."""

    def hold_paradoxical_worldviews(self) -> bool:
        return bool(self._negative_hollow_dimensions and self._internal_universes)
