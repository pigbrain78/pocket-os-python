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
import json
import urllib.error
import urllib.request
from typing import Any, Optional

from . import council_ratification as council


# ---------------------------------------------------------------------------
# Council member registry (server-authoritative; keys never leave the server)
# ---------------------------------------------------------------------------

# Demo signing is OFF unless explicitly enabled. Production default: off.
# This module is bundled with the local PocketOS demo. Keep the demo flow
# usable out of the box, while allowing production deployments to disable the
# in-process signer explicitly.
_DEMO_SIGNING = os.environ.get("POCKETOS_COUNCIL_DEMO_SIGNING", "1") == "1"
_CONSOLE_SIGNER_URL = os.environ.get("POCKETOS_CONSOLE_SIGNER_URL", "").strip().rstrip("/")
_CONSOLE_SIGNER_TOKEN = os.environ.get("POCKETOS_CONSOLE_SIGNER_TOKEN", "").strip()

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
PROMOTED_STATE: str = "PROMOTED"

# States that grant EXECUTION authority once sealed in a verified council block.
# The contract allowlists both RATIFIED and PROMOTED (see ALLOWED_STATES); a
# decision advanced to PROMOTED carries the same verified-council authority as
# one ratified to RATIFIED, so the runtime gate accepts either.
EXECUTION_AUTHORIZED_STATES: frozenset[str] = frozenset({RATIFIED_STATE, PROMOTED_STATE})


def execution_authorized_state(state: str) -> bool:
    """True when a council-sealed state grants execution authority.

    Mirrors the contract's allowlist: RATIFIED and PROMOTED are both execution
    authorities. A forged or unknown state is never execution-authorized.
    """
    return state in EXECUTION_AUTHORIZED_STATES


def active_members() -> list[str]:
    """Distinct registered council members (server-side identities)."""
    return sorted(REGISTRY.keys())


def signing_enabled() -> bool:
    """True only when the process is the demo signing service. In production
    this is False, so /council-sign is disabled and no signing key is reachable
    over HTTP."""
    return _DEMO_SIGNING


def console_signer_configured() -> bool:
    """True only when the production off-box signer contract is configured."""
    return bool(_CONSOLE_SIGNER_URL and _CONSOLE_SIGNER_TOKEN)


def console_signer_status() -> dict[str, Any]:
    return {
        "configured": console_signer_configured(),
        "mode": "console-signer" if console_signer_configured() else ("demo" if _DEMO_SIGNING else "off-box-unconfigured"),
        "private_keys_in_pocketos": False,
    }


def sign_via_console(member: str, candidate_id: str, state: str) -> Optional[str]:
    """Ask the configured off-box Console Signer for a signature.

    PocketOS never receives or stores signing keys. Any missing configuration,
    transport failure, malformed response, or signer error fails closed.
    """
    if not console_signer_configured():
        return None
    payload = json.dumps({"member": member, "decision_id": candidate_id, "state": state}).encode()
    request = urllib.request.Request(
        f"{_CONSOLE_SIGNER_URL}/sign",
        data=payload,
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json", "Authorization": f"Bearer {_CONSOLE_SIGNER_TOKEN}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = json.loads(response.read().decode())
        signature = body.get("signature")
        return signature if isinstance(signature, str) and signature.strip() else None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


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


def seal_ratification(candidate_id: str, state: str,
                      signatures: dict[str, str],
                      ledger: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Seal a verified ratification as a hash-chained block.

    Returns the appended block (the LAST element of ``council.ratify``'s new
    ledger) when quorum verifies; returns None when quorum is NOT met so the
    caller appends no ratification event.

    ``ledger`` is the current list of previously-sealed blocks (in order). It
    is derived by the caller from the historical `decision.ratified` records.
    """
    ok, new_ledger = council.ratify(candidate_id, state, signatures, REGISTRY, ledger)
    if not ok:
        return None
    return new_ledger[-1]


def blocks_from_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reconstruct the council block chain from historical ratification records.

    Every `decision.ratified` event that was sealed by a council quorum embeds
    its block under ``payload["block"]``. This walks the records in order and
    returns those blocks, preserving their index/prev_hash/hash chain so it can
    be verified with ``council.verify_ledger`` back to GENESIS.
    """
    blocks: list[dict[str, Any]] = []
    for r in records:
        ev = r.get("event") or ""
        if ev != "decision.ratified":
            continue
        block = (r.get("payload") or {}).get("block")
        if isinstance(block, dict) and block.get("hash"):
            blocks.append(block)
    return blocks


def chain_intact(blocks: list[dict[str, Any]]) -> bool:
    """True when the reconstructed block chain verifies end-to-end (GENESIS
    anchor, no gap / edit / reorder / forgery)."""
    return council.verify_ledger(blocks)
