# Pocket OS — Application Architecture (Anti-Drift Contract)

**Status:** Canonical reference for the Pocket OS clients (web control room + iPhone).
Every major architectural addition MUST be checked against this document before it is
built. Do not silently create architectural drift.

## 0. The One Invariant

> **MEMORY MAY INFORM EXECUTION. MEMORY MAY NOT AUTHORIZE EXECUTION.**
> **LLM MAY PROPOSE. COUNCIL MAY EVALUATE. GOVERNANCE MAY AUTHORIZE.**
> **HUMAN MAY RATIFY. KERNEL MAY EXECUTE. LEDGER MUST RECORD.**

There is exactly **one** Pocket OS. There is one canonical backend, one canonical
event stream, one ledger, one Cognitive Twin, one AI Shadow. The website and the
iPhone are **clients/projections** of that single system. They never synchronize with
each other directly. They never hold an authoritative copy of any canonical field.

## 1. Canonical Source of Truth

**Authoritative state lives in the server.** Concretely, in the restored build:

- The **ledger** (`scripts/pocketos_demo/demo_state.json`) is the *sole durable,
  append-only, hash-chained store*. Schema `v2`. It is the database. Never delete or
  regenerate it; first boot seeds INTACT and a scrub/replay verifies from genesis.
- Every record carries `sequence`, `event`, `timestamp`, `source`, `schema_version`,
  `kind`, `payload`, `previous_hash`, `hash`. Hashing is deterministic
  (`engines/ledger.py::hash_record`: SHA-256 over canonical sorted-JSON minus the
  self-referential `hash`), and `verify_chain` recomputes the whole chain.
- **Client state is only**: UI state, temporary cache, projection, local presentation.
  A client never authoritatively defines sequence numbers, hashes, ledger positions,
  governance/capability/authority, memory truth, event provenance, canonical
  timestamps, decision authority, execution authority, or cryptographic state.

If a client supplies any such field, the server **ignores or validates it** and owns
the authoritative value. There is no second ledger, no second serialization format.

## 2. Canonical API Boundary

All client traffic goes to the canonical HTTP/SSE API. Endpoints (verified current):

| Method | Path | Purpose | Permission |
| --- | --- | --- | --- |
| GET | `/api/health` | health + ledger integrity | — |
| GET | `/api/state` | full state view (records, counters, traits, contradictions) | — |
| GET | `/api/scrub?end=&include_decisions=` | replay scrub / timeline | — |
| GET | `/api/twin` | Cognitive Twin projection | — |
| GET | `/api/shadow` | AI Shadow projection | — |
| GET | `/api/decisions` | decision registry view | — |
| POST | `/api/login` | session issue | — |
| GET | `/api/session/me` | current session | bearer |
| POST | `/api/logout` | revoke session | bearer |
| POST | `/api/decisions/propose` | create proposal | PROPOSE |
| POST | `/api/decisions/{id}/council-approve` | council evaluation | COUNCIL |
| POST | `/api/decisions/{id}/ratify` | **human ratification** | RATIFY |
| POST | `/api/decisions/{id}/reject` | human rejection | RATIFY |
| POST | `/api/decisions/{id}/execute` | kernel execution | EXECUTE + ratified |
| GET | `/api/stream` | SSE live spine (observational) | — |

**Constitutional command surface.** The ONLY client-issuable mutations are
`propose`, `council-approve`, `ratify`, `reject`, `execute` on decisions, each
enforced server-side by the permission layer and by `ConstitutionalRuntime`
(`engines/decisions.py`). There is **no** other execute/mutate verb exposed to any
client. The `/api/demo/*` and `/api/test/*` mutators are ADMIN-gated, demo/test only.

**Authority is never client-supplied.** Request bodies that carry `claimed_authority`
are accepted and then **ignored** by the runtime. `_require_permission` binds to the
server session's permission set; `ConstitutionalRuntime.execute` re-derives human
authority from the **ledger** (a ratified decision), never from an in-memory flag a
client could flip.

### Decision lifecycle (constitutional path)

```
SIGNAL → CONTEXT → PROPOSAL → COUNCIL → CONSENSUS → DECISION_DNA
 → REASONING_HASH → HUMAN_RATIFICATION → GOVERNANCE_BOUNDARY
 → RUNTIME → EXECUTION → EVIDENCE → LEDGER
```

Statuses: `PENDING` → `COUNCIL` → `AWAITING_RATIFICATION` → `RATIFIED` →
`EXECUTED`, or → `REJECTED`. PROPOSAL / AUTHORIZATION / EXECUTION / EVIDENCE-OF-
EXECUTION are four distinct things and are never conflated in any UI.

## 3. Event Architecture

`/api/stream` is Server-Sent Events of ledger commits (hello + event envelopes, plus
keepalives). Two client rules are absolute:

1. **An SSE event is an observation**, not proof that this client caused the
   mutation. On receipt the client refetches authoritative state and rebuilds its
   projection.
2. **No competing local event ledger.** There is one stream; there is one ledger.

On reconnect: reconnect → resynchronize authoritative state → rebuild projections →
resume live updates. Use exponential backoff with jitter. Clients never fabricate
sequence or event identity from the stream.

## 4. Cognitive Twin

The Twin is a **pure, deterministic fold over the canonical ledger**
(`engines/cognitive.py`, model `twin-1.0`). It is advisory/modeling, not an
autonomous authority. Every `TwinItem` carries `text`, `epistemic`, `confidence`,
`evidence` (ledger sequences), `provenance` (`ledger#<seq>`). The API returns the
projection; the UI **renders** it and does **not** run Twin reasoning.

Epistemic states (canonical legend): `OBSERVED`, `VERIFIED`, `INFERRED`, `UNCERTAIN`,
`REJECTED`, `STALE`. Do not invent new states unless the backend adds them. Inferred
items must never be visually rendered as facts. `current_focus` is INFERRED by
design.

## 5. AI Shadow

The Shadow is an **advisory observation + proposal layer** (`engines/shadow.py`).
Every Shadow item carries an explicit authority boundary — `AUTHORITY: NONE`,
`CAN EXECUTE: NO`, `CAN RATIFY: NO`. The Shadow recommends; it cannot execute,
cannot authorize, cannot silently modify canonical state. The UI makes this boundary
obvious on every item.

## 6. Governance Boundary

The server is authoritative for governance. Clients **present** the result and invoke
only explicitly supported API operations. The UI never implements governance rules
independently, never grants authority, and never displays client-side governance
logic as authoritative. Governance counters are a deterministic fold
(`engines/governance.py`), never a stored client copy.

## 7. Authority Chain (data ownership)

```
LLM proposes ──► Council evaluates ──► Governance authorizes
        ──► Human ratifies ──► Kernel executes ──► Ledger records
```

Every screen shows proposals/recommendations. The only human acts are the
server-permitted `ratify` / `reject`. **There is no execute verb in any client.**

## 8. Client Architectures

### Web (control room)
```
UI ──► PocketClient ──► transport ──► Pocket OS API (/api/*, /api/stream)
```
Vanilla single-page console today (`static/app.js`), rendering state fetched from the
canonical endpoints. No raw `fetch`/`localStorage`/ledger/governance internals outside
the transport layer.

### iPhone (native)
```
SwiftUI View ──► Observable ViewModel
        ──► PocketTwinProjection / PocketShadowProjection
        ──► PocketOSClient ──► Pocket OS API (/api/*, /api/stream)
```
View renders state; ViewModel coordinates presentation; PocketOSClient owns transport
and session; Pocket OS backend is authoritative. **No Pocket OS business logic lives
in SwiftUI.** ViewModels consume the canonical projections — Twin/Shadow reasoning is
never recreated client-side.

iPhone navigation: HOME, MEMORY, PROJECTS, TWIN, SHADOW, DECISIONS, GOVERNANCE,
EVIDENCE, GRAPH, SETTINGS — native SwiftUI patterns, glanceable hierarchy.

## 9. Authentication & Security

- Authenticate **against the actual backend** (`/api/login` → bearer token;
  `/api/session/me`; `/api/logout`). One auth system. Server sessions are
  in-memory + revocable + expiring (server clock authoritative, TTL 3600s).
- Passwords are PBKDF2-HMAC-SHA256 salted hashes; plaintext never stored or shipped.
  Client-supplied authority/permission claims are never trusted.
- iOS uses the platform secure credential store (Keychain). Web follows the backend
  session model.
- Treat every client as untrusted. Never trust client hashes/sequence/timestamps/
  authz/capability/governance. Never expose secrets or private keys in frontend code.
- No privileged governance logic in any client.

## 10. Synchronization, Offline, Stale State

- **No web↔iPhone sync.** Both talk to the same backend; server wins conflicts.
- Offline (iPhone): cached projections readable and **clearly labeled stale/offline**;
  never authoritative; offline never bypasses governance/authority. On return:
  reconnect → authenticate if needed → resync canonical state → reconcile projections
  → resume stream.
- SSE/event-driven refresh preferred over polling; reconnect with backoff + jitter.

## 11. Shared UI Language

Both clients look like the same product: dark-first, restrained accent, high
information density, strong typography, clear hierarchy, technical-but-human. Epistemic
and authority states use labels + icons + badges + typography + supporting text — **not
color alone** (accessibility). Provenance and evidence are visible wherever a belief is
shown, so the user can answer *"why does Pocket OS believe this?"* and *"what evidence
supports this?"*.

## 12. System Status = Observability, Not Authority

Status view shows online/offline, API health, stream connected/disconnected, last
sync, counts (memory/projects/open loops/pending decisions), governance + ledger
verification + Twin/Shadow last-updated. Informational only.

## 13. Testing Strategy

See `tests_pocketos/` (96 tests, 7 suites) — engines, replay, control-room, features,
auth, rehearsal + rehearsal-control-room. Continuous negative guarantees (unit-tested):

1. A client cannot execute without authorization.
2. A client cannot manufacture governance authorization.
3. A client cannot modify ledger history.
4. A client cannot promote INFERRED → VERIFIED.
5. A client cannot promote PROPOSED → ACCEPTED without the backend transition.
6. A client cannot alter canonical sequence numbers.
7. A client cannot alter canonical hashes.
8. A client cannot bypass the capability/permission lease.
9. SSE is never treated as proof the client caused a mutation.
10. Web and iPhone cannot establish competing state (single backend).

Any new UI or API change ships with the matching test; all suites must stay green.

## 14. Build & Recovery Doctrine

Recover, never reset. Build on the last verified state (checkpoint
`pocketos_checkpoint_2026-09-04`: ledger 25 INTACT, 96/96 green). Small, meaningful
commits. After each milestone: save files, verify build, run tests, record state,
checkpoint. If the environment resets, restore from the durable checkpoint — do not
start over blind. The ledger JSON is the single authoritative durable store; treat it
as the database.
