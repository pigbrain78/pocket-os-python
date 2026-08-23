#!/usr/bin/env python3
"""Pocket OS Ledger — independent verification script.

Reads ledger.jsonl (one canonical event per line, chronological order) and
recomputes the hash chain WITHOUT trusting the exporting application.
Exit code 0 = chain valid, matches head.json.
Exit code 1 = chain broken (details printed to stdout).

The canonical payload used for hashing is the exact JSON object
    {"kind": ..., "text": ..., "ref_id": ..., "meta": ..., "user_id": ...}
serialized with json.dumps(sort_keys=True, separators=(",", ":")) and
SHA-256'd. The event hash is SHA-256 of (previous_hash + payload_hash + created_at).
"""
import json, hashlib, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ledger_path = ROOT / "ledger.jsonl"
head_path = ROOT / "head.json"

with open(head_path) as f:
    head = json.load(f)
expected_head = head["head_hash"]
protocol_version = head.get("protocol_version")

prev = "0" * 64
count = 0
verified = 0
breaks = []
with open(ledger_path) as f:
    for i, line in enumerate(f):
        line = line.strip()
        if not line:
            continue
        e = json.loads(line)
        count += 1
        canonical = json.dumps({
            "kind": e["kind"], "text": e["text"], "ref_id": e.get("ref_id"),
            "meta": e.get("meta", {}), "user_id": e["user_id"],
        }, sort_keys=True, separators=(",", ":"))
        payload_hash = hashlib.sha256(canonical.encode()).hexdigest()
        recomputed = hashlib.sha256((prev + payload_hash + e["created_at"]).encode()).hexdigest()
        ok = (
            e.get("previous_hash") == prev
            and e.get("payload_hash") == payload_hash
            and e.get("hash") == recomputed
        )
        if not ok:
            breaks.append({"index": i, "id": e.get("id"), "kind": e.get("kind")})
        else:
            verified += 1
        prev = e.get("hash", prev)

status_ok = (not breaks) and prev == expected_head and count > 0
print(f"protocol_version : {protocol_version}")
print(f"events           : {count}")
print(f"verified         : {verified}")
print(f"breaks           : {len(breaks)}")
print(f"recomputed_head  : {prev}")
print(f"declared_head    : {expected_head}")
print(f"chain_verified   : {status_ok}")
if breaks:
    for b in breaks[:10]:
        print(" - break:", b)
sys.exit(0 if status_ok else 1)
