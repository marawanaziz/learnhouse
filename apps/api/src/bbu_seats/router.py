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
    from src.bbu_seats import service as _seat_svc
    r = await _seat_svc.generate_batch(
        db_session, org_id, count, course_uuids,
        owner_email=(b.get("owner_email") or ""), product_id=product_id,
        batch_label=b.get("batch_label") or "")
    _domain = os.environ.get("LEARNHOUSE_DOMAIN", request.url.netloc)
    _scheme = "https" if os.environ.get("LEARNHOUSE_SSL", "true") == "true" else "http"
    portal_url = f"{_scheme}://{_domain}/api/v1/bbu/seats/portal?token={r['owner_token']}"
    return {"batch_label": r["batch_label"], "count": r["count"], "course_uuids": course_uuids,
            "codes": r["codes"], "owner_token": r["owner_token"], "portal_url": portal_url}


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


# ===========================================================================
# Self-serve: owner portal + recipient redeem page (branded HTML)
# ===========================================================================
from fastapi.responses import HTMLResponse  # noqa: E402
from src.bbu_payments.branding import _shell  # noqa: E402
from src.bbu_seats import service as seat_svc  # noqa: E402


def _base(request: Request) -> str:
    # https-aware base behind the Railway proxy (mirrors bbu_payments._base_url)
    domain = os.environ.get("LEARNHOUSE_DOMAIN", request.url.netloc)
    scheme = "https" if os.environ.get("LEARNHOUSE_SSL", "true") == "true" else "http"
    return f"{scheme}://{domain}"


@router.get("/portal", response_class=HTMLResponse)
async def owner_portal(request: Request, token: str = "", db_session: AsyncSession = Depends(get_db_session)):
    """Self-serve owner portal (magic link). Shows the buyer their seats and
    lets them copy/share each redeem link — no admin, no login required."""
    rows = await seat_svc.owner_seats(db_session, token.strip())
    if not rows:
        return HTMLResponse(_shell("Your Seats", "<div class='checkout'><h1>Seats not found</h1>"
                                   "<p style='color:#4a5b68'>This link looks invalid or expired. "
                                   "Check the link in your purchase confirmation, or contact support.</p></div>"))
    base = _base(request)
    total = len(rows)
    used = sum(1 for r in rows if r.status == "redeemed")
    unused = sum(1 for r in rows if r.status == "unused")
    def share(code):
        return f"{base}/api/v1/bbu/seats/redeem-page?code={code}"
    items = []
    for r in rows:
        if r.status == "redeemed":
            items.append(f"<div class='seat done'><b>{r.code}</b>"
                         f"<span class='who'>Redeemed by {r.redeemed_by_email or '—'}</span></div>")
        elif r.status == "void":
            items.append(f"<div class='seat void'><b>{r.code}</b><span class='who'>Void</span></div>")
        else:
            link = share(r.code)
            items.append(
                f"<div class='seat'><b>{r.code}</b>"
                f"<div class='acts'>"
                f"<button class='mini' onclick=\"cp('{r.code}',this)\">Copy code</button>"
                f"<button class='mini' onclick=\"cp('{link}',this)\">Copy share link</button>"
                f"</div></div>")
    share_links = "\\n".join(share(r.code) for r in rows if r.status == "unused")
    inner = (
        f"<div class='checkout' style='max-width:640px'>"
        f"<span class='eyebrow'>Your seats</span>"
        f"<h1 style='font-size:2rem;margin:10px 0'>Share access with your team</h1>"
        f"<p style='color:#4a5b68'>You have <b>{total}</b> seat{'s' if total != 1 else ''} — "
        f"<b>{unused}</b> available, <b>{used}</b> redeemed. Send each person their own "
        f"share link; they sign in and their access is granted automatically.</p>"
        f"<div style='height:8px'></div>"
        + (f"<button class='btn' style='width:100%' onclick=\"cp(`{share_links}`,this)\">Copy all {unused} share links</button>" if unused else "")
        + f"<div style='height:14px'></div>"
        f"<div class='seats'>{''.join(items)}</div>"
        f"</div>"
        f"<style>"
        f".seats{{display:flex;flex-direction:column;gap:8px}}"
        f".seat{{display:flex;justify-content:space-between;align-items:center;gap:10px;"
        f"padding:12px 14px;border:1px solid #e2ebf2;border-radius:12px;background:#fff}}"
        f".seat b{{font-family:monospace;letter-spacing:.5px}}"
        f".seat.done{{opacity:.6}} .seat.void{{opacity:.45;text-decoration:line-through}}"
        f".seat .who{{font-size:.8rem;color:#6b7f8d}}"
        f".acts{{display:flex;gap:6px}}"
        f".mini{{border:1px solid #cfe0ec;background:#f4f9fd;color:#113d5d;border-radius:999px;"
        f"padding:6px 12px;font-size:.78rem;cursor:pointer}}"
        f"</style>"
        f"<script>function cp(t,b){{navigator.clipboard.writeText(t).then(()=>{{"
        f"const o=b.textContent;b.textContent='Copied ✓';setTimeout(()=>b.textContent=o,1200);}});}}</script>"
    )
    return HTMLResponse(_shell("Your Seats", inner))


@router.get("/redeem-page", response_class=HTMLResponse)
async def redeem_page(request: Request, code: str = "", db_session: AsyncSession = Depends(get_db_session)):
    """Recipient landing page for a shared seat link: sign in + one-click redeem."""
    code = (code or "").strip().upper()
    row = (await db_session.execute(select(BBUSeatCode).where(BBUSeatCode.code == code))).scalars().first()
    base = _base(request)
    if not row:
        body = "<h1>Invalid link</h1><p style='color:#4a5b68'>This access code wasn't found.</p>"
        return HTMLResponse(_shell("Redeem access", f"<div class='checkout'>{body}</div>"))
    if row.status == "redeemed":
        body = "<h1>Already redeemed</h1><p style='color:#4a5b68'>This code has already been used.</p>"
        return HTMLResponse(_shell("Redeem access", f"<div class='checkout'>{body}</div>"))
    n = len([u for u in (row.course_uuids or '').split(',') if u])
    inner = (
        f"<div class='checkout'>"
        f"<span class='eyebrow'>You've been given access</span>"
        f"<h1 style='font-size:2rem;margin:10px 0'>Redeem your BBU training</h1>"
        f"<p style='color:#4a5b68'>This link unlocks <b>{n} training{'s' if n != 1 else ''}</b>. "
        f"Sign in to your Birth &amp; Baby University account, then tap redeem — access is added instantly.</p>"
        f"<div style='height:16px'></div>"
        f"<button class='btn' style='width:100%' id='go'>Redeem now →</button>"
        f"<div class='methods' id='msg'></div>"
        f"</div>"
        f"<script>"
        f"const go=document.getElementById('go');"
        f"go.onclick=async()=>{{go.textContent='Redeeming…';go.disabled=true;"
        f"const r=await fetch('{base}/api/v1/bbu/seats/redeem',{{method:'POST',"
        f"headers:{{'Content-Type':'application/json'}},credentials:'include',"
        f"body:JSON.stringify({{code:'{code}'}})}});"
        f"if(r.ok){{document.querySelector('.checkout').innerHTML="
        f"\"<div style='text-align:center'><div style='font-size:3rem'>🎉</div>"
        f"<h1 style='font-size:1.8rem;margin:12px 0'>You're in!</h1>"
        f"<p style='color:#4a5b68'>Your training has been added.</p>"
        f"<div style='height:16px'></div><a class='btn' href='{base}/'>Go to my courses →</a></div>\";}}"
        f"else if(r.status===401){{document.getElementById('msg').innerHTML="
        f"\"Please <a href='{base}/login?next='+encodeURIComponent(location.href)+\">sign in</a> first, then reopen this link.\";"
        f"go.textContent='Sign in to redeem';go.disabled=false;}}"
        f"else{{const d=await r.json().catch(()=>({{}}));go.textContent='Try again';go.disabled=false;"
        f"document.getElementById('msg').textContent=(d.detail||'Could not redeem.');}}"
        f"}};"
        f"</script>"
    )
    return HTMLResponse(_shell("Redeem access", inner))
