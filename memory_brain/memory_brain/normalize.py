"""normalize.py -- deterministic normalization.

normalized_content is used for duplicate detection via NORMALIZED_HASH. It is
purely deterministic (same input -> same output for a pinned algorithm
version) and never destructive to the original content. Different algorithm
versions may yield different normalized forms; version is always recorded so
replay/verification is reproducible.
"""

from __future__ import annotations

import re
import unicodedata

from . import canonical

NORMALIZATION_ALGORITHM_VERSION = "norm-1.0"

_WS_RE = re.compile(r"\s+")
_NONWORD_RE = re.compile(r"[^\w\s]")


def normalize_text(text: str,
                   algorithm_version: str = NORMALIZATION_ALGORITHM_VERSION) -> str:
    """Deterministic canonical text form for comparison.

    Steps: NFKC -> casefold -> strip accents -> drop punctuation (replaced with
    a space so tokens are not glued) -> collapse whitespace -> strip. So
    'The Service uses PostgreSQL.' and 'the service uses postgresql' collapse
    to the same form.
    """
    if algorithm_version != NORMALIZATION_ALGORITHM_VERSION:
        raise ValueError(f"Unknown normalization algorithm version: {algorithm_version}")

    s = unicodedata.normalize("NFKC", text)
    s = s.casefold()
    s = "".join(ch for ch in unicodedata.normalize("NFD", s)
                if not unicodedata.combining(ch))
    s = _NONWORD_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def normalized_hash(text: str) -> str:
    """Domain-tagged digest of the normalized form (for NORMALIZED_HASH signal)."""
    return canonical.digest(normalize_text(text), canonical.MEMORY_CONTENT)


def content_hash(content: str) -> str:
    """Canonical digest of raw content (for EXACT_HASH signal)."""
    return canonical.digest(content, canonical.MEMORY_CONTENT)
