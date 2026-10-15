from collections.abc import Mapping
from typing import Any

from .models import CapabilityLease, FirewallVerdict, ToolExecutionLevel


class ConstitutionalPolicyEvaluator:
    FORBIDDEN_MUTATION_KEYWORDS = (
        "law_000",
        "constitution",
        "amend_policy",
        "grant_self_permission",
    )

    def evaluate(
        self, lease: CapabilityLease, arguments: Mapping[str, Any], human_ratified: bool = False
    ) -> tuple[bool, FirewallVerdict, str]:
        resource_keys = {"path", "resource", "target", "uri"}
        values = [arguments]
        while values:
            value = values.pop()
            if isinstance(value, str):
                normalized = value.lower()
                for keyword in self.FORBIDDEN_MUTATION_KEYWORDS:
                    if keyword in normalized:
                        return (
                            False,
                            FirewallVerdict.BLOCKED_CONSTITUTIONAL_VIOLATION,
                            f"Law 000 Violation: attempted mutation of governing policy ({keyword})",
                        )
            elif isinstance(value, Mapping):
                for key, child in value.items():
                    if (
                        isinstance(key, str)
                        and key.lower() in resource_keys
                        and isinstance(child, str)
                        and child not in lease.resource_whitelist
                    ):
                        return (
                            False,
                            FirewallVerdict.BLOCKED_CONSTITUTIONAL_VIOLATION,
                            f"Resource {child} is not in the capability lease whitelist",
                        )
                    values.extend((key, child))
            elif isinstance(value, (list, tuple)):
                values.extend(value)

        if lease.execution_level == ToolExecutionLevel.MUTATING_IRREVERSIBLE and not human_ratified:
            return (
                False,
                FirewallVerdict.BLOCKED_CONSTITUTIONAL_VIOLATION,
                "Law 001 Violation: irreversible mutation requires explicit human ratification",
            )
        return True, FirewallVerdict.SANCTIONED, "Constitutional policy check passed"
