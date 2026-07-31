"""Admin roster operations keep mentorship access and member data in sync."""

import pytest
from sqlalchemy import select

from src.bbu_cohorts import service as cohort_svc
from src.bbu_cohorts.models import BBUCohort, BBUCohortMember
from src.db.usergroup_user import UserGroupUser
from src.db.users import User


async def _cohort(db, org, name: str, *, capacity: int = 0) -> BBUCohort:
    cohort = BBUCohort(
        org_id=org.id,
        name=name,
        program="doula",
        course_uuid=f"course_{name.lower().replace(' ', '_')}",
        capacity=capacity,
        status="open",
    )
    db.add(cohort)
    await db.commit()
    await db.refresh(cohort)
    return cohort


@pytest.mark.asyncio
async def test_transfer_moves_roster_membership_and_course_access(
    db, org, regular_user
):
    source = await _cohort(db, org, "August")
    target = await _cohort(db, org, "October")
    await cohort_svc.enroll(db, source, regular_user.id)

    result = await cohort_svc.transfer(
        db, source, target, regular_user.id
    )

    source_member = (
        await db.execute(
            select(BBUCohortMember).where(
                BBUCohortMember.cohort_id == source.id,
                BBUCohortMember.user_id == regular_user.id,
            )
        )
    ).scalars().one()
    target_member = (
        await db.execute(
            select(BBUCohortMember).where(
                BBUCohortMember.cohort_id == target.id,
                BBUCohortMember.user_id == regular_user.id,
            )
        )
    ).scalars().one()
    group_rows = (
        await db.execute(
            select(UserGroupUser).where(UserGroupUser.user_id == regular_user.id)
        )
    ).scalars().all()

    assert result == {
        "transferred": True,
        "source_cohort_id": source.id,
        "target_cohort_id": target.id,
        "status": "active",
    }
    assert source_member.status == "removed"
    assert target_member.status == "active"
    assert {row.usergroup_id for row in group_rows} == {target.usergroup_id}


@pytest.mark.asyncio
async def test_transfer_to_full_cohort_keeps_existing_membership(
    db, org, regular_user, admin_user
):
    source = await _cohort(db, org, "Current")
    target = await _cohort(db, org, "Full", capacity=1)
    await cohort_svc.enroll(db, source, regular_user.id)
    await cohort_svc.enroll(db, target, admin_user.id)

    result = await cohort_svc.transfer(
        db, source, target, regular_user.id
    )

    source_member = await cohort_svc._member(db, source.id, regular_user.id)
    target_member = await cohort_svc._member(db, target.id, regular_user.id)
    assert result == {"error": "target cohort is full"}
    assert source_member.status == "active"
    assert target_member is None


@pytest.mark.asyncio
async def test_roster_email_correction_rejects_duplicates(
    db, org, regular_user, admin_user
):
    cohort = await _cohort(db, org, "Email Fix")
    await cohort_svc.enroll(db, cohort, regular_user.id)

    changed = await cohort_svc.change_member_email(
        db, cohort, regular_user.id, " Updated.Member@Example.com "
    )

    assert changed == {
        "updated": True,
        "user_id": regular_user.id,
        "email": "updated.member@example.com",
    }
    stored_user = (
        await db.execute(select(User).where(User.id == regular_user.id))
    ).scalars().one()
    assert stored_user.email == "updated.member@example.com"

    duplicate = await cohort_svc.change_member_email(
        db, cohort, regular_user.id, admin_user.email
    )
    assert duplicate == {"error": "email is already used by another account"}
