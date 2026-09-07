# Pocket OS — Release Notes (Web Control Room + iPhone Cockpit)

**Version:** pocketos-app-1.0.0
**Date:** 2026-09-07
**Ledger:** 25 records, chain VERIFIED INTACT (genesis #1 → head #25)
**Suites:** Python 96/96 green · Swift (PocketOSKit) 5/5 green · browser suites green

## What this build delivers

Pocket OS is built as **one system with two clients** — both are clients of the same
canonical backend, never competing sources of truth:

1. **Canonical core** (recovered from the verified checkpoint, never reset). The
   ledger (`scripts/pocketos_demo/demo_state.json`) is the sole authoritative store;
   `/api/*` + `/api/stream` expose projections and the constitutional command surface.
2. **Web control room** — the existing 8-tab console extended with six read-only
   views over the canonical API: **Memory, Projects, Open Loops, Governance,
   Evidence, Ledger** (plus existing Console/Timeline/Graph/Health/Genome/Twin/AI
   Shadow/Decisions). Every view renders server-resolved state; none issues a
   mutation or computes authority.
3. **iPhone client** — `ios/PocketOSKit` (SwiftPM library: models, projections,
   `PocketOSClient` transport) **compiles and tests on Linux** and decodes the real
   API contract from captured fixtures. The SwiftUI cockpit (`ios/PocketOSApp/`) is
   authored for Xcode per `ios/README.md` (this cloud sandbox cannot compile iOS UI).
4. **Architecture contract** — `docs/POCKETOS_APP_ARCHITECTURE.md` (anti-drift).

## Authority model (unchanged, enforced)

`MEMORY MAY INFORM. MEMORY MAY NOT AUTHORIZE.` The UI shows proposals and
recommendations; the only human acts are server-permitted ratify/reject. Execution
requires a **ledger-recorded human ratification** plus the EXECUTE permission — both
server-side. Client-supplied authority claims are ignored.

## Verification evidence (this gate)

- Python suites 96/96 green (engines, replay, control-room, features, auth, rehearsal).
- Swift decode tests 5/5 green against live-captured fixtures (twin/shadow/decisions/
  state/health).
- **Negative guarantees exercised live:**
  - `observer` (READ-only) → execution 403 `permission required: EXECUTE`; proposal 403.
  - `operator` with EXECUTE + forged `claimed_authority: EXECUTE` on an unratified
    decision → `EXECUTION_DENIED: decision is not human-ratified` (runtime re-derives
    authority from the ledger, not the client).
  - Ledger unchanged at 25 records, chain INTACT throughout.
- Governance counters reflect the constitutional fold: `1 executed · 1 denied ·
  1 reversed`.
- SSE `/api/stream` connects and delivers the `hello` envelope (revision, records);
  live push-after-mutation is covered by the green `test_sse_pushes_ledger_event` suite.
- Web control room rendered and captured (Chromium proof images in git `outputs/`).

## Run commands (after a reset)

```bash
# 1. Restore tree from the durable checkpoint archive.
# 2. Tooling (only needed if wiped):
python3 -m pip install fastapi uvicorn playwright pytest-playwright httpx
python3 -m playwright install chromium && python3 -m playwright install-deps chromium
# 3. Server (root = project root; ledger seeds INTACT, do not regenerate):
python3 -m uvicorn scripts.pocketos_demo.app:app --host 127.0.0.1 --port 8787
# 4. Python suites (browser suites need the server up):
python3 -m pytest tests_pocketos/ -q
# 5. iOS model/client suites (needs the Swift toolchain):
cd ios && swift build && swift test
# 6. Verify: http://127.0.0.1:8787/api/health → integrity INTACT
```

Demo credentials: `admin` / `demo`, `operator` / `demo`, `observer` / `demo`.
Passwords are PBKDF2-hashed; plaintext never appears in source.

## Building the iPhone app (Xcode)

See `ios/README.md`. The SwiftUI cockpit is Apple-gated and requires a Mac/Xcode
session against the same `ios/` package; the Linux-compilable `PocketOSKit` layers
are already verified here.

## Files added/changed (commits)

- `e28620a` recover verified checkpoint + architecture anti-drift contract
- `1a328c0` canonical core audit green (no execute route, 96/96)
- `41521df` control room — memory/projects/open-loops/governance/evidence/ledger views
- `9eeab89` ios foundation — PocketOSKit decodes real API contract, 5 tests green
- `b8a08d2` ios cockpit — authored SwiftUI + README runbook
- (verification gate commits) proof images + this release note
