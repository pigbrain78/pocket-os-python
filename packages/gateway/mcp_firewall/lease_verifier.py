import base64
import binascii
import json
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .models import CapabilityLease, FirewallVerdict


def canonical_lease_payload(lease: CapabilityLease) -> bytes:
    data = {
        "agent_id": lease.agent_id,
        "allowed_tool": lease.allowed_tool,
        "execution_level": lease.execution_level.value,
        "expires_at": lease.expires_at.astimezone(timezone.utc).isoformat(),
        "issued_at": lease.issued_at.astimezone(timezone.utc).isoformat(),
        "lease_id": lease.lease_id,
        "max_invocations": lease.max_invocations,
        "resource_whitelist": lease.resource_whitelist,
    }
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class LeaseVerifier:
    def __init__(self, governance_pubkey: Ed25519PublicKey | bytes | None = None):
        if isinstance(governance_pubkey, bytes):
            governance_pubkey = Ed25519PublicKey.from_public_bytes(governance_pubkey)
        self.governance_pubkey = governance_pubkey

    def verify(
        self, lease: CapabilityLease, requested_tool: str
    ) -> tuple[bool, FirewallVerdict, str]:
        if lease.is_expired():
            return False, FirewallVerdict.BLOCKED_EXPIRED_LEASE, f"Lease {lease.lease_id} has expired"
        if lease.allowed_tool != requested_tool:
            return (
                False,
                FirewallVerdict.BLOCKED_TOOL_UNMAPPED,
                f"Lease tool {lease.allowed_tool} does not match requested {requested_tool}",
            )
        if lease.invocations_used >= lease.max_invocations:
            return (
                False,
                FirewallVerdict.BLOCKED_EXPIRED_LEASE,
                f"Lease {lease.lease_id} has exhausted allowed invocations",
            )
        if self.governance_pubkey is None:
            return (
                False,
                FirewallVerdict.BLOCKED_CONSTITUTIONAL_VIOLATION,
                "No governance Ed25519 public key is configured",
            )
        try:
            signature = base64.b64decode(lease.signature_ed25519, validate=True)
            if len(signature) != 64:
                raise ValueError("invalid Ed25519 signature length")
            self.governance_pubkey.verify(signature, canonical_lease_payload(lease))
        except (ValueError, binascii.Error, InvalidSignature):
            return (
                False,
                FirewallVerdict.BLOCKED_CONSTITUTIONAL_VIOLATION,
                "Invalid Ed25519 lease signature",
            )
        return True, FirewallVerdict.SANCTIONED, "Lease valid and verified"
