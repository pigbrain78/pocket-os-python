"""schema.py -- SQLite schema contract.

Single SQLite file holds the authoritative append-only ledger plus derived
projection tables. The schema contract is shared with a Postgres backend so a
SQLite -> Postgres migration is a backend swap, not a redesign. Derived
projections (vector index, graph, cache, snapshots) are never authoritative;
the ledger is.

Tables (kept minimal):
  ledger_events          -- authoritative append-only hash-chained event stream
  memories               -- current projection of active memory records
  memory_versions        -- immutable snapshot of a memory's state at each change
  memory_sources         -- source records (document, conversation, agent, ...)
  memory_relationships   -- graph edges (SUPPORTS, CONTRADICTS, SUPERSEDES, ...)
  memory_contradictions  -- explicit unresolved / resolved contradiction pairs
  memory_consolidations  -- reproducible consolidation operations
  review_queue           -- human review items (governance gate)
  memory_access_log      -- audit trail of operations
  memory_snapshots       -- deterministic snapshots
"""

from __future__ import annotations

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ledger_events (
    event_id            TEXT PRIMARY KEY,
    timestamp           TEXT NOT NULL,          -- ISO-8601 UTC
    event_type          TEXT NOT NULL,
    payload             TEXT NOT NULL,          -- canonical JSON
    previous_event_hash TEXT,
    event_hash          TEXT NOT NULL UNIQUE,
    algorithm_version   TEXT NOT NULL DEFAULT '1'
);

CREATE TABLE IF NOT EXISTS memories (
    memory_id           TEXT PRIMARY KEY,
    memory_type         TEXT NOT NULL,
    content             TEXT NOT NULL,
    normalized_content  TEXT,
    status              TEXT NOT NULL,          -- ACTIVE / SUPERSEDED / ...
    confidence          REAL NOT NULL,          -- current_confidence
    importance          REAL NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    event_id            TEXT NOT NULL,          -- committing ledger event
    supersedes          TEXT,
    superseded_by       TEXT,
    source_id           TEXT,
    content_hash        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_versions (
    version_id          TEXT PRIMARY KEY,
    memory_id           TEXT NOT NULL,
    status              TEXT NOT NULL,
    content             TEXT NOT NULL,
    confidence          REAL NOT NULL,
    importance          REAL NOT NULL,
    captured_at         TEXT NOT NULL,
    event_id            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_sources (
    source_id           TEXT PRIMARY KEY,
    source_type         TEXT NOT NULL,          -- document / conversation / url / agent / ...
    external_ref        TEXT,                   -- e.g. path, URL, conversation id
    author              TEXT,
    observed_at         TEXT,
    raw_hash            TEXT,
    extra               TEXT                    -- canonical JSON of optional fields
);

CREATE TABLE IF NOT EXISTS memory_relationships (
    rel_id              TEXT PRIMARY KEY,
    from_memory         TEXT NOT NULL,
    to_memory           TEXT NOT NULL,
    rel_type            TEXT NOT NULL,          -- SUPPORTS / CONTRADICTS / SUPERSEDES / DERIVED_FROM / ...
    created_at          TEXT NOT NULL,
    event_id            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_contradictions (
    contradiction_id    TEXT PRIMARY KEY,
    memory_a            TEXT NOT NULL,
    memory_b            TEXT NOT NULL,
    status              TEXT NOT NULL,          -- UNRESOLVED / RESOLVED
    resolution          TEXT,                   -- SUPERSEDED / CONTRADICTED / BOTH_ACTIVE / RETRACTED
    decided_memory      TEXT,                   -- which side kept active (if any)
    detected_at         TEXT NOT NULL,
    resolved_at         TEXT,
    event_id            TEXT NOT NULL,
    detail              TEXT
);

CREATE TABLE IF NOT EXISTS memory_consolidations (
    consolidation_id    TEXT PRIMARY KEY,
    input_memories      TEXT NOT NULL,          -- canonical JSON list
    output_memory       TEXT NOT NULL,
    algorithm_version   TEXT NOT NULL,
    agent               TEXT,
    created_at          TEXT NOT NULL,
    confidence          REAL,
    reason              TEXT,
    event_id            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_queue (
    item_id             TEXT PRIMARY KEY,
    kind                TEXT NOT NULL,          -- contradiction / merge / low_confidence / sensitive / ...
    ref_json            TEXT NOT NULL,          -- canonical JSON describing the item
    status              TEXT NOT NULL,          -- PENDING / APPROVED / REJECTED / MERGED / ...
    created_at          TEXT NOT NULL,
    decided_at          TEXT,
    decided_by          TEXT,
    decision_event_id   TEXT
);

CREATE TABLE IF NOT EXISTS memory_access_log (
    log_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    actor               TEXT,
    operation           TEXT NOT NULL,
    target              TEXT,
    timestamp           TEXT NOT NULL,
    detail              TEXT
);

CREATE TABLE IF NOT EXISTS memory_snapshots (
    snapshot_id         TEXT PRIMARY KEY,
    ledger_position     TEXT,                   -- last event_id covered
    memory_count        INTEGER NOT NULL,
    graph_state_hash    TEXT,
    index_state_hash    TEXT,
    memory_state_hash   TEXT,
    created_at          TEXT NOT NULL,
    algorithm_versions  TEXT
);
"""


def load_schema(conn) -> None:
    """Apply the schema to an open sqlite3 connection (idempotent)."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()
