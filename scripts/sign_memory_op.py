#!/usr/bin/env python3
"""sign_memory_op.py -- Standalone off-box signer for council-required memory ops.

A council member signs an IRREVERSIBLE memory mutation (retract / delete /
supersede / merge) on a LOCAL, AIR-GAPPED machine. Zero dependency on the
memory_brain runtime, no network calls, fail-closed.

The signature is over a canonical payload bound to (memory_id, operation) —
the SAME candidate the memory_brain council gate verifies, so a signature for
one memory/operation can never be replayed to authorize a different destructive
act (granular scope binding).

Usage:
    # Inspect exactly what you are being asked to sign (no key needed):
    python3 sign_memory_op.py --memory-id MEM-123 --op retract --show-payload

    # Produce a signature (key from a file or env, never argv):
    python3 sign_memory_op.py --memory-id MEM-123 --op retract \\
        --member council-a --key-file ./council-a.key

    # Key from an environment variable:
    MEMBER_KEY_HEX=... python3 sign_memory_op.py --memory-id MEM-123 \\
        --op retract --member council-a --key-env MEMBER_KEY_HEX

    # Inspect/verify an existing signature against a public key:
    python3 sign_memory_op.py --memory-id MEM-123 --op retract \\
        --member council-a --verify-inspect <HEX_SIGNATURE> --key-file ./pub.key

Exit codes: 0 success, 1 misuse, 2 verification failure.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys

# Irreversible operations that require council quorum in memory_brain.
_ALLOWED_OPS = frozenset({"retract", "delete", "supersede", "merge"})
_RATIFIED = "RATIFIED"


def canonical(memory_id: str, op: str, member: str) -> str:
    """Deterministic signed payload — MUST byte-match memory_brain's council gate.

    The gate signs candidate_id = f"{memory_id}:{op}" via council_ratification,
    whose canonical form is {"candidate_id", "ratifier", "state"}. This CLI
    reproduces that EXACT canonical bytes so the emitted signature verifies.
    """
    candidate_id = f"{memory_id}:{op.lower()}"
    return json.dumps(
        {"candidate_id": candidate_id, "ratifier": member, "state": _RATIFIED},
        sort_keys=True, separators=(",", ":"))


def sign(memory_id: str, op: str, member: str, key: bytes) -> str:
    return hmac.new(key, canonical(memory_id, op, member).encode(),
                    hashlib.sha256).hexdigest()


def verify(memory_id: str, op: str, member: str, signature: str, key: bytes) -> bool:
    expected = sign(memory_id, op, member, key)
    return hmac.compare_digest(expected, signature)


def _read_key_file(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return _parse_key_bytes(fh.read().strip(), f"file {path}")
    except OSError as exc:
        print(f"error: cannot read key file '{path}': {exc}", file=sys.stderr)
        sys.exit(1)


def _read_key_env(name: str) -> bytes:
    raw = os.environ.get(name)
    if raw is None:
        print(f"error: environment variable '{name}' is not set", file=sys.stderr)
        sys.exit(1)
    return _parse_key_bytes(raw.encode(), f"env {name}")


def _parse_key_bytes(data: bytes, source: str) -> bytes:
    text = data.decode().strip()
    if len(text) == 64:
        try:
            return bytes.fromhex(text)
        except ValueError:
            pass
    if len(data) == 32:
        return data
    print(f"error: key from {source} must be 32 bytes (64 hex chars or raw); "
          f"got {len(data)} bytes", file=sys.stderr)
    sys.exit(1)


def _validate(memory_id: str, op: str, member: str) -> None:
    if not memory_id:
        print("error: --memory-id is required", file=sys.stderr); sys.exit(1)
    if op.lower() not in _ALLOWED_OPS:
        print(f"error: operation '{op}' is not irreversible/council-required; "
              f"allowed={sorted(_ALLOWED_OPS)}", file=sys.stderr); sys.exit(1)
    if not member:
        print("error: --member is required", file=sys.stderr); sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(prog="sign_memory_op",
        description="Off-box council signing for irreversible memory mutations.")
    ap.add_argument("--memory-id", required=True, help="target memory id")
    ap.add_argument("--op", required=True, choices=sorted(_ALLOWED_OPS),
                    help="irreversible operation being authorized")
    ap.add_argument("--member", required=True, help="council member identity")
    ap.add_argument("--key-file", help="path to 32-byte key file (hex or raw)")
    ap.add_argument("--key-env", help="env var name holding a 64-hex key")
    ap.add_argument("--show-payload", action="store_true",
                    help="print canonical payload to sign and exit (no key)")
    ap.add_argument("--verify-inspect", metavar="HEX_SIG",
                    help="verify this signature against the given key")
    args = ap.parse_args()
    _validate(args.memory_id, args.op, args.member)

    if args.show_payload:
        canon = canonical(args.memory_id, args.op, args.member)
        print(canon)
        print(f"# candidate_id={args.memory_id}:{args.op.lower()} "
              f"state={_RATIFIED} bytes={len(canon.encode())} "
              f"sha256={hashlib.sha256(canon.encode()).hexdigest()}", file=sys.stderr)
        return

    if bool(args.key_file) == bool(args.key_env):
        print("error: provide exactly one of --key-file or --key-env", file=sys.stderr)
        sys.exit(1)
    key = _read_key_file(args.key_file) if args.key_file else _read_key_env(args.key_env)

    if args.verify_inspect:
        ok = verify(args.memory_id, args.op, args.member, args.verify_inspect, key)
        print(json.dumps({"mode": "verify", "member": args.member,
                          "memory_id": args.memory_id, "op": args.op,
                          "signature": args.verify_inspect,
                          "result": "PASS" if ok else "FAIL"}, indent=2))
        sys.exit(0 if ok else 2)

    sig = sign(args.memory_id, args.op, args.member, key)
    canon = canonical(args.memory_id, args.op, args.member)
    print(f"# signing: {canon}", file=sys.stderr)
    print(json.dumps({
        "mode": "sign", "member": args.member,
        "memory_id": args.memory_id, "op": args.op.lower(),
        "signature": sig,
        "note": "submit as one entry of the signatures map on the "
                "memory ratify route"}, indent=2))


if __name__ == "__main__":
    main()
