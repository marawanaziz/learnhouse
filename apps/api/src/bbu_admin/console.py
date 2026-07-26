"""BBU Operations Console — one in-app admin page (session-gated) to operate the
clean-room engines that were previously API/curl-only: coupons, cohorts,
credentials, and reseller seat codes. Mirrors the Cert Manager pattern
(self-contained branded HTML, session-or-key auth). Mounted at /api/v1/bbu/admin.

The page's JS calls this module's own JSON endpoints with the session cookie, so
the admin key never reaches the browser. Each endpoint calls the same service
layer the key-gated routers use — no duplicated business logic.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.users import User
from src.db.courses.courses import Course
from src.db.communities.communities import Community
from src.bbu_admin.auth import authorize_admin
from src.bbu_payments.models import BBUCoupon, BBUProduct, BBUOrder, BBUCircleRedemption
from src.bbu_payments import coupons as coupon_svc
from src.bbu_cohorts.models import BBUCohort, BBUCohortWaitlist
from src.bbu_cohorts import service as cohort_svc
from src.bbu_credentials.models import BBUCredential, BBUCeuLedger
from src.bbu_credentials import service as cred_svc
from src.bbu_seats.models import BBUSeatCode
from src.bbu_seats.router import _gen_code
from src.bbu_payments.branding import NAVY, SKY, STEEL, ICE, PAPER, LOGO, _FONTS

router = APIRouter()
ORG = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _auth(request: Request, db: AsyncSession, body: dict = None):
    await authorize_admin(request, db, (body or {}).get("key", ""))


async def _user(db: AsyncSession, email: str) -> User:
    u = (await db.execute(select(User).where(
        User.email == (email or "").strip().lower()))).scalars().first()
    if not u:
        raise HTTPException(404, "User not found")
    return u


# ===========================================================================
# Coupons
# ===========================================================================
@router.get("/coupons")
async def coupons_list(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    rows = (await db_session.execute(select(BBUCoupon).where(BBUCoupon.org_id == ORG))).scalars().all()
    prods = (await db_session.execute(select(BBUProduct).where(
        BBUProduct.org_id == ORG))).scalars().all()
    pname = {p.id: p.name for p in prods}

    def _covers(c):
        raw = (c.applies_to or "all").strip()
        if not raw or raw.lower() == "all":
            return "All products"
        names = [pname.get(int(x)) for x in raw.split(",") if x.strip().isdigit()]
        return ", ".join(n for n in names if n) or raw

    return [{
        "id": c.id, "code": c.code, "kind": c.kind,
        "value": (f"{c.percent_off}%" if c.kind == "percent" else f"${(c.amount_off_cents or 0)/100:.2f}"),
        "min": round((c.min_amount_cents or 0) / 100, 2),
        "max_redemptions": c.max_redemptions, "times_redeemed": c.times_redeemed,
        "expires_at": (c.expires_at or "")[:10], "active": bool(c.active),
        # what the code covers, and whether Stripe actually knows about it —
        # a code live in the platform but absent from Stripe cannot be redeemed
        "applies_to": c.applies_to or "all",
        "covers": _covers(c),
        "in_stripe": bool(c.stripe_promo_id),
        "stripe_coupon_id": c.stripe_coupon_id or "",
    } for c in rows]


@router.post("/coupons")
async def coupons_create(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    b = await request.json()
    await _auth(request, db_session, b)
    code = (b.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "code required")
    if await coupon_svc.find_by_code(db_session, ORG, code):
        raise HTTPException(409, "That code already exists")
    c = BBUCoupon(
        org_id=ORG, code=code, kind=b.get("kind", "percent"),
        percent_off=int(b.get("percent_off", 0) or 0),
        amount_off_cents=round(float(b.get("amount_off", 0) or 0) * 100),
        min_amount_cents=round(float(b.get("min_amount", 0) or 0) * 100),
        max_redemptions=int(b.get("max_redemptions", 0) or 0),
        # "all" or "7" or "1,2" — a $300-off code left unscoped is valid on every
        # product, so scope has to be settable at creation, not only by the sync.
        applies_to=(b.get("applies_to") or "all").strip(),
        expires_at=(b.get("expires_at") or ""), active=True, created_at=_now())
    try:
        from src.bbu_payments import stripe_sync as _sync
        prods = (await db_session.execute(select(BBUProduct).where(
            BBUProduct.org_id == ORG))).scalars().all()
        for pr in prods:
            _sync.ensure_product(pr)
            db_session.add(pr)
        coupon_svc.ensure_stripe_objects(
            c, _sync._scope_for(c, {pr.id: pr.stripe_product_id for pr in prods}))
    except Exception as e:
        raise HTTPException(502, f"Stripe error: {e}")
    db_session.add(c)
    await db_session.commit()
    return {"ok": True}


@router.get("/coupons/redemptions")
async def coupons_redemptions(request: Request, code: str = "", fmt: str = "json",
                              db_session: AsyncSession = Depends(get_db_session)):
    """Who redeemed which coupon — name, email, date, amount, discount.
    Anna needs this for BCBS grant reporting. `code` filters to one coupon;
    fmt=csv exports. Redemptions are recorded on the order's `extra` blob at
    checkout (extra.coupon_code / extra.coupon_discount_cents)."""
    await _auth(request, db_session)
    orders = (await db_session.execute(select(BBUOrder).where(
        BBUOrder.org_id == ORG, BBUOrder.status == "paid"))).scalars().all()
    prods = {p.id: p.name for p in (await db_session.execute(
        select(BBUProduct).where(BBUProduct.org_id == ORG))).scalars().all()}
    rows = []
    for o in orders:
        ex = o.extra or {}
        cc = (ex.get("coupon_code") or "").strip()
        if not cc:
            continue
        if code and cc.lower() != code.strip().lower():
            continue
        u = None
        if o.user_id:
            u = (await db_session.execute(select(User).where(User.id == o.user_id))).scalars().first()
        if not u and o.email:
            u = (await db_session.execute(select(User).where(User.email == o.email))).scalars().first()
        name = f"{getattr(u,'first_name','') or ''} {getattr(u,'last_name','') or ''}".strip() if u else ""
        rows.append({
            "coupon": cc,
            "name": name or "(no account)",
            "email": o.email or (getattr(u, "email", "") or ""),
            "product": prods.get(o.product_id, f"product {o.product_id}"),
            "paid": round((o.amount_cents or 0) / 100, 2),
            "discount": round(int(ex.get("coupon_discount_cents") or 0) / 100, 2),
            "date": (o.paid_at or o.created_at or "")[:10],
        })
    rows.sort(key=lambda r: (r["coupon"].lower(), r["date"]))
    if fmt == "csv":
        import io, csv
        from fastapi.responses import Response
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["coupon", "name", "email", "product",
                                            "paid", "discount", "date"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
        return Response(buf.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": "attachment; filename=bbu-coupon-redemptions.csv"})
    by_coupon = {}
    for r in rows:
        by_coupon[r["coupon"]] = by_coupon.get(r["coupon"], 0) + 1
    return {"total_redemptions": len(rows), "by_coupon": by_coupon, "rows": rows}


@router.post("/coupons/{cid}/toggle")
async def coupons_toggle(cid: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    c = (await db_session.execute(select(BBUCoupon).where(
        BBUCoupon.id == cid, BBUCoupon.org_id == ORG))).scalars().first()
    if not c:
        raise HTTPException(404, "Not found")
    c.active = not c.active
    (coupon_svc.reactivate_stripe if c.active else coupon_svc.deactivate_stripe)(c)
    db_session.add(c)
    await db_session.commit()
    return {"active": c.active}


# ===========================================================================
# Cohorts
# ===========================================================================
@router.get("/cohorts")
async def cohorts_list(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    rows = (await db_session.execute(select(BBUCohort).where(
        BBUCohort.org_id == ORG).order_by(BBUCohort.id.desc()))).scalars().all()
    out = []
    for c in rows:
        out.append({
            "id": c.id, "name": c.name, "program": c.program, "status": c.status,
            "capacity": c.capacity, "active_members": await cohort_svc.active_count(db_session, c.id),
            "credential_type": c.credential_type, "start_date": c.start_date, "end_date": c.end_date,
            "community_id": c.community_id, "zoom_meeting_id": c.zoom_meeting_id,
            "workbook_url": c.workbook_url, "access_until": cohort_svc.access_until(c),
            "prompts": _prompt_count(c),
        })
    return out


def _prompt_count(c: BBUCohort) -> int:
    import json as _json
    try:
        return len(_json.loads(c.weekly_prompts or "[]"))
    except Exception:
        return 0


@router.get("/communities")
async def communities_list(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Community picker for the cohort form."""
    await _auth(request, db_session)
    rows = (await db_session.execute(select(Community).where(
        Community.org_id == ORG).order_by(Community.name))).scalars().all()
    return [{"id": c.id, "name": c.name} for c in rows]


@router.post("/cohorts")
async def cohorts_create(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    b = await request.json()
    await _auth(request, db_session, b)
    program = b.get("program", "doula")
    cid = b.get("community_id")
    c = BBUCohort(
        org_id=ORG, name=b.get("name", "Untitled Cohort"), program=program,
        course_uuid=(b.get("course_uuid") or "").strip(),
        community_id=int(cid) if str(cid or "").isdigit() else None,
        capacity=int(b.get("capacity", 0) or 0),
        access_months=int(b.get("access_months", 12 if program == "agency" else 6)),
        credential_type=(b.get("credential_type") or "").strip().lower(),
        start_date=b.get("start_date", ""), end_date=b.get("end_date", ""),
        zoom_meeting_id=(b.get("zoom_meeting_id") or "").strip(),
        workbook_url=(b.get("workbook_url") or "").strip(),
        status="open", created_at=_now(), updated_at=_now())
    # seed workbook + weekly prompts from the program template (blanks only)
    cohort_svc.provision_defaults(c)
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    if c.course_uuid:
        await cohort_svc.ensure_usergroup(db_session, c)
    return {"ok": True, "id": c.id}


@router.get("/zoom-meetings")
async def zoom_meetings(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Populate the cohort form's Zoom meeting/webinar dropdown from the account."""
    await _auth(request, db_session)
    from src.bbu_zoom import client as zoom
    return await zoom.list_meetings()


@router.post("/cohorts/run-lifecycle")
async def cohorts_run_lifecycle(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    b = await request.json()
    await _auth(request, db_session, b)
    return await cohort_svc.run_lifecycle(db_session, org_id=ORG, dry=bool(b.get("dry_run", False)))


@router.post("/cohorts/{cid}/update")
async def cohorts_update(cid: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Edit a cohort in place — capacity (the limit), dates, status, access
    window, Zoom, community, workbook. Raising the limit (or going unlimited)
    auto-fills the new seats: promote paid waitlisted members, then invite the
    earliest interest-waitlist prospects for any seats still free."""
    b = await request.json()
    await _auth(request, db_session, b)
    c = (await db_session.execute(select(BBUCohort).where(
        BBUCohort.id == cid, BBUCohort.org_id == ORG))).scalars().first()
    if not c:
        raise HTTPException(404, "Cohort not found")
    res = {"ok": True}
    # status: 'closed' revokes access (same as the Close button); others set raw
    if "status" in b:
        ns = (b.get("status") or "").strip()
        if ns == "closed" and c.status != "closed":
            await cohort_svc.close(db_session, c, revoke_access=True)
        elif ns in ("open", "full", "running"):
            c.status = ns
    for f in ("start_date", "end_date", "zoom_meeting_id", "workbook_url", "credential_type"):
        if f in b:
            setattr(c, f, b[f])
    if "community_id" in b:
        v = b.get("community_id")
        c.community_id = int(v) if str(v or "").isdigit() else None
    if "access_months" in b:
        c.access_months = int(b.get("access_months") or 0)
    if "capacity" in b:
        old = c.capacity or 0
        c.capacity = max(0, int(b.get("capacity") or 0))
        c.updated_at = _now()
        db_session.add(c)
        await db_session.commit()
        # new room? fill it from the waitlists.
        if c.capacity == 0 or c.capacity > old:
            before = await cohort_svc.active_count(db_session, c.id)
            await cohort_svc.promote_waitlist(db_session, c)         # paid waitlisted members
            after = await cohort_svc.active_count(db_session, c.id)
            res["promoted"] = after - before
            free = (c.capacity - after) if c.capacity else 500        # remaining open seats
            if free > 0 and c.status in ("open", "full"):
                invited = await cohort_svc.notify_waitlist(db_session, c.org_id, c.program, free)
                res["invited"] = len(invited)
    c.updated_at = _now()
    db_session.add(c)
    await db_session.commit()
    # re-ensure the access group (links course + community) so edits self-heal
    try:
        await cohort_svc.ensure_usergroup(db_session, c)
    except Exception:
        pass
    return res


@router.get("/cohort-waitlist")
async def cohort_waitlist_list(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    rows = (await db_session.execute(select(BBUCohortWaitlist).where(
        BBUCohortWaitlist.org_id == ORG).order_by(BBUCohortWaitlist.id))).scalars().all()
    return [{
        "id": r.id, "program": r.program, "email": r.email, "name": r.name,
        "phone": r.phone, "status": r.status,
        "created_at": (r.created_at or "")[:10], "notified_at": (r.notified_at or "")[:10],
    } for r in rows]


@router.delete("/cohort-waitlist/{wid}")
async def cohort_waitlist_delete(wid: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    r = (await db_session.execute(select(BBUCohortWaitlist).where(
        BBUCohortWaitlist.id == wid, BBUCohortWaitlist.org_id == ORG))).scalars().first()
    if r:
        await db_session.delete(r)
        await db_session.commit()
    return {"deleted": wid}


@router.post("/cohort-waitlist/notify")
async def cohort_waitlist_notify(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Manually invite the next N waiting prospects of a program to enroll."""
    b = await request.json()
    await _auth(request, db_session, b)
    notified = await cohort_svc.notify_waitlist(
        db_session, ORG, (b.get("program") or "doula"), int(b.get("count", 1) or 1))
    return {"notified": [{"email": r.email, "name": r.name} for r in notified]}


@router.get("/cohorts/{cid}/roster")
async def cohorts_roster(cid: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    members = await cohort_svc.roster(db_session, cid)
    uids = [m.user_id for m in members]
    users = {}
    if uids:
        rows = (await db_session.execute(select(User).where(User.id.in_(uids)))).scalars().all()
        users = {u.id: u for u in rows}
    return [{
        "email": getattr(users.get(m.user_id), "email", ""),
        "name": f"{getattr(users.get(m.user_id), 'first_name', '')} {getattr(users.get(m.user_id), 'last_name', '')}".strip(),
        "status": m.status,
    } for m in members]


@router.post("/cohorts/{cid}/action")
async def cohorts_action(cid: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    b = await request.json()
    await _auth(request, db_session, b)
    c = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == cid))).scalars().first()
    if not c:
        raise HTTPException(404, "Cohort not found")
    action = b.get("action")
    if action == "close":
        return await cohort_svc.close(db_session, c, revoke_access=True)
    u = await _user(db_session, b.get("email", ""))
    if action == "enroll":
        return await cohort_svc.enroll(db_session, c, u.id)
    if action == "complete":
        return await cohort_svc.complete(db_session, c, u.id)
    if action == "remove":
        return await cohort_svc.remove(db_session, c, u.id)
    raise HTTPException(400, "unknown action")


# ===========================================================================
# Credentials
# ===========================================================================
@router.get("/credentials")
async def credentials_user(request: Request, email: str, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    u = await _user(db_session, email)
    creds = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == ORG, BBUCredential.user_id == u.id))).scalars().all()
    total = await cred_svc.approved_ceu_total(db_session, ORG, u.id)
    ledger = (await db_session.execute(select(BBUCeuLedger).where(
        BBUCeuLedger.org_id == ORG, BBUCeuLedger.user_id == u.id))).scalars().all()
    return {
        "email": u.email, "ceu_total": total,
        "credentials": [cred_svc.to_dict(c, total) for c in creds],
        "ledger": [{"ceu": r.ceu_count, "source": r.source, "ref": r.source_ref,
                    "approved": r.approved} for r in ledger],
    }


@router.get("/stripe-sync")
async def stripe_sync_status(request: Request,
                             db_session: AsyncSession = Depends(get_db_session)):
    """How much of the catalogue/coupon set actually exists in Stripe."""
    await _auth(request, db_session)
    from src.bbu_payments import stripe_sync as sync_svc
    return await sync_svc.status(db_session, ORG)


@router.post("/stripe-sync")
async def stripe_sync_run(request: Request,
                          db_session: AsyncSession = Depends(get_db_session)):
    """Push products + active coupons into Stripe. Body: {reset, include_inactive}.

    `reset` clears cached Stripe ids first — required once after switching from
    the test key to the live key, since ids don't carry across accounts/modes.
    """
    body = await request.json() if await request.body() else {}
    await _auth(request, db_session, body)
    from src.bbu_payments import stripe_sync as sync_svc
    return await sync_svc.sync_all(db_session, ORG,
                                   reset=bool(body.get("reset")),
                                   include_inactive=bool(body.get("include_inactive")))


@router.get("/circle-history")
async def circle_history(request: Request, q: str = "", code: str = "",
                         fmt: str = "json", page: int = 1, per_page: int = 50,
                         db_session: AsyncSession = Depends(get_db_session)):
    """Circle's coupon redemption history, archived here before Circle shut down.

    This is what the team hands a funder: which people were served under which
    code. Search by person (name/email) or filter to a single code. fmt=csv
    returns every matching row, ignoring pagination, for a grant report.
    """
    await _auth(request, db_session)
    rows = (await db_session.execute(select(BBUCircleRedemption).where(
        BBUCircleRedemption.org_id == ORG))).scalars().all()

    if code:
        rows = [r for r in rows if r.code.upper() == code.strip().upper()]
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in (r.member_name or "").lower()
                or needle in (r.member_email or "").lower()]
    rows.sort(key=lambda r: (r.redeemed_on or "", r.code), reverse=True)

    # per-code rollup drives the filter dropdown and the funder-facing totals
    tally: dict = {}
    for r in rows:
        t = tally.setdefault(r.code, {"code": r.code, "terms": r.terms,
                                      "redemptions": 0, "people": set()})
        t["redemptions"] += 1
        if r.member_email:
            t["people"].add(r.member_email)
    by_code = sorted(({"code": t["code"], "terms": t["terms"],
                       "redemptions": t["redemptions"], "people": len(t["people"])}
                      for t in tally.values()), key=lambda x: -x["redemptions"])

    def _row(r):
        return {"code": r.code, "terms": r.terms, "name": r.member_name,
                "email": r.member_email, "course": r.paywall_name,
                "date": r.redeemed_on, "amount": r.amount, "status": r.charge_status}

    if fmt == "csv":
        import csv as _csv
        import io as _io
        from fastapi.responses import PlainTextResponse as _PT
        buf = _io.StringIO()
        w = _csv.writer(buf)
        w.writerow(["coupon_code", "terms", "member_name", "member_email",
                    "course", "date_redeemed", "amount", "status"])
        for r in rows:
            w.writerow([r.code, r.terms, r.member_name, r.member_email,
                        r.paywall_name, r.redeemed_on, r.amount, r.charge_status])
        name = f"circle-history{'-' + code.upper() if code else ''}.csv"
        return _PT(buf.getvalue(), media_type="text/csv",
                   headers={"Content-Disposition": f'attachment; filename="{name}"'})

    per_page = max(1, min(500, per_page))
    total = len(rows)
    start = (max(1, page) - 1) * per_page
    return {"total": total, "page": page, "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
            "unique_people": len({r.member_email for r in rows if r.member_email}),
            "by_code": by_code,
            "rows": [_row(r) for r in rows[start:start + per_page]]}


@router.get("/credentials/roster")
async def credentials_roster(request: Request, q: str = "", status: str = "",
                             ctype: str = "", source: str = "",
                             expiring_days: int = 0, fmt: str = "json",
                             page: int = 1, per_page: int = 50,
                             db_session: AsyncSession = Depends(get_db_session)):
    """THE credential registry the admin team manages from: every credential
    holder with status, expiry, days-to-expiry and CEUs. Filterable by status,
    type (birth/postpartum), source (training = first-year cert, cross_cert),
    and an "expiring within N days" window. fmt=csv returns a CSV to hand to a
    mail merge."""
    await _auth(request, db_session)
    creds = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == ORG))).scalars().all()
    uids = list({c.user_id for c in creds})
    users = {}
    if uids:
        urows = (await db_session.execute(select(User).where(User.id.in_(uids)))).scalars().all()
        users = {u.id: u for u in urows}
    now = cred_svc._now_dt()
    ql = (q or "").strip().lower()
    out = []
    for c in creds:
        eff = cred_svc.compute_effective_status(c)
        u = users.get(c.user_id)
        name = f"{getattr(u,'first_name','') or ''} {getattr(u,'last_name','') or ''}".strip()
        email = getattr(u, "email", "") or ""
        exp_raw = (c.full_expires_at if c.status == "full" else c.provisional_expires_at) or ""
        exp = cred_svc._parse(exp_raw)
        days = (exp - now).days if exp else None
        if status and eff != status:
            continue
        if ctype and c.credential_type != ctype:
            continue
        if source and (c.source or "") != source:
            continue
        if expiring_days:
            if days is None or days < 0 or days > expiring_days:
                continue
        if ql and ql not in name.lower() and ql not in email.lower():
            continue
        out.append({
            "credential_id": c.id, "user_id": c.user_id,
            "name": name or "(no name)", "email": email,
            "type": c.credential_type,
            "track": {"cross_cert": "Cross-certification", "manual": "Manual",
                      "training": "First-year training",
                      "accredible": "Imported (Accredible)"}.get(
                          (c.source or "").strip(), (c.source or "unknown")),
            "status": eff,
            "issued": (c.full_effective_at or c.issued_at or "")[:10],
            "expires": exp_raw[:10],
            "days_to_expiry": days,
            "directory_listed": bool(c.directory_opt_in),
        })
    out.sort(key=lambda r: (r["days_to_expiry"] if r["days_to_expiry"] is not None else 10**6))
    if fmt == "csv":
        import io, csv
        from fastapi.responses import Response
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(out[0].keys()) if out else
                           ["credential_id", "user_id", "name", "email", "type", "track",
                            "status", "issued", "expires", "days_to_expiry", "directory_listed"])
        w.writeheader()
        for r in out:
            w.writerow(r)
        return Response(buf.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": "attachment; filename=bbu-credentials.csv"})
    # Summary always reflects the FULL filtered set, not the current page.
    summary = {"total": len(out)}
    for r in out:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    exp30 = len([r for r in out if r["days_to_expiry"] is not None and 0 <= r["days_to_expiry"] <= 30])
    exp90 = len([r for r in out if r["days_to_expiry"] is not None and 0 <= r["days_to_expiry"] <= 90])
    summary["expiring_30d"] = exp30
    summary["expiring_90d"] = exp90
    total = len(out)
    per_page = max(1, min(500, per_page))
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    return {"summary": summary,
            "page": page, "per_page": per_page, "pages": pages, "total": total,
            "showing": [start + 1 if total else 0, min(start + per_page, total)],
            "rows": out[start:start + per_page]}


@router.post("/credentials/action")
async def credentials_action(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    b = await request.json()
    await _auth(request, db_session, b)
    u = await _user(db_session, b.get("email", ""))
    action = b.get("action")
    ctype = (b.get("credential_type") or "birth").strip().lower()
    if action == "issue":
        mode = (b.get("mode") or "provisional").lower()
        if mode == "full":
            await cred_svc.issue_full_direct(db_session, ORG, u.id, ctype, source="manual", source_ref="admin")
        else:
            await cred_svc.issue_provisional(db_session, ORG, u.id, ctype, source_ref="admin")
        return {"ok": True}
    if action == "award_ceu":
        await cred_svc.award_ceu(db_session, ORG, u.id, int(b.get("count", 0)),
                                 source="manual", source_ref=b.get("note", ""))
        return {"ok": True, "ceu_total": await cred_svc.approved_ceu_total(db_session, ORG, u.id)}
    if action == "renew":
        cred = (await db_session.execute(select(BBUCredential).where(
            BBUCredential.org_id == ORG, BBUCredential.user_id == u.id,
            BBUCredential.credential_type == ctype))).scalars().first()
        if not cred:
            raise HTTPException(404, "Credential not found")
        ok, reason = await cred_svc.renew(db_session, cred)
        return {"ok": ok, "reason": reason}
    raise HTTPException(400, "unknown action")


# ===========================================================================
# Seat codes
# ===========================================================================
@router.get("/seats")
async def seats_batches(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    rows = (await db_session.execute(select(BBUSeatCode).where(BBUSeatCode.org_id == ORG))).scalars().all()
    agg = {}
    for r in rows:
        a = agg.setdefault(r.batch_label, {"batch_label": r.batch_label, "total": 0,
                                           "redeemed": 0, "unused": 0, "void": 0,
                                           "owner_email": r.owner_email})
        a["total"] += 1
        a[r.status if r.status in ("redeemed", "void") else "unused"] += 1
    return list(agg.values())


@router.post("/seats/generate")
async def seats_generate(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    b = await request.json()
    await _auth(request, db_session, b)
    count = max(1, min(500, int(b.get("count", 1))))
    course_uuids = [u for u in (b.get("course_uuids") or []) if u]
    if b.get("product_id") and not course_uuids:
        p = (await db_session.execute(select(BBUProduct).where(
            BBUProduct.id == int(b["product_id"])))).scalars().first()
        if p:
            course_uuids = [u for u in (p.course_uuids or "").split(",") if u]
    if not course_uuids:
        raise HTTPException(400, "course_uuids or product_id required")
    label = b.get("batch_label") or f"batch-{_now()[:10]}"
    codes = []
    for _ in range(count):
        code = _gen_code()
        while (await db_session.execute(select(BBUSeatCode).where(BBUSeatCode.code == code))).scalars().first():
            code = _gen_code()
        db_session.add(BBUSeatCode(org_id=ORG, code=code, batch_label=label,
                                   course_uuids=",".join(course_uuids),
                                   owner_email=(b.get("owner_email") or "").strip().lower(),
                                   status="unused", created_at=_now()))
        codes.append(code)
    await db_session.commit()
    return {"batch_label": label, "count": len(codes), "codes": codes}


@router.get("/courses")
async def courses_list(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Course picker for cohort/seat forms."""
    await _auth(request, db_session)
    rows = (await db_session.execute(select(Course).where(
        Course.org_id == ORG).order_by(Course.name))).scalars().all()
    return [{"course_uuid": c.course_uuid, "name": c.name} for c in rows]


# ===========================================================================
# Store merchandising — edit each offer's category + order-bump add-ons.
# ===========================================================================
@router.get("/offers")
async def offers_list(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    rows = (await db_session.execute(select(BBUProduct).where(
        BBUProduct.org_id == ORG).order_by(BBUProduct.name))).scalars().all()
    return [{
        "id": p.id, "name": p.name, "kind": p.kind,
        "price": round((p.price_cents or 0) / 100, 2),
        "category": p.category or "",
        "public": bool(p.public),
        "bump_ids": [int(x) for x in (p.bump_offer_ids or "").split(",") if x.strip().isdigit()],
        "cohort_program": p.cohort_program or "",
        "cohort_id": p.cohort_id,
        "seat_count": int(getattr(p, "seat_count", 0) or 0),
    } for p in rows]


@router.post("/offers/{pid}/merchandising")
async def offers_merch(pid: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    b = await request.json()
    await _auth(request, db_session, b)
    p = (await db_session.execute(select(BBUProduct).where(
        BBUProduct.id == pid, BBUProduct.org_id == ORG))).scalars().first()
    if not p:
        raise HTTPException(404, "Offer not found")
    if "price" in b:
        # Price is entered in DOLLARS in the admin UI; stored as cents. Applies
        # to the next checkout — existing orders keep the price they were sold at.
        try:
            dollars = float(b.get("price"))
        except (TypeError, ValueError):
            raise HTTPException(400, "price must be a number (dollars)")
        if dollars < 0:
            raise HTTPException(400, "price cannot be negative")
        p.price_cents = int(round(dollars * 100))
    if "name" in b and str(b.get("name") or "").strip():
        p.name = str(b["name"]).strip()[:200]
    if "category" in b:
        p.category = (b.get("category") or "")
    if "bump_ids" in b:
        p.bump_offer_ids = ",".join(str(int(x)) for x in (b.get("bump_ids") or [])
                                    if str(x).isdigit() and int(x) != pid)
    if "cohort_program" in b:
        prog = (b.get("cohort_program") or "").strip()
        p.cohort_program = prog if prog in ("doula", "agency") else ""
    if "cohort_id" in b:
        cid = b.get("cohort_id")
        p.cohort_id = int(cid) if str(cid or "").isdigit() and int(cid) > 0 else None
    if "public" in b:
        p.public = bool(b.get("public"))
    if "seat_count" in b:
        p.seat_count = max(0, int(b.get("seat_count") or 0))
    db_session.add(p)
    await db_session.commit()
    return {"ok": True}


# ===========================================================================
# The page
# ===========================================================================
@router.get("/", response_class=HTMLResponse)
async def page(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    return HTMLResponse(_PAGE)


_PAGE = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Operations · Birth &amp; Baby University</title>{_FONTS}
<style>
:root{{--navy:{NAVY};--sky:{SKY};--steel:{STEEL};--ice:{ICE};--paper:{PAPER}}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Open Sans',system-ui,sans-serif;color:{NAVY};background:{PAPER}}}
h1,h2{{font-family:'Playfair Display',Georgia,serif}}
.nav{{background:#fff;border-bottom:1px solid rgba(17,61,93,.08);padding:16px 0}}
.wrap{{max-width:1180px;margin:0 auto;padding:0 22px}}
.nav img{{height:50px}}
.head{{padding:26px 0 4px}}
.eyebrow{{font-family:'League Spartan',sans-serif;font-weight:600;letter-spacing:.24em;text-transform:uppercase;font-size:.7rem;color:{STEEL}}}
.head h1{{font-size:2rem;margin:6px 0 2px}}
.head p{{color:#5b6b78;font-size:.92rem}}
.tabs{{display:flex;gap:.15rem;max-width:1180px;margin:14px auto 0;padding:0 22px;border-bottom:1px solid rgba(17,61,93,.1);flex-wrap:wrap}}
.tab{{font-family:'League Spartan',sans-serif;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:.65rem 1.05rem;color:{STEEL};cursor:pointer;border-bottom:3px solid transparent;font-size:.78rem;transition:color .15s}}
.tab:hover{{color:{NAVY}}}
.tab.on{{color:{NAVY};border-color:{SKY}}}
.panel{{display:none}}.panel.on{{display:block}}
.card{{background:#fff;border-radius:14px;box-shadow:0 10px 30px rgba(17,61,93,.06);padding:1.3rem 1.4rem;margin-bottom:1.3rem}}
h2{{font-size:1.15rem;color:{NAVY};margin:.1rem 0 1rem}}
table{{width:100%;border-collapse:collapse;font-size:.87rem;background:#fff}}
th{{text-align:left;font-family:'League Spartan',sans-serif;font-weight:700;font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;color:{STEEL};padding:11px 12px;border-bottom:2px solid {ICE};background:#fbfdff}}
td{{padding:9px 12px;border-bottom:1px solid rgba(17,61,93,.06);vertical-align:middle}}
tr:hover td{{background:#fbfdff}}
input,select,textarea{{font-family:'Open Sans',system-ui,sans-serif;padding:.5rem .65rem;border:1px solid rgba(17,61,93,.2);border-radius:9px;font-size:.85rem;margin:.2rem;background:#fff;color:{NAVY}}}
input:focus,select:focus{{outline:none;border-color:{STEEL}}}
button,.btn{{font-family:'League Spartan',sans-serif;font-weight:700;letter-spacing:.03em;background:{NAVY};color:#fff;border:none;border-radius:999px;padding:.5rem 1.1rem;font-size:.8rem;cursor:pointer;transition:background .2s}}
button:hover{{background:{STEEL}}}
button.ghost,.btn.ghost{{background:{ICE};color:{NAVY}}}
button.ghost:hover{{background:#dbecf8}}
.row{{display:flex;flex-wrap:wrap;align-items:center;gap:.35rem;margin-bottom:.6rem}}
.badge{{padding:.15rem .6rem;border-radius:999px;font-size:.72rem;font-weight:700;font-family:'League Spartan',sans-serif}}
.on-b{{background:#dff5e6;color:#1c7a41}}.off-b{{background:#fde8e8;color:#b42318}}
.muted{{color:#7d93a6;font-size:.82rem}}
.pill{{background:{ICE};color:{STEEL};border-radius:999px;padding:3px 12px;font-family:'League Spartan',sans-serif;font-weight:600;font-size:.76rem}}
</style></head><body>
<div class=nav><div class=wrap><img src="{LOGO}" alt="Birth &amp; Baby University"></div></div>
<div class=wrap><div class=head><span class=eyebrow>Admin</span><h1>Operations</h1><p>Store · cohorts · coupons · credentials · seat codes · waitlist</p></div></div>
<div class=tabs>
  <div class="tab on" data-t="coupons">Coupons</div>
  <div class="tab" data-t="cohorts">Cohorts</div>
  <div class="tab" data-t="credentials">Credentials</div>
  <div class="tab" data-t="seats">Seat codes</div>
  <div class="tab" data-t="store">Store</div>
  <div class="tab" data-t="sponsors">Sponsored access</div>
  <div class="tab" data-t="circlehist">Circle history</div>
</div>
<div class="wrap" style="padding-top:22px;padding-bottom:50px">
  <div class="panel on" id=p-coupons>
    <div class=card><h2>Create a promo code</h2>
      <div class=row>
        <input id=c-code placeholder="CODE (e.g. LAUNCH20)">
        <select id=c-kind><option value=percent>% off</option><option value=amount>$ off</option></select>
        <input id=c-val type=number placeholder="amount" style="width:90px">
        <input id=c-min type=number placeholder="min $ (opt)" style="width:100px">
        <input id=c-max type=number placeholder="max uses (opt)" style="width:110px">
        <input id=c-exp type=date>
        <button onclick=createCoupon()>Create</button>
      </div><div class=muted id=c-msg></div>
    </div>
    <div class=card><h2>Stripe sync</h2>
      <p class=muted style="margin-top:-.6rem">Buyers type codes on Stripe's checkout page, so every code has to exist in Stripe. Stripe enforces expiry, usage caps and which courses a code covers. <b>Re-run this once after switching from the test key to the live key</b> &mdash; Stripe ids don't carry across accounts.</p>
      <div id=ss-out class=row style="gap:.5rem;flex-wrap:wrap;margin-bottom:.6rem"></div>
      <div class=row>
        <button onclick=runStripeSync(false)>Sync to Stripe</button>
        <button class=ghost onclick=runStripeSync(true)>Re-create all (after key swap)</button>
      </div>
      <div class=muted id=ss-msg></div>
    </div>
    <div class=card><h2>Coupons</h2><table id=t-coupons><thead><tr><th>Code</th><th>Value</th><th>Min</th><th>Used</th><th>Expires</th><th>Status</th><th></th></tr></thead><tbody></tbody></table></div>
  </div>

  <div class="panel" id=p-cohorts>
    <div class=card><h2>Create a cohort</h2>
      <div class=row>
        <input id=co-name placeholder="Name (e.g. Sept 2026 Doula Mentorship)" style="width:300px">
        <select id=co-prog onchange="progDefaults()"><option value=doula>doula</option><option value=agency>agency</option></select>
        <select id=co-course title="course this cohort unlocks"></select>
        <select id=co-comm title="community for weekly prompts"></select>
      </div>
      <div class=row style="margin-top:.5rem">
        <label class=muted>Start <input id=co-start type=date></label>
        <label class=muted>End <input id=co-end type=date></label>
        <input id=co-cap type=number placeholder="capacity (0=∞)" style="width:120px">
        <input id=co-access type=number placeholder="access mo" title="months of access after end" style="width:110px">
        <select id=co-cred><option value="">no credential</option><option value=birth>birth</option><option value=postpartum>postpartum</option><option value=both>both</option></select>
      </div>
      <div class=row style="margin-top:.5rem">
        <select id=co-zoom-sel onchange="zoomSelChange()" style="width:300px"><option value="">— Zoom meeting (none) —</option></select>
        <input id=co-zoom placeholder="Zoom meeting/webinar ID" style="width:180px;display:none">
        <input id=co-workbook placeholder="Workbook URL (optional)" style="width:300px">
        <button onclick=createCohort()>Create</button>
      </div>
      <div class=muted id=co-msg style="margin-top:.4rem"></div>
      <p class=muted style="margin-top:.3rem;font-size:.78rem">Weekly discussion prompts auto-seed from the program template and post one/week into the chosen community. Members auto-register to the Zoom ID; recordings sync back in.</p>
    </div>
    <div class=card><h2>Cohorts <button class=ghost style="float:right;font-size:.8rem" onclick=runLifecycle()>Run lifecycle now</button></h2>
      <table id=t-cohorts><thead><tr><th>Name</th><th>Program</th><th>Dates</th><th>Members</th><th>Cap</th><th>Cred</th><th>Prompts</th><th>Access until</th><th>Status</th><th></th></tr></thead><tbody></tbody></table>
      <div class=muted id=lc-msg style="margin-top:.4rem"></div></div>
    <div class=card id=roster-card style=display:none><h2>Roster — <span id=roster-name></span></h2>
      <div class=row><input id=co-email placeholder="member email"><button onclick="cohortAct('enroll')">Enroll</button><button class=ghost onclick="cohortAct('complete')">Mark complete</button><button class=ghost onclick="cohortAct('remove')">Remove</button><button class=ghost style="margin-left:auto;color:#b23" onclick="closeCohort()">Close cohort</button></div>
      <table id=t-roster><thead><tr><th>Name</th><th>Email</th><th>Status</th></tr></thead><tbody></tbody></table>
    </div>
    <div class=card><h2>Waitlist <button class=ghost style="float:right;font-size:.8rem" onclick="notifyWaitlist()">Notify next waiting</button></h2>
      <p class=muted style="margin-top:-.6rem">Prospects who signed up while cohorts were full. They're invited automatically when a seat frees; use the button to invite the next one manually.</p>
      <table id=t-waitlist><thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>Program</th><th>Status</th><th>Joined</th></tr></thead><tbody></tbody></table>
    </div>
  </div>

  <div class="panel" id=p-credentials>
    <div class=card><h2>Look up a member's credentials</h2>
      <div class=row><input id=cr-email placeholder="member email" style="width:280px"><button onclick=loadCred()>Look up</button></div>
      <div id=cr-out></div>
    </div>
    <div class=card><h2>Credential registry — who's certified &amp; who's expiring</h2>
      <div id=cr-summary class=row style="gap:.5rem;flex-wrap:wrap;margin-bottom:.6rem"></div>
      <div class=row style="flex-wrap:wrap;gap:.4rem">
        <input id=rq placeholder="search name or email" style="width:220px" onkeyup="if(event.key==='Enter')loadRoster()">
        <select id=rstatus><option value="">any status</option><option value=full>full</option><option value=provisional>provisional</option><option value=lapsed>lapsed</option><option value=expired>expired</option></select>
        <select id=rtype><option value="">any type</option><option value=birth>birth</option><option value=postpartum>postpartum</option></select>
        <select id=rsource><option value="">any track</option><option value=accredible>Imported (Accredible)</option><option value=training>First-year training</option><option value=cross_cert>Cross-certification</option><option value=manual>Manual</option></select>
        <select id=rexp><option value=0>any expiry</option><option value=30>expiring ≤30 days</option><option value=60>expiring ≤60 days</option><option value=90>expiring ≤90 days</option><option value=180>expiring ≤180 days</option></select>
        <button onclick="RPAGE=1;loadCredRoster()">Filter</button>
        <select id=rper onchange="RPAGE=1;loadCredRoster()"><option value=50>50 / page</option><option value=100>100 / page</option><option value=250>250 / page</option><option value=500>500 / page</option></select>
        <button class=ghost onclick=exportRoster()>⬇ Export CSV (all matching)</button>
      </div>
      <div style="max-height:520px;overflow:auto;margin-top:.6rem">
        <table id=t-credroster><thead><tr><th>Member</th><th>Credential</th><th>Track</th><th>Status</th><th>Valid through</th><th>Days left</th></tr></thead><tbody></tbody></table>
      </div>
      <div class=row id=rpager style="justify-content:space-between;align-items:center;margin-top:.6rem"></div>
    </div>
    <div class=card><h2>Actions</h2>
      <div class=row>
        <input id=cra-email placeholder="member email">
        <select id=cra-type><option value=birth>birth</option><option value=postpartum>postpartum</option></select>
        <button onclick="credAct('issue','provisional')">Issue provisional</button>
        <button class=ghost onclick="credAct('issue','full')">Issue full</button>
        <button class=ghost onclick="credAct('renew')">Renew</button>
      </div>
      <div class=row><input id=cra-ceu type=number placeholder="CEUs" style="width:90px"><button class=ghost onclick="credAct('award_ceu')">Award CEUs</button></div>
      <div class=muted id=cra-msg></div>
    </div>
  </div>

  <div class="panel" id=p-seats>
    <div class=card><h2>Generate seat codes (reseller / bulk)</h2>
      <div class=row>
        <input id=s-label placeholder="batch label (e.g. Hospital X 16-pack)" style="width:280px">
        <select id=s-course></select>
        <input id=s-count type=number placeholder="how many" style="width:110px">
        <input id=s-owner placeholder="owner email (opt)" style="width:200px">
        <button onclick=genSeats()>Generate</button>
      </div><div class=muted id=s-msg></div>
      <textarea id=s-codes style="width:100%;height:0;border:0;opacity:0;position:absolute"></textarea>
    </div>
    <div class=card><h2>Batches</h2><table id=t-seats><thead><tr><th>Batch</th><th>Owner</th><th>Total</th><th>Redeemed</th><th>Unused</th></tr></thead><tbody></tbody></table></div>
  </div>

  <div class="panel" id=p-store>
    <div class=card><h2>Store merchandising</h2>
      <p class=muted style="margin-top:-.6rem">Set each offer's category (store bucket), order-bump add-ons, and — for mentorship offers — the cohort a purchase enrolls into. Changes are live immediately.</p>
      <table id=t-store><thead><tr><th>Offer</th><th>Price</th><th>Listed</th><th>Category</th><th>Seats/pack</th><th>Order-bump add-ons</th><th>Cohort enroll</th></tr></thead><tbody></tbody></table>
    </div>
  </div>


  <div class="panel" id=p-sponsors>
    <div class=card><h2>Sponsored access &mdash; free enrollment, no Stripe</h2>
      <p class=muted style="margin-top:-.6rem">For people whose seat someone else paid for: grant recipients, CFD families, scholarships, staff. They are enrolled directly &mdash; no checkout, no card, no $0 payment page. Everyone added here lands in that sponsor's report, together with the matching Circle history.</p>
      <div class=row style="flex-wrap:wrap;gap:.4rem">
        <input id=sp-name placeholder="Sponsor name (e.g. BCBS Illinois)" style="width:230px">
        <select id=sp-kind><option value=grant>grant</option><option value=partner>partner org</option><option value=scholarship>scholarship</option><option value=clinic>clinic / hospital</option><option value=internal>staff / internal</option></select>
        <input id=sp-seats type=number placeholder="seat cap (0 = unlimited)" style="width:170px">
        <input id=sp-legacy placeholder="old Circle codes (e.g. BCBSIL,BCBS)" style="width:230px">
        <button onclick=createSponsor()>Create</button>
      </div>
      <div class=row style="margin-top:.4rem"><select id=sp-courses multiple size=4 style="min-width:420px"></select>
        <span class=muted style="max-width:280px">Hold &#8984;/Ctrl to pick every course this sponsor covers.</span></div>
      <div class=muted id=sp-msg></div>
    </div>
    <div class=card><h2>Sponsors</h2>
      <table id=t-sponsors><thead><tr><th>Sponsor</th><th>Type</th><th>Courses</th><th>Seats</th><th>Share link</th><th></th></tr></thead><tbody></tbody></table>
    </div>
    <div class=card><h2>Add people</h2>
      <div class=row><select id=sp-target></select></div>
      <p class=muted style="margin-bottom:.3rem">Paste emails &mdash; commas, semicolons or one per line. Accounts are created automatically; recipients just get a set-password email.</p>
      <textarea id=sp-emails placeholder="jane@example.com&#10;sam@example.com" style="width:100%;height:110px"></textarea>
      <div class=row style="margin-top:.5rem">
        <button onclick="bulkEnroll(true)">Preview</button>
        <button onclick="bulkEnroll(false)">Enrol them</button>
        <input id=sp-codecount type=number placeholder="# codes" style="width:110px">
        <button class=ghost onclick=makeCodes()>Generate codes instead</button>
      </div>
      <div class=muted id=sp-enroll-msg></div>
      <textarea id=sp-codes style="width:100%;height:0;border:0;opacity:0;position:absolute"></textarea>
    </div>
    <div class=card><h2>Funder report</h2>
      <p class=muted style="margin-top:-.6rem">Everyone a sponsor covered &mdash; new enrollments plus the Circle-era redemptions from its old codes, deduplicated by person. This is the file a funder gets.</p>
      <div class=row><select id=sp-report-target></select><button onclick=loadSponsorReport()>Run</button><button class=ghost onclick=exportSponsorReport()>&#11015; Export CSV</button></div>
      <div id=sp-report-sum class=row style="gap:.5rem;flex-wrap:wrap;margin:.5rem 0"></div>
      <div style="max-height:420px;overflow:auto">
        <table id=t-spreport><thead><tr><th>Name</th><th>Email</th><th>Date</th><th>Granted via</th><th>Source</th></tr></thead><tbody></tbody></table>
      </div>
    </div>
  </div>

  <div class="panel" id=p-circlehist>
    <div class=card><h2>Coupon history from Circle</h2>
      <p class=muted style="margin-top:-.6rem">Every coupon redemption from the old Circle community, archived here before it was shut down &mdash; who redeemed which code, for which course, and when. This is the record for funder and grant reporting. It is history only: nothing here grants access or issues a certificate.</p>
      <div id=ch-summary class=row style="gap:.5rem;flex-wrap:wrap;margin-bottom:.6rem"></div>
      <div class=row style="flex-wrap:wrap;gap:.4rem">
        <input id=chq placeholder="search name or email" style="width:230px" onkeyup="if(event.key==='Enter'){{CHPAGE=1;loadCircleHist()}}">
        <select id=chcode onchange="CHPAGE=1;loadCircleHist()"><option value="">all coupon codes</option></select>
        <button onclick="CHPAGE=1;loadCircleHist()">Filter</button>
        <select id=chper onchange="CHPAGE=1;loadCircleHist()"><option value=50>50 / page</option><option value=100>100 / page</option><option value=250>250 / page</option></select>
        <button class=ghost onclick=exportCircleHist()>&#11015; Export CSV (all matching)</button>
      </div>
      <div style="max-height:520px;overflow:auto;margin-top:.6rem">
        <table id=t-circlehist><thead><tr><th>Code</th><th>Member</th><th>Email</th><th>Course</th><th>Date</th><th>Value</th></tr></thead><tbody></tbody></table>
      </div>
      <div class=row id=chpager style="justify-content:space-between;align-items:center;margin-top:.6rem"></div>
    </div>
    <div class=card><h2>Totals by code</h2>
      <p class=muted style="margin-top:-.6rem">Redemptions counts every use; people counts distinct email addresses (one person can redeem across several courses).</p>
      <table id=t-chcodes><thead><tr><th>Code</th><th>Terms</th><th>Redemptions</th><th>People</th><th></th></tr></thead><tbody></tbody></table>
    </div>
  </div>
</div>
<script>
const API='/api/v1/bbu/admin';
const j=(u,o)=>fetch(API+u,Object.assign({{credentials:'include',headers:{{'Content-Type':'application/json'}}}},o||{{}})).then(r=>r.json());
function esc(s){{return String(s==null?'':s).replace(/[&<>]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]))}}
// tabs
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
  document.querySelectorAll('.panel').forEach(x=>x.classList.remove('on'));
  t.classList.add('on'); document.getElementById('p-'+t.dataset.t).classList.add('on');
  if(t.dataset.t==='cohorts')loadCohorts(); if(t.dataset.t==='seats')loadSeats(); if(t.dataset.t==='store')loadStore();
  if(t.dataset.t==='credentials')loadCredRoster();
  if(t.dataset.t==='circlehist')loadCircleHist();
  if(t.dataset.t==='sponsors')loadSponsors();
}});
// Stripe sync — the platform's products/coupons must exist in Stripe to redeem
function loadStripeSync(){{
  j('/stripe-sync').then(d=>{{
    if(!d||d.detail){{document.getElementById('ss-out').innerHTML='<span class=muted>Could not load.</span>';return;}}
    const warn = d.stripe_mode!=='live' ? ' style="background:#fde8e8;color:#8a1c1c"' : '';
    document.getElementById('ss-out').innerHTML=
      `<span class=badge${{warn}}>Stripe: ${{esc(d.stripe_mode)}} mode</span>`+
      `<span class=badge>${{d.products_in_stripe}}/${{d.products_total}} products</span>`+
      `<span class=badge>${{d.coupons_in_stripe}}/${{d.coupons_active}} active coupons</span>`+
      `<span class=badge>${{d.scoped_coupons}} course-scoped</span>`;
    document.getElementById('ss-msg').textContent = (d.not_yet_in_stripe||[]).length
      ? 'Not in Stripe yet: '+d.not_yet_in_stripe.join(', ') : '';
  }});
}}
function runStripeSync(reset){{
  if(reset && !confirm('Re-create every Stripe coupon and product from scratch?\\n\\nDo this after switching the Stripe key (test to live). Old ids are discarded.'))return;
  document.getElementById('ss-msg').textContent='Syncing…';
  j('/stripe-sync',{{method:'POST',body:JSON.stringify({{reset:!!reset}})}}).then(d=>{{
    if(d.error){{document.getElementById('ss-msg').textContent=d.error;return;}}
    const errs=[...(d.products.errors||[]),...(d.coupons.errors||[])];
    document.getElementById('ss-msg').textContent =
      `Done (${{d.stripe_mode}} mode) — ${{d.products.created}} products, ${{d.coupons.created}} coupons created`+
      (d.coupons.skipped_inactive?`, ${{d.coupons.skipped_inactive}} inactive skipped`:'')+
      (errs.length?` — ${{errs.length}} error(s): ${{errs.map(e=>esc(e.code||e.product)+': '+esc(e.error)).join(' | ')}}`:'');
    loadStripeSync(); loadCoupons&&loadCoupons();
  }});
}}
// Sponsored access — free enrollment with no Stripe in the path
const SPAPI='/api/v1/bbu/sponsors';
let SPONSORS=[];
const spj=(u,o)=>fetch(SPAPI+u,Object.assign({{credentials:'include',headers:{{'Content-Type':'application/json'}}}},o||{{}})).then(r=>r.json());
function loadSponsors(){{
  if(!document.getElementById('sp-courses').options.length){{
    j('/courses').then(cs=>{{document.getElementById('sp-courses').innerHTML=(cs||[]).map(c=>
      `<option value="${{esc(c.course_uuid||c.uuid)}}">${{esc(c.name||c.title)}}</option>`).join('');}});
  }}
  spj('').then(d=>{{
    SPONSORS=Array.isArray(d)?d:[];
    const opts=SPONSORS.map(s=>`<option value="${{s.id}}">${{esc(s.name)}}</option>`).join('');
    document.getElementById('sp-target').innerHTML=opts;
    document.getElementById('sp-report-target').innerHTML=opts;
    document.querySelector('#t-sponsors tbody').innerHTML=SPONSORS.map(s=>{{
      const seats=s.seat_limit?`${{s.seats_used}} / ${{s.seat_limit}}`:`${{s.seats_used}} (no cap)`;
      const link=s.join_enabled&&s.join_token
        ? `<code style="font-size:.72rem">${{location.origin}}${{SPAPI}}/join/${{esc(s.join_token)}}</code>`
        : '<span class=muted>off</span>';
      return `<tr><td><b>${{esc(s.name)}}</b>${{s.legacy_codes?`<br><span class=muted style="font-size:.75rem">Circle: ${{esc(s.legacy_codes)}}</span>`:''}}</td>`+
        `<td>${{esc(s.kind)}}</td><td>${{s.courses}}</td><td>${{seats}}</td><td>${{link}}</td>`+
        `<td><button class=ghost onclick="copyJoin('${{esc(s.join_token)}}')">Copy link</button></td></tr>`;
    }}).join('')||'<tr><td colspan=6 class=muted>No sponsors yet.</td></tr>';
  }});
}}
function copyJoin(t){{ if(!t)return; navigator.clipboard.writeText(location.origin+SPAPI+'/join/'+t);
  document.getElementById('sp-msg').textContent='Share link copied.'; }}
function createSponsor(){{
  const courses=[...document.getElementById('sp-courses').selectedOptions].map(o=>o.value).join(',');
  const name=document.getElementById('sp-name').value.trim();
  if(!name||!courses){{document.getElementById('sp-msg').textContent='Name and at least one course are required.';return;}}
  spj('',{{method:'POST',body:JSON.stringify({{name,kind:document.getElementById('sp-kind').value,
    course_uuids:courses, seat_limit:parseInt(document.getElementById('sp-seats').value||'0',10),
    legacy_codes:document.getElementById('sp-legacy').value.trim(), join_enabled:true}})}}).then(r=>{{
      document.getElementById('sp-msg').textContent=r.ok?'Created ✓':(r.detail||'Error');
      if(r.ok){{document.getElementById('sp-name').value='';loadSponsors();}}
    }});
}}
function bulkEnroll(dry){{
  const id=document.getElementById('sp-target').value;
  const text=document.getElementById('sp-emails').value.trim();
  if(!id||!text)return;
  document.getElementById('sp-enroll-msg').textContent=dry?'Checking…':'Enrolling…';
  spj('/'+id+'/bulk-enroll',{{method:'POST',body:JSON.stringify({{text,dry_run:!!dry}})}}).then(r=>{{
    if(r.detail){{document.getElementById('sp-enroll-msg').textContent=r.detail;return;}}
    const c=r.counts||{{}};
    document.getElementById('sp-enroll-msg').textContent=
      (dry?'Preview — ':'Done — ')+Object.entries(c).map(([k,v])=>`${{v}} ${{k.replace(/_/g,' ')}}`).join(', ');
    if(!dry)loadSponsors();
  }});
}}
function makeCodes(){{
  const id=document.getElementById('sp-target').value;
  const n=parseInt(document.getElementById('sp-codecount').value||'0',10);
  if(!id||!n)return;
  spj('/'+id+'/codes',{{method:'POST',body:JSON.stringify({{count:n}})}}).then(r=>{{
    if(r.detail){{document.getElementById('sp-enroll-msg').textContent=r.detail;return;}}
    const ta=document.getElementById('sp-codes'); ta.value=(r.codes||[]).join('  ');
    ta.select(); try{{document.execCommand('copy')}}catch(e){{}}
    document.getElementById('sp-enroll-msg').innerHTML=`Generated ${{r.count}} codes (copied):<br><code>${{esc((r.codes||[]).join('  '))}}</code>`;
  }});
}}
function loadSponsorReport(){{
  const id=document.getElementById('sp-report-target').value; if(!id)return;
  spj('/'+id+'/report').then(d=>{{
    if(d.detail){{document.getElementById('sp-report-sum').textContent=d.detail;return;}}
    document.getElementById('sp-report-sum').innerHTML=
      `<span class=badge>${{d.unique_people}} people served</span>`+
      `<span class=badge>${{d.from_platform}} on this platform</span>`+
      `<span class=badge>${{d.from_circle}} from Circle</span>`;
    document.querySelector('#t-spreport tbody').innerHTML=(d.rows||[]).map(r=>
      `<tr><td>${{esc(r.name)}}</td><td>${{esc(r.email)}}</td><td>${{esc(r.date)}}</td>`+
      `<td>${{esc(r.via)}}</td><td>${{esc(r.source)}}</td></tr>`).join('')
      ||'<tr><td colspan=5 class=muted>Nobody yet.</td></tr>';
  }});
}}
function exportSponsorReport(){{
  const id=document.getElementById('sp-report-target').value; if(!id)return;
  window.open(SPAPI+'/'+id+'/report?fmt=csv','_blank');
}}
// Circle coupon history (archived before Circle was shut down)
let CHPAGE=1, CHCODES=0;
function chQS(){{
  const p=new URLSearchParams();
  const q=document.getElementById('chq').value.trim(); if(q)p.set('q',q);
  const c=document.getElementById('chcode').value; if(c)p.set('code',c);
  return p.toString();
}}
function chGo(n){{CHPAGE=n;loadCircleHist();document.querySelector('#t-circlehist').scrollIntoView({{block:'nearest'}});}}
function chPick(code){{document.getElementById('chcode').value=code;CHPAGE=1;loadCircleHist();
  document.querySelector('#t-circlehist').scrollIntoView({{block:'nearest'}});}}
function loadCircleHist(){{
  const per=document.getElementById('chper').value, qs=chQS();
  j('/circle-history?page='+CHPAGE+'&per_page='+per+(qs?'&'+qs:'')).then(d=>{{
    if(!d||d.detail){{document.querySelector('#t-circlehist tbody').innerHTML='<tr><td colspan=6 class=muted>Could not load.</td></tr>';return;}}
    document.getElementById('ch-summary').innerHTML=
      `<span class=badge>${{d.total}} redemptions</span>`+
      `<span class=badge>${{d.unique_people}} people</span>`+
      `<span class=badge>${{(d.by_code||[]).length}} codes</span>`;
    document.querySelector('#t-circlehist tbody').innerHTML=(d.rows||[]).map(r=>
      `<tr><td><b>${{esc(r.code)}}</b></td><td>${{esc(r.name)}}</td><td>${{esc(r.email)}}</td>`+
      `<td>${{esc(r.course)}}</td><td>${{esc(r.date)}}</td><td>${{esc(r.amount)}}</td></tr>`
    ).join('')||'<tr><td colspan=6 class=muted>Nothing matches.</td></tr>';
    const pg=[];
    if(d.page>1)pg.push(`<button class=ghost onclick="chGo(${{d.page-1}})">&larr; Prev</button>`);
    pg.push(`<span class=muted>Page ${{d.page}} of ${{d.pages}}</span>`);
    if(d.page<d.pages)pg.push(`<button class=ghost onclick="chGo(${{d.page+1}})">Next &rarr;</button>`);
    document.getElementById('chpager').innerHTML=pg.join(' ');
    // the code dropdown + rollup only need building once (they ignore the filter)
    if(!CHCODES && !chQS()){{
      CHCODES=1;
      document.getElementById('chcode').innerHTML='<option value="">all coupon codes</option>'+
        (d.by_code||[]).map(c=>`<option value="${{esc(c.code)}}">${{esc(c.code)}} (${{c.redemptions}})</option>`).join('');
      document.querySelector('#t-chcodes tbody').innerHTML=(d.by_code||[]).map(c=>
        `<tr><td><b>${{esc(c.code)}}</b></td><td>${{esc(c.terms)}}</td><td>${{c.redemptions}}</td><td>${{c.people}}</td>`+
        `<td><button class=ghost onclick="chPick('${{esc(c.code)}}')">View</button></td></tr>`).join('');
    }}
  }});
}}
function exportCircleHist(){{
  const qs=chQS(); window.open(API+'/circle-history?fmt=csv'+(qs?'&'+qs:''),'_blank');
}}
// Store merchandising
const CATS=['','Birth Classes','Postpartum Classes','Spanish Classes','Professional Training','Mentorship','Bundles','eBooks'];
let STORE=[]; let COHORTS=[];
function cohortSel(o){{
  const cur = o.cohort_id ? ('id:'+o.cohort_id) : (o.cohort_program ? ('prog:'+o.cohort_program) : '');
  let opts = `<option value="" ${{cur===''?'selected':''}}>— not a cohort —</option>`
    + `<option value="prog:doula" ${{cur==='prog:doula'?'selected':''}}>Next open Doula Mentorship</option>`
    + `<option value="prog:agency" ${{cur==='prog:agency'?'selected':''}}>Next open Agency cohort</option>`;
  const specific = COHORTS.filter(c=>c.status!=='closed');
  if(specific.length) opts += `<optgroup label="Specific cohort">`
    + specific.map(c=>`<option value="id:${{c.id}}" ${{cur==='id:'+c.id?'selected':''}}>${{esc(c.name)}} (${{esc(c.program)}}·${{esc(c.status)}})</option>`).join('') + `</optgroup>`;
  return `<select onchange="saveCohort(${{o.id}},this.value)">${{opts}}</select>`;
}}
function renderStore(){{
  document.querySelector('#t-store tbody').innerHTML=STORE.map(o=>{{
    const opts=CATS.map(c=>`<option value="${{esc(c)}}" ${{o.category===c?'selected':''}}>${{c||'—'}}</option>`).join('');
    const bumps=STORE.filter(x=>x.id!==o.id).map(x=>`<label style="display:block;font-size:.78rem"><input type=checkbox ${{o.bump_ids.includes(x.id)?'checked':''}} onchange="toggleBump(${{o.id}},${{x.id}},this.checked)"> ${{esc(x.name)}} ($${{x.price}})</label>`).join('');
    const n=o.bump_ids.length;
    const listed=`<label style="cursor:pointer"><input type=checkbox ${{o.public?'checked':''}} onchange="saveListed(${{o.id}},this.checked)"> ${{o.public?'live':'hidden'}}</label>`;
    const seats=`<input type=number min=0 value="${{o.seat_count||0}}" title="0 = not a seat pack; N = buying it mints N shareable seats" style="width:56px" onchange="saveSeats(${{o.id}},this.value)">`;
    const price=`<span style="color:#6b6f79">$</span><input type=number min=0 step="0.01" value="${{o.price}}" title="Price in dollars. Saves on change; applies to the next checkout." style="width:84px;font-weight:700" onchange="savePrice(${{o.id}},this.value,this)">`;
    return `<tr><td><b>${{esc(o.name)}}</b></td><td>${{price}}</td>`
      +`<td>${{listed}}</td>`
      +`<td><select onchange="saveCat(${{o.id}},this.value)">${{opts}}</select></td>`
      +`<td>${{seats}}</td>`
      +`<td><details><summary style="cursor:pointer;color:#3a91c6">${{n?n+' add-on'+(n>1?'s':''):'none'}}</summary><div style="max-height:150px;overflow:auto;padding:.3rem 0">${{bumps}}</div></details></td>`
      +`<td>${{cohortSel(o)}}</td></tr>`;
  }}).join('');
}}
function loadStore(){{Promise.all([j('/offers'),j('/cohorts')]).then(([d,c])=>{{
  STORE=d||[]; COHORTS=c||[]; renderStore();
}})}}
function saveCohort(id,val){{
  const o=STORE.find(x=>x.id===id); if(!o)return;
  let body={{cohort_program:'',cohort_id:0}};
  if(val.startsWith('prog:')) body.cohort_program=val.slice(5);
  else if(val.startsWith('id:')) body.cohort_id=parseInt(val.slice(3),10);
  o.cohort_program=body.cohort_program; o.cohort_id=body.cohort_id||null;
  j('/offers/'+id+'/merchandising',{{method:'POST',body:JSON.stringify(body)}});
}}
function savePrice(id,val,el){{
  const v=parseFloat(val);
  if(!(v>=0)){{alert('Enter a valid price');return}}
  const o=STORE.find(x=>x.id===id); if(o)o.price=v;
  const prev=el.style.background; el.style.background='#fff8dd';
  j('/offers/'+id+'/merchandising',{{method:'POST',body:JSON.stringify({{price:v}})}})
    .then(()=>{{el.style.background='#e6f7ec';setTimeout(()=>{{el.style.background=prev}},1200)}})
    .catch(()=>{{el.style.background='#fdeaea';alert('Could not save price')}});
}}
function saveListed(id,on){{const o=STORE.find(x=>x.id===id);if(o)o.public=on;
  j('/offers/'+id+'/merchandising',{{method:'POST',body:JSON.stringify({{public:on}})}}).then(()=>renderStore());}}
function saveSeats(id,val){{const o=STORE.find(x=>x.id===id);if(o)o.seat_count=+val||0;
  j('/offers/'+id+'/merchandising',{{method:'POST',body:JSON.stringify({{seat_count:+val||0}})}});}}
function saveCat(id,cat){{j('/offers/'+id+'/merchandising',{{method:'POST',body:JSON.stringify({{category:cat}})}})}}
function toggleBump(id,bumpId,on){{
  const o=STORE.find(x=>x.id===id); if(!o)return;
  o.bump_ids = on ? [...new Set([...o.bump_ids,bumpId])] : o.bump_ids.filter(x=>x!==bumpId);
  j('/offers/'+id+'/merchandising',{{method:'POST',body:JSON.stringify({{bump_ids:o.bump_ids}})}});
}}
// Coupons
function loadCoupons(){{j('/coupons').then(d=>{{
  document.querySelector('#t-coupons tbody').innerHTML=(d||[]).map(c=>
    `<tr><td><b>${{esc(c.code)}}</b></td><td>${{esc(c.value)}}</td><td>${{c.min?'$'+c.min:'—'}}</td>`
    +`<td>${{c.times_redeemed}}${{c.max_redemptions?'/'+c.max_redemptions:''}}</td><td>${{c.expires_at||'—'}}</td>`
    +`<td><span class="badge ${{c.active?'on-b':'off-b'}}">${{c.active?'Active':'Off'}}</span></td>`
    +`<td><button class=ghost onclick="toggleCoupon(${{c.id}})">${{c.active?'Deactivate':'Activate'}}</button></td></tr>`).join('');
}})}}
function createCoupon(){{
  const kind=document.getElementById('c-kind').value, v=+document.getElementById('c-val').value;
  const body={{code:document.getElementById('c-code').value,kind:kind,
    percent_off:kind==='percent'?v:0, amount_off:kind==='amount'?v:0,
    min_amount:+document.getElementById('c-min').value||0,
    max_redemptions:+document.getElementById('c-max').value||0,
    expires_at:document.getElementById('c-exp').value?document.getElementById('c-exp').value+'T23:59:59+00:00':''}};
  j('/coupons',{{method:'POST',body:JSON.stringify(body)}}).then(r=>{{
    document.getElementById('c-msg').textContent=r.ok?'Created ✓':(r.detail||'Error'); if(r.ok)loadCoupons();}});
}}
function toggleCoupon(id){{j('/coupons/'+id+'/toggle',{{method:'POST'}}).then(loadCoupons)}}
// Cohorts
let curCohort=null;
function progDefaults(){{
  // sensible default access window per program (editable)
  const el=document.getElementById('co-access');
  if(!el.value) el.value = document.getElementById('co-prog').value==='agency'?12:6;
}}
function zoomSelChange(){{
  const s=document.getElementById('co-zoom-sel').value, t=document.getElementById('co-zoom');
  if(s==='__manual__'){{t.style.display='';t.value='';t.focus();}} else {{t.style.display='none';}}
}}
function loadZoomMeetings(){{
  j('/zoom-meetings').then(d=>{{
    const opts=['<option value="">— Zoom meeting (none) —</option>']
      .concat((d||[]).map(m=>`<option value="${{m.id}}">${{esc(m.topic)}}${{m.kind==='webinar'?' (webinar)':''}}</option>`))
      .concat(['<option value="__manual__">✎ Enter ID manually…</option>']);
    document.getElementById('co-zoom-sel').innerHTML=opts.join('');
  }}).catch(()=>{{}});
}}
function loadCohorts(){{
  j('/courses').then(cs=>{{document.getElementById('co-course').innerHTML='<option value="">— course (unlocks) —</option>'+cs.map(c=>`<option value="${{c.course_uuid}}">${{esc(c.name)}}</option>`).join('')}});
  j('/communities').then(cs=>{{document.getElementById('co-comm').innerHTML='<option value="">— community (prompts) —</option>'+(cs||[]).map(c=>`<option value="${{c.id}}">${{esc(c.name)}}</option>`).join('')}});
  loadZoomMeetings();
  loadWaitlist();
  j('/cohorts').then(d=>{{
    document.querySelector('#t-cohorts tbody').innerHTML=(d||[]).map(c=>{{
      const dates=(c.start_date||'').slice(0,10)+(c.end_date?' → '+c.end_date.slice(0,10):'');
      const zoom=c.zoom_meeting_id?' 🎥':''; const wb=c.workbook_url?' 📓':'';
      const STAT=['open','full','running','closed'];
      const statSel=`<select onchange="saveCohortField(${{c.id}},'status',this.value)">`+STAT.map(s=>`<option ${{c.status===s?'selected':''}}>${{s}}</option>`).join('')+`</select>`;
      const capIn=`<input type=number min=0 value="${{c.capacity||0}}" title="0 = unlimited" style="width:58px" onchange="saveCap(${{c.id}},this.value)">`;
      return `<tr><td><b>${{esc(c.name)}}</b>${{zoom}}${{wb}}</td><td>${{esc(c.program)}}</td><td class=muted style=font-size:.8rem>${{esc(dates||'—')}}</td>`
      +`<td>${{c.active_members}}</td><td>${{capIn}}</td><td>${{esc(c.credential_type||'—')}}</td>`
      +`<td>${{c.prompts||0}}</td><td class=muted style=font-size:.8rem>${{esc((c.access_until||'—'))}}</td><td>${{statSel}}</td>`
      +`<td><button class=ghost onclick="openRoster(${{c.id}},'${{esc(c.name).replace(/'/g,"")}}')">Roster</button></td></tr>`;
    }}).join('');
  }});
}}
function saveCap(id,val){{
  j('/cohorts/'+id+'/update',{{method:'POST',body:JSON.stringify({{capacity:+val||0}})}}).then(r=>{{
    const inv=(r&&r.invited)||0; document.getElementById('lc-msg').textContent=
      'Capacity updated'+(r&&r.promoted?(' · '+r.promoted+' waitlisted member(s) promoted'):'')+(inv?(' · '+inv+' waitlist prospect(s) invited'):'');
    loadCohorts();}});
}}
function saveCohortField(id,field,val){{
  const b={{}};b[field]=val;
  j('/cohorts/'+id+'/update',{{method:'POST',body:JSON.stringify(b)}}).then(()=>loadCohorts());
}}
function createCohort(){{
  const gv=id=>document.getElementById(id).value;
  const zsel=gv('co-zoom-sel'); const zoom = zsel==='__manual__' ? gv('co-zoom') : zsel;
  const body={{name:gv('co-name'),program:gv('co-prog'),course_uuid:gv('co-course'),
    community_id:gv('co-comm')||null,capacity:+gv('co-cap')||0,access_months:+gv('co-access')||0,
    credential_type:gv('co-cred'),start_date:gv('co-start'),end_date:gv('co-end'),
    zoom_meeting_id:zoom,workbook_url:gv('co-workbook')}};
  if(!body.name){{document.getElementById('co-msg').textContent='Name required';return;}}
  j('/cohorts',{{method:'POST',body:JSON.stringify(body)}}).then(r=>{{document.getElementById('co-msg').textContent=r.ok?'Created ✓ (prompts seeded)':'Error';loadCohorts();}});
}}
function runLifecycle(){{
  document.getElementById('lc-msg').textContent='Running…';
  j('/cohorts/run-lifecycle',{{method:'POST',body:JSON.stringify({{dry_run:false}})}}).then(r=>{{
    document.getElementById('lc-msg').textContent=`Started ${{r.started_count||0}} · closed ${{r.expired_count||0}} · prompts posted ${{r.prompts_posted||0}} · recordings +${{r.recordings_added||0}}`;
    loadCohorts();}});
}}
function loadWaitlist(){{j('/cohort-waitlist').then(d=>{{
  const badge=s=>`<span style="font-size:.75rem;padding:2px 8px;border-radius:10px;background:${{s==='waiting'?'#eef3f7':'#e6f4ea'}};color:${{s==='waiting'?'#3a5566':'#1c7a3e'}}">${{esc(s)}}</span>`;
  document.querySelector('#t-waitlist tbody').innerHTML=(d||[]).map(w=>
    `<tr><td>${{esc(w.name||'—')}}</td><td>${{esc(w.email)}}</td><td>${{esc(w.phone||'—')}}</td><td>${{esc(w.program)}}</td><td>${{badge(w.status)}}</td><td class=muted style=font-size:.8rem>${{esc(w.created_at)}}</td></tr>`
  ).join('')||'<tr><td colspan=6 class=muted>No one waiting.</td></tr>';
}})}}
function notifyWaitlist(){{
  j('/cohort-waitlist/notify',{{method:'POST',body:JSON.stringify({{program:'doula',count:1}})}}).then(r=>{{
    const n=(r.notified||[]).length; alert(n?('Invited: '+r.notified.map(x=>x.email).join(', ')):'No one waiting to notify.');loadWaitlist();}});
}}
function openRoster(id,name){{curCohort=id;document.getElementById('roster-card').style.display='block';
  document.getElementById('roster-name').textContent=name;loadRoster();}}
function loadRoster(){{j('/cohorts/'+curCohort+'/roster').then(d=>{{
  document.querySelector('#t-roster tbody').innerHTML=(d||[]).map(m=>`<tr><td>${{esc(m.name)}}</td><td>${{esc(m.email)}}</td><td>${{esc(m.status)}}</td></tr>`).join('');}})}}
function cohortAct(action){{
  j('/cohorts/'+curCohort+'/action',{{method:'POST',body:JSON.stringify({{action:action,email:document.getElementById('co-email').value}})}}).then(()=>{{loadRoster();loadCohorts();}});
}}
function closeCohort(){{
  if(!confirm('Close this cohort and revoke all members\\' access?'))return;
  j('/cohorts/'+curCohort+'/action',{{method:'POST',body:JSON.stringify({{action:'close'}})}}).then(()=>{{loadRoster();loadCohorts();}});
}}
// Credentials
function rosterQS(){{
  const p=new URLSearchParams();
  const q=document.getElementById('rq').value.trim(); if(q)p.set('q',q);
  const st=document.getElementById('rstatus').value; if(st)p.set('status',st);
  const ty=document.getElementById('rtype').value; if(ty)p.set('ctype',ty);
  const so=document.getElementById('rsource').value; if(so)p.set('source',so);
  const ex=document.getElementById('rexp').value; if(ex&&ex!=='0')p.set('expiring_days',ex);
  return p.toString();
}}
let RPAGE=1;
function goPage(n){{RPAGE=n;loadCredRoster();document.querySelector('#t-credroster').scrollIntoView({{block:'nearest'}});}}
function loadCredRoster(){{
  const per=document.getElementById('rper').value||50;
  j('/credentials/roster?'+rosterQS()+'&page='+RPAGE+'&per_page='+per).then(d=>{{
    const s=d.summary||{{}};
    const chip=(l,v,c)=>`<span style="background:${{c}};border-radius:999px;padding:.25rem .7rem;font-size:.8rem;font-weight:700">${{l}}: ${{v||0}}</span>`;
    document.getElementById('cr-summary').innerHTML=
      chip('Total',s.total,'#eaf2f9')+chip('Full',s.full,'#dff5e6')+chip('Provisional',s.provisional,'#fff2d6')
      +chip('Lapsed',s.lapsed,'#fde8e8')+chip('Expired',s.expired,'#fde8e8')
      +chip('Expiring ≤30d',s.expiring_30d,'#ffe0b2')+chip('Expiring ≤90d',s.expiring_90d,'#f1e4ff');
    document.querySelector('#t-credroster tbody').innerHTML=(d.rows||[]).map(r=>{{
      const dl=r.days_to_expiry;
      const col=dl===null?'#6b6f79':(dl<0?'#b3261e':(dl<=30?'#b26a00':(dl<=90?'#7a5b12':'#1c7a41')));
      const badge=`<span style="padding:.15rem .55rem;border-radius:999px;font-size:.75rem;font-weight:700;background:${{r.status==='full'?'#dff5e6':(r.status==='provisional'?'#fff2d6':'#fde8e8')}}">${{esc(r.status)}}</span>`;
      return `<tr><td><b>${{esc(r.name)}}</b><br><span class=muted style="font-size:.8rem">${{esc(r.email)}}</span></td>`
        +`<td>${{esc(r.type)}}</td><td style="font-size:.82rem">${{esc(r.track)}}</td><td>${{badge}}</td>`
        +`<td>${{esc(r.expires||'—')}}</td>`
        +`<td style="color:${{col}};font-weight:700">${{dl===null?'—':(dl<0?Math.abs(dl)+'d ago':dl+'d')}}</td></tr>`;
    }}).join('')||'<tr><td colspan=6 class=muted>No credentials match those filters.</td></tr>';
    const pg=document.getElementById('rpager');
    if(!d.total){{pg.innerHTML='';return;}}
    const btn=(lbl,n,dis)=>`<button class=ghost ${{dis?'disabled style="opacity:.4;cursor:default"':''}} ${{dis?'':'onclick=goPage('+n+')'}}>${{lbl}}</button>`;
    let nums='';
    const span=2, from=Math.max(1,d.page-span), to=Math.min(d.pages,d.page+span);
    if(from>1) nums+=btn('1',1,false)+(from>2?'<span class=muted style="padding:0 .3rem">…</span>':'');
    for(let i=from;i<=to;i++) nums+= i===d.page
      ? `<button style="background:${{'#113d5d'}};color:#fff;font-weight:700">${{i}}</button>`
      : btn(String(i),i,false);
    if(to<d.pages) nums+=(to<d.pages-1?'<span class=muted style="padding:0 .3rem">…</span>':'')+btn(String(d.pages),d.pages,false);
    pg.innerHTML=`<span class=muted>Showing <b>${{d.showing[0]}}–${{d.showing[1]}}</b> of <b>${{d.total}}</b></span>`
      +`<span style="display:flex;gap:.25rem;align-items:center">${{btn('‹ Prev',d.page-1,d.page<=1)}}${{nums}}${{btn('Next ›',d.page+1,d.page>=d.pages)}}</span>`;
  }});
}}
function exportRoster(){{
  const qs=rosterQS(); window.open(API+'/credentials/roster?fmt=csv'+(qs?'&'+qs:''),'_blank');
}}
function loadCred(){{
  j('/credentials?email='+encodeURIComponent(document.getElementById('cr-email').value)).then(d=>{{
    if(d.detail){{document.getElementById('cr-out').innerHTML='<span class=muted>'+esc(d.detail)+'</span>';return;}}
    const creds=(d.credentials||[]).map(c=>`<tr><td>${{esc(c.credential_type)}}</td><td><span class="badge on-b">${{esc(c.status)}}</span></td><td>${{(c.issued_at||'').slice(0,10)}}</td><td>${{(c.full_expires_at||c.provisional_expires_at||'').slice(0,10)}}</td></tr>`).join('');
    document.getElementById('cr-out').innerHTML=`<p class=muted>CEU total: <b>${{d.ceu_total}}</b></p><table><thead><tr><th>Type</th><th>Status</th><th>Issued</th><th>Valid through</th></tr></thead><tbody>${{creds||'<tr><td colspan=4 class=muted>No credentials</td></tr>'}}</tbody></table>`;
  }});
}}
function credAct(action,mode){{
  const body={{action:action,mode:mode,email:document.getElementById('cra-email').value,
    credential_type:document.getElementById('cra-type').value,count:+document.getElementById('cra-ceu').value||0}};
  j('/credentials/action',{{method:'POST',body:JSON.stringify(body)}}).then(r=>{{
    document.getElementById('cra-msg').textContent=r.ok?('Done ✓'+(r.ceu_total!=null?' (CEU: '+r.ceu_total+')':'')):(r.reason||r.detail||'Error');}});
}}
// Seats
function loadSeats(){{
  j('/courses').then(cs=>{{document.getElementById('s-course').innerHTML='<option value="">— course —</option>'+cs.map(c=>`<option value="${{c.course_uuid}}">${{esc(c.name)}}</option>`).join('')}});
  j('/seats').then(d=>{{document.querySelector('#t-seats tbody').innerHTML=(d||[]).map(b=>`<tr><td><b>${{esc(b.batch_label)}}</b></td><td>${{esc(b.owner_email||'—')}}</td><td>${{b.total}}</td><td>${{b.redeemed}}</td><td>${{b.unused}}</td></tr>`).join('');}});
}}
function genSeats(){{
  const body={{batch_label:document.getElementById('s-label').value,course_uuids:[document.getElementById('s-course').value].filter(Boolean),
    count:+document.getElementById('s-count').value||1,owner_email:document.getElementById('s-owner').value}};
  j('/seats/generate',{{method:'POST',body:JSON.stringify(body)}}).then(r=>{{
    if(r.codes){{document.getElementById('s-msg').innerHTML='Generated '+r.count+' codes:<br><code>'+r.codes.join('  ')+'</code>';loadSeats();}}
    else document.getElementById('s-msg').textContent=r.detail||'Error';}});
}}
loadCoupons(); loadStripeSync();
</script></body></html>"""
