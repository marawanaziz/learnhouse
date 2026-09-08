"""BBU registration audience assignment.

The public BBU signup asks one routing question. Keep the BBU-specific mapping
in this clean-room module while the generic user service only calls the hook
for org 1.
"""
from datetime import datetime

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.courses import Course
from src.db.trail_runs import TrailRun
from src.db.usergroup_resources import UserGroupResource
from src.db.usergroup_user import UserGroupUser
from src.db.usergroups import UserGroup

ORG_ID = 1
AUDIENCE_GROUPS = {
    "family": "Family",
    "professional": "BBU Professionals",
}


async def enroll_usergroup_courses(
    db_session: AsyncSession,
    user_id: int,
    org_id: int,
    usergroup_id: int,
) -> int:
    """Put BBU invite-group courses on the learner's My Learning page."""
    if org_id != ORG_ID or not user_id:
        return 0

    courses = (
        await db_session.execute(
            select(Course)
            .join(
                UserGroupResource,
                UserGroupResource.resource_uuid == Course.course_uuid,
            )
            .where(
                Course.org_id == org_id,
                Course.published == True,  # noqa: E712
                UserGroupResource.usergroup_id == usergroup_id,
            )
        )
    ).scalars().all()
    if not courses:
        return 0

    course_ids = {course.id for course in courses if course.id}
    existing = set(
        (
            await db_session.execute(
                select(TrailRun.course_id).where(
                    TrailRun.user_id == user_id,
                    TrailRun.course_id.in_(course_ids),
                )
            )
        ).scalars().all()
    )
    missing = [course for course in courses if course.id not in existing]
    if not missing:
        return 0

    from src.bbu_migration.router import _ensure_run, _ensure_trail

    trail = await _ensure_trail(db_session, org_id, user_id)
    for course in missing:
        await _ensure_run(db_session, trail, course, user_id)
    return len(missing)


async def assign_registration_audience(
    db_session: AsyncSession,
    user_id: int,
    org_id: int,
    extra_metadata: dict | None,
) -> str:
    """Add a newly-created BBU user to Family or BBU Professionals.

    A missing/unknown answer falls back to Family. The public form requires an
    explicit answer, but the fallback also covers OAuth and older clients.
    """
    if org_id != ORG_ID or not user_id:
        return ""

    requested = str((extra_metadata or {}).get("bbu_audience") or "family")
    audience = requested if requested in AUDIENCE_GROUPS else "family"
    group_name = AUDIENCE_GROUPS[audience]
    group = (
        await db_session.execute(
            select(UserGroup).where(
                UserGroup.org_id == org_id,
                UserGroup.name == group_name,
            )
        )
    ).scalars().first()
    if not group or not group.id:
        return ""

    existing = (
        await db_session.execute(
            select(UserGroupUser).where(
                UserGroupUser.usergroup_id == group.id,
                UserGroupUser.user_id == user_id,
            )
        )
    ).scalars().first()
    if existing:
        return audience

    now = str(datetime.now())
    db_session.add(
        UserGroupUser(
            usergroup_id=group.id,
            user_id=user_id,
            org_id=org_id,
            creation_date=now,
            update_date=now,
        )
    )
    await db_session.commit()
    return audience
