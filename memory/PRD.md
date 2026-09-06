# Pocket OS — PRD

## Vision
Pocket OS is a **Cognitive Operating System** — not another note app. Everything captured becomes connected. Knowledge compounds. AI advises, humans decide, every decision is traceable.

## MVP Scope (all 12 differentiators as simplified, coherent layers)
**Phase 1 — Capture**: Universal capture (text), Cognitive Timeline, AI Concept Classification (Gemini 3 Flash), Living Knowledge Graph (nodes + edges), Memory Growth ring animation.
**Phase 2 — Understand**: Decision DNA (downstream lineage), Idea Evolution (Git-like versions), Memory Gravity score per note.
**Phase 3 — Think**: Personal AI Council (5 specialist agents), AI Shadow (behavioral insights), Cognitive Twin (reasoning from user history).
**Phase 4 — Reflect**: Memory Health dashboard (Apple-Health rings), Knowledge ROI (projects/tasks/revenue per note), Thinking Replay endpoint.
**Bonus (from your feedback)**: Cognitive Operating Console home (brain activity, opportunities, focus, Knowledge Compounding Score).

## Stack
- Frontend: Expo Router (SDK 54), React Native, react-native-svg, expo-blur, reanimated.
- Backend: FastAPI + MongoDB (motor).
- Auth: JWT email/password (bcrypt).
- LLM: Gemini 3 Flash via `emergentintegrations` (EMERGENT_LLM_KEY).

## Screens
- Auth: welcome / login / register (seeded demo user).
- Tabs: **Console** (home OS dashboard), **Timeline**, **Graph**, **Health**, **Genome**.
- Detail: `/note/[id]` (gravity, AI Council carousel, Idea Evolution timeline, Decision DNA cards, Knowledge ROI grid), `/note/new` (capture → Memory Strengthened reveal).

## Endpoints (`/api/*`)
`auth/register`, `auth/login`, `auth/me`, `notes` (CRUD-lite), `notes/:id/council`, `notes/:id/evolve`, `notes/:id/roi`, `timeline`, `graph`, `decisions`, `health-dashboard`, `console`, `shadow`, `twin/predict`, `replay/:id`, `seed-demo`.

## Wow moments delivered
- **Capture reveal**: Memory Strength before → after with animated ring, extracted concepts, new connections.
- **Timeline replay**: Grouped by day, per-event colored icons + vertical line, memory strength bars.
- **Living Graph**: SVG canvas showing note & concept nodes with edges; concept chips selectable.
- **AI Council**: 5 colored agent cards streamed from Gemini for any note.
- **Memory Health**: 3 concentric rings + overall score + metric tiles.
- **Cognitive Twin**: user asks a question, answered strictly from their own history.
- **Pocket Score / Knowledge Compounding**: on the Console home.

## Business enhancement
Every note carries **Attributed Revenue + Produced Projects/Tasks/Articles/Proposals** on the ROI card — making knowledge quality visible as a monetizable asset (naturally supports a Pro tier that surfaces ROI analytics).


## Phase 3 — Council Debate Engine (Jun 2026)
Multi-signal governance escalation replaces the naive "consensus.confidence < 0.65" trigger with an eight-signal escalator: `low_confidence`, `agent_disagreement (stddev>0.25)`, `high_risk`, `governance_domain` (security/governance/architecture/irreversibility/expense keyword match), `prior_decision_conflict`, `insufficient_evidence`, `novel_decision`, and `conflicting_positions`.

When ANY signal fires, a three-turn debate is executed:
1. **Critic (Claude Sonnet 4.6)** — argues against the majority verdict.
2. **Defender (GPT-5.4)** — steelmans the majority, listing required conditions.
3. **Synthesizer (Gemini 3 Flash)** — emits strict-JSON synthesis with `resolution`, `conditions[]`, `escalate`, `synthesis_position`, `confidence`.

Every turn is written to the Immutable Event Ledger as its own hashed event, and the final Synthesis Proposal carries a canonical `synthesis_hash` (SHA-256 over triggers + turn hashes + synthesis payload). Synthesis Proposals remain **unratified** until a human ratifies (`POST /api/synthesis/{sid}/ratify`) or rejects (`POST /api/synthesis/{sid}/reject`). Ratification re-computes Decision DNA for every decision bound to the note so that `reasoning_hash` cryptographically covers the ratified synthesis, and adds a `synthesis_ratified` event to the Ledger. `reasoning_source` on the DNA card becomes `synthesis`, precedence: **synthesis > consensus > raw_council**.

### New endpoints
`GET /api/notes/{id}/debate/triggers`, `GET /api/notes/{id}/debate/latest`, `POST /api/notes/{id}/council/debate` (multi-turn), `POST /api/synthesis/{sid}/ratify`, `POST /api/synthesis/{sid}/reject`.

## Round 5 — Contradiction Detection + Auditor Bundle Export (Jun 2026)
Extended `prior_decision_conflict` from count-based to **semantic contradiction detection**. On every new consensus we compare the new note's concepts against every RATIFIED synthesis in the user's workspace using token-level Jaccard + containment overlap; when overlap exceeds 20% AND positions genuinely oppose (APPROVE/CONDITIONAL_APPROVE ↔ REJECT), the system records a **non-destructive** `contradictions` record + `contradiction_detected` ledger event. Rejected and unratified syntheses are explicitly excluded — only ratified precedents are authoritative. Neither side is mutated.

### New endpoints
`GET /api/notes/{id}/contradictions`, `GET /api/decisions/{id}/contradictions`, `POST /api/contradictions/{cid}/resolve`, `GET /api/ledger/export`.

### New UI
- `<note/[id].tsx>` **Contradictions** card between Consensus and Cognitive Router: ⚡ "Contradicts Decision #N" chip, position-swap badges, shared concept chips, overlap/jaccard/containment metrics, tap opens prior note, "Mark resolved" preserves evidence.
- `<ledger.tsx>` **Export** button in header → downloads a self-contained JSON bundle containing `manifest`, `head`, `ledger.jsonl`, third-party `verify.py`, and `README.md`. Independent verification: recomputes SHA-256 chain against declared head_hash without trusting the app.

### Guarantees
- 30 backend tests pass (4 new for contradictions + export).
- Independent verification (`python3 verify.py`) returns exit 0 against a live-exported bundle.
- Ledger stays verified through all new contradiction/resolution events.


## Round 6 — Credibility Hardening Pass (Jun 2026)
Targeted metric-credibility patches. NO parallel subsystems created; existing architecture preserved.
- **Decision metrics** — removed `random.randint` fabrication in `/api/decisions`. `referenced_notes` now counts real concept-overlap peers, `influenced_agents` = distinct council agents who reviewed the source note, `affected_projects`/`produced_tasks` default to 0 (attributed only when downstream evidence exists).
- **Cognitive DNA** — returns `confidence`, `evidence_count`, `counter_signal` per trait; bounded 20-95% (no false 99% scores); explicit disclaimer that it's a derived behavioral model, not a psychological assessment.
- **Cognitive Twin** — restructured to return `{prediction, confidence, evidence[], evidence_count, counter_signal, reasoning, kind: "MODEL PREDICTION"}`. Strict-JSON Gemini prompt with confidence ceiling of 0.85. Genome tab now renders the prediction with confidence pill, reasoning, counter-signal, and the exact evidence items reasoned from.
- **AI Shadow** — labeled `DESCRIPTIVE MODEL` (distinct from Twin's `MODEL PREDICTION`).
- **Seed data** — `revenue`/`produced_*` fields default to 0 instead of random. No more fake activity.
- **Test-data cleanup** — new `POST /api/admin/cleanup-test-notes` surgically purges recognizably synthetic artifacts (coffee notes, TEST_ prefixes, my own earlier test notes). Cascades to related state; append-only ledger events untouched.

Backend tests still green (30/30). No new subsystems, no duplicate scoring engines, no parallel state.



## Session +N — Emergency Admin Password Reset (recovery)
Owner-lockout recovery path for locked-out account holders in production.
- **New endpoint** `POST /api/auth/admin/reset-password` — guarded by `ADMIN_RESET_TOKEN` env var (constant-time `hmac.compare_digest`). If env var unset/empty → 503 (safe default off).
- Rate-limited to 10 attempts / 60 s (in-memory sliding window).
- Rejects passwords < 8 chars.
- Creates the account if the email does not exist (recovery from data loss).
- Writes an `admin_password_reset` event to the Immutable Event Ledger for every successful reset.
- Response returns a fresh JWT so the owner can call the API directly if the app UI is unreachable.

### Runbook — locked out of production
1. Set `ADMIN_RESET_TOKEN=<long random string>` in production env, redeploy.
2. `curl -X POST https://<prod>/api/auth/admin/reset-password -H "Content-Type: application/json" -d '{"email":"you@x.com","new_password":"<new>","admin_token":"<value from env>"}'`
3. Sign in to the app with the new password.
4. Remove `ADMIN_RESET_TOKEN` from env (or set to empty) + redeploy to disable the endpoint again.

## Session +N — Forgot Password (Emergent Resend email flow)
Real, no-lockout password recovery so admin reset is no longer needed.
- **`POST /api/auth/forgot-password`** — accepts `{email}`. **Enumeration-safe**: known and unknown emails return byte-identical `{ok:true, detail:"If an account exists for that email, a reset code has been sent."}` at 200. Rate-limited to 5 requests/hour/email. Creates a `password_resets` record (id, email, user_id, hashed code, created_at, expires_at, attempts, used) only for real users.
- **`POST /api/auth/reset-password`** — accepts `{email, code, new_password}`. 6-digit numeric codes, SHA-256 hashed at rest (server-side pepper via JWT_SECRET), 15-minute TTL, single-use, ≤5 wrong attempts before auto-invalidation. Returns `{ok, token, user}` and writes a `password_reset_completed` event to the Immutable Event Ledger.
- **Email delivery**: Emergent-managed Resend proxy (`https://integrations.emergentagent.com`, `X-Email-Key` header). Sender display name `EMAIL_FROM_NAME=Pocket OS`. Template is server-side (callers only supply the email ID, per G4); passes the full playbook guardrail gate (`_assert_safe_email`) — no `<form>/<input>`, only https absolute URLs, no shorteners, no IP literals, no credential-ask phrases.
- **Preview graceful degradation**: `EMERGENT_EMAIL_KEY` is intentionally empty in preview → `send_email` no-ops and logs a warning instead of raising. Real email starts flowing after the next deploy (platform auto-provisions the key).
- **Frontend**: "Forgot password?" link added to `/auth/login` (testID `forgot-password-link`). New screens `/auth/forgot-password` (request code, enumeration-safe confirmation) and `/auth/reset-password` (email + 6-digit code + new password + confirm; on success auto-logs in via `useAuth().login` and routes to `/(tabs)/console`).
- **Tests**: `/app/backend/tests/test_forgot_password.py` (24 tests, serial `-n 0`).

## Session +N — Replay Documentary Engine (Timeline scrubber)
Reality-as-of-any-moment folded from the append-only ledger. State is NEVER
read from the current derived collections — it is a pure function of the
ledger head prefix, which makes the ledger's canonicity observable.

- **`GET /api/replay/bounds`** — returns `{earliest, latest, now}` (ISO-8601) so the client scrubber knows its slider domain.
- **`GET /api/replay?at=<iso>`** — folds every event with `created_at <= at`, applying pure deltas to an empty state accumulator. Response: `{at, now, bounds, state, events_seen, events_after, recent_events[]}`. State has 14 counters: notes_created, notes_evolved, concepts_extracted, connections_made, memory_strength (latest observation wins), council_runs, debates_started, syntheses_proposed/ratified/rejected, decisions_made, operations_run, open_contradictions (min-clamped at 0), resolved_contradictions.
- **`at` missing or malformed** → gracefully defaults to server `now` (never 400/500).
- **Frontend**: New `<TimeScrubber>` component uses `PanResponder` with delta-from-grant math (`gestureState.dx`) so drags feel identical on mobile touch and web mouse; `measureInWindow`-based fallback for track-tap. Timeline tab now renders a "REALITY AS OF" card above the list with a 6-tile metric grid, the scrubber, and a footer showing `events_seen / events_after`. Events with `created_at > at` are dimmed to 30% opacity and tagged "· not yet" — the "future" is visible but visibly not-yet.
- **LIVE detection**: `events_after === 0`. Initial load and Return-to-Now omit the `at` param to avoid millisecond-truncation excluding the last event.
- **Tests**: `/app/backend/tests/test_replay.py` — 27 tests including client-side re-fold cross-check that recomputes all 14 counters from the raw 466-event ledger and asserts they match the server byte-for-byte at 5 different timestamps. Full frontend E2E via testing_agent (drag → assert counters shrink; return-to-now → assert counters restore).
