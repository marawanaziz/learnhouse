"""Granting sponsored access, and reporting on who got it.

Deliberately reuses the same primitives the paid path uses — the course access
usergroup and the trail run — so a sponsored learner is indistinguishable from a
paying one everywhere downstream (progress, quizzes, certificates, credentials).
The only difference is that no order and no Stripe object exists.
"""
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.users import User
from src.bbu_sponsors.models import BBUSponsor, BBUSponsoredEnrollment


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_token() -> str:
    return secrets.token_urlsafe(18)


def course_list(s: str) -> list:
    return [c.strip() for c in (s or "").split(",") if c.strip()]


async def seats_used(db: AsyncSession, sponsor: BBUSponsor) -> int:
    rows = (await db.execute(select(BBUSponsoredEnrollment).where(
        BBUSponsoredEnrollment.sponsor_id == sponsor.id))).scalars().all()
    return len({(r.email or "").lower() for r in rows if r.email})


async def has_capacity(db: AsyncSession, sponsor: BBUSponsor) -> bool:
    if not sponsor.seat_limit:
        return True
    return await seats_used(db, sponsor) < sponsor.seat_limit


async def enroll(db: AsyncSession, sponsor: BBUSponsor, email: str,
                 name: str = "", method: str = "bulk", code: str = "") -> dict:
    """Give one person access under this sponsor. Idempotent per (sponsor, email).

    Creates the account if it doesn't exist — a grant recipient shouldn't have to
    sign up first. Returns a per-row result rather than raising, so one bad
    address in a pasted list of 200 doesn't abort the whole batch.
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return {"email": email, "status": "skipped", "reason": "not an email address"}

    existing = (await db.execute(select(BBUSponsoredEnrollment).where(
        BBUSponsoredEnrollment.sponsor_id == sponsor.id,
        BBUSponsoredEnrollment.email == email))).scalars().first()
    if existing:
        return {"email": email, "status": "already_enrolled"}

    if not await has_capacity(db, sponsor):
        return {"email": email, "status": "skipped", "reason": "sponsor seat limit reached"}

    # imported lazily: these live in modules that import heavy routers
    from src.bbu_migration.router import _get_or_create_user, _learner_role_id
    from src.bbu_seats.router import _grant_course_access

    role_id = await _learner_role_id(db)
    was_new = (await db.execute(select(User).where(User.email == email))).scalars().first() is None
    user = await _get_or_create_user(db, sponsor.org_id, role_id, email, name)

    granted = []
    for cu in course_list(sponsor.course_uuids):
        try:
            await _grant_course_access(db, sponsor.org_id, user, cu)
            granted.append(cu)
        except Exception:
            pass

    db.add(BBUSponsoredEnrollment(
        org_id=sponsor.org_id, sponsor_id=sponsor.id or 0, user_id=user.id,
        email=email, name=name or f"{user.first_name} {user.last_name}".strip(),
        course_uuids=",".join(granted), method=method, code=code, enrolled_at=now(),
    ))
    await db.commit()
    return {"email": email, "status": "enrolled", "new_account": was_new,
            "courses": len(granted)}


async def report(db: AsyncSession, org_id: int, sponsor: BBUSponsor) -> dict:
    """Everyone this sponsor covered — new enrollments plus the Circle history.

    A funder does not care that BBU changed platforms mid-grant, so the legacy
    Circle redemptions matched by `legacy_codes` are folded in as the same kind
    of row. Deduplicated by email: one person is one person served, even if they
    claimed several courses.
    """
    rows = (await db.execute(select(BBUSponsoredEnrollment).where(
        BBUSponsoredEnrollment.sponsor_id == sponsor.id))).scalars().all()
    out = [{"email": r.email, "name": r.name, "date": (r.enrolled_at or "")[:10],
            "via": r.method, "source": "platform",
            "courses": len(course_list(r.course_uuids))} for r in rows]

    codes = [c.strip().upper() for c in (sponsor.legacy_codes or "").split(",") if c.strip()]
    if codes:
        from src.bbu_payments.models import BBUCircleRedemption
        legacy = (await db.execute(select(BBUCircleRedemption).where(
            BBUCircleRedemption.org_id == org_id))).scalars().all()
        for r in legacy:
            if (r.code or "").upper() in codes:
                out.append({"email": r.member_email, "name": r.member_name,
                            "date": r.redeemed_on, "via": f"circle:{r.code}",
                            "source": "circle", "courses": 1})

    people = {(r["email"] or "").lower() for r in out if r["email"]}
    return {
        "sponsor": sponsor.name,
        "kind": sponsor.kind,
        "seat_limit": sponsor.seat_limit,
        "rows": sorted(out, key=lambda r: (r["date"] or ""), reverse=True),
        "total_rows": len(out),
        "unique_people": len(people),
        "from_platform": sum(1 for r in out if r["source"] == "platform"),
        "from_circle": sum(1 for r in out if r["source"] == "circle"),
    }
