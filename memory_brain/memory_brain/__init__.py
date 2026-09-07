"""Memory Second Brain.

A ledger-first, provenance-aware, cryptographically auditable memory subsystem.
The authoritative history is an append-only hash-chained ledger; the searchable
memory store, graph, and vector index are all derived projections rebuildable
from the ledger.

Reuses the SAIL canonical serialization authority (RFC 8785 JCS-style, domain-
tagged SHA-256) as the sole hashing path. See core.MemoryBrain for the facade.
"""

__version__ = "1.0.0"

from .core import MemoryBrain  # noqa: F401
from .ledger import Ledger, LedgerIntegrityError  # noqa: F401
from .canonical import digest, canonical_json  # noqa: F401
from .models import Confidence, MemoryRecord  # noqa: F401
from .provenance import Provenance, ProvenanceLink  # noqa: F401
from .api import MemoryAPI  # noqa: F401

__all__ = ["MemoryBrain", "Ledger", "LedgerIntegrityError", "MemoryAPI",
           "digest", "canonical_json", "Confidence", "Provenance",
           "ProvenanceLink", "MemoryRecord", "__version__"]
