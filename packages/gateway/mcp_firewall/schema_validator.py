import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote

from .models import FirewallVerdict


class SchemaValidator:
    DANGEROUS_PATTERNS = (
        re.compile(r"(?:^|[/\\])\.\.(?:[/\\]|$)", re.IGNORECASE),
        re.compile(r";\s*rm\s+-rf", re.IGNORECASE),
        re.compile(r"\bdrop\s+table\b", re.IGNORECASE),
        re.compile(r"/etc/shadow", re.IGNORECASE),
    )
    MAX_ARGUMENT_BYTES = 65536
    MAX_NESTING_DEPTH = 32

    def validate(self, arguments: Any) -> tuple[bool, FirewallVerdict, str]:
        if not isinstance(arguments, Mapping):
            return False, FirewallVerdict.BLOCKED_AST_INJECTION, "Tool arguments must be a JSON object"
        try:
            serialized = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError, RecursionError, UnicodeEncodeError):
            return False, FirewallVerdict.BLOCKED_AST_INJECTION, "Tool arguments must contain JSON values only"
        if len(serialized.encode("utf-8")) > self.MAX_ARGUMENT_BYTES:
            return False, FirewallVerdict.BLOCKED_AST_INJECTION, "Tool arguments exceed the size limit"

        values: list[tuple[Any, int]] = [(arguments, 0)]
        while values:
            value, depth = values.pop()
            if depth > self.MAX_NESTING_DEPTH:
                return False, FirewallVerdict.BLOCKED_AST_INJECTION, "Tool arguments exceed the nesting limit"
            if isinstance(value, str):
                normalized = value
                for _ in range(3):
                    normalized = unquote(normalized)
                for pattern in self.DANGEROUS_PATTERNS:
                    if pattern.search(normalized):
                        return (
                            False,
                            FirewallVerdict.BLOCKED_AST_INJECTION,
                            f"AST injection detected: parameter matched {pattern.pattern}",
                        )
            elif isinstance(value, Mapping):
                values.extend((item, depth + 1) for pair in value.items() for item in pair)
            elif isinstance(value, (list, tuple)):
                values.extend((item, depth + 1) for item in value)
        return True, FirewallVerdict.SANCTIONED, "AST parameter validation successful"
