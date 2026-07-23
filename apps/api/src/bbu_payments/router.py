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
from src.bbu_payments.branding import store_page, checkout_page, success_page
from src.bbu_payments import affiliates as aff

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
async def products(db_session: AsyncSession = Depends(get_db_session)):
    rows = await _list_products(db_session)
    return [
        {
            "id": p.id, "name": p.name, "kind": p.kind,
            "price_cents": p.price_cents, "currency": p.currency,
            "description": p.description, "image_url": p.image_url,
            "course_uuids": [u for u in p.course_uuids.split(",") if u],
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


@router.get("/store", response_class=HTMLResponse)
async def store(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    rows = await _list_products(db_session)
    resp = HTMLResponse(store_page(rows, _base_url(request)))
    await _apply_ref(request, resp, db_session)
    return resp


@router.get("/buy/{product_id}", response_class=HTMLResponse)
async def buy(product_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    p = (await db_session.execute(select(BBUProduct).where(BBUProduct.id == product_id))).scalars().first()
    if not p:
        raise HTTPException(404, "Product not found")
    resp = HTMLResponse(checkout_page(p, PUB_KEY, _base_url(request)))
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
    return HTMLResponse(success_page(order, _base_url(request)))


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

    # Affiliate attribution: ref from body (JS reads the cookie) or the cookie.
    ref = (body.get("ref") or request.cookies.get(REF_COOKIE) or "").strip()

    base = _base_url(request)
    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=email or None,
        line_items=[{
            "price_data": {
                "currency": p.currency,
                "product_data": {"name": p.name, "description": (p.description or "")[:300]},
                "unit_amount": p.price_cents,
            },
            "quantity": 1,
        }],
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
        email=email, amount_cents=p.price_cents, currency=p.currency,
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

    uuids = [u for u in (product.course_uuids or "").split(",") if u]
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
    if not user:
        return  # no account yet (guest email) — order stays the record of purchase
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
