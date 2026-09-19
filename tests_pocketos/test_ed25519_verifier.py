import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.pocketos_demo.engines import council_ratification as council
from scripts.pocketos_demo.engines import ed25519_verifier as verifier


def _registry_material():
    private = {member: Ed25519PrivateKey.generate() for member in ("council-a", "council-b", "council-c")}
    document = {
        member: {
            "key_id": f"{member}:v1",
            "public_key": base64.b64encode(key.public_key().public_bytes_raw()).decode("ascii"),
        }
        for member, key in private.items()
    }
    return private, document


def _sign(private, member, candidate_id="D-1", state="RATIFIED"):
    raw = private[member].sign(verifier.canonical_bytes(candidate_id, state, member))
    return verifier.envelope(f"{member}:v1", raw)


def test_ed25519_verifies_canonical_payload_and_distinct_quorum():
    private, document = _registry_material()
    registry = verifier.load_registry(json.dumps(document), sorted(private))
    signatures = {"council-a": _sign(private, "council-a"), "council-b": _sign(private, "council-b")}

    assert verifier.verify("D-1", "RATIFIED", "council-a", signatures["council-a"], registry)
    assert len(verifier.verified_members("D-1", "RATIFIED", signatures, registry)) == 2


def test_ed25519_rejects_wrong_scope_state_member_key_and_algorithm():
    private, document = _registry_material()
    registry = verifier.load_registry(json.dumps(document), sorted(private))
    signature = _sign(private, "council-a")

    assert not verifier.verify("D-2", "RATIFIED", "council-a", signature, registry)
    assert not verifier.verify("D-1", "PROMOTED", "council-a", signature, registry)
    assert not verifier.verify("D-1", "RATIFIED", "council-b", signature, registry)
    assert not verifier.verify("D-1", "RATIFIED", "council-a", {**signature, "key_id": "council-a:v9"}, registry)
    assert not verifier.verify("D-1", "RATIFIED", "council-a", {**signature, "algorithm": "HMAC-SHA256"}, registry)


def test_ed25519_rejects_malformed_and_duplicate_quorum_inputs():
    private, document = _registry_material()
    registry = verifier.load_registry(json.dumps(document), sorted(private))
    valid = _sign(private, "council-a")

    assert not verifier.verify("D-1", "RATIFIED", "council-a", {"algorithm": "Ed25519"}, registry)
    assert not verifier.verify("D-1", "RATIFIED", "council-a", {**valid, "signature": "not-base64"}, registry)
    assert len(verifier.verified_members("D-1", "RATIFIED", {"council-a": valid, "council-b": valid}, registry)) == 1
    ok, ledger = council.ratify_verified_members("D-1", "RATIFIED", {"council-a"}, [])
    assert ok is False
    assert ledger == []


def test_public_key_registry_is_strict_and_fails_closed():
    private, document = _registry_material()
    del document["council-c"]
    try:
        verifier.load_registry(json.dumps(document), sorted(private))
    except ValueError as exc:
        assert "council-c" in str(exc)
    else:
        raise AssertionError("incomplete public-key registry was accepted")
