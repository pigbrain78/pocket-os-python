# Plan: Pocket OS — iPhone App + Web Control Room (Single Canonical System)

## Goal

Build Pocket OS as **one system with two clients** — a canonical backend/core, a deep web control room, and a native iPhone cognitive cockpit — where both clients are projections of the **same authoritative Pocket OS state**. No website↔iPhone sync, no competing source of truth, no client-side authority. The constitutional invariant holds everywhere: *memory informs, never authorizes; LLM proposes, council evaluates, governance authorizes, human ratifies, kernel executes, ledger records.*

Deliverables this build produces:
1. A verified, running canonical Pocket OS core over `/api/v1` + `/api/stream` (recovered from the last verified state, never reset).
2. A web control-room interface covering all specified domains.
3. An iPhone client: Linux-compilable `PocketOSClient` + projection layers **plus** the full SwiftUI cockpit authored and Apple-gated for Xcode.
4. `docs/POCKETOS_APP_ARCHITECTURE.md` (anti-drift contract) and a committed checkpoint.

## Assumptions

- **Run surface = this cloud sandbox.** The system reminder fixes this lane to the sandbox; I cannot reach a Mac this turn. Consequences, stated plainly: the sandbox **can** build and verify the canonical core, the web control room, and the Swift projection/model/client layers (Swift 6.0.3 compiles on Linux). It **cannot** compile the actual SwiftUI views (requires Xcode) or touch a real iPhone. The SwiftUI layer is therefore authored, Apple-gated (`#if canImport(SwiftUI)`), and delivered against `ios/README.md` so a later Local/Xcode session compiles and runs it. The plan keeps iOS UI genuinely buildable as the documented terminal step, not a stub.
- **Source of truth = durable verified checkpoint.** GitHub reports **not connected** in this sandbox and no token/`gh` login exists, so I cannot clone the private `pigbrain78/pocket-os-python` here. Per the "never reset / recover from last verified state" directive, the build restores `pocketos_checkpoint_2026-09-04` (manifest + README + source; verified state era commit `fcd661b`, ledger 25 INTACT, Swift 33 / Python 114 / browser 14 green) and continues surgically from it. This contradicts nothing in the prompt — it is the available verified state.
- **Backend state is authoritative; clients are pure projections.** Client state = UI state, cache, projection only. Clients never supply sequence numbers, hashes, ledger positions, governance/capability/authority claims, or canonical timestamps; the server validates every field it accepts and owns the rest.
- **No new domains invented.** Where this prompt's screens exceed what the verified backend exposes (e.g. Memory Graph, Discovery, Governance as live surfaces), the UI renders the **canonical projection the API returns** or a clearly-labeled empty/derived state — it never fabricates authoritative data. New read surface may be added to the backend as versioned `/api/v1` endpoints only if needed and contract-guarded.
- **No UI-initiated authority.** Every screen shows proposals/recommendations; the only human acts are the server-permitted `ratify`/`reject`. There is no execute verb in any client.
- **Language:** plan/architecture is English per prior work and the prompt.

## Phase 1 — Foundation (recover + verify + shared contract)

Recover, never reset. In order:
1. Restore the checkpoint into the project tree; confirm the canonical modules exist (ledger core, governance/constitutional runtime, cognitive-twin fold, ai-shadow fold, seed data). If prior source files are missing after a reset, restore authoritative modules from the durable checkpoint **before** building anything on them — never reconstruct/guess their APIs.
2. Run the read-only persistence audit the standing instructions require **before any development**: ledger state file INTACT, full test suites green (Python 114, browser 14; Swift 33 if the `ios/` tree is present), auth security, subsystem health. Only proceed on a green result; report the exact state.
3. Confirm/regenerate the committed OpenAPI contract snapshot `docs/POCKETOS_CLIENT_API.openapi.json` (scoped to `/api/v1` only) and the drift-guard test are green.
4. Confirm the event envelope shape and `/api/stream` SSE semantics the clients will consume.
5. **Milestone commit:** `pocketos: app foundation`.

## Phase 2 — Architecture contract (anti-drift)

1. Author `docs/POCKETOS_APP_ARCHITECTURE.md` covering: canonical source of truth; web architecture; iPhone architecture; the `/api/v1` boundary; event architecture (SSE as observation, never client causation); Cognitive Twin + AI Shadow projection contracts; governance boundary; the full authority chain (propose→council→ratify→execute→record); data ownership; synchronization; offline behavior; security boundary; testing strategy; the "no duplicate source-of-truth" rule.
2. Freeze the shared client contract on one concept set: Memory, Project, Decision, Evidence, Event, Cognitive Twin, AI Shadow, Epistemic Status, Provenance, Governance, Capability, Ledger — identical meaning on web and iPhone. **No `WebMemory` vs `iPhoneMemory`.**

## Phase 3 — Canonical core depth (server-authoritative projections)

Add only what both clients consume, as versioned, contract-guarded `/api/v1` reads — never execute routes:
1. Verify/confirm the canonical read projections the control room needs are served: `status`, `memory`, `cognitive-twin`, `ai-shadow`, `decisions`, `ledger`, `replay`, `evidence` (the 8 canonical responses already fixture-snapshotted), plus the aggregates the cockpit needs (projects, open loops, governance state, evidence verification).
2. Add any missing **read** endpoints for Projects / Open Loops / Governance / Evidence inspection only if the existing contract lacks them; each is a fold over the same ledger, deterministically, with epistemic labels preserved. Do not invent a second projection path.
3. Keep command surface at `propose`/`ratify`/`reject` only; ratification is a recorded ledger event and execute re-derives authority from the ledger every time.
4. Re-run the boundary test suite (proves: no execute route, epistemic preservation, no web-only fields, normalized 401/403/404, governance-bypass impossible, client cannot supply ledger position). **Milestone commit:** `pocketos: canonical depth`.

## Phase 4 — Web Control Room

Build as clients of the canonical API through the existing `pocket` client abstraction (UI → `PocketClient` → transport → API; no raw `fetch`/HTTP outside the transport layer). Dark-first, high-density, restrained accent, shared epistemic visual language (label+icon+badge, never color alone):
1. **Overview** — cognitive state, current focus (renders INFERRED as "appears to be…"), active projects, open loops, AI Shadow, recent memories/events, live SSE status.
2. **Memory** — browser/detail with provenance, epistemic status, confidence, evidence refs, related entities.
3. **Cognitive Twin** — advisory fold; VERIFIED clearly distinct from INFERRED; no Twin reasoning in the UI.
4. **AI Shadow** — observations/patterns/proposals, each with explicit **AUTHORITY: NONE · CAN EXECUTE: NO · CAN RATIFY: NO**.
5. **Projects** — status, activity, linked memories, open loops, decisions, evidence, dependencies, recommendations.
6. **Open Loops** — inspectable; never auto-executes.
7. **Decisions** — PROPOSAL / AUTHORIZATION / EXECUTION / EVIDENCE-OF-EXECUTION never conflated.
8. **Governance** — pending proposals, required approvals, capability leases, rejected items; human ratification path surfaced server-permitted.
9. **Evidence** — "why does Pocket OS believe this?" with record, provenance, sequence, hashes, verification state.
10. **Ledger** — append-only event history, hash-chain relationship, verification status; read-only, no client-side ledger.
11. **Graph / Discovery / Capabilities / System** — graph as projection of backend relationships (no decorative edges); discovery retains epistemic labels; system status = observability, not authority.
12. Responsive web (desktop/laptop/tablet/mobile browser), accessibility (keyboard nav, contrast, reduced motion, non-color state), global search across entities returning type + epistemic + confidence + provenance.
13. Re-run web + browser suites. **Milestone commit:** `pocketos: control room`.

## Phase 5 — iPhone Cognitive Cockpit (projection + SwiftUI, Apple-gated)

Architecture already frozen and verified cross-client: SwiftUI View → Observable ViewModel → `PocketTwinProjection`/`PocketShadowProjection` → `PocketOSClient` → `/api/v1` + `/api/stream`. No Pocket OS business logic in SwiftUI.
1. **Foundation (Linux-compilable):** confirm/complete `PocketOSClient` (actor `PocketTransport`: HTTP, bearer-session auth, `x-request-id`, normalized `PocketAPIError` distinguishing NETWORK/AUTH/AUTHORIZATION/VALIDATION/SERVER/STALE/CONFLICT/UNKNOWN) and models mirroring the contract exactly (full `EpistemicStatus`, AI Shadow authority NONE, no execute verb). Re-run Swift suite green.
2. **Cockpit screens (authored, `#if canImport(SwiftUI)`):** HOME (Cognitive State / Current Focus / Active Projects / Open Loops / AI Shadow / Recent Memories / Recent Events), MEMORY, PROJECTS, TWIN, SHADOW, DECISIONS, GOVERNANCE, EVIDENCE, GRAPH, SETTINGS — native SwiftUI patterns, glanceable hierarchy, shared epistemic + authority visual language, Dynamic Type + VoiceOver, secure credential storage, voice-first capture flow with distinct Captured/Processing/Memory proposed/Memory accepted states.
3. **Live + resilience:** consume `/api/stream`; SSE is an observation, not proof the client caused a mutation; reconnect with exponential backoff + jitter then resync authoritative state, rebuild projections, resume. Offline: cached projections clearly labeled stale, never authoritative, governance/authority never bypassed, server wins conflicts.
4. Verify Swift projection/model suites green on Linux; the SwiftUI screens are delivered to Xcode per `ios/README.md`. **Milestone commit:** `pocketos: cognitive cockpit (iOS)`.

## Phase 6 — Verification gate

1. Full suites: Python (unit/contract + browser), Swift (projection/model), drift-guard, boundary, control-room, governance.
2. Critical negative tests re-run and green: no execution without authorization; no client-manufactured governance; no ledger-history mutation; no INFERRED→VERIFIED promotion by a client; no PROPOSED→ACCEPTED without the backend transition; no client-set sequence/hashes; capability lease unbounded by client; SSE never treated as client causation; web and iPhone cannot establish competing state.
3. Ledger verification (append-only, hash-chain) confirms INTACT; existing canonical fixtures untouched.
4. Update the durable checkpoint; write release notes with exact run/verify commands. **Milestone commit:** `pocketos: verified checkpoint`.

## Risks & Open Questions

- **GitHub unreachable this lane** — the private repo cannot be cloned from this sandbox (not connected, no token). Build proceeds from the durable verified checkpoint instead; nothing is reset or recreated. If you want the build against the live repo head, that must happen in a conversation with GitHub access (Local, or this thread with access granted).
- **No Xcode here** — the iPhone SwiftUI screens are authored and Apple-gated but cannot be compiled or UI-tested in this sandbox. True iPhone build/run is the documented terminal step in a Local/Xcode session against the same `ios/` package. Until then "iPhone app builds" is not claimed as verified — it is delivered to Xcode, which is the honest boundary.
- **Scope breadth vs verified backend** — the prompt lists surfaces (Graph, Discovery, Capabilities, Contradiction UI, Cognitive Timeline, Notifications) that the verified backend may not yet fully expose. The plan renders canonical projections and never fabricates authority; where the backend lacks a surface, that surface is added as a versioned read only, or clearly presented as unsupported — never invented client-side.
- **What "the existing Pocket OS contracts" are** must be confirmed against the restored source, not assumed from memory. Any conflict between this prompt and the real implementation → stop and reconcile, never invent a third behavior.
- **Convergence doctrine** — the plan consolidates onto one canonical core rather than spawning parallel subsystems, honoring the standing architectural preference.

## Execution Checklist

- [x] Recover the verified checkpoint and run the read-only persistence audit (ledger INTACT, suites green) before any change. — Recovering the verified Pocket OS checkpoint and running the read-only persistence audit — Checkpoint recovered; audit green: ledger 25 records chain-verified INTACT, server healthy, 96/96 tests pass
- [x] Author the anti-drift architecture doc and freeze the shared web+iPhone contract. — Recovering the verified Pocket OS checkpoint and running the read-only persistence audit — Anti-drift architecture doc authored from the real implementation; shared web+iPhone contract frozen on the canonical /api surface
- [x] Add any missing server-authoritative read projections; keep command surface to propose/ratify/reject. — Auditing the canonical core: confirming read projections already suffice and no execute leakage exists before any new surface — Canonical core verified complete: all control-room read domains served by /api; mutations auth-gated (401); no execute route; no new backend surface required
- [~] Build the full web control room as a pure client of the canonical API. — Expanding the web control room across the full canonical domain set on the existing console
- [~] Build the iPhone projection + model layers and author the Apple-gated SwiftUI cockpit for Xcode. — Building the iPhone layer: project core + models + projections as Linux-compilable Swift, then the Apple-gated SwiftUI cockpit and Xcode runbook
- [ ] Run the full verification gate (incl. critical negative tests) and checkpoint the result.
