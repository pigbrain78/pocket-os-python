"""Verification, quality, and provenance tests."""

import pytest

from memory_brain.core import MemoryBrain
from memory_brain import quality
from memory_brain.models import Confidence
from memory_brain.provenance import Provenance
from memory_brain.verify import VerificationError
from memory_brain.api import MemoryAPI


# --- verification --------------------------------------------------------
def test_verify_chain_ok_on_fresh(brain):
    brain.remember("a", memory_type="FACT")
    assert brain.verify.verify_chain()["ok"] is True


def test_verify_memory_recomputes_hash(brain):
    mid = brain.remember("verifiable content", memory_type="FACT")["memory_id"]
    rep = brain.verify.verify_memory(mid)
    assert rep["ok"] is True
    assert rep["memory_id"] == mid


def test_verify_memory_detects_hash_tamper(brain):
    mid = brain.remember("tamper target", memory_type="FACT")["memory_id"]
    # Silently alter stored content (simulating a tampered projection).
    brain.conn.execute("UPDATE memories SET content='modified' WHERE memory_id=?",
                       (mid,))
    brain.conn.commit()
    with pytest.raises(VerificationError):
        brain.verify.verify_memory(mid)


def test_verify_provenance_requires_source(brain):
    mid = brain.remember("has a source", memory_type="FACT",
                         source_id=brain.register_source("doc", "d.md"))["memory_id"]
    assert brain.verify.verify_provenance(mid)["ok"] is True


# --- quality -------------------------------------------------------------
def test_quality_breakdown_exposed():
    br = quality.score(
        {"content_hash": "abc", "confidence": 0.8, "source_id": "s1",
         "updated_at": "2026-09-07T00:00:00Z"},
        verified=True, contradicts_any=False, retrieved_ok=4, retrieved_total=5)
    d = br.to_dict()
    assert "overall_quality" in d
    # Every component is independently exposed, never hidden.
    for key in ("provenance_quality", "evidence_quality", "consistency",
                "confidence", "freshness", "retrieval_reliability"):
        assert key in d


def test_verified_higher_than_unverified():
    base = {"content_hash": "x", "confidence": 0.8, "source_id": "s",
            "updated_at": "2026-09-07T00:00:00Z"}
    v = quality.score(base, verified=True).to_dict()
    u = quality.score(base, verified=False).to_dict()
    assert v["provenance_quality"] > u["provenance_quality"]


# --- confidence is four components, never collapsed ----------------------
def test_confidence_components_preserved():
    conf = Confidence(source=0.9, extraction=0.8, inference=0.6)
    d = conf.to_dict()
    assert d["source_confidence"] == 0.9
    assert d["extraction_confidence"] == 0.8
    assert d["inference_confidence"] == 0.6
    assert d["current_confidence"] == round(0.5 * 0.9 + 0.3 * 0.8 + 0.2 * 0.6, 4)


def test_inference_not_confused_with_source():
    # A pure inference (low source confidence, high inference) must NOT read
    # as a verified source fact.
    conf = Confidence(source=0.1, extraction=0.2, inference=0.9)
    assert conf.source < 0.3  # source component stays low
    assert conf.inference == 0.9


# --- provenance kinds ----------------------------------------------------
def test_provenance_never_presents_inference_as_fact():
    p = Provenance()
    p.add("SOURCE", "design doc", actor="slick")
    p.add("OBSERVATION", "read")
    p.add("INFERENCE", "concluded X follows from Y")
    kinds = [l.kind for l in p.links]
    assert "INFERENCE" in kinds
    assert p.verified is False  # no VERIFICATION link yet


def test_provenance_verified_flag():
    p = Provenance()
    p.add("SOURCE", "audit", actor="human")
    p.add("VERIFICATION", "independently confirmed", actor="human")
    assert p.verified is True


# --- api contract ---------------------------------------------------------
def test_api_integration_contract():
    api, brain, src = None, MemoryBrain(":memory:"), None
    src = brain.register_source("document", "spec.md", "slick")
    api = MemoryAPI(brain=brain)
    # remember
    r = api.remember("the api layer exposes a contract", memory_type="FACT",
                     source_id=src)
    assert r["committed"] is True
    mid = r["memory_id"]
    # verify / explain / search
    assert api.verify("chain")["ok"] is True
    assert api.verify("memory", memory_id=mid)["ok"] is True
    expl = api.explain(mid)
    assert expl["memory"]["content"] == "the api layer exposes a contract"
    hits = api.search("api contract")
    assert hits and hits[0]["memory_id"] == mid
    # context
    ctx = api.context("api layer contract")
    assert "context_hash" in ctx
    # export / health
    blob = api.export()
    assert '"memories"' in blob or "memories" in blob
    assert api.health()["health"] in ("ok", "degraded")
    assert api.integrity()["ok"] is True
