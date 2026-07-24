"""BBU cohorts — admin API (admin-key gated). Mounted at /api/v1/bbu/cohorts."""
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.users import User
from src.bbu_cohorts.models import BBUCohort, BBUCohortMember
from src.bbu_cohorts import service as svc

router = APIRouter()
ADMIN_KEY = os.environ.get("BBU_MIGRATION_KEY") or os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")


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


def _cohort_dict(c: BBUCohort, active: int = None) -> dict:
    d = {
        "id": c.id, "name": c.name, "program": c.program,
        "course_uuid": c.course_uuid, "community_id": c.community_id,
        "usergroup_id": c.usergroup_id, "start_date": c.start_date,
        "end_date": c.end_date, "capacity": c.capacity, "status": c.status,
        "access_months": c.access_months, "zoom_link": c.zoom_link,
        "workbook_url": c.workbook_url, "credential_type": c.credential_type,
        "recordings": [r for r in (c.recordings or "").split("\n") if r],
        "access_until": svc.access_until(c),
    }
    if active is not None:
        d["active_members"] = active
    return d


@router.get("")
async def list_cohorts(request: Request, org_id: int = 1, db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    rows = (await db_session.execute(select(BBUCohort).where(
        BBUCohort.org_id == org_id).order_by(BBUCohort.id.desc()))).scalars().all()
    out = []
    for c in rows:
        out.append(_cohort_dict(c, await svc.active_count(db_session, c.id)))
    return out


@router.post("")
async def create_cohort(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    b = await request.json()
    program = b.get("program", "doula")
    c = BBUCohort(
        org_id=int(b.get("org_id", 1)), name=b.get("name", "Untitled Cohort"),
        program=program, course_uuid=(b.get("course_uuid") or "").strip(),
        community_id=b.get("community_id"),
        start_date=b.get("start_date", ""), end_date=b.get("end_date", ""),
        capacity=int(b.get("capacity", 0) or 0), status=b.get("status", "open"),
        access_months=int(b.get("access_months", 12 if program == "agency" else 6)),
        zoom_link=b.get("zoom_link", ""), workbook_url=b.get("workbook_url", ""),
        credential_type=(b.get("credential_type") or "").strip().lower(),
        created_at=_now(), updated_at=_now())
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    if c.course_uuid:
        await svc.ensure_usergroup(db_session, c)
        await db_session.refresh(c)
    return _cohort_dict(c, 0)


@router.get("/{cohort_id}")
async def get_cohort(cohort_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    c = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == cohort_id))).scalars().first()
    if not c:
        raise HTTPException(404, "Cohort not found")
    members = await svc.roster(db_session, cohort_id)
    # hydrate emails/names
    uids = [m.user_id for m in members]
    users = {}
    if uids:
        rows = (await db_session.execute(select(User).where(User.id.in_(uids)))).scalars().all()
        users = {u.id: u for u in rows}
    roster = [{
        "user_id": m.user_id,
        "email": getattr(users.get(m.user_id), "email", ""),
        "name": f"{getattr(users.get(m.user_id), 'first_name', '')} {getattr(users.get(m.user_id), 'last_name', '')}".strip(),
        "status": m.status, "joined_at": m.joined_at, "completed_at": m.completed_at,
    } for m in members]
    d = _cohort_dict(c, sum(1 for m in members if m.status == "active"))
    d["roster"] = roster
    return d


@router.put("/{cohort_id}")
async def update_cohort(cohort_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    c = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == cohort_id))).scalars().first()
    if not c:
        raise HTTPException(404, "Cohort not found")
    b = await request.json()
    for f in ("name", "program", "start_date", "end_date", "status", "zoom_link",
              "workbook_url", "credential_type", "course_uuid"):
        if f in b:
            setattr(c, f, b[f])
    if "capacity" in b:
        c.capacity = int(b["capacity"] or 0)
    if "access_months" in b:
        c.access_months = int(b["access_months"] or 0)
    if "add_recording" in b and b["add_recording"]:
        recs = [r for r in (c.recordings or "").split("\n") if r]
        recs.append(str(b["add_recording"]))
        c.recordings = "\n".join(recs)
    c.updated_at = _now()
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    if c.course_uuid and not c.usergroup_id:
        await svc.ensure_usergroup(db_session, c)
    return _cohort_dict(c, await svc.active_count(db_session, c.id))


@router.post("/{cohort_id}/enroll")
async def enroll_member(cohort_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    c = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == cohort_id))).scalars().first()
    if not c:
        raise HTTPException(404, "Cohort not found")
    b = await request.json()
    u = await _user_by_email(db_session, b.get("email", ""))
    return await svc.enroll(db_session, c, u.id)


@router.post("/{cohort_id}/complete")
async def complete_member(cohort_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    c = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == cohort_id))).scalars().first()
    if not c:
        raise HTTPException(404, "Cohort not found")
    b = await request.json()
    u = await _user_by_email(db_session, b.get("email", ""))
    return await svc.complete(db_session, c, u.id)


@router.post("/{cohort_id}/remove")
async def remove_member(cohort_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    c = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == cohort_id))).scalars().first()
    if not c:
        raise HTTPException(404, "Cohort not found")
    b = await request.json()
    u = await _user_by_email(db_session, b.get("email", ""))
    return await svc.remove(db_session, c, u.id)


@router.delete("/{cohort_id}")
async def delete_cohort(cohort_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    c = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == cohort_id))).scalars().first()
    if not c:
        raise HTTPException(404, "Cohort not found")
    # revoke access + drop member rows, then the cohort itself
    await svc.close(db_session, c, revoke_access=True)
    members = await svc.roster(db_session, cohort_id)
    for m in members:
        await db_session.delete(m)
    await db_session.delete(c)
    await db_session.commit()
    return {"deleted": cohort_id, "members_removed": len(members)}


@router.post("/run-lifecycle")
async def run_lifecycle(request: Request, org_id: int = 1, dry_run: bool = True,
                        db_session: AsyncSession = Depends(get_db_session)):
    """Manual trigger for the same job the daily scheduler runs: flip started
    cohorts to 'running' and close cohorts past their access window. dry_run
    defaults True — preview what would change."""
    _check(request)
    return await svc.run_lifecycle(db_session, org_id=org_id, dry=dry_run)


@router.post("/{cohort_id}/close")
async def close_cohort(cohort_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    c = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == cohort_id))).scalars().first()
    if not c:
        raise HTTPException(404, "Cohort not found")
    b = await request.json()
    return await svc.close(db_session, c, revoke_access=bool(b.get("revoke_access", True)))
