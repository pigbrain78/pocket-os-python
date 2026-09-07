"""vector.py -- deterministic local semantic retrieval index.

Embeddings are NEVER authoritative. They are only an indexing mechanism for
semantic search. This module provides a deterministic, dependency-free local
token-vector index so the system is testable and runnable without any external
embedding service. In production an external embedding model may replace the
feature vectors, but the retrieval contract and the "index is derived" rule
are unchanged.
"""

from __future__ import annotations

import math
import re
from typing import Iterable, Optional

from . import normalize

VECTOR_ALGORITHM_VERSION = "vec-1.0"


def _features(text: str) -> dict[str, float]:
    """Bag-of-character-n-grams + word features with sublinear weighting."""
    toks = re.findall(r"[a-z0-9]+", normalize.normalize_text(text))
    feat: dict[str, float] = {}
    for t in toks:
        feat[f"w:{t}"] = feat.get(f"w:{t}", 0.0) + 1.0
    # char trigrams capture morphology/ordering weakly.
    flat = normalize.normalize_text(text).replace(" ", "")
    for i in range(len(flat) - 2):
        g = flat[i:i + 3]
        feat[f"g:{g}"] = feat.get(f"g:{g}", 0.0) + 1.0
    # sublinear tf
    return {k: 1.0 + math.log(v) for k, v in feat.items()}


def _l2(fv: dict[str, float]) -> float:
    return math.sqrt(sum(v * v for v in fv.values()))


def cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    denom = _l2(a) * _l2(b)
    if denom == 0.0:
        return 0.0
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    return round(dot / denom, 6)


class VectorIndex:
    """In-memory deterministic vector index over a set of (id, text) docs."""

    def __init__(self, algorithm_version: str = VECTOR_ALGORITHM_VERSION):
        if algorithm_version != VECTOR_ALGORITHM_VERSION:
            raise ValueError(f"Unknown vector algorithm version: {algorithm_version}")
        self._docs: dict[str, str] = {}
        self._vecs: dict[str, dict[str, float]] = {}

    def add(self, doc_id: str, text: str) -> None:
        self._docs[doc_id] = text
        self._vecs[doc_id] = _features(text)

    def add_many(self, docs: Iterable[tuple[str, str]]) -> None:
        for doc_id, text in docs:
            self.add(doc_id, text)

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        qv = _features(query)
        scored = []
        for doc_id, vec in self._vecs.items():
            scored.append((doc_id, cosine_similarity(qv, vec)))
        scored.sort(key=lambda t: -t[1])
        return [(i, s) for i, s in scored if s > 0.0][:top_k]

    def state_hash(self) -> str:
        from . import canonical as C
        ordered = {k: self._docs[k] for k in sorted(self._docs)}
        return C.digest(ordered, "memory.vectorindex")
