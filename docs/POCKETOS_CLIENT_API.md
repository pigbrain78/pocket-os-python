# Pocket OS — Shared Client / API Contract

Version: 1 (schema `v2`)
Status: canonical

This document defines the boundary between Pocket OS clients — the web console
today, the native iPhone application tomorrow — and the single canonical Pocket
OS system. Both clients consume the **same** versioned contract. There is one
Cognitive Twin, one AI Shadow, one Memory, one Ledger, one Governance boundary;
clients only ever project and command it.

---

## 1. Architecture

```
UI (web today, iPhone tomorrow)
        │
        ▼
PocketClient            domain facade — stable method surface
        │
        ▼
PocketTransport         owns HTTP, auth headers, serialization, errors, paths
        │
        ▼
Pocket OS API  /api/v1 versioned, platform-neutral JSON
        │
        ▼
Canonical core          ledger / governance / twin / shadow / runtime
```

Rules:

- **The client is untrusted.** The browser must never be authoritative. Server
  state always wins over any local cache (a cache is only a projection).
- **Commands are not execution.** A client may propose and, with the matching
  server-side authority, ratify or reject — it can never execute directly.
  Every command still travels the governance/constitutional path.
- **Only the transport knows wire paths.** The UI calls `pocket.<domain>.*`,
  never `fetch()` or a route string.

---

## 2. Client boundary

The web UI interacts with Pocket OS only through `window.pocket` (loaded from
`/static/lib/pocket/`). It does not call `fetch()`, `localStorage`,
`EventSource` against a hardcoded URL, or any API route directly. The iPhone
client will use the identical HTTP contract, so no web-specific code lives in
the transport.

`PocketClient` exposes domain concepts, not routes:

- `system.getStatus()`
- `memory.list()`, `memory.get(id)`
- `cognitiveTwin.getState()`
- `aiShadow.listObservations()`
- `decisions.list/get/propose/ratify/reject`
- `ledger.getStatus/listEvents/getEvent`
- `replay.getStatus/inspect`
- `evidence.getVerificationStatus()`
- `events.subscribe(listener)`
- `session.login/logout/me`
- `console.*` — legacy composite projections the current web console renders
  (kept so the existing UI keeps working; new code should use the domain
  methods above)

---

## 3. API domains (routes)

All under `/api/v1`. Each response envelope carries `api_version`, `request_id`,
and `schema_version`.

| Domain | Endpoint | Kind |
|---|---|---|
| System | `GET /api/v1/status` | query |
| Memory | `GET /api/v1/memory`, `GET /api/v1/memory/{seq}` | query |
| Cognitive Twin | `GET /api/v1/cognitive-twin` | query |
| AI Shadow | `GET /api/v1/ai-shadow` | query |
| Decisions | `GET /api/v1/decisions`, `GET /api/v1/decisions/{id}` | query |
| Decisions | `POST /api/v1/decisions/propose` | command (proposal) |
| Decisions | `POST /api/v1/decisions/{id}/ratify` | command (human) |
| Decisions | `POST /api/v1/decisions/{id}/reject` | command (human) |
| Ledger | `GET /api/v1/ledger`, `GET /api/v1/ledger/events/{seq}` | query |
| Replay | `GET /api/v1/replay/status`, `GET /api/v1/replay/inspect` | query |
| Evidence | `GET /api/v1/evidence/verification` | query |

Commands require an authenticated session (`Authorization: Bearer <token>`)
with the matching permission. Read queries return normalized errors when the
token is missing or lacks permission — never a fabricated success.

---

## 4. Contract types

### System status

```json
{ "api_version": "1", "schema_version": "v2", "request_id": "…",
  "status": "healthy", "ledger": { "integrity": "INTACT", "valid": true },
  "records": 25, "revision": 0, "server_time": 1750000000 }
```

### Memory record

```json
{ "id": "7", "sequence": 7, "event": "memory.created", "kind": "memory",
  "payload": {}, "hash": "…", "provenance": "ledger#7" }
```

### Cognitive Twin

The twin is a model. Inferences are always tagged with an epistemic status and
confidence — never collapsed into a boolean like `trusted`.

```json
{ "cognitive_twin": { "model_version": "twin-1.0",
    "state": { "current_focus": { "text": "…", "epistemic": "INFERRED",
      "confidence": 0.9, "provenance": "…" } } } }
```

### AI Shadow

```json
{ "ai_shadow": { "authority_boundary": { "shadow_authority": "NONE" },
    "items": [ { "type": "…", "text": "…", "authority": "NONE",
      "confidence": 0.0, "provenance": "…" } ] } }
```

The Shadow is advisory. Its authority is always `NONE`; acting on a
recommendation means turning it into a proposal that enters governance.

### Decision

```json
{ "item": { "decision_id": "D-…", "title": "…", "status": "PENDING",
  "risk": "MEDIUM", "reversible": true, "provenance": "ledger#…" } }
```

### Ledger / event

```json
{ "ledger": { "integrity": "INTACT", "valid": true }, "head_sequence": 25,
  "genesis_sequence": 1, "events": [ … ] }
```

### Replay inspect

```json
{ "ok": true, "provenance": "Reconstructed from ledger events 1–14",
  "start_seq": 1, "end_seq": 14, "event_count": 14, "state": {} }
```

On a compromised chain the server refuses: `ok:false` with
`error.code = "REPLAY_REJECTED"` and no partial state slice is ever returned.

---

## 5. Error model

Every failure is a normalized JSON envelope with a **machine-readable code**
(never a parsed human string):

```json
{ "error": { "code": "AUTHENTICATION_REQUIRED", "message": "…",
  "request_id": "…" } }
```

Codes:

`AUTHENTICATION_REQUIRED`, `AUTHORIZATION_DENIED`, `GOVERNANCE_REJECTED`,
`LEASE_EXPIRED`, `VALIDATION_FAILED`, `NOT_FOUND`, `CONFLICT`,
`REPLAY_REJECTED`, `VERIFICATION_FAILED`, `RATE_LIMITED`, `INTERNAL_ERROR`,
`NETWORK_ERROR`.

---

## 6. Event model

`pocket.events.subscribe(listener)` lets the UI observe live events. Events are
observations of canonical state — the browser must never assume receiving an
event means the browser caused it.

```json
{ "type": "memory.created", "event_id": "…", "sequence": 18429,
  "occurred_at": 1750000000, "payload": {} }
```

---

## 7. Governance invariant

```
NO VALID GOVERNANCE AUTHORIZATION  →  NO CAPABILITY LEASE
                                   →  NO EXECUTION
                                   →  NO STATE MUTATION
```

There is **no** execute route under `/api/v1`. The only decision commands are
propose / ratify / reject; execution authority lives server-side behind the
constitutional runtime. A client can never grant itself authority, supply a
ledger position, or mint a hash.

---

## 8. iPhone compatibility

The contract is platform-neutral JSON: stable IDs, explicit timestamps,
versioned schemas, deterministic serialization, provenance references. No
`localStorage`, DOM, `window`, or browser-only field appears in any canonical
response (enforced by a boundary test). The future Swift/iOS client consumes
the same objects without reproducing backend logic.

---

## 9. Versioning & migration

`/api/v1` is the stable contract. The legacy `/api` routes remain for the
current console's composite projections and are owned by the transport (via
`pocket.console.*`); they are not part of the canonical client contract. When
the contract changes, a new versioned surface (`/api/v2`) is added rather than
mutating `/api/v1` in place.

## 10. Machine-readable schema

The contract is published as an OpenAPI 3.1 document for code generation:

- **Live**: `GET /api/v1/openapi.json` — always reflects the running app.
- **Committed artifact**: `docs/POCKETOS_CLIENT_API.openapi.json` — the
  canonical `/api/v1` surface only (16 paths), versioned and checked in so the
  iPhone client can pin a spec even when the live server is unreachable.

A Swift/iOS client can generate its transport (types, routes, request bodies)
directly from this schema, which is exactly why the contract carries no
web-only concepts.
