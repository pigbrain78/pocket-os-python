"""Production Ed25519 verification for off-box council signatures.

Private keys never enter PocketOS. The process loads only a JSON registry of
member key IDs and base64-encoded public keys, then verifies signatures over
the canonical council payload.
"""
from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import council_ratification as council

ALGORITHM = "Ed25519"


@dataclass(frozen=True)
class PublicKeyRecord:
    key_id: str
    key: Ed25519PublicKey


def _b64decode(value: str) -> bytes:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
        raise ValueError("invalid base64 key or signature") from exc


def load_registry(raw: str, members: list[str]) -> dict[str, PublicKeyRecord]:
    """Load the complete active public-key registry or fail closed."""
    if not raw.strip():
        return {}
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("public-key registry is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("public-key registry must be an object")
    registry: dict[str, PublicKeyRecord] = {}
    for member in members:
        item = document.get(member)
        if not isinstance(item, dict):
            raise ValueError(f"missing public key for {member}")
        key_id = item.get("key_id")
        public_key = item.get("public_key")
        if not isinstance(key_id, str) or not key_id.strip():
            raise ValueError(f"missing key_id for {member}")
        if not isinstance(public_key, str):
            raise ValueError(f"missing public_key for {member}")
        raw_key = _b64decode(public_key)
        if len(raw_key) != 32:
            raise ValueError(f"invalid Ed25519 public key length for {member}")
        registry[member] = PublicKeyRecord(key_id=key_id, key=Ed25519PublicKey.from_public_bytes(raw_key))
    return registry


def envelope(key_id: str, signature: bytes) -> dict[str, str]:
    return {
        "algorithm": ALGORITHM,
        "key_id": key_id,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def canonical_bytes(candidate_id: str, state: str, member: str) -> bytes:
    return council.canonical(candidate_id, state, member).encode("utf-8")


def verify(candidate_id: str, state: str, member: str, value: Any,
           registry: dict[str, PublicKeyRecord]) -> bool:
    """Verify one strict Ed25519 envelope against the active key ID."""
    if state not in council.ALLOWED_STATES:
        return False
    record = registry.get(member)
    if record is None or not isinstance(value, dict):
        return False
    if value.get("algorithm") != ALGORITHM or value.get("key_id") != record.key_id:
        return False
    signature = value.get("signature")
    if not isinstance(signature, str):
        return False
    try:
        raw_signature = _b64decode(signature)
        if len(raw_signature) != 64:
            return False
        record.key.verify(raw_signature, canonical_bytes(candidate_id, state, member))
        return True
    except (ValueError, InvalidSignature):
        return False


def verified_members(candidate_id: str, state: str, signatures: dict[str, Any],
                     registry: dict[str, PublicKeyRecord]) -> set[str]:
    return {
        member for member, value in (signatures or {}).items()
        if verify(candidate_id, state, member, value, registry)
    }
