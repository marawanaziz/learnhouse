"""BBU reseller / bulk seat codes — API. Mounted at /api/v1/bbu/seats.

- generate/list/void: admin-key gated (agency owner or BBU admin).
- redeem: the authenticated redeemer, OR admin-key + email (assisted redemption).
"""
import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.security.auth import get_current_user
from src.db.users import User
from src.db.usergroups import UserGroup
from src.db.usergroup_user import UserGroupUser
from src.bbu_seats.models import BBUSeatCode

router = APIRouter()
ADMIN_KEY = os.environ.get("BBU_MIGRATION_KEY") or os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")
_ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous 0/O/1/I


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_admin(request: Request) -> bool:
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key", "")
    return bool(ADMIN_KEY) and key == ADMIN_KEY


def _require_admin(request: Request):
    if not _is_admin(request):
        raise HTTPException(403, "Forbidden")


def _gen_code(prefix: str = "BBU") -> str:
    body = "".join(secrets.choice(_ALPHA) for _ in range(10))
    return f"{prefix}-{body[:5]}-{body[5:]}"


async def _grant_course_access(db: AsyncSession, org_id: int, user: User, course_uuid: str):
    """Add the user to the course's access usergroup (description==course_uuid),
    the same group course-gating/purchase-grant use. Also ensure a trail run so
    the course surfaces in their dashboard. Idempotent."""
    grp = (await db.execute(select(UserGroup).where(
        UserGroup.org_id == org_id, UserGroup.description == course_uuid))).scalars().first()
    if grp:
        has = (await db.execute(select(UserGroupUser).where(
            UserGroupUser.usergroup_id == grp.id,
            UserGroupUser.user_id == user.id))).scalars().first()
        if not has:
            db.add(UserGroupUser(usergroup_id=grp.id or 0, user_id=user.id or 0,
                                 org_id=org_id, creation_date=_now(), update_date=_now()))
            await db.commit()
    # best-effort trail run for "my courses" visibility
    try:
        from src.db.courses.courses import Course
        from src.bbu_migration.router import _ensure_trail, _ensure_run
        course = (await db.execute(select(Course).where(
            Course.course_uuid == course_uuid))).scalars().first()
        if course:
            trail = await _ensure_trail(db, org_id, user.id or 0)
            await _ensure_run(db, trail, course, user.id or 0)
    except Exception:
        pass


@router.post("/generate")
async def generate(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Admin. Body: {count, batch_label, course_uuids:[...] OR product_id, owner_email?, org_id?}"""
    _require_admin(request)
    b = await request.json()
    org_id = int(b.get("org_id", 1))
    count = max(1, min(1000, int(b.get("count", 1))))
    course_uuids = [u for u in (b.get("course_uuids") or []) if u]
    product_id = b.get("product_id")
    if product_id and not course_uuids:
        from src.bbu_payments.models import BBUProduct
        p = (await db_session.execute(select(BBUProduct).where(
            BBUProduct.id == int(product_id)))).scalars().first()
        if not p:
            raise HTTPException(404, "Product not found")
        course_uuids = [u for u in (p.course_uuids or "").split(",") if u]
    if not course_uuids:
        raise HTTPException(400, "course_uuids or a product_id with courses required")
    label = b.get("batch_label") or f"batch-{_now()[:10]}"
    codes = []
    for _ in range(count):
        code = _gen_code()
        while (await db_session.execute(select(BBUSeatCode).where(
                BBUSeatCode.code == code))).scalars().first():
            code = _gen_code()
        row = BBUSeatCode(org_id=org_id, code=code, batch_label=label,
                          course_uuids=",".join(course_uuids), product_id=product_id,
                          owner_email=(b.get("owner_email") or "").strip().lower(),
                          status="unused", created_at=_now())
        db_session.add(row)
        codes.append(code)
    await db_session.commit()
    return {"batch_label": label, "count": len(codes), "course_uuids": course_uuids,
            "codes": codes}


@router.get("/batches")
async def batches(request: Request, org_id: int = 1, db_session: AsyncSession = Depends(get_db_session)):
    _require_admin(request)
    rows = (await db_session.execute(select(BBUSeatCode).where(
        BBUSeatCode.org_id == org_id))).scalars().all()
    agg = {}
    for r in rows:
        a = agg.setdefault(r.batch_label, {"batch_label": r.batch_label, "total": 0,
                                           "redeemed": 0, "unused": 0, "void": 0,
                                           "course_uuids": r.course_uuids.split(",") if r.course_uuids else [],
                                           "owner_email": r.owner_email})
        a["total"] += 1
        a[r.status if r.status in ("redeemed", "void") else "unused"] += 1
    return list(agg.values())


@router.get("/batch/{batch_label}")
async def batch_detail(batch_label: str, request: Request, org_id: int = 1,
                       db_session: AsyncSession = Depends(get_db_session)):
    _require_admin(request)
    rows = (await db_session.execute(select(BBUSeatCode).where(
        BBUSeatCode.org_id == org_id, BBUSeatCode.batch_label == batch_label))).scalars().all()
    return [{"code": r.code, "status": r.status, "redeemed_by": r.redeemed_by_email,
             "redeemed_at": r.redeemed_at} for r in rows]


@router.post("/void")
async def void(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Admin. Body: {code} or {batch_label}. Voids UNUSED codes only."""
    _require_admin(request)
    b = await request.json()
    q = select(BBUSeatCode).where(BBUSeatCode.status == "unused")
    if b.get("code"):
        q = q.where(BBUSeatCode.code == b["code"].strip().upper())
    elif b.get("batch_label"):
        q = q.where(BBUSeatCode.batch_label == b["batch_label"])
    else:
        raise HTTPException(400, "code or batch_label required")
    rows = (await db_session.execute(q)).scalars().all()
    for r in rows:
        r.status = "void"
        db_session.add(r)
    await db_session.commit()
    return {"voided": len(rows)}


@router.post("/redeem")
async def redeem(request: Request, db_session: AsyncSession = Depends(get_db_session),
                 user=Depends(get_current_user)):
    """Redeem a seat code. The redeemer is the authenticated user; an admin may
    redeem on someone's behalf with {code, email} + admin key."""
    b = await request.json()
    code = (b.get("code") or "").strip().upper()
    if not code:
        raise HTTPException(400, "code required")
    # resolve redeemer
    target = None
    if _is_admin(request) and b.get("email"):
        target = (await db_session.execute(select(User).where(
            User.email == b["email"].strip().lower()))).scalars().first()
        if not target:
            raise HTTPException(404, "User not found")
    else:
        uid = getattr(user, "id", 0)
        if not uid:
            raise HTTPException(401, "Sign in to redeem a code")
        target = (await db_session.execute(select(User).where(User.id == uid))).scalars().first()
    row = (await db_session.execute(select(BBUSeatCode).where(
        BBUSeatCode.code == code))).scalars().first()
    if not row:
        raise HTTPException(404, "Invalid code")
    if row.status == "redeemed":
        raise HTTPException(409, "This code has already been redeemed")
    if row.status == "void":
        raise HTTPException(410, "This code is no longer valid")
    course_uuids = [u for u in (row.course_uuids or "").split(",") if u]
    for cu in course_uuids:
        await _grant_course_access(db_session, row.org_id, target, cu)
    row.status = "redeemed"
    row.redeemed_by_user_id = target.id
    row.redeemed_by_email = target.email
    row.redeemed_at = _now()
    db_session.add(row)
    await db_session.commit()
    return {"redeemed": True, "granted_courses": len(course_uuids),
            "email": target.email}
