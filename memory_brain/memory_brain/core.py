"""core.py -- MemoryBrain facade: the integration contract.

This is the deterministic business-logic layer that owns the memory commit
path. It composes the ledger, the SQLite projection store, provenance, and the
engines (dedup, contradiction, consolidation), and enforces governance on every
authoritative mutation.

An LLM is only an advisory producer of claims; this class is what actually
writes memories, and every write is an append-only ledger event. Governed
operations (supersede by an LLM, retract, sensitive writes) are first routed to
the human review queue; an APPROVE decision then applies the pending action
through the SAME deterministic commit path.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from . import canonical, normalize, schema
from .models import (Confidence, _id, iso_now, MEMORY_TYPES, MEMORY_STATUSES)
from .council import require_ratified as _council_require, \
    is_council_required as _council_required_op

from .ledger import Ledger
from .provenance import Provenance
from .graph import KnowledgeGraph
from .review import ReviewQueue, DECISIONS
from .verify import Verifier
from .health import Health
from .governance import Governance, GovernanceDecision
from . import consolidate as cons_mod
from .ingest import RawClaim  # noqa: F401 (re-export surface)


class MemoryBrain:
    def __init__(self, db_path: str = ":memory:", *,
                 allow_auto_commit: bool = False,
                 require_review_for_sensitive: bool = True,
                 require_council_for_irreversible: bool = False):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        schema.load_schema(self.conn)
        self.ledger = Ledger(self.conn)
        self.graph = KnowledgeGraph(self.conn)
        self.review = ReviewQueue(self.conn, self.ledger)
        self.verify = Verifier(self.conn, self.ledger)
        self.health = Health(self.conn, self.ledger)
        self.governance = Governance(
            allow_auto_commit=allow_auto_commit,
            require_review_for_sensitive=require_review_for_sensitive)
        # When True, irreversible mutations (retract/delete) require verified
        # council quorum, NOT a bare human APPROVE. Off by default to preserve
        # the existing single-reviewer path; on, it enforces the authority gate.
        self.council_gated = require_council_for_irreversible

    # -- sources ----------------------------------------------------------
    def register_source(self, source_type: str, external_ref: Optional[str] = None,
                        author: Optional[str] = None,
                        observed_at: Optional[str] = None,
                        source_id: Optional[str] = None) -> str:
        sid = source_id or _id("src")
        self.conn.execute(
            "INSERT INTO memory_sources (source_id, source_type, external_ref,"
            " author, observed_at) VALUES (?,?,?,?,?)",
            (sid, source_type, external_ref, author, observed_at))
        self.conn.commit()
        return sid

    # -- public commit ----------------------------------------------------
    def remember(self, content: str, *, memory_type: Optional[str] = None,
                 source_id: Optional[str] = None,
                 provenance: Optional[Provenance] = None,
                 confidence: Optional[Confidence] = None,
                 importance: Optional[float] = None,
                 actor: Optional[str] = None, is_llm: bool = False,
                 sensitive: bool = False,
                 supersedes: Optional[str] = None,
                 status: str = "ACTIVE",
                 verified: Optional[bool] = None) -> dict:
        """Advisory-safe memory commit.

        Returns either {"committed": True, ...} or
        {"requires_review": True, item_id: ...} when governance routes the
        write to the human review queue. On APPROVE of that item the write is
        applied by apply_review_decision through the same deterministic path.
        """
        mtype = (memory_type or _infer_type(content)).upper()
        if mtype not in MEMORY_TYPES and not mtype.startswith("X_"):
            raise ValueError(f"Unknown memory type: {mtype}")
        if status not in MEMORY_STATUSES:
            raise ValueError(f"Unknown status: {status}")

        conf = confidence or Confidence(source=0.5, extraction=0.5, inference=0.0)
        imp = importance if importance is not None else 0.4
        prov = provenance or _default_provenance(actor)
        if verified is True:
            prov.add("VERIFICATION", "human-confirmed verification", actor=actor)
        elif verified is False:
            status = "UNVERIFIED"

        is_mutation = supersedes is not None or status in ("SUPERSEDED", "RETRACTED")
        gate = self.governance.evaluate(
            "supersede" if is_mutation else "create",
            actor=actor, is_llm=is_llm, sensitive=sensitive,
            confidence=conf.current)

        if gate.requires_review:
            action = {
                "op": "remember", "content": content, "memory_type": mtype,
                "source_id": source_id, "supersedes": supersedes,
                "status": status, "sensitive": sensitive,
                "is_llm": is_llm, "actor": actor,
                "provenance_kinds": [l.kind for l in prov.links],
                "source_id": source_id,
            }
            item = self.review.enqueue("memory_proposal", {
                **action, "confidence": conf.to_dict(), "importance": imp,
                "reason": gate.reason,
            })
            return {"requires_review": True, "item_id": item.item_id,
                    "reason": gate.reason, "action": action}

        return self._commit_remember(content, mtype=mtype, source_id=source_id,
                                     conf=conf, imp=imp, actor=actor,
                                     is_llm=is_llm, sensitive=sensitive,
                                     supersedes=supersedes, status=status,
                                     provenance_kinds=[l.kind for l in prov.links])

    # -- internal deterministic commit (bypasses the review gate) ----------
    def _commit_remember(self, content: str, *, mtype: str,
                         source_id: Optional[str],
                         conf: Confidence, imp: float,
                         actor: Optional[str], is_llm: bool,
                         sensitive: bool, supersedes: Optional[str],
                         status: str, provenance_kinds: list[str]) -> dict:
        # Register a source record if none supplied.
        if source_id is None:
            source_id = self.register_source("adapter", author=actor)

        # Dedup: reject an exact duplicate (except an explicit supersede write).
        if supersedes is None:
            dup = self._find_exact_duplicate(content)
            if dup is not None:
                return {"committed": False, "duplicate_of": dup,
                        "memory_id": dup}

        content_hash = normalize.content_hash(content)
        norm = normalize.normalize_text(content)
        now = iso_now()
        prev_mem = self._get(supersedes) if supersedes else None

        payload = {
            "content": content,
            "memory_type": mtype,
            "source_id": source_id,
            "content_hash": content_hash,
            "confidence": conf.to_dict(),
            "importance": imp,
            "supersedes": supersedes,
            "actor": actor,
            "is_llm": is_llm,
            "sensitive": sensitive,
            "provenance_kinds": provenance_kinds,
        }
        ev = self.ledger.append(
            "MEMORY_CREATED" if prev_mem is None else "MEMORY_SUPERSEDED",
            payload)

        memory_id = _id("mem")
        cur_conf = conf.current
        self.conn.execute(
            "INSERT INTO memories (memory_id, memory_type, content,"
            " normalized_content, status, confidence, importance, created_at,"
            " updated_at, event_id, supersedes, superseded_by, source_id,"
            " content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (memory_id, mtype, content, norm, status, cur_conf, imp, now, now,
             ev.event_id, supersedes, None, source_id, content_hash))
        self.conn.execute(
            "INSERT INTO memory_versions (version_id, memory_id, status,"
            " content, confidence, importance, captured_at, event_id)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (_id("ver"), memory_id, status, content, cur_conf, imp, now,
             ev.event_id))

        if prev_mem is not None:
            self._set_status(supersedes, "SUPERSEDED")
            self._link(supersedes, memory_id, "SUPERSEDES", ev.event_id)
            self.conn.execute(
                "UPDATE memories SET superseded_by=? WHERE memory_id=?",
                (memory_id, supersedes))

        self.conn.commit()
        self._scan_contradictions(memory_id, content)
        return {"committed": True, "memory_id": memory_id,
                "event_id": ev.event_id, "content_hash": content_hash,
                "status": status}

    # -- governed mutation: retract ----------------------------------------
    def retract(self, memory_id: str, reason: str, actor: str) -> dict:
        """Request a retraction. Irreversible -> always routes to review."""
        mem = self._get(memory_id)
        if mem is None:
            raise KeyError(f"memory {memory_id} not found")
        item = self.review.enqueue("retract_request", {
            "op": "retract", "memory_id": memory_id, "reason": reason,
            "actor": actor})
        return {"requires_review": True, "item_id": item.item_id}

    # -- human review application ------------------------------------------
    def apply_review_decision(self, item_id: str, decision: str,
                              decided_by: str) -> dict:
        """A human decision; if APPROVE, apply the pending governed action.

        The decision and the resulting mutation are each their own ledger
        event. A non-approve decision never mutates state.

        FAIL-CLOSED COUNCIL GATE: when this brain is council-gated and the
        action is irreversible (retract/delete), a bare human APPROVE is NOT
        authority. The review item is recorded as decided, but the mutation is
        NOT applied until a verified council quorum ratifies it (see
        ratify_council). This is the memory_brain analogue of the Pocket OS
        invariant: a bare approval may PROPOSE; only verified consensus
        AUTHORIZES the irreversible mutation.
        """
        if decision not in DECISIONS:
            raise ValueError(f"Unknown decision: {decision}")
        item = self.review.decide(item_id, decision, decided_by)
        result = {"item_id": item.item_id, "status": item.status}
        if decision == "APPROVE":
            action = self._action_from_item(item)
            op = action.get("op", "")
            if self.council_gated and _council_required_op(op):
                # A human approve alone may NOT mutate an irreversible memory.
                result["applied"] = None
                result["council_required"] = True
                result["reason"] = (
                    "irreversible operation requires verified council quorum; "
                    "submit council signatures via ratify_council")
            else:
                result["applied"] = self._apply_action(action, decided_by)
        else:
            result["applied"] = None
        return result

    def ratify_council(self, item_id: str, signatures: dict[str, str]) -> dict:
        """Authoritatively ratify a council-required review item.

        Verifies a threshold of DISTINCT council members under active keys for
        the bound candidate (memory_id + operation). On quorum, applies the
        pending irreversible mutation and records a MEMORY_COUNCIL_RATIFIED
        ledger event. This is the ONLY path that authorizes an irreversible
        mutation on a council-gated brain.
        """
        if not self.council_gated:
            return {"ratified": False, "reason": "council gating not enabled"}
        import json as _json
        # find the review item
        row = self.conn.execute(
            "SELECT * FROM review_queue WHERE item_id=?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(f"No review item {item_id}")
        action = _json.loads(row["ref_json"])
        op = action.get("op", "")
        memory_id = action.get("memory_id")
        if not _council_required_op(op) or not memory_id:
            return {"ratified": False, "reason": f"operation '{op}' is not council-required"}
        if not _council_require(memory_id, op, signatures):
            return {"ratified": False,
                    "reason": "COUNCIL_QUORUM_NOT_MET or invalid signatures"}
        # quorum verified -> record ratification + apply the mutation
        ev = self.ledger.append(
            "MEMORY_COUNCIL_RATIFIED",
            {"item_id": item_id, "memory_id": memory_id, "operation": op,
             "authority": "COUNCIL_QUORUM"})
        self._apply_action(action, "council-quorum")
        return {"ratified": True, "event_id": ev.event_id,
                "memory_id": memory_id, "operation": op}

    def _action_from_item(self, item):
        import json as _json
        return _json.loads(item.ref_json)

    def _apply_action(self, action: dict, decided_by: str) -> dict:
        op = action.get("op")
        if op == "remember":
            conf = Confidence(**{
                k: v for k, v in action.get("confidence", {}).items()
                if k in ("source", "extraction", "inference")})
            return self._commit_remember(
                action["content"], mtype=action["memory_type"],
                source_id=action.get("source_id"), conf=conf,
                imp=action.get("importance", 0.4),
                actor=decided_by, is_llm=action.get("is_llm", False),
                sensitive=action.get("sensitive", False),
                supersedes=action.get("supersedes"),
                status=action.get("status", "ACTIVE"),
                provenance_kinds=action.get("provenance_kinds", []))
        if op == "retract":
            memory_id = action["memory_id"]
            reason = action.get("reason", "")
            mem = self._get(memory_id)
            if mem is None:
                raise KeyError(f"memory {memory_id} not found")
            ev = self.ledger.append(
                "MEMORY_RETRACTED",
                {"memory_id": memory_id, "reason": reason, "actor": decided_by})
            self._set_status(memory_id, "RETRACTED")
            self.conn.commit()
            return {"retracted": True, "memory_id": memory_id,
                    "event_id": ev.event_id}
        raise ValueError(f"Unknown governed action: {op}")

    # -- reads -------------------------------------------------------------
    def get(self, memory_id: str) -> Optional[dict]:
        return self._get(memory_id)

    def _get(self, memory_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
        return dict(row) if row else None

    def _find_exact_duplicate(self, content: str) -> Optional[str]:
        ch = normalize.content_hash(content)
        row = self.conn.execute(
            "SELECT memory_id FROM memories WHERE content_hash=? AND "
            "status='ACTIVE'", (ch,)).fetchone()
        return row["memory_id"] if row else None

    def active_memories(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE status='ACTIVE'").fetchall()
        return [dict(r) for r in rows]

    def history(self, memory_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM memory_versions WHERE memory_id=? "
            "ORDER BY captured_at ASC", (memory_id,)).fetchall()
        return [dict(r) for r in rows]

    def provenance(self, memory_id: str) -> list[dict]:
        mem = self._get(memory_id)
        if mem is None:
            return []
        src = self.conn.execute(
            "SELECT * FROM memory_sources WHERE source_id=?",
            (mem.get("source_id"),)).fetchone()
        return [{"kind": "SOURCE",
                 "source_id": src["source_id"] if src else None}]

    # -- internal helpers ----------------------------------------------------
    def _set_status(self, memory_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE memories SET status=?, updated_at=? WHERE memory_id=?",
            (status, iso_now(), memory_id))

    def _link(self, a: str, b: str, rel_type: str, event_id: str) -> None:
        self.graph.add_edge(a, b, rel_type, event_id=event_id)

    def _scan_contradictions(self, memory_id: str, content: str) -> None:
        mem = self._get(memory_id)
        mtype = mem["memory_type"] if mem else "FACT"
        if mtype not in ("FACT", "BELIEF", "DECISION", "REQUIREMENT"):
            return
        others = self.conn.execute(
            "SELECT memory_id, content FROM memories "
            "WHERE status='ACTIVE' AND memory_id<>?", (memory_id,)).fetchall()
        from .dedup import _possible_contradiction
        for o in others:
            if not _possible_contradiction(content, o["content"]):
                continue
            item = self.review.enqueue(
                "possible_contradiction",
                {"memory_a": memory_id, "memory_b": o["memory_id"],
                 "content_a": content, "content_b": o["content"]})
            ev = self.ledger.append(
                "MEMORY_CONTRADICTION_DETECTED",
                {"memory_a": memory_id, "memory_b": o["memory_id"],
                 "review_item": item.item_id})
            self.conn.execute(
                "INSERT INTO memory_contradictions (contradiction_id, memory_a,"
                " memory_b, status, detected_at, event_id) VALUES (?,?,?,?,?,?)",
                (_id("con"), memory_id, o["memory_id"], "UNRESOLVED", iso_now(),
                 ev.event_id))
            self.conn.commit()

    def consolidate(self, memory_ids: list[str], reason: str,
                    actor: Optional[str] = None) -> dict:
        mems = [self._get(m) for m in memory_ids]
        if any(m is None for m in mems):
            raise KeyError("one or more memories not found")
        contents = [m["content"] for m in mems]
        spec = cons_mod.ConsolidationSpec(
            memory_ids=memory_ids, contents=contents, reason=reason, agent=actor)
        res = cons_mod.run(spec)
        avg_conf = round(sum(float(m["confidence"]) for m in mems) / len(mems), 4)
        output_memory = res.output_content

        payload = {"consolidation_id": res.consolidation_id,
                   "input_memories": memory_ids, "output_content": output_memory,
                   "algorithm_version": res.algorithm_version, "reason": reason,
                   "actor": actor, "avg_confidence": avg_conf}
        ev = self.ledger.append("MEMORY_CONSOLIDATED", payload)

        mid = _id("mem")
        now = iso_now()
        ch = normalize.content_hash(output_memory)
        self.conn.execute(
            "INSERT INTO memories (memory_id, memory_type, content,"
            " normalized_content, status, confidence, importance, created_at,"
            " updated_at, event_id, source_id, content_hash) VALUES"
            " (?,?,?,?,?,?,?,?,?,?,?,?)",
            (mid, "SUMMARY", output_memory, normalize.normalize_text(output_memory),
             "ACTIVE", avg_conf, 0.5, now, now, ev.event_id, None, ch))
        for m in memory_ids:
            self.graph.add_edge(m, mid, "DERIVED_FROM", event_id=ev.event_id)
        self.conn.execute(
            "INSERT INTO memory_consolidations (consolidation_id, input_memories,"
            " output_memory, algorithm_version, agent, created_at, confidence,"
            " reason, event_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (res.consolidation_id, canonical.canonical_json(memory_ids), mid,
             res.algorithm_version, actor, now, avg_conf, reason, ev.event_id))
        self.conn.commit()
        return {"consolidated": True, "consolidation_id": res.consolidation_id,
                "output_memory": mid, "event_id": ev.event_id}


def _infer_type(content: str) -> str:
    from .classify import guess_memory_type
    return guess_memory_type(content)


def _default_provenance(actor: Optional[str]) -> Provenance:
    prov = Provenance()
    prov.add("SOURCE", "memory_brain.commit", actor=actor)
    prov.add("EXTRACTION", "structured commit")
    return prov
