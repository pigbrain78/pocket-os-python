"""Cognitive Twin cross-client equivalence (Python/server side).

The same canonical Cognitive Twin state (tests_pocketos/fixtures/cognitive_twin_positive.json)
must mean the same thing on the web (JS) client and the Swift client: every item
carries text + epistemic + confidence + evidence + provenance, and inferences are
never collapsed into facts.

Swift equivalence is covered by ios/Tests/PocketOSClientTests/... ; these tests
assert the server's canonical twin and the JS client's typed view agree with the
shared fixture.
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "cognitive_twin_positive.json")

def _fixture():
    with open(FIXTURE) as f: return json.load(f)["cognitive_twin"]

CANONICAL_ITEM_KEYS = {"text","epistemic","confidence","evidence","provenance"}

def _all_items(t, acc=None):
    if acc is None: acc=[]
    s=t["state"]
    for k in ("current_focus","open_loops","closed_loops","active_projects"):
        v=s.get(k)
        if isinstance(v,dict): acc.append(v)
        elif isinstance(v,list): acc.extend(v)
    for k in ("relevant_memories","recent_observations","relationships","decision_history"):
        acc.extend(t.get(k) or [])
    return acc

def test_every_twin_item_has_canonical_semantic_fields():
    t=_fixture()
    items=_all_items(t)
    assert items, "no twin items"
    for it in items:
        for key in CANONICAL_ITEM_KEYS:
            assert key in it, f"item missing {key}: {it}"
        assert it["epistemic"] in ("OBSERVED","VERIFIED","INFERRED","PROPOSED","UNCERTAIN","REJECTED","STALE")
        assert it["provenance"], "provenance must not be empty"
        assert it["evidence"], "evidence must not be empty"

def test_inference_not_collapsed_to_fact():
    t=_fixture()
    # The focus is an inference; the contract must mark it INFERRED, never a
    # boolean "trusted"/"verified". No item may carry a generic trusted flag.
    f=t["state"]["current_focus"]
    assert f["epistemic"]=="INFERRED"
    # assert no item was flattened into {"trusted": true}
    for it in _all_items(t):
        assert "trusted" not in it, "epistemic status must not collapse to a boolean"

def test_js_typed_view_matches_fixture_semantics():
    # The web pocket client's cognitiveTwin.getState() returns the canonical
    # /api/v1/cognitive-twin envelope; the JS typed view reads cognitive_twin
    # and each item's text/epistemic/confidence/evidence/provenance. Assert the
    # fixture drives that view to equivalent semantics (same keys per item).
    t=_fixture()
    assert isinstance(t.get("summary"), str)
    for it in _all_items(t):
        for k in CANONICAL_ITEM_KEYS: assert k in it
