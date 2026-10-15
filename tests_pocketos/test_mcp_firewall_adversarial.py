import base64
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kernel.economic_bridge import EconomicBridge
from packages.gateway.mcp_firewall.interceptor import MCPConstitutionalFirewall
from packages.gateway.mcp_firewall.lease_verifier import canonical_lease_payload
from packages.gateway.mcp_firewall.models import (
    CapabilityLease,
    FirewallVerdict,
    ToolExecutionLevel,
)
from packages.gateway.mcp_firewall.schema_validator import SchemaValidator
from scripts.gemini_mcp_bridge import GEMINI_TOOLS, execute_governed_gemini_prompt


def build_signed_lease(
    private_key: Ed25519PrivateKey,
    lease_id: str,
    tool: str,
    level: ToolExecutionLevel,
    expired: bool = False,
) -> CapabilityLease:
    now = datetime.now(timezone.utc)
    lease = CapabilityLease(
        lease_id=lease_id,
        agent_id="agent_alpha",
        allowed_tool=tool,
        execution_level=level,
        issued_at=now - timedelta(seconds=20),
        expires_at=now - timedelta(seconds=10) if expired else now + timedelta(seconds=200),
        signature_ed25519="pending",
    )
    signature = base64.b64encode(private_key.sign(canonical_lease_payload(lease))).decode("ascii")
    return lease.model_copy(update={"signature_ed25519": signature})


@pytest.mark.asyncio
async def test_expired_lease_is_blocked():
    private_key = Ed25519PrivateKey.generate()
    firewall = MCPConstitutionalFirewall(governance_pubkey=private_key.public_key())
    lease = build_signed_lease(private_key, "lease_exp", "query_db", ToolExecutionLevel.READ_ONLY, True)

    allowed, _, receipt = await firewall.intercept_tool_call(
        {"method": "tools/call", "params": {"name": "query_db", "arguments": {}}},
        lease=lease,
    )

    assert not allowed
    assert receipt.verdict == FirewallVerdict.BLOCKED_EXPIRED_LEASE
    assert receipt.latency_ms < 12


@pytest.mark.asyncio
async def test_unratified_irreversible_mutation_is_blocked():
    private_key = Ed25519PrivateKey.generate()
    firewall = MCPConstitutionalFirewall(governance_pubkey=private_key.public_key())
    lease = build_signed_lease(
        private_key, "lease_mut", "delete_records", ToolExecutionLevel.MUTATING_IRREVERSIBLE
    )

    allowed, _, receipt = await firewall.intercept_tool_call(
        {"method": "tools/call", "params": {"name": "delete_records", "arguments": {"id": 1}}},
        lease=lease,
    )

    assert not allowed
    assert receipt.verdict == FirewallVerdict.BLOCKED_CONSTITUTIONAL_VIOLATION
    assert "Law 001" in receipt.reason


@pytest.mark.asyncio
async def test_path_traversal_is_blocked_even_when_url_encoded():
    result = SchemaValidator().validate({"path": "%2e%2e%2f%2e%2e%2fetc/shadow"})

    assert result[0] is False
    assert result[1] == FirewallVerdict.BLOCKED_AST_INJECTION


@pytest.mark.asyncio
async def test_nested_law_000_mutation_and_unwhitelisted_resource_are_blocked():
    private_key = Ed25519PrivateKey.generate()
    firewall = MCPConstitutionalFirewall(governance_pubkey=private_key.public_key())
    lease = build_signed_lease(private_key, "lease_policy", "update", ToolExecutionLevel.READ_ONLY)

    allowed, _, receipt = await firewall.intercept_tool_call(
        {
            "method": "tools/call",
            "params": {"name": "update", "arguments": {"metadata": {"operation": "amend_policy"}}},
        },
        lease=lease,
    )
    assert not allowed
    assert receipt.verdict == FirewallVerdict.BLOCKED_CONSTITUTIONAL_VIOLATION

    lease = build_signed_lease(private_key, "lease_path", "read_file", ToolExecutionLevel.READ_ONLY)
    allowed, _, receipt = await firewall.intercept_tool_call(
        {
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": {"options": {"path": "/safe/file"}}},
        },
        lease=lease,
    )
    assert not allowed
    assert receipt.verdict == FirewallVerdict.BLOCKED_CONSTITUTIONAL_VIOLATION


@pytest.mark.asyncio
async def test_valid_sanctioned_call_and_invocation_limit():
    private_key = Ed25519PrivateKey.generate()
    firewall = MCPConstitutionalFirewall(governance_pubkey=private_key.public_key())
    lease = build_signed_lease(private_key, "lease_ok", "fetch_weather", ToolExecutionLevel.READ_ONLY)
    rpc = {"method": "tools/call", "params": {"name": "fetch_weather", "arguments": {"city": "Angier"}}}

    allowed, _, receipt = await firewall.intercept_tool_call(rpc, lease=lease)

    assert allowed
    assert receipt.verdict == FirewallVerdict.SANCTIONED
    assert receipt.latency_ms < 12
    assert receipt.mesh_digest.startswith("sovereign:mcp:firewall:")
    assert lease.invocations_used == 1
    allowed, _, exhausted_receipt = await firewall.intercept_tool_call(rpc, lease=lease)
    assert not allowed
    assert exhausted_receipt.verdict == FirewallVerdict.BLOCKED_EXPIRED_LEASE


@pytest.mark.asyncio
async def test_invalid_signature_and_missing_governance_key_fail_closed():
    private_key = Ed25519PrivateKey.generate()
    other_key = Ed25519PrivateKey.generate()
    lease = build_signed_lease(private_key, "lease_bad", "query_db", ToolExecutionLevel.READ_ONLY)
    rpc = {"method": "tools/call", "params": {"name": "query_db", "arguments": {}}}

    allowed, _, receipt = await MCPConstitutionalFirewall(
        governance_pubkey=other_key.public_key()
    ).intercept_tool_call(rpc, lease=lease)
    assert not allowed
    assert receipt.verdict == FirewallVerdict.BLOCKED_CONSTITUTIONAL_VIOLATION

    allowed, _, receipt = await MCPConstitutionalFirewall().intercept_tool_call(rpc, lease=lease)
    assert not allowed
    assert receipt.verdict == FirewallVerdict.BLOCKED_CONSTITUTIONAL_VIOLATION


def test_receipt_uses_rfc8785_jcs_for_mesh_digest():
    firewall = MCPConstitutionalFirewall()
    receipt = firewall.sink.emit_receipt(None, "agent", "tool", FirewallVerdict.SANCTIONED, "ok", 1.234)
    data = receipt.model_dump(mode="json", exclude={"mesh_digest"})
    assert receipt.mesh_digest == "sovereign:mcp:firewall:" + hashlib.sha256(rfc8785.dumps(data)).hexdigest()


def test_economic_bridge_settles_satoshis_and_debits_wallet():
    class Wallet:
        def __init__(self):
            self.debit = None

        def debit_sats(self, amount, reason):
            self.debit = (amount, reason)

    wallet = Wallet()
    bridge = EconomicBridge(wallet=wallet)
    receipt = bridge.settle_execution_cost(
        {
            "task_id": "test_sandbox_run",
            "cpu_seconds": 2.5,
            "peak_memory_bytes": 104857600,
            "io_read_bytes": 5242880,
            "io_write_bytes": 5242880,
        }
    )

    assert receipt["estimated_cost_sats"] == 50
    assert receipt["settled"] is True
    assert wallet.debit == (50, "ResourceMeter:test_sandbox_run")
    with pytest.raises(ValueError):
        bridge.settle_execution_cost({"cpu_seconds": -1})


@pytest.mark.asyncio
async def test_gemini_function_calls_are_intercepted_with_governance_minted_lease():
    private_key = Ed25519PrivateKey.generate()

    class Client:
        class Models:
            def generate_content(self, **kwargs):
                assert kwargs["config"]["tools"] == GEMINI_TOOLS
                return SimpleNamespace(
                    function_calls=[SimpleNamespace(name="pocketos_query_memory", args={"query_key": "release"})]
                )

        models = Models()

    def lease_minter(tool_name, level):
        return build_signed_lease(private_key, "gemini", tool_name, level)

    _, results = await execute_governed_gemini_prompt(
        "query memory",
        Client(),
        MCPConstitutionalFirewall(governance_pubkey=private_key.public_key()),
        lease_minter,
    )

    assert len(results) == 1
    assert results[0][0] is True
