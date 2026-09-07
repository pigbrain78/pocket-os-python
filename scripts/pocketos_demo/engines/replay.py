"""Replay scrubber engine.

Deterministically reconstructs historical state from the ledger up to a chosen
sequence. It refuses to reconstruct over a compromised (broken) chain — it
never produces a half-reconstructed state. If replay cannot safely reconstruct
a state it stops and reports why.

A scrub refactor is delegated to an injectable ``_verifier`` so the engine can
be unit-tested with an explicitly compromised chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


class ScrubberError(Exception):
    """Raised when the scrubber refuses to reconstruct state."""

    def __init__(self, message: str, broken_seq: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.broken_seq = broken_seq


@dataclass(frozen=True)
class ScrubResult:
    """A successfully reconstructed historical state slice."""

    start_seq: int
    end_seq: int
    events: tuple[dict[str, Any], ...]
    state: dict[str, Any]

    @property
    def event_count(self) -> int:
        return len(self.events)

    def provenance_line(self) -> str:
        return f"Reconstructed from ledger events {self.start_seq}\u2013{self.end_seq}"


def _merge_state(state: dict[str, Any], event_type: str, payload: dict[str, Any]) -> None:
    """Fold one event into a running aggregate state.

    Legacy records (schema_version legacy_v1) have no event type and no kind;
    they carry no derived-state contribution, so they are skipped rather than
    crashing the fold on a None event.
    """
    if not isinstance(event_type, str) or "." not in event_type:
        return
    kind = event_type.split(".")[0]
    counts = state.setdefault("counts", {})
    counts[kind] = counts.get(kind, 0) + 1
    state.setdefault("kinds_seen", []).append(kind)


class Scrubber:
    """Reconstruct state from a ledger provider up to a chosen sequence.

    The ledger provider must expose ``records()`` returning the canonical list
    of records, and ``__len__`` (the number of records).
    """

    def __init__(
        self,
        ledger,
        verifier: Callable[[], Any] | None = None,
    ) -> None:
        self._ledger = ledger
        self._verifier = verifier

    def _chain_verifier(self):
        from .ledger import verify_chain

        return lambda: verify_chain(self._ledger.records())

    def scrub(self, end_seq: Optional[int] = None) -> ScrubResult:
        records = self._ledger.records()
        verification = (self._verifier or self._chain_verifier())()
        if not verification.intact:
            idx = getattr(verification, "broken_index", None)
            broken = (idx + 1) if idx is not None else None
            raise ScrubberError(
                "Refusing to reconstruct state over a compromised ledger",
                broken_seq=broken,
            )
        n = len(records)
        if end_seq is None:
            end_seq = n
        if not isinstance(end_seq, int):
            raise TypeError("end_seq must be an int")
        if end_seq < 1:
            raise ScrubberError("end_seq must be >= 1")
        if end_seq > n:
            raise ScrubberError(f"end_seq {end_seq} exceeds ledger length {n}")

        state: dict[str, Any] = {"counts": {}, "kinds_seen": []}
        events: list[dict[str, Any]] = []
        for i in range(end_seq):
            rec = records[i]
            events.append(rec)
            _merge_state(state, rec.get("event"), rec.get("payload", {}))
        return ScrubResult(start_seq=1, end_seq=end_seq, events=tuple(events), state=state)
