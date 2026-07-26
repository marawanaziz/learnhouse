"""BBU community AI personas — the daily "drip" that keeps communities lively.

Native port of the Gaux personas engine (which posts into LearnHouse over HTTP);
because BBU *is* LearnHouse we post in-process. 27 clearly-labelled AI expert
personas (educators, not advisors; AI-disclosed; crisis-line routing) each with a
paste-ready system prompt (personas.json, from the Gaux Communities package).

Content is generated with OpenRouter (google/gemini-2.5-flash-lite), same as
Gaux. SAFE BY DEFAULT: dry-run unless `?live=1` / PERSONAS_LIVE=true. One post
per run (configurable), one persona per day (rotates), AI-disclosed author name.

Mounted at /api/v1/bbu/personas.
  GET  /run?live=1   cron — generate (+ optionally post) one persona post. Bearer CRON_SECRET or admin key.
  GET  /preview      admin — dry-run a sample post from today's persona (no write).
"""
import os
import json
import hashlib
from datetime import datetime, timezone, date
from uuid import uuid4

import httpx
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.security.security import security_hash_password
from src.db.users import User
from src.db.user_organizations import UserOrganization
from src.db.communities.communities import Community
from src.db.communities.discussions import Discussion

router = APIRouter()
ORG = 1
ADMIN_KEY = os.environ.get("BBU_MIGRATION_KEY") or os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")
CRON_SECRET = os.environ.get("CRON_SECRET", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.environ.get("PERSONAS_LLM_MODEL", "google/gemini-2.5-flash-lite")
TARGET_COMMUNITY = os.environ.get("BBU_PERSONA_COMMUNITY", "")  # name match; blank = first community
LEARNER_ROLE_ID = 4

_PERSONAS = None

# Appended to every persona system prompt (shared house rules + emergency reflexes).
SHARED_RULES = (
    "\n\nHouse rules (always): You are a clearly-labelled AI persona — never claim to be a real "
    "licensed human or to have a relationship with the member. Educate generally; never diagnose, "
    "interpret an individual's symptoms, or tell a specific person what to do — route personal "
    "decisions to their own provider. On any clinical question add a brief 'general information, not "
    "medical advice' note. Voice: warm, direct, plain-spoken, treats the reader as intelligent; no "
    "'mama', no baby-talk, no cheerleading, no emoji crutches, no manufactured urgency. Be generous, "
    "not salesy; no external links or selling. Emergency reflexes: self-harm/suicidal thoughts or "
    "thoughts of harming the baby -> Postpartum Support International 1-833-TLC-MAMA and 988; infant "
    "under 3 months with 100.4F/38C+, trouble breathing, dehydration, or a non-blanching rash -> "
    "'call your pediatrician or go in'; heavy bleeding, severe pain, or fainting in pregnancy/"
    "postpartum -> urgent care now."
)


def _personas():
    global _PERSONAS
    if _PERSONAS is None:
        path = os.path.join(os.path.dirname(__file__), "personas.json")
        with open(path) as f:
            _PERSONAS = json.load(f)
    return _PERSONAS


def _now():
    return datetime.now(timezone.utc).isoformat()


def _persona_of_the_day(personas):
    """Deterministic daily rotation — same persona all day, moves to the next tomorrow."""
    idx = date.today().toordinal() % len(personas)
    return personas[idx]


def _guard(request: Request):
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key", "")
    auth = request.headers.get("authorization", "")
    if CRON_SECRET and auth == f"Bearer {CRON_SECRET}":
        return
    if ADMIN_KEY and key == ADMIN_KEY:
        return
    raise HTTPException(401, "Unauthorized")


async def _generate(persona: dict) -> dict:
    """Ask OpenRouter for one short community post in this persona's voice."""
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "OPENROUTER_API_KEY not set")
    system = persona["system_prompt"] + SHARED_RULES
    user = (
        f"Write ONE short, genuinely useful standalone community post for Birth & Baby University's "
        f"member community, in your voice, on a helpful everyday topic in your lane"
        + (f" ({persona.get('covers')})" if persona.get("covers") else "")
        + ". Like a sharp friend sharing something worth knowing — a normalising 'here's how this "
        "generally works' post, not an ad. 90-160 words. Start with a short punchy first line that "
        "works as a title. Do not address a specific person's situation. Plain text only."
    )
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(OPENROUTER_URL, headers={
            "content-type": "application/json", "authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://birthandbabyuniversity.com", "X-Title": "BBU community personas",
        }, json={
            "model": MODEL, "max_tokens": 400, "temperature": 0.9,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        })
    if r.status_code != 200:
        raise HTTPException(502, f"OpenRouter {r.status_code}: {r.text[:200]}")
    data = r.json()
    if data.get("error"):
        raise HTTPException(502, f"openrouter_error: {str(data['error'])[:200]}")
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
    if not text:
        raise HTTPException(502, "empty_generation")
    # first line -> title, rest -> body
    lines = [l for l in text.splitlines() if l.strip()]
    title = lines[0].strip().strip('"').strip("*").strip()[:120] if lines else persona["role"]
    body = "\n\n".join(lines[1:]).strip() if len(lines) > 1 else text
    return {"title": title, "body": body}


async def _ensure_persona_user(db: AsyncSession, persona: dict) -> User:
    """Create/find the AI-labelled LearnHouse user that authors this persona's posts."""
    email = f"persona{persona['n']:02d}@ai.birthandbabyuniversity.com"
    u = (await db.execute(select(User).where(User.email == email))).scalars().first()
    if u:
        return u
    display = f"{persona['name']} · AI persona"
    parts = persona["name"].replace("Dr. ", "").split(" ", 1)
    u = User(
        username=f"bbu_ai_persona_{persona['n']:02d}",
        email=email, first_name=(persona["name"])[:100], last_name="· AI persona",
        password=security_hash_password(str(uuid4())),
        user_uuid=f"user_{uuid4()}", email_verified=True,
        bio=f"AI community guide — {persona['role']}. Clearly-labelled AI persona; general education, not medical advice.",
        signup_method="bbu_ai_persona", creation_date=_now(), update_date=_now(),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    db.add(UserOrganization(user_id=u.id or 0, org_id=ORG, role_id=LEARNER_ROLE_ID,
                            creation_date=_now(), update_date=_now()))
    await db.commit()
    return u


async def _all_communities(db: AsyncSession, match: str = "") -> list:
    """Communities the personas post into. Default: every community in the org
    (Anna asked for personas in all the different groups). `match` narrows by
    name substring."""
    comms = (await db.execute(select(Community).where(Community.org_id == ORG))).scalars().all()
    if match:
        comms = [c for c in comms if match.lower() in (c.name or "").lower()]
    if not comms:
        raise HTTPException(404, "No community to post into")
    return comms


async def _target_community(db: AsyncSession) -> Community:
    comms = await _all_communities(db, TARGET_COMMUNITY)
    return comms[0]


@router.get("/preview")
async def preview(request: Request, n: int = 0, db_session: AsyncSession = Depends(get_db_session)):
    """Dry-run: generate (not post) a sample post from a persona (default: today's)."""
    _guard(request)
    personas = _personas()
    persona = next((p for p in personas if p["n"] == n), None) if n else _persona_of_the_day(personas)
    post = await _generate(persona)
    return {"persona": f"{persona['name']} — {persona['role']}", "title": post["title"], "body": post["body"]}


@router.get("/run")
async def run(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Daily cron. Generates one persona post; posts it ONLY when live (?live=1 or
    PERSONAS_LIVE=true), otherwise returns it for review (dry-run)."""
    _guard(request)
    live = request.query_params.get("live") in ("1", "true") or os.environ.get("PERSONAS_LIVE") == "true"
    match = request.query_params.get("community", "") or TARGET_COMMUNITY
    # weekly=1 posts only on the configured weekday (Anna: 1 post/week for the
    # mentorship group), so the same daily cron can drive both cadences.
    weekly = request.query_params.get("weekly") in ("1", "true")
    weekday = int(request.query_params.get("weekday", "1"))  # Mon=0
    if weekly and date.today().weekday() != weekday:
        return {"skipped": "not the weekly post day", "weekday": weekday}

    personas = _personas()
    communities = await _all_communities(db_session, match)
    results = []
    for i, community in enumerate(communities):
        # rotate a different persona per community so they don't all sound alike
        persona = personas[(date.today().toordinal() + i) % len(personas)]
        try:
            post = await _generate(persona)
        except HTTPException as e:
            results.append({"community": community.name, "error": str(e.detail)[:120]})
            continue
        row = {"community": community.name,
               "persona": f"{persona['name']} — {persona['role']}",
               "title": post["title"], "body": post["body"]}
        if live:
            author = await _ensure_persona_user(db_session, persona)
            disc = Discussion(
                community_id=community.id, org_id=ORG, author_id=author.id or 0,
                title=post["title"][:200], content=post["body"], label="general",
                discussion_uuid=f"discussion_{uuid4()}", upvote_count=0, edit_count=0,
                creation_date=str(datetime.now()), update_date=str(datetime.now()),
            )
            db_session.add(disc)
            await db_session.commit()
            await db_session.refresh(disc)
            row["discussion_uuid"] = disc.discussion_uuid
        results.append(row)
    return {"dry_run": not live, "communities": len(communities), "posts": results}
