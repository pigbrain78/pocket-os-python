"""council.py -- memory_brain adapter to the verified council ratification gate.

Converges memory_brain's governance onto the SAME cryptographic authority that
Pocket OS uses for `decision.ratified`. The invariant enforced:

    a high-impact memory mutation (retract / supersede / merge / delete)
        ⇐ verified council quorum
    and nothing else.

A bare human review APPROVE is NOT authority for these operations. A review
item of a council-required kind only reaches the memory ledger as
`MEMORY_COUNCIL_RATIFIED` after a threshold of distinct council members verifies
under their active keys. The adapter never reimplements signing or quorum; it is
a thin, deterministic wrapper over the exact `council_ratification` contract.

PRODUCTION KEY ISOLATION
------------------------
In production, signing keys are NOT held in this process. The adapter holds
verification material only and validates signatures produced OFF-BOX (see
scripts/council_signer.py). On-box signing is available ONLY in demo mode
(POCKETOS_COUNCIL_DEMO_SIGNING=1) for the local test harness.
"""

from __future__ import annotations

import json
from typing import Optional

# Import the exact contract from the Pocket OS tree. This tree is expected to
# be laid out with the pocketos demo under `scripts/pocketos_demo/engines/`.
try:
    from pocketos_demo.engines import council_ratification as _council
    from pocketos_demo.engines import council_gate as _gate
    _CONTRACT_AVAILABLE = True
except Exception:  # pragma: no cover - contract absent; fail closed
    _council = None
    _gate = None
    _CONTRACT_AVAILABLE = False

# Memory operations that require verified council quorum (irreversible or
# authoritative-mutating). Mirrors the severity classification in governance.py.
_COUNCIL_REQUIRED = frozenset({"retract", "delete", "supersede", "merge"})


class CouncilUnavailable(RuntimeError):
    """Raised when the council contract is not importable in this deployment."""


def available() -> bool:
    """True when the council contract is importable (this process can verify)."""
    return _CONTRACT_AVAILABLE


def is_council_required(operation: str) -> bool:
    """Whether ``operation`` must pass verified council quorum."""
    return operation.lower() in _COUNCIL_REQUIRED


def _registry():
    """Verification registry from the gate. Fails closed if contract absent."""
    if _gate is None:
        raise CouncilUnavailable("council contract is not available")
    return _gate.REGISTRY


def signing_enabled() -> bool:
    if _gate is None:
        return False
    return _gate.signing_enabled()


def candidate_id(memory_id: str, operation: str) -> str:
    """Deterministic candidate id a council member signs.

    Bound to BOTH the memory and the operation so a signature cannot be replayed
    against a different memory or a different (non-ratified) operation.
    """
    return f"{memory_id}:{operation.lower()}"


def payload(memory_id: str, operation: str, detail: Optional[dict] = None) -> dict:
    """The canonical candidate payload the council is asked to ratify."""
    return {
        "memory_id": memory_id,
        "operation": operation.lower(),
        "state": "RATIFIED",
        "detail": detail or {},
    }


def require_ratified(memory_id: str, operation: str,
                     signatures: dict[str, str]) -> bool:
    """Authoritative quorum check. THE ONLY thing that may authorize a
    council-required memory mutation. Returns False (never raises) on any
    verification failure."""
    if not _CONTRACT_AVAILABLE:
        return False
    if not is_council_required(operation):
        raise ValueError(
            f"operation '{operation}' is not council-required; "
            "this gate only applies to retract/delete/supersede/merge")
    return _council.verify_ratification(
        candidate_id(memory_id, operation), "RATIFIED", signatures, _registry())


def validate_signatures(memory_id: str, operation: str,
                        signatures: dict[str, str]) -> dict:
    """Per-signature diagnostics (never authority)."""
    cid = candidate_id(memory_id, operation)
    out: dict = {}
    if _gate is not None:
        reg = _registry()
        for member in sorted(reg.keys()):
            out[member] = _council.verify(
                cid, "RATIFIED", member, (signatures or {}).get(member, ""), reg)
    out["distinct_verified"] = sum(1 for v in out.values() if v)
    out["quorum"] = _council.QUORUM if _council else 2
    out["quorum_met"] = out["distinct_verified"] >= out["quorum"]
    return out


def sign_for_member(member: str, memory_id: str, operation: str) -> Optional[str]:
    """DEMO-ONLY on-box signing. Returns None in production (off-box signing)."""
    if _gate is None or not _gate.signing_enabled():
        return None
    return _gate.sign_for_member(member, candidate_id(memory_id, operation),
                                 "RATIFIED")
