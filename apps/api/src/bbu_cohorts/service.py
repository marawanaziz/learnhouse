"""BBU cohorts — enrollment / lifecycle logic. Clean-room.

Access is granted via a native usergroup linked to the cohort's course (same
mechanism as course-gating). Completing a cohort calls the credentials engine to
upgrade the member's provisional credential to full.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.usergroups import UserGroup
from src.db.usergroup_user import UserGroupUser
from src.db.usergroup_resources import UserGroupResource
from src.bbu_cohorts.models import BBUCohort, BBUCohortMember


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_usergroup(db: AsyncSession, cohort: BBUCohort) -> int:
    """Create (once) the cohort's access usergroup and link its course to it."""
    if cohort.usergroup_id:
        grp = (await db.execute(select(UserGroup).where(
            UserGroup.id == cohort.usergroup_id))).scalars().first()
        if grp:
            await _ensure_course_link(db, grp.id, cohort)
            return grp.id
    grp = UserGroup(org_id=cohort.org_id, name=f"{cohort.name} · Cohort",
                    description=f"cohort:{cohort.id}",
                    usergroup_uuid=f"usergroup_{uuid4()}",
                    creation_date=_now(), update_date=_now())
    db.add(grp)
    await db.commit()
    await db.refresh(grp)
    cohort.usergroup_id = grp.id
    db.add(cohort)
    await db.commit()
    await _ensure_course_link(db, grp.id, cohort)
    return grp.id


async def _ensure_course_link(db: AsyncSession, usergroup_id: int, cohort: BBUCohort):
    if not cohort.course_uuid:
        return
    link = (await db.execute(select(UserGroupResource).where(
        UserGroupResource.usergroup_id == usergroup_id,
        UserGroupResource.resource_uuid == cohort.course_uuid,
    ))).scalars().first()
    if not link:
        db.add(UserGroupResource(usergroup_id=usergroup_id,
                                 resource_uuid=cohort.course_uuid,
                                 org_id=cohort.org_id,
                                 creation_date=_now(), update_date=_now()))
        await db.commit()


async def _in_group(db: AsyncSession, usergroup_id: int, user_id: int) -> bool:
    row = (await db.execute(select(UserGroupUser).where(
        UserGroupUser.usergroup_id == usergroup_id,
        UserGroupUser.user_id == user_id,
    ))).scalars().first()
    return bool(row)


async def _add_to_group(db: AsyncSession, usergroup_id: int, org_id: int, user_id: int):
    if not await _in_group(db, usergroup_id, user_id):
        db.add(UserGroupUser(usergroup_id=usergroup_id, user_id=user_id,
                             org_id=org_id, creation_date=_now(), update_date=_now()))
        await db.commit()


async def _remove_from_group(db: AsyncSession, usergroup_id: int, user_id: int):
    row = (await db.execute(select(UserGroupUser).where(
        UserGroupUser.usergroup_id == usergroup_id,
        UserGroupUser.user_id == user_id,
    ))).scalars().first()
    if row:
        await db.delete(row)
        await db.commit()


async def active_count(db: AsyncSession, cohort_id: int) -> int:
    rows = (await db.execute(select(BBUCohortMember).where(
        BBUCohortMember.cohort_id == cohort_id,
        BBUCohortMember.status == "active",
    ))).scalars().all()
    return len(rows)


async def _member(db: AsyncSession, cohort_id: int, user_id: int):
    return (await db.execute(select(BBUCohortMember).where(
        BBUCohortMember.cohort_id == cohort_id,
        BBUCohortMember.user_id == user_id,
    ))).scalars().first()


async def enroll(db: AsyncSession, cohort: BBUCohort, user_id: int) -> dict:
    """Add a user to the cohort. Honors capacity → waitlist. Grants course access
    for active members. Idempotent."""
    await ensure_usergroup(db, cohort)
    m = await _member(db, cohort.id, user_id)
    at_capacity = cohort.capacity and (await active_count(db, cohort.id)) >= cohort.capacity
    if m and m.status in ("active", "completed"):
        return {"status": m.status, "already": True}
    target = "waitlisted" if at_capacity else "active"
    if m:
        m.status = target
        m.joined_at = m.joined_at or _now()
    else:
        m = BBUCohortMember(org_id=cohort.org_id, cohort_id=cohort.id or 0,
                            user_id=user_id, status=target, joined_at=_now())
    db.add(m)
    await db.commit()
    if target == "active":
        await _add_to_group(db, cohort.usergroup_id, cohort.org_id, user_id)
    else:
        # mark cohort full when we start waitlisting
        if cohort.status == "open":
            cohort.status = "full"
            db.add(cohort)
            await db.commit()
    return {"status": target, "already": False}


async def complete(db: AsyncSession, cohort: BBUCohort, user_id: int) -> dict:
    """Mark a member completed and upgrade their credential (mentorship trigger)."""
    m = await _member(db, cohort.id, user_id)
    if not m:
        return {"error": "not a member"}
    m.status = "completed"
    m.completed_at = _now()
    db.add(m)
    await db.commit()
    upgraded = []
    if cohort.credential_type:  # this cohort grants a credential upgrade
        try:
            from src.bbu_credentials import service as cred_svc
            ctype = "" if cohort.credential_type == "both" else cohort.credential_type
            # BBU rule: the 3-yr full cert is effective-dated to the cohort's LAST
            # DAY, not the day the admin marks completion.
            ups = await cred_svc.on_mentorship_completion(
                db, cohort.org_id, user_id, credential_type=ctype,
                cohort_ref=f"cohort:{cohort.id}",
                effective_at=(cohort.end_date or None))
            upgraded = [c.credential_type for c in ups]
        except Exception:
            import traceback
            print(f"[BBU] cohort complete credential upgrade failed:\n{traceback.format_exc()[-500:]}", flush=True)
    return {"completed": True, "credentials_upgraded": upgraded}


async def remove(db: AsyncSession, cohort: BBUCohort, user_id: int) -> dict:
    """Remove a member before completion → revoke access (blocks their cert)."""
    m = await _member(db, cohort.id, user_id)
    if not m:
        return {"error": "not a member"}
    m.status = "removed"
    db.add(m)
    await db.commit()
    if cohort.usergroup_id:
        await _remove_from_group(db, cohort.usergroup_id, user_id)
    # promote the next waitlisted member if there's now room
    await promote_waitlist(db, cohort)
    return {"removed": True}


async def promote_waitlist(db: AsyncSession, cohort: BBUCohort):
    if not cohort.capacity:
        return
    while (await active_count(db, cohort.id)) < cohort.capacity:
        nxt = (await db.execute(select(BBUCohortMember).where(
            BBUCohortMember.cohort_id == cohort.id,
            BBUCohortMember.status == "waitlisted",
        ).order_by(BBUCohortMember.id))).scalars().first()
        if not nxt:
            break
        nxt.status = "active"
        db.add(nxt)
        await db.commit()
        await _add_to_group(db, cohort.usergroup_id, cohort.org_id, nxt.user_id)


async def close(db: AsyncSession, cohort: BBUCohort, revoke_access: bool = True) -> dict:
    """Close the cohort: status=closed; optionally revoke all members' access."""
    cohort.status = "closed"
    cohort.updated_at = _now()
    db.add(cohort)
    await db.commit()
    revoked = 0
    if revoke_access and cohort.usergroup_id:
        members = (await db.execute(select(UserGroupUser).where(
            UserGroupUser.usergroup_id == cohort.usergroup_id))).scalars().all()
        for row in members:
            await db.delete(row)
            revoked += 1
        await db.commit()
    return {"closed": True, "access_revoked": revoked}


async def resolve_target_cohort(db: AsyncSession, org_id: int, cohort_id=None, program: str = ""):
    """Pick the cohort a purchase should enroll into: a specific cohort_id if the
    product pins one, otherwise the NEXT open cohort of the program (earliest
    start date, status open/full — full still enrolls to its waitlist)."""
    if cohort_id:
        return (await db.execute(select(BBUCohort).where(
            BBUCohort.id == int(cohort_id), BBUCohort.org_id == org_id))).scalars().first()
    if program:
        rows = (await db.execute(select(BBUCohort).where(
            BBUCohort.org_id == org_id, BBUCohort.program == program,
            BBUCohort.status.in_(["open", "full"]))
        )).scalars().all()
        # earliest upcoming start date first ("" sorts last)
        rows.sort(key=lambda c: (c.start_date or "9999", c.id))
        return rows[0] if rows else None
    return None


async def enroll_from_product(db: AsyncSession, org_id: int, user_id: int,
                              cohort_id=None, program: str = "") -> dict:
    """Called on a paid mentorship purchase: enroll the buyer into the resolved
    cohort (waitlists if full). Fail-soft return so it never breaks fulfillment."""
    cohort = await resolve_target_cohort(db, org_id, cohort_id, program)
    if not cohort:
        return {"enrolled": False, "reason": "no open cohort for program", "program": program}
    res = await enroll(db, cohort, user_id)
    return {"enrolled": True, "cohort_id": cohort.id, "cohort": cohort.name, **res}


async def roster(db: AsyncSession, cohort_id: int) -> list:
    return (await db.execute(select(BBUCohortMember).where(
        BBUCohortMember.cohort_id == cohort_id).order_by(BBUCohortMember.id))).scalars().all()
