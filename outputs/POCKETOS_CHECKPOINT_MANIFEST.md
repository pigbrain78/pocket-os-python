Title: Pocket OS — Durable Checkpoint Manifest
Kicker: Recovery instructions + exact state at checkpoint time
Theme: PocketOS
Genre: project-status

# Pocket OS Durable Checkpoint

```figexec
GREEN — a recoverable checkpoint of the complete Pocket OS source, tests, and
ledger has been created. If the workspace resets, this archive restores the
project to its exact current state: no regeneration, no data loss, no
"clean-slate" rebuild. Recovery is deterministic from this manifest.
```

## Checkpoint record

- **Version:** control-room + live-spine + hardened-auth build (ledger schema `v2`)
- **Date:** 2026-09-04
- **Ledger:** 25 records, chain VERIFIED INTACT (genesis `#1` → head `#25`)
- **Server:** `127.0.0.1:8787`, `status: healthy`, `integrity: INTACT`
- **Cognitive Twin:** model `twin-1.0`, focus epistemic = `INFERRED`
- **AI Shadow:** advisory, authority `NONE`

## Source inventory (21 files)

**Backend** — `scripts/pocketos_demo/app.py` (695 LOC) + 9 engine modules under
`scripts/pocketos_demo/engines/` (~1244 LOC): `ledger`, `replay`, `governance`,
`genome`, `seeds`, `cognitive`, `shadow`, `decisions`, `__init__`.

**Frontend** — `scripts/pocketos_demo/static/`: `index.html`, `app.js` (vanilla
JS, SSE live spine), `styles.css`.

**Persistent state** — `scripts/pocketos_demo/demo_state.json` (the append-only
hash-chained ledger; the sole durable store).

## Test inventory (96 tests / 7 suites)

| Suite | Count |
| --- | --- |
| `test_pocketos_engines.py` | 25 |
| `test_pocketos_replay.py` | 11 |
| `test_pocketos_controlroom.py` | 20 |
| `test_pocketos_features.py` | 11 |
| `test_pocketos_auth.py` | 15 |
| `rehearsal_test.py` | 7 |
| `test_rehearsal_controlroom.py` | 7 |

All 96 green at checkpoint time.

## Recovery instructions (after a workspace reset)

1. **Restore the tree** — extract the companion archive (`pocketos_checkpoint_2026-09-04.zip`
   or `.tar.gz`) into the project root. It recreates `scripts/pocketos_demo/`,
   `tests_pocketos/`, and this manifest under `outputs/`.
2. **Reinstall tooling** (a reset wipes packages and Chromium libs):
   `python3 -m pip install fastapi uvicorn playwright pytest-playwright`
   `python3 -m playwright install chromium` then `python3 -m playwright install-deps chromium`
3. **Start the server** (root = project root):
   `python3 -m uvicorn scripts.pocketos_demo.app:app --host 127.0.0.1 --port 8787`
   The demo ledger at `scripts/pocketos_demo/demo_state.json` seeds INTACT on
   first boot; do NOT regenerate it.
4. **Run the suites** (unit/API need no server; browser suites need it up):
   `python3 -m pytest tests_pocketos/<suite>.py -q`
5. **Verify** `http://127.0.0.1:8787/api/health` reports `integrity: INTACT`.

## Demo credentials (test/demo builds only)

Login as `admin` / `demo`, `operator` / `demo`, or `observer` / `demo`. Passwords
are PBKDF2-hashed; the plaintext never appears in source. The `/api/demo/*` and
`/api/test/*` mutators require the `ADMIN` permission and are feature-gated.

## Notes

- Sessions are in-memory by design; a restart drops them (expected — revocable).
- The ledger JSON is the single authoritative durable store; treat it as the
  database and never delete it.
