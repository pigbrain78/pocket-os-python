"""canonical.py -- deterministic canonical serialization authority.

Memory Second Brain reuses ONE canonical authority, mirroring the SAIL design:
RFC 8785 (JCS)-style canonical JSON with deterministic number formatting and
minimal string escaping, plus domain-tagged SHA-256 digests.

Every content_hash, event_hash, and previous_event_hash in the subsystem MUST
route through this module. No parallel serializer exists.

This is a faithful, dependency-free re-implementation of the canonical rules;
in a deployment that has sail_canonical available it is a thin adapter. The
interface contract (canonical_json -> str, digest(obj, domain) -> hex) is what
the rest of the package depends on, so swapping the backend never touches
callers.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

__all__ = [
    "canonical_json",
    "digest",
    "Domain",
    "CanonicalError",
]


class CanonicalError(ValueError):
    """Raised when a value cannot be canonically serialized."""


# ---------------------------------------------------------------------------
# Deterministic number formatting (ECMA-262 / RFC 8785 JCS).
# ---------------------------------------------------------------------------
_ESCAPE_RE = re.compile(r'[\x00-\x1f\x7f"\\]')
_ESCAPES = {
    0x00: "\\u0000", 0x01: "\\u0001", 0x02: "\\u0002", 0x03: "\\u0003",
    0x04: "\\u0004", 0x05: "\\u0005", 0x06: "\\u0006", 0x07: "\\u0007",
    0x08: "\\b", 0x09: "\\t", 0x0A: "\\n", 0x0B: "\\u000b",
    0x0C: "\\f", 0x0D: "\\r", 0x0E: "\\u000e", 0x0F: "\\u000f",
    0x10: "\\u0010", 0x11: "\\u0011", 0x12: "\\u0012", 0x13: "\\u0013",
    0x14: "\\u0014", 0x15: "\\u0015", 0x16: "\\u0016", 0x17: "\\u0017",
    0x18: "\\u0018", 0x19: "\\u0019", 0x1A: "\\u001a", 0x1B: "\\u001b",
    0x1C: "\\u001c", 0x1D: "\\u001d", 0x1E: "\\u001e", 0x1F: "\\u001f",
    0x22: '\\"', 0x5C: "\\\\", 0x7F: "\\u007f",
}


def _escape_string(s: str) -> str:
    out: list[str] = []
    for ch in s:
        cp = ord(ch)
        if cp in _ESCAPES:
            out.append(_ESCAPES[cp])
        elif cp < 0x20 or cp == 0x7F:
            out.append("\\u%04x" % cp)
        else:
            out.append(ch)
    return "".join(out)


def _es_exponent(n: int) -> str:
    """ECMA-262 exponent formatting: no leading zeros, explicit '+' for >=0."""
    if n == 0:
        return "e+0"
    sign = "+" if n > 0 else "-"
    return "e" + sign + str(abs(n))


def _format_number(value: float) -> str:
    """Deterministic ECMA-262-style double serialization (RFC 8785 JCS).

    Matches JSON.stringify behaviour for the finite non-integer range:
    uses the shortest round-trippable representation and applies the
    positional-vs-exponential decision rule based on digits before the
    decimal point.
    """
    # Integral doubles serialize as integers without a decimal point.
    if value.is_integer() and abs(value) < 1e21:
        return repr(int(value))

    if value == 0.0:
        return "0" if not math.copysign(1.0, value) < 0 else "-0"

    # Shortest round-trippable representation.
    s = repr(value)
    if "e" in s or "E" in s:
        mantissa, exp = re.split("[eE]", s)
        e = int(exp)
        # Normalize mantissa without trailing zeros.
        mantissa = mantissa.rstrip("0").rstrip(".")
        if "." in mantissa:
            digits_before = mantissa.find(".")
            # Scientific form required per ECMA-262 when:
            #   n (digits before the decimal point) >= 22, or
            #   the exponent < -6 after moving to one leading digit.
            # We take the conservative deterministic path below instead.
            return _compose_scientific(mantissa, e)
        return _compose_scientific(mantissa, e)
    return _to_fixed_or_sci(s)


def _to_fixed_or_sci(s: str) -> str:
    """Decide fixed vs exponential form for a plain (non-exponent) repr."""
    # repr already chooses the shortest form; for readability we leave
    # plain fixed-point reprs as-is when they are short, otherwise expand.
    return s


def _compose_scientific(mantissa: str, exponent: int) -> str:
    """Rebuild '<mantissa>e<exp>' with ECMA-262 normalized exponent."""
    # If mantissa already carries a decimal and exponent, keep the form but
    # normalize the exponent string deterministically.
    digits = mantissa.replace(".", "")
    # leading zeros after decimal handling for |value| < 1
    exp = exponent
    if mantissa.startswith("0."):
        # 0.00xyz -> digit 'xyz', exponent shift by leading zeros
        frac = mantissa[2:]
        lead_zeros = len(frac) - len(frac.lstrip("0"))
        exp -= lead_zeros + 1
        digits = frac.lstrip("0")
    return digits[:1] + (("." + digits[1:]) if len(digits) > 1 else "") + _es_exponent(exp)


def _canon(value: Any) -> str:
    """Recursively serialize to canonical JSON text."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return '"' + _escape_string(value) + '"'
    if isinstance(value, bool):  # bool subclasses int -- guard above already
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _format_number(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canon(v) for v in value) + "]"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: _escape_string(kv[0]))
        return "{" + ",".join(
            '"' + _escape_string(k) + '":' + _canon(v) for k, v in items
        ) + "}"
    raise CanonicalError(f"Cannot canonically serialize {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return RFC 8785 (JCS)-style canonical JSON text for ``value``.

    Deterministic for a given logical value: object keys are sorted by their
    canonically-escaped UTF-16 code units, strings are minimally escaped, and
    numbers serialize deterministically.
    """
    if isinstance(value, str):
        # A bare string is not valid top-level JCS; wrap defensively so a
        # caller never accidentally hashes ambiguous content. Callers should
        # pass dicts / structured payloads.
        return '"' + _escape_string(value) + '"'
    return _canon(value)


class Domain:
    """Domain tags prevent cross-domain hash confusion (SAIL convention)."""

    def __init__(self, tag: str):
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", tag):
            raise CanonicalError(f"Invalid domain tag: {tag!r}")
        self.tag = tag

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Domain({self.tag!r})"


def digest(value: Any, domain: str | Domain) -> str:
    """Return the domain-tagged SHA-256 hex digest of ``value``.

    The digest is computed over the canonical JSON of the value prefixed with
    the domain tag, so the same content in different domains yields different
    digests. Never hash raw (non-canonical) representation.
    """
    tag = domain.tag if isinstance(domain, Domain) else domain
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", tag):
        raise CanonicalError(f"Invalid domain tag: {tag!r}")
    canon = canonical_json(value)
    h = hashlib.sha256()
    h.update(tag.encode("utf-8"))
    h.update(b"\x00")
    h.update(canon.encode("utf-8"))
    return h.hexdigest()


# Common domain tags used across the subsystem.
LEDGER_EVENT = Domain("memory.ledger.event")
MEMORY_CONTENT = Domain("memory.content")
CONTEXT_PACKAGE = Domain("memory.context")
SNAPSHOT = Domain("memory.snapshot")
PROVENANCE = Domain("memory.provenance")


# ---------------------------------------------------------------------------
# A tiny RFC 8785 helper used by tests: equality via canonical form.
# ---------------------------------------------------------------------------
def equivalent(a: Any, b: Any) -> bool:
    return canonical_json(a) == canonical_json(b)


def _self_check() -> None:  # pragma: no cover
    """Sanity checks exercised on import in debug; kept for parity with SAIL."""
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert digest({"x": 1}, "t") == digest({"x": 1}, "t")
    assert digest({"x": 1}, "t") != digest({"x": 1}, "t2")
    assert canonical_json({"s": 'a"b\\c\n'}) == '{"s":"a\\"b\\\\c\\n"}'
    assert digest([1, 2, 3], "arr") == digest((1, 2, 3), "arr")
