import time
from collections.abc import Mapping
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .lease_verifier import LeaseVerifier
from .ledger_sink import LedgerSink
from .models import CapabilityLease, FirewallReceipt, FirewallVerdict
from .policy_evaluator import ConstitutionalPolicyEvaluator
from .schema_validator import SchemaValidator


class MCPConstitutionalFirewall:
    def __init__(self, ledger_engine: Any = None, governance_pubkey: Ed25519PublicKey | bytes | None = None):
        self.verifier = LeaseVerifier(governance_pubkey)
        self.policy = ConstitutionalPolicyEvaluator()
        self.validator = SchemaValidator()
        self.sink = LedgerSink(ledger_engine)

    async def intercept_tool_call(
        self,
        rpc_payload: dict[str, Any],
        lease: CapabilityLease | None = None,
        human_ratified: bool = False,
    ) -> tuple[bool, dict[str, Any], FirewallReceipt]:
        start_time = time.perf_counter()
        params = rpc_payload.get("params", {})
        if not isinstance(params, Mapping):
            params = {}
        method = rpc_payload.get("method")
        tool_name = params.get("name", "unknown_tool")
        if not isinstance(tool_name, str):
            tool_name = "unknown_tool"
        arguments = params.get("arguments", {})
        agent_id = lease.agent_id if lease else "anonymous_agent"
        lease_id = lease.lease_id if lease else None

        def reject(verdict: FirewallVerdict, reason: str, code: int):
            latency = (time.perf_counter() - start_time) * 1000
            receipt = self.sink.emit_receipt(lease_id, agent_id, tool_name, verdict, reason, latency)
            return False, {"error": {"code": code, "message": reason}}, receipt

        if method == "tools/call" and lease is None:
            return reject(
                FirewallVerdict.BLOCKED_CONSTITUTIONAL_VIOLATION,
                "Missing capability lease",
                -32001,
            )
        if method == "tools/call" and lease is not None:
            ok, verdict, reason = self.verifier.verify(lease, tool_name)
            if not ok:
                return reject(verdict, reason, -32002)

        ok, verdict, reason = self.validator.validate(arguments)
        if not ok:
            return reject(verdict, reason, -32004)
        if lease is not None and method == "tools/call":
            ok, verdict, reason = self.policy.evaluate(lease, arguments, human_ratified)
            if not ok:
                return reject(verdict, reason, -32003)
            lease.invocations_used += 1
        latency = (time.perf_counter() - start_time) * 1000
        receipt = self.sink.emit_receipt(
            lease_id,
            agent_id,
            tool_name,
            FirewallVerdict.SANCTIONED,
            "Sanctioned by Constitutional Policy",
            latency,
        )
        return True, rpc_payload, receipt
