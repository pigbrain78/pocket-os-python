"""Consolidation engine tests: reproducible, originals preserved, links kept."""

from memory_brain.core import MemoryBrain
from memory_brain import consolidate as cons_mod


def test_consolidation_deterministic():
    spec = cons_mod.ConsolidationSpec(
        memory_ids=["m1", "m2"], contents=["a", "b"], reason="merge")
    r1 = cons_mod.run(spec)
    r2 = cons_mod.run(spec)
    assert r1.consolidation_id == r2.consolidation_id
    assert r1.output_content == r2.output_content


def test_consolidation_preserves_originals(brain):
    a = brain.remember("memory A", memory_type="FACT")["memory_id"]
    c = brain.remember("memory C", memory_type="FACT")["memory_id"]
    out = brain.consolidate([a, c], "consolidate related")
    assert out["consolidated"] is True
    # Originals still ACTIVE and queryable.
    assert brain.get(a)["status"] == "ACTIVE"
    assert brain.get(c)["status"] == "ACTIVE"
    # Output links to inputs via DERIVED_FROM edges.
    edges = brain.graph.edges("DERIVED_FROM")
    assert len(edges) >= 2
    assert all(e["rel_type"] == "DERIVED_FROM" for e in edges)


def test_consolidation_records_operation():
    b = MemoryBrain(":memory:")
    a = b.remember("x", memory_type="FACT")["memory_id"]
    c = b.remember("y", memory_type="FACT")["memory_id"]
    b.consolidate([a, c], "merge pair", actor="slick")
    row = b.conn.execute(
        "SELECT * FROM memory_consolidations").fetchone()
    assert row is not None
    assert row["agent"] == "slick"
    assert row["event_id"]
    # Ledger carries the consolidation event.
    assert any(e.event_type == "MEMORY_CONSOLIDATED"
               for e in b.ledger.events())
