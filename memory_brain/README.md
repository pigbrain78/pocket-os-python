# Memory Second Brain

A ledger-first, provenance-aware, cryptographically auditable cognitive memory
subsystem. It ingests information, classifies it, tracks provenance, detects
duplicates and contradictions, consolidates related memories, and serves
grounded context packages to ecosystem agents — never silently rewriting
historical memory.

## Design contract

- **The ledger is authoritative.** `ledger_events` is the only authoritative
  store. The searchable memory store, the graph, and the vector index are all
  *derived projections*, rebuildable from the ledger by replay.
- **History is immutable.** Corrections, supersessions, merges, retractions,
  and verifications each append a new event. Historical records stay queryable
  forever. Nothing in the subsystem edits or deletes a written event.
- **Canonicalization is centralized.** Every hash routes through
  `canonical.py` — a JCS-style canonical serializer with domain-tagged SHA-256
  digests (the same authority pattern as SAIL's `sail_canonical`). Never hash
  raw LLM output.
- **Governance before execution.** An LLM is an advisory layer only;
  deterministic business logic makes the final commit decision. Governed
  operations route to the human review queue; an APPROVE decision applies the
  pending action through the same deterministic path. Contradictions are never
  auto-resolved.
- **Confidence is not one number.** Four components are kept separate
  (source / extraction / inference / current). Importance is independent and
  never overrides provenance. Quality exposes every component.
- **Same input, same output.** Every transformation carries an
  `algorithm_version`; replay with the same events and versions yields the same
  derived state.

## Module layout

| Module | Responsibility |
|---|---|
| `canonical.py` | JCS-style canonical JSON + domain-tagged SHA-256 (sole hashing authority) |
| `schema.py` | SQLite DDL, shared SQLite/Postgres schema contract |
| `models.py` | Typed records (Memory, LedgerEvent, Confidence, ...) |
| `ledger.py` | Append-only hash-chained event store (`write`/`replay`/`verify_chain`) |
| `provenance.py` | SOURCE/OBSERVATION/EXTRACTION/INFERENCE/... chain |
| `normalize.py` | Deterministic text normalization (NORMALIZED_HASH) |
| `classify.py` | Memory typing, 4-part confidence, independent importance, staleness |
| `ingest.py` | Modular adapters: text / json / conversation / csv |
| `dedup.py` | 7-signal duplicate detection, auto-merge only on EXACT_DUPLICATE |
| `contradiction.py` | Explicit A CONTRADICTS B analysis; never silent resolution |
| `consolidate.py` | Reproducible consolidation; originals preserved and linked |
| `graph.py` | Derived relationship store (never authoritative) |
| `vector.py` | Deterministic local semantic index (embeddings never authoritative) |
| `retrieve.py` | Hybrid retrieval engine |
| `context.py` | Context Builder -> grounded context packages |
| `governance.py` | Policy gates; deterministic decision rules |
| `review.py` | Human review queue; decisions become ledger events |
| `verify.py` | verify_chain / verify_memory / verify_provenance / verify_context / verify_snapshot |
| `quality.py` | Memory Quality Score with exposed component breakdown |
| `health.py` | Per-subsystem health + observability metrics |
| `api.py` | Typed API surface + integration contract (works headlessly or via FastAPI) |
| `core.py` | `MemoryBrain` facade — the deterministic commit path |

## Quick start

```python
from memory_brain import MemoryBrain, MemoryAPI

brain = MemoryBrain(":memory:")                 # SQLite; use a path to persist
src = brain.register_source("document", "docs/architecture.md", "slick")

# Ingest + remember a fact.
r = brain.remember("The payment service uses PostgreSQL.",
                   memory_type="FACT", source_id=src)
mid = r["memory_id"]

# Provenance + integrity.
brain.verify.verify_chain()                     # no raise => chain intact
brain.verify.verify_memory(mid)                 # recomputes content_hash
brain.explain(mid) if False else None

# A governed supersession proposed by an LLM goes to review, not straight in.
res = brain.remember("The payment service now uses SQLite.",
                     memory_type="FACT", supersedes=mid,
                     actor="llm", is_llm=True)
assert res["requires_review"] is True
brain.apply_review_decision(res["item_id"], "APPROVE", "human-owner")

# Retrieve and build a grounded context package.
api = MemoryAPI(brain=brain)
ctx = api.context("what database does the payment service use")
```

## API surface

The shared contract for ecosystem agents is exposed by `MemoryAPI` (headless)
or via `build_fastapi(...)` when FastAPI is available:

```
remember()  recall()   search()   verify()  explain()
link()      consolidate() supersede() retract() export()  context()
```

## Tests

```
python -m pytest tests/ -q
```

Covers determinism, ledger tamper detection, immutability, replay, dedup,
contradiction (left unresolved), consolidation reproducibility, provenance,
governance (LLM-advisory, human gate), retrieval, context packages, quality,
and the end-to-end demonstration workflow.

## Design notes & tradeoffs

- **No external services by default.** SQLite + pure stdlib keeps the core
  deterministic and testable anywhere. Postgres/Redis/Neo4j/embedding services
  are upgrade paths behind clean interfaces — never required for the core
  invariants to hold.
- **Vector similarity is deterministic** (char-ngram + token features). An
  external embedding model may replace it, but embeddings are only an indexing
  mechanism and never authoritative.
- **In this reference build, `retract` always routes to the review queue** —
  retraction is irreversible, so the human gate is non-negotiable by default.
