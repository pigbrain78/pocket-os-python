# PocketOS Demo Quickstart

This checkpoint is intended for a small feedback group: it is not a production deployment, but it provides a coherent, governed demo surface that can be exercised locally without external credentials.

## Run locally

From the repository root:

```bash
python -m pip install -r requirements.txt
PYTHONPATH=. uvicorn scripts.pocketos_demo.app:app --host 127.0.0.1 --port 8787
```

Open `http://127.0.0.1:8787/` in a browser. The canonical client API is available under `/api/v1`; the machine-readable contract is available at `/api/v1/openapi.json`.

The demo users are intentionally simple:

| User | Password | Purpose |
|---|---|---|
| `admin` | `demo` | Full demo operator permissions |
| `operator` | `demo` | Proposal and governance operator permissions |
| `observer` | `demo` | Read-only boundary testing |

These credentials are for local demonstration only. Do not reuse them for a public deployment.

## Suggested walkthrough

First, show the healthy canonical state at `/api/v1/status`, `/api/v1/cognitive-twin`, and `/api/v1/ai-shadow`. The response includes explicit epistemic and authority fields; the AI Shadow is advisory and has no execution or ratification authority.

Next, log in as `admin` and propose a reversible low-risk decision. A proposal remains governed: it must be council-approved, signed by the configured council members, and ratified before it can become execution-authorized. A bearer token or a client-supplied authority claim cannot bypass those gates.

For the local deterministic rehearsal, enable the sandbox signer only in the process environment before starting the server:

```bash
POCKETOS_RUNTIME_ENV=sandbox \
POCKETOS_COUNCIL_TEST_SIGNER_ENABLED=1 \
PYTHONPATH=. uvicorn scripts.pocketos_demo.app:app --host 127.0.0.1 --port 8787
```

Production signing remains fail-closed. It requires an explicitly enabled production switch, a verified off-box Console Signer, and an Ed25519 public-key registry. Private signing keys must never be placed in this repository or in the PocketOS process.

Finally, use `/api/v1/ledger`, `/api/v1/replay/status`, and `/api/v1/stream/fallback` to demonstrate append-only evidence, replay refusal after tampering, and polling fallback when a live SSE connection is unavailable.

## Validation checkpoint

The current local verification baseline is:

- **22/22** canonical `/api/v1` boundary tests passed.
- **129/129** non-browser PocketOS tests passed against a local server.
- Ed25519, signer, Render-contract, control-room, and cryptographic regression tests passed.
- Browser rehearsal tests remain a separate layer and require the Playwright pytest plugin and browser installation.

## Feedback prompts

Ask testers to report the first screen or action where they become uncertain, any response that is difficult to understand, and any point where they expect an action to be available but governance correctly blocks it. Those observations are more valuable than a generic statement that the demo “works.”

## Known scope limits

This checkpoint is suitable for a beginner-facing app demo and structured feedback, not for production use. It does not include a provisioned production Console Signer, durable multi-user deployment storage, a production secret-management setup, or a completed browser automation environment. Those should be completed after the first feedback round identifies the highest-value missing workflows.
