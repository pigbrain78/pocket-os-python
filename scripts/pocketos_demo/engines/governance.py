"""Governance counters.

Counters are derived deterministically from the ledger's governance events, so
the UI never holds its own authoritative copy — the backend resolves the
counters and the panel only renders them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GovernanceCounters:
    executed: int = 0
    denied: int = 0
    reversed: int = 0

    def render(self) -> str:
        return (
            f"{self.executed} executed \u00b7 "
            f"{self.denied} denied \u00b7 "
            f"{self.reversed} reversed"
        )


def governance_counters(records: list[dict[str, Any]]) -> GovernanceCounters:
    """Count executed / denied / reversed governance outcomes in the chain.

    A deterministic fold — not a stored counter — so it stays consistent no
    matter how the ledger was produced or tampered with.
    """
    executed = 0
    denied = 0
    reversed_ = 0
    for rec in records:
        outcome = (rec.get("payload") or {}).get("outcome")
        if rec.get("event") == "governance.decided":
            if outcome == "approved":
                executed += 1
            elif outcome == "denied":
                denied += 1
            elif outcome == "reversed":
                reversed_ += 1
    return GovernanceCounters(executed=executed, denied=denied, reversed=reversed_)
