"""BBU coupons / promo codes — clean-room, native-Stripe.

Each BBUCoupon is mirrored to a Stripe Coupon + Promotion Code the first time
it's saved. Checkout sessions set ``allow_promotion_codes=True`` so the buyer
types the code on Stripe's own page; Stripe enforces expiry, redemption caps and
minimum spend. On fulfillment we read the applied discount off the session,
increment ``times_redeemed`` and record it on the order for reporting.
"""
from datetime import datetime, timezone

import stripe
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.bbu_payments.models import BBUCoupon


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_stripe_objects(coupon: BBUCoupon) -> None:
    """Create the Stripe Coupon + Promotion Code once; cache their ids on the row.
    No-op when Stripe isn't configured or the ids already exist."""
    if not stripe.api_key:
        return
    if not coupon.stripe_coupon_id:
        params: dict = {"name": coupon.code, "duration": "once"}
        if coupon.kind == "percent":
            params["percent_off"] = max(1, min(100, int(coupon.percent_off or 0)))
        else:
            params["amount_off"] = int(coupon.amount_off_cents or 0)
            params["currency"] = coupon.currency or "usd"
        if coupon.max_redemptions:
            params["max_redemptions"] = int(coupon.max_redemptions)
        if coupon.expires_at:
            try:
                dt = datetime.fromisoformat(coupon.expires_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                params["redeem_by"] = int(dt.timestamp())
            except Exception:
                pass
        c = stripe.Coupon.create(**params)
        coupon.stripe_coupon_id = c["id"]
    if not coupon.stripe_promo_id:
        promo: dict = {"coupon": coupon.stripe_coupon_id, "code": (coupon.code or "").upper()}
        if coupon.min_amount_cents:
            promo["restrictions"] = {
                "minimum_amount": int(coupon.min_amount_cents),
                "minimum_amount_currency": coupon.currency or "usd",
            }
        p = stripe.PromotionCode.create(**promo)
        coupon.stripe_promo_id = p["id"]


def deactivate_stripe(coupon: BBUCoupon) -> None:
    """Disable the promotion code in Stripe so it can't be redeemed anymore.
    (The underlying Coupon is left intact for historical orders.)"""
    if not stripe.api_key or not coupon.stripe_promo_id:
        return
    try:
        stripe.PromotionCode.modify(coupon.stripe_promo_id, active=False)
    except Exception:
        pass


def reactivate_stripe(coupon: BBUCoupon) -> None:
    if not stripe.api_key or not coupon.stripe_promo_id:
        return
    try:
        stripe.PromotionCode.modify(coupon.stripe_promo_id, active=True)
    except Exception:
        pass


def compute_discount_cents(coupon: BBUCoupon, subtotal_cents: int) -> int:
    if coupon.kind == "percent":
        return round(subtotal_cents * max(0, min(100, coupon.percent_off)) / 100)
    return min(subtotal_cents, max(0, coupon.amount_off_cents))


def validate_for(coupon: BBUCoupon, product_id: int, subtotal_cents: int):
    """Return (ok, reason). Mirrors the checks Stripe enforces, for the store's
    pre-checkout preview so the customer sees a clear message."""
    if not coupon or not coupon.active:
        return False, "This code isn't active."
    if coupon.expires_at:
        try:
            dt = datetime.fromisoformat(coupon.expires_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < datetime.now(timezone.utc):
                return False, "This code has expired."
        except Exception:
            pass
    if coupon.max_redemptions and coupon.times_redeemed >= coupon.max_redemptions:
        return False, "This code has reached its redemption limit."
    if coupon.min_amount_cents and subtotal_cents < coupon.min_amount_cents:
        need = coupon.min_amount_cents / 100
        return False, f"Minimum spend of ${need:.2f} required."
    applies = (coupon.applies_to or "all").strip()
    if applies and applies != "all":
        ids = {s.strip() for s in applies.split(",") if s.strip()}
        if str(product_id) not in ids:
            return False, "This code doesn't apply to this product."
    return True, ""


async def find_by_code(db: AsyncSession, org_id: int, code: str):
    if not code:
        return None
    rows = (await db.execute(
        select(BBUCoupon).where(BBUCoupon.org_id == org_id)
    )).scalars().all()
    code_u = code.strip().upper()
    for c in rows:
        if (c.code or "").strip().upper() == code_u:
            return c
    return None


async def record_redemption_from_session(db: AsyncSession, org_id: int, session_obj: dict):
    """After a paid checkout, if a promotion code was applied, bump the matching
    BBUCoupon's redemption count. Returns (code, discount_cents) for the order."""
    discounts = session_obj.get("discounts") or []
    total_details = session_obj.get("total_details") or {}
    discount_cents = int(total_details.get("amount_discount") or 0)
    promo_id = ""
    for d in discounts:
        pc = d.get("promotion_code")
        promo_id = pc if isinstance(pc, str) else (pc or {}).get("id", "")
        if promo_id:
            break
    code = ""
    if promo_id:
        c = (await db.execute(
            select(BBUCoupon).where(
                BBUCoupon.org_id == org_id, BBUCoupon.stripe_promo_id == promo_id
            )
        )).scalars().first()
        if c:
            c.times_redeemed = (c.times_redeemed or 0) + 1
            code = c.code
            db.add(c)
    return code, discount_cents
