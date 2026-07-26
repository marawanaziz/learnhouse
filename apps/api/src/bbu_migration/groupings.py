"""Anna's class groupings — audience segmentation, Bold copies, Spanish communities.

From her 26 Jul brief: professionals should see professional and doula trainings,
families should see family classes, Project Bold cohorts should see only their own
labelled versions, and the Spanish classes should live in their own community
rather than clutter the main catalogue.

Three provisioning steps, each idempotent and each with a dry run, because they
mutate the live catalogue:

  POST /groupings/audiences   create the audiences + their usergroups, tag products
  POST /groupings/clone-bold  duplicate the named courses into Project Bold versions
  POST /groupings/communities create the Spanish communities and attach courses
  GET  /groupings/plan        what the tagging pass *would* do, changing nothing

Tagging is by name rule with an explicit override map. Names change, so `plan`
exists to be read by a human before anything is written — a misfiled product
disappears from a storefront, which is exactly the kind of silent breakage that
is hard to notice and easy to avoid.
"""
import os
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.courses.courses import Course
from src.db.usergroups import UserGroup
from src.db.communities.communities import Community
from src.bbu_payments.models import BBUProduct, BBUAudience

router = APIRouter()
ORG = 1
ADMIN_KEY = os.environ.get("BBU_MIGRATION_KEY") or os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")

# slug, display name, is_public_default, cross_sell, order
AUDIENCES = [
    ("family", "Expecting Families", True, False, 10),
    ("professional", "Perinatal Professionals", False, True, 20),
    ("bold_professional", "Project Bold — Professionals", False, False, 30),
    ("bold_family", "Project Bold — Families", False, False, 40),
    ("spanish_family", "Spanish-Speaking Families", False, False, 50),
    ("bold_spanish_family", "Project Bold — Spanish-Speaking Families", False, False, 60),
]

# A product is professional if its name matches any of these.
PRO_MARKERS = ("doula training", "perinatal professional", "mentorship",
               "agency owner", "cross certification")
# Spanish catalogue (names are Spanish, so match on the actual titles).
ES_MARKERS = ("atención", "atencion", "introducción", "introduccion",
              "lactancia", "preparándose", "preparandose", "pase virtual")
# Explicit wins over the rules — for anything the markers get wrong.
OVERRIDES: dict = {
    "all access class pass": "family",
    "birth prep ebook & guide": "family",
    "newborn care basics ebook & guide": "family",
    "one-on-one consultation": "family,professional",
    "bbu test guide (qa)": "",          # internal QA item, leave untagged
}

# Courses Anna asked to duplicate for Project Bold.
BOLD_SOURCES = [
    "Breastfeeding for Perinatal Professionals",
    "Comfort Measures for Perinatal Professionals",
    "Newborn Care for Perinatal Professionals",
]
BOLD_PREFIX = "Project Bold — "


def _check(request: Request, body: dict | None = None):
    if not ADMIN_KEY:
        raise HTTPException(503, "Migration key not configured")
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key") \
        or (body or {}).get("key") or ""
    if key != ADMIN_KEY:
        raise HTTPException(403, "Forbidden")


def _now() -> str:
    return str(datetime.now())


def classify(name: str) -> str:
    """Product name -> comma-separated audience slugs."""
    n = (name or "").strip().lower()
    if n in OVERRIDES:
        return OVERRIDES[n]
    if n.startswith(BOLD_PREFIX.strip().lower()) or "project bold" in n:
        return "bold_professional" if any(m in n for m in PRO_MARKERS) else "bold_family"
    if any(m in n for m in ES_MARKERS):
        return "spanish_family"
    if any(m in n for m in PRO_MARKERS):
        return "professional"
    return "family"


async def _ensure_usergroup(db: AsyncSession, name: str, description: str) -> UserGroup:
    grp = (await db.execute(select(UserGroup).where(
        UserGroup.org_id == ORG, UserGroup.name == name))).scalars().first()
    if grp:
        return grp
    grp = UserGroup(org_id=ORG, name=name, description=description,
                    usergroup_uuid=f"usergroup_{uuid4()}",
                    creation_date=_now(), update_date=_now())
    db.add(grp)
    await db.commit()
    await db.refresh(grp)
    return grp


@router.get("/groupings/plan")
async def plan(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """What the tagging pass would do. Read this before applying."""
    _check(request)
    rows = (await db_session.execute(select(BBUProduct).where(
        BBUProduct.org_id == ORG).order_by(BBUProduct.name))).scalars().all()
    out, buckets = [], {}
    for p in rows:
        tags = classify(p.name)
        out.append({"id": p.id, "name": p.name, "current": p.audiences or "(none)",
                    "proposed": tags or "(none — visible to all)"})
        buckets[tags or "(none)"] = buckets.get(tags or "(none)", 0) + 1
    return {"products": len(rows), "by_audience": buckets, "plan": out}


@router.post("/groupings/audiences")
async def provision_audiences(request: Request,
                              db_session: AsyncSession = Depends(get_db_session)):
    """Create the audiences (+ a usergroup each) and tag every product."""
    body = await request.json() if await request.body() else {}
    _check(request, body)
    dry = bool(body.get("dry_run"))

    made, linked = [], []
    for slug, name, is_default, cross, order in AUDIENCES:
        a = (await db_session.execute(select(BBUAudience).where(
            BBUAudience.org_id == ORG, BBUAudience.slug == slug))).scalars().first()
        if a is None:
            a = BBUAudience(org_id=ORG, slug=slug)
            made.append(slug)
        a.name, a.is_public_default, a.cross_sell, a.sort_order = name, is_default, cross, order
        a.active = True
        if not dry:
            if not a.usergroup_id:
                grp = await _ensure_usergroup(
                    db_session, f"Audience — {name}",
                    f"Audience segment '{slug}': controls which catalogue these "
                    f"members see. Managed from Members.")
                a.usergroup_id = grp.id or 0
                linked.append({"audience": slug, "usergroup_id": a.usergroup_id})
            db_session.add(a)

    tagged = []
    rows = (await db_session.execute(select(BBUProduct).where(
        BBUProduct.org_id == ORG))).scalars().all()
    for p in rows:
        want = classify(p.name)
        if (p.audiences or "") != want:
            tagged.append({"product": p.name, "from": p.audiences or "(none)",
                           "to": want or "(none)"})
            if not dry:
                p.audiences = want
                db_session.add(p)
    if not dry:
        await db_session.commit()
    return {"dry_run": dry, "audiences_created": made, "usergroups_linked": linked,
            "products_retagged": len(tagged), "changes": tagged}


@router.post("/groupings/clone-bold")
async def clone_bold(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Duplicate the professional courses Anna named into Project Bold versions.

    Uses the platform's own course clone (chapters, activities, blocks, files) and
    then renames — the built-in clone appends "(Copy)", which is not a name to put
    in front of a cohort. Clones land unpublished so nothing goes live half-named.
    """
    body = await request.json() if await request.body() else {}
    _check(request, body)
    dry = bool(body.get("dry_run"))
    names = body.get("courses") or BOLD_SOURCES

    from src.services.courses.courses import clone_course
    from src.db.users import User, PublicUser
    from src.db.user_organizations import UserOrganization
    from src.security.org_auth import ADMIN_OR_MAINTAINER_ROLE_IDS

    # clone_course is RBAC-gated on a real session user, and this endpoint
    # authenticates with the admin key instead. Act as an actual org admin
    # rather than weakening the check — an anonymous caller is correctly
    # refused ("Resource is not public or not published") because the courses
    # being copied are access-gated.
    admin_row = None
    memberships = (await db_session.execute(select(UserOrganization).where(
        UserOrganization.org_id == ORG,
        UserOrganization.role_id.in_(list(ADMIN_OR_MAINTAINER_ROLE_IDS))
    ))).scalars().all()
    if memberships:
        admin_row = (await db_session.execute(select(User).where(
            User.id == memberships[0].user_id))).scalars().first()
    if not admin_row:
        raise HTTPException(500, "No org admin found to perform the clone")
    acting = PublicUser.model_validate(admin_row.model_dump())

    results = []
    for src_name in names:
        course = (await db_session.execute(select(Course).where(
            Course.org_id == ORG, Course.name == src_name))).scalars().first()
        if not course:
            results.append({"source": src_name, "status": "source not found"})
            continue
        target = f"{BOLD_PREFIX}{src_name}"
        if (await db_session.execute(select(Course).where(
                Course.org_id == ORG, Course.name == target))).scalars().first():
            results.append({"source": src_name, "status": "already exists", "name": target})
            continue
        if dry:
            results.append({"source": src_name, "status": "would clone", "name": target})
            continue
        try:
            cloned = await clone_course(request, course.course_uuid, acting, db_session)
            row = (await db_session.execute(select(Course).where(
                Course.course_uuid == cloned.course_uuid))).scalars().first()
            if row:
                row.name = target
                row.public = False
                row.update_date = _now()
                db_session.add(row)
                await db_session.commit()
            results.append({"source": src_name, "status": "cloned", "name": target,
                            "course_uuid": cloned.course_uuid})
        except Exception as e:
            results.append({"source": src_name, "status": f"error: {str(e)[:160]}"})
    return {"dry_run": dry, "results": results}


@router.post("/groupings/communities")
async def provision_communities(request: Request,
                                db_session: AsyncSession = Depends(get_db_session)):
    """Create the Spanish-speaking communities and attach the Spanish courses.

    Anna's reasoning: demand is low enough that a dedicated community is a
    tidier home for these than another row in everyone's catalogue.
    """
    body = await request.json() if await request.body() else {}
    _check(request, body)
    dry = bool(body.get("dry_run"))

    from src.db.communities.community_courses import CommunityCourse

    wanted = body.get("communities") or [
        {"name": "Spanish-Speaking Families",
         "description": "Clases en español para familias que esperan un bebé.",
         "match": ES_MARKERS, "bold": False},
        {"name": "Project Bold — Spanish-Speaking Families",
         "description": "Clases en español para las familias de Project Bold.",
         "match": ES_MARKERS, "bold": True},
    ]

    courses = (await db_session.execute(select(Course).where(
        Course.org_id == ORG))).scalars().all()

    out = []
    for spec in wanted:
        existing = (await db_session.execute(select(Community).where(
            Community.org_id == ORG, Community.name == spec["name"]))).scalars().first()
        targets = [c for c in courses
                   if any(m in (c.name or "").lower() for m in spec["match"])
                   and (("project bold" in (c.name or "").lower()) == bool(spec["bold"]))]
        entry = {"community": spec["name"],
                 "status": "exists" if existing else "would create",
                 "courses_matched": [c.name for c in targets]}
        if not dry:
            if not existing:
                existing = Community(
                    org_id=ORG, name=spec["name"], description=spec["description"],
                    public=False, community_uuid=f"community_{uuid4()}",
                    creation_date=_now(), update_date=_now())
                db_session.add(existing)
                await db_session.commit()
                await db_session.refresh(existing)
                entry["status"] = "created"
            # write the join rows directly: the service call is RBAC-gated on a
            # session user, and this endpoint authenticates with the admin key
            linked = 0
            for c in targets:
                dupe = (await db_session.execute(select(CommunityCourse).where(
                    CommunityCourse.community_id == existing.id,
                    CommunityCourse.course_id == c.id))).scalars().first()
                if dupe:
                    continue
                db_session.add(CommunityCourse(
                    org_id=ORG, community_id=existing.id or 0,
                    course_id=c.id or 0, creation_date=_now()))
                linked += 1
            if not existing.course_id and targets:
                existing.course_id = targets[0].id
                db_session.add(existing)
            await db_session.commit()
            entry["courses_linked"] = linked
        out.append(entry)
    return {"dry_run": dry, "communities": out}
