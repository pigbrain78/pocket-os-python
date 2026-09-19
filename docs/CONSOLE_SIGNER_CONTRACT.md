# PocketOS Console Signer Contract

## Status

This contract is a production-readiness template. Production signing remains disabled until the signer operator supplies and verifies the concrete endpoint, authentication method, algorithm, key identifiers, canonicalization rules, verification material, and error semantics.

## Authority boundary

PocketOS remains the governance authority. The Cognitive Twin informs, the AI Shadow recommends, governance authorizes, a human ratifies when required, the Console Signer signs, the execution runtime executes, and the ledger records. The signer must never decide whether a proposal is authorized.

## Required configuration

| Item | Server-side configuration | Required before enablement |
|---|---|---|
| Signer endpoint | `POCKETOS_CONSOLE_SIGNER_URL` | Yes |
| Authentication secret | `POCKETOS_CONSOLE_SIGNER_TOKEN` | Yes; Render secret only |
| Verification algorithm | `POCKETOS_COUNCIL_SIGNATURE_ALGORITHM=Ed25519` | Yes in production |
| Active public keys | `POCKETOS_COUNCIL_PUBLIC_KEYS_JSON` | Yes; public material only |
| Operational kill switch | `POCKETOS_PRODUCTION_SIGNING_ENABLED=1` | Yes, explicit operator action |
| Runtime environment | `POCKETOS_RUNTIME_ENV` (or `POCKETOS_ENV`) | Yes; must be `production` for off-box production signing |
| Sandbox test signer | `POCKETOS_COUNCIL_TEST_SIGNER_ENABLED=1` (or legacy `POCKETOS_COUNCIL_DEMO_SIGNING=1`) | Required in sandbox/dev/test when council-sign route is exercised |
| Algorithm | Supplied by signer operator | Yes |
| Key identifiers | Supplied by signer operator | Yes |
| Verification material | Active public keys or equivalent | Yes |
| Contract version | Supplied by signer operator | Yes |

Private signing keys must never be stored in PocketOS, the mobile bundle, browser storage, Git, diagnostics, or logs.

## Adapter request

The current adapter sends a server-to-server `POST` request to `<POCKETOS_CONSOLE_SIGNER_URL>/sign` with a bearer token and JSON payload:

```json
{
  "member": "council-a",
  "decision_id": "D-example",
  "state": "RATIFIED"
}
```

This shape is provisional until the signer operator confirms the production contract. Do not enable production signing against an unverified service.

## Adapter response

The current adapter accepts a non-empty JSON string field:

```json
{
  "algorithm": "Ed25519",
  "key_id": "council-a:v1",
  "signature": "<base64-encoded-64-byte-signature>"
}
```

A production deployment verifies the returned signature against the expected public key, algorithm, canonical message, and key identifier before sealing a ratification. HTTP success alone is not cryptographic proof. The public-key registry is a JSON object keyed by council member, for example `{"council-a":{"key_id":"council-a:v1","public_key":"<base64-32-byte-public-key>"}}`; all active members must be present or verification fails closed.

## Fail-closed behavior

Signing is permitted only when all conditions hold:

1. The production kill switch is explicitly enabled.
2. The Console Signer endpoint and server-side token are configured.
3. The signer authentication succeeds.
4. The response matches the verified contract.
5. Independent signature verification succeeds.
6. Governance and human-ratification rules already authorize the operation.

Timeouts and unknown responses return no signature. Signing requests must use deterministic request identifiers and idempotency semantics before production activation; ordinary health retries must never be copied blindly to signing requests.

## Readiness gate

Before setting `POCKETOS_PRODUCTION_SIGNING_ENABLED=1`, verify the positive and negative signature cases, signer identity, key rotation behavior, timeout behavior, outage recovery, no-secret logging, exact production CORS origins, ledger integrity, and the complete backend/mobile test suites.

## Migration notes

- Non-production environments should explicitly set `POCKETOS_RUNTIME_ENV=sandbox` (or `POCKETOS_ENV=sandbox`) and enable `POCKETOS_COUNCIL_TEST_SIGNER_ENABLED=1` for deterministic local council signatures.
- Production signing is now fail-closed outside `production` runtime mode even if `POCKETOS_PRODUCTION_SIGNING_ENABLED=1` is set.
