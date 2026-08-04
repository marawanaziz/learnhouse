"""Idempotent participant emails for BBU mentorship cohorts."""

import asyncio
import html
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from src.bbu_cohorts.models import (
    BBUCohort,
    BBUCohortMember,
    BBUCohortNotification,
)
from src.db.users import User


EVENT_WELCOME = "welcome"
EVENT_REMINDER_7D = "reminder_7d"
EVENT_REMINDER_1D = "reminder_1d"
EVENT_START = "start"
EVENTS = {EVENT_WELCOME, EVENT_REMINDER_7D, EVENT_REMINDER_1D, EVENT_START}
_COHORT_TIMEZONE = ZoneInfo("America/Chicago")
_STALE_CLAIM_AFTER = timedelta(minutes=15)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date(raw: str) -> date | None:
    try:
        return date.fromisoformat((raw or "")[:10])
    except (TypeError, ValueError):
        return None


def _pretty_date(raw: str) -> str:
    parsed = _date(raw)
    return parsed.strftime("%B %d, %Y").replace(" 0", " ") if parsed else "the scheduled date"


def _message(cohort: BBUCohort, user: User, event: str) -> tuple[str, str]:
    name = html.escape((user.first_name or "").strip() or "there")
    cohort_name = html.escape(cohort.name or "your mentorship cohort")
    start_text = _pretty_date(cohort.start_date)
    start = html.escape(start_text)

    subjects = {
        EVENT_WELCOME: f"Welcome to {cohort.name}",
        EVENT_REMINDER_7D: f"Your mentorship starts {start_text}",
        EVENT_REMINDER_1D: f"Tomorrow: {cohort.name}",
        EVENT_START: f"{cohort.name} starts today",
    }
    intros = {
        EVENT_WELCOME: f"You are officially enrolled in <strong>{cohort_name}</strong>, beginning {start}.",
        EVENT_REMINDER_7D: f"This is a friendly reminder that <strong>{cohort_name}</strong> begins {start}.",
        EVENT_REMINDER_1D: f"<strong>{cohort_name}</strong> begins tomorrow. We are excited to see you.",
        EVENT_START: f"<strong>{cohort_name}</strong> begins today. We are excited to get started with you.",
    }

    resources = []
    if (cohort.zoom_link or "").strip():
        link = html.escape(cohort.zoom_link.strip(), quote=True)
        resources.append(f'<p><a href="{link}">Join the mentorship session</a></p>')
    elif (cohort.zoom_meeting_id or "").strip():
        resources.append(
            "<p>Your Zoom registration is connected to this email address. "
            "Please keep the personal joining details sent by Zoom.</p>"
        )
    if (cohort.workbook_url or "").strip():
        link = html.escape(cohort.workbook_url.strip(), quote=True)
        resources.append(f'<p><a href="{link}">Open your mentorship workbook</a></p>')

    platform = "https://learn.birthandbabyuniversity.com"
    body = (
        f"<p>Hi {name},</p>"
        f"<p>{intros[event]}</p>"
        f"{''.join(resources)}"
        f'<p>You can also visit <a href="{platform}">Birth and Baby University</a> '
        "for your mentorship resources and community.</p>"
        "<p>If you have any questions or cannot find your meeting details, please reply to this email.</p>"
        "<p>Warmly,<br>Birth and Baby University</p>"
    )
    return subjects[event], body


async def _get_or_claim(
    db: AsyncSession,
    cohort: BBUCohort,
    user_id: int,
    event: str,
    scheduled_for: str,
) -> BBUCohortNotification | None:
    row = (await db.execute(select(BBUCohortNotification).where(
        BBUCohortNotification.cohort_id == cohort.id,
        BBUCohortNotification.user_id == user_id,
        BBUCohortNotification.event == event,
    ).with_for_update())).scalars().first()
    if row and row.status == "sent":
        return None
    if row and row.status == "sending":
        try:
            claimed_at = datetime.fromisoformat(row.last_attempt_at)
            if claimed_at.tzinfo is None:
                claimed_at = claimed_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - claimed_at < _STALE_CLAIM_AFTER:
                return None
        except (TypeError, ValueError):
            pass
    if not row:
        row = BBUCohortNotification(
            org_id=cohort.org_id,
            cohort_id=cohort.id or 0,
            user_id=user_id,
            event=event,
            scheduled_for=scheduled_for,
        )
    row.status = "sending"
    row.attempts = (row.attempts or 0) + 1
    row.last_attempt_at = _now()
    row.error = ""
    db.add(row)
    try:
        await db.commit()
        await db.refresh(row)
        return row
    except IntegrityError:
        await db.rollback()
        return None


async def send_event(
    db: AsyncSession,
    cohort: BBUCohort,
    user_id: int,
    event: str,
    scheduled_for: str = "",
) -> dict:
    if event not in EVENTS:
        return {"event": event, "status": "invalid"}
    user = (await db.execute(select(User).where(User.id == user_id))).scalars().first()
    if not user or not getattr(user, "email", ""):
        return {"event": event, "status": "skipped", "reason": "user has no email"}
    record = await _get_or_claim(db, cohort, user_id, event, scheduled_for)
    if not record:
        return {"event": event, "status": "already_handled"}

    subject, body = _message(cohort, user, event)
    try:
        from src.services.email.utils import send_email
        result = await asyncio.to_thread(send_email, user.email, subject, body)
        message_id = ""
        if isinstance(result, dict):
            message_id = str(result.get("id") or result.get("messageId") or "")
        record.status = "sent"
        record.sent_at = _now()
        record.provider_message_id = message_id[:160]
        record.error = ""
    except Exception as exc:
        record.status = "failed"
        record.error = str(exc)[:1000]
    db.add(record)
    await db.commit()
    return {"event": event, "status": record.status, "attempts": record.attempts}


def _due_events(cohort: BBUCohort, member: BBUCohortMember, today: date) -> list[tuple[str, date]]:
    start = _date(cohort.start_date)
    joined = _date(member.joined_at)
    if not start:
        return [(EVENT_WELCOME, today)] if joined == today else []

    events: list[tuple[str, date]] = []
    if joined == today and today < start:
        events.append((EVENT_WELCOME, today))

    seven_day = start - timedelta(days=7)
    if joined and joined <= seven_day and seven_day <= today < start - timedelta(days=1):
        events.append((EVENT_REMINDER_7D, seven_day))
    if today == start - timedelta(days=1):
        events.append((EVENT_REMINDER_1D, start - timedelta(days=1)))
    if today == start:
        events.append((EVENT_START, start))
    return events


async def run_due(db: AsyncSession, org_id: int = 1, dry: bool = False) -> dict:
    # Cohort dates are Chicago-local calendar dates. UTC would send date-based
    # reminders the prior evening for this organization.
    today = datetime.now(_COHORT_TIMEZONE).date()
    cohorts = (await db.execute(select(BBUCohort).where(
        BBUCohort.org_id == org_id,
        BBUCohort.status != "closed",
    ))).scalars().all()
    due = []
    for cohort in cohorts:
        members = (await db.execute(select(BBUCohortMember).where(
            BBUCohortMember.cohort_id == cohort.id,
            BBUCohortMember.status == "active",
        ))).scalars().all()
        for member in members:
            for event, scheduled in _due_events(cohort, member, today):
                existing = (await db.execute(select(BBUCohortNotification).where(
                    BBUCohortNotification.cohort_id == cohort.id,
                    BBUCohortNotification.user_id == member.user_id,
                    BBUCohortNotification.event == event,
                    BBUCohortNotification.status == "sent",
                ))).scalars().first()
                if not existing:
                    due.append((cohort, member, event, scheduled))

    if dry:
        return {
            "dry": True,
            "due": [
                {
                    "cohort_id": cohort.id,
                    "user_id": member.user_id,
                    "event": event,
                    "scheduled_for": scheduled.isoformat(),
                }
                for cohort, member, event, scheduled in due
            ],
            "due_count": len(due),
        }

    results = []
    for cohort, member, event, scheduled in due:
        results.append(await send_event(
            db, cohort, member.user_id, event, scheduled.isoformat()
        ))
    return {
        "dry": False,
        "processed": len(results),
        "sent": sum(1 for result in results if result.get("status") == "sent"),
        "failed": sum(1 for result in results if result.get("status") == "failed"),
        "results": results,
    }
