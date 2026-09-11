"""ingest.py -- modular ingestion adapters.

Every ingestion path produces the SAME intermediate representation: a list of
``RawClaim`` records (text + optional structured fields + provenance links).
Downstream, claims flow through normalize -> classify -> dedup -> contradiction
-> commit. Adapters are modular so new source kinds (pdf, url, git, csv,
telemetry, agent output) are added without touching the pipeline.

Failure handling: an adapter that throws is surfaced as a FAILED claim and is
never silently discarded -- the caller decides whether to retry or quarantine.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Iterable, Optional

from .provenance import Provenance, ProvenanceLink


@dataclass
class RawClaim:
    text: str
    memory_type_hint: Optional[str] = None
    source_id: Optional[str] = None
    provenance: Provenance = field(default_factory=Provenance)
    extra: dict = field(default_factory=dict)


class IngestionError(Exception):
    """Raised when an ingestion adapter fails; the claim is NOT discarded."""


# --- text / markdown -----------------------------------------------------
def ingest_text(text: str, source_id: Optional[str] = None,
                author: Optional[str] = None,
                external_ref: Optional[str] = None) -> list[RawClaim]:
    """Split free text / markdown into claim-sized records by paragraphs/lines."""
    out: list[RawClaim] = []
    # Split on blank lines and markdown headers; drop pure markup lines.
    for block in _split_blocks(text):
        cleaned = _clean_block(block)
        if not cleaned:
            continue
        prov = Provenance()
        prov.add("SOURCE", "raw text", actor=author, source_ref=external_ref)
        prov.add("EXTRACTION", "paragraph claim extraction")
        out.append(RawClaim(text=cleaned, source_id=source_id, provenance=prov))
    return out


def _split_blocks(text: str) -> list[str]:
    import re
    # Keep code fences together; split otherwise on blank lines.
    blocks: list[str] = []
    fence: Optional[str] = None
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if fence is None:
                if buf:
                    blocks.append("\n".join(buf))
                    buf = []
                fence = line.strip()
                buf.append(line)
            else:
                buf.append(line)
                blocks.append("\n".join(buf))
                buf = []
                fence = None
            continue
        buf.append(line)
        if fence is None and line.strip() == "":
            blocks.append("\n".join(buf))
            buf = []
    if buf:
        blocks.append("\n".join(buf))
    return [b for b in blocks if b.strip()]


def _clean_block(block: str) -> str:
    import re
    lines = [l for l in block.splitlines()
             if not l.lstrip().startswith(("#", ">", "-", "*", "`"))]
    text = " ".join(lines).strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# --- structured JSON -----------------------------------------------------
def ingest_json(payload, source_id: Optional[str] = None,
                author: Optional[str] = None) -> list[RawClaim]:
    """Ingest structured JSON: either a list of claim strings, a dict, or
    {'claims': [...]} with per-claim provenance. Deterministic traversal."""
    out: list[RawClaim] = []

    def walk(obj, path: str = "$"):
        if isinstance(obj, str):
            prov = Provenance()
            prov.add("SOURCE", f"json {path}", actor=author)
            prov.add("EXTRACTION", "json string field")
            out.append(RawClaim(text=obj, source_id=source_id, provenance=prov))
        elif isinstance(obj, dict):
            for k in sorted(obj.keys()):
                walk(obj[k], f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                walk(item, f"{path}[{i}]")

    walk(payload)
    return out


# --- conversation transcript ---------------------------------------------
def ingest_conversation(messages: Iterable[dict], source_id: Optional[str] = None,
                        author_field: str = "actor") -> list[RawClaim]:
    """Ingest a conversation: list of {actor, text} turns."""
    out: list[RawClaim] = []
    for turn in messages:
        actor = turn.get(author_field, turn.get("role", "unknown"))
        text = turn.get("text", turn.get("content", ""))
        if not text or not str(text).strip():
            continue
        prov = Provenance()
        prov.add("SOURCE", "conversation turn", actor=str(actor))
        prov.add("OBSERVATION", "transcript")
        prov.add("EXTRACTION", "turn claim extraction")
        out.append(RawClaim(text=str(text).strip(), source_id=source_id,
                            provenance=prov))
    return out


# --- CSV -----------------------------------------------------------------
def ingest_csv(data: str, source_id: Optional[str] = None,
               text_columns: Optional[list[str]] = None) -> list[RawClaim]:
    """Ingest CSV text. Each row becomes claims from chosen text columns."""
    out: list[RawClaim] = []
    reader = csv.DictReader(io.StringIO(data))
    cols = text_columns or [c for c in (reader.fieldnames or [])]
    for row in reader:
        parts = []
        for c in cols:
            if c in row and row[c] and str(row[c]).strip():
                parts.append(f"{c}: {row[c].strip()}")
        if not parts:
            continue
        prov = Provenance()
        prov.add("SOURCE", "csv row", source_ref=source_id)
        prov.add("EXTRACTION", "csv field join")
        out.append(RawClaim(text=" | ".join(parts), source_id=source_id,
                            provenance=prov))
    return out


def claims_to_json(claims: list[RawClaim]) -> str:
    return json.dumps([
        {
            "text": c.text,
            "memory_type_hint": c.memory_type_hint,
            "source_id": c.source_id,
            "provenance": c.provenance.to_dict(),
            "extra": c.extra,
        }
        for c in claims
    ], indent=2)
