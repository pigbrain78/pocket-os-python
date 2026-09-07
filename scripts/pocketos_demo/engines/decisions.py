"""Decision lifecycle & constitutional runtime engine.

The decision engine owns the only pathway by which a consequential action can
be executed. The browser is a client: it may READ state, CREATE proposals, and
request human ratification — but no client (browser, iPhone, AI Shadow,
Cognitive Twin) can bypass the constitutional path. Ratification is an explicit
human action recorded as a ledger event, and execution is authorized
server-side only after the decision carries a ratified human authority.

Negative guarantees enforced here (and unit-tested):

  * browser cannot execute directly
  * AI Shadow cannot execute directly (authority is always NONE)
  * Cognitive Twin cannot execute directly (advisory only)
  * rejected decisions cannot execute
  * unratified decisions cannot execute
  * a client flipping an in-memory ratification flag cannot execute (the
    runtime re-derives authority from the ledger)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Optional

STAGE_SIGNAL = "SIGNAL"
STAGE_CONTEXT = "CONTEXT"
STAGE_PROPOSAL = "PROPOSAL"
STAGE_COUNCIL = "COUNCIL"
STAGE_CONSENSUS = "CONSENSUS"
STAGE_DECISION_DNA = "DECISION_DNA"
STAGE_REASONING_HASH = "REASONING_HASH"
STAGE_HUMAN_RATIFICATION = "HUMAN_RATIFICATION"
STAGE_GOVERNANCE_BOUNDARY = "GOVERNANCE_BOUNDARY"
STAGE_RUNTIME = "RUNTIME"
STAGE_EXECUTION = "EXECUTION"
STAGE_EVIDENCE = "EVIDENCE"
STAGE_LEDGER = "LEDGER"

DECISION_LIFECYCLE = (
    STAGE_SIGNAL, STAGE_CONTEXT, STAGE_PROPOSAL, STAGE_COUNCIL, STAGE_CONSENSUS,
    STAGE_DECISION_DNA, STAGE_REASONING_HASH, STAGE_HUMAN_RATIFICATION,
    STAGE_GOVERNANCE_BOUNDARY, STAGE_RUNTIME, STAGE_EXECUTION, STAGE_EVIDENCE,
    STAGE_LEDGER,
)

STATUS_PENDING = "PENDING"
STATUS_COUNCIL = "COUNCIL"
STATUS_AWAITING_RATIFICATION = "AWAITING_RATIFICATION"
STATUS_RATIFIED = "RATIFIED"
STATUS_REJECTED = "REJECTED"
STATUS_EXECUTED = "EXECUTED"

HUMAN_AUTHORITY = "HUMAN"
NO_AUTHORITY = "NONE"


def reasoning_hash(text: str) -> str:
    """Deterministic reasoning hash for a decision's proposal text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class Decision:
    """A decision moving through the constitutional lifecycle.

    This is authoritative ledger-derived state, NOT client state. A decision
    only executes when it is RATIFIED by a human and then run through the
    governance boundary.
    """

    decision_id: str
    title: str
    proposal_seq: int
    lifecycle_index: int
    status: str
    human_ratified: bool
    reason_hash: str
    council_approved: bool
    rejected: bool = False
    risk: str = "MEDIUM"
    reversible: bool = True
    executed_seq: Optional[int] = None

    def view(self) -> dict[str, Any]:
        stages = list(DECISION_LIFECYCLE)
        current = stages[min(self.lifecycle_index, len(stages) - 1)]
        return {
            "decision_id": self.decision_id,
            "title": self.title,
            "proposal_seq": self.proposal_seq,
            "status": self.status,
            "stage": current,
            "lifecycle": stages,
            "human_ratified": self.human_ratified,
            "rejected": self.rejected,
            "reason_hash": self.reason_hash,
            "council_approved": self.council_approved,
            "risk": self.risk,
            "reversible": self.reversible,
            "executed_seq": self.executed_seq,
            "can_execute": self.status == STATUS_RATIFIED,
            "evidence_stage": STAGE_EVIDENCE,
        }

    def authority(self) -> str:
        """Who is allowed to push this forward right now."""
        if self.status == STATUS_AWAITING_RATIFICATION:
            return HUMAN_AUTHORITY  # only a human may ratify
        return NO_AUTHORITY


class DecisionRegistry:
    """Server-side registry of decisions derived from ledger events.

    The registry never trusts client claims; it recomputes every decision's
    status from ledger events. Client-supplied authority/approval flags are
    ignored — only recorded events advance a decision.
    """

    def __init__(self) -> None:
        self._decisions: dict[str, Decision] = {}

    def _register(self, decision: Decision) -> None:
        self._decisions[decision.decision_id] = decision

    def ingest(self, record: dict[str, Any]) -> Optional[Decision]:
        """Fold one ledger event into the registry."""
        ev = record.get("event") or ""
        payload = record.get("payload") or {}
        seq = int(record.get("sequence") or 0)

        if ev == "decision.proposed":
            d = Decision(
                decision_id=payload.get("decision_id") or f"d{seq}",
                title=payload.get("title") or "untitled decision",
                proposal_seq=seq,
                lifecycle_index=DECISION_LIFECYCLE.index(STAGE_PROPOSAL),
                status=STATUS_COUNCIL if payload.get("send_to_council") else STATUS_PENDING,
                human_ratified=False,
                reason_hash=reasoning_hash(payload.get("title") or ""),
                council_approved=False,
                risk=payload.get("risk", "MEDIUM"),
                reversible=bool(payload.get("reversible", True)),
            )
            self._register(d)
            return d

        if ev == "decision.council_approved":
            d = self._decisions.get(payload.get("decision_id"))
            if d:
                d.council_approved = True
                d.status = STATUS_AWAITING_RATIFICATION
                d.lifecycle_index = DECISION_LIFECYCLE.index(STAGE_HUMAN_RATIFICATION)
            return d

        if ev == "decision.ratified":
            d = self._decisions.get(payload.get("decision_id"))
            if d:
                d.human_ratified = True
                d.status = STATUS_RATIFIED
                d.lifecycle_index = DECISION_LIFECYCLE.index(STAGE_GOVERNANCE_BOUNDARY)
            return d

        if ev == "decision.rejected":
            d = self._decisions.get(payload.get("decision_id"))
            if d:
                d.rejected = True
                d.status = STATUS_REJECTED
                d.lifecycle_index = DECISION_LIFECYCLE.index(STAGE_GOVERNANCE_BOUNDARY)
            return d

        if ev == "decision.executed":
            d = self._decisions.get(payload.get("decision_id"))
            if d:
                d.status = STATUS_EXECUTED
                d.executed_seq = seq
                d.lifecycle_index = DECISION_LIFECYCLE.index(STAGE_LEDGER)
            return d
        return None

    def rebuild(self, records: list[dict[str, Any]]) -> None:
        self._decisions.clear()
        for r in records:
            self.ingest(r)

    def all(self) -> list[Decision]:
        return sorted(self._decisions.values(), key=lambda d: d.proposal_seq)

    def get(self, decision_id: str) -> Optional[Decision]:
        return self._decisions.get(decision_id)


class ExecutionDenied(Exception):
    """Raised when an execution attempt does not carry a ratified authority."""

    def __init__(self, decision_id: str, reason: str) -> None:
        super().__init__(f"execution denied for {decision_id}: {reason}")
        self.decision_id = decision_id
        self.reason = reason


class ConstitutionalRuntime:
    """The only path to execution. Client calls funnel through here."""

    def __init__(self, registry: DecisionRegistry, ledger) -> None:
        self._registry = registry
        self._ledger = ledger  # has .append(event, source, payload) and .records()

    def _scan_authority(self, decision_id: str) -> dict[str, bool]:
        """Re-derive a decision's authority from the canonical ledger, never
        from the in-memory registry projection.

        A client (or any in-process code) that flips a Decision field by hand
        gains nothing — only recorded events advance a decision.
        """
        proposed = False
        rejected = False
        ratified = False
        executed = False
        for r in self._ledger.records():
            ev = r.get("event") or ""
            payload = r.get("payload") or {}
            if payload.get("decision_id") != decision_id:
                continue
            if ev == "decision.proposed":
                proposed = True
            elif ev == "decision.rejected":
                rejected = True
            elif ev == "decision.ratified":
                ratified = True
            elif ev == "decision.executed":
                executed = True
        return {"proposed": proposed, "rejected": rejected, "ratified": ratified, "executed": executed}

    def execute(self, decision_id: str, claimed_authority: str = NO_AUTHORITY) -> dict[str, Any]:
        """Execute a decision ONLY if the ledger records it as human-ratified.

        ``claimed_authority`` is deliberately ignored for authority — the
        server recomputes truth from the ledger. A client claiming HUMAN
        authority (or mutating an in-memory flag) gains nothing unless a
        recorded ratification event exists.
        """
        decision = self._registry.get(decision_id)
        if decision is None:
            raise ExecutionDenied(decision_id, "unknown decision")
        auth = self._scan_authority(decision_id)
        if not auth["proposed"]:
            raise ExecutionDenied(decision_id, "unknown decision")
        if auth["rejected"]:
            raise ExecutionDenied(decision_id, "decision was rejected")
        if not auth["ratified"]:
            raise ExecutionDenied(decision_id, "decision is not human-ratified")
        if auth["executed"]:
            raise ExecutionDenied(decision_id, "decision already executed")
        record = self._ledger.append(
            "decision.executed",
            "Runtime",
            {
                "decision_id": decision_id,
                "title": decision.title,
                "authority": HUMAN_AUTHORITY,
                "claimed_authority_ignored": claimed_authority,
                "risk": decision.risk,
                "reversible": decision.reversible,
                "result": "executed",
            },
        )
        self._registry.ingest(record)
        return {"executed": True, "decision_id": decision_id, "ledger_seq": record["sequence"]}
