"""Push the platform's catalogue and coupons into Stripe.

Stripe is the source of truth for redemption: the buyer types the code on
Stripe's own Checkout page (``allow_promotion_codes``), and Stripe enforces
expiry, redemption caps, minimum spend and — critically — course scope. For that
to work, everything the platform knows has to exist in Stripe first:

  BBUProduct  -> Stripe Product      (so line items reference a stable product)
  BBUCoupon   -> Stripe Coupon + Promotion Code, restricted via applies_to

The product half is not optional. Checkout used to build line items from inline
``product_data``, which mints a throwaway Stripe Product per session; a coupon
scoped to specific products then matches nothing and Stripe rejects it with
"This coupon cannot be redeemed because it does not apply to anything in this
order." Referencing a persistent product id is what makes scoped codes work.

TEST vs LIVE. Stripe ids are per-account and per-mode. Ids minted against a test
key are meaningless once the live key is in, and a cached stale id silently
breaks the code. So `reset=True` clears every cached id and re-creates against
whichever key is active — **run it once after switching to the live key**.
"""
from datetime import datetime, timezone

import stripe
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.bbu_payments.models import BBUProduct, BBUCoupon
from src.bbu_payments import coupons as coupon_svc


def _mode() -> str:
    return "live" if (stripe.api_key or "").startswith("sk_live") else "test"


def ensure_product(p: BBUProduct) -> str:
    """Create/refresh the Stripe Product mirroring this offer; cache its id."""
    if not stripe.api_key:
        return ""
    if p.stripe_product_id:
        return p.stripe_product_id
    sp = stripe.Product.create(
        name=p.name,
        description=(p.description or "")[:300] or None,
        metadata={"bbu_product_id": str(p.id), "kind": p.kind or "course"},
    )
    p.stripe_product_id = sp["id"]
    return p.stripe_product_id


def _scope_for(coupon: BBUCoupon, prod_by_id: dict) -> list:
    """BBUCoupon.applies_to ("all" | "3,4,12") -> Stripe Product ids."""
    raw = (coupon.applies_to or "all").strip()
    if not raw or raw.lower() == "all":
        return []
    out = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            sid = (prod_by_id.get(int(part)) or "")
            if sid:
                out.append(sid)
    return out


async def sync_all(db: AsyncSession, org_id: int, reset: bool = False,
                   include_inactive: bool = False) -> dict:
    """Mirror every product and coupon into Stripe. Idempotent."""
    if not stripe.api_key:
        return {"error": "Stripe not configured"}

    products = (await db.execute(select(BBUProduct).where(
        BBUProduct.org_id == org_id))).scalars().all()
    coupons = (await db.execute(select(BBUCoupon).where(
        BBUCoupon.org_id == org_id))).scalars().all()

    # Stripe ids are per-account and per-mode, and nothing in the id says which.
    # Rather than trust a human to remember `reset` after the test->live swap,
    # probe one cached id: if the active key can't see it, the ids belong to
    # another account/mode and every one of them is dead. Re-create instead of
    # silently serving codes that will be rejected at checkout.
    stale = False
    probe = next((c.stripe_coupon_id for c in coupons if c.stripe_coupon_id), "")
    if probe and not reset:
        try:
            stripe.Coupon.retrieve(probe)
        except Exception:
            stale = True
    reset = reset or stale

    if reset:
        for p in products:
            p.stripe_product_id = ""
        for c in coupons:
            c.stripe_coupon_id = ""
            c.stripe_promo_id = ""

    prod_made, prod_errors = 0, []
    for p in products:
        try:
            before = p.stripe_product_id
            ensure_product(p)
            if p.stripe_product_id and not before:
                prod_made += 1
            db.add(p)
        except Exception as e:
            prod_errors.append({"product": p.name, "error": str(e)[:180]})

    prod_by_id = {p.id: p.stripe_product_id for p in products if p.id}

    coup_made, coup_skipped, coup_errors = 0, 0, []
    for c in coupons:
        if not c.active and not include_inactive:
            coup_skipped += 1
            continue
        try:
            before = c.stripe_coupon_id
            coupon_svc.ensure_stripe_objects(c, _scope_for(c, prod_by_id))
            if c.stripe_coupon_id and not before:
                coup_made += 1
            db.add(c)
        except Exception as e:
            coup_errors.append({"code": c.code, "error": str(e)[:180]})

    await db.commit()
    return {
        "stripe_mode": _mode(),
        "reset": reset,
        "auto_reset_stale_ids": stale,
        "products": {"total": len(products), "created": prod_made,
                     "errors": prod_errors[:10]},
        "coupons": {"total": len(coupons), "created": coup_made,
                    "skipped_inactive": coup_skipped, "errors": coup_errors[:10]},
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


async def status(db: AsyncSession, org_id: int) -> dict:
    products = (await db.execute(select(BBUProduct).where(
        BBUProduct.org_id == org_id))).scalars().all()
    coupons = (await db.execute(select(BBUCoupon).where(
        BBUCoupon.org_id == org_id))).scalars().all()
    active = [c for c in coupons if c.active]
    return {
        "stripe_mode": _mode() if stripe.api_key else "not configured",
        "products_total": len(products),
        "products_in_stripe": sum(1 for p in products if p.stripe_product_id),
        "coupons_total": len(coupons),
        "coupons_active": len(active),
        "coupons_in_stripe": sum(1 for c in active if c.stripe_promo_id),
        "scoped_coupons": sum(1 for c in active
                              if (c.applies_to or "all").lower() != "all"),
        "not_yet_in_stripe": [c.code for c in active if not c.stripe_promo_id][:25],
    }
