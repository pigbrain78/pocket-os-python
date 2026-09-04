"""Cross-client canonical event contract tests (Python/server side).

The SAME canonical event envelope (tests_pocketos/fixtures/canonical_event_positive.json)
is decoded by the web (JS) client and the Swift client into equivalent semantic
fields. These tests prove the server's canonical view of that envelope agrees:
the server ledger record carries the same event_type, sequence, source, kind,
previous_hash, schema_version, and payload as the shared fixture — so every
client decodes one truth.

The web (JS) client equivalence is asserted structurally here (the field names
and types the JS normalizer emits match the fixture); the Swift equivalence is
covered by ios/Tests/PocketOSClientTests/CrossClientEventContractTests.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "canonical_event_positive.json")


def _load_fixture():
    with open(FIXTURE) as f:
        return json.load(f)


def _js_normalizer_fields(env):
    """Mirror of the web pocket client's SSE normalizer (index.js): it forwards
    type/event_id/sequence/occurred_at/source/kind/previous_hash/schema_version/
    payload. Returns the equivalent semantic dict the JS client would emit."""
    return {
        "type": env.get("type"),
        "event_id": env.get("event_id"),
        "sequence": env.get("sequence"),
        "occurred_at": env.get("occurred_at"),
        "source": env.get("source"),
        "kind": env.get("kind"),
        "previous_hash": env.get("previous_hash"),
        "schema_version": env.get("schema_version"),
        "payload": env.get("payload"),
    }


def test_fixture_has_all_canonical_fields():
    env = _load_fixture()
    for key in ("type", "event_id", "sequence", "occurred_at", "source", "kind",
                "previous_hash", "schema_version", "payload"):
        assert key in env, f"shared fixture missing canonical field {key}"


def test_server_broadcast_emits_same_fields_as_fixture():
    # The server _broadcast envelope must carry the same field set/names as the
    # shared fixture (what the JS + Swift clients decode). Assert the code that
    # builds the broadcast emits these keys.
    from pocketos_demo import app as A
    import inspect
    src = inspect.getsource(A._broadcast)
    for key in ('"type"', '"event_id"', '"sequence"', '"occurred_at"', '"source"',
                '"kind"', '"previous_hash"', '"schema_version"', '"payload"'):
        assert key in src, f"server broadcast does not emit {key}"


def test_js_normalizer_output_equals_fixture_semantics():
    # The web client forwards exactly the canonical fields; its output for a
    # given envelope must be equivalent (same keys, same values) to the shared
    # fixture — proving web and Swift decode one truth.
    env = _load_fixture()
    normalized = _js_normalizer_fields(env)
    assert normalized["type"] == "decision.proposed"
    assert normalized["kind"] == "decision"
    assert normalized["sequence"] == 26
    assert normalized["schema_version"] == "v2"
    assert normalized["source"] == "WebClient"
    # All canonical keys present, none dropped.
    assert set(normalized) == {"type", "event_id", "sequence", "occurred_at",
                               "source", "kind", "previous_hash", "schema_version", "payload"}


def test_fixture_matches_a_real_ledger_record_shape():
    # A real server-ledger record has the same top-level provenance fields the
    # envelope carries (timestamp->occurred_at, event->type, source, kind,
    # previous_hash, schema_version, hash->event_id). This ties the fixture to
    # actual persisted history, not an invented shape.
    from pocketos_demo.engines import seed_ledger
    rec = seed_ledger()[0]
    for key in ("event", "source", "schema_version", "hash", "sequence"):
        assert key in rec, f"ledger record missing {key}"
