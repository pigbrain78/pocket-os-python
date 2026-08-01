from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import random
import math
import uuid
import jwt
import bcrypt
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta

from emergentintegrations.llm.chat import LlmChat, UserMessage

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']
EMERGENT_LLM_KEY = os.environ['EMERGENT_LLM_KEY']
JWT_SECRET = os.environ['JWT_SECRET']
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

async def run_council(note_text: str) -> List[Dict[str, str]]:
    results = []
    for name, color, sys in AGENTS:
        msg = await gemini_chat(sys, note_text[:1500], session_id=f"council-{name}")
        results.append({"agent": name, "color_key": color, "response": msg or f"{name} could not respond right now."})
    return results

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
    ev = {
        "id": uid(),
        "user_id": user_id,
        "kind": kind,
        "text": text,
        "ref_id": ref_id,
        "meta": meta or {},
        "created_at": now_iso(),
    }
    await db.events.insert_one(ev)
    return ev

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

@api.get("/auth/me")
async def me(user=Depends(get_current_user)):
    return user

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

# ---------------- Decisions ----------------
@api.post("/decisions")
async def create_decision(inp: DecisionIn, user=Depends(get_current_user)):
    count = await db.decisions.count_documents({"user_id": user["id"]})
    d = {
        "id": uid(),
        "number": count + 1,
        "user_id": user["id"],
        "title": inp.title,
        "context": inp.context or "",
        "note_id": inp.note_id,
        "affected_projects": random.randint(3, 14),
        "produced_tasks": random.randint(8, 60),
        "referenced_notes": random.randint(4, 40),
        "influenced_agents": random.randint(1, 5),
        "created_at": now_iso(),
    }
    await db.decisions.insert_one(d)
    await log_event(user["id"], "decision_made", f"Decision #{d['number']}: {inp.title}", ref_id=d["id"])
    d.pop("_id", None)
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
    """Score user across 6 thinking traits with evidence."""
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
    text_blob = " ".join((n.get("text", "") + " " + n.get("title", "")).lower() for n in notes)
    traits = []
    for name, kws in keywords.items():
        hits = sum(text_blob.count(k) for k in kws)
        score = min(99, 55 + hits * 4 + (decisions_count if name == "Planning" else 0) * 2 + (versions_total if name == "Experimentation" else 0) * 2)
        # gather 2 evidence notes with any hit
        evidence = []
        for n in notes:
            t = (n.get("text", "") + " " + n.get("title", "")).lower()
            if any(k in t for k in kws):
                evidence.append({"id": n["id"], "title": n["title"]})
                if len(evidence) >= 2:
                    break
        traits.append({"trait": name, "score": score, "evidence": evidence})
    return {"traits": traits, "total_signals": edges_count + decisions_count + versions_total}

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
    }

# ---------------- Cognitive Twin ----------------
@api.post("/twin/predict")
async def twin_predict(inp: TwinQuery, user=Depends(get_current_user)):
    notes = await db.notes.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).limit(30).to_list(30)
    decisions = await db.decisions.find({"user_id": user["id"]}, {"_id": 0}).limit(10).to_list(10)
    ctx = "Recent notes:\n" + "\n".join(f"- {n['title']}: {n['text'][:120]}" for n in notes[:15])
    ctx += "\n\nDecisions:\n" + "\n".join(f"- #{d['number']} {d['title']}" for d in decisions)
    system = (
        "You are a Cognitive Twin. Reason strictly from the user's provided history to answer what THEY would probably do next. "
        "Be concise (3-5 sentences). Speak in second person. Reference specific past notes or decisions when relevant."
    )
    prompt = f"Question: {inp.question}\n\nHistory:\n{ctx}"
    out = await gemini_chat(system, prompt, session_id=f"twin-{user['id']}")
    return {"answer": out or "Not enough history yet — capture more notes and decisions to grow your twin."}

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
            "revenue": random.choice([0, 0, 4500, 18000]),
            "produced_projects": random.randint(0, 4),
            "produced_tasks": random.randint(0, 14),
            "produced_articles": random.randint(0, 2),
            "produced_proposals": random.randint(0, 3),
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
