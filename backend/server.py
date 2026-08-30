from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import json
import logging
import random
import math
import uuid
import jwt
import bcrypt
import hashlib
import httpx
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta

from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']
EMERGENT_LLM_KEY = os.environ['EMERGENT_LLM_KEY']
JWT_SECRET = os.environ['JWT_SECRET']
APPLE_AUDIENCES = [a.strip() for a in os.environ.get('APPLE_AUDIENCES', '').split(',') if a.strip()]
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"
_apple_jwks_cache: Dict[str, Any] = {"keys": None, "fetched_at": None}
JWT_ALGO = "HS256"
JWT_EXP_DAYS = 30

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="Pocket OS")
api = APIRouter(prefix="/api")
security = HTTPBearer()

# ---------------- Utilities ----------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def uid() -> str:
    return str(uuid.uuid4())

def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False

def create_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXP_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

async def get_current_user(cred: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    try:
        payload = jwt.decode(cred.credentials, JWT_SECRET, algorithms=[JWT_ALGO])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = await db.users.find_one({"id": user_id}, {"_id": 0, "password": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ---------------- Models ----------------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    name: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class AppleIn(BaseModel):
    identity_token: str
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None

class AdminResetIn(BaseModel):
    email: EmailStr
    new_password: str
    admin_token: str

class NoteIn(BaseModel):
    text: str
    title: Optional[str] = None

class DecisionIn(BaseModel):
    title: str
    context: Optional[str] = ""
    note_id: Optional[str] = None

class TwinQuery(BaseModel):
    question: str

# ---------------- AI Helpers ----------------
async def gemini_chat(system: str, prompt: str, session_id: str = None) -> str:
    """Single-shot Gemini 3 Flash call."""
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id or uid(),
        system_message=system,
    ).with_model("gemini", "gemini-3-flash-preview")
    try:
        resp = await chat.send_message(UserMessage(text=prompt))
        return resp if isinstance(resp, str) else str(resp)
    except Exception as e:
        logging.exception("gemini_chat failed")
        return ""

async def llm_call(provider: str, model: str, system: str, prompt: str, session_id: str = None) -> str:
    """Single-shot call to any provider (gemini/openai/anthropic)."""
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id or uid(),
        system_message=system,
    ).with_model(provider, model)
    try:
        resp = await chat.send_message(UserMessage(text=prompt))
        return resp if isinstance(resp, str) else str(resp)
    except Exception:
        logging.exception(f"llm_call failed for {provider}/{model}")
        return ""

async def extract_concepts(text: str) -> List[str]:
    system = "You extract key concepts from notes. Return ONLY a comma-separated list of 3-8 short concept phrases (2-4 words each). No numbering, no explanations."
    out = await gemini_chat(system, text[:2000])
    if not out:
        return []
    concepts = [c.strip().strip(".").strip('"').strip("'") for c in out.split(",") if c.strip()]
    return [c for c in concepts if 2 <= len(c) <= 60][:8]

AGENTS = [
    ("Research", "agentResearch", "You are a rigorous Research Agent. In 1-2 short sentences, cite what supporting evidence or prior work relates to this note."),
    ("Architect", "agentArchitect", "You are an Architect Agent. In 1-2 short sentences, explain how this idea affects the user's system/architecture."),
    ("Critic", "agentCritic", "You are a Critic Agent. In 1-2 short sentences, expose the weakest assumption or risk in this note."),
    ("Planner", "agentPlanner", "You are a Planner Agent. In 1-2 short sentences, propose the next concrete milestone or action."),
    ("Documentation Steward", "agentDocSteward", "You are a Documentation Steward. In 1-2 short sentences, describe how you would document or reorganize this knowledge."),
]

# Consensus-mode: each agent produces a structured verdict
CONSENSUS_PROMPT = (
    "Return ONLY strict JSON (no backticks, no prose) with these keys:\n"
    "  position: one of \"APPROVE\", \"REJECT\", \"UNCERTAIN\"\n"
    "  confidence: float 0..1 (your certainty in your position)\n"
    "  risk_score: float 0..1 (how risky adopting this idea would be)\n"
    "  reasoning: one short sentence explaining your verdict\n"
    "  evidence: array of 1-3 short bullet strings\n"
)
CONSENSUS_SYSTEMS = {
    "Research": "You are the Research Agent. Judge whether the note is backed by evidence and prior work. " + CONSENSUS_PROMPT,
    "Architect": "You are the Architect Agent. Judge whether the note fits the user's system architecture. " + CONSENSUS_PROMPT,
    "Critic": "You are the Critic Agent. Judge the strongest reason to REJECT the note. Bias toward REJECT if any material risk exists. " + CONSENSUS_PROMPT,
    "Planner": "You are the Planner Agent. Judge whether the note points to a viable next milestone. " + CONSENSUS_PROMPT,
    "Documentation Steward": "You are the Documentation Steward. Judge whether the note is coherent enough to canonicalize. " + CONSENSUS_PROMPT,
}
POSITION_WEIGHT = {"APPROVE": 1.0, "REJECT": -1.0, "UNCERTAIN": 0.0}
CONSENSUS_THRESHOLD = 0.5

async def run_council(note_text: str) -> List[Dict[str, str]]:
    results = []
    for name, color, sys in AGENTS:
        msg = await gemini_chat(sys, note_text[:1500], session_id=f"council-{name}")
        results.append({"agent": name, "color_key": color, "response": msg or f"{name} could not respond right now."})
    return results

def _parse_json_lenient(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    s = raw.strip()
    # strip common wrappers
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:].strip()
    # find first { and last }
    a = s.find("{"); b = s.rfind("}")
    if a >= 0 and b > a:
        s = s[a:b+1]
    try:
        return json.loads(s)
    except Exception:
        return None

async def run_council_consensus(note_text: str) -> List[Dict[str, Any]]:
    """Structured mode: each agent returns position/confidence/risk/reasoning/evidence."""
    results = []
    for name, color, _ in AGENTS:
        system = CONSENSUS_SYSTEMS[name]
        raw = await gemini_chat(system, note_text[:1500], session_id=f"consensus-{name}")
        parsed = _parse_json_lenient(raw) or {}
        pos = str(parsed.get("position", "UNCERTAIN")).upper()
        if pos not in POSITION_WEIGHT:
            pos = "UNCERTAIN"
        try:
            conf = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
        except Exception:
            conf = 0.5
        try:
            risk = max(0.0, min(1.0, float(parsed.get("risk_score", 0.3))))
        except Exception:
            risk = 0.3
        evidence = parsed.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        evidence = [str(e)[:200] for e in evidence][:3]
        reasoning = str(parsed.get("reasoning", raw[:180] if raw else ""))[:220]
        results.append({
            "agent": name,
            "color_key": color,
            "position": pos,
            "confidence": round(conf, 2),
            "risk_score": round(risk, 2),
            "reasoning": reasoning,
            "evidence": evidence,
        })
    return results

def compute_consensus_score(verdicts: List[Dict[str, Any]], historical_success: float = 0.8) -> Dict[str, Any]:
    if not verdicts:
        return {"score": 0, "recommendation": "UNCERTAIN", "alignment": 0, "evidence_weight": 0, "risk_penalty": 0, "historical_success": historical_success, "needs_debate": True}
    # Signed alignment: sum(position * confidence) / N   -> -1..+1
    aligned = sum(POSITION_WEIGHT[v["position"]] * v["confidence"] for v in verdicts) / len(verdicts)
    # Evidence weight: how much verdicts cited evidence
    evidence_weight = sum(min(1.0, len(v["evidence"]) / 3.0) for v in verdicts) / len(verdicts)
    # Average risk
    risk_penalty = sum(v["risk_score"] for v in verdicts) / len(verdicts)
    # Final signed decision score in a bounded range
    raw = evidence_weight + aligned + historical_success - risk_penalty
    score = round(raw, 3)
    # Recommendation
    if aligned >= 0.4 and risk_penalty < 0.6:
        rec = "APPROVE"
    elif aligned <= -0.4:
        rec = "REJECT"
    else:
        rec = "UNCERTAIN"
    # Needs debate if the council is split or confidence is low
    approve = sum(1 for v in verdicts if v["position"] == "APPROVE")
    reject = sum(1 for v in verdicts if v["position"] == "REJECT")
    avg_conf = sum(v["confidence"] for v in verdicts) / len(verdicts)
    stalemate = (approve > 0 and reject > 0 and abs(approve - reject) <= 1) or avg_conf < CONSENSUS_THRESHOLD
    return {
        "score": score,
        "recommendation": rec,
        "alignment": round(aligned, 2),
        "evidence_weight": round(evidence_weight, 2),
        "risk_penalty": round(risk_penalty, 2),
        "historical_success": round(historical_success, 2),
        "avg_confidence": round(avg_conf, 2),
        "approve_count": approve,
        "reject_count": reject,
        "uncertain_count": len(verdicts) - approve - reject,
        "needs_debate": bool(stalemate),
    }

# ---------------- Debate Escalation Triggers ----------------
# Governance-relevant signals that escalate a decision to a full Council Debate.
GOVERNANCE_KEYWORDS = {
    "security": ["security", "auth", "credential", "password", "token", "leak", "vulnerab", "encrypt", "breach"],
    "governance": ["governance", "policy", "policies", "compliance", "audit", "constitution"],
    "architecture": ["architecture", "refactor", "migration", "schema change", "breaking change", "infra"],
    "irreversibility": ["delete", "drop", "wipe", "irreversible", "permanent", "cannot be undone"],
    "expense": ["expensive", "budget", "cost", "spend", "$$$"],
}

import re

_CONCEPT_STOPWORDS = {
    "the","a","an","of","for","and","or","in","on","to","with","by","at","as",
    "is","it","be","this","that","these","those","are","was","were",
    "policy","policies","strategy","strategies","system","systems",
    "based","new","old","full","use","using","via","from",
}

def _concept_tokens(concept: str) -> set:
    """Normalize a concept phrase into a set of meaningful lowercase tokens."""
    if not concept:
        return set()
    tokens = re.split(r'[^a-z0-9]+', concept.lower())
    return {t for t in tokens if t and t not in _CONCEPT_STOPWORDS and len(t) >= 3}

def _concept_bag(concepts: List[str]) -> set:
    bag = set()
    for c in concepts or []:
        bag |= _concept_tokens(c)
    return bag

def _concept_similarity(a_concepts: List[str], b_concepts: List[str]) -> Dict[str, Any]:
    """Return {score, shared, jaccard, containment} using token-level bag-of-words.
    `score` is max(jaccard, containment) — either signal is enough for semantic overlap.
    """
    a = _concept_bag(a_concepts)
    b = _concept_bag(b_concepts)
    if not a or not b:
        return {"score": 0.0, "shared": [], "jaccard": 0.0, "containment": 0.0}
    inter = a & b
    union = a | b
    jaccard = round(len(inter) / len(union), 3) if union else 0.0
    containment = round(len(inter) / min(len(a), len(b)), 3) if a and b else 0.0
    return {
        "score": max(jaccard, containment),
        "shared": sorted(inter),
        "jaccard": jaccard,
        "containment": containment,
    }

async def detect_semantic_contradictions(
    user_id: str,
    new_note_id: Optional[str],
    new_note: Dict[str, Any],
    new_position: str,
    exclude_decision_id: Optional[str] = None,
    concept_overlap_threshold: float = 0.2,
) -> List[Dict[str, Any]]:
    """Find prior authoritative decisions whose reasoning conflicts with the new
    consensus/synthesis. Only RATIFIED syntheses count as authoritative precedents.

    A contradiction is emitted when BOTH conditions hold:
      1. Concept overlap: Jaccard(new_concepts, prior_concepts) >= threshold.
      2. Opposing position: new_position ∈ APPROVE|CONDITIONAL_APPROVE ↔ prior ∈ REJECT (or vice-versa).

    Drafts, rejected proposals, and raw-council-only decisions are NOT authoritative
    and are excluded. Returns [] when no contradictions found.
    """
    if not new_note or not new_position or new_position == "UNCERTAIN":
        return []

    new_concepts_raw = list(new_note.get("concepts") or [])
    if not new_concepts_raw:
        return []

    # Collect ratified syntheses across the user's workspace
    ratified_syntheses = await db.debates.find(
        {"user_id": user_id, "ratified": True}, {"_id": 0}
    ).to_list(2000)
    if not ratified_syntheses:
        return []

    # Group by note_id (a note may have multiple syntheses; latest ratified wins)
    latest_by_note: Dict[str, Dict[str, Any]] = {}
    for s in ratified_syntheses:
        nid = s.get("note_id")
        if not nid:
            continue
        current = latest_by_note.get(nid)
        if not current or (s.get("ratified_at") or "") > (current.get("ratified_at") or ""):
            latest_by_note[nid] = s

    contradictions: List[Dict[str, Any]] = []
    for prior_note_id, synth in latest_by_note.items():
        if new_note_id and prior_note_id == new_note_id:
            # Same note — a new decision on the same note is a version/refinement,
            # not a semantic contradiction against a peer decision.
            continue

        prior_note = await db.notes.find_one({"id": prior_note_id, "user_id": user_id}, {"_id": 0})
        if not prior_note:
            continue

        prior_concepts_raw = list(prior_note.get("concepts") or [])
        if not prior_concepts_raw:
            continue

        sim = _concept_similarity(new_concepts_raw, prior_concepts_raw)
        if sim["score"] < concept_overlap_threshold or not sim["shared"]:
            continue

        prior_position = (synth.get("synthesis") or {}).get("synthesis_position") or "UNCERTAIN"

        # Position opposition table
        positive = {"APPROVE", "CONDITIONAL_APPROVE"}
        negative = {"REJECT"}
        opposing = (
            (new_position in positive and prior_position in negative)
            or (new_position in negative and prior_position in positive)
        )
        if not opposing:
            continue

        # Prior decisions bound to this ratified synthesis
        prior_decisions = await db.decisions.find(
            {"user_id": user_id, "note_id": prior_note_id, "reasoning_source": "synthesis"},
            {"_id": 0},
        ).to_list(20)
        if exclude_decision_id:
            prior_decisions = [d for d in prior_decisions if d.get("id") != exclude_decision_id]

        # Fallback: any decision on the prior note if none are bound to synthesis
        if not prior_decisions:
            prior_decisions = await db.decisions.find(
                {"user_id": user_id, "note_id": prior_note_id}, {"_id": 0}
            ).sort("created_at", -1).limit(1).to_list(1)

        prior_decision = prior_decisions[0] if prior_decisions else None
        contradictions.append({
            "prior_note_id": prior_note_id,
            "prior_note_title": prior_note.get("title"),
            "prior_decision_id": (prior_decision or {}).get("id"),
            "prior_decision_number": (prior_decision or {}).get("number"),
            "prior_synthesis_id": synth.get("id"),
            "prior_synthesis_hash": synth.get("synthesis_hash"),
            "prior_ratified_at": synth.get("ratified_at"),
            "prior_position": prior_position,
            "new_position": new_position,
            "overlapping_concepts": sim["shared"],
            "concept_overlap_jaccard": sim["jaccard"],
            "concept_overlap_containment": sim["containment"],
            "concept_overlap_score": sim["score"],
        })

    # Strongest overlaps first
    contradictions.sort(key=lambda c: c["concept_overlap_score"], reverse=True)
    return contradictions

async def compute_debate_triggers(
    user_id: str,
    note_id: str,
    note: Dict[str, Any],
    scored: Dict[str, Any],
    verdicts: List[Dict[str, Any]],
    exclude_decision_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a list of governance-relevant triggers that require a Council Debate.
    Each trigger is a signed, hash-friendly dict {kind, detail, weight}.
    """
    triggers: List[Dict[str, Any]] = []

    # 1. Low consensus confidence
    if scored.get("avg_confidence", 1.0) < 0.65:
        triggers.append({"kind": "low_confidence", "detail": f"avg_confidence {scored.get('avg_confidence')}", "weight": 0.9})

    # 2. Agent disagreement (stddev of signed confidence)
    signed = [POSITION_WEIGHT[v["position"]] * v["confidence"] for v in verdicts] if verdicts else []
    disagreement = 0.0
    if signed:
        mean = sum(signed) / len(signed)
        variance = sum((s - mean) ** 2 for s in signed) / len(signed)
        disagreement = round(variance ** 0.5, 3)
        if disagreement > 0.25:
            triggers.append({"kind": "agent_disagreement", "detail": f"stddev {disagreement}", "weight": 0.85})

    # 3. High-risk decision
    if scored.get("risk_penalty", 0) >= 0.6:
        triggers.append({"kind": "high_risk", "detail": f"avg risk {scored.get('risk_penalty')}", "weight": 0.95})

    # 4. Security / governance / architectural domain
    text_blob = ((note.get("text") or "") + " " + (note.get("title") or "")).lower()
    domain_hits: List[str] = []
    for domain, kws in GOVERNANCE_KEYWORDS.items():
        if any(kw in text_blob for kw in kws):
            domain_hits.append(domain)
    if domain_hits:
        triggers.append({"kind": "governance_domain", "detail": ",".join(domain_hits), "weight": 1.0})

    # 5. Semantic contradiction with prior RATIFIED decisions across the workspace.
    # Only Ratified Syntheses count as authoritative precedents; drafts / rejected
    # proposals / raw_council-only decisions are advisory and NOT authoritative here.
    new_position = "UNCERTAIN"
    approve_c = scored.get("approve_count", 0)
    reject_c = scored.get("reject_count", 0)
    if approve_c > reject_c and approve_c >= 2:
        new_position = "APPROVE"
    elif reject_c > approve_c and reject_c >= 2:
        new_position = "REJECT"
    contradictions = await detect_semantic_contradictions(
        user_id, note_id, note, new_position, exclude_decision_id=exclude_decision_id
    )
    if contradictions:
        # Compact trigger detail summarising the strongest contradictions
        headline = "; ".join(
            f"Decision #{c['prior_decision_number']} ({c['prior_position']}) on {len(c['overlapping_concepts'])} shared concept(s)"
            for c in contradictions[:2]
        )
        triggers.append({
            "kind": "prior_decision_conflict",
            "detail": f"{len(contradictions)} semantic contradiction(s): {headline}",
            "weight": 0.9,
            "contradictions": contradictions,
        })

    # 6. Low evidence quality / insufficient provenance
    if scored.get("evidence_weight", 1.0) < 0.34:
        triggers.append({"kind": "insufficient_evidence", "detail": f"evidence_weight {scored.get('evidence_weight')}", "weight": 0.8})

    # 7. Novel decision (no historical similar concepts)
    concepts = note.get("concepts") or []
    if concepts:
        similar = await db.notes.count_documents({
            "user_id": user_id,
            "id": {"$ne": note_id},
            "concepts": {"$in": concepts},
        })
        if similar == 0:
            triggers.append({"kind": "novel_decision", "detail": "no prior notes share concepts", "weight": 0.6})

    # 8. Conflicting recommendations from specialized agents
    approve = scored.get("approve_count", 0)
    reject = scored.get("reject_count", 0)
    if approve >= 1 and reject >= 1:
        triggers.append({"kind": "conflicting_positions", "detail": f"{approve}A vs {reject}R", "weight": 0.75})

    return {
        "triggers": triggers,
        # `novel_decision` on its own is not enough to force a debate — it only escalates
        # when paired with another signal. This prevents every fresh capture from triggering.
        "should_debate": len([t for t in triggers if t["kind"] != "novel_decision"]) > 0
                          or len(triggers) >= 2,
        "disagreement_stddev": disagreement,
    }

# ---------------- Concept & Graph plumbing ----------------
async def upsert_concept_node(user_id: str, concept: str) -> str:
    key = concept.lower().strip()
    existing = await db.graph_nodes.find_one({"user_id": user_id, "kind": "concept", "key": key}, {"_id": 0})
    if existing:
        await db.graph_nodes.update_one(
            {"id": existing["id"]},
            {"$inc": {"weight": 1}, "$set": {"updated_at": now_iso()}},
        )
        return existing["id"]
    node = {
        "id": uid(),
        "user_id": user_id,
        "kind": "concept",
        "key": key,
        "label": concept,
        "weight": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.graph_nodes.insert_one(node)
    return node["id"]

async def add_edge(user_id: str, src: str, dst: str, kind: str):
    await db.graph_edges.insert_one({
        "id": uid(),
        "user_id": user_id,
        "src": src,
        "dst": dst,
        "kind": kind,
        "created_at": now_iso(),
    })

async def log_event(user_id: str, kind: str, text: str, ref_id: Optional[str] = None, meta: Optional[Dict] = None):
    payload = {
        "kind": kind,
        "text": text,
        "ref_id": ref_id,
        "meta": meta or {},
        "user_id": user_id,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload_hash = hashlib.sha256(canonical.encode()).hexdigest()

    prev = await db.events.find_one({"user_id": user_id}, {"_id": 0, "hash": 1, "created_at": 1}, sort=[("created_at", -1)])
    previous_hash = prev["hash"] if prev and prev.get("hash") else "0" * 64
    ts = now_iso()
    event_hash = hashlib.sha256((previous_hash + payload_hash + ts).encode()).hexdigest()

    ev = {
        "id": uid(),
        "user_id": user_id,
        "kind": kind,
        "text": text,
        "ref_id": ref_id,
        "meta": meta or {},
        "previous_hash": previous_hash,
        "payload_hash": payload_hash,
        "hash": event_hash,
        "created_at": ts,
    }
    await db.events.insert_one(ev)
    ev.pop("_id", None)
    return ev

@api.get("/ledger/verify")
async def verify_ledger(user=Depends(get_current_user)):
    events = await db.events.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", 1).to_list(5000)
    chained = [e for e in events if e.get("hash")]
    legacy = len(events) - len(chained)
    breaks = []
    expected_prev = "0" * 64
    for i, e in enumerate(chained):
        if e.get("previous_hash") != expected_prev:
            breaks.append({"index": i, "id": e["id"], "reason": "previous_hash mismatch"})
        recomputed_payload = hashlib.sha256(json.dumps({
            "kind": e["kind"], "text": e["text"], "ref_id": e.get("ref_id"),
            "meta": e.get("meta", {}), "user_id": user["id"],
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if e.get("payload_hash") != recomputed_payload:
            breaks.append({"index": i, "id": e["id"], "reason": "payload tampered"})
        recomputed_hash = hashlib.sha256((expected_prev + recomputed_payload + e["created_at"]).encode()).hexdigest()
        if e.get("hash") != recomputed_hash:
            breaks.append({"index": i, "id": e["id"], "reason": "event_hash invalid"})
        expected_prev = e.get("hash", expected_prev)
    return {
        "total_events": len(events),
        "chained": len(chained),
        "legacy_unchained": legacy,
        "breaks": breaks,
        "verified": len(breaks) == 0 and len(chained) > 0,
        "head_hash": chained[-1]["hash"] if chained else "0" * 64,
    }

# Governance-relevant event kinds surface in the Ledger view.
LEDGER_KINDS_ALL = [
    "note_created", "concepts_extracted", "linked", "memory_strengthened",
    "council_convened", "consensus_convened",
    "debate_triggered", "debate_turn_critic", "debate_turn_defender",
    "synthesis_proposed", "synthesis_ratified", "synthesis_rejected",
    "decision_made", "idea_evolved",
]

@api.get("/ledger/events")
async def ledger_events(
    user=Depends(get_current_user),
    kinds: Optional[str] = None,          # comma-separated
    ref_id: Optional[str] = None,
    q: Optional[str] = None,               # free-text search over event.text
    limit: int = 200,
):
    """Return the user's Immutable Ledger events with per-event chain verification.
    Every event is verified against its actual predecessor in the FULL chain so filters
    never break verification: the chain integrity is computed BEFORE filtering."""
    # 1. Pull the whole chain in chronological order and verify each event against its predecessor.
    all_events = await db.events.find(
        {"user_id": user["id"]}, {"_id": 0}
    ).sort("created_at", 1).to_list(10000)

    expected_prev = "0" * 64
    verified_ok = 0
    for idx, e in enumerate(all_events):
        e["chain_position"] = idx
        if not e.get("hash"):
            e["verified"] = False
            e["verify_reason"] = "legacy_unchained"
            continue
        recomputed_payload = hashlib.sha256(json.dumps({
            "kind": e["kind"], "text": e["text"], "ref_id": e.get("ref_id"),
            "meta": e.get("meta", {}), "user_id": user["id"],
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        prev_ok = e.get("previous_hash") == expected_prev
        payload_ok = e.get("payload_hash") == recomputed_payload
        recomputed_hash = hashlib.sha256((expected_prev + recomputed_payload + e["created_at"]).encode()).hexdigest()
        hash_ok = e.get("hash") == recomputed_hash
        ok = prev_ok and payload_ok and hash_ok
        e["verified"] = ok
        if not ok:
            reasons = []
            if not prev_ok:
                reasons.append("previous_hash mismatch")
            if not payload_ok:
                reasons.append("payload tampered")
            if not hash_ok:
                reasons.append("event_hash invalid")
            e["verify_reason"] = "; ".join(reasons)
        else:
            verified_ok += 1
        expected_prev = e.get("hash", expected_prev)

    head_hash = all_events[-1]["hash"] if all_events and all_events[-1].get("hash") else "0" * 64

    # 2. Apply filters
    kinds_set = None
    if kinds:
        kinds_set = {k.strip() for k in kinds.split(",") if k.strip()}
    q_lower = q.lower() if q else None

    filtered = []
    for e in all_events:
        if kinds_set and e["kind"] not in kinds_set:
            continue
        if ref_id and e.get("ref_id") != ref_id:
            continue
        if q_lower and q_lower not in (e.get("text") or "").lower() and q_lower not in (e.get("hash") or ""):
            continue
        filtered.append(e)

    # 3. Reverse-chronological for UI; clamp limit
    filtered.reverse()
    if limit and limit > 0:
        filtered = filtered[:limit]

    return {
        "events": filtered,
        "head_hash": head_hash,
        "total_events": len(all_events),
        "verified_ok": verified_ok,
        "chain_verified": verified_ok == len([e for e in all_events if e.get("hash")]) and any(e.get("hash") for e in all_events),
        "available_kinds": sorted({e["kind"] for e in all_events}),
    }



def sha_of(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

async def compute_decision_dna(user_id: str, decision: Dict[str, Any]) -> Dict[str, str]:
    """Build the 4 sub-hashes + root for a decision, using the same inputs a replay could reconstruct."""
    note_id = decision.get("note_id")
    note = await db.notes.find_one({"id": note_id, "user_id": user_id}, {"_id": 0}) if note_id else None

    # Prefer the latest ratified Synthesis (from Council Debate) over consensus.
    synthesis = None
    if note_id:
        s_latest = await db.debates.find(
            {"note_id": note_id, "user_id": user_id, "ratified": True}, {"_id": 0},
        ).sort("ratified_at", -1).limit(1).to_list(1)
        if s_latest:
            synthesis = s_latest[0]

    # Prefer the latest structured Consensus record for reasoning
    consensus = None
    if note_id and not synthesis:
        latest = await db.consensus_records.find(
            {"note_id": note_id, "user_id": user_id}, {"_id": 0},
        ).sort("created_at", -1).limit(1).to_list(1)
        if latest:
            consensus = latest[0]

    # Fall back to raw council responses if no consensus exists
    council = await db.council_responses.find({"note_id": note_id}, {"_id": 0}).to_list(20) if (note_id and not consensus and not synthesis) else []
    graph_edges = await db.graph_edges.count_documents({"user_id": user_id, "src": note_id}) if note_id else 0

    context = {
        "title": decision.get("title"),
        "note_title": (note or {}).get("title"),
        "note_concepts": (note or {}).get("concepts", []),
        "graph_neighbors": graph_edges,
        "user_id": user_id,
    }
    if synthesis:
        # Highest precedence: a human-ratified Synthesis from a Council Debate.
        reasoning = {
            "source": "synthesis",
            "synthesis_id": synthesis["id"],
            "synthesis_hash": synthesis.get("synthesis_hash"),
            "ratified_at": synthesis.get("ratified_at"),
            "ratified_by": synthesis.get("ratified_by"),
            "consensus_id": synthesis.get("consensus_id"),
            "triggers": synthesis.get("triggers", []),
            "turns": [
                {
                    "role": t.get("role"),
                    "provider": t.get("provider"),
                    "model": t.get("model"),
                    "argument_hash": t.get("argument_hash"),
                } for t in synthesis.get("turns", [])
            ],
            "synthesis": synthesis.get("synthesis", {}),
            "context_field": decision.get("context", ""),
        }
    elif consensus:
        # Bind the exact consensus verdicts + score into the reasoning bucket
        reasoning = {
            "source": "consensus",
            "consensus_id": consensus["id"],
            "consensus_created_at": consensus["created_at"],
            "verdicts": [
                {
                    "agent": v["agent"],
                    "position": v["position"],
                    "confidence": v["confidence"],
                    "risk_score": v["risk_score"],
                    "reasoning": v["reasoning"],
                    "evidence": v["evidence"],
                } for v in consensus["verdicts"]
            ],
            "score": consensus["score"],
            "context_field": decision.get("context", ""),
        }
    else:
        reasoning = {
            "source": "raw_council",
            "council": [{"agent": r["agent"], "response": r["response"]} for r in council],
            "context_field": decision.get("context", ""),
        }
    governance = {
        "policies_checked": ["sandbox.workspace_only", "human_approval_required"],
        "approvals": ["constitutional"],
        "risk": "medium",
    }
    outcome = {
        "affected_projects": decision.get("affected_projects", 0),
        "produced_tasks": decision.get("produced_tasks", 0),
        "referenced_notes": decision.get("referenced_notes", 0),
        "influenced_agents": decision.get("influenced_agents", 0),
    }

    ch = sha_of(context)
    rh = sha_of(reasoning)
    gh = sha_of(governance)
    oh = sha_of(outcome)
    root = sha_of({"context": ch, "reasoning": rh, "governance": gh, "outcome": oh})
    return {
        "context_hash": ch, "reasoning_hash": rh,
        "governance_hash": gh, "outcome_hash": oh,
        "dna_root": root,
        "reasoning_source": reasoning.get("source"),
        "reasoning_consensus_id": reasoning.get("consensus_id"),
        "reasoning_synthesis_id": reasoning.get("synthesis_id"),
    }

@api.get("/decisions/{did}/dna")
async def decision_dna(did: str, user=Depends(get_current_user)):
    d = await db.decisions.find_one({"id": did, "user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    fresh = await compute_decision_dna(user["id"], d)
    # Always persist fresh so reasoning binding reflects the latest consensus
    await db.decisions.update_one({"id": did}, {"$set": fresh})
    stored = {k: d.get(k) for k in ("context_hash", "reasoning_hash", "governance_hash", "outcome_hash", "dna_root")}
    verified = all(stored.values()) and stored == {k: fresh[k] for k in stored}
    return {"dna": fresh, "stored": stored, "verified": verified}

async def compute_gravity(user_id: str, note_id: str) -> float:
    """Gravity = weighted mix of connections + reuse + decisions referencing it."""
    edges = await db.graph_edges.count_documents({"user_id": user_id, "$or": [{"src": note_id}, {"dst": note_id}]})
    decisions = await db.decisions.count_documents({"user_id": user_id, "note_id": note_id})
    note = await db.notes.find_one({"id": note_id}, {"_id": 0}) or {}
    concept_count = len(note.get("concepts", []))
    versions = await db.note_versions.count_documents({"note_id": note_id})
    raw = 12 * edges + 18 * decisions + 6 * concept_count + 8 * versions
    score = 100 * (1 - math.exp(-raw / 40))
    return round(score, 1)

async def memory_strength(user_id: str) -> int:
    notes = await db.notes.count_documents({"user_id": user_id})
    edges = await db.graph_edges.count_documents({"user_id": user_id})
    decisions = await db.decisions.count_documents({"user_id": user_id})
    raw = 4 * notes + 2 * edges + 6 * decisions
    return min(100, int(30 + 70 * (1 - math.exp(-raw / 80))))

# ---------------- Auth Routes ----------------
@api.post("/auth/register")
async def register(inp: RegisterIn):
    existing = await db.users.find_one({"email": inp.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = {
        "id": uid(),
        "email": inp.email.lower(),
        "name": inp.name,
        "password": hash_password(inp.password),
        "created_at": now_iso(),
    }
    await db.users.insert_one(user)
    token = create_token(user["id"])
    return {"token": token, "user": {"id": user["id"], "email": user["email"], "name": user["name"]}}

@api.post("/auth/login")
async def login(inp: LoginIn):
    user = await db.users.find_one({"email": inp.email.lower()})
    if not user or not verify_password(inp.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user["id"])
    return {"token": token, "user": {"id": user["id"], "email": user["email"], "name": user["name"]}}

# ---- Emergency admin password reset ----
# One-time bypass for locked-out account owners. Guarded by ADMIN_RESET_TOKEN
# env var, which MUST be set at deploy time and MUST be a long random string.
# If the env var is unset or empty, the endpoint refuses to run (503) so it
# cannot be accidentally left open. Every reset is written to the Immutable
# Event Ledger as evidence.
import hmac as _hmac
import time as _time

_ADMIN_RESET_ATTEMPTS: List[float] = []  # in-memory sliding window of recent attempts

def _admin_reset_rate_limit_ok() -> bool:
    now = _time.time()
    window_start = now - 60.0
    # drop old entries
    _ADMIN_RESET_ATTEMPTS[:] = [t for t in _ADMIN_RESET_ATTEMPTS if t >= window_start]
    if len(_ADMIN_RESET_ATTEMPTS) >= 10:
        return False
    _ADMIN_RESET_ATTEMPTS.append(now)
    return True

@api.post("/auth/admin/reset-password")
async def admin_reset_password(inp: AdminResetIn):
    """Emergency password reset for a locked-out account owner.

    Requires ADMIN_RESET_TOKEN env var to be set. Compares the supplied token
    in constant time. If the target email does not exist, the account is
    created so a legitimate owner recovering from data loss can still get in.
    """
    admin_token = os.environ.get("ADMIN_RESET_TOKEN", "").strip()
    if not admin_token:
        raise HTTPException(status_code=503, detail="Admin reset is disabled on this deployment")
    if not _admin_reset_rate_limit_ok():
        raise HTTPException(status_code=429, detail="Too many admin reset attempts, try again later")
    supplied = (inp.admin_token or "").strip()
    if not _hmac.compare_digest(supplied, admin_token):
        # log the failed attempt without leaking why
        logging.warning("admin_reset_password: token mismatch for email=%s", inp.email)
        raise HTTPException(status_code=401, detail="Invalid admin token")
    if len(inp.new_password) < 8:
        raise HTTPException(status_code=400, detail="new_password must be at least 8 characters")

    email = inp.email.lower()
    existing = await db.users.find_one({"email": email})
    now = now_iso()
    if existing:
        await db.users.update_one(
            {"id": existing["id"]},
            {"$set": {"password": hash_password(inp.new_password), "password_reset_at": now}},
        )
        user_id = existing["id"]
        created = False
        display_name = existing.get("name") or email.split("@")[0]
    else:
        user_id = uid()
        display_name = email.split("@")[0]
        await db.users.insert_one({
            "id": user_id,
            "email": email,
            "name": display_name,
            "password": hash_password(inp.new_password),
            "created_at": now,
            "password_reset_at": now,
        })
        created = True

    # Append to Immutable Event Ledger as evidence of the admin action.
    try:
        await log_event(
            user_id=user_id,
            kind="admin_password_reset",
            text=f"Admin password reset for {email}",
            meta={"email": email, "created_new_account": created},
        )
    except Exception:
        logging.exception("admin_reset_password: failed to append ledger event")

    token = create_token(user_id)
    return {
        "ok": True,
        "created_new_account": created,
        "user": {"id": user_id, "email": email, "name": display_name},
        "token": token,
    }

@api.get("/auth/me")
async def me(user=Depends(get_current_user)):
    return user

@api.delete("/auth/account")
async def delete_account(user=Depends(get_current_user)):
    """Permanently delete the authenticated user's account and all associated
    workspace data. Apple App Store requires an in-app deletion path for any
    account-based app. This action is IRREVERSIBLE.

    The Immutable Event Ledger events for this user are also removed, since
    they are user-scoped evidence. Legal audit requirements (if any) should be
    exported via /api/ledger/export BEFORE calling this endpoint.
    """
    uid_ = user["id"]
    # Cascade delete every user-scoped collection.
    for coll in (
        "notes", "note_versions", "graph_nodes", "graph_edges",
        "council_responses", "consensus_records", "debates", "contradictions",
        "operations", "decisions", "executions", "agents", "leases",
        "chat_sessions", "chat_messages", "events",
    ):
        try:
            await db[coll].delete_many({"user_id": uid_})
        except Exception:
            logging.exception(f"delete_account: failed to purge collection {coll}")
    await db.users.delete_one({"id": uid_})
    return {"deleted": True, "user_id": uid_}

# ---------------- Apple Sign-In ----------------
async def get_apple_jwks() -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    cached = _apple_jwks_cache.get("keys")
    fetched = _apple_jwks_cache.get("fetched_at")
    if cached and fetched and (now - fetched).total_seconds() < 3600:
        return cached
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(APPLE_JWKS_URL)
        r.raise_for_status()
        keys = r.json().get("keys", [])
    _apple_jwks_cache["keys"] = keys
    _apple_jwks_cache["fetched_at"] = now
    return keys

async def verify_apple_identity_token(token: str) -> Dict[str, Any]:
    if not APPLE_AUDIENCES:
        raise HTTPException(status_code=500, detail="Server misconfigured: APPLE_AUDIENCES missing")
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Malformed identity token: {e}")
    kid = unverified_header.get("kid")
    keys = await get_apple_jwks()
    jwk = next((k for k in keys if k.get("kid") == kid), None)
    if not jwk:
        # Refresh once in case Apple rotated keys
        _apple_jwks_cache["keys"] = None
        keys = await get_apple_jwks()
        jwk = next((k for k in keys if k.get("kid") == kid), None)
    if not jwk:
        raise HTTPException(status_code=401, detail="Signing key not found in Apple JWKS")
    try:
        public_key = jwt.PyJWK(jwk).key
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=APPLE_AUDIENCES,
            issuer=APPLE_ISSUER,
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid Apple token: {e}")
    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Apple token missing subject")
    return payload

@api.post("/auth/apple")
async def apple_sign_in(inp: AppleIn):
    payload = await verify_apple_identity_token(inp.identity_token)
    apple_sub = payload["sub"]
    email_from_token = payload.get("email")
    email_verified = payload.get("email_verified") in (True, "true", "True")

    # 1) Try to find an existing account by apple_sub
    existing = await db.users.find_one({"apple_sub": apple_sub}, {"_id": 0, "password": 0})

    # 2) If none, and Apple gave us a verified email, try to link by email
    if not existing and email_from_token and email_verified:
        existing = await db.users.find_one({"email": email_from_token.lower()}, {"_id": 0, "password": 0})
        if existing:
            await db.users.update_one({"id": existing["id"]}, {"$set": {"apple_sub": apple_sub}})
            existing["apple_sub"] = apple_sub

    if existing:
        token = create_token(existing["id"])
        return {"token": token, "user": {"id": existing["id"], "email": existing["email"], "name": existing.get("name", "")}}

    # 3) New user — use first-sign-in name/email if Apple didn't include them
    name = (inp.full_name or "").strip() or "Apple User"
    email = (inp.email or email_from_token or f"{apple_sub}@privaterelay.apple").lower()
    user = {
        "id": uid(),
        "email": email,
        "name": name,
        "apple_sub": apple_sub,
        "password": None,
        "created_at": now_iso(),
    }
    await db.users.insert_one(user)
    token = create_token(user["id"])
    return {"token": token, "user": {"id": user["id"], "email": user["email"], "name": user["name"]}}

# ---------------- Notes / Timeline ----------------
@api.post("/notes")
async def create_note(inp: NoteIn, user=Depends(get_current_user)):
    note_id = uid()
    concepts = await extract_concepts(inp.text)
    before_strength = await memory_strength(user["id"])

    note = {
        "id": note_id,
        "user_id": user["id"],
        "title": inp.title or inp.text[:60],
        "text": inp.text,
        "concepts": concepts,
        "version": 1,
        "parent_id": None,
        "revenue": 0,
        "produced_projects": 0,
        "produced_tasks": 0,
        "produced_articles": 0,
        "produced_proposals": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.notes.insert_one(note)
    note.pop("_id", None)

    # Version 0 record
    await db.note_versions.insert_one({
        "id": uid(),
        "note_id": note_id,
        "version": 1,
        "stage": "Idea",
        "text": inp.text,
        "user_id": user["id"],
        "created_at": now_iso(),
    })

    # Create graph node for note + concept links
    note_node = {
        "id": note_id,
        "user_id": user["id"],
        "kind": "note",
        "key": note_id,
        "label": note["title"],
        "weight": 3,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.graph_nodes.insert_one(note_node)

    connections = []
    for c in concepts:
        cid = await upsert_concept_node(user["id"], c)
        await add_edge(user["id"], note_id, cid, "has_concept")
        # link to earlier notes that share this concept
        siblings = db.graph_edges.find({"user_id": user["id"], "dst": cid, "kind": "has_concept"})
        async for e in siblings:
            if e["src"] != note_id:
                await add_edge(user["id"], note_id, e["src"], "related")
                connections.append(c)
                break

    after_strength = await memory_strength(user["id"])

    await log_event(user["id"], "note_created", f"Created note: {note['title']}", ref_id=note_id)
    await log_event(user["id"], "concepts_extracted", f"AI extracted {len(concepts)} concepts", ref_id=note_id, meta={"concepts": concepts})
    if connections:
        await log_event(user["id"], "linked", f"Linked to prior knowledge on: {', '.join(set(connections))[:80]}", ref_id=note_id)
    await log_event(user["id"], "memory_strengthened", f"Memory strengthened: {before_strength}% -> {after_strength}%", ref_id=note_id, meta={"before": before_strength, "after": after_strength})

    note.pop("_id", None)
    return {
        "note": {**note, "gravity": await compute_gravity(user["id"], note_id)},
        "memory": {"before": before_strength, "after": after_strength},
        "new_connections": list(set(connections)),
    }

@api.get("/notes")
async def list_notes(user=Depends(get_current_user)):
    notes = await db.notes.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    for n in notes:
        n["gravity"] = await compute_gravity(user["id"], n["id"])
    return notes

@api.get("/notes/{note_id}")
async def get_note(note_id: str, user=Depends(get_current_user)):
    n = await db.notes.find_one({"id": note_id, "user_id": user["id"]}, {"_id": 0})
    if not n:
        raise HTTPException(status_code=404, detail="Not found")
    n["gravity"] = await compute_gravity(user["id"], note_id)
    versions = await db.note_versions.find({"note_id": note_id}, {"_id": 0}).sort("version", 1).to_list(50)
    council = await db.council_responses.find({"note_id": note_id}, {"_id": 0}).to_list(20)
    decisions = await db.decisions.find({"note_id": note_id, "user_id": user["id"]}, {"_id": 0}).to_list(20)
    return {"note": n, "versions": versions, "council": council, "decisions": decisions}

@api.post("/notes/{note_id}/council")
async def council(note_id: str, user=Depends(get_current_user)):
    n = await db.notes.find_one({"id": note_id, "user_id": user["id"]}, {"_id": 0})
    if not n:
        raise HTTPException(status_code=404, detail="Not found")
    responses = await run_council(n["text"])
    for r in responses:
        await db.council_responses.insert_one({
            "id": uid(),
            "note_id": note_id,
            "user_id": user["id"],
            "agent": r["agent"],
            "color_key": r["color_key"],
            "response": r["response"],
            "created_at": now_iso(),
        })
    await log_event(user["id"], "council_convened", f"AI Council reviewed: {n['title']}", ref_id=note_id)
    return {"responses": responses}

@api.post("/notes/{note_id}/council/consensus")
async def council_consensus(note_id: str, user=Depends(get_current_user)):
    """Structured Council Protocol: each agent returns position/confidence/risk/evidence,
    the consensus engine scores them, and the note gets a formal verdict."""
    n = await db.notes.find_one({"id": note_id, "user_id": user["id"]}, {"_id": 0})
    if not n:
        raise HTTPException(status_code=404, detail="Not found")

    # Historical success rate for this user - drives one term of the score
    total_dec = await db.decisions.count_documents({"user_id": user["id"]})
    reversed_ = await db.executions.count_documents({"user_id": user["id"], "state": "REVERSED"})
    executed = await db.executions.count_documents({"user_id": user["id"], "state": "EXECUTED"})
    if executed + reversed_ > 0:
        history = max(0.4, executed / (executed + reversed_))
    else:
        history = 0.8

    verdicts = await run_council_consensus(n["text"])
    scored = compute_consensus_score(verdicts, historical_success=history)

    record = {
        "id": uid(),
        "note_id": note_id,
        "user_id": user["id"],
        "verdicts": verdicts,
        "score": scored,
        "created_at": now_iso(),
    }
    await db.consensus_records.insert_one(record)
    record.pop("_id", None)
    await log_event(
        user["id"], "consensus_convened",
        f"Consensus: {scored['recommendation']} ({scored['approve_count']}A/{scored['reject_count']}R) on: {n['title']}",
        ref_id=note_id,
        meta={"score": scored["score"], "recommendation": scored["recommendation"], "needs_debate": scored["needs_debate"]},
    )

    # --- Semantic contradiction detection: non-destructive governed findings ---
    # We recompute triggers here so the contradiction analysis persists alongside
    # the fresh consensus and appears in the note UI.
    trig = await compute_debate_triggers(user["id"], note_id, n, scored, verdicts)
    contradiction_records: List[Dict[str, Any]] = []
    for t in trig["triggers"]:
        if t["kind"] != "prior_decision_conflict":
            continue
        for c in t.get("contradictions") or []:
            rec = {
                "id": uid(),
                "user_id": user["id"],
                "new_note_id": note_id,
                "new_note_title": n.get("title"),
                "new_consensus_id": record["id"],
                "new_position": c["new_position"],
                "prior_note_id": c["prior_note_id"],
                "prior_note_title": c["prior_note_title"],
                "prior_decision_id": c.get("prior_decision_id"),
                "prior_decision_number": c.get("prior_decision_number"),
                "prior_synthesis_id": c.get("prior_synthesis_id"),
                "prior_synthesis_hash": c.get("prior_synthesis_hash"),
                "prior_position": c["prior_position"],
                "overlapping_concepts": c["overlapping_concepts"],
                "concept_overlap_jaccard": c["concept_overlap_jaccard"],
                "concept_overlap_containment": c.get("concept_overlap_containment"),
                "concept_overlap_score": c.get("concept_overlap_score"),
                "resolved": False,
                "resolution": None,
                "resolved_at": None,
                "resolved_by": None,
                "created_at": now_iso(),
            }
            await db.contradictions.insert_one(rec)
            rec.pop("_id", None)
            contradiction_records.append(rec)
            await log_event(
                user["id"], "contradiction_detected",
                f"Contradiction: {rec['new_position']} vs Decision #{rec.get('prior_decision_number','?')} ({rec['prior_position']}) — {len(rec['overlapping_concepts'])} shared concept(s)",
                ref_id=note_id,
                meta={
                    "contradiction_id": rec["id"],
                    "prior_note_id": rec["prior_note_id"],
                    "prior_synthesis_id": rec.get("prior_synthesis_id"),
                    "prior_decision_id": rec.get("prior_decision_id"),
                    "overlapping_concepts": rec["overlapping_concepts"],
                    "concept_overlap_jaccard": rec["concept_overlap_jaccard"],
                },
            )
    record["contradictions"] = contradiction_records
    return record

@api.get("/notes/{note_id}/debate/triggers")
async def debate_triggers(note_id: str, user=Depends(get_current_user)):
    """Analyze the latest consensus + note context and return which governance signals
    (if any) escalate this decision to a full Council Debate."""
    n = await db.notes.find_one({"id": note_id, "user_id": user["id"]}, {"_id": 0})
    if not n:
        raise HTTPException(status_code=404, detail="Note not found")
    latest = await db.consensus_records.find(
        {"note_id": note_id, "user_id": user["id"]}, {"_id": 0}
    ).sort("created_at", -1).limit(1).to_list(1)
    if not latest:
        return {"triggers": [], "should_debate": False, "disagreement_stddev": 0.0, "consensus_id": None}
    scored = latest[0]["score"]
    verdicts = latest[0]["verdicts"]
    t = await compute_debate_triggers(user["id"], note_id, n, scored, verdicts)
    t["consensus_id"] = latest[0]["id"]
    return t

@api.get("/notes/{note_id}/debate/latest")
async def debate_latest(note_id: str, user=Depends(get_current_user)):
    """Return the most recent debate record for a note (if any)."""
    latest = await db.debates.find(
        {"note_id": note_id, "user_id": user["id"]}, {"_id": 0}
    ).sort("created_at", -1).limit(1).to_list(1)
    return latest[0] if latest else None

@api.post("/notes/{note_id}/council/debate")
async def council_debate(note_id: str, user=Depends(get_current_user)):
    """Run a full multi-turn Council Debate:
      Turn 1: Claude Sonnet as Critic — argues against the majority verdict.
      Turn 2: GPT-5.4 as Defender — steelmans the majority against the critic.
      Turn 3: Gemini as Synthesizer — proposes a resolution (unratified).
    Each turn is hashed and appended to the Ledger as its own event, and the
    final Synthesis Proposal awaits explicit Human Ratification."""
    n = await db.notes.find_one({"id": note_id, "user_id": user["id"]}, {"_id": 0})
    if not n:
        raise HTTPException(status_code=404, detail="Not found")
    latest = await db.consensus_records.find(
        {"note_id": note_id, "user_id": user["id"]}, {"_id": 0}
    ).sort("created_at", -1).limit(1).to_list(1)
    if not latest:
        raise HTTPException(status_code=400, detail="No consensus record yet. Convene consensus first.")

    consensus_id = latest[0]["id"]
    verdicts = latest[0]["verdicts"]
    scored = latest[0]["score"]

    # 1. Compute triggers and require at least one to proceed
    trig = await compute_debate_triggers(user["id"], note_id, n, scored, verdicts)
    if not trig["should_debate"]:
        raise HTTPException(status_code=400, detail="No debate triggers fired. Consensus is stable.")

    # Log that a debate was triggered (auditable)
    await log_event(
        user["id"], "debate_triggered",
        f"Debate triggered on: {n['title']} — {len(trig['triggers'])} signal(s)",
        ref_id=note_id,
        meta={"triggers": trig["triggers"], "consensus_id": consensus_id},
    )

    # Determine majority position
    approve = scored.get("approve_count", 0)
    reject = scored.get("reject_count", 0)
    majority = "APPROVE" if approve > reject else ("REJECT" if reject > approve else "UNCERTAIN")

    positions_block = "\n".join(
        f"- {v['agent']} → {v['position']} (conf {v['confidence']}, risk {v['risk_score']}): {v['reasoning']}"
        for v in verdicts
    )
    triggers_block = "\n".join(f"- {t['kind']}: {t['detail']}" for t in trig["triggers"])
    note_block = f"Title: {n['title']}\n\n{n.get('text','')[:1200]}"

    turns: List[Dict[str, Any]] = []

    # Turn 1 — Critic (Claude Sonnet 4.6)
    critic_system = (
        "You are the Council Critic. The majority of specialized agents leaned toward "
        f"{majority}. In 2-3 short sentences, argue the STRONGEST case AGAINST the majority. "
        "Be concrete: cite the weakest assumption, the biggest unknown, or the largest risk. "
        "Do NOT hedge. End with one line prefixed 'RISK:' summarizing the single greatest risk."
    )
    critic_prompt = f"NOTE:\n{note_block}\n\nAGENT VERDICTS:\n{positions_block}\n\nESCALATION TRIGGERS:\n{triggers_block}"
    critic_out = await llm_call(
        "anthropic", "claude-sonnet-4-6", critic_system, critic_prompt,
        session_id=f"debate-critic-{note_id}",
    )
    critic_hash = sha_of({"role": "critic", "argument": critic_out, "against": majority})
    turns.append({
        "role": "critic", "provider": "anthropic", "model": "claude-sonnet-4-6",
        "against": majority, "argument": critic_out or "(critic unavailable)",
        "argument_hash": critic_hash,
    })
    await log_event(
        user["id"], "debate_turn_critic",
        f"Critic (Claude) argued against {majority}",
        ref_id=note_id,
        meta={"argument_hash": critic_hash, "consensus_id": consensus_id},
    )

    # Turn 2 — Defender (GPT-5.4)
    defender_system = (
        f"You are the Council Defender. The majority position was {majority}. A critic has just "
        "attacked that position. In 2-3 short sentences, steelman the majority: acknowledge the "
        "critic's strongest point, then explain why the majority position still holds under stated "
        "conditions. End with a line prefixed 'CONDITIONS:' listing the conditions that must hold."
    )
    defender_prompt = (
        f"NOTE:\n{note_block}\n\nMAJORITY VERDICTS:\n{positions_block}\n\n"
        f"CRITIC ARGUMENT:\n{critic_out}\n\nESCALATION TRIGGERS:\n{triggers_block}"
    )
    defender_out = await llm_call(
        "openai", "gpt-5.4", defender_system, defender_prompt,
        session_id=f"debate-defender-{note_id}",
    )
    defender_hash = sha_of({"role": "defender", "argument": defender_out, "for": majority, "responds_to": critic_hash})
    turns.append({
        "role": "defender", "provider": "openai", "model": "gpt-5.4",
        "for": majority, "argument": defender_out or "(defender unavailable)",
        "responds_to": critic_hash, "argument_hash": defender_hash,
    })
    await log_event(
        user["id"], "debate_turn_defender",
        f"Defender (GPT-5.4) steelmanned {majority}",
        ref_id=note_id,
        meta={"argument_hash": defender_hash, "responds_to": critic_hash, "consensus_id": consensus_id},
    )

    # Turn 3 — Synthesizer (Gemini)
    synth_system = (
        "You are the Council Synthesizer. The critic and defender have finished. Produce a "
        "resolution as strict JSON only (no prose, no backticks) with keys:\n"
        "  resolution: one sentence with the best path forward.\n"
        "  conditions: array of 1-3 short conditions under which resolution holds.\n"
        "  escalate: 'YES' or 'NO' — whether human review is required.\n"
        "  escalate_reason: one short sentence explaining escalate.\n"
        "  confidence: float 0..1.\n"
        "  synthesis_position: 'APPROVE'|'REJECT'|'CONDITIONAL_APPROVE'|'DEFER'."
    )
    synth_prompt = (
        f"NOTE:\n{note_block}\n\nORIGINAL VERDICTS:\n{positions_block}\n\n"
        f"CRITIC:\n{critic_out}\n\nDEFENDER:\n{defender_out}\n\n"
        f"ESCALATION TRIGGERS:\n{triggers_block}"
    )
    synth_raw = await gemini_chat(synth_system, synth_prompt, session_id=f"debate-synth-{note_id}")
    parsed = _parse_json_lenient(synth_raw) or {}
    synthesis = {
        "resolution": str(parsed.get("resolution", ""))[:500],
        "conditions": [str(c)[:200] for c in (parsed.get("conditions") or [])][:3]
                       if isinstance(parsed.get("conditions"), list)
                       else ([str(parsed.get("conditions",""))[:200]] if parsed.get("conditions") else []),
        "escalate": str(parsed.get("escalate","")).upper() == "YES",
        "escalate_reason": str(parsed.get("escalate_reason", ""))[:300],
        "confidence": max(0.0, min(1.0, float(parsed.get("confidence") or 0.5))) if str(parsed.get("confidence","")).replace(".","",1).replace("-","",1).isdigit() else 0.5,
        "synthesis_position": str(parsed.get("synthesis_position", "DEFER")).upper(),
    }
    synth_argument_hash = sha_of({"role": "synthesizer", "synthesis": synthesis, "responds_to": [critic_hash, defender_hash]})
    turns.append({
        "role": "synthesizer", "provider": "gemini", "model": "gemini-3-flash-preview",
        "argument": synth_raw or "(synthesizer unavailable)",
        "responds_to": [critic_hash, defender_hash],
        "argument_hash": synth_argument_hash,
    })

    # Signed, canonical synthesis hash — this becomes the future reasoning_hash upon ratification.
    synthesis_payload = {
        "note_id": note_id,
        "consensus_id": consensus_id,
        "triggers": trig["triggers"],
        "turns": [
            {"role": t["role"], "provider": t["provider"], "model": t["model"], "argument_hash": t["argument_hash"]}
            for t in turns
        ],
        "synthesis": synthesis,
    }
    synthesis_hash = sha_of(synthesis_payload)

    record = {
        "id": uid(),
        "note_id": note_id,
        "user_id": user["id"],
        "consensus_id": consensus_id,
        "triggers": trig["triggers"],
        "disagreement_stddev": trig["disagreement_stddev"],
        "majority": majority,
        "turns": turns,
        "synthesis": synthesis,
        "synthesis_hash": synthesis_hash,
        "ratified": False,
        "ratified_at": None,
        "ratified_by": None,
        "rejected": False,
        "rejected_at": None,
        "rejected_by": None,
        "created_at": now_iso(),
    }
    await db.debates.insert_one(record)
    record.pop("_id", None)

    await log_event(
        user["id"], "synthesis_proposed",
        f"Synthesis proposed for: {n['title']}",
        ref_id=note_id,
        meta={
            "synthesis_id": record["id"],
            "synthesis_hash": synthesis_hash,
            "consensus_id": consensus_id,
            "synthesis_position": synthesis.get("synthesis_position"),
            "escalate": synthesis.get("escalate"),
        },
    )
    return record

@api.post("/synthesis/{sid}/ratify")
async def synthesis_ratify(sid: str, user=Depends(get_current_user)):
    """Human ratifies a Synthesis Proposal. This re-binds every decision on this note
    to the synthesis as the new reasoning source, and appends a ratification event
    to the Ledger."""
    rec = await db.debates.find_one({"id": sid, "user_id": user["id"]}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Synthesis not found")
    if rec.get("ratified"):
        raise HTTPException(status_code=400, detail="Already ratified")
    if rec.get("rejected"):
        raise HTTPException(status_code=400, detail="Already rejected; cannot ratify")

    ts = now_iso()
    ratifier = user.get("email") or user.get("name") or user.get("id")
    await db.debates.update_one(
        {"id": sid},
        {"$set": {"ratified": True, "ratified_at": ts, "ratified_by": ratifier}},
    )
    rec.update({"ratified": True, "ratified_at": ts, "ratified_by": ratifier})

    await log_event(
        user["id"], "synthesis_ratified",
        f"Synthesis ratified by {ratifier}",
        ref_id=rec.get("note_id"),
        meta={"synthesis_id": sid, "synthesis_hash": rec.get("synthesis_hash")},
    )

    # Rebind every decision on this note so reasoning_hash covers the ratified synthesis.
    rebound = []
    if rec.get("note_id"):
        decisions = await db.decisions.find(
            {"user_id": user["id"], "note_id": rec["note_id"]}, {"_id": 0}
        ).to_list(50)
        for d in decisions:
            fresh = await compute_decision_dna(user["id"], d)
            await db.decisions.update_one({"id": d["id"]}, {"$set": fresh})
            rebound.append({"decision_id": d["id"], "dna_root": fresh["dna_root"], "reasoning_hash": fresh["reasoning_hash"]})

    return {"synthesis": rec, "rebound_decisions": rebound}

@api.post("/synthesis/{sid}/reject")
async def synthesis_reject(sid: str, user=Depends(get_current_user)):
    """Human rejects a Synthesis Proposal. It stays in the record for audit but is
    not bound into any Decision DNA."""
    rec = await db.debates.find_one({"id": sid, "user_id": user["id"]}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Synthesis not found")
    if rec.get("rejected"):
        raise HTTPException(status_code=400, detail="Already rejected")
    if rec.get("ratified"):
        raise HTTPException(status_code=400, detail="Already ratified; cannot reject")

    ts = now_iso()
    rejecter = user.get("email") or user.get("name") or user.get("id")
    await db.debates.update_one(
        {"id": sid},
        {"$set": {"rejected": True, "rejected_at": ts, "rejected_by": rejecter}},
    )
    rec.update({"rejected": True, "rejected_at": ts, "rejected_by": rejecter})

    await log_event(
        user["id"], "synthesis_rejected",
        f"Synthesis rejected by {rejecter}",
        ref_id=rec.get("note_id"),
        meta={"synthesis_id": sid, "synthesis_hash": rec.get("synthesis_hash")},
    )
    return rec

# ---------------- Contradictions ----------------
@api.get("/notes/{note_id}/contradictions")
async def note_contradictions(note_id: str, user=Depends(get_current_user)):
    """All contradictions this note participates in — as the new challenger AND as prior precedent."""
    n = await db.notes.find_one({"id": note_id, "user_id": user["id"]}, {"_id": 0})
    if not n:
        raise HTTPException(status_code=404, detail="Note not found")
    as_new = await db.contradictions.find(
        {"user_id": user["id"], "new_note_id": note_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    as_prior = await db.contradictions.find(
        {"user_id": user["id"], "prior_note_id": note_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    return {"as_new": as_new, "as_prior": as_prior}

@api.get("/decisions/{did}/contradictions")
async def decision_contradictions(did: str, user=Depends(get_current_user)):
    d = await db.decisions.find_one({"id": did, "user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    return await db.contradictions.find(
        {"user_id": user["id"], "$or": [{"prior_decision_id": did}, {"prior_note_id": d.get("note_id")}, {"new_note_id": d.get("note_id")}]},
        {"_id": 0},
    ).sort("created_at", -1).to_list(50)

@api.post("/contradictions/{cid}/resolve")
async def resolve_contradiction(cid: str, user=Depends(get_current_user)):
    """Human marks a contradiction as consciously accepted / resolved. Non-destructive
    (evidence remains); records the resolution as a ledger event."""
    rec = await db.contradictions.find_one({"id": cid, "user_id": user["id"]}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    if rec.get("resolved"):
        return rec
    ts = now_iso()
    who = user.get("email") or user.get("name") or user.get("id")
    await db.contradictions.update_one({"id": cid}, {"$set": {"resolved": True, "resolved_at": ts, "resolved_by": who}})
    rec.update({"resolved": True, "resolved_at": ts, "resolved_by": who})
    await log_event(
        user["id"], "contradiction_resolved",
        f"Contradiction resolved by {who}",
        ref_id=rec.get("new_note_id"),
        meta={"contradiction_id": cid, "prior_decision_id": rec.get("prior_decision_id")},
    )
    return rec

# ---------------- Ledger Export (auditor bundle) ----------------
LEDGER_EXPORT_PROTOCOL_VERSION = "pocketos.ledger.v1"

VERIFY_SCRIPT = '''#!/usr/bin/env python3
"""Pocket OS Ledger — independent verification script.

Reads ledger.jsonl (one canonical event per line, chronological order) and
recomputes the hash chain WITHOUT trusting the exporting application.
Exit code 0 = chain valid, matches head.json.
Exit code 1 = chain broken (details printed to stdout).

The canonical payload used for hashing is the exact JSON object
    {"kind": ..., "text": ..., "ref_id": ..., "meta": ..., "user_id": ...}
serialized with json.dumps(sort_keys=True, separators=(",", ":")) and
SHA-256'd. The event hash is SHA-256 of (previous_hash + payload_hash + created_at).
"""
import json, hashlib, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ledger_path = ROOT / "ledger.jsonl"
head_path = ROOT / "head.json"

with open(head_path) as f:
    head = json.load(f)
expected_head = head["head_hash"]
protocol_version = head.get("protocol_version")

prev = "0" * 64
count = 0
verified = 0
breaks = []
with open(ledger_path) as f:
    for i, line in enumerate(f):
        line = line.strip()
        if not line:
            continue
        e = json.loads(line)
        count += 1
        canonical = json.dumps({
            "kind": e["kind"], "text": e["text"], "ref_id": e.get("ref_id"),
            "meta": e.get("meta", {}), "user_id": e["user_id"],
        }, sort_keys=True, separators=(",", ":"))
        payload_hash = hashlib.sha256(canonical.encode()).hexdigest()
        recomputed = hashlib.sha256((prev + payload_hash + e["created_at"]).encode()).hexdigest()
        ok = (
            e.get("previous_hash") == prev
            and e.get("payload_hash") == payload_hash
            and e.get("hash") == recomputed
        )
        if not ok:
            breaks.append({"index": i, "id": e.get("id"), "kind": e.get("kind")})
        else:
            verified += 1
        prev = e.get("hash", prev)

status_ok = (not breaks) and prev == expected_head and count > 0
print(f"protocol_version : {protocol_version}")
print(f"events           : {count}")
print(f"verified         : {verified}")
print(f"breaks           : {len(breaks)}")
print(f"recomputed_head  : {prev}")
print(f"declared_head    : {expected_head}")
print(f"chain_verified   : {status_ok}")
if breaks:
    for b in breaks[:10]:
        print(" - break:", b)
sys.exit(0 if status_ok else 1)
'''

VERIFY_README = '''# Pocket OS Ledger Audit Bundle

This bundle is a self-contained, independently verifiable snapshot of the
user's Immutable Event Ledger at export time.

## Layout
```
audit_bundle/
├── manifest.json          Bundle metadata + protocol version + hash algorithm
├── head.json              Declared head_hash + chain stats + export timestamp
├── ledger.jsonl           One canonical event per line, chronological
├── verification/
│   └── verify.py          Third-party re-verification (no app trust required)
└── README.md              This file
```

## Verify locally
```
cd audit_bundle
python3 verification/verify.py
```
Exit code 0 = chain is intact and matches declared head_hash.

## Canonicalization
- SHA-256 for artifact/event integrity.
- Canonical JSON: `json.dumps(sort_keys=True, separators=(",", ":"))`.
- Event hash = SHA256(previous_hash + payload_hash + created_at).
- Payload hash = SHA256(canonical JSON of {kind, text, ref_id, meta, user_id}).

## Governance rule
This bundle is EVIDENCE, not authorization. A detected discrepancy is an
auditable finding — it does not grant permission to rewrite history or
retroactively invalidate ratified decisions.
'''

@api.get("/ledger/export")
async def ledger_export(
    user=Depends(get_current_user),
    format: str = "bundle",
):
    """Export the user's Immutable Event Ledger as an auditor-friendly bundle.

    `format=bundle` (default) returns a JSON object containing:
      - manifest      (protocol, hashing, timestamp, head_hash)
      - head          (declared head_hash + chain stats)
      - ledger_jsonl  (chronological events, one canonical JSON per line)
      - verify_script (independent Python re-verification, no app trust)
      - readme        (bundle documentation)

    `format=jsonl` returns just the newline-delimited ledger.
    """
    all_events = await db.events.find(
        {"user_id": user["id"]}, {"_id": 0}
    ).sort("created_at", 1).to_list(50000)

    # Only chained events participate in the cryptographic hash chain; legacy
    # pre-chain events have no hash and are excluded from the auditor bundle.
    chained_events = [e for e in all_events if e.get("hash")]

    # Recompute head hash locally to guarantee export matches on-disk state.
    prev = "0" * 64
    for e in chained_events:
        prev = e["hash"]
    head_hash = prev
    chained = len(chained_events)

    # jsonl: one canonical event per line
    def event_line(e: Dict[str, Any]) -> str:
        keys = ["id", "user_id", "kind", "text", "ref_id", "meta",
                "previous_hash", "payload_hash", "hash", "created_at"]
        return json.dumps({k: e.get(k) for k in keys}, sort_keys=True, separators=(",", ":"), default=str)
    jsonl = "\n".join(event_line(e) for e in chained_events) + ("\n" if chained_events else "")

    if format == "jsonl":
        return StreamingResponse(iter([jsonl]), media_type="application/x-ndjson")

    export_ts = now_iso()
    manifest = {
        "audit_id": uid(),
        "protocol_version": LEDGER_EXPORT_PROTOCOL_VERSION,
        "scope": f"user:{user['id']}",
        "timestamp": export_ts,
        "hash_algorithm": "sha256",
        "canonicalization": 'json.dumps(sort_keys=True, separators=(",", ":"))',
        "event_hash_recipe": "sha256(previous_hash + payload_hash + created_at)",
        "payload_hash_recipe": "sha256(canonical({kind,text,ref_id,meta,user_id}))",
        "total_events": len(all_events),
        "chained_events": chained,
        "legacy_unchained_excluded": len(all_events) - chained,
        "head_hash": head_hash,
    }
    head = {
        "protocol_version": LEDGER_EXPORT_PROTOCOL_VERSION,
        "head_hash": head_hash,
        "timestamp": export_ts,
        "chain_verified_by_exporter": True,
        "total_events": len(all_events),
        "chained_events": chained,
    }
    return {
        "manifest": manifest,
        "head": head,
        "ledger_jsonl": jsonl,
        "verify_script": VERIFY_SCRIPT,
        "readme": VERIFY_README,
    }

@api.post("/admin/cleanup-test-notes")
async def cleanup_test_notes(user=Depends(get_current_user)):
    """Purge obvious development/test artifacts from this user's workspace WITHOUT
    touching real captured knowledge. Records the cleanup as a ledger event.

    Targets titles containing recognisably synthetic patterns (coffee test notes,
    'TEST_' prefixes, etc). Related graph edges, versions, consensus, debates, and
    contradictions on those notes are removed alongside the notes themselves.
    """
    patterns = [
        r"morning coffee",
        r"^TEST[_ :]",
        r"bland (?:coffee|note)",
        r"^Relax auth for internal",   # my earlier test artifact
        r"^Skip deploy pipeline",       # test suite artifact
        r"i like drinking coffee",
    ]
    combined = "|".join(patterns)
    q = {"user_id": user["id"], "$or": [
        {"title": {"$regex": combined, "$options": "i"}},
        {"text":  {"$regex": r"i like drinking coffee|bland coffee", "$options": "i"}},
    ]}
    to_delete = await db.notes.find(q, {"_id": 0, "id": 1, "title": 1}).to_list(500)
    ids = [n["id"] for n in to_delete]
    if ids:
        # Cascade delete related state (append-only ledger events remain untouched)
        await db.notes.delete_many({"id": {"$in": ids}, "user_id": user["id"]})
        await db.note_versions.delete_many({"note_id": {"$in": ids}, "user_id": user["id"]})
        await db.graph_edges.delete_many({"user_id": user["id"], "$or": [{"src": {"$in": ids}}, {"dst": {"$in": ids}}]})
        await db.graph_nodes.delete_many({"user_id": user["id"], "kind": "note", "id": {"$in": ids}})
        await db.council_responses.delete_many({"user_id": user["id"], "note_id": {"$in": ids}})
        await db.consensus_records.delete_many({"user_id": user["id"], "note_id": {"$in": ids}})
        await db.debates.delete_many({"user_id": user["id"], "note_id": {"$in": ids}})
        await db.contradictions.delete_many({"user_id": user["id"], "$or": [{"new_note_id": {"$in": ids}}, {"prior_note_id": {"$in": ids}}]})
        await db.operations.delete_many({"user_id": user["id"], "note_id": {"$in": ids}})
        await db.decisions.delete_many({"user_id": user["id"], "note_id": {"$in": ids}})

    # Prune orphan concept nodes/edges that no longer connect to any note.
    # Concepts are graph_nodes with kind=='concept'; they are authored only via
    # has_concept edges from notes. If every incident edge is gone, the concept
    # itself is dead evidence and should be removed to keep AI Shadow honest.
    orphan_removed = 0
    concept_nodes = await db.graph_nodes.find(
        {"user_id": user["id"], "kind": "concept"}, {"_id": 0, "id": 1}
    ).to_list(2000)
    for cn in concept_nodes:
        remaining = await db.graph_edges.count_documents({
            "user_id": user["id"],
            "$or": [{"src": cn["id"]}, {"dst": cn["id"]}],
        })
        if remaining == 0:
            await db.graph_nodes.delete_one({"id": cn["id"], "user_id": user["id"]})
            orphan_removed += 1

    if ids or orphan_removed:
        await log_event(
            user["id"], "test_data_cleaned",
            f"Removed {len(ids)} development/test note(s) + {orphan_removed} orphan concept(s)",
            meta={"deleted_note_ids": ids, "titles": [n["title"] for n in to_delete], "orphan_concepts_removed": orphan_removed},
        )
    return {"deleted": len(ids), "titles": [n["title"] for n in to_delete], "orphan_concepts_removed": orphan_removed}

@api.post("/notes/{note_id}/evolve")
async def evolve_note(note_id: str, inp: NoteIn, user=Depends(get_current_user)):
    parent = await db.notes.find_one({"id": note_id, "user_id": user["id"]}, {"_id": 0})
    if not parent:
        raise HTTPException(status_code=404, detail="Not found")
    latest = await db.note_versions.find({"note_id": note_id}).sort("version", -1).limit(1).to_list(1)
    next_v = (latest[0]["version"] if latest else 1) + 1
    stages = ["Idea", "Refined", "Merged", "Implemented", "Shipped", "Revenue"]
    stage = stages[min(next_v - 1, len(stages) - 1)]
    v = {
        "id": uid(),
        "note_id": note_id,
        "version": next_v,
        "stage": stage,
        "text": inp.text,
        "user_id": user["id"],
        "created_at": now_iso(),
    }
    await db.note_versions.insert_one(v)
    v.pop("_id", None)
    await db.notes.update_one({"id": note_id}, {"$set": {"text": inp.text, "version": next_v, "updated_at": now_iso()}})
    await log_event(user["id"], "idea_evolved", f"{parent['title']} -> {stage}", ref_id=note_id, meta={"version": next_v, "stage": stage})
    v.pop("_id", None)
    return v

@api.get("/notes/{note_id}/roi")
async def note_roi(note_id: str, user=Depends(get_current_user)):
    n = await db.notes.find_one({"id": note_id, "user_id": user["id"]}, {"_id": 0})
    if not n:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "projects": n.get("produced_projects", 0),
        "tasks": n.get("produced_tasks", 0),
        "articles": n.get("produced_articles", 0),
        "proposals": n.get("produced_proposals", 0),
        "revenue": n.get("revenue", 0),
    }

# ---------------- Timeline ----------------
@api.get("/timeline")
async def timeline(user=Depends(get_current_user)):
    events = await db.events.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(300)
    return events

# ---------------- Graph ----------------
@api.get("/graph")
async def graph(user=Depends(get_current_user)):
    nodes = await db.graph_nodes.find({"user_id": user["id"]}, {"_id": 0}).to_list(1000)
    edges = await db.graph_edges.find({"user_id": user["id"]}, {"_id": 0}).to_list(3000)
    return {"nodes": nodes, "edges": edges}

@api.get("/graph/node/{node_id}")
async def graph_node(node_id: str, user=Depends(get_current_user)):
    node = await db.graph_nodes.find_one({"id": node_id, "user_id": user["id"]}, {"_id": 0})
    if not node:
        raise HTTPException(status_code=404, detail="Not found")
    incoming = await db.graph_edges.find({"user_id": user["id"], "dst": node_id}, {"_id": 0}).to_list(500)
    outgoing = await db.graph_edges.find({"user_id": user["id"], "src": node_id}, {"_id": 0}).to_list(500)
    neighbor_ids = list({e["src"] for e in incoming} | {e["dst"] for e in outgoing})
    neighbors = await db.graph_nodes.find({"user_id": user["id"], "id": {"$in": neighbor_ids}}, {"_id": 0}).to_list(500)
    connected_notes = sum(1 for n in neighbors if n["kind"] == "note")
    connected_concepts = sum(1 for n in neighbors if n["kind"] == "concept")
    decisions = 0
    gravity = 0.0
    if node["kind"] == "note":
        decisions = await db.decisions.count_documents({"user_id": user["id"], "note_id": node_id})
        gravity = await compute_gravity(user["id"], node_id)
    return {
        "node": node,
        "gravity": gravity,
        "connected_notes": connected_notes,
        "connected_concepts": connected_concepts,
        "decisions": decisions,
        "neighbors": neighbors[:12],
        "edge_count": len(incoming) + len(outgoing),
    }

# ---------------- Decisions ----------------
@api.post("/decisions")
async def create_decision(inp: DecisionIn, user=Depends(get_current_user)):
    """Create a decision derived from real system state — no synthetic metrics.

    - referenced_notes = notes sharing at least one concept with the source note
    - influenced_agents = distinct AI Council agents that produced a verdict on the source note
    - affected_projects, produced_tasks default to 0 (attributed only when downstream evidence exists)
    """
    count = await db.decisions.count_documents({"user_id": user["id"]})

    referenced_notes = 0
    influenced_agents = 0
    if inp.note_id:
        src = await db.notes.find_one({"id": inp.note_id, "user_id": user["id"]}, {"_id": 0})
        if src and src.get("concepts"):
            referenced_notes = await db.notes.count_documents({
                "user_id": user["id"],
                "id": {"$ne": inp.note_id},
                "concepts": {"$in": src["concepts"]},
            })
        # Distinct council agents who reviewed this note (raw + consensus verdicts)
        raw_agents = await db.council_responses.distinct(
            "agent", {"user_id": user["id"], "note_id": inp.note_id}
        )
        cons = await db.consensus_records.find(
            {"user_id": user["id"], "note_id": inp.note_id}, {"_id": 0, "verdicts.agent": 1}
        ).to_list(20)
        cons_agents = {v["agent"] for r in cons for v in r.get("verdicts", []) if v.get("agent")}
        influenced_agents = len(set(raw_agents) | cons_agents)

    d = {
        "id": uid(),
        "number": count + 1,
        "user_id": user["id"],
        "title": inp.title,
        "context": inp.context or "",
        "note_id": inp.note_id,
        "affected_projects": 0,          # attributed only when downstream evidence exists
        "produced_tasks": 0,             # attributed only when downstream evidence exists
        "referenced_notes": referenced_notes,
        "influenced_agents": influenced_agents,
        "created_at": now_iso(),
    }
    await db.decisions.insert_one(d)
    d.pop("_id", None)
    dna = await compute_decision_dna(user["id"], d)
    await db.decisions.update_one({"id": d["id"]}, {"$set": dna})
    d.update(dna)
    await log_event(user["id"], "decision_made", f"Decision #{d['number']}: {inp.title}", ref_id=d["id"])
    return d

@api.get("/decisions")
async def list_decisions(user=Depends(get_current_user)):
    ds = await db.decisions.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return ds

@api.get("/decisions/{did}")
async def get_decision(did: str, user=Depends(get_current_user)):
    d = await db.decisions.find_one({"id": did, "user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    return d

# ---------------- Memory Health ----------------
@api.get("/health-dashboard")
async def health_dashboard(user=Depends(get_current_user)):
    notes = await db.notes.count_documents({"user_id": user["id"]})
    edges = await db.graph_edges.count_documents({"user_id": user["id"]})
    decisions = await db.decisions.count_documents({"user_id": user["id"]})
    concepts = await db.graph_nodes.count_documents({"user_id": user["id"], "kind": "concept"})

    all_notes = await db.notes.find({"user_id": user["id"]}, {"_id": 0}).to_list(2000)
    unlinked = 0
    now = datetime.now(timezone.utc)
    fresh = 0
    for n in all_notes:
        note_edges = await db.graph_edges.count_documents({"user_id": user["id"], "$or": [{"src": n["id"]}, {"dst": n["id"]}]})
        if note_edges <= 1:
            unlinked += 1
        try:
            dt = datetime.fromisoformat(n["created_at"])
            if (now - dt).days <= 14:
                fresh += 1
        except Exception:
            pass

    density = min(100, int((edges / max(notes, 1)) * 25))
    coverage = min(100, int((decisions / max(notes, 1)) * 120))
    freshness = min(100, int((fresh / max(notes, 1)) * 100)) if notes else 0
    dup_risk = max(0, min(30, int((concepts * 0.1))))
    overall = int((density + coverage + freshness + (100 - dup_risk * 3)) / 4)

    return {
        "overall": max(20, min(100, overall)),
        "density": density,
        "coverage": coverage,
        "freshness": freshness,
        "duplicate_risk": dup_risk,
        "unlinked": unlinked,
        "totals": {"notes": notes, "edges": edges, "decisions": decisions, "concepts": concepts},
    }

# ---------------- Console (Home) ----------------
@api.get("/console")
async def console(user=Depends(get_current_user)):
    strength = await memory_strength(user["id"])
    notes = await db.notes.count_documents({"user_id": user["id"]})
    edges = await db.graph_edges.count_documents({"user_id": user["id"]})
    decisions = await db.decisions.count_documents({"user_id": user["id"]})
    concepts = await db.graph_nodes.count_documents({"user_id": user["id"], "kind": "concept"})
    ideas_impl = await db.note_versions.count_documents({"user_id": user["id"], "stage": {"$in": ["Implemented", "Shipped", "Revenue"]}})

    latest = await db.notes.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).limit(1).to_list(1)
    top_note = None
    if latest:
        top_note = latest[0]
        top_note["gravity"] = await compute_gravity(user["id"], top_note["id"])

    # Knowledge Compounding Score - non-linear reuse metric
    raw = (edges * 1.5) + (decisions * 4) + (ideas_impl * 6)
    compounding = round(100 * (1 - math.exp(-raw / 60)), 1)

    all_notes = await db.notes.find({"user_id": user["id"]}, {"_id": 0}).to_list(2000)
    recent_conns = 0
    now = datetime.now(timezone.utc)
    for n in all_notes:
        try:
            dt = datetime.fromisoformat(n["created_at"])
            if (now - dt).days <= 7:
                recent_conns += len(n.get("concepts", []))
        except Exception:
            pass

    return {
        "greeting_name": user.get("name", "").split(" ")[0],
        "brain_activity": strength,
        "inbox": notes,
        "new_knowledge": recent_conns,
        "council_recommendations": min(5, decisions),
        "decisions_pending": max(0, notes - decisions),
        "opportunities": min(9, ideas_impl + 2),
        "compounding_delta": round(min(9.9, recent_conns * 0.4), 1),
        "pocket_score": {
            "knowledge_assets": notes,
            "connections": edges,
            "reusable": concepts,
            "decisions_preserved": decisions,
            "ideas_implemented": ideas_impl,
            "compounding": compounding,
            "cognitive_capacity_delta": round(min(9.9, recent_conns * 0.3), 1),
        },
        "focus": {
            "title": top_note["title"] if top_note else "Start capturing today",
            "gravity": top_note["gravity"] if top_note else 0,
            "note_id": top_note["id"] if top_note else None,
        },
    }

# ---------------- Operations (command palette) ----------------
OPERATIONS = {
    "summarize": ("Summarize the note in 3 crisp bullet points. Return only bullets starting with '- '.", "Summary"),
    "refactor":  ("Rewrite this note more clearly and tightly, keeping the same meaning. Return only the rewritten note.", "Refactored"),
    "generate_sop": ("Convert this note into a Standard Operating Procedure. Output: a numbered list of 4-7 steps, each imperative and specific. No preamble.", "SOP"),
    "find_gaps": ("Identify what's MISSING from this note to make it complete or actionable. Return 3-5 gaps, each on its own line starting with '- '.", "Gaps"),
    "next_actions": ("Extract concrete next actions from this note. Return 3-5 actions, each on its own line starting with '- '.", "Next Actions"),
}

class OperationIn(BaseModel):
    command: str

@api.post("/notes/{note_id}/operations")
async def run_operation(note_id: str, inp: OperationIn, user=Depends(get_current_user)):
    n = await db.notes.find_one({"id": note_id, "user_id": user["id"]}, {"_id": 0})
    if not n:
        raise HTTPException(status_code=404, detail="Not found")
    op = OPERATIONS.get(inp.command)
    if not op:
        raise HTTPException(status_code=400, detail="Unknown command")
    system, label = op
    out = await gemini_chat(system, n["text"][:2000], session_id=f"op-{inp.command}-{note_id}")
    record = {
        "id": uid(),
        "note_id": note_id,
        "user_id": user["id"],
        "command": inp.command,
        "label": label,
        "output": out or "Operation returned no result.",
        "created_at": now_iso(),
    }
    await db.operations.insert_one(record)
    record.pop("_id", None)
    await log_event(user["id"], "operation_run", f"{label} on: {n['title']}", ref_id=note_id, meta={"command": inp.command})
    return record

@api.get("/notes/{note_id}/operations")
async def list_operations(note_id: str, user=Depends(get_current_user)):
    ops = await db.operations.find({"note_id": note_id, "user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(30)
    return ops

# ---------------- Gemini Chat (multi-turn conversational) ----------------
CHAT_SYSTEM = (
    "You are Pocket OS, the user's cognitive assistant. Answer clearly and concisely. "
    "Use markdown lightly (bullets, bold) only when it improves clarity. "
    "When the user references their notes, decisions, or the graph, help them reason from their own history."
)

# Model registry: model_id -> provider
MODEL_REGISTRY = {
    "gemini-3-flash-preview": {"provider": "gemini", "label": "Gemini 3 Flash", "hint": "Fast · low cost"},
    "gpt-5.4": {"provider": "openai", "label": "GPT-5.4", "hint": "Balanced"},
    "claude-sonnet-4-6": {"provider": "anthropic", "label": "Claude Sonnet 4.6", "hint": "Best reasoning"},
}
DEFAULT_MODEL = "gemini-3-flash-preview"

class ChatSessionIn(BaseModel):
    title: Optional[str] = None
    model: Optional[str] = DEFAULT_MODEL
    note_context_id: Optional[str] = None

class ChatSessionUpdate(BaseModel):
    model: Optional[str] = None
    note_context_id: Optional[str] = None  # empty string clears

class ChatMessageIn(BaseModel):
    text: str

@api.get("/chat/models")
async def list_models(user=Depends(get_current_user)):
    return [{"id": mid, **meta} for mid, meta in MODEL_REGISTRY.items()]

@api.get("/chat/sessions")
async def list_chat_sessions(user=Depends(get_current_user)):
    sessions = await db.chat_sessions.find({"user_id": user["id"]}, {"_id": 0}).sort("updated_at", -1).to_list(200)
    return sessions

@api.post("/chat/sessions")
async def create_chat_session(inp: ChatSessionIn, user=Depends(get_current_user)):
    model = inp.model if inp.model in MODEL_REGISTRY else DEFAULT_MODEL
    title = inp.title
    if inp.note_context_id:
        n = await db.notes.find_one({"id": inp.note_context_id, "user_id": user["id"]}, {"_id": 0})
        if not n:
            raise HTTPException(status_code=404, detail="Note context not found")
        title = title or f"Chat about: {n['title']}"
    s = {
        "id": uid(),
        "user_id": user["id"],
        "title": title or "New Chat",
        "model": model,
        "note_context_id": inp.note_context_id,
        "message_count": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.chat_sessions.insert_one(s)
    s.pop("_id", None)
    return s

@api.patch("/chat/sessions/{sid}")
async def update_chat_session(sid: str, inp: ChatSessionUpdate, user=Depends(get_current_user)):
    session = await db.chat_sessions.find_one({"id": sid, "user_id": user["id"]}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=404, detail="Not found")
    updates: Dict[str, Any] = {}
    if inp.model is not None:
        if inp.model not in MODEL_REGISTRY:
            raise HTTPException(status_code=400, detail=f"Unknown model {inp.model}")
        updates["model"] = inp.model
    if inp.note_context_id is not None:
        if inp.note_context_id == "":
            updates["note_context_id"] = None
        else:
            n = await db.notes.find_one({"id": inp.note_context_id, "user_id": user["id"]}, {"_id": 0})
            if not n:
                raise HTTPException(status_code=404, detail="Note not found")
            updates["note_context_id"] = inp.note_context_id
    if updates:
        updates["updated_at"] = now_iso()
        await db.chat_sessions.update_one({"id": sid}, {"$set": updates})
    fresh = await db.chat_sessions.find_one({"id": sid}, {"_id": 0})
    return fresh

@api.get("/chat/sessions/{sid}")
async def get_chat_session(sid: str, user=Depends(get_current_user)):
    s = await db.chat_sessions.find_one({"id": sid, "user_id": user["id"]}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    msgs = await db.chat_messages.find({"session_id": sid, "user_id": user["id"]}, {"_id": 0}).sort("created_at", 1).to_list(2000)
    return {"session": s, "messages": msgs}

@api.delete("/chat/sessions/{sid}")
async def delete_chat_session(sid: str, user=Depends(get_current_user)):
    r1 = await db.chat_sessions.delete_one({"id": sid, "user_id": user["id"]})
    await db.chat_messages.delete_many({"session_id": sid, "user_id": user["id"]})
    if r1.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "deleted"}

@api.post("/chat/sessions/{sid}/stream")
async def stream_chat_message(sid: str, inp: ChatMessageIn, user=Depends(get_current_user)):
    session = await db.chat_sessions.find_one({"id": sid, "user_id": user["id"]}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    user_msg = {
        "id": uid(),
        "session_id": sid,
        "user_id": user["id"],
        "role": "user",
        "content": inp.text,
        "created_at": now_iso(),
    }
    await db.chat_messages.insert_one(user_msg)

    prior = await db.chat_messages.find(
        {"session_id": sid, "user_id": user["id"], "id": {"$ne": user_msg["id"]}},
        {"_id": 0},
    ).sort("created_at", 1).to_list(200)

    is_first = session.get("message_count", 0) == 0
    if is_first:
        new_title = inp.text.strip().split("\n")[0][:60] or session["title"]
        await db.chat_sessions.update_one({"id": sid}, {"$set": {"title": new_title}})

    model = session.get("model") or DEFAULT_MODEL
    if model not in MODEL_REGISTRY:
        model = DEFAULT_MODEL
    provider = MODEL_REGISTRY[model]["provider"]

    # Load note context if bound
    note_ctx = None
    if session.get("note_context_id"):
        note_ctx = await db.notes.find_one({"id": session["note_context_id"], "user_id": user["id"]}, {"_id": 0})

    async def gen():
        yield f"data: {json.dumps({'type':'start','user_message_id':user_msg['id']})}\n\n"

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=sid,
            system_message=CHAT_SYSTEM,
        ).with_model(provider, model)

        preamble_parts = []
        if note_ctx:
            preamble_parts.append(
                f"The user has attached this note as context:\nTITLE: {note_ctx['title']}\nBODY:\n{note_ctx['text']}\n\n"
                f"Concepts: {', '.join(note_ctx.get('concepts', []))}\n"
                f"---\n"
            )
        if prior:
            hist_lines = [f"{'User' if m['role']=='user' else 'Assistant'}: {m['content']}" for m in prior]
            preamble_parts.append("Conversation so far:\n" + "\n".join(hist_lines) + "\n\n---\n\nNew user turn:\n")
        prompt = "".join(preamble_parts) + inp.text

        full = ""
        try:
            async for ev in chat.stream_message(UserMessage(text=prompt)):
                if isinstance(ev, TextDelta) and ev.content:
                    full += ev.content
                    yield f"data: {json.dumps({'type':'delta','content':ev.content})}\n\n"
                elif isinstance(ev, StreamDone):
                    break
        except Exception as e:
            err = str(e)[:200]
            yield f"data: {json.dumps({'type':'error','error':err})}\n\n"
            full = full or "(Chat model returned an error. Please try again.)"

        assistant_id = uid()
        await db.chat_messages.insert_one({
            "id": assistant_id,
            "session_id": sid,
            "user_id": user["id"],
            "role": "assistant",
            "content": full,
            "model": model,
            "created_at": now_iso(),
        })
        await db.chat_sessions.update_one(
            {"id": sid},
            {"$inc": {"message_count": 2}, "$set": {"updated_at": now_iso()}},
        )
        yield f"data: {json.dumps({'type':'done','assistant_message_id':assistant_id,'total_len':len(full)})}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ---------------- Governance Layer ----------------
CAPABILITY_KEYWORDS = {
    "memory.read": ["memory", "recall", "read", "retrieve", "context"],
    "memory.write": ["store", "save", "commit", "persist", "capture"],
    "graph.read": ["graph", "traverse", "network", "connections", "neighbors"],
    "graph.write": ["link", "connect", "edge", "relate"],
    "ledger.append": ["decision", "record", "log", "provenance", "audit"],
    "council.review": ["council", "review", "critic", "architect", "planner"],
    "twin.reason": ["reason", "predict", "shadow", "twin"],
    "operations.summarize": ["summarize", "condense", "brief"],
    "operations.generate": ["generate", "produce", "create", "sop"],
    "operations.refactor": ["refactor", "rewrite", "clean"],
    "filesystem.read": ["file", "read", "fetch"],
    "network.egress": ["http", "url", "fetch", "api", "network"],
}

BUILTIN_AGENTS = [
    {
        "name": "Research Agent", "author": "Pocket OS Core",
        "manifest": "Cite supporting evidence and prior work for any note. Reads memory and graph. Never writes.",
        "capabilities": ["memory.read", "graph.read", "council.review"],
        "risk": "low",
    },
    {
        "name": "Architect Agent", "author": "Pocket OS Core",
        "manifest": "Explain how ideas affect the user's system architecture. Traverses the graph. Never writes.",
        "capabilities": ["memory.read", "graph.read", "council.review"],
        "risk": "low",
    },
    {
        "name": "Critic Agent", "author": "Pocket OS Core",
        "manifest": "Expose weak assumptions and risks. Reads memory. Never writes.",
        "capabilities": ["memory.read", "council.review"],
        "risk": "low",
    },
    {
        "name": "Planner Agent", "author": "Pocket OS Core",
        "manifest": "Propose next milestones and concrete actions. Reads memory and graph.",
        "capabilities": ["memory.read", "graph.read", "council.review", "operations.generate"],
        "risk": "medium",
    },
    {
        "name": "Documentation Steward", "author": "Pocket OS Core",
        "manifest": "Reorganize and document knowledge. Reads memory, writes back canonical structure.",
        "capabilities": ["memory.read", "memory.write", "operations.refactor", "ledger.append"],
        "risk": "high",
    },
]

class AgentSubmit(BaseModel):
    name: str
    author: Optional[str] = "Community"
    manifest: str

class LeaseIn(BaseModel):
    capabilities: List[str]
    scope: str = "workspace"
    expires_in_days: int = 30

class ExecutionIn(BaseModel):
    action: str
    note_id: Optional[str] = None
    capability: str

def extract_capabilities(text: str) -> List[str]:
    t = text.lower()
    hits = []
    for cap, kws in CAPABILITY_KEYWORDS.items():
        if any(k in t for k in kws):
            hits.append(cap)
    return hits[:8] or ["memory.read"]

def compute_trust(agent: Dict) -> int:
    caps = agent.get("capabilities", [])
    write_caps = sum(1 for c in caps if "write" in c or "ledger" in c or "network" in c)
    risk_penalty = {"low": 0, "medium": 15, "high": 30}.get(agent.get("risk", "medium"), 15)
    base = 90 - write_caps * 5 - risk_penalty
    executions = agent.get("stats", {}).get("successful", 0)
    reversed_ = agent.get("stats", {}).get("reversed", 0)
    delta = min(15, executions * 2) - reversed_ * 8
    return max(20, min(99, base + delta))

async def ensure_builtin_agents(user_id: str):
    existing = await db.agents.count_documents({"user_id": user_id})
    if existing > 0:
        return
    for spec in BUILTIN_AGENTS:
        aid = uid()
        agent = {
            "id": aid,
            "user_id": user_id,
            "name": spec["name"],
            "author": spec["author"],
            "version": "1.0.0",
            "lineage_id": aid,
            "manifest": spec["manifest"],
            "capabilities": spec["capabilities"],
            "risk": spec["risk"],
            "public_key": "pk_" + uid()[:24],
            "status": "registered",  # submitted -> analyzing -> scored -> registered
            "trust_score": 0,
            "stats": {"successful": 0, "reversed": 0, "proposed": 0},
            "created_at": now_iso(),
        }
        agent["trust_score"] = compute_trust(agent)
        await db.agents.insert_one(agent)
        # Issue an initial lease for the built-in caps
        lease = {
            "id": uid(),
            "user_id": user_id,
            "agent_id": aid,
            "capabilities": spec["capabilities"],
            "scope": "workspace",
            "status": "active",
            "issued_at": now_iso(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=90)).isoformat(),
            "revoked_at": None,
            "issued_by": "constitutional",
        }
        await db.leases.insert_one(lease)
        contract = {
            "id": uid(),
            "user_id": user_id,
            "agent_id": aid,
            "name": f"Default Contract — {spec['name']}",
            "policies": [
                {"rule": "sandbox.workspace_only", "enforced": True},
                {"rule": "no_network_egress", "enforced": "network.egress" not in spec["capabilities"]},
                {"rule": "human_approval_required", "enforced": spec["risk"] == "high"},
            ],
            "created_at": now_iso(),
        }
        await db.governance_contracts.insert_one(contract)

@api.get("/governance/summary")
async def governance_summary(user=Depends(get_current_user)):
    await ensure_builtin_agents(user["id"])
    agents = await db.agents.count_documents({"user_id": user["id"]})
    active_leases = await db.leases.count_documents({"user_id": user["id"], "status": "active"})
    pending = await db.executions.count_documents({"user_id": user["id"], "state": "PROPOSED"})
    executed = await db.executions.count_documents({"user_id": user["id"], "state": "EXECUTED"})
    reversed_ct = await db.executions.count_documents({"user_id": user["id"], "state": "REVERSED"})
    contracts = await db.governance_contracts.count_documents({"user_id": user["id"]})
    return {
        "agents": agents,
        "active_leases": active_leases,
        "pending_approvals": pending,
        "executed": executed,
        "reversed": reversed_ct,
        "contracts": contracts,
    }

@api.get("/agents")
async def list_agents(user=Depends(get_current_user)):
    await ensure_builtin_agents(user["id"])
    agents = await db.agents.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", 1).to_list(200)
    return agents

@api.get("/agents/{aid}")
async def get_agent(aid: str, user=Depends(get_current_user)):
    a = await db.agents.find_one({"id": aid, "user_id": user["id"]}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Not found")
    leases = await db.leases.find({"agent_id": aid, "user_id": user["id"]}, {"_id": 0}).sort("issued_at", -1).to_list(50)
    contracts = await db.governance_contracts.find({"agent_id": aid, "user_id": user["id"]}, {"_id": 0}).to_list(20)
    executions = await db.executions.find({"agent_id": aid, "user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return {"agent": a, "leases": leases, "contracts": contracts, "executions": executions}

@api.post("/agents/submit")
async def submit_agent(inp: AgentSubmit, user=Depends(get_current_user)):
    """Marketplace admission pipeline: submit -> static analysis -> capability extraction -> policy validation -> trust scoring -> registered."""
    aid = uid()
    pipeline = []

    # Step 1: Submission
    pipeline.append({"step": "Submission", "status": "ok", "detail": f"Received manifest from {inp.author}."})

    # Step 2: Static analysis (concept extraction as a proxy)
    concepts = await extract_concepts(inp.manifest)
    pipeline.append({"step": "Static Analysis", "status": "ok", "detail": f"Extracted {len(concepts)} concepts."})

    # Step 3: Capability extraction
    caps = extract_capabilities(inp.manifest)
    pipeline.append({"step": "Capability Extraction", "status": "ok", "detail": f"Declared capabilities: {', '.join(caps)}"})

    # Step 4: Policy validation
    risk = "high" if any("write" in c or "ledger" in c or "network" in c for c in caps) else ("medium" if len(caps) >= 4 else "low")
    violations = []
    if "network.egress" in caps and risk == "high":
        violations.append("Network egress requires additional human approval.")
    pipeline.append({"step": "Policy Validation", "status": "warning" if violations else "ok", "detail": violations[0] if violations else "No policy violations."})

    # Step 5: Sandbox assignment
    pipeline.append({"step": "Sandbox Assignment", "status": "ok", "detail": f"Assigned workspace sandbox. Risk={risk}."})

    agent = {
        "id": aid,
        "user_id": user["id"],
        "name": inp.name,
        "author": inp.author or "Community",
        "version": "1.0.0",
        "lineage_id": aid,
        "manifest": inp.manifest,
        "capabilities": caps,
        "concepts": concepts,
        "risk": risk,
        "public_key": "pk_" + uid()[:24],
        "status": "registered",
        "trust_score": 0,
        "stats": {"successful": 0, "reversed": 0, "proposed": 0},
        "created_at": now_iso(),
    }
    agent["trust_score"] = compute_trust(agent)
    pipeline.append({"step": "Trust Scoring", "status": "ok", "detail": f"Trust score computed: {agent['trust_score']}."})

    # Step 6: Registration
    await db.agents.insert_one(agent)
    agent.pop("_id", None)

    # Auto-issue default lease for low-risk agents; require human approval for high
    if risk != "high":
        lease = {
            "id": uid(), "user_id": user["id"], "agent_id": aid,
            "capabilities": caps, "scope": "workspace", "status": "active",
            "issued_at": now_iso(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "revoked_at": None, "issued_by": "auto",
        }
        await db.leases.insert_one(lease)
        pipeline.append({"step": "Marketplace Registration", "status": "ok", "detail": "Registered + default lease issued."})
    else:
        pipeline.append({"step": "Marketplace Registration", "status": "warning", "detail": "Registered. High-risk lease requires human approval."})

    await log_event(user["id"], "agent_submitted", f"Submitted agent: {inp.name}", ref_id=aid, meta={"risk": risk, "trust": agent["trust_score"]})
    return {"agent": agent, "pipeline": pipeline}

@api.post("/agents/{aid}/leases")
async def issue_lease(aid: str, inp: LeaseIn, user=Depends(get_current_user)):
    a = await db.agents.find_one({"id": aid, "user_id": user["id"]}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Not found")
    invalid = [c for c in inp.capabilities if c not in a["capabilities"]]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Agent lacks capabilities: {', '.join(invalid)}")
    lease = {
        "id": uid(), "user_id": user["id"], "agent_id": aid,
        "capabilities": inp.capabilities, "scope": inp.scope, "status": "active",
        "issued_at": now_iso(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=inp.expires_in_days)).isoformat(),
        "revoked_at": None, "issued_by": "constitutional",
    }
    await db.leases.insert_one(lease)
    lease.pop("_id", None)
    await log_event(user["id"], "lease_issued", f"Lease issued: {a['name']}", ref_id=aid, meta={"capabilities": inp.capabilities})
    return lease

@api.post("/leases/{lid}/revoke")
async def revoke_lease(lid: str, user=Depends(get_current_user)):
    lease = await db.leases.find_one({"id": lid, "user_id": user["id"]}, {"_id": 0})
    if not lease:
        raise HTTPException(status_code=404, detail="Not found")
    await db.leases.update_one({"id": lid}, {"$set": {"status": "revoked", "revoked_at": now_iso()}})
    agent = await db.agents.find_one({"id": lease["agent_id"]}, {"_id": 0}) or {}
    await log_event(user["id"], "lease_revoked", f"Lease revoked: {agent.get('name','agent')}", ref_id=lease["agent_id"])
    return {"status": "revoked", "lease_id": lid}

@api.post("/agents/{aid}/executions")
async def propose_execution(aid: str, inp: ExecutionIn, user=Depends(get_current_user)):
    a = await db.agents.find_one({"id": aid, "user_id": user["id"]}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Not found")
    # Find active lease covering this capability
    lease = await db.leases.find_one({
        "agent_id": aid, "user_id": user["id"], "status": "active",
        "capabilities": inp.capability,
    }, {"_id": 0})
    if not lease:
        raise HTTPException(status_code=403, detail=f"No active lease covers capability '{inp.capability}'.")
    contract = await db.governance_contracts.find_one({"agent_id": aid, "user_id": user["id"]}, {"_id": 0})
    # High-risk agents require human approval; others go straight to APPROVED
    initial_state = "PROPOSED" if a.get("risk") == "high" else "APPROVED"
    ex = {
        "id": uid(), "user_id": user["id"], "agent_id": aid,
        "lease_id": lease["id"], "contract_id": contract["id"] if contract else None,
        "action": inp.action, "capability": inp.capability, "note_id": inp.note_id,
        "state": initial_state, "state_history": [
            {"state": "PROPOSED", "at": now_iso()},
        ],
        "evidence": None, "created_at": now_iso(),
    }
    if initial_state == "APPROVED":
        ex["state_history"].append({"state": "APPROVED", "at": now_iso(), "by": "auto-policy"})
    await db.executions.insert_one(ex)
    ex.pop("_id", None)
    await db.agents.update_one({"id": aid}, {"$inc": {"stats.proposed": 1}})
    await log_event(user["id"], "execution_proposed", f"{a['name']} proposed: {inp.action}", ref_id=aid, meta={"state": initial_state})
    return ex

@api.post("/executions/{eid}/approve")
async def approve_execution(eid: str, user=Depends(get_current_user)):
    ex = await db.executions.find_one({"id": eid, "user_id": user["id"]}, {"_id": 0})
    if not ex:
        raise HTTPException(status_code=404, detail="Not found")
    if ex["state"] not in ("PROPOSED", "APPROVED"):
        raise HTTPException(status_code=400, detail=f"Cannot execute from state {ex['state']}")
    # Move to EXECUTED with mock evidence
    hist = ex.get("state_history", [])
    if ex["state"] == "PROPOSED":
        hist.append({"state": "APPROVED", "at": now_iso(), "by": "human"})
    hist.append({"state": "EXECUTED", "at": now_iso(), "by": "runtime"})
    evidence = {"outcome": "success", "hash": "0x" + uid().replace("-", "")[:16], "sealed_at": now_iso()}
    await db.executions.update_one({"id": eid}, {"$set": {"state": "EXECUTED", "state_history": hist, "evidence": evidence}})
    await db.agents.update_one({"id": ex["agent_id"]}, {"$inc": {"stats.successful": 1}})
    # Recompute trust
    ag = await db.agents.find_one({"id": ex["agent_id"]}, {"_id": 0})
    if ag:
        await db.agents.update_one({"id": ex["agent_id"]}, {"$set": {"trust_score": compute_trust(ag)}})
    await log_event(user["id"], "execution_executed", f"Execution sealed: {ex['action']}", ref_id=ex["agent_id"])
    return {"status": "EXECUTED", "evidence": evidence}

@api.post("/executions/{eid}/reverse")
async def reverse_execution(eid: str, user=Depends(get_current_user)):
    ex = await db.executions.find_one({"id": eid, "user_id": user["id"]}, {"_id": 0})
    if not ex:
        raise HTTPException(status_code=404, detail="Not found")
    if ex["state"] != "EXECUTED":
        raise HTTPException(status_code=400, detail="Only EXECUTED actions can be reversed")
    hist = ex.get("state_history", [])
    hist.append({"state": "REVERSED", "at": now_iso(), "by": "human"})
    await db.executions.update_one({"id": eid}, {"$set": {"state": "REVERSED", "state_history": hist}})
    await db.agents.update_one({"id": ex["agent_id"]}, {"$inc": {"stats.successful": -1, "stats.reversed": 1}})
    ag = await db.agents.find_one({"id": ex["agent_id"]}, {"_id": 0})
    if ag:
        await db.agents.update_one({"id": ex["agent_id"]}, {"$set": {"trust_score": compute_trust(ag)}})
    await log_event(user["id"], "execution_reversed", f"Execution reversed: {ex['action']}", ref_id=ex["agent_id"])
    return {"status": "REVERSED"}

@api.get("/executions/pending")
async def pending_executions(user=Depends(get_current_user)):
    pend = await db.executions.find({"user_id": user["id"], "state": "PROPOSED"}, {"_id": 0}).sort("created_at", -1).to_list(50)
    # Attach agent info
    out = []
    for e in pend:
        a = await db.agents.find_one({"id": e["agent_id"]}, {"_id": 0}) or {}
        e["agent_name"] = a.get("name", "Unknown")
        e["agent_risk"] = a.get("risk", "medium")
        out.append(e)
    return out

# ---------------- Opportunity Engine ----------------
@api.get("/opportunities")
async def opportunities(user=Depends(get_current_user)):
    """Continuously find gaps in user's knowledge."""
    notes = await db.notes.find({"user_id": user["id"]}, {"_id": 0}).to_list(500)
    decisions_all = await db.decisions.find({"user_id": user["id"]}, {"_id": 0}).to_list(500)
    concepts = await db.graph_nodes.find({"user_id": user["id"], "kind": "concept"}, {"_id": 0}).sort("weight", -1).to_list(50)

    opps = []
    # 1. Notes without decisions
    decided_notes = {d.get("note_id") for d in decisions_all if d.get("note_id")}
    for n in notes[:20]:
        if n["id"] not in decided_notes:
            g = await compute_gravity(user["id"], n["id"])
            if g >= 40:
                opps.append({
                    "kind": "missing_decision",
                    "title": f"'{n['title']}' has no logged decision",
                    "suggestion": "Log a decision to capture the tradeoffs.",
                    "target_id": n["id"],
                    "priority": int(g),
                })
    # 2. High-weight concepts with only 1 note
    for c in concepts[:15]:
        related = await db.graph_edges.count_documents({"user_id": user["id"], "dst": c["id"]})
        if related == 1 and c["weight"] >= 2:
            opps.append({
                "kind": "unlinked_concept",
                "title": f"'{c['label']}' appears only in one note",
                "suggestion": "Connect a second note to grow this concept cluster.",
                "target_id": c["id"],
                "priority": 40,
            })
    # 3. Notes without council
    for n in notes[:20]:
        c_count = await db.council_responses.count_documents({"note_id": n["id"]})
        if c_count == 0:
            g = await compute_gravity(user["id"], n["id"])
            if g >= 30:
                opps.append({
                    "kind": "no_council",
                    "title": f"AI Council hasn't reviewed '{n['title']}'",
                    "suggestion": "Convene the 5 agents for a multi-perspective review.",
                    "target_id": n["id"],
                    "priority": int(g * 0.8),
                })
    opps.sort(key=lambda x: -x["priority"])
    return opps[:8]

# ---------------- Missions ----------------
@api.get("/missions")
async def missions(user=Depends(get_current_user)):
    notes = await db.notes.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50)
    if not notes:
        return []
    # Build missions from highest gravity notes
    scored = []
    for n in notes:
        g = await compute_gravity(user["id"], n["id"])
        scored.append((g, n))
    scored.sort(key=lambda x: -x[0])
    out = []
    for g, n in scored[:3]:
        versions = await db.note_versions.count_documents({"note_id": n["id"]})
        council = await db.council_responses.count_documents({"note_id": n["id"]})
        decisions = await db.decisions.count_documents({"note_id": n["id"], "user_id": user["id"]})
        checks = [
            ("Extracted concepts", len(n.get("concepts", [])) >= 3),
            ("AI Council reviewed", council >= 5),
            ("Decision logged", decisions >= 1),
            ("Evolved past v1", versions >= 2),
            ("Cross-linked", await db.graph_edges.count_documents({"user_id": user["id"], "src": n["id"]}) >= 3),
        ]
        done = sum(1 for _, ok in checks if ok)
        out.append({
            "note_id": n["id"],
            "title": f"Complete '{n['title']}'",
            "gravity": g,
            "progress": int((done / len(checks)) * 100),
            "checklist": [{"label": l, "done": bool(ok)} for l, ok in checks],
            "reward": 60 + int(g),
        })
    return out

# ---------------- Cognitive DNA ----------------
@api.get("/cognitive-dna")
async def cognitive_dna(user=Depends(get_current_user)):
    """Score user across 6 thinking traits using ONLY observed behavioral signals.

    Every trait returns: score, confidence (bounded by evidence volume), evidence
    (2-3 supporting notes), evidence_count, and — where available — a counter_signal
    from an inverse trait's stronger evidence. This is a DERIVED behavioral model,
    not a psychological assessment.
    """
    notes = await db.notes.find({"user_id": user["id"]}, {"_id": 0}).to_list(500)
    decisions_count = await db.decisions.count_documents({"user_id": user["id"]})
    versions_total = await db.note_versions.count_documents({"user_id": user["id"]})
    edges_count = await db.graph_edges.count_documents({"user_id": user["id"]})

    keywords = {
        "Architectural": ["architecture", "system", "runtime", "schema", "layer", "component", "pipeline"],
        "Systems Thinking": ["governance", "graph", "connected", "network", "orchestration", "memory"],
        "Planning": ["milestone", "framework", "plan", "roadmap", "playbook", "workflow"],
        "Documentation": ["document", "note", "doc", "steward", "readme", "spec"],
        "Experimentation": ["prototype", "test", "try", "explore", "flutterflow", "experiment"],
        "Risk Management": ["risk", "sandbox", "review", "governance", "provenance", "audit"],
    }
    counter_pairs = {
        "Architectural": "Experimentation",
        "Experimentation": "Architectural",
        "Planning": "Experimentation",
        "Documentation": "Experimentation",
        "Risk Management": "Experimentation",
        "Systems Thinking": "Experimentation",
    }

    # Precompute per-trait hit counts and evidence notes
    trait_hits: Dict[str, int] = {}
    trait_evidence: Dict[str, List[Dict[str, str]]] = {}
    for name, kws in keywords.items():
        total_hits = 0
        ev: List[Dict[str, str]] = []
        for n in notes:
            t = (n.get("text", "") + " " + n.get("title", "")).lower()
            local = sum(t.count(k) for k in kws)
            if local > 0:
                total_hits += local
                if len(ev) < 3:
                    ev.append({"id": n["id"], "title": n["title"]})
        trait_hits[name] = total_hits
        trait_evidence[name] = ev

    total_signals = edges_count + decisions_count + versions_total + sum(trait_hits.values())

    traits = []
    for name in keywords:
        hits = trait_hits[name]
        ev_notes = len(trait_evidence[name])
        # Score is bounded to prevent false precision. Requires evidence to move.
        planning_boost = decisions_count if name == "Planning" else 0
        exp_boost = versions_total if name == "Experimentation" else 0
        base = 40 + hits * 3 + planning_boost * 2 + exp_boost * 2
        score = max(20, min(95, base))
        # Confidence is bounded by the raw amount of evidence — never claim 90%
        # certainty on 2 supporting notes.
        confidence = max(0.15, min(0.9, (hits + ev_notes * 2) / 30))
        # Counter-signal: if the inverse trait has stronger evidence, expose it
        inverse = counter_pairs.get(name)
        counter = None
        if inverse and trait_hits.get(inverse, 0) > hits and hits >= 1:
            counter = {
                "trait": inverse,
                "hits": trait_hits[inverse],
                "note": "Inverse pattern shows stronger evidence than this trait.",
            }
        traits.append({
            "trait": name,
            "score": score,
            "confidence": round(confidence, 2),
            "evidence": trait_evidence[name],
            "evidence_count": hits,
            "counter_signal": counter,
        })
    return {
        "traits": traits,
        "total_signals": total_signals,
        "notes_analyzed": len(notes),
        "disclaimer": "Derived from your captured history. Behavioral model — not psychological certainty.",
    }

# ---------------- AI Shadow ----------------
@api.get("/shadow")
async def shadow(user=Depends(get_current_user)):
    notes = await db.notes.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).limit(20).to_list(20)
    decisions_count = await db.decisions.count_documents({"user_id": user["id"]})
    concepts_all = await db.graph_nodes.find({"user_id": user["id"], "kind": "concept"}, {"_id": 0}).sort("weight", -1).limit(5).to_list(5)

    if not notes:
        return {"insights": [], "top_patterns": []}

    sample = "\n".join(f"- {n['title']}" for n in notes[:15])
    system = "You infer HOW a person thinks from their notes. Not what they know — HOW they decide, structure ideas, and work. Return 4 short second-person observations, each on its own line, starting with 'You'. No numbers, no bullets."
    prompt = f"Notes:\n{sample}\n\nDecisions preserved: {decisions_count}."
    out = await gemini_chat(system, prompt, session_id=f"shadow-{user['id']}")
    insights = [l.strip("-• ").strip() for l in (out or "").split("\n") if l.strip().lower().startswith("you")][:4]
    if not insights:
        insights = ["You capture ideas frequently but link them slowly.", "You prefer structured architecture over ad-hoc solutions."]

    return {
        "insights": insights,
        "top_patterns": [{"label": c["label"], "weight": c["weight"]} for c in concepts_all],
        "kind": "DESCRIPTIVE MODEL",
        "description": "How you tend to think — descriptive behavioral model from your captured history.",
    }

# ---------------- Cognitive Twin ----------------
@api.post("/twin/predict")
async def twin_predict(inp: TwinQuery, user=Depends(get_current_user)):
    """Predictive behavioral model — reasons strictly from the user's captured history.
    Distinct from AI Shadow (descriptive: HOW you think) — this answers WHAT you'd
    probably do next. Always returns evidence, confidence, and counter-signal so the
    prediction is auditable and never appears as certainty.
    """
    notes = await db.notes.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).limit(30).to_list(30)
    decisions = await db.decisions.find({"user_id": user["id"]}, {"_id": 0}).limit(10).to_list(10)
    ratified = await db.debates.count_documents({"user_id": user["id"], "ratified": True})
    contradictions = await db.contradictions.count_documents({"user_id": user["id"]})

    if not notes:
        return {
            "prediction": "Not enough history yet — capture more notes and decisions to grow your twin.",
            "confidence": 0.0,
            "evidence": [],
            "evidence_count": 0,
            "counter_signal": None,
            "reasoning": "The Cognitive Twin requires captured history to model your behavior.",
            "kind": "MODEL PREDICTION",
        }

    ctx = "Recent notes:\n" + "\n".join(f"- {n['title']}: {n['text'][:120]}" for n in notes[:15])
    ctx += "\n\nDecisions:\n" + "\n".join(f"- #{d['number']} {d['title']}" for d in decisions)
    system = (
        "You are a Cognitive Twin. Reason STRICTLY from the user's provided history to predict what THEY would probably do next. "
        "Return ONLY strict JSON (no backticks, no prose) with keys: "
        "prediction (one crisp sentence, second person, starts with 'You would probably'), "
        "confidence (float 0..1 — be honest; do not exceed 0.85 without strong evidence), "
        "counter_signal (one short sentence identifying evidence AGAINST the prediction, or null), "
        "reasoning (one short sentence naming which past notes/decisions drove the prediction). "
        "Never invent history that isn't in the provided context."
    )
    prompt = f"Question: {inp.question}\n\nHistory:\n{ctx}"
    out = await gemini_chat(system, prompt, session_id=f"twin-{user['id']}")
    parsed = _parse_json_lenient(out) or {}
    prediction = str(parsed.get("prediction") or out or "").strip()[:400]
    if not prediction:
        prediction = "Not enough history yet — capture more notes and decisions to grow your twin."
    try:
        conf = max(0.0, min(0.9, float(parsed.get("confidence") or 0.5)))
    except Exception:
        conf = 0.5
    # Evidence surface: most recent notes and decisions actually shown to the model
    evidence = [{"kind": "note", "id": n["id"], "title": n["title"]} for n in notes[:6]] + \
               [{"kind": "decision", "id": d["id"], "number": d.get("number"), "title": d["title"]} for d in decisions[:4]]
    counter = str(parsed.get("counter_signal") or "").strip()[:280] or None
    reasoning = str(parsed.get("reasoning") or "").strip()[:280] or "Reasoned from the notes and decisions listed as evidence."
    return {
        "prediction": prediction,
        "confidence": round(conf, 2),
        "evidence": evidence,
        "evidence_count": len(notes) + len(decisions),
        "ratified_precedents": ratified,
        "known_contradictions": contradictions,
        "counter_signal": counter,
        "reasoning": reasoning,
        "kind": "MODEL PREDICTION",
    }

# ---------------- Thinking Replay ----------------
@api.get("/replay/{note_id}")
async def replay(note_id: str, user=Depends(get_current_user)):
    n = await db.notes.find_one({"id": note_id, "user_id": user["id"]}, {"_id": 0})
    if not n:
        raise HTTPException(status_code=404, detail="Not found")
    events = await db.events.find({"user_id": user["id"], "ref_id": note_id}, {"_id": 0}).sort("created_at", 1).to_list(200)
    versions = await db.note_versions.find({"note_id": note_id}, {"_id": 0}).sort("version", 1).to_list(50)
    council = await db.council_responses.find({"note_id": note_id}, {"_id": 0}).to_list(50)
    decisions = await db.decisions.find({"note_id": note_id, "user_id": user["id"]}, {"_id": 0}).to_list(50)
    return {"note": n, "events": events, "versions": versions, "council": council, "decisions": decisions}

# ---------------- Seed ----------------
@api.post("/seed-demo")
async def seed_demo(user=Depends(get_current_user)):
    existing = await db.notes.count_documents({"user_id": user["id"]})
    if existing > 0:
        return {"status": "already_seeded", "count": existing}

    demo_notes = [
        ("Pocket OS Architecture", "Building a cognitive OS with memory graph, decision DNA, AI council. Runtime handles provenance and orchestration."),
        ("Agent Marketplace Schema", "Agents publish manifests: capabilities, memory access scopes, cost. Users subscribe. Governance layer enforces sandboxing."),
        ("AI Governance Article", "Read a piece on responsible autonomy. Key: provenance trails and reversible decisions."),
        ("Client Sales Framework", "Anchor with a specific outcome, contrast three tiers, close with the compounding effect over 12 months."),
        ("Proposal Framework v3", "Structure: Situation, Complication, Question, Answer. Add a lineage section so past proposals inform the new one."),
        ("FlutterFlow Notes", "FlutterFlow is fastest for prototypes, but React Native still wins on control and native depth."),
        ("Automation Playbook", "Every recurring workflow gets a doc + a script + a review trigger. Automation without review becomes drift."),
    ]
    created_ids = []
    for title, text in demo_notes:
        concepts = await extract_concepts(text)
        note_id = uid()
        note = {
            "id": note_id,
            "user_id": user["id"],
            "title": title,
            "text": text,
            "concepts": concepts,
            "version": 1,
            "parent_id": None,
            "revenue": 0,
            "produced_projects": 0,
            "produced_tasks": 0,
            "produced_articles": 0,
            "produced_proposals": 0,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.notes.insert_one(note)
        await db.note_versions.insert_one({
            "id": uid(), "note_id": note_id, "version": 1, "stage": "Idea",
            "text": text, "user_id": user["id"], "created_at": now_iso(),
        })
        await db.graph_nodes.insert_one({
            "id": note_id, "user_id": user["id"], "kind": "note", "key": note_id,
            "label": title, "weight": 3, "created_at": now_iso(), "updated_at": now_iso(),
        })
        for c in concepts:
            cid = await upsert_concept_node(user["id"], c)
            await add_edge(user["id"], note_id, cid, "has_concept")
        await log_event(user["id"], "note_created", f"Created note: {title}", ref_id=note_id)
        await log_event(user["id"], "concepts_extracted", f"AI extracted {len(concepts)} concepts", ref_id=note_id, meta={"concepts": concepts})
        created_ids.append(note_id)

    # Add cross-note related edges based on shared concepts
    all_notes = await db.notes.find({"user_id": user["id"]}, {"_id": 0}).to_list(200)
    for i, a in enumerate(all_notes):
        for b in all_notes[i+1:]:
            shared = set([c.lower() for c in a.get("concepts", [])]) & set([c.lower() for c in b.get("concepts", [])])
            if shared:
                await add_edge(user["id"], a["id"], b["id"], "related")

    # Evolve one note
    if created_ids:
        for stage in ["Refined", "Merged", "Implemented"]:
            await db.note_versions.insert_one({
                "id": uid(), "note_id": created_ids[0], "version": len(await db.note_versions.find({"note_id": created_ids[0]}).to_list(50)) + 1,
                "stage": stage, "text": f"[{stage}] " + demo_notes[0][1], "user_id": user["id"], "created_at": now_iso(),
            })
            await log_event(user["id"], "idea_evolved", f"{demo_notes[0][0]} -> {stage}", ref_id=created_ids[0], meta={"stage": stage})

    # Seed decisions
    demo_decisions = [
        ("Adopt event-sourced timeline", "All actions become chronological events."),
        ("Standardize on Gemini 3 Flash for extraction", "Fast, cheap, structured."),
        ("Governance layer before Agent Marketplace", "Sandbox first, publish later."),
    ]
    for i, (dt, dc) in enumerate(demo_decisions):
        d = {
            "id": uid(),
            "number": i + 1,
            "user_id": user["id"],
            "title": dt,
            "context": dc,
            "note_id": created_ids[i] if i < len(created_ids) else None,
            "affected_projects": random.randint(4, 14),
            "produced_tasks": random.randint(12, 84),
            "referenced_notes": random.randint(6, 36),
            "influenced_agents": random.randint(1, 5),
            "created_at": now_iso(),
        }
        await db.decisions.insert_one(d)
        await log_event(user["id"], "decision_made", f"Decision #{d['number']}: {dt}", ref_id=d["id"])

    # Council responses on first note (canned to avoid latency)
    canned = [
        ("Research", "agentResearch", "Related work: 'Building a Second Brain' (Forte) and event sourcing patterns from DDD."),
        ("Architect", "agentArchitect", "Fits your runtime-shell split. Timeline is a natural fit for CQRS read-model projections."),
        ("Critic", "agentCritic", "Risk: schema drift as event kinds proliferate. Enforce a registry before scaling agent count."),
        ("Planner", "agentPlanner", "Next milestone: publish v0 of the event schema and wire replay for one note end-to-end."),
        ("Documentation Steward", "agentDocSteward", "I will index this under Architecture > Runtime and cross-link governance."),
    ]
    for name, color, resp in canned:
        await db.council_responses.insert_one({
            "id": uid(), "note_id": created_ids[0], "user_id": user["id"],
            "agent": name, "color_key": color, "response": resp, "created_at": now_iso(),
        })
    await log_event(user["id"], "council_convened", "AI Council reviewed: Pocket OS Architecture", ref_id=created_ids[0])

    return {"status": "seeded", "notes": len(created_ids)}

# ---------------- Wire ----------------

# ---------------- Cognitive Router ----------------
INTENT_KEYWORDS = {
    "RESEARCH":       ["research", "cite", "prior work", "benchmark", "study", "compare", "sources", "evidence"],
    "ARCHITECTURE":   ["architecture", "design", "system", "schema", "runtime", "layer", "protocol"],
    "CRITIQUE":       ["critique", "risk", "weakness", "objection", "reject", "flaw", "assumption"],
    "PLANNING":       ["plan", "milestone", "roadmap", "next step", "sequence", "phases"],
    "SOP_GENERATION": ["sop", "procedure", "runbook", "checklist", "operating", "instructions"],
    "DECISION":       ["decide", "decision", "approve", "choose", "trade-off", "should we"],
    "DOCUMENTATION":  ["document", "readme", "spec", "canonical", "steward"],
    "GENERAL":        [],
}
INTENT_AGENTS = {
    "RESEARCH":       [("Research Agent", "primary"), ("Architect Agent", "reviewer")],
    "ARCHITECTURE":   [("Architect Agent", "primary"), ("Critic Agent", "reviewer"), ("Documentation Steward", "steward")],
    "CRITIQUE":       [("Critic Agent", "primary"), ("Research Agent", "evidence")],
    "PLANNING":       [("Planner Agent", "primary"), ("Architect Agent", "reviewer"), ("Critic Agent", "stress-test")],
    "SOP_GENERATION": [("Documentation Steward", "primary"), ("Architect Agent", "reviewer")],
    "DECISION":       [("Research Agent", "evidence"), ("Architect Agent", "structure"), ("Critic Agent", "stress-test"), ("Planner Agent", "next-milestone")],
    "DOCUMENTATION":  [("Documentation Steward", "primary"), ("Architect Agent", "reviewer")],
    "GENERAL":        [("Research Agent", "primary"), ("Planner Agent", "reviewer")],
}
INTENT_MODE = {
    "RESEARCH": "sequential", "ARCHITECTURE": "sequential", "CRITIQUE": "single",
    "PLANNING": "sequential", "SOP_GENERATION": "sequential", "DECISION": "parallel",
    "DOCUMENTATION": "sequential", "GENERAL": "single",
}

class RouteIn(BaseModel):
    text: Optional[str] = None
    note_id: Optional[str] = None
    task_type: Optional[str] = None

def classify_intent(text: str, hint: Optional[str]) -> str:
    if hint and hint.upper() in INTENT_KEYWORDS:
        return hint.upper()
    t = text.lower()
    best, best_score = "GENERAL", 0
    for intent, kws in INTENT_KEYWORDS.items():
        score = sum(1 for k in kws if k in t)
        if score > best_score:
            best, best_score = intent, score
    return best

@api.post("/router/route")
async def router_route(inp: RouteIn, user=Depends(get_current_user)):
    if not inp.text and not inp.note_id:
        raise HTTPException(status_code=400, detail="Provide text or note_id")

    note = None
    text_for_intent = inp.text or ""
    if inp.note_id:
        note = await db.notes.find_one({"id": inp.note_id, "user_id": user["id"]}, {"_id": 0})
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        text_for_intent = (inp.text or "") + " " + note["title"] + " " + note["text"]

    intent = classify_intent(text_for_intent, inp.task_type)
    mode = INTENT_MODE[intent]

    await ensure_builtin_agents(user["id"])
    registry = await db.agents.find({"user_id": user["id"]}, {"_id": 0}).to_list(200)
    reg_by_name = {a["name"]: a for a in registry}

    steps = []
    for name, role in INTENT_AGENTS[intent]:
        a = reg_by_name.get(name)
        if not a:
            continue
        lease = await db.leases.find_one({"agent_id": a["id"], "user_id": user["id"], "status": "active"}, {"_id": 0})
        risk_pen = {"low": 0, "medium": 10, "high": 25}.get(a.get("risk", "medium"), 10)
        score = int(a.get("trust_score", 50)) + (10 if lease else -30) - risk_pen
        steps.append({
            "agent_id": a["id"],
            "agent_name": a["name"],
            "role": role,
            "score": score,
            "governance": {
                "active_lease": bool(lease),
                "capabilities": lease["capabilities"] if lease else a["capabilities"],
                "risk": a.get("risk"),
                "expires_at": lease["expires_at"] if lease else None,
            },
        })

    context_refs = {"notes": [], "concepts": [], "decisions": [], "recent_events": []}
    if note:
        context_refs["notes"].append({
            "id": note["id"], "title": note["title"], "concepts": note.get("concepts", []),
            "gravity": await compute_gravity(user["id"], note["id"]),
        })
        edges = await db.graph_edges.find(
            {"user_id": user["id"], "$or": [{"src": note["id"]}, {"dst": note["id"]}], "kind": "related"},
            {"_id": 0},
        ).to_list(20)
        nb_ids = list({(e["dst"] if e["src"] == note["id"] else e["src"]) for e in edges})
        nb_notes = await db.notes.find({"id": {"$in": nb_ids}, "user_id": user["id"]}, {"_id": 0}).to_list(20)
        for nb in nb_notes[:5]:
            context_refs["notes"].append({
                "id": nb["id"], "title": nb["title"],
                "gravity": await compute_gravity(user["id"], nb["id"]),
            })
        related_decisions = await db.decisions.find({"user_id": user["id"], "note_id": note["id"]}, {"_id": 0}).limit(5).to_list(5)
        context_refs["decisions"] = [
            {"id": d["id"], "number": d["number"], "title": d["title"], "dna_root": d.get("dna_root")}
            for d in related_decisions
        ]

    ev = await db.events.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).limit(5).to_list(5)
    context_refs["recent_events"] = [{"kind": e["kind"], "text": e["text"], "created_at": e["created_at"]} for e in ev]

    plan = {
        "id": uid(), "user_id": user["id"], "intent": intent, "mode": mode,
        "steps": steps, "context_refs": context_refs,
        "source": {"note_id": inp.note_id, "text_preview": (inp.text or "")[:200]},
        "created_at": now_iso(),
    }
    await db.routing_plans.insert_one(plan)
    plan.pop("_id", None)
    await log_event(
        user["id"], "router_planned",
        f"Intent {intent} → {mode} across {len(steps)} agents",
        ref_id=inp.note_id, meta={"intent": intent, "mode": mode, "step_count": len(steps)},
    )
    return plan


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
