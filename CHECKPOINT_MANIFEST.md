# Pocket OS — Durable Checkpoint Manifest (app build)

**Status:** GREEN — recoverable checkpoint of the complete Pocket OS source, web
control room, iOS client, and docs. If the workspace resets, this archive restores
the project to its exact current state.

## Checkpoint record

- **Version:** pocketos-app-1.0.0 (canonical core + control room + iOS client/cockpit)
- **Date:** 2026-09-07
- **Ledger:** 25 records, chain VERIFIED INTACT (genesis #1 → head #25), schema `v2`
- **Server:** `127.0.0.1:8787`, `status: healthy`, `integrity: INTACT`
- **Suites:** Python 96/96 green · Swift PocketOSKit 5/5 green · browser suites green
- **Cognitive Twin:** model `twin-1.0`, focus epistemic = `INFERRED`
- **AI Shadow:** advisory, authority `NONE`, can_execute/ratify = false

## Inventory

**Backend** — `scripts/pocketos_demo/` (`app.py` + 9 engine modules + `demo_state.json`
ledger + static web console).

**Web control room** — `scripts/pocketos_demo/static/` (`index.html`, `app.js`,
`styles.css`): Console, Timeline, Graph, Health, Genome, Twin, AI Shadow, Decisions,
Memory, Projects, Open Loops, Governance, Evidence, Ledger.

**iOS** — `ios/Package.swift`, `ios/Sources/PocketOSKit/` (models, projections,
`PocketOSClient`, session, JSONValue, envelopes), `ios/Tests/PocketOSKitTests/` +
`Fixtures/`, `ios/PocketOSApp/Sources/Cockpit/` (SwiftUI: Theme, Components,
ViewModel, Screens, App), `ios/README.md`.

**Docs** — `docs/POCKETOS_APP_ARCHITECTURE.md`, `RELEASE_NOTES.md`,
`outputs/pocketos_controlroom_{proof,memory}.png`.

## Recovery instructions (after a workspace reset)

1. **Restore the tree** — extract the companion archive into the project root: it
   recreates `scripts/`, `tests_pocketos/`, `ios/`, `docs/`, `outputs/`, this manifest.
2. **Reinstall tooling** (a reset wipes packages, Chromium, and the Swift toolchain):
   `python3 -m pip install fastapi uvicorn playwright pytest-playwright httpx`
   `python3 -m playwright install chromium` then `... install-deps chromium`
   Swift toolchain: download Swift 6.0.3 (ubuntu2404) to `/opt/swift` (see runbook).
3. **Start the server** (root = project root): the demo ledger seeds INTACT on first
   boot; do NOT regenerate it.
   `python3 -m uvicorn scripts.pocketos_demo.app:app --host 127.0.0.1 --port 8787`
4. **Run suites** (browser suites need the server up):
   `python3 -m pytest tests_pocketos/ -q`
   `cd ios && swift build && swift test`
5. **Verify** `http://127.0.0.1:8787/api/health` reports `integrity: INTACT`.

## Demo credentials (test/demo builds only)

`admin`/`demo`, `operator`/`demo`, `observer`/`demo`. Passwords are PBKDF2-hashed;
plaintext never appears in source. Sessions are in-memory + revocable by design.

## Notes

- The ledger JSON is the single authoritative durable store; treat it as the
  database and never delete or regenerate it.
- The SwiftUI cockpit (`ios/PocketOSApp/`) is authored and Apple-gated for Xcode;
  it is not compiled in this cloud sandbox. `ios/README.md` documents the Xcode build.
