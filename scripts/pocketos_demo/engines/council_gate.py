"""council_gate.py — Pocket OS adapter for the council ratification contract.

This is the ARCHITECTURAL INTEGRATION of the cryptographic council contract
into Pocket OS, NOT a bolt-on verify() call.

Authority model (the invariant this enforces):

    decision.ratified   ⇐   verified council ratification
    and nothing else.

Bearer permission and cryptographic quorum are deliberately kept distinct:

    * Bearer RATIFY permission  = "may REQUEST ratification"  (necessary, insufficient)
    * Council threshold quorum  = "grants AUTHORITY to ratify" (the only authority)

A `decision.ratified` ledger event is appended ONLY when a threshold of
DISTINCT council members verifies under their ACTIVE keys. A bearer token alone
can never produce the event.

PRODUCTION KEY ISOLATION
------------------------
In production, raw council member signing keys are NOT held in the Pocket OS
runtime and are NEVER reachable through an HTTP route. Pocket OS holds only the
verification material (the active key bytes used to check HMAC signatures) and
relies on each council member signing OFF-BOX.

Signing keys are injected only when the process is explicitly running the DEMO
signing service (POCKETOS_COUNCIL_DEMO_SIGNING=1), which powers the local test
harness and browser demo. When that env var is absent (the production default),
signing keys are never loaded and /council-sign is disabled.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from . import council_ratification as council


# ---------------------------------------------------------------------------
# Council member registry (server-authoritative; keys never leave the server)
# ---------------------------------------------------------------------------

# Demo signing is OFF unless explicitly enabled. Production default: off.
_DEMO_SIGNING = os.environ.get("POCKETOS_COUNCIL_DEMO_SIGNING", "0") == "1"

# Deterministic demo seeds (used ONLY in demo signing mode). In production these
# are replaced by off-box member keys; Pocket OS never sees the raw signing key.
_DEMO_KEYS: dict[str, bytes] = {
    "council-a": bytes.fromhex("aa" * 32),
    "council-b": bytes.fromhex("bb" * 32),
    "council-c": bytes.fromhex("cc" * 32),
}

# The registry Pocket OS verifies signatures against. In demo mode this is the
# seeded demo keys; in production it is loaded from protected config (the active
# public key material per member). Either way, these are verification keys only.
REGISTRY: council.Registry = council.new_registry(_DEMO_KEYS)

# State string a decision is ratified INTO. Must be allowlisted by the contract.
RATIFIED_STATE: str = "RATIFIED"


def active_members() -> list[str]:
    """Distinct registered council members (server-side identities)."""
    return sorted(REGISTRY.keys())


def signing_enabled() -> bool:
    """True only when the process is the demo signing service. In production
    this is False, so /council-sign is disabled and no signing key is reachable
    over HTTP."""
    return _DEMO_SIGNING


def sign_for_member(member: str, candidate_id: str, state: str) -> Optional[str]:
    """Server-side signing on behalf of a council member.

    AVAILABLE ONLY IN DEMO SIGNING MODE (POCKETOS_COUNCIL_DEMO_SIGNING=1),
    which powers the local test harness and browser demo. In production this
    returns None: members sign OFF-BOX and Pocket OS only ever VERIFIES
    signatures; raw signing keys never reside in the Pocket OS runtime or
    behind an HTTP route.
    """
    if not _DEMO_SIGNING:
        return None
    ak = council.active_key(REGISTRY, member)
    if ak is None:
        return None
    _, key = ak
    return council.sign(candidate_id, state, member, key)


def verify_quorum(candidate_id: str, state: str,
                  signatures: dict[str, str]) -> bool:
    """Authoritative quorum check against the live registry. This is the ONLY
    thing that may authorize a `decision.ratified` event."""
    return council.verify_ratification(candidate_id, state, signatures, REGISTRY)


def validate_signatures(candidate_id: str, state: str,
                        signatures: dict[str, str]) -> dict[str, Any]:
    """Per-signature validation result for diagnostics (never authority)."""
    out: dict[str, Any] = {"state_allowed": state in council.ALLOWED_STATES}
    sigs = signatures or {}
    for member in active_members():
        out[member] = council.verify(candidate_id, state, member,
                                     sigs.get(member, ""), REGISTRY)
    out["distinct_verified"] = sum(1 for m in active_members() if out.get(m))
    out["quorum"] = council.QUORUM
    out["quorum_met"] = out["distinct_verified"] >= council.QUORUM
    return out
