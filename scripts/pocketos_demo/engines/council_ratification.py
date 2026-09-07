"""council_ratification.py — Multi-member signed council ratification.

Canonical ratification primitive for Pocket OS (and the wider ecosystem).

Reconstructed to the documented contract (PROJECT_MAP.md, thread dad741c8):
single-file, pure stdlib, self-contained, executable test harness.

Semantics (these ARE the contract):
  * ALLOWED_STATES = frozenset({"RATIFIED", "PROMOTED"}) — checked FIRST in verify.
  * QUORUM = 2 — minimum distinct members whose signatures must verify.
  * Registry = dict[ratifier -> list[(kid, key_bytes)]], oldest→newest; the LAST
    record is the member's ACTIVE key; earlier ones are append-only audit history.
  * new_registry(keys) wraps a flat {ratifier: key} map into single-version
    Registry entries ("<id>:v1").
  * rotate(registry, ratifier, new_key) is PURE — returns a NEW registry with a
    fresh active key appended; original unchanged; raises KeyError for unknown
    members. Under the live registry the old key is immediately revoked, while a
    signature made under the old key still verifies against the registry snapshot
    that was live when it was signed.
  * active_key(registry, ratifier) returns the current (kid, key) or None.
  * canonical(candidate_id, state, ratifier) — deterministic signed payload:
    {"candidate_id", "ratifier", "state"}, JSON-sorted keys, compact separators.
  * sign(...) — HMAC-SHA256 over canonical(...) under the member's ACTIVE key.
  * verify(...) — per-signature check: reject if state not in ALLOWED_STATES or
    no active key; else constant-time compare_digest.
  * verify_ratification(...) — quorum gate over dict[ratifier -> signature];
    counts DISTINCT members that verify under their active keys; passes iff
    count >= QUORUM.
  * Ledger = list[dict] — append-only, hash-chained ratification records.
  * ratify(candidate_id, state, signatures, registry, ledger) — GOVERNED COMMIT:
    if quorum holds, appends ONE hash-chained block
    {index, prev_hash, candidate_id, state, sorted ratifiers, timestamp, hash}
    and returns (True, new_ledger); a denial returns (False, same_ledger),
    appending nothing. First block chains to "GENESIS".
  * verify_ledger(ledger) — recomputes every block hash and the prev_hash chain;
    any gap/edit/reorder fails.

Run:  python3 council_ratification.py   -> prints PASS on all layers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

ALLOWED_STATES: frozenset[str] = frozenset({"RATIFIED", "PROMOTED"})
QUORUM: int = 2

# Registry: dict[ratifier -> list[(kid: str, key: bytes)]], oldest→newest; last is active.
Registry = dict[str, list[tuple[str, bytes]]]


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def new_registry(keys: dict[str, bytes]) -> Registry:
    """Wrap a flat {ratifier: key} map into a single-version Registry."""
    reg: Registry = {}
    for ratifier, key in keys.items():
        reg[ratifier] = [(f"{ratifier}:v1", key)]
    return reg


def rotate(registry: Registry, ratifier: str, new_key: bytes) -> Registry:
    """PURE — return a NEW registry with a fresh active key for `ratifier`.

    The input registry is never mutated. Raises KeyError for unknown members.
    """
    if ratifier not in registry:
        raise KeyError(f"unknown member: {ratifier}")
    history = list(registry[ratifier])
    version = len(history) + 1
    kid = f"{ratifier}:v{version}"
    history = history + [(kid, new_key)]
    out = {r: list(rec) for r, rec in registry.items()}
    out[ratifier] = history
    return out


def active_key(registry: Registry, ratifier: str) -> Optional[tuple[str, bytes]]:
    if ratifier not in registry or not registry[ratifier]:
        return None
    return registry[ratifier][-1]


# ---------------------------------------------------------------------------
# Canonical payload + signing
# ---------------------------------------------------------------------------

def canonical(candidate_id: str, state: str, ratifier: str) -> str:
    """Deterministic signed payload: JSON-sorted keys, compact separators."""
    return json.dumps(
        {"candidate_id": candidate_id, "ratifier": ratifier, "state": state},
        sort_keys=True,
        separators=(",", ":"),
    )


def sign(candidate_id: str, state: str, ratifier: str, key: bytes) -> str:
    """HMAC-SHA256 over the canonical payload."""
    return hmac.new(key, canonical(candidate_id, state, ratifier).encode(), hashlib.sha256).hexdigest()


def verify(candidate_id: str, state: str, ratifier: str, signature: str,
           registry: Registry) -> bool:
    """Per-signature check against the member's ACTIVE key.

    Rejects if state is not allowlisted or the member has no active key.
    Constant-time compare via hmac.compare_digest.
    """
    if state not in ALLOWED_STATES:
        return False
    ak = active_key(registry, ratifier)
    if ak is None:
        return False
    _, key = ak
    expected = sign(candidate_id, state, ratifier, key)
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Quorum gate
# ---------------------------------------------------------------------------

def verify_ratification(candidate_id: str, state: str,
                        signatures: dict[str, str],
                        registry: Registry) -> bool:
    """Count DISTINCT members that verify; pass iff count >= QUORUM."""
    if state not in ALLOWED_STATES:
        return False
    verified = set()
    for ratifier, sig in signatures.items():
        if verify(candidate_id, state, ratifier, sig, registry):
            verified.add(ratifier)
    return len(verified) >= QUORUM


# ---------------------------------------------------------------------------
# Append-only ratification ledger
# ---------------------------------------------------------------------------

def _block_hash(block: dict[str, Any]) -> str:
    body = {
        "index": block["index"],
        "prev_hash": block["prev_hash"],
        "candidate_id": block["candidate_id"],
        "state": block["state"],
        "ratifiers": block["ratifiers"],
        "timestamp": block["timestamp"],
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def ratify(candidate_id: str, state: str, signatures: dict[str, str],
           registry: Registry, ledger: list[dict]) -> tuple[bool, list[dict]]:
    """GOVERNED COMMIT. Appends ONE hash-chained block iff quorum holds.

    A denial returns (False, unchanged ledger), appending nothing.
    """
    if not verify_ratification(candidate_id, state, signatures, registry):
        return False, ledger
    prev_hash = ledger[-1]["hash"] if ledger else "GENESIS"
    ratifiers = sorted(signatures.keys())
    block = {
        "index": len(ledger),
        "prev_hash": prev_hash,
        "candidate_id": candidate_id,
        "state": state,
        "ratifiers": ratifiers,
        "timestamp": int(time.time()),
        "hash": "",
    }
    block["hash"] = _block_hash(block)
    return True, ledger + [block]


def verify_ledger(ledger: list[dict]) -> bool:
    """Recompute every block hash and walk the prev_hash chain.

    Any edit, gap, or reorder breaks integrity.
    """
    prev = "GENESIS"
    for block in ledger:
        if block.get("prev_hash") != prev:
            return False
        if _block_hash(block) != block.get("hash"):
            return False
        prev = block["hash"]
    return True


# ---------------------------------------------------------------------------
# Self-contained test harness
# ---------------------------------------------------------------------------

def main() -> None:
    # Seed three council members.
    members = {
        "council-a": bytes.fromhex("aa" * 32),
        "council-b": bytes.fromhex("bb" * 32),
        "council-c": bytes.fromhex("cc" * 32),
    }
    reg = new_registry(members)
    ledger: list[dict] = []

    checks = {
        "signed_ratification": False,
        "scope_binding": False,
        "member_binding": False,
        "state_allowlist": False,
        "threshold_quorum": False,
        "key_rotation": False,
        "append_only_ledger": False,
        "tamper_detection": False,
    }

    # 1. Two distinct members sign -> quorum holds.
    cid, st = "candidate-1", "RATIFIED"
    sigs = {
        "council-a": sign(cid, st, "council-a", members["council-a"]),
        "council-b": sign(cid, st, "council-b", members["council-b"]),
    }
    ok, ledger = ratify(cid, st, sigs, reg, ledger)
    checks["signed_ratification"] = ok and len(ledger) == 1 and verify_ledger(ledger)

    # 2. Wrong candidate / state / member bindings reject.
    checks["scope_binding"] = (
        not verify(cid + "-x", st, "council-a", sigs["council-a"], reg)
        and not verify(cid, "PROMOTED", "council-a", sigs["council-a"], reg)
    )
    checks["member_binding"] = (
        not verify(cid, st, "council-b", sigs["council-a"], reg)
    )

    # 3. State allowlist: only RATIFIED / PROMOTED may be ratified.
    bad = sign(cid, "EXECUTED", "council-a", members["council-a"])
    checks["state_allowlist"] = not verify(cid, "EXECUTED", "council-a", bad, reg)

    # 4. Threshold quorum: single + duplicate signers are insufficient.
    one = {"council-a": sign(cid, st, "council-a", members["council-a"])}
    dup = {"council-a": one["council-a"], "council-b": one["council-a"]}
    checks["threshold_quorum"] = (
        not verify_ratification(cid, st, one, reg)
        and not verify_ratification(cid, st, dup, reg)
    )

    # 5. Key rotation: old key revoked live; history auditable.
    reg2 = rotate(reg, "council-a", bytes.fromhex("11" * 32))
    old_sig = sign(cid, st, "council-a", members["council-a"])
    checks["key_rotation"] = (
        not verify(cid, st, "council-a", old_sig, reg2)   # revoked live
        and verify(cid, st, "council-a", old_sig, reg)    # auditable vs snapshot
    )

    # 6. Append-only ledger: denials append nothing.
    before = len(ledger)
    sub = {"council-a": one["council-a"]}
    ok2, ledger2 = ratify("candidate-2", st, sub, reg, ledger)
    checks["append_only_ledger"] = (ok2 is False and len(ledger2) == before)

    # 7. Tamper detection: editing a committed block breaks verification.
    if ledger:
        tampered = [dict(b) for b in ledger]
        tampered[0]["state"] = "PROMOTED"
        checks["tamper_detection"] = not verify_ledger(tampered)

    print("council_ratification PASS" if all(checks.values()) else "council_ratification FAIL")
    for k, v in checks.items():
        print(f"  {k}: {v}")
    print(f"  ledger_blocks: {len(ledger)}")


if __name__ == "__main__":
    main()
