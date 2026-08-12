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
