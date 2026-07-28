"""BBU registration audience assignment.

The public BBU signup asks one routing question. Keep the BBU-specific mapping
in this clean-room module while the generic user service only calls the hook
for org 1.
"""
from datetime import datetime

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.usergroup_user import UserGroupUser
from src.db.usergroups import UserGroup

ORG_ID = 1
AUDIENCE_GROUPS = {
    "family": "Family",
    "professional": "BBU Professionals",
}


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
