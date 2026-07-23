"""BBU credentials — admin + hook API (admin-key gated).
Mounted at /api/v1/bbu/credentials."""
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.users import User
from src.db.courses.courses import Course
from src.db.courses.certifications import Certifications
from src.bbu_credentials.models import BBUCredential, BBUCeuLedger
from src.bbu_credentials import service as svc

router = APIRouter()
ADMIN_KEY = os.environ.get("BBU_MIGRATION_KEY") or os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")

# Reminder cadence (days before expiry) — the scheduled reminder job fires here.
REMINDER_DAYS = [180, 90, 60, 45, 30]


def _check(request: Request):
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key", "")
    if not ADMIN_KEY or key != ADMIN_KEY:
        raise HTTPException(403, "Forbidden")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _user_by_email(db: AsyncSession, email: str) -> User:
    u = (await db.execute(select(User).where(
        User.email == (email or "").strip().lower()))).scalars().first()
    if not u:
        raise HTTPException(404, "User not found")
    return u


@router.get("")
async def list_credentials(request: Request, org_id: int = 1, status: str = "",
                           db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    q = select(BBUCredential).where(BBUCredential.org_id == org_id)
    rows = (await db_session.execute(q)).scalars().all()
    out = []
    for c in rows:
        eff = svc.compute_effective_status(c)
        if status and eff != status:
            continue
        total = await svc.approved_ceu_total(db_session, org_id, c.user_id)
        out.append(svc.to_dict(c, total))
    return out


@router.get("/user")
async def user_credentials(request: Request, email: str, org_id: int = 1,
                           db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    u = await _user_by_email(db_session, email)
    creds = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id, BBUCredential.user_id == u.id))).scalars().all()
    total = await svc.approved_ceu_total(db_session, org_id, u.id)
    ledger = (await db_session.execute(select(BBUCeuLedger).where(
        BBUCeuLedger.org_id == org_id, BBUCeuLedger.user_id == u.id))).scalars().all()
    return {
        "email": u.email,
        "ceu_total": total,
        "credentials": [svc.to_dict(c, total) for c in creds],
        "ledger": [{"id": r.id, "ceu": r.ceu_count, "source": r.source,
                    "ref": r.source_ref, "approved": r.approved,
                    "submitted_at": r.submitted_at} for r in ledger],
    }


@router.post("/issue")
async def issue(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Manual issue. Body: {email, credential_type, mode: provisional|full, org_id?}"""
    _check(request)
    b = await request.json()
    u = await _user_by_email(db_session, b.get("email", ""))
    org_id = int(b.get("org_id", 1))
    ctype = (b.get("credential_type") or "birth").strip().lower()
    mode = (b.get("mode") or "provisional").strip().lower()
    if mode == "full":
        c = await svc.issue_full_direct(db_session, org_id, u.id, ctype,
                                        source="manual", source_ref=b.get("note", ""))
    else:
        c = await svc.issue_provisional(db_session, org_id, u.id, ctype,
                                        source_ref=b.get("note", ""))
    total = await svc.approved_ceu_total(db_session, org_id, u.id)
    return svc.to_dict(c, total)


@router.post("/award-ceu")
async def award_ceu(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Body: {email, count, source?, source_ref?, approved?, org_id?}"""
    _check(request)
    b = await request.json()
    u = await _user_by_email(db_session, b.get("email", ""))
    org_id = int(b.get("org_id", 1))
    row = await svc.award_ceu(db_session, org_id, u.id, int(b.get("count", 0)),
                              source=b.get("source", "manual"),
                              source_ref=b.get("source_ref", ""),
                              approved=bool(b.get("approved", True)))
    total = await svc.approved_ceu_total(db_session, org_id, u.id)
    return {"ledger_id": row.id, "ceu_total": total}


@router.post("/approve-ceu")
async def approve_ceu(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Approve a pending external CEU. Body: {ledger_id, org_id?}"""
    _check(request)
    b = await request.json()
    row = (await db_session.execute(select(BBUCeuLedger).where(
        BBUCeuLedger.id == int(b.get("ledger_id", 0))))).scalars().first()
    if not row:
        raise HTTPException(404, "Ledger entry not found")
    row.approved = True
    row.approved_at = _now()
    db_session.add(row)
    await db_session.commit()
    await svc.maybe_upgrade_on_ceu(db_session, row.org_id, row.user_id)
    total = await svc.approved_ceu_total(db_session, row.org_id, row.user_id)
    return {"approved": True, "ceu_total": total}


@router.post("/renew")
async def renew(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Body: {email, credential_type, org_id?}"""
    _check(request)
    b = await request.json()
    u = await _user_by_email(db_session, b.get("email", ""))
    org_id = int(b.get("org_id", 1))
    ctype = (b.get("credential_type") or "birth").strip().lower()
    cred = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id, BBUCredential.user_id == u.id,
        BBUCredential.credential_type == ctype))).scalars().first()
    if not cred:
        raise HTTPException(404, "Credential not found")
    ok, reason = await svc.renew(db_session, cred)
    total = await svc.approved_ceu_total(db_session, org_id, u.id)
    return {"renewed": ok, "reason": reason, **svc.to_dict(cred, total)}


@router.post("/on-course-complete")
async def on_course_complete(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Course-completion hook. Body: {email, course_uuid, org_id?}. Reads the
    course's certification config to decide issue/CEU/cross-cert."""
    _check(request)
    b = await request.json()
    u = await _user_by_email(db_session, b.get("email", ""))
    org_id = int(b.get("org_id", 1))
    cu = (b.get("course_uuid") or "").strip()
    course = (await db_session.execute(select(Course).where(
        Course.course_uuid == cu))).scalars().first()
    if not course:
        raise HTTPException(404, "Course not found")
    cert = (await db_session.execute(select(Certifications).where(
        Certifications.course_id == course.id))).scalars().first()
    cfg = (cert.config if cert else {}) or {}
    result = await svc.on_course_complete(db_session, org_id, u.id, cu, cfg)
    return result


@router.put("/{credential_id}/directory")
async def set_directory(credential_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    b = await request.json()
    c = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.id == credential_id))).scalars().first()
    if not c:
        raise HTTPException(404, "Credential not found")
    c.directory_opt_in = bool(b.get("opt_in", True))
    c.updated_at = _now()
    db_session.add(c)
    await db_session.commit()
    return {"id": c.id, "directory_opt_in": c.directory_opt_in}


@router.post("/refresh-statuses")
async def refresh_statuses(request: Request, org_id: int = 1,
                           db_session: AsyncSession = Depends(get_db_session)):
    """Recompute stored status for all credentials (lapse/expire the overdue)."""
    _check(request)
    rows = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id))).scalars().all()
    changed = 0
    for c in rows:
        eff = svc.compute_effective_status(c)
        if eff != c.status:
            c.status = eff
            c.updated_at = _now()
            db_session.add(c)
            changed += 1
    if changed:
        await db_session.commit()
    return {"checked": len(rows), "changed": changed}


@router.get("/reminders/due")
async def reminders_due(request: Request, org_id: int = 1,
                        db_session: AsyncSession = Depends(get_db_session)):
    """Which credentials fall within a reminder window (days-to-expiry near a
    REMINDER_DAYS mark, ±3 days). The scheduled job reads this then emails via
    GHL/SMTP. Read-only — safe to call from cron without side effects."""
    _check(request)
    now = svc._now_dt()
    rows = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id))).scalars().all()
    due = []
    for c in rows:
        eff = svc.compute_effective_status(c)
        exp = svc._parse(c.full_expires_at if eff == "full" else c.provisional_expires_at)
        if not exp or eff in ("lapsed", "expired"):
            continue
        days = (exp - now).days
        for mark in REMINDER_DAYS:
            if abs(days - mark) <= 3:
                due.append({"credential_id": c.id, "user_id": c.user_id,
                            "credential_type": c.credential_type, "status": eff,
                            "days_to_expiry": days, "mark": mark})
                break
    return {"count": len(due), "due": due}
