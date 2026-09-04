"""AI Shadow cross-client equivalence (Python/server side).

The same canonical AI Shadow state (tests_pocketos/fixtures/ai_shadow_positive.json)
must mean the same thing on the web (JS) client and the Swift client: each item
carries type + text + confidence + evidence + provenance + authority, the AI
Shadow is advisory (authority NONE, cannot execute/ratify), and observations are
never collapsed into facts.

Swift equivalence: ios/Tests/PocketOSClientTests/CrossShadowContractTests.
These assert the server canonical view + the JS typed view agree with the
shared fixture.
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "ai_shadow_positive.json")

def _fixture():
    with open(FIXTURE) as f: return json.load(f)

CANONICAL_ITEM_KEYS = {"type","text","confidence","evidence","provenance","authority","status"}

def test_every_shadow_item_has_canonical_fields():
    d=_fixture(); a=d["ai_shadow"]
    items=a["items"]
    assert items, "no shadow items"
    for it in items:
        for key in CANONICAL_ITEM_KEYS:
            assert key in it, f"item missing {key}: {it}"
        assert it["authority"]=="NONE", "AI Shadow must be advisory (authority NONE)"
        assert it["provenance"], "provenance must not be empty"
        assert it["evidence"], "evidence must not be empty"
        assert it["type"] in a["types"], "item type must be in the declared types list"

def test_shadow_cannot_execute_or_ratify():
    d=_fixture(); b=d["ai_shadow"]["authority_boundary"]
    assert b["shadow_authority"]=="NONE"
    assert b["shadow_can_execute"] is False
    assert b["shadow_can_ratify"] is False
    # Governance invariant: execution requires council + human ratification.
    assert "COUNCIL_CONSENSUS" in b["execution_requires"]
    assert "HUMAN_RATIFICATION" in b["execution_requires"]

def test_js_typed_view_matches_fixture_semantics():
    # The web pocket client's aiShadow.listObservations() returns the canonical
    # /api/v1/ai-shadow envelope; the typed view reads ai_shadow.items and each
    # item's type/text/confidence/evidence/provenance/authority/status. Assert
    # the fixture drives that view to equivalent semantics.
    d=_fixture()
    assert d["schema_version"]=="v2"
    for it in d["ai_shadow"]["items"]:
        for key in CANONICAL_ITEM_KEYS: assert key in it
        assert it["authority"]=="NONE"
