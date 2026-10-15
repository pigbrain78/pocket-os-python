import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from packages.gateway.mcp_firewall.interceptor import MCPConstitutionalFirewall
from packages.gateway.mcp_firewall.models import CapabilityLease, ToolExecutionLevel


GEMINI_TOOLS = [
    {
        "function_declarations": [
            {
                "name": "pocketos_query_memory",
                "description": "Queries the append-only memory ledger.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query_key": {"type": "STRING", "description": "Exact memory key or tag"}
                    },
                    "required": ["query_key"],
                },
            },
            {
                "name": "pocketos_propose_action",
                "description": "Submits a mutating action proposal for human review.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "target": {"type": "STRING", "description": "Target system or file path"},
                        "mutation_type": {"type": "STRING", "description": "Action to propose"},
                    },
                    "required": ["target", "mutation_type"],
                },
            },
        ]
    }
]

LeaseMinter = Callable[[str, ToolExecutionLevel], CapabilityLease]


def mint_gemini_lease(
    tool_name: str, execution_level: ToolExecutionLevel, lease_minter: LeaseMinter
) -> CapabilityLease:
    lease = lease_minter(tool_name, execution_level)
    if lease.allowed_tool != tool_name or lease.execution_level != execution_level:
        raise ValueError("governance lease minter returned a lease with the wrong scope")
    return lease


async def execute_governed_gemini_prompt(
    prompt: str,
    client: Any,
    firewall: MCPConstitutionalFirewall,
    lease_minter: LeaseMinter,
) -> tuple[Any, list[tuple[bool, dict[str, Any], Any]]]:
    response = await asyncio.to_thread(
        client.models.generate_content,
        model="gemini-2.5-pro",
        contents=prompt,
        config={"tools": GEMINI_TOOLS},
    )
    results = []
    for call in getattr(response, "function_calls", None) or []:
        tool_name = call.get("name") if isinstance(call, Mapping) else call.name
        arguments = call.get("args", {}) if isinstance(call, Mapping) else getattr(call, "args", {})
        level = (
            ToolExecutionLevel.MUTATING_REVERSIBLE
            if tool_name == "pocketos_propose_action"
            else ToolExecutionLevel.READ_ONLY
        )
        lease = mint_gemini_lease(tool_name, level, lease_minter)
        results.append(
            await firewall.intercept_tool_call(
                {
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
                lease=lease,
            )
        )
    return response, results
