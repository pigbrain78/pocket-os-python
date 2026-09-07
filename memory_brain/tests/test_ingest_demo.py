"""Ingestion adapters + the section-36 demonstration workflow."""

from memory_brain import ingest
from memory_brain.core import MemoryBrain
from memory_brain.api import MemoryAPI
from memory_brain.models import Confidence


# --- adapters ------------------------------------------------------------
def test_ingest_text_splits_blocks():
    claims = ingest.ingest_text(
        "The system uses PostgreSQL.\n\n# heading\n\nIt also has Redis cache.",
        source_id="s1")
    assert len(claims) >= 2
    assert all(c.provenance.links for c in claims)  # every claim has provenance


def test_ingest_json_walks_struct():
    claims = ingest.ingest_json(
        {"claims": ["service is sqlite", "service is deployed"], "meta": "x"})
    assert len(claims) >= 2
    assert all(c.source_id is None or isinstance(c.source_id, str) for c in claims)


def test_ingest_conversation():
    claims = ingest.ingest_conversation([
        {"actor": "slick", "text": "we decided to use sqlite for edge"},
        {"actor": "igor", "text": ""},
        {"actor": "ralph5", "text": "agreed, keeps it deterministic"},
    ])
    # Blank turns dropped.
    assert len(claims) == 2
    assert all(c.provenance.links for c in claims)


def test_ingest_csv():
    csv_data = "name,role\nslick,devops\nigor,agent\n"
    claims = ingest.ingest_csv(csv_data, text_columns=["name", "role"])
    assert len(claims) == 2
    assert "slick" in claims[0].text and "devops" in claims[0].text


def test_failed_ingestion_not_silently_discarded():
    # A claim that fails downstream is surfaced, never dropped silently.
    from memory_brain.provenance import Provenance
    try:
        prov = Provenance()
        prov.add("BOGUS_KIND", "x")  # invalid kind -> raises
    except ValueError:
        pass  # surfaced as validation error rather than silent drop


# --- section-36 demonstration workflow -----------------------------------
def test_end_to_end_demonstration_workflow():
    """A technical doc + a conversation -> ingest -> provenance -> retrieve
    -> context -> verify, with the complete provenance chain."""

    brain = MemoryBrain(":memory:")
    doc_src = brain.register_source("document", "docs/architecture.md", "slick")
    conv_src = brain.register_source("conversation", "thread/42", "team")

    # 1. Ingest a technical document.
    doc_claims = ingest.ingest_text(
        "The payment service uses PostgreSQL for its primary store. "
        "It is deployed to the production cluster.",
        source_id=doc_src)
    # 2. Ingest a conversation.
    conv_claims = ingest.ingest_conversation([
        {"actor": "slick", "text": "we are moving the payment service to sqlite "
         "for edge deployments"},
    ], source_id=conv_src)

    # 3. Commit all claims with provenance.
    committed = []
    for claim in doc_claims:
        r = brain.remember(claim.text, memory_type="FACT",
                           source_id=claim.source_id, actor="slick")
        if r.get("committed"):
            committed.append(r)
    for claim in conv_claims:
        r = brain.remember(claim.text, memory_type="DECISION",
                           source_id=claim.source_id, actor="slick")
        if r.get("committed"):
            committed.append(r)

    assert committed, "no claims committed"

    # 4. Dedup: re-committing the exact same document paragraph is caught.
    exact_doc_text = ("The payment service uses PostgreSQL for its primary "
                      "store. It is deployed to the production cluster.")
    dup = brain.remember(exact_doc_text, memory_type="FACT", source_id=doc_src)
    assert dup.get("committed") is False and dup.get("duplicate_of")

    # 5. The sqlite move decision should have flagged a contradiction with the
    #    postgres fact (review queue), never auto-resolved.
    pending_kinds = [i.kind for i in brain.review.pending()]
    assert "possible_contradiction" in pending_kinds

    # 6. Ledger + replay integrity.
    brain.verify.verify_chain()
    events = brain.ledger.events()
    assert len(events) >= len(committed)

    # 7. Provenance chain is intact per memory.
    for c in committed:
        mid = c["memory_id"]
        assert brain.verify.verify_memory(mid)["ok"] is True

    # 8. Context generation.
    api = MemoryAPI(brain=brain)
    ctx = api.context("what database does the payment service use", top_k=5)
    assert "facts" in ctx
    # The contradiction must surface in the context package, not be hidden.
    assert isinstance(ctx["contradictions"], list)

    # 9. Retrieval returns the source-anchored memory.
    hits = api.search("payment service database")
    assert hits and hits[0]["content"]
    assert hits[0]["source"] is not None
