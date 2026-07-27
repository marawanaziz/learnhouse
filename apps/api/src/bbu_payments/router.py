"""BBU native-Stripe payments — API router + branded storefront.

Endpoints (mounted at /api/v1/bbu):
  GET  /store                      BBU-branded storefront (HTML)
  GET  /buy/{course_uuid}          branded checkout landing for one course (HTML)
  GET  /success                    post-payment confirmation (HTML)
  GET  /products                   JSON list of purchasable products
  POST /checkout                   create a Stripe Checkout Session -> {url}
  POST /webhook                    Stripe webhook: mark order paid + enroll

Clean-room: no imports from apps/api/ee. Uses the stripe SDK directly with
BBU_STRIPE_* env vars. HSA/FSA + Klarna surface automatically via
automatic_payment_methods.
"""
import os
import json
import hashlib
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

# BBU certificate template images (the client's exact Canva artwork). Served
# from the API because the Next standalone build doesn't reliably pick up new
# public/ subfolders; the API file-serving path is proven (e-book downloads).
CERT_TEMPLATE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "cert_templates")
)

from src.core.events.database import get_db_session
from src.db.courses.courses import Course
from src.bbu_payments.models import BBUProduct, BBUOrder
from src.bbu_cohorts.models import BBUCohort
from src.bbu_payments.branding import store_page, checkout_page, success_page
from src.bbu_payments import affiliates as aff
from src.bbu_payments import coupons as _coupon_svc

REF_COOKIE = "bbu_ref"

router = APIRouter()

stripe.api_key = os.environ.get("BBU_STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.environ.get("BBU_STRIPE_WEBHOOK_SECRET", "")
PUB_KEY = os.environ.get("BBU_STRIPE_PUBLISHABLE_KEY", "")


def _as_dict(obj):
    """Convert a Stripe object to a plain nested dict. stripe-python v15 objects
    don't reliably support .get()/dict(), so normalize before use. Plain dicts
    (unsigned webhook path) pass through unchanged."""
    if isinstance(obj, dict):
        return obj
    for m in ("to_dict_recursive", "to_dict"):
        fn = getattr(obj, m, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                pass
    return obj


def _base_url(request: Request) -> str:
    # Prefer the configured domain so redirects are correct behind the proxy.
    domain = os.environ.get("LEARNHOUSE_DOMAIN", request.url.netloc)
    scheme = "https" if os.environ.get("LEARNHOUSE_SSL", "true") == "true" else "http"
    return f"{scheme}://{domain}"


async def _list_products(db: AsyncSession, org_id: int = 1):
    rows = (await db.execute(
        select(BBUProduct).where(BBUProduct.org_id == org_id, BBUProduct.public == True)  # noqa: E712
    )).scalars().all()
    return rows



async def _visible_products(request: Request, db: AsyncSession, rows: list,
                            audience: str = "", org_id: int = 1) -> list:
    """Apply the audience filter for whoever is asking.

    Best-effort on identity: the storefront is reachable signed-out, and failing
    to resolve a user must fall back to the public catalogue rather than 500 or
    show an empty shop.
    """
    from src.bbu_payments import audiences as aud
    uid = 0
    try:
        from src.security.auth import get_current_user, resolve_acting_user_id
        uid = resolve_acting_user_id(await get_current_user(request, db)) or 0
    except Exception:
        uid = 0
    try:
        return await aud.filter_products(db, rows, user_id=uid, org_id=org_id,
                                         audience=audience)
    except Exception:
        return rows


async def _upcoming_cohorts(db: AsyncSession, org_id: int, program: str = "") -> list:
    """Every cohort a buyer could still join, soonest first.

    Buyers were paying without seeing which dates they were signing up for and
    only found out afterwards; the page showed a single yes/no availability flag.
    """
    from datetime import date as _date
    from src.bbu_cohorts import service as cohort_svc
    out = []
    try:
        today = _date.today().isoformat()
        q = select(BBUCohort).where(BBUCohort.org_id == org_id,
                                    BBUCohort.status.in_(("open", "full")))
        if program:
            q = q.where(BBUCohort.program == program)
        for c in (await db.execute(q)).scalars().all():
            if c.end_date and c.end_date < today:
                continue
            taken = await cohort_svc.active_count(db, c.id)
            out.append({
                "id": c.id, "name": c.name, "program": c.program,
                "start_date": c.start_date, "end_date": c.end_date,
                "seats_left": (c.capacity - taken) if c.capacity else None,
                "full": bool(c.capacity and taken >= c.capacity),
            })
        out.sort(key=lambda x: (x["start_date"] or "9999"))
    except Exception:
        return []
    return out


@router.get("/cert-template/{name}")
async def cert_template(name: str):
    """Serve a BBU certificate template PNG (same-origin so html2canvas can
    read it for the PDF export)."""
    safe = os.path.basename(name)
    if not (safe.startswith("bbu_cert-") and safe.endswith(".png")):
        raise HTTPException(404, "Not found")
    path = os.path.join(CERT_TEMPLATE_DIR, safe)
    if not os.path.exists(path):
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@router.get("/products")
async def products(request: Request, audience: str = "",
                   db_session: AsyncSession = Depends(get_db_session)):
    rows = await _list_products(db_session)
    rows = await _visible_products(request, db_session, rows, audience)
    # Buyers of a cohort product need to see which dates they can actually join
    # before they pay, not a single yes/no availability flag afterwards.
    programs = {getattr(p, "cohort_program", "") or "" for p in rows}
    cohorts_by_program = {}
    for prog in programs:
        if prog:
            cohorts_by_program[prog] = await _upcoming_cohorts(db_session, 1, prog)
    return [
        {
            "id": p.id, "name": p.name, "kind": p.kind,
            "price_cents": p.price_cents, "currency": p.currency,
            "description": p.description, "image_url": p.image_url,
            "course_uuids": [u for u in p.course_uuids.split(",") if u],
            "cohort_program": getattr(p, "cohort_program", "") or "",
            "upcoming_cohorts": cohorts_by_program.get(
                getattr(p, "cohort_program", "") or "", []
            ) if (getattr(p, "cohort_program", "") or getattr(p, "cohort_id", None)) else [],
        }
        for p in rows
    ]


def _ip_hash(request: Request) -> str:
    ip = (request.client.host if request.client else "") or ""
    return hashlib.sha256(ip.encode()).hexdigest()[:32]


async def _apply_ref(request: Request, response, db_session: AsyncSession):
    """If a ?ref=CODE is present and valid, set the attribution cookie and log
    the click. Returns the ref code that is in effect (query or existing cookie)."""
    ref = (request.query_params.get("ref") or "").strip()
    if ref:
        affiliate = await aff.get_affiliate_by_ref(db_session, ref)
        if affiliate:
            settings = await aff.get_settings(db_session)
            response.set_cookie(
                REF_COOKIE, ref, max_age=settings.attribution_window_days * 86400,
                httponly=True, samesite="lax", secure=True,
            )
            try:
                await aff.log_click(db_session, affiliate, str(request.url.path), _ip_hash(request))
            except Exception:
                pass
            return ref
    return request.cookies.get(REF_COOKIE, "")


@router.get("/r/{ref_code}")
async def referral_redirect(ref_code: str, request: Request,
                            db_session: AsyncSession = Depends(get_db_session)):
    """Affiliate referral entry point: set the attribution cookie, then send the
    visitor into the site.

    The affiliate link used to be `{base}/?ref=CODE` — the site root, which is
    served by the Next frontend and never touches this router. The cookie was
    therefore never set and attribution silently dropped for every referral that
    didn't happen to land on the API-served store page. Routing through here
    guarantees the click is recorded whatever the visitor does next, signed in
    or not.

    `?next=` allows deep links (a specific class) while keeping attribution.
    """
    from fastapi.responses import RedirectResponse

    nxt = (request.query_params.get("next") or "/").strip()
    # only ever redirect within this site
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    resp = RedirectResponse(url=f"{_base_url(request)}{nxt}", status_code=302)

    affiliate = await aff.get_affiliate_by_ref(db_session, (ref_code or "").strip())
    if affiliate:
        settings = await aff.get_settings(db_session)
        resp.set_cookie(REF_COOKIE, affiliate.ref_code,
                        max_age=settings.attribution_window_days * 86400,
                        httponly=True, samesite="lax", secure=True)
        try:
            await aff.log_click(db_session, affiliate, str(request.url.path),
                                _ip_hash(request))
        except Exception:
            pass
    return resp


@router.get("/store", response_class=HTMLResponse)
async def store(request: Request, audience: str = "",
                db_session: AsyncSession = Depends(get_db_session)):
    rows = await _list_products(db_session)
    rows = await _visible_products(request, db_session, rows, audience)
    # attach upcoming dates to cohort products so the storefront can render them
    for p in rows:
        prog = getattr(p, "cohort_program", "") or ""
        if prog or getattr(p, "cohort_id", None):
            try:
                p._upcoming_cohorts = await _upcoming_cohorts(db_session, 1, prog)
            except Exception:
                p._upcoming_cohorts = []
    resp = HTMLResponse(store_page(rows, _base_url(request)))
    await _apply_ref(request, resp, db_session)
    return resp


@router.get("/buy/{product_id}", response_class=HTMLResponse)
async def buy(product_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    p = (await db_session.execute(select(BBUProduct).where(BBUProduct.id == product_id))).scalars().first()
    if not p:
        raise HTTPException(404, "Product not found")

    # ?coupon= drives the webinar offer pages: the discount rides the URL so the
    # attendee never types a code. An unusable code fails loudly here rather than
    # quietly rendering list price and charging it.
    coupon_code = (request.query_params.get("coupon") or "").strip()
    discount_cents = 0
    if coupon_code:
        c = await _coupon_svc.find_by_code(db_session, p.org_id, coupon_code)
        ok, reason = (_coupon_svc.validate_for(c, p.id, p.price_cents) if c
                      else (False, "that code doesn't exist"))
        if not ok:
            raise HTTPException(400, f"This discount link isn't valid — {reason}")
        discount_cents = _coupon_svc.compute_discount_cents(c, p.price_cents)

    # cohort products: if every upcoming cohort is full, render the waitlist form
    sold_out, program = False, ""
    prog = getattr(p, "cohort_program", "") or ""
    if prog or getattr(p, "cohort_id", None):
        from src.bbu_cohorts import service as cohort_svc
        pinned = getattr(p, "cohort_id", None)
        if pinned:
            c = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == pinned))).scalars().first()
            program = (c.program if c else prog) or ""
            sold_out = not bool(c and c.status in ("open", "full") and
                                (not c.capacity or (await cohort_svc.active_count(db_session, c.id)) < c.capacity))
        else:
            program = prog
            sold_out = not await cohort_svc.has_open_seat(db_session, p.org_id, prog)
    cohorts = []
    if prog or getattr(p, "cohort_id", None):
        cohorts = await _upcoming_cohorts(db_session, p.org_id, program or prog)
    resp = HTMLResponse(checkout_page(p, PUB_KEY, _base_url(request), sold_out=sold_out,
                                      program=program, coupon_code=coupon_code,
                                      discount_cents=discount_cents, cohorts=cohorts))
    await _apply_ref(request, resp, db_session)
    return resp


@router.get("/success", response_class=HTMLResponse)
async def success(request: Request, session_id: str = "", db_session: AsyncSession = Depends(get_db_session)):
    order = None
    if session_id:
        # Belt-and-suspenders fulfillment: don't rely solely on the async
        # webhook. Retrieve the session server-side and fulfill if it's paid.
        if stripe.api_key:
            try:
                sess = _as_dict(stripe.checkout.Session.retrieve(session_id))
                if sess.get("payment_status") == "paid":
                    await _fulfill(db_session, sess)
            except Exception as e:
                import traceback
                print(f"[BBU] success fulfill error: {e}\n{traceback.format_exc()[-600:]}", flush=True)
        order = (await db_session.execute(
            select(BBUOrder).where(BBUOrder.stripe_session_id == session_id)
        )).scalars().first()

    resp = HTMLResponse(success_page(order, _base_url(request)))

    # Sign the buyer in. Checkout only collects an email — they have no password
    # and never went through signup — so without this they land on the platform
    # anonymous, can't see what they just bought, and have no way in. Paying is a
    # stronger proof of identity than the email link we'd otherwise send; the
    # session is scoped to the account the payment created.
    try:
        if order and order.user_id and order.status == "paid":
            from src.db.users import User as _U
            from src.security.auth import create_access_token, create_refresh_token
            from src.routers.auth import set_auth_cookies
            buyer = (await db_session.execute(
                select(_U).where(_U.id == order.user_id))).scalars().first()
            if buyer and buyer.email:
                # `sub` is resolved as an EMAIL downstream:
                #   security_get_user(..., email=token_data.username)
                # Passing the generated username mints a token that decodes
                # fine and then matches no user, so the buyer silently stays
                # anonymous. Login only works because people sign in by email.
                set_auth_cookies(
                    resp,
                    create_access_token(data={"sub": buyer.email}),
                    create_refresh_token(data={"sub": buyer.email}),
                    request,
                )
    except Exception:
        import traceback
        print(f"[BBU] post-purchase sign-in failed:\n{traceback.format_exc()[-500:]}",
              flush=True)
    return resp


@router.post("/complete-account")
async def complete_account(request: Request,
                           db_session: AsyncSession = Depends(get_db_session)):
    """Finish the account a purchase created: name, phone, and a chosen password.

    Identity comes from the PAID ORDER, never from the ambient session cookie.
    Using the cookie was a real defect: the buy flow is often opened in a browser
    that is already signed in as somebody else — an admin demoing it, a shared
    machine — and the form then rewrote *that* account's name and password
    instead of the buyer's. The Stripe session id in the success URL is the only
    thing that identifies who actually paid.
    """
    from src.security.security import security_hash_password
    from src.db.users import User as _U

    b = await request.json()
    session_id = (b.get("session_id") or "").strip()
    password = (b.get("password") or "").strip()
    confirm = (b.get("confirm") or "").strip()
    name = (b.get("name") or "").strip()
    phone = (b.get("phone") or "").strip()

    if not session_id:
        raise HTTPException(400, "Missing your order reference — please reopen the link from your receipt.")
    if not name:
        raise HTTPException(400, "Please enter your name.")
    if len("".join(ch for ch in phone if ch.isdigit())) < 10:
        raise HTTPException(400, "Please enter a valid phone number.")
    if len(password) < 8:
        raise HTTPException(400, "Please choose a password of at least 8 characters.")
    if confirm and confirm != password:
        raise HTTPException(400, "Those passwords don't match.")

    order = (await db_session.execute(select(BBUOrder).where(
        BBUOrder.stripe_session_id == session_id))).scalars().first()
    if not order or order.status != "paid":
        raise HTTPException(403, "We couldn't verify that purchase.")

    # The order's own email is the buyer. Create the account here if fulfillment
    # hasn't already (webhook ordering, or a fulfillment that errored).
    user = None
    if order.user_id:
        user = (await db_session.execute(
            select(_U).where(_U.id == order.user_id))).scalars().first()
    if not user and order.email:
        user = (await db_session.execute(
            select(_U).where(_U.email == order.email))).scalars().first()
    if not user and order.email:
        from src.bbu_migration.router import _get_or_create_user, _learner_role_id
        user = await _get_or_create_user(
            db_session, order.org_id, await _learner_role_id(db_session),
            order.email, name)
    if not user:
        raise HTTPException(404, "We couldn't find the account for that purchase.")

    # Refuse to touch an account that isn't the one that paid.
    if (user.email or "").lower() != (order.email or "").lower():
        raise HTTPException(403, "That purchase belongs to a different account.")

    user.password = security_hash_password(password)
    # Leave password_changed_at alone: it revokes tokens issued before it, which
    # would sign the buyer out of the session they are about to use.
    parts = name.split(" ", 1)
    user.first_name = parts[0][:100]
    user.last_name = (parts[1] if len(parts) > 1 else "")[:100]
    user.phone = phone[:40]
    user.update_date = datetime.now(timezone.utc).isoformat()
    order.user_id = user.id
    db_session.add(user)
    db_session.add(order)
    await db_session.commit()

    # Make sure the courses they paid for are actually granted before we send
    # them onward — otherwise "start your course" lands on a locked page.
    try:
        prod = (await db_session.execute(select(BBUProduct).where(
            BBUProduct.id == order.product_id))).scalars().first()
        if prod:
            await _grant_course_access(db_session, order, prod)
    except Exception:
        import traceback
        print(f"[BBU] grant during complete-account failed:\n"
              f"{traceback.format_exc()[-500:]}", flush=True)

    try:
        from src.bbu_ghl.client import GHLClient, is_configured
        if is_configured():
            async with GHLClient() as ghl:
                await ghl.upsert_contact(email=user.email, first_name=user.first_name,
                                         last_name=user.last_name, phone=phone)
    except Exception:
        pass

    # Sign in as the BUYER, replacing whatever session the browser had.
    resp = JSONResponse({"ok": True, "email": user.email})
    try:
        from src.security.auth import create_access_token, create_refresh_token
        from src.routers.auth import set_auth_cookies
        set_auth_cookies(resp,
                         create_access_token(data={"sub": user.email}),
                         create_refresh_token(data={"sub": user.email}),
                         request)
    except Exception:
        pass
    return resp


@router.get("/course-book")
async def course_book(course_uuid: str, db_session: AsyncSession = Depends(get_db_session)):
    """The downloadable workbook for a course, if one has been set.

    Cohort programmes carry a workbook_url; a course reached through a cohort
    inherits it. Returns an empty url when nothing is configured so the UI can
    hide the link rather than offer a dead button.
    """
    out = {"url": "", "label": "Download the course book"}
    try:
        from src.bbu_cohorts.models import BBUCohort
        from src.bbu_cohorts.templates import workbook_for

        course = (await db_session.execute(select(Course).where(
            Course.course_uuid == course_uuid))).scalars().first()
        if not course:
            return out
        cohorts = (await db_session.execute(select(BBUCohort).where(
            BBUCohort.org_id == course.org_id))).scalars().all()
        for c in cohorts:
            if (c.course_uuid or "") == course_uuid or (course.name or "").startswith(c.name or "\x00"):
                url = (getattr(c, "workbook_url", "") or "") or workbook_for(c.program or "")
                if url:
                    out["url"] = url
                    return out
        for p in (await db_session.execute(select(BBUProduct).where(
                BBUProduct.org_id == course.org_id))).scalars().all():
            if course_uuid in (p.course_uuids or "") and (p.cohort_program or ""):
                url = workbook_for(p.cohort_program)
                if url:
                    out["url"] = url
                    return out
    except Exception:
        return out
    return out


@router.get("/my-ebooks")
async def my_ebooks(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """E-books the signed-in member has bought, with a fresh download link.

    E-books are products with a token-gated PDF, entirely separate from the
    Library's folder tree — so a buyer had nowhere to re-download from after the
    original receipt. This is what the Library shows them.
    """
    from src.security.auth import get_current_user, resolve_acting_user_id
    from src.db.users import User as _U

    try:
        uid = resolve_acting_user_id(await get_current_user(request, db_session)) or 0
    except Exception:
        uid = 0
    if not uid:
        return []
    user = (await db_session.execute(select(_U).where(_U.id == uid))).scalars().first()
    if not user:
        return []

    orders = (await db_session.execute(select(BBUOrder).where(
        BBUOrder.org_id == 1, BBUOrder.status == "paid"))).scalars().all()
    mine = [o for o in orders
            if (o.user_id == uid) or ((o.email or "").lower() == (user.email or "").lower())]
    owned = {}
    for o in mine:
        if o.product_id not in owned or o.download_token:
            owned[o.product_id] = o

    # Show the whole e-book shelf, not only what's been bought. A member should
    # be able to SEE what exists — owned ones download, the rest link to buy.
    # Returning purchases only left the Library empty for everyone until their
    # first e-book sale.
    base = _base_url(request)
    out = []
    for p in (await db_session.execute(select(BBUProduct).where(
            BBUProduct.org_id == 1, BBUProduct.kind == "ebook"))).scalars().all():
        if not p.public and p.id not in owned:
            continue          # unlisted/QA items stay hidden unless owned
        o = owned.get(p.id)
        out.append({
            "id": p.id, "name": p.name, "description": (p.description or "")[:200],
            "image_url": p.image_url or "",
            "owned": bool(o),
            "price": round((p.price_cents or 0) / 100, 2),
            "purchased_on": ((o.paid_at or o.created_at or "")[:10] if o else ""),
            "download_url": (f"{base}/api/v1/bbu/ebook/download/{o.download_token}"
                             if o and o.download_token else ""),
            "buy_url": f"{base}/api/v1/bbu/buy/{p.id}",
        })
    out.sort(key=lambda x: (not x["owned"], x["name"]))
    return out


@router.get("/cohort-availability")
async def cohort_availability(product_id: int, db_session: AsyncSession = Depends(get_db_session)):
    """Storefront check: is this a cohort product, and does it have an open seat?
    When sold out, the buy page shows a waitlist form instead of the pay button."""
    p = (await db_session.execute(select(BBUProduct).where(BBUProduct.id == product_id))).scalars().first()
    if not p:
        raise HTTPException(404, "Product not found")
    prog = getattr(p, "cohort_program", "") or ""
    if not prog and not getattr(p, "cohort_id", None):
        return {"is_cohort": False, "available": True}
    from src.bbu_cohorts import service as cohort_svc
    if getattr(p, "cohort_id", None):
        c = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == p.cohort_id))).scalars().first()
        avail = bool(c and c.status in ("open", "full") and
                     (not c.capacity or (await cohort_svc.active_count(db_session, c.id)) < c.capacity))
        prog = prog or (c.program if c else "")
    else:
        avail = await cohort_svc.has_open_seat(db_session, p.org_id, prog)
    upcoming = await _upcoming_cohorts(db_session, p.org_id, prog)

    return {"is_cohort": True, "available": avail, "program": prog,
            "upcoming": upcoming,
            "waitlist_count": await cohort_svc.waitlist_count(db_session, p.org_id, prog)}


@router.post("/cohort-waitlist")
async def cohort_waitlist_join(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Public: join the waitlist for a sold-out cohort product (no charge)."""
    b = await request.json()
    p = (await db_session.execute(select(BBUProduct).where(BBUProduct.id == b.get("product_id")))).scalars().first()
    if not p:
        raise HTTPException(404, "Product not found")
    prog = getattr(p, "cohort_program", "") or ""
    if not prog and getattr(p, "cohort_id", None):
        c = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == p.cohort_id))).scalars().first()
        prog = c.program if c else "doula"
    from src.bbu_cohorts import service as cohort_svc
    return await cohort_svc.add_to_waitlist(
        db_session, p.org_id, prog or "doula",
        email=b.get("email", ""), name=b.get("name", ""), phone=b.get("phone", ""),
        product_id=p.id)


@router.post("/checkout")
async def checkout(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    body = await request.json()
    product_id = body.get("product_id")
    email = (body.get("email") or "").strip()
    p = (await db_session.execute(select(BBUProduct).where(BBUProduct.id == product_id))).scalars().first()
    if not p:
        raise HTTPException(404, "Product not found")
    if not stripe.api_key:
        raise HTTPException(500, "Stripe not configured")

    # Waitlist gate: never sell a seat that doesn't exist. If this is a cohort
    # product and every upcoming cohort is full, refuse checkout and steer the
    # buyer to the waitlist (belt-and-suspenders — the buy page already hides the
    # pay button, this stops a direct API hit too).
    prog = getattr(p, "cohort_program", "") or ""
    if (prog or getattr(p, "cohort_id", None)):
        from src.bbu_cohorts import service as cohort_svc
        pinned = getattr(p, "cohort_id", None)
        if pinned:
            c = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == pinned))).scalars().first()
            open_seat = bool(c and c.status in ("open", "full") and
                             (not c.capacity or (await cohort_svc.active_count(db_session, c.id)) < c.capacity))
        else:
            open_seat = await cohort_svc.has_open_seat(db_session, p.org_id, prog)
        if not open_seat:
            return {"waitlist": True, "message": "This cohort is full — join the waitlist and we'll message you the moment a spot opens."}

    # Affiliate attribution: ref from body (JS reads the cookie) or the cookie.
    ref = (body.get("ref") or request.cookies.get(REF_COOKIE) or "").strip()

    base = _base_url(request)
    # Reference the persistent Stripe Product, not inline product_data: a
    # course-scoped coupon can only match a stable product id. Created on demand
    # if the catalogue sync hasn't run yet.
    from src.bbu_payments import stripe_sync as _sync
    try:
        _sync.ensure_product(p)
        db_session.add(p)
    except Exception:
        pass
    price_data = {"currency": p.currency, "unit_amount": p.price_cents}
    if p.stripe_product_id:
        price_data["product"] = p.stripe_product_id
    else:
        price_data["product_data"] = {"name": p.name,
                                      "description": (p.description or "")[:300]}

    # Webinar offer links carry the discount in the URL — nobody types a code.
    # Stripe refuses `discounts` and `allow_promotion_codes` on the SAME session,
    # but the choice is per session: a link-borne coupon pre-applies the discount,
    # and everyone else still gets the promo box.
    discount_cents, discounts = 0, None
    code = (body.get("coupon") or "").strip()
    if code:
        c = await _coupon_svc.find_by_code(db_session, p.org_id, code)
        ok, reason = (_coupon_svc.validate_for(c, p.id, p.price_cents) if c
                      else (False, "that code doesn't exist"))
        # Never silently bill list price to someone who followed a discount link.
        if not ok:
            raise HTTPException(400, f"This discount link isn't valid — {reason}")
        try:
            scope = _sync._scope_for(c, {p.id: p.stripe_product_id})
            _coupon_svc.ensure_stripe_objects(c, scope)
            db_session.add(c)
        except Exception as e:
            raise HTTPException(400, f"Could not apply that discount: {str(e)[:120]}")
        if not c.stripe_promo_id:
            raise HTTPException(400, "That discount isn't available right now.")
        discount_cents = _coupon_svc.compute_discount_cents(c, p.price_cents)
        discounts = [{"promotion_code": c.stripe_promo_id}]

    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=email or None,
        line_items=[{"price_data": price_data, "quantity": 1}],
        **({"discounts": discounts} if discounts
           # buyers type BBU promo codes on Stripe's page; Stripe enforces expiry,
           # caps, minimum spend and course scope
           else {"allow_promotion_codes": True}),
        # Checkout Sessions auto-enable every eligible payment method configured
        # on the Stripe account (cards incl. HSA/FSA, Klarna, wallets) when
        # payment_method_types is omitted — no per-session flag needed.
        success_url=f"{base}/api/v1/bbu/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base}/api/v1/bbu/buy/{p.id}",
        metadata={"bbu_product_id": str(p.id), "course_uuids": p.course_uuids,
                  "affiliate_ref": ref},
    )

    order = BBUOrder(
        org_id=p.org_id, product_id=p.id, stripe_session_id=session.id,
        email=email, amount_cents=max(0, p.price_cents - discount_cents),
        currency=p.currency,
        status="pending", course_uuids=p.course_uuids, affiliate_ref=ref,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db_session.add(order)
    await db_session.commit()
    return {"url": session.url, "session_id": session.id}


async def _grant_course_access(db_session: AsyncSession, order, product):
    """Enroll the order's buyer into each course granted by the product. Reuses
    the migration's idempotent trail/run helpers so a re-delivered webhook or a
    success re-hit doesn't create duplicate enrollments."""
    from src.db.courses.courses import Course
    from src.db.users import User
    from src.db.usergroups import UserGroup
    from src.db.usergroup_user import UserGroupUser
    from src.bbu_migration.router import _ensure_trail, _ensure_run

    # Prefer the order's recorded course set (includes any order-bump add-ons),
    # falling back to the primary product's courses.
    uuids = [u for u in ((order.course_uuids or product.course_uuids) or "").split(",") if u]
    if not uuids:
        return
    # Resolve the buyer: prefer the user_id captured at checkout, else by email.
    user = None
    if order.user_id:
        user = (await db_session.execute(
            select(User).where(User.id == order.user_id)
        )).scalars().first()
    if not user and order.email:
        user = (await db_session.execute(
            select(User).where(User.email == order.email)
        )).scalars().first()
    if not user and order.email:
        # First-time buyer: checkout only asked for an email, so there is no
        # account yet. Returning here left them having paid for nothing — the
        # order was marked paid, no access was granted, and the success page
        # pointed at /courses which they could neither see nor sign in to.
        # Create the account so the purchase actually lands somewhere.
        try:
            from src.bbu_migration.router import _get_or_create_user, _learner_role_id
            role_id = await _learner_role_id(db_session)
            name = ""
            try:
                name = ((order.extra or {}).get("customer_name") or "")
            except Exception:
                name = ""
            user = await _get_or_create_user(db_session, order.org_id, role_id,
                                             order.email, name)
            order.user_id = user.id
            db_session.add(order)
            await db_session.commit()
        except Exception:
            import traceback
            print(f"[BBU] buyer account creation failed for order {order.id}:\n"
                  f"{traceback.format_exc()[-600:]}", flush=True)
    if not user:
        return  # nothing we can do without an email — order remains the record
    now = datetime.now(timezone.utc).isoformat()
    trail = await _ensure_trail(db_session, order.org_id, user.id)
    for cu in uuids:
        course = (await db_session.execute(
            select(Course).where(Course.course_uuid == cu)
        )).scalars().first()
        if course:
            # 1) enrollment (trail run) — for progress tracking / "my courses"
            await _ensure_run(db_session, trail, course, user.id)
            # 2) ACCESS — add the buyer to the course's access usergroup. This is
            #    what actually unlocks a gated (non-public) course. Access group
            #    is keyed by course_uuid in its description (see gate-courses).
            grp = (await db_session.execute(select(UserGroup).where(
                UserGroup.org_id == order.org_id, UserGroup.description == cu
            ))).scalars().first()
            if grp:
                has = (await db_session.execute(select(UserGroupUser).where(
                    UserGroupUser.usergroup_id == grp.id,
                    UserGroupUser.user_id == user.id,
                ))).scalars().first()
                if not has:
                    db_session.add(UserGroupUser(
                        usergroup_id=grp.id or 0, user_id=user.id or 0,
                        org_id=order.org_id, creation_date=now, update_date=now))
    await db_session.commit()


async def _fulfill(db_session: AsyncSession, session_obj: dict):
    """Mark the order paid. (Enrollment: OSS build grants access on the free
    tier, so a paid buyer can open the course immediately; the paid order is the
    system of record and the hook point for usergroup-gated access later.)"""
    sid = session_obj.get("id")
    order = (await db_session.execute(
        select(BBUOrder).where(BBUOrder.stripe_session_id == sid)
    )).scalars().first()
    if not order:
        return
    order.status = "paid"
    order.stripe_payment_intent = session_obj.get("payment_intent") or ""
    order.paid_at = datetime.now(timezone.utc).isoformat()
    # Stripe already collects the cardholder name — use it rather than asking for
    # a name before payment, so the buy page stays a single email field.
    cust_name = (session_obj.get("customer_details") or {}).get("name") or ""
    if cust_name:
        order.extra = {**(order.extra or {}), "customer_name": cust_name}
    cust_email = (session_obj.get("customer_details") or {}).get("email")
    if cust_email and not order.email:
        order.email = cust_email
    # capture ref from session metadata if the cookie didn't reach checkout
    if not order.affiliate_ref:
        order.affiliate_ref = (session_obj.get("metadata") or {}).get("affiliate_ref", "") or ""
    # Record any promo code the buyer applied on Stripe's page: bump the coupon's
    # redemption count and stamp code + discount on the order for reporting.
    try:
        from src.bbu_payments import coupons as _coupon_svc
        code, disc_cents = await _coupon_svc.record_redemption_from_session(
            db_session, order.org_id, session_obj)
        if code or disc_cents:
            order.extra = {**(order.extra or {}), "coupon_code": code,
                           "discount_cents": disc_cents}
    except Exception:
        pass
    # E-book delivery: issue a secure download token for paid ebook orders.
    prod = (await db_session.execute(
        select(BBUProduct).where(BBUProduct.id == order.product_id)
    )).scalars().first()
    try:
        if prod and prod.kind == "ebook":
            from src.bbu_payments.ebooks import ensure_download_token
            ensure_download_token(order)
    except Exception:
        pass
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    # Course access: enroll the buyer into every course the product grants, so
    # the purchase shows in their trail / "my courses" and progress tracks.
    # Best-effort — never let an enrollment hiccup block marking the order paid.
    try:
        if prod and prod.kind in ("course", "bundle"):
            await _grant_course_access(db_session, order, prod)
    except Exception:
        import traceback
        print(f"[BBU] course grant failed for order {order.id}:\n{traceback.format_exc()[-600:]}", flush=True)
    # Mentorship "buy into a cohort": if the purchased product is linked to a
    # cohort/program, enroll the buyer into the resolved cohort (waitlists if
    # full). This grants the cohort community + course and drives the eventual
    # provisional->full credential upgrade on completion. Fail-soft.
    try:
        if prod and (getattr(prod, "cohort_program", "") or getattr(prod, "cohort_id", None)):
            from src.db.users import User as _User
            buyer = None
            if order.user_id:
                buyer = (await db_session.execute(select(_User).where(_User.id == order.user_id))).scalars().first()
            if not buyer and order.email:
                buyer = (await db_session.execute(select(_User).where(_User.email == order.email))).scalars().first()
            if buyer:
                from src.bbu_cohorts import service as cohort_svc
                res = await cohort_svc.enroll_from_product(
                    db_session, order.org_id, buyer.id,
                    cohort_id=prod.cohort_id, program=prod.cohort_program)
                print(f"[BBU] cohort enroll for order {order.id}: {res}", flush=True)
    except Exception:
        import traceback
        print(f"[BBU] cohort enroll failed for order {order.id}:\n{traceback.format_exc()[-600:]}", flush=True)
    # Reseller/bulk pack: auto-generate the buyer's seat codes + an owner-portal
    # token so the agency owner can self-serve (view/share/redeem). Idempotent —
    # keyed on batch_label order-{id}; a re-delivered webhook won't double-mint.
    try:
        if prod and int(getattr(prod, "seat_count", 0) or 0) > 0:
            from src.bbu_seats.models import BBUSeatCode
            from src.bbu_seats import service as seat_svc
            label = f"order-{order.id}"
            exists = (await db_session.execute(select(BBUSeatCode).where(
                BBUSeatCode.batch_label == label))).scalars().first()
            if exists:
                token = exists.owner_token
            else:
                cu = [u for u in (prod.course_uuids or "").split(",") if u]
                r = await seat_svc.generate_batch(
                    db_session, order.org_id, int(prod.seat_count), cu,
                    owner_email=order.email, product_id=prod.id, batch_label=label)
                token = r["owner_token"]
            # stash the portal token on the order so the success page can link it
            extra = dict(order.extra or {})
            extra["seat_owner_token"] = token
            extra["seat_count"] = int(prod.seat_count)
            order.extra = extra
            db_session.add(order)
            await db_session.commit()
    except Exception:
        import traceback
        print(f"[BBU] seat generation failed for order {order.id}:\n{traceback.format_exc()[-600:]}", flush=True)
    # Book the affiliate commission. Always attempted — it's idempotent (one
    # commission per order+event), so re-delivered webhooks / success re-hits
    # don't double-book, and a prior partial fulfill can still be completed.
    try:
        await aff.book_commission_for_order(db_session, order, event="first_sale")
    except Exception:
        import traceback
        print(f"[BBU] commission booking failed for order {order.id}:\n{traceback.format_exc()}", flush=True)
    # Mirror the purchase into GoHighLevel as a course_enrollment module record
    # + contact rollup fields. Fail-soft: a CRM hiccup must never break a sale.
    try:
        if prod:
            from src.bbu_ghl import sync as ghl_sync
            await ghl_sync.sync_order(db_session, order, prod)
    except Exception:
        import traceback
        print(f"[BBU] GHL sync failed for order {order.id}:\n{traceback.format_exc()[-600:]}", flush=True)


@router.post("/webhook")
async def webhook(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        if WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
        else:
            event = json.loads(payload)
    except Exception as e:
        raise HTTPException(400, f"Invalid webhook: {e}")

    etype = event["type"] if isinstance(event, dict) else event.type
    data = _as_dict(event["data"]["object"] if isinstance(event, dict) else event.data.object)
    if etype == "checkout.session.completed":
        await _fulfill(db_session, data)
    elif etype == "charge.refunded":
        pi = data.get("payment_intent")
        if pi:
            order = (await db_session.execute(
                select(BBUOrder).where(BBUOrder.stripe_payment_intent == pi)
            )).scalars().first()
            if order:
                order.status = "refunded"
                db_session.add(order)
                await db_session.commit()
                # reverse any not-yet-paid commissions for this order
                try:
                    await aff.reverse_commissions_for_order(db_session, order.id)
                except Exception:
                    pass
    return JSONResponse({"received": True})
