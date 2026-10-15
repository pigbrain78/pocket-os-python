import hashlib
import time
import uuid
from typing import Any

import rfc8785

from .models import FirewallReceipt, FirewallVerdict


class LedgerSink:
    def __init__(self, ledger_engine: Any = None):
        self.ledger_engine = ledger_engine

    def emit_receipt(
        self,
        lease_id: str | None,
        agent_id: str,
        tool_name: str,
        verdict: FirewallVerdict,
        reason: str,
        latency_ms: float,
    ) -> FirewallReceipt:
        timestamp = int(time.time() * 1000)
        receipt_data = {
            "receipt_id": str(uuid.uuid4()),
            "timestamp": timestamp,
            "lease_id": lease_id,
            "agent_id": agent_id,
            "tool_name": tool_name,
            "verdict": verdict.value,
            "reason": reason,
            "latency_ms": round(latency_ms, 2),
        }
        digest = hashlib.sha256(rfc8785.dumps(receipt_data)).hexdigest()
        receipt = FirewallReceipt(**receipt_data, mesh_digest=f"sovereign:mcp:firewall:{digest}")
        if self.ledger_engine is not None:
            self.ledger_engine.append_event("MCP_FIREWALL_VERDICT", receipt.model_dump(mode="json"))
        return receipt
