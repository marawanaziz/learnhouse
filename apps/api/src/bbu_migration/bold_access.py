"""Project BOLD host attribution and access automation.

Project BOLD uses LearnHouse's existing UserGroupResource and TrailRun access
models. The public host is the only source of automatic BOLD attribution;
email domains, names, and ordinary BBU membership are deliberately ignored.
"""

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Request, Depends
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.communities.communities import Community
from src.db.courses.courses import Course
from src.db.communities.community_courses import CommunityCourse
from src.db.trails import Trail
from src.db.trail_runs import TrailRun
from src.db.trail_steps import TrailStep
from src.db.usergroup_resources import UserGroupResource
from src.db.usergroup_user import UserGroupUser
from src.db.usergroups import UserGroup
from src.db.user_organizations import UserOrganization
from src.db.users import User
from src.bbu_migration.router import _check


router = APIRouter()

ORG_ID = 1
BOLD_HOST = "learn.boldmovement.org"
BOLD_COMMUNITY_NAMES = (
    "Project BOLD Families",
    "Project BOLD for Perinatal Professionals",
    "Project BOLD — Spanish-Speaking Families",
)
OWNER_NAMED_USERS = {
    302: "kate@throughtothrive.org",
    3621: "anna@chicagofamilydoulas.com",
}


def _now() -> str:
    return str(datetime.now())


def _request_hostname(request: Request) -> str:
    """Return the public request hostname, without trusting arbitrary paths."""
    forwarded = request.headers.get("x-forwarded-host")
    raw = forwarded or request.headers.get("host", "")
    return raw.split(",", 1)[0].strip().split(":", 1)[0].rstrip(".").lower()


def is_bold_host_request(request: Request) -> bool:
    return _request_hostname(request) == BOLD_HOST


def is_bold_course(course: Course) -> bool:
    return "bold" in (course.name or "").casefold()


def _bold_metadata(user: User) -> dict:
    metadata = user.extra_metadata
    return dict(metadata) if isinstance(metadata, dict) else {}


def is_bold_participant(user: User) -> bool:
    return _bold_metadata(user).get("bold_participant") is True


def is_deterministically_host_attributed(user: User) -> bool:
    metadata = _bold_metadata(user)
    return (
        metadata.get("bold_participant") is True
        and metadata.get("bold_signup_host") == BOLD_HOST
    )


def mark_bold_participant(user: User, source: str) -> bool:
    metadata = _bold_metadata(user)
    changed = (
        metadata.get("bold_participant") is not True
        or metadata.get("bold_access_source") != source
    )
    metadata["bold_participant"] = True
    metadata["bold_access_source"] = source
    if source in {"host_signup", "host_login"}:
        if metadata.get("bold_signup_host") != BOLD_HOST:
            changed = True
        metadata["bold_signup_host"] = BOLD_HOST
    if changed:
        user.extra_metadata = metadata
    return changed


async def _target_groups(db: AsyncSession, org_id: int) -> list[UserGroup]:
    communities = (
        await db.execute(
            select(Community).where(
                Community.org_id == org_id,
                Community.name.in_(BOLD_COMMUNITY_NAMES),
            )
        )
    ).scalars().all()
    if not communities:
        return []
    community_uuids = [c.community_uuid for c in communities]
    group_ids = (
        await db.execute(
            select(UserGroupResource.usergroup_id).where(
                UserGroupResource.org_id == org_id,
                UserGroupResource.resource_uuid.in_(community_uuids),
            )
        )
    ).scalars().all()
    if not group_ids:
        return []
    return (
        await db.execute(
            select(UserGroup).where(
                UserGroup.org_id == org_id,
                UserGroup.id.in_(group_ids),
            )
        )
    ).scalars().all()


async def _published_bold_courses(db: AsyncSession, org_id: int) -> list[Course]:
    courses = (
        await db.execute(
            select(Course).where(
                Course.org_id == org_id,
                Course.published == True,  # noqa: E712
            )
        )
    ).scalars().all()
    return [course for course in courses if is_bold_course(course)]


async def _ensure_group_memberships(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    groups: list[UserGroup],
) -> tuple[int, int]:
    added = 0
    existing = 0
    for group in groups:
        if not group.id:
            continue
        membership = (
            await db.execute(
                select(UserGroupUser).where(
                    UserGroupUser.usergroup_id == group.id,
                    UserGroupUser.user_id == user_id,
                )
            )
        ).scalars().first()
        if membership:
            existing += 1
            continue
        db.add(
            UserGroupUser(
                usergroup_id=group.id,
                user_id=user_id,
                org_id=org_id,
                creation_date=_now(),
                update_date=_now(),
            )
        )
        added += 1
    return added, existing


async def _ensure_course_group_links(
    db: AsyncSession,
    courses: list[Course],
    groups: list[UserGroup],
) -> int:
    added = 0
    for course in courses:
        if not course.course_uuid:
            continue
        for group in groups:
            if not group.id:
                continue
            link = (
                await db.execute(
                    select(UserGroupResource).where(
                        UserGroupResource.usergroup_id == group.id,
                        UserGroupResource.resource_uuid == course.course_uuid,
                    )
                )
            ).scalars().first()
            if link:
                continue
            db.add(
                UserGroupResource(
                    usergroup_id=group.id,
                    resource_uuid=course.course_uuid,
                    org_id=course.org_id,
                    creation_date=_now(),
                    update_date=_now(),
                )
            )
            added += 1
    return added


async def _ensure_trail(db: AsyncSession, org_id: int, user_id: int) -> Trail:
    trail = (
        await db.execute(
            select(Trail).where(Trail.org_id == org_id, Trail.user_id == user_id)
        )
    ).scalars().first()
    if trail:
        return trail
    trail = Trail(
        org_id=org_id,
        user_id=user_id,
        trail_uuid=f"trail_{uuid4()}",
        creation_date=_now(),
        update_date=_now(),
    )
    db.add(trail)
    await db.flush()
    return trail


async def _ensure_course_runs(
    db: AsyncSession,
    user_id: int,
    courses: list[Course],
    org_id: int,
) -> tuple[int, int]:
    trail = await _ensure_trail(db, org_id, user_id)
    added = 0
    existing = 0
    for course in courses:
        if not trail.id or not course.id:
            continue
        run = (
            await db.execute(
                select(TrailRun).where(
                    TrailRun.trail_id == trail.id,
                    TrailRun.course_id == course.id,
                    TrailRun.user_id == user_id,
                )
            )
        ).scalars().first()
        if run:
            existing += 1
            continue
        db.add(
            TrailRun(
                trail_id=trail.id,
                course_id=course.id,
                org_id=org_id,
                user_id=user_id,
                creation_date=_now(),
                update_date=_now(),
            )
        )
        added += 1
    return added, existing


async def ensure_bold_access(
    db: AsyncSession,
    user_id: int,
    org_id: int = ORG_ID,
    source: str | None = None,
) -> dict:
    """Idempotently grant the current BOLD course/community access."""
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalars().first()
    if not user:
        return {"user_id": user_id, "found": False}
    org_membership = (
        await db.execute(
            select(UserOrganization).where(
                UserOrganization.user_id == user_id,
                UserOrganization.org_id == org_id,
            )
        )
    ).scalars().first()
    if not org_membership:
        return {"user_id": user_id, "found": True, "org_member": False}

    if source:
        mark_bold_participant(user, source)
    groups = await _target_groups(db, org_id)
    courses = await _published_bold_courses(db, org_id)
    resource_links = await _ensure_course_group_links(db, courses, groups)
    memberships_added, memberships_existing = await _ensure_group_memberships(
        db, user_id, org_id, groups
    )
    runs_added, runs_existing = await _ensure_course_runs(
        db, user_id, courses, org_id
    )
    db.add(user)
    await db.commit()
    return {
        "user_id": user_id,
        "found": True,
        "org_member": True,
        "bold_courses": len(courses),
        "target_communities": len(groups),
        "course_group_links_added": resource_links,
        "community_memberships_added": memberships_added,
        "community_memberships_existing": memberships_existing,
        "enrollments_added": runs_added,
        "enrollments_existing": runs_existing,
    }


async def ensure_bold_access_for_request(
    request: Request,
    db: AsyncSession,
    user_id: int,
    org_id: int = ORG_ID,
    source: str = "host_login",
) -> dict | None:
    if not is_bold_host_request(request):
        return None
    return await ensure_bold_access(db, user_id, org_id, source=source)


async def ensure_bold_course_access(
    db: AsyncSession, course: Course
) -> dict:
    """Make a newly/currently published BOLD course visible to BOLD members."""
    if not course.published or not is_bold_course(course):
        return {"course_uuid": course.course_uuid, "eligible": False}
    groups = await _target_groups(db, course.org_id)
    links_added = await _ensure_course_group_links(db, [course], groups)
    participants = (
        await db.execute(
            select(User).join(
                UserOrganization, UserOrganization.user_id == User.id
            ).where(UserOrganization.org_id == course.org_id)
        )
    ).scalars().all()
    participants = [user for user in participants if is_bold_participant(user)]
    runs_added = 0
    for user in participants:
        added, _existing = await _ensure_course_runs(
            db, user.id or 0, [course], course.org_id
        )
        runs_added += added
    await db.commit()
    return {
        "course_uuid": course.course_uuid,
        "eligible": True,
        "group_links_added": links_added,
        "participant_count": len(participants),
        "enrollments_added": runs_added,
    }


async def _safe_user_snapshot(db: AsyncSession, user_ids: set[int]) -> list[dict]:
    if not user_ids:
        return []
    users = (
        await db.execute(select(User).where(User.id.in_(user_ids)))
    ).scalars().all()
    return [
        {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "bold_participant": is_bold_participant(user),
            "bold_signup_host": _bold_metadata(user).get("bold_signup_host"),
            "bold_access_source": _bold_metadata(user).get("bold_access_source"),
        }
        for user in users
    ]


@router.get("/bold/status")
async def bold_status(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    _check(request)
    courses = (
        await db_session.execute(
            select(Course).where(Course.org_id == ORG_ID).order_by(Course.id)
        )
    ).scalars().all()
    bold_courses = [course for course in courses if is_bold_course(course)]
    communities = (
        await db_session.execute(
            select(Community).where(
                Community.org_id == ORG_ID,
                Community.name.in_(BOLD_COMMUNITY_NAMES),
            ).order_by(Community.id)
        )
    ).scalars().all()
    groups = await _target_groups(db_session, ORG_ID)
    users = (
        await db_session.execute(
            select(User).join(
                UserOrganization, UserOrganization.user_id == User.id
            ).where(UserOrganization.org_id == ORG_ID)
        )
    ).scalars().all()
    attributed = {
        user.id for user in users
        if user.id and is_deterministically_host_attributed(user)
    }
    explicit_ids = set(OWNER_NAMED_USERS)
    snapshot = await _safe_user_snapshot(db_session, attributed | explicit_ids)
    course_ids = {course.id for course in bold_courses if course.id}
    participant_ids = {
        user.id for user in users if user.id and is_bold_participant(user)
    } | explicit_ids
    enrollment_query = select(TrailRun)
    if course_ids and participant_ids:
        enrollment_query = enrollment_query.where(
            TrailRun.course_id.in_(course_ids),
            TrailRun.user_id.in_(participant_ids),
        )
    else:
        enrollment_query = enrollment_query.where(False)
    enrollments = (await db_session.execute(enrollment_query)).scalars().all()
    membership_count = 0
    group_ids = [g.id for g in groups if g.id]
    if group_ids and participant_ids:
        membership_count = len(
            (
                await db_session.execute(
                    select(UserGroupUser).where(
                        UserGroupUser.usergroup_id.in_(group_ids),
                        UserGroupUser.user_id.in_(participant_ids),
                    )
                )
            ).scalars().all()
        )
    return {
        "host": BOLD_HOST,
        "communities": [
            {"id": c.id, "uuid": c.community_uuid, "name": c.name, "public": c.public}
            for c in communities
        ],
        "groups": [
            {"id": g.id, "uuid": g.usergroup_uuid, "name": g.name}
            for g in groups
        ],
        "bold_courses": [
            {
                "id": c.id,
                "uuid": c.course_uuid,
                "name": c.name,
                "published": c.published,
                "public": c.public,
            }
            for c in bold_courses
        ],
        "bold_course_count": len(bold_courses),
        "published_bold_course_count": sum(1 for c in bold_courses if c.published),
        "deterministically_host_attributed_user_ids": sorted(attributed),
        "participant_user_ids": sorted(participant_ids),
        "participant_users": snapshot,
        "participant_bold_enrollment_count": len(enrollments),
        "participant_target_membership_count": membership_count,
        "owner_named_users": OWNER_NAMED_USERS,
    }


@router.get("/bold/backup")
async def bold_backup(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    """Read-only, BOLD-scoped recovery snapshot. No secrets are returned."""
    _check(request)
    status = await bold_status(request, db_session)
    bold_course_ids = {
        item["id"] for item in status["bold_courses"] if item.get("id")
    }
    runs_query = select(TrailRun)
    if bold_course_ids:
        runs_query = runs_query.where(TrailRun.course_id.in_(bold_course_ids))
    else:
        runs_query = runs_query.where(False)
    runs = (await db_session.execute(runs_query)).scalars().all()
    run_ids = [run.id for run in runs if run.id]
    steps_query = select(TrailStep)
    if run_ids:
        steps_query = steps_query.where(TrailStep.trailrun_id.in_(run_ids))
    else:
        steps_query = steps_query.where(False)
    steps = (await db_session.execute(steps_query)).scalars().all()
    groups = await _target_groups(db_session, ORG_ID)
    group_ids = [g.id for g in groups if g.id]
    memberships_query = select(UserGroupUser)
    resources_query = select(UserGroupResource)
    if group_ids:
        memberships_query = memberships_query.where(
            UserGroupUser.usergroup_id.in_(group_ids)
        )
        resources_query = resources_query.where(
            UserGroupResource.usergroup_id.in_(group_ids)
        )
    else:
        memberships_query = memberships_query.where(False)
        resources_query = resources_query.where(False)
    memberships = (await db_session.execute(memberships_query)).scalars().all()
    resources = (await db_session.execute(resources_query)).scalars().all()
    communities = (
        await db_session.execute(
            select(Community).where(
                Community.org_id == ORG_ID,
                Community.name.in_(BOLD_COMMUNITY_NAMES),
            )
        )
    ).scalars().all()
    community_ids = [community.id for community in communities if community.id]
    community_courses_query = select(CommunityCourse)
    if community_ids:
        community_courses_query = community_courses_query.where(
            CommunityCourse.community_id.in_(community_ids)
        )
    else:
        community_courses_query = community_courses_query.where(False)
    community_courses = (
        await db_session.execute(community_courses_query)
    ).scalars().all()
    users = (
        await db_session.execute(
            select(User).join(
                UserOrganization, UserOrganization.user_id == User.id
            ).where(UserOrganization.org_id == ORG_ID)
        )
    ).scalars().all()
    participant_ids = {
        user.id for user in users if user.id and is_bold_participant(user)
    } | set(OWNER_NAMED_USERS)
    return {
        "captured_at": _now(),
        "configuration": {
            "host": BOLD_HOST,
            "community_names": list(BOLD_COMMUNITY_NAMES),
            "owner_named_user_ids": OWNER_NAMED_USERS,
        },
        "users": await _safe_user_snapshot(db_session, participant_ids),
        "courses": status["bold_courses"],
        "communities": status["communities"],
        "groups": status["groups"],
        "enrollments": [
            {
                "id": run.id,
                "trail_id": run.trail_id,
                "course_id": run.course_id,
                "org_id": run.org_id,
                "user_id": run.user_id,
                "data": run.data,
                "status": run.status,
                "creation_date": run.creation_date,
                "update_date": run.update_date,
            }
            for run in runs
        ],
        "enrollment_steps": [
            {
                "id": step.id,
                "trailrun_id": step.trailrun_id,
                "activity_id": step.activity_id,
                "course_id": step.course_id,
                "trail_id": step.trail_id,
                "org_id": step.org_id,
                "complete": step.complete,
                "teacher_verified": step.teacher_verified,
                "grade": step.grade,
                "user_id": step.user_id,
                "creation_date": step.creation_date,
                "update_date": step.update_date,
            }
            for step in steps
        ],
        "community_memberships": [
            {
                "id": membership.id,
                "usergroup_id": membership.usergroup_id,
                "user_id": membership.user_id,
                "org_id": membership.org_id,
                "creation_date": membership.creation_date,
                "update_date": membership.update_date,
            }
            for membership in memberships
        ],
        "group_resources": [
            {
                "id": resource.id,
                "usergroup_id": resource.usergroup_id,
                "resource_uuid": resource.resource_uuid,
                "org_id": resource.org_id,
                "creation_date": resource.creation_date,
                "update_date": resource.update_date,
            }
            for resource in resources
        ],
        "community_course_links": [
            {
                "id": link.id,
                "org_id": link.org_id,
                "community_id": link.community_id,
                "course_id": link.course_id,
                "creation_date": link.creation_date,
            }
            for link in community_courses
        ],
    }


@router.post("/bold/backfill")
async def bold_backfill(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    """Backfill exact host-attributed users and the two owner-named accounts."""
    body = await request.json() if await request.body() else {}
    _check(request, body)
    users = (
        await db_session.execute(
            select(User).join(
                UserOrganization, UserOrganization.user_id == User.id
            ).where(UserOrganization.org_id == ORG_ID)
        )
    ).scalars().all()
    attributed = {
        user.id for user in users
        if user.id and is_deterministically_host_attributed(user)
    }
    target_ids = set(attributed)
    for user_id, expected_email in OWNER_NAMED_USERS.items():
        user = (
            await db_session.execute(select(User).where(User.id == user_id))
        ).scalars().first()
        if user and str(user.email).casefold() == expected_email:
            target_ids.add(user_id)
    results = []
    for user_id in sorted(target_ids):
        source = "owner_named" if user_id in OWNER_NAMED_USERS else "host_signup"
        results.append(await ensure_bold_access(db_session, user_id, source=source))
    return {
        "target_user_ids": sorted(target_ids),
        "deterministically_host_attributed_user_ids": sorted(attributed),
        "results": results,
    }


@router.post("/bold/course-sync")
async def bold_course_sync(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    """Apply published BOLD access to every matching course, idempotently."""
    body = await request.json() if await request.body() else {}
    _check(request, body)
    courses = await _published_bold_courses(db_session, ORG_ID)
    results = [await ensure_bold_course_access(db_session, course) for course in courses]
    return {"course_count": len(courses), "results": results}
