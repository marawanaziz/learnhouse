"""BBU affiliate program — core logic (settings, attribution, commission ledger).

Kept separate from the payments router so the checkout/webhook code stays lean.
Everything rule-related is read from BBUAffiliateSettings (with per-affiliate
overrides) — no hard-coded rates or windows.
"""
import secrets
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.bbu_payments.models import (
    BBUAffiliate, BBUAffiliateRefAlias, BBUAffiliateSettings, BBUCommission,
    BBUReferralClick, BBUOrder,
)


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


async def get_settings(db: AsyncSession, org_id: int = 1) -> BBUAffiliateSettings:
    """Fetch the program settings row, creating the launch defaults on first use."""
    row = (await db.execute(
        select(BBUAffiliateSettings).where(BBUAffiliateSettings.org_id == org_id)
    )).scalars().first()
    if row:
        return row
    row = BBUAffiliateSettings(org_id=org_id, updated_at=_iso(_now()))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def gen_ref_code(name: str) -> str:
    base = "".join(c for c in (name or "").upper() if c.isalnum())[:8] or "BBU"
    return f"{base}{secrets.token_hex(2).upper()}"


def gen_token() -> str:
    return secrets.token_urlsafe(24)


async def get_affiliate_by_ref(db: AsyncSession, ref_code: str, org_id: int = 1):
    if not ref_code:
        return None
    affiliate = (await db.execute(
        select(BBUAffiliate).where(
            BBUAffiliate.ref_code == ref_code, BBUAffiliate.org_id == org_id
        )
    )).scalars().first()
    if affiliate:
        return affiliate
    alias = (await db.execute(
        select(BBUAffiliateRefAlias).where(
            BBUAffiliateRefAlias.ref_code == ref_code,
            BBUAffiliateRefAlias.org_id == org_id,
        )
    )).scalars().first()
    if not alias:
        return None
    return (await db.execute(
        select(BBUAffiliate).where(
            BBUAffiliate.id == alias.affiliate_id,
            BBUAffiliate.org_id == org_id,
        )
    )).scalars().first()


async def log_click(db: AsyncSession, affiliate: BBUAffiliate, landing_path: str, ip_hash: str):
    db.add(BBUReferralClick(
        org_id=affiliate.org_id, affiliate_id=affiliate.id, ref_code=affiliate.ref_code,
        landing_path=landing_path[:500], ip_hash=ip_hash, created_at=_iso(_now()),
    ))
    await db.commit()


def _rate_for(aff: BBUAffiliate, s: BBUAffiliateSettings) -> float:
    return aff.commission_rate if aff.commission_rate is not None else s.default_commission_rate


def _events_for(aff: BBUAffiliate, s: BBUAffiliateSettings) -> set:
    raw = aff.commissionable_events if aff.commissionable_events is not None else s.commissionable_events
    return {e.strip() for e in (raw or "").split(",") if e.strip()}


def _commissionable_amount(order: BBUOrder, s: BBUAffiliateSettings) -> int:
    """The amount the rate is applied to, per commission_basis."""
    gross = order.amount_cents or 0
    if s.commission_basis == "gross":
        return gross
    # net_after_fees: subtract an estimated Stripe fee
    fee = round(gross * s.stripe_fee_pct) + s.stripe_fee_flat_cents
    return max(0, gross - fee)


async def book_commission_for_order(db: AsyncSession, order: BBUOrder, event: str = "first_sale"):
    """Called from the paid-order webhook. Books a commission if the order was
    referred, the event is commissionable, and it isn't excluded. All rules from
    settings — safe to call on every paid order (no-ops when not applicable)."""
    if not order.affiliate_ref:
        return None
    s = await get_settings(db, order.org_id)
    affrow = await get_affiliate_by_ref(db, order.affiliate_ref, order.org_id)
    if not affrow or affrow.status == "suspended":
        return None
    # zero-revenue exclusion (grant / 100%-off)
    if s.exclude_zero_revenue and (order.amount_cents or 0) <= 0:
        return None
    # event must be commissionable
    if event not in _events_for(affrow, s):
        return None
    # self-referral guard
    if not s.self_referral_allowed and order.email and affrow.email and \
            order.email.strip().lower() == affrow.email.strip().lower():
        return None
    # idempotency: one commission per (order, event)
    existing = (await db.execute(
        select(BBUCommission).where(
            BBUCommission.order_id == order.id, BBUCommission.event == event
        )
    )).scalars().first()
    if existing:
        return existing
    aff = affrow

    rate = _rate_for(aff, s)
    basis = _commissionable_amount(order, s)
    amount = round(basis * rate)
    if amount <= 0:
        return None
    now = _now()
    c = BBUCommission(
        org_id=order.org_id, affiliate_id=aff.id, order_id=order.id, event=event,
        basis_cents=basis, rate=rate, amount_cents=amount, currency=order.currency,
        status="pending", available_at=_iso(now + timedelta(days=s.refund_hold_days)),
        created_at=_iso(now),
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def reverse_commissions_for_order(db: AsyncSession, order_id: int):
    """On refund: reverse any not-yet-paid commissions for the order."""
    rows = (await db.execute(
        select(BBUCommission).where(BBUCommission.order_id == order_id)
    )).scalars().all()
    changed = 0
    for c in rows:
        if c.status in ("pending", "available"):
            c.status = "reversed"
            db.add(c)
            changed += 1
    if changed:
        await db.commit()
    return changed
