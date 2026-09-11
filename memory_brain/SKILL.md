# Memory Second Brain — skill definition

**Name:** Memory Second Brain
**Kind:** reference + patterns (ledger-first memory subsystem)
**Runtime:** SQLite + pure stdlib, Python
**Canonical authority:** SAIL `sail_canonical.py` rules (JCS-style, domain-tagged SHA-256)

## When to use this skill
Use when the ecosystem needs a *shared cognitive memory layer* — durable,
provenance-aware, auditable memory that any agent (SAIL, Ralph5 Ultra, Igor,
PocketOS, ACE, KIP, Synapse Ledger, Godview, Software Factory, Manus Prime,
Sovereign Axiom) can read and write through one contract. It is NOT a notes
app, chatbot memory, or a bare vector database.

Recognize it by the asks:
- "ingest this document/conversation/repo into memory"
- "remember X with provenance"
- "what does the ecosystem know / why does it believe it / where did it come from"
- "detect duplicates or contradictions across what we know"
- "give me a grounded context package for query Q"
- "prove the ledger / replay the memory state"

## Non-negotiable invariants (tested in this reference)
1. The ledger (`ledger_events`) is the only authoritative store; all else is derived and rebuildable by replay.
2. Historical memory is immutable — corrections/supersessions/merges/retractions append events; nothing edits or deletes history.
3. All hashing routes through the canonical authority — never hash raw LLM output.
4. The LLM is advisory only; deterministic business logic commits. Governed ops route to the human review queue; APPROVE applies the action.
5. Contradictions are never auto-resolved — unresolved ones stay visible and go to review.
6. Confidence is 4 separated components; importance is independent and cannot override provenance.
7. Same input + same algorithm version => same output (determinism).

## How to run it
See `README.md`. Fastest path:
```
python -m pytest tests/ -q      # 63 invariants
python -c "from memory_brain import MemoryBrain, MemoryAPI; ..."  # quick start
```

## Extension seams
- **New source kinds** -> add an adapter in `ingest.py` producing `RawClaim`s.
- **New memory types** -> register in `models.MEMORY_TYPES`; no architecture change.
- **Contradiction / dedup / consolidate** -> replace local rules with an LLM
  advisory pass, but keep the deterministic commit decision and the
  review gate. LLM output never bypasses governance.
- **Embeddings / Neo4j / Postgres / Redis** -> clean interfaces exist
  (`vector.py`, `graph.py`, schema contract); derived indexes are never
  authoritative over the ledger.

## Package provenance
- Version 1.0.0, built and verified in-sandbox (63 tests passing).
- Mirrors the SAIL canonical/ledger/governance discipline the ecosystem already
  uses — no parallel serializer, no silent mutation, deterministic replay.
