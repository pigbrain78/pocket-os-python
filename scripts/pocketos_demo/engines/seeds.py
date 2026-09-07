"""Seed data and demo feature gate.

The seed produces an INTACT, hash-chained ledger. Demo build items (tamper,
reset, seed-legacy) are gated behind DEMO_FEATURE_GATE so none ships to
production. The seed intentionally includes tension-flagged memories and a
full decision lifecycle so the console, twin, and shadow have real data.
"""

from __future__ import annotations

from typing import Any

from .ledger import hash_record

# Demo-only feature flag. When False, tamper/reset/seed-legacy are disabled.
DEMO_FEATURE_GATE = True

SEED_CONTRADICTIONS = 4


def _payload(
    title: str,
    note: str = "",
    tension: int = 0,
    outcome: str | None = None,
) -> dict[str, Any]:
    p: dict[str, Any] = {"title": title}
    if note:
        p["note"] = note
    if tension:
        p["tension"] = tension
    if outcome:
        p["outcome"] = outcome
    return p


def _build_seed_records() -> list[dict[str, Any]]:
    """Build the canonical INTACT seed as a list of record dicts, each with an
    empty hash field to be filled by the hash chaining pass."""
    specs: list[tuple[str, str, dict[str, Any]]] = [
        # tension: 4 web/saas contradicting claims
        ("memory.created", "PocketOS", _payload("system state: web", tension=1)),
        ("memory.created", "PocketOS", _payload("system state: saas", tension=1)),
        ("memory.created", "PocketOS", _payload("system state: web", tension=1)),
        ("memory.created", "PocketOS", _payload("system state: saas", tension=1)),
        # governance decisions fold into executed/denied/reversed counters
        ("governance.decided", "Governance", _payload("approve agent action", tension=0, outcome="approved")),
        ("governance.decided", "Governance", _payload("deny external publish", tension=0, outcome="denied")),
        ("governance.decided", "Governance", _payload("reverse stale approval", tension=0, outcome="reversed")),
        # decision lifecycle: proposal -> council -> human ratification
        ("decision.proposed", "AI Shadow", {
            "title": "Execute capability: ingest v1 corpus",
            "decision_id": "D-CORPUS-1001",
            "risk": "MEDIUM",
            "reversible": True,
            "send_to_council": True,
        }),
        ("decision.council_approved", "Council", {
            "decision_id": "D-CORPUS-1001", "council": "APPROVED",
        }),
        ("decision.ratified", "Human", {
            "decision_id": "D-CORPUS-1001", "authority": "HUMAN",
        }),
        # a rejected decision — can never execute
        ("decision.proposed", "AI Shadow", {
            "title": "Publish internal metrics externally",
            "decision_id": "D-METRICS-1002",
            "risk": "HIGH",
            "reversible": False,
            "send_to_council": True,
        }),
        ("decision.council_approved", "Council", {
            "decision_id": "D-METRICS-1002", "council": "APPROVED",
        }),
        ("decision.rejected", "Human", {
            "decision_id": "D-METRICS-1002", "authority": "HUMAN", "reason": "external side effect",
        }),
        # a pending proposal not yet through council
        ("decision.proposed", "AI Shadow", {
            "title": "Open new knowledge workspace",
            "decision_id": "D-WORKSPACE-1003",
            "risk": "LOW",
            "reversible": True,
            "send_to_council": False,
        }),
        # plain memory + tasks for the twin to fold
        ("memory.created", "PocketOS", _payload("plan for PocketOS web control plane", tension=0)),
        ("memory.created", "PocketOS", _payload("edge node sync cadence", tension=0)),
        ("task.created", "PocketOS", _payload("scaffold web console", tension=0)),
        ("task.created", "PocketOS", _payload("wire governance console", tension=0)),
        ("task.completed", "PocketOS", _payload("scaffold web console", tension=0)),
        ("task.created", "PocketOS", _payload("integrate replay scrubber", tension=0)),
        ("knowledge.document", "Import", _payload("PocketOS architecture notes", tension=0)),
        ("knowledge.document", "Import", _payload("iPhone client requirements", tension=0)),
        ("agent.observation", "RALPH5", _payload("found failing test in web harness", tension=0)),
        ("system.sync", "PocketOS", _payload("edge node sync complete", tension=0)),
        ("system.health", "PocketOS", _payload("all subsystems nominal", tension=0)),
    ]
    records: list[dict[str, Any]] = []
    prev_hash: str | None = None
    for i, (event, source, payload) in enumerate(specs):
        row: dict[str, Any] = {
            "sequence": i + 1,
            "event": event,
            "timestamp": 0,
            "source": source,
            "schema_version": "v2",
            "kind": event.split(".")[0],
            "payload": payload,
            "previous_hash": prev_hash,
            "hash": "",
        }
        row["hash"] = hash_record(row)
        prev_hash = row["hash"]
        records.append(row)
    return records


SEED_RECORDS = _build_seed_records()


def seed_ledger() -> list[dict[str, Any]]:
    """Return a fresh copy of the canonical INTACT seed chain."""
    return [dict(r) for r in SEED_RECORDS]


def contradiction_count(records: list[dict[str, Any]]) -> int:
    """Number of records flagged with tension (contradicting claims)."""
    return sum(1 for r in records if bool((r.get("payload") or {}).get("tension")))
