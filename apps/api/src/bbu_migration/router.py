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


@router.get("/courses")
async def list_courses(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Course id/name/uuid map. The cut-over puller needs numeric ids to build
    [email, course_id] enrolment pairs, and names to match against the source."""
    _check(request)
    org = (await db_session.execute(select(Organization).where(Organization.slug == "bbu"))).scalars().first()
    rows = (await db_session.execute(
        select(Course).where(Course.org_id == org.id).order_by(Course.name)
    )).scalars().all()
    return {"count": len(rows), "courses": [
        {"id": c.id, "name": c.name, "uuid": c.course_uuid, "public": c.public} for c in rows]}


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


@router.post("/contacts")
async def migrate_contacts(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Bulk-import contacts (no course enrollment) as org users. Idempotent by
    email; silent (no emails — SMTP isn't configured). Tagged by `source` so the
    batch is filterable/reversible. Body: {contacts:[{email,first_name,last_name}],
    source?, dry_run?}."""
    body = await request.json()
    _check(request, body)
    source = (body.get("source") or "xperiencify_migration")[:60]
    dry_run = str(body.get("dry_run", True)).lower() != "false"
    contacts = body.get("contacts") or []
    org_id = 1
    role_id = await _learner_role_id(db_session)
    created = existing = skipped = 0
    errors = []
    for c in contacts:
        email = (c.get("email") or "").strip().lower()
        if not email or "@" not in email:
            skipped += 1
            continue
        try:
            u = (await db_session.execute(select(User).where(User.email == email))).scalars().first()
            if u:
                existing += 1
                continue
            if dry_run:
                created += 1
                continue
            username = await _unique_username(db_session, email)
            fn = ((c.get("first_name") or "").strip() or "Member")[:100]
            ln = ((c.get("last_name") or "").strip())[:100]
            user = User(
                username=username, email=email, first_name=fn, last_name=ln,
                password=security_hash_password(secrets.token_urlsafe(24)),
                user_uuid=f"user_{uuid4()}", email_verified=False,
                signup_method=source, creation_date=_now(), update_date=_now(),
            )
            db_session.add(user)
            await db_session.commit()
            await db_session.refresh(user)
            db_session.add(UserOrganization(
                user_id=user.id or 0, org_id=org_id, role_id=role_id,
                creation_date=_now(), update_date=_now(),
            ))
            await db_session.commit()
            created += 1
        except Exception as e:
            await db_session.rollback()
            errors.append(f"{email}: {type(e).__name__}: {e}")
    return {"source": source, "dry_run": dry_run, "input": len(contacts),
            "created": created, "existing": existing, "skipped": skipped,
            "errors": errors[:20], "error_count": len(errors)}


@router.post("/provision-agency-course")
async def provision_agency_course(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Create the dedicated 'Doula Agency Owner Mentorship' course (gated) + its
    access usergroup, then wire it to product 26 (seat_count=16, course_uuids) and
    the agency cohort (id 7 by default). Idempotent. Body: {seat_count?, product_id?,
    cohort_id?, dry_run?}."""
    from uuid import uuid4
    from src.db.courses.courses import Course
    from src.db.courses.chapters import Chapter
    from src.db.courses.course_chapters import CourseChapter
    from src.db.courses.activities import (Activity, ActivityTypeEnum,
                                           ActivitySubTypeEnum, ActivityLockType)
    from src.db.courses.chapter_activities import ChapterActivity
    from src.db.usergroups import UserGroup
    from src.db.usergroup_resources import UserGroupResource
    from src.bbu_payments.models import BBUProduct
    from src.bbu_cohorts.models import BBUCohort

    body = await request.json()
    _check(request, body)
    org_id = 1
    seat_count = int(body.get("seat_count", 16))
    product_id = int(body.get("product_id", 26))
    cohort_id = int(body.get("cohort_id", 7))
    NAME = "Doula Agency Owner Mentorship"

    # 1) find or create the course
    course = (await db_session.execute(select(Course).where(
        Course.org_id == org_id, Course.name == NAME))).scalars().first()
    created = False
    if not course:
        course = Course(
            name=NAME,
            description="Your private 5-week live cohort for scaling a doula agency — systems, leadership, and team growth. Live Zoom sessions + community. Use the Members area to manage and share your team seats.",
            learnings="", thumbnail_type=None, thumbnail_image="", thumbnail_video="",
            public=False, published=True, open_to_contributors=False,
            org_id=org_id, course_uuid=f"course_{uuid4()}",
            creation_date=_now(), update_date=_now())
        db_session.add(course)
        await db_session.commit()
        await db_session.refresh(course)
        created = True
        # a welcome chapter + activity so the course is openable
        chap = Chapter(name="Welcome", org_id=org_id, course_id=course.id,
                       chapter_uuid=f"chapter_{uuid4()}", creation_date=_now(), update_date=_now())
        db_session.add(chap)
        await db_session.commit()
        await db_session.refresh(chap)
        db_session.add(CourseChapter(order=0, course_id=course.id, chapter_id=chap.id,
                                     org_id=org_id, creation_date=_now(), update_date=_now()))
        welcome = {"type": "doc", "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Welcome, Agency Owner!"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "This is your Doula Agency Owner Mentorship home. Your live cohort sessions run over Zoom and the discussion happens in your cohort community. To view and share your team's seat codes, open the Members / seat portal link from your purchase confirmation."}]}]}
        act = Activity(name="Welcome to the Mentorship", activity_type=ActivityTypeEnum.TYPE_DYNAMIC,
                       activity_sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_PAGE, content=welcome,
                       details=None, published=True, lock_type=ActivityLockType.RESTRICTED,
                       org_id=org_id, course_id=course.id, activity_uuid=f"activity_{uuid4()}",
                       creation_date=_now(), update_date=_now())
        db_session.add(act)
        await db_session.commit()
        await db_session.refresh(act)
        db_session.add(ChapterActivity(order=0, chapter_id=chap.id, activity_id=act.id,
                                       course_id=course.id, org_id=org_id,
                                       creation_date=_now(), update_date=_now()))
        await db_session.commit()

    cu = course.course_uuid
    # 2) access usergroup (description=course_uuid) + link the course to it
    grp = (await db_session.execute(select(UserGroup).where(
        UserGroup.org_id == org_id, UserGroup.description == cu))).scalars().first()
    if not grp:
        grp = UserGroup(org_id=org_id, name=f"{NAME} · Access", description=cu,
                        usergroup_uuid=f"usergroup_{uuid4()}", creation_date=_now(), update_date=_now())
        db_session.add(grp)
        await db_session.commit()
        await db_session.refresh(grp)
    link = (await db_session.execute(select(UserGroupResource).where(
        UserGroupResource.usergroup_id == grp.id, UserGroupResource.resource_uuid == cu))).scalars().first()
    if not link:
        db_session.add(UserGroupResource(usergroup_id=grp.id, resource_uuid=cu, org_id=org_id,
                                         creation_date=_now(), update_date=_now()))
        await db_session.commit()

    # 3) wire the product: seat_count + course_uuids
    prod = (await db_session.execute(select(BBUProduct).where(BBUProduct.id == product_id))).scalars().first()
    prod_wired = None
    if prod:
        prod.seat_count = seat_count
        prod.course_uuids = cu
        db_session.add(prod)
        await db_session.commit()
        prod_wired = {"id": prod.id, "name": prod.name, "seat_count": prod.seat_count, "course_uuids": prod.course_uuids}

    # 4) wire the cohort: point it at this course
    coh = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == cohort_id))).scalars().first()
    coh_wired = None
    if coh:
        coh.course_uuid = cu
        db_session.add(coh)
        await db_session.commit()
        coh_wired = {"id": coh.id, "name": coh.name, "course_uuid": coh.course_uuid}

    return {"course": {"id": course.id, "uuid": cu, "name": NAME, "created": created,
                       "public": course.public, "published": course.published},
            "access_group_id": grp.id, "product": prod_wired, "cohort": coh_wired}


@router.post("/enrollments")
async def migrate_enrollments(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Bulk enroll existing users into courses + grant gated access. Idempotent.
    No lesson progress is fabricated (source only exposes a %). Body:
    {enrollments:[[email, course_id], ...], grant_access?, dry_run?}."""
    from src.db.usergroups import UserGroup
    from src.db.usergroup_user import UserGroupUser
    body = await request.json()
    _check(request, body)
    dry_run = str(body.get("dry_run", True)).lower() != "false"
    grant_access = str(body.get("grant_access", True)).lower() != "false"
    pairs = body.get("enrollments") or []
    org_id = 1
    # cache: course_id -> Course, course_uuid -> UserGroup, email -> user
    course_cache, grp_cache, user_cache = {}, {}, {}
    enrolled = access = not_found = missing_course = 0
    errors = []
    for i, pr in enumerate(pairs):
        try:
            email = (pr[0] or "").strip().lower()
            cid = int(pr[1])
            if email not in user_cache:
                user_cache[email] = (await db_session.execute(
                    select(User).where(User.email == email))).scalars().first()
            user = user_cache[email]
            if not user:
                not_found += 1
                continue
            if cid not in course_cache:
                course_cache[cid] = (await db_session.execute(
                    select(Course).where(Course.id == cid))).scalars().first()
            course = course_cache[cid]
            if not course:
                missing_course += 1
                continue
            if dry_run:
                enrolled += 1
                continue
            trail = await _ensure_trail(db_session, org_id, user.id or 0)
            await _ensure_run(db_session, trail, course, user.id or 0)
            enrolled += 1
            if grant_access:
                cu = course.course_uuid
                if cu not in grp_cache:
                    grp_cache[cu] = (await db_session.execute(select(UserGroup).where(
                        UserGroup.org_id == org_id, UserGroup.description == cu))).scalars().first()
                grp = grp_cache[cu]
                if grp:
                    has = (await db_session.execute(select(UserGroupUser).where(
                        UserGroupUser.usergroup_id == grp.id,
                        UserGroupUser.user_id == user.id))).scalars().first()
                    if not has:
                        db_session.add(UserGroupUser(
                            usergroup_id=grp.id or 0, user_id=user.id or 0, org_id=org_id,
                            creation_date=_now(), update_date=_now()))
                        access += 1
            if (i + 1) % 200 == 0:
                await db_session.commit()
        except Exception as e:
            await db_session.rollback()
            errors.append(f"{pr}: {type(e).__name__}: {e}")
    if not dry_run:
        await db_session.commit()
    return {"dry_run": dry_run, "grant_access": grant_access, "input": len(pairs),
            "enrolled": enrolled, "access_granted": access, "user_not_found": not_found,
            "course_not_found": missing_course, "errors": errors[:20], "error_count": len(errors)}


@router.post("/seed-catalog")
async def seed_catalog(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Idempotent upsert of the full BBU store catalog. Body: {items:[{name,
    kind, price_cents, currency?, course_names?[] | course_uuids?[], description?,
    benefits?, public?}]}. Maps course_names -> course_uuids by matching Course.name
    so products grant access to the right courses. Upsert key = (name, org_id)."""
    from src.bbu_payments.models import BBUProduct
    body = await request.json()
    _check(request, body)
    items = body.get("items") or []
    org_id = 1
    # name -> course_uuid lookup for this org
    courses = (await db_session.execute(select(Course).where(Course.org_id == org_id))).scalars().all()
    by_name = {c.name.strip().lower(): c.course_uuid for c in courses}
    created, updated, errors = 0, 0, []
    for it in items:
        try:
            name = (it.get("name") or "").strip()
            if not name:
                continue
            uuids = list(it.get("course_uuids") or [])
            for cn in (it.get("course_names") or []):
                cu = by_name.get(cn.strip().lower())
                if cu:
                    uuids.append(cu)
                else:
                    errors.append(f"{name}: no course '{cn}'")
            existing = (await db_session.execute(
                select(BBUProduct).where(BBUProduct.name == name, BBUProduct.org_id == org_id)
            )).scalars().first()
            p = existing or BBUProduct(org_id=org_id, name=name)
            p.kind = it.get("kind", p.kind or "course")
            p.price_cents = int(it.get("price_cents", p.price_cents or 0))
            p.currency = (it.get("currency") or p.currency or "usd").lower()
            if uuids:
                p.course_uuids = ",".join(uuids)
            p.description = it.get("description", p.description) or ""
            p.benefits = it.get("benefits", p.benefits) or ""
            if "image_url" in it:
                p.image_url = it["image_url"]
            p.public = bool(it.get("public", True))
            db_session.add(p)
            await db_session.commit()
            updated += 1 if existing else 0
            created += 0 if existing else 1
        except Exception as e:
            await db_session.rollback()
            errors.append(f"{it.get('name')}: {e}")
    return {"created": created, "updated": updated, "errors": errors[:30], "error_count": len(errors)}


@router.post("/gate-courses")
async def gate_courses(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Gate course access via native usergroups. Per course: find/create an
    access usergroup (description=course_uuid for reliable lookup), link the
    course to it, backfill members from existing TrailRuns (preserve access the
    students already had), and optionally set public=False.

    Body: {course_uuids?: [..] (default all org-1 courses), make_private?: bool,
    dry_run?: bool}. Idempotent. Access after gating = access-group membership,
    which is what a purchase grants (see bbu_payments _grant_course_access)."""
    from uuid import uuid4
    from src.db.usergroups import UserGroup
    from src.db.usergroup_user import UserGroupUser
    from src.db.usergroup_resources import UserGroupResource

    body = await request.json()
    _check(request, body)
    filt = body.get("course_uuids") or []
    make_private = bool(body.get("make_private", False))
    dry = bool(body.get("dry_run", False))
    org_id = 1

    q = select(Course).where(Course.org_id == org_id)
    if filt:
        q = q.where(Course.course_uuid.in_(filt))
    courses = (await db_session.execute(q)).scalars().all()

    results = []
    for c in courses:
        grp = (await db_session.execute(select(UserGroup).where(
            UserGroup.org_id == org_id, UserGroup.description == c.course_uuid
        ))).scalars().first()

        # enrolled users (from trail runs) — the access to preserve
        enrolled = set((await db_session.execute(
            select(TrailRun.user_id).where(TrailRun.course_id == c.id)
        )).scalars().all())

        if dry:
            existing = set()
            if grp:
                existing = set((await db_session.execute(
                    select(UserGroupUser.user_id).where(UserGroupUser.usergroup_id == grp.id)
                )).scalars().all())
            results.append({"course": c.name, "public": c.public,
                            "group_exists": bool(grp), "enrolled": len(enrolled),
                            "would_add": len([u for u in enrolled if u not in existing]),
                            "would_make_private": make_private and c.public})
            continue

        if not grp:
            grp = UserGroup(org_id=org_id, name=f"{c.name} · Access",
                            description=c.course_uuid, usergroup_uuid=f"usergroup_{uuid4()}",
                            creation_date=_now(), update_date=_now())
            db_session.add(grp)
            await db_session.commit()
            await db_session.refresh(grp)

        # link course to the access group
        link = (await db_session.execute(select(UserGroupResource).where(
            UserGroupResource.usergroup_id == grp.id,
            UserGroupResource.resource_uuid == c.course_uuid,
        ))).scalars().first()
        if not link:
            db_session.add(UserGroupResource(
                usergroup_id=grp.id or 0, resource_uuid=c.course_uuid, org_id=org_id,
                creation_date=_now(), update_date=_now()))
            await db_session.commit()

        # backfill members
        existing = set((await db_session.execute(
            select(UserGroupUser.user_id).where(UserGroupUser.usergroup_id == grp.id)
        )).scalars().all())
        to_add = [u for u in enrolled if u not in existing]
        for uid in to_add:
            db_session.add(UserGroupUser(usergroup_id=grp.id or 0, user_id=uid,
                                         org_id=org_id, creation_date=_now(), update_date=_now()))
        if to_add:
            await db_session.commit()

        made_private = False
        if make_private and c.public:
            c.public = False
            db_session.add(c)
            await db_session.commit()
            made_private = True

        results.append({"course": c.name, "group_id": grp.id, "enrolled": len(enrolled),
                        "added": len(to_add), "made_private": made_private,
                        "public_now": c.public})

    return {"courses": len(results), "dry_run": dry,
            "made_private": sum(1 for r in results if r.get("made_private")),
            "detail": results[:40]}


@router.post("/provision-login")
async def provision_login(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Operator tool (admin-key gated): create a login or reset an existing one
    directly in the DB, using LearnHouse's own password hashing so the login
    works. Needed because SMTP isn't configured, so the normal reset-by-email
    flow can't deliver. Body: {email, password, first_name?, last_name?,
    role_uuid?, org_id?}. Sets email_verified so login works without email.

    NOTE: passwords are one-way bcrypt hashes — an existing password cannot be
    recovered, only reset to a new known value (which replaces the old one)."""
    from uuid import uuid4
    body = await request.json()
    _check(request, body)
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not email or not password:
        raise HTTPException(400, "email and password required")
    first = (body.get("first_name") or "").strip()
    last = (body.get("last_name") or "").strip()
    role_uuid = body.get("role_uuid") or "role_global_user"
    org_id = int(body.get("org_id", 1))

    role = (await db_session.execute(
        select(Role).where(Role.role_uuid == role_uuid)
    )).scalars().first()
    role_id = role.id if role and role.id else await _learner_role_id(db_session)

    user = (await db_session.execute(select(User).where(User.email == email))).scalars().first()
    created = False
    if user:
        user.password = security_hash_password(password)
        user.email_verified = True
        if first:
            user.first_name = first
        if last:
            user.last_name = last
        user.update_date = _now()
        db_session.add(user)
        await db_session.commit()
    else:
        username = await _unique_username(db_session, email)
        user = User(
            username=username, email=email,
            first_name=first or "Test", last_name=last or "User",
            password=security_hash_password(password),
            user_uuid=f"user_{uuid4()}", email_verified=True,
            signup_method="admin_provision",
            creation_date=_now(), update_date=_now(),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        created = True

    membership = (await db_session.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == user.id, UserOrganization.org_id == org_id
        )
    )).scalars().first()
    if not membership:
        db_session.add(UserOrganization(
            user_id=user.id or 0, org_id=org_id, role_id=role_id,
            creation_date=_now(), update_date=_now(),
        ))
        await db_session.commit()
    elif role and membership.role_id != role_id:
        membership.role_id = role_id
        db_session.add(membership)
        await db_session.commit()

    return {"email": email, "created": created, "user_id": user.id,
            "username": user.username, "role_uuid": role_uuid, "org_id": org_id}


@router.post("/certifications")
async def setup_certifications(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Create/update a Certifications record per course with BBU config (idempotent —
    one cert per course). Body: {items:[{course_uuid, config}]}. config carries
    certificate_pattern:'bbu', bbu_template, bbu_layout, bbu_validity_years,
    certification_name/description/type."""
    from uuid import uuid4
    from src.db.courses.certifications import Certifications

    body = await request.json()
    _check(request, body)
    items = body.get("items") or []
    made, updated, errors = 0, 0, []
    for it in items:
        cu = (it or {}).get("course_uuid", "")
        config = (it or {}).get("config") or {}
        try:
            course = (await db_session.execute(
                select(Course).where(Course.course_uuid == cu)
            )).scalars().first()
            if not course:
                errors.append(f"{cu}: course not found")
                continue
            existing = (await db_session.execute(
                select(Certifications).where(Certifications.course_id == course.id)
            )).scalars().first()
            if existing:
                existing.config = config
                existing.update_date = _now()
                db_session.add(existing)
                updated += 1
            else:
                db_session.add(Certifications(
                    course_id=course.id or 0, config=config,
                    certification_uuid=f"certification_{uuid4()}",
                    creation_date=_now(), update_date=_now(),
                ))
                made += 1
            await db_session.commit()
        except Exception as e:
            await db_session.rollback()
            errors.append(f"{cu}: {e}")
    return {"created": made, "updated": updated, "errors": errors[:20], "error_count": len(errors)}


@router.post("/issue-certificate")
async def issue_certificate(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Admin: issue a course certificate to a user (by email) — for testing /
    manual grants. Body: {email, course_uuid}. Idempotent per (user, cert)."""
    import secrets as _secrets
    from uuid import uuid4
    from src.db.courses.certifications import Certifications, CertificateUser

    body = await request.json()
    _check(request, body)
    email = (body.get("email") or "").strip().lower()
    cu = (body.get("course_uuid") or "").strip()
    user = (await db_session.execute(select(User).where(User.email == email))).scalars().first()
    if not user:
        raise HTTPException(404, "User not found")
    course = (await db_session.execute(select(Course).where(Course.course_uuid == cu))).scalars().first()
    if not course:
        raise HTTPException(404, "Course not found")
    cert = (await db_session.execute(
        select(Certifications).where(Certifications.course_id == course.id)
    )).scalars().first()
    if not cert:
        raise HTTPException(404, "No certification configured for this course")
    existing = (await db_session.execute(
        select(CertificateUser).where(
            CertificateUser.user_id == user.id,
            CertificateUser.certification_id == cert.id,
        )
    )).scalars().first()
    if existing:
        return {"already": True, "user_certification_uuid": existing.user_certification_uuid}
    _alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    now = datetime.now()
    ucid = (f"{_secrets.choice(_alpha)}{_secrets.choice(_alpha)}-"
            f"{now.year}{now.month:02d}{now.day:02d}-{(user.user_uuid or '')[-4:] or 'USER'}-"
            f"{_secrets.token_hex(4)}")
    row = CertificateUser(user_id=user.id or 0, certification_id=cert.id or 0,
                          user_certification_uuid=ucid, created_at=_now(), updated_at=_now())
    db_session.add(row)
    await db_session.commit()
    return {"issued": True, "user_certification_uuid": ucid,
            "course": course.name}


@router.post("/thumbnails")
async def import_thumbnails(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Set course thumbnails from remote image URLs (e.g. the original Circle
    cover images). Body: {items:[{course_uuid, image_url}], overwrite?:bool}.
    Fetches each image server-side and stores it through the normal thumbnail
    pipeline so it lands in the content volume at the path the UI expects."""
    import io
    import httpx
    from starlette.datastructures import UploadFile as StarletteUploadFile, Headers
    from src.db.courses.courses import ThumbnailType
    from src.services.courses.thumbnails import upload_thumbnail

    body = await request.json()
    _check(request, body)
    items = body.get("items") or []
    overwrite = bool(body.get("overwrite", False))

    # org_id -> org_uuid cache
    org_cache: dict[int, str] = {}
    async def _org_uuid(org_id: int) -> str:
        if org_id not in org_cache:
            o = (await db_session.execute(
                select(Organization).where(Organization.id == org_id)
            )).scalars().first()
            org_cache[org_id] = o.org_uuid if o else ""
        return org_cache[org_id]

    set_count, skipped, errors = 0, 0, []
    async with httpx.AsyncClient(follow_redirects=True, timeout=45) as client:
        for it in items:
            cu = (it or {}).get("course_uuid", "")
            url = (it or {}).get("image_url", "")
            try:
                course = (await db_session.execute(
                    select(Course).where(Course.course_uuid == cu)
                )).scalars().first()
                if not course:
                    errors.append(f"{cu}: course not found")
                    continue
                if course.thumbnail_image and not overwrite:
                    skipped += 1
                    continue
                if not url:
                    errors.append(f"{cu}: no image_url")
                    continue
                r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code != 200 or not r.content:
                    errors.append(f"{cu}: fetch {r.status_code}")
                    continue
                ctype = r.headers.get("content-type", "image/jpeg").split(";")[0]
                ext = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
                       "image/webp": "webp", "image/gif": "gif"}.get(ctype, "jpg")
                uf = StarletteUploadFile(
                    filename=f"circle_cover.{ext}",
                    file=io.BytesIO(r.content),
                    headers=Headers({"content-type": ctype}),
                )
                org_uuid = await _org_uuid(course.org_id)
                name_in_disk = await upload_thumbnail(uf, org_uuid, course.course_uuid)
                course.thumbnail_image = name_in_disk
                course.thumbnail_type = ThumbnailType.IMAGE
                db_session.add(course)
                await db_session.commit()
                set_count += 1
            except Exception as e:
                await db_session.rollback()
                errors.append(f"{cu}: {e}")
    return {"set": set_count, "skipped": skipped,
            "errors": errors[:30], "error_count": len(errors)}


# =========================================================================== #
# Credential course tagging (build-spec 1.6 / 2.1). Merges credential flags into
# each cert-bearing course's Certifications.config so completion auto-issues the
# right credential/CEUs. Idempotent (merge, not replace).
# =========================================================================== #
# name -> flags. Kept explicit (not inferred) so the mapping is auditable.
# bbu_no_skip: integrity-critical courses (professional cert + CEU) where video
# fast-forward past the max-watched point is disabled so completion is genuine.
CREDENTIAL_TAGS = {
    "Certified Birth Doula Training":                  {"bbu_credential_type": "birth", "bbu_no_skip": True},
    "Certified Postpartum Doula Training":             {"bbu_credential_type": "postpartum", "bbu_no_skip": True},
    "Cross Certification Birth Doula Training":         {"bbu_credential_type": "birth", "bbu_is_cross_cert": True, "bbu_no_skip": True},
    "Cross Certification Postpartum Doula Training":    {"bbu_credential_type": "postpartum", "bbu_is_cross_cert": True, "bbu_no_skip": True},
    "Breastfeeding for Perinatal Professionals":       {"bbu_ceu_value": 3, "bbu_no_skip": True},
    "Comfort Measures for Perinatal Professionals":    {"bbu_ceu_value": 3, "bbu_no_skip": True},
    "Newborn Care for Perinatal Professionals":        {"bbu_ceu_value": 3, "bbu_no_skip": True},
}


@router.get("/communities")
async def list_communities(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """List every community with its access + image state (admin-key)."""
    _check(request)
    from src.db.communities.communities import Community
    from src.db.usergroup_resources import UserGroupResource
    from src.db.usergroups import UserGroup
    org_id = 1
    comms = (await db_session.execute(select(Community).where(
        Community.org_id == org_id).order_by(Community.name))).scalars().all()
    # course link (uuid) per community
    course_by_id = {c.id: c for c in (await db_session.execute(
        select(Course).where(Course.org_id == org_id))).scalars().all()}
    # usergroup links per community_uuid
    links = (await db_session.execute(select(UserGroupResource, UserGroup).join(
        UserGroup, UserGroup.id == UserGroupResource.usergroup_id).where(
        UserGroupResource.org_id == org_id))).all()
    groups_by_res: dict = {}
    for link, grp in links:
        groups_by_res.setdefault(link.resource_uuid, []).append(grp.name)
    # Communities hold MANY courses via the community_course join table; the
    # legacy Community.course_id only ever held the first one. Report both, or
    # the mapping looks empty for every community linked after the join landed.
    from src.db.communities.community_courses import CommunityCourse
    joins = (await db_session.execute(select(CommunityCourse).where(
        CommunityCourse.org_id == org_id))).scalars().all()
    courses_by_comm: dict = {}
    for j in joins:
        c = course_by_id.get(j.course_id)
        if c:
            courses_by_comm.setdefault(j.community_id, []).append(c.name)
    out = []
    for c in comms:
        course = course_by_id.get(c.course_id) if c.course_id else None
        linked = sorted(set(courses_by_comm.get(c.id, [])
                            + ([course.name] if course else [])))
        out.append({
            "id": c.id, "community_uuid": c.community_uuid, "name": c.name,
            "public": bool(c.public), "has_image": bool(c.thumbnail_image),
            "course_uuid": course.course_uuid if course else None,
            "course_has_thumb": bool(course.thumbnail_image) if course else False,
            "access_groups": groups_by_res.get(c.community_uuid, []),
            "courses": linked, "course_count": len(linked),
        })
    return out


@router.post("/community-thumbnails")
async def community_thumbnails(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Set community images. Body: {items:[{community_uuid, image_url}], overwrite?}.
    If image_url is omitted for a course-linked community, its linked course's
    existing cover is reused. Fetches remote images and stores them through the
    community thumbnail pipeline so they land where the UI expects."""
    import io, httpx
    from starlette.datastructures import UploadFile as StarletteUploadFile, Headers
    from src.db.communities.communities import Community
    from src.services.communities.thumbnails import upload_community_thumbnail

    body = await request.json()
    _check(request, body)
    items = body.get("items") or []
    overwrite = bool(body.get("overwrite", False))
    org_id = 1
    org = (await db_session.execute(select(Organization).where(Organization.id == org_id))).scalars().first()
    org_uuid = org.org_uuid if org else ""
    courses = {c.id: c for c in (await db_session.execute(
        select(Course).where(Course.org_id == org_id))).scalars().all()}

    set_count, skipped, errors = 0, 0, []
    async with httpx.AsyncClient(follow_redirects=True, timeout=45) as client:
        for it in items:
            cu = (it or {}).get("community_uuid", "")
            url = (it or {}).get("image_url", "")
            try:
                comm = (await db_session.execute(select(Community).where(
                    Community.community_uuid == cu, Community.org_id == org_id))).scalars().first()
                if not comm:
                    errors.append(f"{cu}: community not found"); continue
                if comm.thumbnail_image and not overwrite:
                    skipped += 1; continue
                if not url:
                    errors.append(f"{cu}: no image_url"); continue
                r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code != 200 or not r.content:
                    errors.append(f"{cu}: fetch {r.status_code}"); continue
                ctype = r.headers.get("content-type", "image/jpeg").split(";")[0]
                ext = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
                       "image/webp": "webp", "image/gif": "gif"}.get(ctype, "jpg")
                uf = StarletteUploadFile(filename=f"cover.{ext}", file=io.BytesIO(r.content),
                                         headers=Headers({"content-type": ctype}))
                name = await upload_community_thumbnail(uf, org_uuid, comm.community_uuid)
                comm.thumbnail_image = name
                comm.update_date = _now()
                db_session.add(comm)
                await db_session.commit()
                set_count += 1
            except Exception as e:
                await db_session.rollback()
                errors.append(f"{cu}: {e}")
    return {"set": set_count, "skipped": skipped, "errors": errors[:30], "error_count": len(errors)}


@router.post("/populate-group")
async def populate_group(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Add members to a usergroup so gating it doesn't lock everyone out. Body:
    {group_name, source:"credentials"|"emails", emails?:[...], create?}. source
    'credentials' adds everyone who holds a BBU credential (real professional
    membership). Idempotent."""
    from src.db.usergroups import UserGroup
    from src.db.usergroup_user import UserGroupUser
    from src.bbu_credentials.models import BBUCredential
    body = await request.json()
    _check(request, body)
    org_id = 1
    gname = (body.get("group_name") or "").strip()
    source = body.get("source", "emails")
    if not gname:
        raise HTTPException(400, "group_name required")
    grp = (await db_session.execute(select(UserGroup).where(
        UserGroup.org_id == org_id, UserGroup.name == gname))).scalars().first()
    if not grp:
        if not body.get("create", True):
            raise HTTPException(404, "group not found")
        grp = UserGroup(org_id=org_id, name=gname, description=f"audience:{gname}",
                        usergroup_uuid=f"usergroup_{uuid4()}", creation_date=_now(), update_date=_now())
        db_session.add(grp); await db_session.commit(); await db_session.refresh(grp)

    user_ids = set()
    if source == "credentials":
        uids = (await db_session.execute(select(BBUCredential.user_id).where(
            BBUCredential.org_id == org_id))).scalars().all()
        user_ids = {u for u in uids if u}
    else:
        emails = [e.strip().lower() for e in (body.get("emails") or []) if e]
        if emails:
            rows = (await db_session.execute(select(User).where(User.email.in_(emails)))).scalars().all()
            user_ids = {u.id for u in rows}
    existing = set((await db_session.execute(select(UserGroupUser.user_id).where(
        UserGroupUser.usergroup_id == grp.id))).scalars().all())
    added = 0
    for uid in user_ids:
        if uid in existing:
            continue
        db_session.add(UserGroupUser(usergroup_id=grp.id or 0, user_id=uid or 0,
                                     org_id=org_id, creation_date=_now(), update_date=_now()))
        added += 1
    await db_session.commit()
    return {"group": gname, "candidates": len(user_ids), "added": added,
            "already_members": len(existing)}


@router.post("/gate-communities")
async def gate_communities(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Gate community access via usergroups (same mechanism as courses). Body:
    {items:[{community_uuid, group_name}], make_private?}. Per item: find/create the
    named usergroup, link the community to it; optionally set public=false so only
    members see it. Idempotent."""
    from src.db.communities.communities import Community
    from src.db.usergroups import UserGroup
    from src.db.usergroup_resources import UserGroupResource
    body = await request.json()
    _check(request, body)
    items = body.get("items") or []
    make_private = bool(body.get("make_private", True))
    org_id = 1
    results = []
    for it in items:
        cu = (it or {}).get("community_uuid", "")
        gname = (it or {}).get("group_name", "")
        comm = (await db_session.execute(select(Community).where(
            Community.community_uuid == cu, Community.org_id == org_id))).scalars().first()
        if not comm or not gname:
            results.append({"community_uuid": cu, "error": "missing community or group_name"}); continue
        grp = (await db_session.execute(select(UserGroup).where(
            UserGroup.org_id == org_id, UserGroup.name == gname))).scalars().first()
        if not grp:
            grp = UserGroup(org_id=org_id, name=gname, description=f"community:{cu}",
                            usergroup_uuid=f"usergroup_{uuid4()}", creation_date=_now(), update_date=_now())
            db_session.add(grp); await db_session.commit(); await db_session.refresh(grp)
        link = (await db_session.execute(select(UserGroupResource).where(
            UserGroupResource.usergroup_id == grp.id,
            UserGroupResource.resource_uuid == cu))).scalars().first()
        if not link:
            db_session.add(UserGroupResource(usergroup_id=grp.id or 0, resource_uuid=cu,
                                             org_id=org_id, creation_date=_now(), update_date=_now()))
        if make_private:
            comm.public = False
            comm.update_date = _now()
            db_session.add(comm)
        await db_session.commit()
        results.append({"community": comm.name, "group": gname, "private": make_private})
    return {"gated": results}


@router.post("/set-learner-menu")
async def set_learner_menu(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Set which tabs appear in the learner top nav. Body: {items:["courses",
    "communities","store"], dry_run?} — anything omitted is hidden. Writes
    customization.menu.items on the org config (data, not code)."""
    from sqlalchemy.orm.attributes import flag_modified
    from src.db.organization_config import OrganizationConfig
    body = await request.json()
    _check(request, body)
    org_id = int(body.get("org_id", 1))
    dry = bool(body.get("dry_run"))
    keep = body.get("items") or ["courses", "communities", "store"]

    row = (await db_session.execute(select(OrganizationConfig).where(
        OrganizationConfig.org_id == org_id))).scalars().first()
    if not row:
        raise HTTPException(404, "Org config not found")
    cfg = dict(row.config or {})
    # config is stored under a nested "config" key in this schema version
    inner = dict(cfg.get("config") or cfg)
    custom = dict(inner.get("customization") or {})
    before = ((custom.get("menu") or {}).get("items")) or []
    custom["menu"] = {"items": [{"type": t, "enabled": True, "order": i,
                                 "label": "", "url": "", "icon": ""}
                                for i, t in enumerate(keep)]}
    inner["customization"] = custom
    if "config" in cfg:
        cfg["config"] = inner
    else:
        cfg = inner
    if not dry:
        row.config = cfg
        flag_modified(row, "config")
        db_session.add(row)
        await db_session.commit()
    return {"dry_run": dry, "kept": keep,
            "hidden": [t for t in ["courses", "library", "podcasts", "communities",
                                   "playgrounds", "store"] if t not in keep],
            "previous_items": before}


@router.post("/fix-certificate-dates")
async def fix_certificate_dates(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Correct the reissued course certificates to their REAL earned dates using an
    Accredible export. The bulk reissue stamped everything with today's date because
    no real dates were available; this backdates each certificate to Accredible's
    issued_on. Body: {items:[{email,group_name,issued_on}], dry_run?}.

    Mapping: a 'Provisional 1 Year …' record dates the full TRAINING course (that's
    when the training was completed). A 'Certified … Doula' record for someone with
    NO provisional came in via cross-certification, so it dates the CROSS-CERT
    course. Perinatal-professional records date their own course."""
    from src.db.courses.certifications import Certifications, CertificateUser
    body = await request.json()
    _check(request, body)
    dry = bool(body.get("dry_run", True))
    items = body.get("items") or []
    org_id = 1

    PROVISIONAL_TO_COURSE = {
        "Provisional 1 Year Certified Postpartum Doula": "Certified Postpartum Doula Training",
        "Provisional 1 Year Certified Labor Doula": "Certified Birth Doula Training",
    }
    FULL_ONLY_TO_COURSE = {   # full with no provisional => came via cross-cert
        "Certified Postpartum Doula": "Cross Certification Postpartum Doula Training",
        "Certified Labor Doula": "Cross Certification Birth Doula Training",
    }
    SELF_TITLED = {
        "Breastfeeding for Perinatal Professionals",
        "Newborn Care for Perinatal Professionals",
        "Comfort Measures for Perinatal Professionals",
    }
    FULL_TYPE = {"Certified Postpartum Doula": "postpartum", "Certified Labor Doula": "birth"}
    PROV_TYPE = {"Provisional 1 Year Certified Postpartum Doula": "postpartum",
                 "Provisional 1 Year Certified Labor Doula": "birth"}

    # who holds a provisional per (email, type) -> a later full is an upgrade, not a cross-cert
    has_prov = set()
    for it in items:
        t = PROV_TYPE.get((it.get("group_name") or "").strip())
        if t:
            has_prov.add(((it.get("email") or "").strip().lower(), t))

    # target (email, course_name) -> earliest real date
    targets: dict = {}
    for it in items:
        email = (it.get("email") or "").strip().lower()
        grp = (it.get("group_name") or "").strip()
        issued = (it.get("issued_on") or "").strip()
        if not email or not issued:
            continue
        course_name = None
        if grp in PROVISIONAL_TO_COURSE:
            course_name = PROVISIONAL_TO_COURSE[grp]
        elif grp in SELF_TITLED:
            course_name = grp
        elif grp in FULL_ONLY_TO_COURSE:
            if (email, FULL_TYPE[grp]) in has_prov:
                continue          # upgrade of their own training, already dated above
            course_name = FULL_ONLY_TO_COURSE[grp]
        if not course_name:
            continue
        key = (email, course_name)
        if key not in targets or issued < targets[key]:
            targets[key] = issued

    courses = (await db_session.execute(select(Course).where(Course.org_id == org_id))).scalars().all()
    by_name = {c.name.strip(): c for c in courses}
    certs = (await db_session.execute(select(Certifications))).scalars().all()
    cert_by_course = {c.course_id: c for c in certs}

    fixed = no_user = no_course = no_cert_row = 0
    for (email, course_name), issued in targets.items():
        course = by_name.get(course_name)
        if not course:
            no_course += 1
            continue
        cert = cert_by_course.get(course.id)
        if not cert:
            no_cert_row += 1
            continue
        user = (await db_session.execute(select(User).where(User.email == email))).scalars().first()
        if not user:
            no_user += 1
            continue
        cu = (await db_session.execute(select(CertificateUser).where(
            CertificateUser.user_id == user.id,
            CertificateUser.certification_id == cert.id))).scalars().first()
        if not cu:
            no_cert_row += 1
            continue
        if not dry:
            cu.created_at = issued
            cu.updated_at = issued
            db_session.add(cu)
        fixed += 1
    if not dry:
        await db_session.commit()
    return {"dry_run": dry, "targets": len(targets), "certificates_dated": fixed,
            "missing_user": no_user, "missing_course": no_course,
            "no_certificate_issued": no_cert_row}


@router.get("/no-skip-courses")
async def no_skip_courses(db_session: AsyncSession = Depends(get_db_session)):
    """Public: course_uuids where video forward-seek is disabled and lessons must be
    completed in order.

    BBU policy: this applies to EVERY course — a student should never be able to
    skip a video or jump ahead, regardless of whether the course carries a
    certificate. A course can opt OUT by setting bbu_allow_skip=true on its
    Certifications.config (nothing does today)."""
    from src.db.courses.certifications import Certifications
    org_id = 1
    certs = (await db_session.execute(select(Certifications))).scalars().all()
    opted_out = {c.course_id for c in certs if (c.config or {}).get("bbu_allow_skip")}
    courses = (await db_session.execute(select(Course).where(
        Course.org_id == org_id))).scalars().all()
    return {"course_uuids": [c.course_uuid for c in courses if c.id not in opted_out]}


@router.post("/tag-credential-courses")
async def tag_credential_courses(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Merge credential flags (bbu_credential_type / bbu_is_cross_cert /
    bbu_ceu_value) into each course's Certifications.config. Body: {dry_run?,
    overrides?:{course_name:{...flags}}}. Requires the course to already have a
    Certifications record (run /certifications first)."""
    from sqlalchemy.orm.attributes import flag_modified
    from src.db.courses.certifications import Certifications
    body = await request.json()
    _check(request, body)
    org_id = 1
    dry = bool(body.get("dry_run"))
    tags = dict(CREDENTIAL_TAGS)
    for nm, fl in (body.get("overrides") or {}).items():
        tags[nm] = fl
    courses = (await db_session.execute(select(Course).where(Course.org_id == org_id))).scalars().all()
    by_name = {c.name.strip(): c for c in courses}
    applied, missing_course, missing_cert = [], [], []
    for name, flags in tags.items():
        course = by_name.get(name.strip())
        if not course:
            missing_course.append(name); continue
        cert = (await db_session.execute(select(Certifications).where(
            Certifications.course_id == course.id))).scalars().first()
        if not cert:
            missing_cert.append(name); continue
        cfg = dict(cert.config or {})
        before = {k: cfg.get(k) for k in flags}
        if before != flags and not dry:
            cfg.update(flags)
            cert.config = cfg
            flag_modified(cert, "config")
            cert.update_date = _now()
            db_session.add(cert)
        applied.append({"course": name, "flags": flags, "was": before})
    if not dry:
        await db_session.commit()
    return {"dry_run": dry, "applied": applied,
            "missing_course": missing_course, "missing_cert": missing_cert}


# =========================================================================== #
# Certificate reissue (build-spec 1.6). Migration imported completions as
# TrailSteps but never issued course certificates. This issues a CertificateUser
# to every student who completed ALL activities of a cert-bearing course, so
# existing holders can re-download at cutover. Direct row creation — does NOT run
# the credential engine (historical dates unknown; that backfill waits on the
# Accredible export). Idempotent; dry_run reports counts first.
# =========================================================================== #
@router.post("/reissue-certificates")
async def reissue_certificates(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Body: {course_uuids?:[...], dry_run?:bool, issue_date?:ISO}. Default
    dry_run=True. issue_date defaults to now (original Circle dates aren't in the
    migration snapshot — accurate dates require the Accredible export)."""
    import secrets as _secrets
    from sqlalchemy import func as _func
    from uuid import uuid4 as _uuid4
    from src.db.courses.certifications import Certifications, CertificateUser
    from src.db.trail_steps import TrailStep

    body = await request.json()
    _check(request, body)
    org_id = 1
    dry = body.get("dry_run", True)
    issue_dt = (body.get("issue_date") or _now())
    only = set(body.get("course_uuids") or [])

    # cert-bearing courses = those with a Certifications record
    certs = (await db_session.execute(select(Certifications))).scalars().all()
    cert_by_course = {c.course_id: c for c in certs}
    courses = (await db_session.execute(select(Course).where(
        Course.org_id == org_id, Course.id.in_(list(cert_by_course.keys()))))).scalars().all()

    _alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    report, total_issued, total_completers = [], 0, 0
    for course in courses:
        if only and course.course_uuid not in only:
            continue
        cert = cert_by_course.get(course.id)
        # total activities for this course
        act_ids = [a for (a,) in (await db_session.execute(
            select(Activity.id).where(Activity.course_id == course.id))).all()]
        n_act = len(act_ids)
        if n_act == 0:
            report.append({"course": course.name, "completers": 0, "issued": 0, "note": "no activities"})
            continue
        # users with completed steps covering ALL activities
        rows = (await db_session.execute(
            select(TrailStep.user_id, _func.count(_func.distinct(TrailStep.activity_id)))
            .where(TrailStep.course_id == course.id, TrailStep.complete == True)  # noqa: E712
            .group_by(TrailStep.user_id))).all()
        completers = [uid for (uid, cnt) in rows if cnt and cnt >= n_act]
        total_completers += len(completers)
        # existing cert holders (skip)
        have = set((await db_session.execute(
            select(CertificateUser.user_id).where(
                CertificateUser.certification_id == cert.id))).scalars().all())
        to_issue = [u for u in completers if u not in have]
        issued = 0
        if not dry:
            for uid in to_issue:
                u = (await db_session.execute(select(User).where(User.id == uid))).scalars().first()
                short = (u.user_uuid[-4:] if u and u.user_uuid else "USER")
                ucid = (f"{_secrets.choice(_alpha)}{_secrets.choice(_alpha)}-"
                        f"{issue_dt[:10].replace('-','')}-{short}-{_secrets.token_hex(4)}")
                db_session.add(CertificateUser(
                    user_id=uid, certification_id=cert.id or 0,
                    user_certification_uuid=ucid, created_at=issue_dt, updated_at=issue_dt))
                issued += 1
            await db_session.commit()
        report.append({"course": course.name, "activities": n_act,
                       "completers": len(completers), "already_have": len(have),
                       "issued": (issued if not dry else len(to_issue))})
        total_issued += (issued if not dry else len(to_issue))
    report.sort(key=lambda r: -r.get("issued", 0))
    return {"dry_run": dry, "issue_date": issue_dt,
            "total_completers": total_completers, "total_to_issue": total_issued,
            "by_course": report}
