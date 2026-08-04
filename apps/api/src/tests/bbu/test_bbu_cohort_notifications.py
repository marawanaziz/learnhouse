"""Mentorship roster access and participant email automation."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from src.bbu_cohorts import notifications
from src.bbu_cohorts import service as cohort_svc
from src.bbu_cohorts.models import (
    BBUCohort,
    BBUCohortMember,
    BBUCohortNotification,
)
from src.db.usergroup_user import UserGroupUser


async def _cohort(db, org, *, starts_in: int = 7) -> BBUCohort:
    today = datetime.now(ZoneInfo("America/Chicago")).date()
    cohort = BBUCohort(
        org_id=org.id,
        name="August Doula Mentorship",
        program="doula",
        course_uuid="course_mentorship",
        start_date=(today + timedelta(days=starts_in)).isoformat(),
        end_date=(today + timedelta(days=starts_in + 42)).isoformat(),
        status="open",
    )
    db.add(cohort)
    await db.commit()
    await db.refresh(cohort)
    return cohort


@pytest.mark.asyncio
async def test_reconcile_access_group_removes_non_roster_member(
    db, org, regular_user, admin_user
):
    cohort = await _cohort(db, org)
    await cohort_svc.enroll(db, cohort, regular_user.id)
    db.add(UserGroupUser(
        usergroup_id=cohort.usergroup_id,
        user_id=admin_user.id,
        org_id=org.id,
        creation_date="",
        update_date="",
    ))
    await db.commit()

    result = await cohort_svc.reconcile_access_group(db, cohort)

    rows = (await db.execute(select(UserGroupUser).where(
        UserGroupUser.usergroup_id == cohort.usergroup_id,
    ))).scalars().all()
    assert result == {"cohort_id": cohort.id, "official": 1, "added": 0, "removed": 1}
    assert {row.user_id for row in rows} == {regular_user.id}


@pytest.mark.asyncio
async def test_due_reminder_sends_once_and_records_delivery(
    db, org, regular_user, monkeypatch
):
    cohort = await _cohort(db, org, starts_in=7)
    await cohort_svc.ensure_usergroup(db, cohort)
    db.add(BBUCohortMember(
        org_id=org.id,
        cohort_id=cohort.id,
        user_id=regular_user.id,
        status="active",
        joined_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
    ))
    await db.commit()

    sent = []
    monkeypatch.setattr(
        "src.services.email.utils.send_email",
        lambda to, subject, body: sent.append((str(to), subject, body)) or {"id": "message-1"},
    )

    first = await notifications.run_due(db, org_id=org.id, dry=False)
    second = await notifications.run_due(db, org_id=org.id, dry=False)

    ledger = (await db.execute(select(BBUCohortNotification))).scalars().all()
    assert first["sent"] == 1
    assert second["sent"] == 0
    assert len(sent) == 1
    assert ledger[0].event == notifications.EVENT_REMINDER_7D
    assert ledger[0].status == "sent"
    assert ledger[0].provider_message_id == "message-1"


@pytest.mark.asyncio
async def test_failed_notification_retries_without_duplicate_sent_event(
    db, org, regular_user, monkeypatch
):
    cohort = await _cohort(db, org, starts_in=7)
    await cohort_svc.ensure_usergroup(db, cohort)
    db.add(BBUCohortMember(
        org_id=org.id,
        cohort_id=cohort.id,
        user_id=regular_user.id,
        status="active",
        joined_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
    ))
    await db.commit()

    attempts = []

    def flaky(*args):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("temporary provider failure")
        return {"id": "message-2"}

    monkeypatch.setattr("src.services.email.utils.send_email", flaky)
    first = await notifications.run_due(db, org_id=org.id, dry=False)
    second = await notifications.run_due(db, org_id=org.id, dry=False)
    third = await notifications.run_due(db, org_id=org.id, dry=False)

    ledger = (await db.execute(select(BBUCohortNotification))).scalars().one()
    assert first["failed"] == 1
    assert second["sent"] == 1
    assert third["processed"] == 0
    assert len(attempts) == 2
    assert ledger.status == "sent"
    assert ledger.attempts == 2
