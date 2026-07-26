"""BBU offers API — serves LearnHouse's native in-app Store/Offers UI.

The upstream Store/Offers React pages (apps/web/.../store, dash/payments,
AccountPurchases) call a REST surface `payments/{org_id}/offers/*` that ships
only with LearnHouse's commercial EE payments package — absent from this
self-hosted fork. This module implements that exact contract on top of our
clean-room `bbu_payments` models (BBUProduct/BBUOrder), so the native UI works
with zero page changes. No EE imports.

Mounted at /api/v1/payments.

Contract consumed by apps/web/services/payments/offers.ts:
  GET    /{org_id}/offers/public-listing              -> Offer[]
  GET    /{org_id}/offers/{offer_uuid}/public         -> Offer
  POST   /{org_id}/offers/{offer_uuid}/checkout       -> {checkout_url}
  GET    /{org_id}/offers                    (admin)  -> Offer[] (incl. hidden)
  POST   /{org_id}/offers                    (admin)  -> Offer
  PUT    /{org_id}/offers/{offer_uuid}       (admin)  -> Offer
  DELETE /{org_id}/offers/{offer_uuid}       (admin)  -> {archived}
  GET    /{org_id}/enrollments/mine          (auth)   -> Enrollment[]
  POST   /{org_id}/billing-portal            (auth)   -> {portal_url}
  GET    /{org_id}/checkout-success                   -> 302 back into the app
"""
import os
from datetime import datetime, timezone
from urllib.parse import urlparse, quote

import stripe
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.security.auth import get_current_user
from src.db.courses.courses import Course
from src.db.organizations import Organization
from src.bbu_payments.models import BBUProduct, BBUOrder, BBUCoupon
from src.bbu_payments.router import _fulfill, _as_dict
from src.bbu_payments import coupons as coupon_svc
from src.bbu_payments.helpers import merge_course_uuids

router = APIRouter()

stripe.api_key = os.environ.get("BBU_STRIPE_SECRET_KEY", "")
ADMIN_KEY = os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")


# --------------------------------------------------------------------------- #
# Mapping: BBUProduct -> the "Offer" shape the React UI expects.
# --------------------------------------------------------------------------- #
def _offer_uuid(product_id: int) -> str:
    return f"offer_{product_id}"


def _parse_offer_uuid(offer_uuid: str) -> int:
    try:
        return int(str(offer_uuid).rsplit("_", 1)[-1])
    except (ValueError, IndexError):
        raise HTTPException(404, "Offer not found")


async def _org_uuid(db: AsyncSession, org_id: int) -> str:
    org = (await db.execute(
        select(Organization).where(Organization.id == org_id)
    )).scalars().first()
    return org.org_uuid if org else ""


async def _included_resources(db: AsyncSession, product: BBUProduct, org_uuid: str):
    """Map a product's course_uuids -> the Resource[] the UI renders."""
    uuids = [u for u in (product.course_uuids or "").split(",") if u]
    if not uuids:
        return []
    rows = (await db.execute(
        select(Course).where(Course.course_uuid.in_(uuids))
    )).scalars().all()
    by_uuid = {c.course_uuid: c for c in rows}
    resources = []
    for u in uuids:  # preserve product ordering
        c = by_uuid.get(u)
        if not c:
            continue
        resources.append({
            "resource_uuid": c.course_uuid,
            "resource_type": "course",
            "name": c.name,
            "description": "",
            "thumbnail_image": c.thumbnail_image or "",
            "org_uuid": org_uuid,
        })
    return resources


async def _bump_offers(db: AsyncSession, p: BBUProduct) -> list:
    """Resolve a product's order-bump add-on ids into light summaries for the UI."""
    ids = [int(x) for x in (p.bump_offer_ids or "").split(",") if x.strip().isdigit()]
    if not ids:
        return []
    rows = (await db.execute(select(BBUProduct).where(
        BBUProduct.id.in_(ids), BBUProduct.org_id == p.org_id))).scalars().all()
    by_id = {b.id: b for b in rows}
    out = []
    for i in ids:  # preserve order
        b = by_id.get(i)
        if b:
            out.append({"offer_uuid": _offer_uuid(b.id), "name": b.name,
                        "amount": round((b.price_cents or 0) / 100, 2),
                        "kind": b.kind})
    return out


async def _to_offer(db: AsyncSession, p: BBUProduct, org_uuid: str) -> dict:
    return {
        "id": p.id,
        "offer_uuid": _offer_uuid(p.id),
        "name": p.name,
        "description": p.description or "",
        "offer_type": "one_time",           # BBU sells one-time products
        "price_type": "fixed_price",
        "amount": round((p.price_cents or 0) / 100, 2),
        "currency": (p.currency or "usd").upper(),
        "benefits": p.benefits or "",
        "payments_group_id": None,
        "kind": p.kind,
        "category": p.category or "",
        "bump_offers": await _bump_offers(db, p),
        "included_resources": await _included_resources(db, p, org_uuid),
    }


async def _get_product(db: AsyncSession, org_id: int, offer_uuid: str) -> BBUProduct:
    pid = _parse_offer_uuid(offer_uuid)
    p = (await db.execute(
        select(BBUProduct).where(BBUProduct.id == pid, BBUProduct.org_id == org_id)
    )).scalars().first()
    if not p:
        raise HTTPException(404, "Offer not found")
    return p


def _require_admin(request: Request):
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key", "")
    if not ADMIN_KEY or key != ADMIN_KEY:
        raise HTTPException(403, "Forbidden")


def _require_user(user):
    # get_current_user returns AnonymousUser (id == 0) when unauthenticated.
    uid = getattr(user, "id", 0)
    email = getattr(user, "email", "") or ""
    if not uid or not email:
        raise HTTPException(401, "Authentication required")
    return uid, email


# --------------------------------------------------------------------------- #
# Public listing + detail
# --------------------------------------------------------------------------- #
@router.get("/{org_id}/offers/public-listing")
async def public_listing(org_id: int, db_session: AsyncSession = Depends(get_db_session)):
    rows = (await db_session.execute(
        select(BBUProduct).where(
            BBUProduct.org_id == org_id, BBUProduct.public == True  # noqa: E712
        )
    )).scalars().all()
    org_uuid = await _org_uuid(db_session, org_id)
    return [await _to_offer(db_session, p, org_uuid) for p in rows]


@router.get("/{org_id}/offers/{offer_uuid}/public")
async def public_offer(org_id: int, offer_uuid: str, db_session: AsyncSession = Depends(get_db_session)):
    p = await _get_product(db_session, org_id, offer_uuid)
    return await _to_offer(db_session, p, await _org_uuid(db_session, org_id))


# --------------------------------------------------------------------------- #
# Checkout (authenticated) — creates a Stripe session, returns its URL.
# --------------------------------------------------------------------------- #
@router.post("/{org_id}/offers/{offer_uuid}/checkout")
async def checkout(
    org_id: int, offer_uuid: str, request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    uid, email = _require_user(user)
    if not stripe.api_key:
        raise HTTPException(500, "Stripe not configured")
    p = await _get_product(db_session, org_id, offer_uuid)

    # Optional order-bump add-ons selected at checkout (list of offer_uuids).
    try:
        body = await request.json()
    except Exception:
        body = {}
    bump_uuids = body.get("bumps") or []
    if isinstance(bump_uuids, str):
        bump_uuids = [b for b in bump_uuids.split(",") if b]
    allowed_bumps = {x.strip() for x in (p.bump_offer_ids or "").split(",") if x.strip()}
    bump_products = []
    for bu in bump_uuids:
        try:
            bid = _parse_offer_uuid(bu)
        except HTTPException:
            continue
        if str(bid) not in allowed_bumps:      # only bumps the product declares
            continue
        bp = (await db_session.execute(select(BBUProduct).where(
            BBUProduct.id == bid, BBUProduct.org_id == org_id))).scalars().first()
        if bp:
            bump_products.append(bp)

    redirect_uri = request.query_params.get("redirect_uri", "") or _base_from_request(request)
    parsed = urlparse(redirect_uri)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else _base_from_request(request)
    # Return page inside the app: strip "/store/..." back to the org root.
    path = parsed.path or ""
    org_root = path.split("/store")[0] if "/store" in path else path.rsplit("/", 1)[0]
    next_url = f"{origin}{org_root}/account/purchases?purchased=1"

    success_url = (f"{origin}/api/v1/payments/{org_id}/checkout-success"
                   f"?session_id={{CHECKOUT_SESSION_ID}}&next={quote(next_url, safe='')}")

    # Reference the persistent Stripe Product so course-scoped coupons can match
    # (inline product_data mints a throwaway product Stripe's applies_to can't see).
    from src.bbu_payments import stripe_sync as _sync

    def _line(prod):
        try:
            _sync.ensure_product(prod)
            db_session.add(prod)
        except Exception:
            pass
        pd = {"currency": prod.currency, "unit_amount": prod.price_cents}
        if prod.stripe_product_id:
            pd["product"] = prod.stripe_product_id
        else:
            pd["product_data"] = {"name": prod.name,
                                  "description": (prod.description or "")[:300]}
        return {"price_data": pd, "quantity": 1}
    line_items = [_line(p)] + [_line(bp) for bp in bump_products]

    # Merge course access across the primary product + any bumps (dedup, ordered).
    merged_courses = merge_course_uuids(prod.course_uuids for prod in [p] + bump_products)
    total_cents = p.price_cents + sum(bp.price_cents for bp in bump_products)

    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=email or None,
        line_items=line_items,
        success_url=success_url,
        cancel_url=redirect_uri or f"{origin}{org_root}/store",
        allow_promotion_codes=True,  # buyers enter BBU promo codes on Stripe's page
        metadata={"bbu_product_id": str(p.id), "course_uuids": merged_courses,
                  "bump_ids": ",".join(str(bp.id) for bp in bump_products),
                  "affiliate_ref": "", "buyer_user_id": str(uid)},
    )

    order = BBUOrder(
        org_id=p.org_id, product_id=p.id, stripe_session_id=session.id,
        email=email, user_id=uid, amount_cents=total_cents, currency=p.currency,
        status="pending", course_uuids=merged_courses,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db_session.add(order)
    await db_session.commit()
    return {"checkout_url": session.url, "session_id": session.id}


@router.get("/{org_id}/checkout-success")
async def checkout_success(
    org_id: int, request: Request, session_id: str = "", next: str = "",
    db_session: AsyncSession = Depends(get_db_session),
):
    """Belt-and-suspenders fulfillment for the in-app flow, then bounce the
    buyer back into the app (webhook fulfills too; whichever lands first wins)."""
    if session_id and stripe.api_key:
        try:
            sess = _as_dict(stripe.checkout.Session.retrieve(session_id))
            if sess.get("payment_status") == "paid":
                await _fulfill(db_session, sess)
        except Exception as e:
            import traceback
            print(f"[BBU] offer checkout-success fulfill error: {e}\n{traceback.format_exc()[-500:]}", flush=True)
    dest = next or _base_from_request(request)
    return RedirectResponse(dest, status_code=303)


# --------------------------------------------------------------------------- #
# My purchases (authenticated) — powers account/purchases.
# --------------------------------------------------------------------------- #
@router.get("/{org_id}/enrollments/mine")
async def my_enrollments(
    org_id: int, request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    uid, email = _require_user(user)
    orders = (await db_session.execute(
        select(BBUOrder).where(
            BBUOrder.org_id == org_id, BBUOrder.status == "paid",
            (BBUOrder.user_id == uid) | (BBUOrder.email == email),
        )
    )).scalars().all()
    # product lookup for names/kinds
    pids = list({o.product_id for o in orders})
    products = {}
    if pids:
        rows = (await db_session.execute(
            select(BBUProduct).where(BBUProduct.id.in_(pids))
        )).scalars().all()
        products = {p.id: p for p in rows}
    base = _base_from_request(request)
    out = []
    for o in orders:
        p = products.get(o.product_id)
        item = {
            "enrollment_id": o.id,
            "offer_id": _offer_uuid(o.product_id),
            "offer_name": (p.name if p else "Purchase"),
            "offer_type": "one_time",
            "status": "active",
            "amount": round((o.amount_cents or 0) / 100, 2),
            "currency": (o.currency or "usd").upper(),
            "creation_date": o.paid_at or o.created_at or None,
        }
        if p and p.kind == "ebook" and o.download_token:
            item["download_url"] = f"{base}/api/v1/bbu/ebook/download/{o.download_token}"
            item["is_ebook"] = True
        out.append(item)
    # newest first
    out.sort(key=lambda x: x.get("creation_date") or "", reverse=True)
    return out


@router.post("/{org_id}/billing-portal")
async def billing_portal(
    org_id: int, request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    """Best-effort Stripe billing portal for invoices/receipts. BBU sells
    one-time products, so if the buyer has no Stripe customer we return null and
    the UI shows a graceful toast rather than erroring."""
    uid, email = _require_user(user)
    return_url = request.query_params.get("return_url") or _base_from_request(request)
    if not stripe.api_key:
        return {"portal_url": None}
    try:
        customers = _as_dict(stripe.Customer.list(email=email, limit=1))
        data = customers.get("data") or []
        if not data:
            return {"portal_url": None}
        sess = _as_dict(stripe.billing_portal.Session.create(
            customer=data[0]["id"], return_url=return_url,
        ))
        return {"portal_url": sess.get("url")}
    except Exception:
        return {"portal_url": None}


# --------------------------------------------------------------------------- #
# Admin offer CRUD (dash/payments). Admin-key gated (Anna manages the catalog).
# --------------------------------------------------------------------------- #
@router.get("/{org_id}/offers")
async def admin_list_offers(org_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _require_admin(request)
    rows = (await db_session.execute(
        select(BBUProduct).where(BBUProduct.org_id == org_id)
    )).scalars().all()
    org_uuid = await _org_uuid(db_session, org_id)
    return [await _to_offer(db_session, p, org_uuid) for p in rows]


@router.get("/{org_id}/offers/{offer_uuid}")
async def admin_get_offer(org_id: int, offer_uuid: str, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _require_admin(request)
    p = await _get_product(db_session, org_id, offer_uuid)
    return await _to_offer(db_session, p, await _org_uuid(db_session, org_id))


@router.post("/{org_id}/offers")
async def admin_create_offer(org_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _require_admin(request)
    body = await request.json()
    resources = [r for r in (body.get("resource_uuids") or []) if r]
    p = BBUProduct(
        org_id=org_id,
        name=body.get("name", "Untitled offer"),
        kind="bundle" if len(resources) > 1 else "course",
        course_uuids=",".join(resources),
        price_cents=round(float(body.get("amount", 0)) * 100),
        currency=(body.get("currency", "usd") or "usd").lower(),
        description=body.get("description", ""),
        benefits=body.get("benefits", ""),
        category=body.get("category", ""),
        bump_offer_ids=",".join(str(x) for x in (body.get("bump_offer_ids") or [])),
        public=True,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return await _to_offer(db_session, p, await _org_uuid(db_session, org_id))


@router.put("/{org_id}/offers/{offer_uuid}")
async def admin_update_offer(org_id: int, offer_uuid: str, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _require_admin(request)
    p = await _get_product(db_session, org_id, offer_uuid)
    body = await request.json()
    if "name" in body: p.name = body["name"]
    if "description" in body: p.description = body["description"]
    if "benefits" in body: p.benefits = body["benefits"]
    if "category" in body: p.category = body["category"] or ""
    if "bump_offer_ids" in body:
        p.bump_offer_ids = ",".join(str(x) for x in (body["bump_offer_ids"] or []))
    if "amount" in body: p.price_cents = round(float(body["amount"]) * 100)
    if "currency" in body: p.currency = (body["currency"] or "usd").lower()
    if "resource_uuids" in body:
        resources = [r for r in (body["resource_uuids"] or []) if r]
        p.course_uuids = ",".join(resources)
        if p.kind in ("course", "bundle"):
            p.kind = "bundle" if len(resources) > 1 else "course"
    if "public" in body: p.public = bool(body["public"])
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return await _to_offer(db_session, p, await _org_uuid(db_session, org_id))


@router.delete("/{org_id}/offers/{offer_uuid}")
async def admin_archive_offer(org_id: int, offer_uuid: str, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _require_admin(request)
    p = await _get_product(db_session, org_id, offer_uuid)
    p.public = False  # archive = hide from store (non-destructive)
    db_session.add(p)
    await db_session.commit()
    return {"archived": _offer_uuid(p.id)}


# --------------------------------------------------------------------------- #
# Coupons / promo codes. Admin-key gated CRUD; public validate for store preview.
# Codes are entered natively on Stripe Checkout (allow_promotion_codes) — these
# rows are the admin system-of-record and mirror to Stripe on save.
# --------------------------------------------------------------------------- #
def _coupon_dict(c: BBUCoupon) -> dict:
    return {
        "id": c.id,
        "code": c.code,
        "kind": c.kind,
        "percent_off": c.percent_off,
        "amount_off": round((c.amount_off_cents or 0) / 100, 2),
        "currency": (c.currency or "usd").upper(),
        "applies_to": c.applies_to or "all",
        "min_amount": round((c.min_amount_cents or 0) / 100, 2),
        "max_redemptions": c.max_redemptions,
        "times_redeemed": c.times_redeemed,
        "expires_at": c.expires_at or "",
        "active": bool(c.active),
        "stripe_linked": bool(c.stripe_promo_id),
    }


@router.get("/{org_id}/coupons")
async def admin_list_coupons(org_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _require_admin(request)
    rows = (await db_session.execute(
        select(BBUCoupon).where(BBUCoupon.org_id == org_id)
    )).scalars().all()
    return [_coupon_dict(c) for c in rows]


@router.post("/{org_id}/coupons")
async def admin_create_coupon(org_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _require_admin(request)
    body = await request.json()
    code = (body.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "code required")
    existing = await coupon_svc.find_by_code(db_session, org_id, code)
    if existing:
        raise HTTPException(409, "A coupon with that code already exists")
    kind = body.get("kind", "percent")
    c = BBUCoupon(
        org_id=org_id, code=code, kind=kind,
        percent_off=int(body.get("percent_off", 0) or 0),
        amount_off_cents=round(float(body.get("amount_off", 0) or 0) * 100),
        currency=(body.get("currency", "usd") or "usd").lower(),
        applies_to=(body.get("applies_to") or "all"),
        min_amount_cents=round(float(body.get("min_amount", 0) or 0) * 100),
        max_redemptions=int(body.get("max_redemptions", 0) or 0),
        expires_at=(body.get("expires_at") or ""),
        active=bool(body.get("active", True)),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        coupon_svc.ensure_stripe_objects(c)
    except Exception as e:
        raise HTTPException(502, f"Stripe coupon create failed: {e}")
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return _coupon_dict(c)


@router.put("/{org_id}/coupons/{coupon_id}")
async def admin_update_coupon(org_id: int, coupon_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _require_admin(request)
    c = (await db_session.execute(
        select(BBUCoupon).where(BBUCoupon.id == coupon_id, BBUCoupon.org_id == org_id)
    )).scalars().first()
    if not c:
        raise HTTPException(404, "Coupon not found")
    body = await request.json()
    # Only mutable, non-Stripe-locked fields (discount value/duration are fixed
    # in Stripe once created; changing them means archive + recreate).
    if "applies_to" in body:
        c.applies_to = body["applies_to"] or "all"
    if "active" in body:
        c.active = bool(body["active"])
        (coupon_svc.reactivate_stripe if c.active else coupon_svc.deactivate_stripe)(c)
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return _coupon_dict(c)


@router.delete("/{org_id}/coupons/{coupon_id}")
async def admin_delete_coupon(org_id: int, coupon_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _require_admin(request)
    c = (await db_session.execute(
        select(BBUCoupon).where(BBUCoupon.id == coupon_id, BBUCoupon.org_id == org_id)
    )).scalars().first()
    if not c:
        raise HTTPException(404, "Coupon not found")
    c.active = False
    coupon_svc.deactivate_stripe(c)
    db_session.add(c)
    await db_session.commit()
    return {"deactivated": c.id}


@router.post("/{org_id}/offers/{offer_uuid}/validate-coupon")
async def validate_coupon(org_id: int, offer_uuid: str, request: Request,
                          db_session: AsyncSession = Depends(get_db_session),
                          user=Depends(get_current_user)):
    """Pre-checkout preview: given a code + offer, return the discounted price.
    Requires a signed-in user (same as checkout) so anonymous visitors can't
    enumerate/brute-force coupon codes."""
    _require_user(user)
    body = await request.json()
    code = (body.get("code") or "").strip()
    p = await _get_product(db_session, org_id, offer_uuid)
    c = await coupon_svc.find_by_code(db_session, org_id, code)
    if not c:
        return {"valid": False, "reason": "That code isn't recognized."}
    ok, reason = coupon_svc.validate_for(c, p.id, p.price_cents)
    if not ok:
        return {"valid": False, "reason": reason}
    disc = coupon_svc.compute_discount_cents(c, p.price_cents)
    return {
        "valid": True,
        "code": c.code,
        "discount": round(disc / 100, 2),
        "original": round(p.price_cents / 100, 2),
        "final": round(max(0, p.price_cents - disc) / 100, 2),
    }


def _base_from_request(request: Request) -> str:
    domain = os.environ.get("LEARNHOUSE_DOMAIN", request.url.netloc)
    scheme = "https" if os.environ.get("LEARNHOUSE_SSL", "true") == "true" else "http"
    return f"{scheme}://{domain}"
