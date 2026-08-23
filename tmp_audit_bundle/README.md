# Pocket OS Ledger Audit Bundle

This bundle is a self-contained, independently verifiable snapshot of the
user's Immutable Event Ledger at export time.

## Layout
```
audit_bundle/
├── manifest.json          Bundle metadata + protocol version + hash algorithm
├── head.json              Declared head_hash + chain stats + export timestamp
├── ledger.jsonl           One canonical event per line, chronological
├── verification/
│   └── verify.py          Third-party re-verification (no app trust required)
└── README.md              This file
```

## Verify locally
```
cd audit_bundle
python3 verification/verify.py
```
Exit code 0 = chain is intact and matches declared head_hash.

## Canonicalization
- SHA-256 for artifact/event integrity.
- Canonical JSON: `json.dumps(sort_keys=True, separators=(",", ":"))`.
- Event hash = SHA256(previous_hash + payload_hash + created_at).
- Payload hash = SHA256(canonical JSON of {kind, text, ref_id, meta, user_id}).

## Governance rule
This bundle is EVIDENCE, not authorization. A detected discrepancy is an
auditable finding — it does not grant permission to rewrite history or
retroactively invalidate ratified decisions.
