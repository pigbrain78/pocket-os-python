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
