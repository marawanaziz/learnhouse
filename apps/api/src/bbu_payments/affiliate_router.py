"""BBU affiliate program — HTTP routes (mounted at /api/v1/bbu/affiliate).

  GET  /join                 branded signup page
  POST /join                 create affiliate + Stripe Connect onboarding link
  GET  /onboard/{code}       (re)start Stripe Connect onboarding -> redirect
  GET  /return/{code}        post-onboarding return -> portal
  GET  /portal/{token}       affiliate dashboard (link, earnings, payouts)
  GET  /admin                admin dashboard (all affiliates, run payouts)
  POST /admin/settings       update program settings
  POST /admin/payouts/run    run the payout batch now
  POST /webhook/connect      Stripe Connect account.updated webhook

Payouts use Stripe Connect Express + Transfers. Clean-room (no ee imports).
"""
import os
import json
from datetime import datetime, timezone, timedelta

import stripe
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.bbu_payments.models import (
    BBUAffiliate, BBUCommission, BBUPayout, BBUReferralClick, BBUOrder, BBUProduct,
)
from sqlalchemy import func as _func
from src.bbu_payments import affiliates as aff
from src.bbu_admin.auth import authorize_admin
from src.bbu_payments.affiliate_branding import (
    join_page, portal_page, admin_page,
)

router = APIRouter()
stripe.api_key = os.environ.get("BBU_STRIPE_SECRET_KEY", "")
CONNECT_WEBHOOK_SECRET = os.environ.get("BBU_STRIPE_CONNECT_WEBHOOK_SECRET", "")
# Admin pages/actions are gated by an unguessable key (browser-friendly, since
# the API can't read the Next.js NextAuth bearer token from a direct page load).
ADMIN_KEY = os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")


def _check_admin(request: Request, body: dict | None = None):
    if not ADMIN_KEY:
        raise HTTPException(503, "Affiliate admin key not configured")
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key") \
        or (body or {}).get("key") or ""
    if key != ADMIN_KEY:
        raise HTTPException(403, "Forbidden")


def _base_url(request: Request) -> str:
    domain = os.environ.get("LEARNHOUSE_DOMAIN", request.url.netloc)
    scheme = "https" if os.environ.get("LEARNHOUSE_SSL", "true") == "true" else "http"
    return f"{scheme}://{domain}"


def _now():
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
#  Signup + Stripe Connect onboarding
# --------------------------------------------------------------------------- #
@router.get("/join", response_class=HTMLResponse)
async def join_get(request: Request):
    return HTMLResponse(join_page(_base_url(request)))


async def _create_onboarding_link(request: Request, affiliate: BBUAffiliate) -> str:
    """Create/refresh a Stripe Connect Express account + onboarding link."""
    base = _base_url(request)
    if not affiliate.stripe_connect_account_id:
        acct = stripe.Account.create(
            type="express",
            email=affiliate.email or None,
            business_type="individual",
            capabilities={"transfers": {"requested": True}},
            metadata={"bbu_affiliate_id": str(affiliate.id), "ref_code": affiliate.ref_code},
        )
        affiliate.stripe_connect_account_id = acct.id
        affiliate.status = "onboarding"
    link = stripe.AccountLink.create(
        account=affiliate.stripe_connect_account_id,
        refresh_url=f"{base}/api/v1/bbu/affiliate/onboard/{affiliate.ref_code}",
        return_url=f"{base}/api/v1/bbu/affiliate/return/{affiliate.ref_code}",
        type="account_onboarding",
    )
    return link.url


@router.post("/join")
async def join_post(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    body = await request.json()
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Email required")
    if not stripe.api_key:
        raise HTTPException(500, "Stripe not configured")
    # de-dupe by email
    existing = (await db_session.execute(
        select(BBUAffiliate).where(BBUAffiliate.email == email)
    )).scalars().first()
    if existing:
        affiliate = existing
        if not affiliate.name and name:
            affiliate.name = name
    else:
        affiliate = BBUAffiliate(
            org_id=1, name=name, email=email, ref_code=aff.gen_ref_code(name),
            status="pending", portal_token=aff.gen_token(), created_at=aff._iso(_now()),
        )
        db_session.add(affiliate)
        await db_session.commit()
        await db_session.refresh(affiliate)
    url = await _create_onboarding_link(request, affiliate)
    db_session.add(affiliate)
    await db_session.commit()
    # Mirror affiliate state onto the GHL contact as fields (code + status), so
    # the welcome / promo-kit workflows can trigger. Fail-soft.
    try:
        from src.bbu_ghl import sync as ghl_sync
        await ghl_sync.sync_affiliate(db_session, affiliate)
    except Exception:
        import traceback
        print(f"[BBU] GHL affiliate sync failed for {email}:\n{traceback.format_exc()[-400:]}", flush=True)
    return {"onboarding_url": url}


@router.get("/onboard/{code}")
async def onboard(code: str, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    affiliate = await aff.get_affiliate_by_ref(db_session, code)
    if not affiliate:
        raise HTTPException(404, "Affiliate not found")
    url = await _create_onboarding_link(request, affiliate)
    db_session.add(affiliate)
    await db_session.commit()
    return RedirectResponse(url)


@router.get("/return/{code}")
async def onboard_return(code: str, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    affiliate = await aff.get_affiliate_by_ref(db_session, code)
    if not affiliate:
        raise HTTPException(404, "Affiliate not found")
    # refresh account status from Stripe
    if affiliate.stripe_connect_account_id:
        try:
            acct = stripe.Account.retrieve(affiliate.stripe_connect_account_id)
            if acct.get("payouts_enabled"):
                affiliate.payouts_enabled = True
                affiliate.status = "active"
            db_session.add(affiliate)
            await db_session.commit()
        except Exception:
            pass
    return RedirectResponse(f"{_base_url(request)}/api/v1/bbu/affiliate/portal/{affiliate.portal_token}")


# --------------------------------------------------------------------------- #
#  Affiliate portal
# --------------------------------------------------------------------------- #
async def _earnings(db_session: AsyncSession, affiliate_id: int):
    rows = (await db_session.execute(
        select(BBUCommission).where(BBUCommission.affiliate_id == affiliate_id)
    )).scalars().all()
    now_iso = _now().isoformat()
    pending = sum(c.amount_cents for c in rows if c.status == "pending")
    available = sum(c.amount_cents for c in rows if c.status == "available"
                    or (c.status == "pending" and c.available_at and c.available_at <= now_iso))
    paid = sum(c.amount_cents for c in rows if c.status == "paid")
    sales = len([c for c in rows if c.status in ("pending", "available", "paid")])
    return {"pending": pending, "available": available, "paid": paid, "sales": sales, "rows": rows}


@router.get("/portal/{token}", response_class=HTMLResponse)
async def portal(token: str, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    affiliate = (await db_session.execute(
        select(BBUAffiliate).where(BBUAffiliate.portal_token == token)
    )).scalars().first()
    if not affiliate:
        raise HTTPException(404, "Portal not found")
    e = await _earnings(db_session, affiliate.id)
    payouts = (await db_session.execute(
        select(BBUPayout).where(BBUPayout.affiliate_id == affiliate.id).order_by(BBUPayout.id.desc())
    )).scalars().all()
    return HTMLResponse(portal_page(affiliate, e, payouts, _base_url(request)))


# --------------------------------------------------------------------------- #
#  Payout engine
# --------------------------------------------------------------------------- #
async def _mark_available(db_session: AsyncSession, org_id: int = 1):
    """Flip pending commissions to available once past their hold date."""
    now_iso = _now().isoformat()
    rows = (await db_session.execute(
        select(BBUCommission).where(
            BBUCommission.org_id == org_id, BBUCommission.status == "pending",
            BBUCommission.available_at <= now_iso,
        )
    )).scalars().all()
    for c in rows:
        c.status = "available"
        db_session.add(c)
    if rows:
        await db_session.commit()
    return len(rows)


async def run_payouts(db_session: AsyncSession, org_id: int = 1, dry_run: bool = False):
    """Batch-pay each affiliate's available commissions past the min threshold."""
    settings = await aff.get_settings(db_session, org_id)
    await _mark_available(db_session, org_id)
    period = _now().strftime("%Y-%m")
    # group available commissions by affiliate
    affs = (await db_session.execute(
        select(BBUAffiliate).where(BBUAffiliate.org_id == org_id, BBUAffiliate.payouts_enabled == True)  # noqa: E712
    )).scalars().all()
    results = []
    for a in affs:
        commissions = (await db_session.execute(
            select(BBUCommission).where(
                BBUCommission.affiliate_id == a.id, BBUCommission.status == "available",
            )
        )).scalars().all()
        total = sum(c.amount_cents for c in commissions)
        if total < settings.min_payout_cents or total <= 0:
            continue
        if dry_run:
            results.append({"affiliate": a.email, "amount_cents": total, "dry_run": True})
            continue
        payout = BBUPayout(
            org_id=org_id, affiliate_id=a.id, amount_cents=total, currency="usd",
            status="pending", period=period, created_at=_now().isoformat(),
        )
        db_session.add(payout)
        await db_session.commit()
        await db_session.refresh(payout)
        try:
            transfer = stripe.Transfer.create(
                amount=total, currency="usd",
                destination=a.stripe_connect_account_id,
                metadata={"bbu_payout_id": str(payout.id), "affiliate": a.email, "period": period},
            )
            payout.stripe_transfer_id = transfer.id
            payout.status = "paid"
            for c in commissions:
                c.status = "paid"
                c.payout_id = payout.id
                db_session.add(c)
            db_session.add(payout)
            await db_session.commit()
            results.append({"affiliate": a.email, "amount_cents": total, "transfer": transfer.id})
        except Exception as e:
            payout.status = "failed"
            db_session.add(payout)
            await db_session.commit()
            results.append({"affiliate": a.email, "amount_cents": total, "error": str(e)})
    return results


# --------------------------------------------------------------------------- #
#  Admin
# --------------------------------------------------------------------------- #
@router.get("/admin", response_class=HTMLResponse)
async def admin(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await authorize_admin(request, db_session, "")  # session (dashboard) or key
    settings = await aff.get_settings(db_session)
    affs = (await db_session.execute(select(BBUAffiliate).order_by(BBUAffiliate.id.desc()))).scalars().all()
    # totals
    rows = (await db_session.execute(select(BBUCommission))).scalars().all()
    totals = {
        "pending": sum(c.amount_cents for c in rows if c.status == "pending"),
        "available": sum(c.amount_cents for c in rows if c.status == "available"),
        "paid": sum(c.amount_cents for c in rows if c.status == "paid"),
    }
    # per-affiliate earned
    earned = {}
    for c in rows:
        if c.status in ("pending", "available", "paid"):
            earned[c.affiliate_id] = earned.get(c.affiliate_id, 0) + c.amount_cents
    return HTMLResponse(admin_page(settings, affs, totals, earned, _base_url(request),
                                   admin_key=request.query_params.get("key", "")))


@router.get("/admin/detail/{aff_id}")
async def admin_detail(aff_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Full per-affiliate profile: their share links, who enrolled through them,
    commissions, clicks and payouts."""
    await authorize_admin(request, db_session, "")
    a = (await db_session.execute(select(BBUAffiliate).where(BBUAffiliate.id == aff_id))).scalars().first()
    if not a:
        raise HTTPException(404, "Affiliate not found")
    base = _base_url(request)
    s = await aff.get_settings(db_session)
    rate = a.commission_rate if a.commission_rate is not None else s.default_commission_rate
    # who enrolled through their link (orders carrying their ref)
    orders = (await db_session.execute(select(BBUOrder).where(
        BBUOrder.affiliate_ref == a.ref_code).order_by(BBUOrder.id.desc()))).scalars().all()
    prod_names = {}
    referred = []
    for o in orders:
        pid = o.product_id
        if pid and pid not in prod_names:
            p = (await db_session.execute(select(BBUProduct).where(BBUProduct.id == pid))).scalars().first()
            prod_names[pid] = p.name if p else f"product {pid}"
        referred.append({"email": o.email, "product": prod_names.get(pid, ""),
                         "amount": round((o.amount_cents or 0) / 100, 2), "status": o.status,
                         "date": (o.paid_at or o.created_at or "")[:10]})
    # commissions
    comms = (await db_session.execute(select(BBUCommission).where(
        BBUCommission.affiliate_id == aff_id).order_by(BBUCommission.id.desc()))).scalars().all()
    commissions = [{"amount": round((c.amount_cents or 0) / 100, 2), "status": c.status,
                    "event": c.event, "date": (c.created_at or "")[:10]} for c in comms]
    earned = {"pending": 0, "available": 0, "paid": 0}
    for c in comms:
        if c.status in earned:
            earned[c.status] += (c.amount_cents or 0)
    # clicks + payouts
    clicks = (await db_session.execute(select(_func.count()).select_from(BBUReferralClick).where(
        BBUReferralClick.affiliate_id == aff_id))).scalar() or 0
    payouts = (await db_session.execute(select(BBUPayout).where(
        BBUPayout.affiliate_id == aff_id).order_by(BBUPayout.id.desc()))).scalars().all()
    payout_rows = [{"amount": round((p.amount_cents or 0) / 100, 2), "status": p.status,
                    "period": p.period, "date": (p.created_at or "")[:10]} for p in payouts]
    return {
        "id": a.id, "name": a.name, "email": a.email, "ref_code": a.ref_code,
        "status": a.status, "rate": round(rate * 100), "payouts_enabled": bool(a.payouts_enabled),
        "referral_link": f"{base}/?ref={a.ref_code}",
        "portal_link": (f"{base}/api/v1/bbu/affiliate/portal/{a.portal_token}" if a.portal_token else ""),
        "join_link": f"{base}/api/v1/bbu/affiliate/join",
        "clicks": int(clicks), "converted": len(referred),
        "earned": {k: round(v / 100, 2) for k, v in earned.items()},
        "referred": referred, "commissions": commissions, "payouts": payout_rows,
    }


@router.post("/admin/create")
async def admin_create(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Add an affiliate manually (name + email). Generates their ref code + portal
    token so you can hand them their links immediately."""
    body = await request.json()
    await authorize_admin(request, db_session, body.get("key", ""))
    email = (body.get("email") or "").strip().lower()
    name = (body.get("name") or "").strip()
    if not email:
        raise HTTPException(400, "email required")
    existing = (await db_session.execute(select(BBUAffiliate).where(
        BBUAffiliate.email == email))).scalars().first()
    if existing:
        return {"ok": True, "id": existing.id, "already": True, "ref_code": existing.ref_code}
    code = aff.gen_ref_code(name or email)
    while (await db_session.execute(select(BBUAffiliate).where(BBUAffiliate.ref_code == code))).scalars().first():
        code = aff.gen_ref_code(name or email)
    rate = body.get("commission_rate")
    a = BBUAffiliate(org_id=1, name=name, email=email, ref_code=code,
                     status="active", commission_rate=(float(rate) if rate not in (None, "") else None),
                     portal_token=aff.gen_token(), created_at=aff._now().isoformat())
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return {"ok": True, "id": a.id, "ref_code": a.ref_code}


@router.post("/admin/settings")
async def update_settings(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    body = await request.json()
    await authorize_admin(request, db_session, body.get("key", ""))
    s = await aff.get_settings(db_session)
    for field in ("default_commission_rate", "commissionable_events", "commission_basis",
                  "attribution_window_days", "attribution_model", "refund_hold_days",
                  "payout_schedule", "min_payout_cents", "self_referral_allowed",
                  "exclude_zero_revenue"):
        if field in body and body[field] is not None:
            setattr(s, field, body[field])
    s.updated_at = _now().isoformat()
    db_session.add(s)
    await db_session.commit()
    return {"ok": True}


@router.post("/admin/payouts/run")
async def admin_run_payouts(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    await authorize_admin(request, db_session, body.get("key", ""))
    results = await run_payouts(db_session, dry_run=bool(body.get("dry_run")))
    return {"results": results}


# --------------------------------------------------------------------------- #
#  Stripe Connect webhook (account.updated)
# --------------------------------------------------------------------------- #
@router.post("/webhook/connect")
async def connect_webhook(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        if CONNECT_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig, CONNECT_WEBHOOK_SECRET)
        else:
            event = json.loads(payload)
    except Exception as e:
        raise HTTPException(400, f"Invalid webhook: {e}")
    etype = event["type"] if isinstance(event, dict) else event.type
    data = event["data"]["object"] if isinstance(event, dict) else event.data.object
    if etype == "account.updated":
        acct_id = data.get("id")
        affiliate = (await db_session.execute(
            select(BBUAffiliate).where(BBUAffiliate.stripe_connect_account_id == acct_id)
        )).scalars().first()
        if affiliate and data.get("payouts_enabled"):
            if not affiliate.payouts_enabled:
                affiliate.payouts_enabled = True
                affiliate.status = "active"
                db_session.add(affiliate)
                await db_session.commit()
                # TODO(P4): push to GHL for welcome sequence + promo kit
    return JSONResponse({"received": True})
