"""BBU migration endpoints (admin-key gated) — bulk import Circle students,
enrollments, and per-lesson progress into LearnHouse's native trail tables.

Clean-room (no ee imports). Reuses the existing User / UserOrganization /
Trail / TrailRun / TrailStep models, so no schema changes are needed. The
public trail endpoints are current-user scoped; this writes trail records for
arbitrary migrated users, which is why it lives in its own admin-gated module.

Mounted at /api/v1/bbu/migrate.
  POST /students   batch: create/find users, enroll, mark completed lessons
"""
import os
import secrets
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.security.security import security_hash_password
from src.db.users import User
from src.db.user_organizations import UserOrganization
from src.db.organizations import Organization
from src.db.roles import Role
from src.db.courses.courses import Course
from src.db.courses.activities import Activity
from src.db.trails import Trail
from src.db.trail_runs import TrailRun
from src.db.trail_steps import TrailStep
from src.db.communities.communities import Community
from src.db.communities.discussions import Discussion
from src.db.communities.discussion_comments import DiscussionComment

router = APIRouter()

ADMIN_KEY = os.environ.get("BBU_MIGRATION_KEY") or os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")
LEARNER_ROLE_UUID = "role_global_user"  # "User / Read-Only Learner", seeded id=4
LEARNER_ROLE_ID_FALLBACK = 4


def _check(request: Request, body: dict | None = None):
    if not ADMIN_KEY:
        raise HTTPException(503, "Migration key not configured")
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key") \
        or (body or {}).get("key") or ""
    if key != ADMIN_KEY:
        raise HTTPException(403, "Forbidden")


def _now():
    return str(datetime.now())


async def _learner_role_id(db: AsyncSession) -> int:
    role = (await db.execute(
        select(Role).where(Role.role_uuid == LEARNER_ROLE_UUID)
    )).scalars().first()
    return role.id if role and role.id else LEARNER_ROLE_ID_FALLBACK


async def _unique_username(db: AsyncSession, email: str) -> str:
    base = "".join(c for c in email.split("@")[0] if c.isalnum()).lower()[:24] or "user"
    for _ in range(6):
        cand = f"{base}{secrets.token_hex(2)}"
        exists = (await db.execute(select(User).where(User.username == cand))).scalars().first()
        if not exists:
            return cand
    return f"{base}{secrets.token_hex(4)}"


async def _get_or_create_user(db: AsyncSession, org_id: int, role_id: int,
                              email: str, name: str) -> User:
    email = email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalars().first()
    if user:
        return user
    username = await _unique_username(db, email)
    parts = (name or "").strip().split(" ", 1)
    first_name = (parts[0] if parts and parts[0] else "Member")[:100]
    last_name = (parts[1] if len(parts) > 1 else "")[:100]
    user = User(
        username=username, email=email, first_name=first_name, last_name=last_name,
        password=security_hash_password(secrets.token_urlsafe(24)),
        user_uuid=f"user_{uuid4()}", email_verified=False,
        signup_method="circle_migration",
        creation_date=_now(), update_date=_now(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    db.add(UserOrganization(
        user_id=user.id or 0, org_id=org_id, role_id=role_id,
        creation_date=_now(), update_date=_now(),
    ))
    await db.commit()
    return user


async def _ensure_trail(db: AsyncSession, org_id: int, user_id: int) -> Trail:
    trail = (await db.execute(
        select(Trail).where(Trail.org_id == org_id, Trail.user_id == user_id)
    )).scalars().first()
    if trail:
        return trail
    trail = Trail(org_id=org_id, user_id=user_id, trail_uuid=f"trail_{uuid4()}",
                  creation_date=_now(), update_date=_now())
    db.add(trail)
    await db.commit()
    await db.refresh(trail)
    return trail


async def _ensure_run(db: AsyncSession, trail: Trail, course: Course, user_id: int) -> TrailRun:
    run = (await db.execute(select(TrailRun).where(
        TrailRun.trail_id == trail.id, TrailRun.course_id == course.id,
        TrailRun.user_id == user_id,
    ))).scalars().first()
    if run:
        return run
    run = TrailRun(trail_id=trail.id or 0, course_id=course.id or 0, org_id=course.org_id,
                   user_id=user_id, creation_date=_now(), update_date=_now())
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def _ensure_community(db: AsyncSession, org_id: int, name: str, desc: str) -> Community:
    c = (await db.execute(
        select(Community).where(Community.org_id == org_id, Community.name == name)
    )).scalars().first()
    if c:
        return c
    c = Community(org_id=org_id, name=name[:200], description=desc or "", public=True,
                  community_uuid=f"community_{uuid4()}", creation_date=_now(), update_date=_now())
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


@router.post("/communities")
async def migrate_communities(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Bulk-import Circle community/event spaces -> LearnHouse Communities, their
    posts -> Discussions, and comments -> DiscussionComments. Authors mapped by
    email (created if missing); timestamps preserved. Idempotent by (community,
    title) for discussions."""
    body = await request.json()
    _check(request, body)
    org = (await db_session.execute(select(Organization).where(Organization.slug == body.get("org_slug", "bbu")))).scalars().first()
    if not org:
        raise HTTPException(404, "org not found")
    org_id = org.id
    role_id = await _learner_role_id(db_session)
    admin_email = (os.environ.get("LEARNHOUSE_INITIAL_ADMIN_EMAIL") or "m@sixtysixten.com").lower()

    # Optional clean slate: wipe this org's migrated discussions + comments so a
    # re-run produces an exact, non-duplicated result.
    if body.get("reset"):
        from sqlalchemy import delete
        comm_ids = [r for (r,) in (await db_session.execute(
            select(Community.id).where(Community.org_id == org_id))).all()]
        disc_ids = [r for (r,) in (await db_session.execute(
            select(Discussion.id).where(Discussion.community_id.in_(comm_ids)))).all()] if comm_ids else []
        if disc_ids:
            await db_session.execute(delete(DiscussionComment).where(DiscussionComment.discussion_id.in_(disc_ids)))
            await db_session.execute(delete(Discussion).where(Discussion.id.in_(disc_ids)))
            await db_session.commit()

    async def author_id(email, name):
        email = (email or "").strip().lower()
        if not email:
            email = admin_email
        try:
            u = await _get_or_create_user(db_session, org_id, role_id, email, name or "Member")
            return u.id
        except Exception:
            u = (await db_session.execute(select(User).where(User.email == admin_email))).scalars().first()
            return u.id if u else None

    made = {"communities": 0, "discussions": 0, "comments": 0, "skipped": 0}
    errors = []
    for comm in body.get("communities", []):
        c = await _ensure_community(db_session, org_id, comm["name"], comm.get("description", ""))
        made["communities"] += 1
        for post in comm.get("discussions", []):
            title = (post.get("title") or "Untitled")[:300]
            # Dedup on (community, title, created_at): distinct posts that share a
            # title (e.g. two "Introduction" posts) are kept; true re-runs no-op.
            _created = post.get("created_at") or ""
            existing = (await db_session.execute(select(Discussion).where(
                Discussion.community_id == c.id, Discussion.title == title,
                Discussion.creation_date == _created))).scalars().first()
            if existing:
                made["skipped"] += 1
                disc = existing
            else:
                aid = await author_id(post.get("author_email"), post.get("author_name"))
                if not aid:
                    errors.append(f"no author for post '{title[:40]}'")
                    continue
                disc = Discussion(
                    title=title, content=post.get("content") or "", label="general",
                    community_id=c.id, org_id=org_id, author_id=aid,
                    discussion_uuid=f"discussion_{uuid4()}",
                    creation_date=post.get("created_at") or _now(),
                    update_date=post.get("created_at") or _now())
                db_session.add(disc)
                await db_session.commit()
                await db_session.refresh(disc)
                made["discussions"] += 1
            for cm in post.get("comments", []):
                caid = await author_id(cm.get("author_email"), cm.get("author_name"))
                if not caid:
                    continue
                # idempotency: skip if same author+content already on this discussion
                dup = (await db_session.execute(select(DiscussionComment).where(
                    DiscussionComment.discussion_id == disc.id,
                    DiscussionComment.author_id == caid,
                    DiscussionComment.content == (cm.get("content") or "")))).scalars().first()
                if dup:
                    continue
                db_session.add(DiscussionComment(
                    content=cm.get("content") or "", discussion_id=disc.id, author_id=caid,
                    comment_uuid=f"comment_{uuid4()}",
                    creation_date=cm.get("created_at") or _now(),
                    update_date=cm.get("created_at") or _now()))
                made["comments"] += 1
            await db_session.commit()
    return {**made, "errors": errors[:20], "error_count": len(errors)}


@router.get("/verify")
async def verify(request: Request, email: str = "", db_session: AsyncSession = Depends(get_db_session)):
    """Admin-key gated counts to confirm the student migration end-state."""
    _check(request)
    from sqlalchemy import func
    org = (await db_session.execute(select(Organization).where(Organization.slug == "bbu"))).scalars().first()
    org_id = org.id
    users = (await db_session.execute(
        select(func.count()).select_from(UserOrganization).where(UserOrganization.org_id == org_id)
    )).scalar()
    runs = (await db_session.execute(select(func.count()).select_from(TrailRun))).scalar()
    steps = (await db_session.execute(
        select(func.count()).select_from(TrailStep).where(TrailStep.complete == True)  # noqa: E712
    )).scalar()
    out = {"org": "bbu", "users": users, "enrollments_trailruns": runs, "completed_steps": steps}
    if email:
        u = (await db_session.execute(select(User).where(User.email == email.lower()))).scalars().first()
        if u:
            urun = (await db_session.execute(
                select(func.count()).select_from(TrailRun).where(TrailRun.user_id == u.id)
            )).scalar()
            ustep = (await db_session.execute(
                select(func.count()).select_from(TrailStep).where(
                    TrailStep.user_id == u.id, TrailStep.complete == True)  # noqa: E712
            )).scalar()
            out["sample"] = {"email": email, "user_id": u.id, "enrollments": urun, "completed_lessons": ustep}
        else:
            out["sample"] = {"email": email, "found": False}
    return out


@router.post("/students")
async def migrate_students(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    body = await request.json()
    _check(request, body)
    students = body.get("students") or []
    org = (await db_session.execute(
        select(Organization).where(Organization.slug == body.get("org_slug", "bbu"))
    )).scalars().first()
    if not org:
        raise HTTPException(404, "Org not found")
    org_id = org.id
    role_id = await _learner_role_id(db_session)

    # cache course + activity lookups across the batch
    course_cache: dict[str, Course] = {}
    activity_cache: dict[str, Activity] = {}

    async def get_course(uuid):
        if uuid not in course_cache:
            course_cache[uuid] = (await db_session.execute(
                select(Course).where(Course.course_uuid == uuid)
            )).scalars().first()
        return course_cache[uuid]

    async def get_activity(uuid):
        if uuid not in activity_cache:
            activity_cache[uuid] = (await db_session.execute(
                select(Activity).where(Activity.activity_uuid == uuid)
            )).scalars().first()
        return activity_cache[uuid]

    users_made = enrolls = steps = 0
    errors = []
    for s in students:
        email = (s.get("email") or "").strip().lower()
        if not email:
            continue
        try:
            existed = (await db_session.execute(select(User).where(User.email == email))).scalars().first()
            user = await _get_or_create_user(db_session, org_id, role_id, email, s.get("name", ""))
            if not existed:
                users_made += 1
            trail = await _ensure_trail(db_session, org_id, user.id or 0)
            for enr in (s.get("enrollments") or []):
                course = await get_course(enr.get("course_uuid", ""))
                if not course:
                    continue
                run = await _ensure_run(db_session, trail, course, user.id or 0)
                enrolls += 1
                for auuid in (enr.get("completed_activity_uuids") or []):
                    act = await get_activity(auuid)
                    if not act:
                        continue
                    existing = (await db_session.execute(select(TrailStep).where(
                        TrailStep.user_id == user.id, TrailStep.activity_id == act.id,
                    ))).scalars().first()
                    if existing:
                        continue
                    db_session.add(TrailStep(
                        trailrun_id=run.id or 0, activity_id=act.id or 0, course_id=course.id or 0,
                        trail_id=trail.id or 0, org_id=course.org_id, complete=True,
                        teacher_verified=False, grade="", user_id=user.id or 0,
                        creation_date=_now(), update_date=_now(),
                    ))
                    steps += 1
            await db_session.commit()
        except Exception as e:
            await db_session.rollback()
            errors.append(f"{email}: {e}")
    return {"users_created": users_made, "enrollments": enrolls, "steps": steps,
            "errors": errors[:20], "error_count": len(errors)}
