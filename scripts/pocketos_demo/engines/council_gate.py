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
can never produce the event. This removes the previous alternate authority
channel (permission -> ratify event) so the ledger event is authoritative by
construction — the runtime's ledger scan then merely READS an already-verified
event rather than deciding ratification itself.

The council member registry (and its keys) live here, server-side only. Keys
are never exposed to clients. A client submits signatures; the adapter verifies
them against the active keys and, on quorum, emits the single authoritative
ledger event through STATE.append.
"""

from __future__ import annotations

from typing import Any, Optional

from . import council_ratification as council


# ---------------------------------------------------------------------------
# Council member registry (server-authoritative; keys never leave the server)
# ---------------------------------------------------------------------------

# Three council members. Keys are deterministic demo seeds — in production these
# would be injected from protected storage / HSM. They exist ONLY to prove the
# cryptographic boundary; they are not credentials for the bearer API.
_COUNCIL_KEYS: dict[str, bytes] = {
    "council-a": bytes.fromhex("aa" * 32),
    "council-b": bytes.fromhex("bb" * 32),
    "council-c": bytes.fromhex("cc" * 32),
}

REGISTRY: council.Registry = council.new_registry(_COUNCIL_KEYS)

# State string a decision is ratified INTO. Must be allowlisted by the contract.
RATIFIED_STATE: str = "RATIFIED"


def active_members() -> list[str]:
    """Distinct registered council members (server-side identities)."""
    return sorted(REGISTRY.keys())


def sign_for_member(member: str, candidate_id: str, state: str) -> Optional[str]:
    """Server-side signing on behalf of a council member (used in tests/demo to
    assemble a quorum; a real deployment would have each member sign off-box).

    Returns None for an unknown member.
    """
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
