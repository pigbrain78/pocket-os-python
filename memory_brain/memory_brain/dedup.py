"""dedup.py -- duplicate detection across multiple independent signals.

Never collapses signals. A candidate pair is scored on several orthogonal
axes and classified. Automatic action (deduplication/merge) is permitted only
for EXACT_DUPLICATE; everything uncertain (PROBABLE_DUPLICATE, RELATED,
POSSIBLE_CONTRADICTION) routes to the human review queue. Uncertain records
are never auto-merged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from . import normalize
from .models import DEDUP_CLASS

DEDUP_ALGORITHM_VERSION = "dedup-1.0"

# Contradiction keywords for the POSSIBLE_CONTRADICTION hint.
_ANTONYM_PAIRS: list[tuple[str, str]] = [
    ("postgres", "sqlite"), ("postgresql", "sqlite"),
    ("uses", "does not use"), ("is", "is not"),
    ("enabled", "disabled"), ("active", "inactive"),
    ("true", "false"), ("yes", "no"),
]


@dataclass
class DedupSignals:
    exact_hash_match: bool
    normalized_hash_match: bool
    entity_overlap: float      # 0..1
    claim_similarity: float    # 0..1
    source_related: bool
    temporal_related: bool

    @property
    def semantic_similarity(self) -> float:
        # Deterministic stand-in for an embedding model: blend normalized
        # token overlap. In production an embedding model may replace this,
        # but embeddings are never authoritative -- see module docstring.
        return round(0.7 * self.claim_similarity + 0.3 * self.entity_overlap, 4)


@dataclass
class DedupResult:
    classification: str
    signals: DedupSignals
    auto_action: Optional[str]   # None, or "merge"/"dedupe" only for EXACT
    reason: str


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalize.normalize_text(text)))


def compute_signals(content_a: str, content_b: str,
                    source_a: Optional[str] = None,
                    source_b: Optional[str] = None) -> DedupSignals:
    exact = normalize.content_hash(content_a) == normalize.content_hash(content_b)
    norm_match = normalize.normalized_hash(content_a) == normalize.normalized_hash(content_b)
    toks_a = _tokens(content_a)
    toks_b = _tokens(content_b)
    entity_overlap = _jaccard(toks_a, toks_b)
    claim_similarity = _char_ngram_sim(content_a, content_b)
    source_related = (source_a is not None and source_a == source_b)
    temporal_related = False  # caller may override; deterministic default
    return DedupSignals(exact, norm_match, entity_overlap, claim_similarity,
                        source_related, temporal_related)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 4)


def _char_ngram_sim(a: str, b: str, n: int = 3) -> float:
    """Character n-gram Jaccard similarity -- robust to word reordering."""
    def ngrams(s: str):
        s = normalize.normalize_text(s)
        if len(s) < n:
            return {s} if s else set()
        return {s[i:i + n] for i in range(len(s) - n + 1)}
    ga, gb = ngrams(a), ngrams(b)
    if not ga and not gb:
        return 1.0
    if not ga or not gb:
        return 0.0
    return round(len(ga & gb) / len(ga | gb), 4)


def _possible_contradiction(a: str, b: str) -> bool:
    """Heuristic: does the pair look like it may contradict (polar opposites)?"""
    la, lb = normalize.normalize_text(a), normalize.normalize_text(b)
    for x, y in _ANTONYM_PAIRS:
        if (x in la and y in lb) or (x in lb and y in la):
            return True
    return False


def classify_pair(content_a: str, content_b: str,
                  source_a: Optional[str] = None,
                  source_b: Optional[str] = None,
                  algorithm_version: str = DEDUP_ALGORITHM_VERSION) -> DedupResult:
    """Classify a candidate pair into one of DEDUP_CLASS.

    Auto-action is only produced for an EXACT_DUPLICATE (identical content and
    identical normalized form). All other classes return auto_action=None and
    are routed to review.
    """
    if algorithm_version != DEDUP_ALGORITHM_VERSION:
        raise ValueError(f"Unknown dedup algorithm version: {algorithm_version}")

    sig = compute_signals(content_a, content_b, source_a, source_b)

    if sig.exact_hash_match or (sig.normalized_hash_match and sig.claim_similarity >= 0.98):
        return DedupResult("EXACT_DUPLICATE", sig, "merge",
                           "identical or near-identical content; safe to dedupe")

    if _possible_contradiction(content_a, content_b) and sig.claim_similarity >= 0.35:
        return DedupResult("POSSIBLE_CONTRADICTION", sig, None,
                           "polar-opposite phrasing over shared context; review")

    if sig.claim_similarity >= 0.85:
        return DedupResult("PROBABLE_DUPLICATE", sig, None,
                           "high similarity but not exact; human review required")

    if sig.claim_similarity >= 0.5 or sig.entity_overlap >= 0.5:
        return DedupResult("RELATED", sig, None,
                           "related knowledge, distinct claim; no merge")

    return DedupResult("DISTINCT", sig, None, "distinct knowledge")
