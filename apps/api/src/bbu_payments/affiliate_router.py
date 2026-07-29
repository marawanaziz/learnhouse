"""BBU affiliate program — HTTP routes (mounted at /api/v1/bbu/affiliate).

  GET  /join                 branded signup page
  POST /join                 create affiliate + Stripe Connect onboarding link
  GET  /me/onboarding        signed-in Stripe Connect onboarding -> redirect
  GET  /me/return            signed-in post-onboarding return -> account page
  GET  /me/dashboard         signed-in Stripe Express dashboard -> redirect
  GET  /onboard/{code}       legacy portal onboarding -> redirect
  GET  /return/{code}        legacy post-onboarding return -> portal
  GET  /portal/{token}       affiliate dashboard (link, earnings, payouts)
  GET  /admin                admin dashboard (all affiliates, run payouts)
  POST /admin/settings       update program settings
  POST /admin/payouts/run    run the payout batch now
  POST /webhook/connect      Stripe Connect account.updated webhook

Payouts use Stripe Connect Express + Transfers. Clean-room (no ee imports).
"""
import asyncio
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import stripe
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.security.auth import get_current_user, resolve_acting_user_id
from src.db.users import User, AnonymousUser
from src.bbu_payments.models import (
    BBUAffiliate, BBUCommission, BBUPayout, BBUReferralClick, BBUOrder, BBUProduct,
)
from sqlalchemy import func as _func
from src.bbu_payments import affiliates as aff
from src.bbu_payments.public_url import get_bbu_public_base_url
from src.bbu_admin.auth import authorize_admin
from src.bbu_payments.affiliate_branding import (
    member_join_page, portal_page, admin_page,
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
    return get_bbu_public_base_url(request)


def _now():
    return datetime.now(timezone.utc)


NO_CACHE_HEADERS = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
}


def _safe_orgslug(value: str) -> str:
    """Keep Stripe return/refresh redirects on the expected organization path."""
    value = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,99}", value):
        return value
    return (
        os.environ.get("LEARNHOUSE_INITIAL_ORG_SLUG")
        or os.environ.get("NEXT_PUBLIC_LEARNHOUSE_DEFAULT_ORG")
        or "birth-and-baby-university"
    )


def _member_account_url(request: Request, orgslug: str, result: str = "") -> str:
    # The learner-facing app keeps account routes relative to the active
    # tenant/custom domain. Prefixing the organization slug here produces a
    # non-existent route on BBU's custom domain after Stripe returns.
    path = "/account/affiliate"
    if result:
        path += "?" + urlencode({"stripe": result})
    return f"{_base_url(request)}{path}"


def _connect_state(account) -> dict:
    """Translate Stripe's account object into the learner-facing payout states."""
    if not account:
        return {
            "status": "not_started",
            "payouts_enabled": False,
            "details_submitted": False,
            "currently_due_count": 0,
            "disabled_reason": "",
        }
    requirements = account.get("requirements") or {}
    currently_due = requirements.get("currently_due") or []
    disabled_reason = requirements.get("disabled_reason") or ""
    payouts_enabled = bool(account.get("payouts_enabled"))
    details_submitted = bool(account.get("details_submitted"))
    if payouts_enabled:
        status = "connected"
    elif disabled_reason:
        status = "restricted"
    elif not details_submitted or currently_due:
        status = "incomplete"
    else:
        status = "pending_review"
    return {
        "status": status,
        "payouts_enabled": payouts_enabled,
        "details_submitted": details_submitted,
        "currently_due_count": len(currently_due),
        "disabled_reason": disabled_reason,
    }


def _apply_connect_state(affiliate: BBUAffiliate, account) -> dict:
    state = _connect_state(account)
    affiliate.payouts_enabled = state["payouts_enabled"]
    if affiliate.status != "suspended":
        affiliate.status = "active" if state["payouts_enabled"] else "onboarding"
    return state


async def _refresh_connect_state(
    db_session: AsyncSession,
    affiliate: BBUAffiliate,
) -> dict:
    if not affiliate.stripe_connect_account_id:
        return _connect_state(None)
    try:
        account = await asyncio.to_thread(
            stripe.Account.retrieve,
            affiliate.stripe_connect_account_id,
        )
    except Exception:
        return {
            "status": (
                "connected" if affiliate.payouts_enabled else "unavailable"
            ),
            "payouts_enabled": bool(affiliate.payouts_enabled),
            "details_submitted": False,
            "currently_due_count": 0,
            "disabled_reason": "",
        }
    state = _apply_connect_state(affiliate, account)
    db_session.add(affiliate)
    await db_session.commit()
    return state


async def _member_account_and_affiliate(
    db_session: AsyncSession,
    user,
) -> tuple[User, BBUAffiliate | None]:
    uid = (
        resolve_acting_user_id(user)
        if user and not isinstance(user, AnonymousUser)
        else 0
    )
    if not uid:
        raise HTTPException(401, "Sign in required")
    account = (await db_session.execute(
        select(User).where(User.id == uid)
    )).scalars().first()
    if not account:
        raise HTTPException(404, "Account not found")
    email = (account.email or "").strip().lower()
    affiliate = (await db_session.execute(
        select(BBUAffiliate).where(
            BBUAffiliate.org_id == 1,
            _func.lower(BBUAffiliate.email) == email,
        )
    )).scalars().first()
    return account, affiliate


async def _get_or_create_member_affiliate(
    db_session: AsyncSession,
    account: User,
    affiliate: BBUAffiliate | None,
) -> tuple[BBUAffiliate, bool]:
    if affiliate:
        if affiliate.status == "suspended":
            raise HTTPException(403, "Affiliate account is suspended")
        return affiliate, False
    name = _account_name(account)
    ref_code = aff.gen_ref_code(name)
    while await aff.get_affiliate_by_ref(db_session, ref_code):
        ref_code = aff.gen_ref_code(name)
    affiliate = BBUAffiliate(
        org_id=1,
        name=name,
        email=(account.email or "").strip().lower(),
        ref_code=ref_code,
        status="pending",
        portal_token=aff.gen_token(),
        created_at=aff._iso(_now()),
    )
    db_session.add(affiliate)
    await db_session.commit()
    await db_session.refresh(affiliate)
    return affiliate, True


def _account_name(account: User) -> str:
    full_name = " ".join(
        part.strip()
        for part in (
            getattr(account, "first_name", "") or "",
            getattr(account, "last_name", "") or "",
        )
        if part and part.strip()
    )
    return full_name or getattr(account, "username", "") or account.email


async def _sync_affiliate_to_ghl(
    db_session: AsyncSession,
    affiliate: BBUAffiliate,
) -> None:
    try:
        from src.bbu_ghl import sync as ghl_sync
        await ghl_sync.sync_affiliate(db_session, affiliate)
    except Exception:
        import traceback
        print(
            f"[BBU] GHL affiliate sync failed for {affiliate.email}:\n"
            f"{traceback.format_exc()[-400:]}",
            flush=True,
        )


# --------------------------------------------------------------------------- #
#  Signup + Stripe Connect onboarding
# --------------------------------------------------------------------------- #
@router.get("/join", response_class=HTMLResponse)
async def join_get(request: Request):
    return RedirectResponse(
        _member_account_url(request, "", "join"),
        status_code=303,
    )


async def _create_onboarding_link(
    request: Request,
    affiliate: BBUAffiliate,
    db_session: AsyncSession,
    *,
    member_flow: bool = False,
    orgslug: str = "",
) -> str:
    """Create or resume a Stripe Express account without duplicating it."""
    if not stripe.api_key:
        raise HTTPException(503, "Stripe payouts are not configured")
    base = _base_url(request)
    if not affiliate.stripe_connect_account_id:
        acct = await asyncio.to_thread(
            stripe.Account.create,
            type="express",
            email=affiliate.email or None,
            business_type="individual",
            business_profile={
                "product_description": (
                    "Affiliate referral commissions for Birth & Baby University"
                ),
            },
            capabilities={"transfers": {"requested": True}},
            metadata={
                "bbu_affiliate_id": str(affiliate.id),
                "ref_code": affiliate.ref_code,
            },
            idempotency_key=f"bbu_affiliate_connect_{affiliate.id}",
        )
        affiliate.stripe_connect_account_id = acct.id
        affiliate.status = "onboarding"
        db_session.add(affiliate)
        # Persist the Stripe account before generating the single-use link. If
        # link creation fails, the learner can safely retry without a duplicate.
        await db_session.commit()

    if member_flow:
        query = urlencode({"orgslug": _safe_orgslug(orgslug)})
        refresh_url = (
            f"{base}/api/v1/bbu/affiliate/me/onboarding?{query}"
        )
        return_url = f"{base}/api/v1/bbu/affiliate/me/return?{query}"
    else:
        if not affiliate.portal_token:
            affiliate.portal_token = aff.gen_token()
            db_session.add(affiliate)
            await db_session.commit()
        refresh_url = (
            f"{base}/api/v1/bbu/affiliate/portal/"
            f"{affiliate.portal_token}/onboarding"
        )
        return_url = (
            f"{base}/api/v1/bbu/affiliate/portal/"
            f"{affiliate.portal_token}/return"
        )
    link = await asyncio.to_thread(
        stripe.AccountLink.create,
        account=affiliate.stripe_connect_account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
        collection_options={"fields": "eventually_due"},
    )
    return link.url


@router.post("/join")
async def join_post(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    body = await request.json()
    account, affiliate = await _member_account_and_affiliate(db_session, user)
    requested_email = (body.get("email") or "").strip().lower()
    if requested_email and requested_email != (account.email or "").strip().lower():
        raise HTTPException(403, "Use your signed-in email")
    affiliate, _created = await _get_or_create_member_affiliate(
        db_session, account, affiliate
    )
    url = await _create_onboarding_link(
        request,
        affiliate,
        db_session,
        member_flow=True,
        orgslug=body.get("orgslug") or "",
    )
    await _sync_affiliate_to_ghl(db_session, affiliate)
    return {"onboarding_url": url}


@router.get("/onboard/{code}")
async def onboard(
    code: str,
    request: Request,
    orgslug: str = "",
    db_session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    """Compatibility route for old buttons, now protected by account identity."""
    _account, member_affiliate = await _member_account_and_affiliate(
        db_session, user
    )
    affiliate = await aff.get_affiliate_by_ref(db_session, code)
    if not affiliate or not member_affiliate or affiliate.id != member_affiliate.id:
        raise HTTPException(404, "Affiliate not found")
    url = await _create_onboarding_link(
        request,
        affiliate,
        db_session,
        member_flow=True,
        orgslug=orgslug,
    )
    db_session.add(affiliate)
    await db_session.commit()
    return RedirectResponse(url, status_code=303)


@router.get("/return/{code}")
async def onboard_return(
    code: str,
    request: Request,
    orgslug: str = "",
    db_session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    """Compatibility return route for account-authenticated onboarding."""
    _account, member_affiliate = await _member_account_and_affiliate(
        db_session, user
    )
    affiliate = await aff.get_affiliate_by_ref(db_session, code)
    if not affiliate or not member_affiliate or affiliate.id != member_affiliate.id:
        raise HTTPException(404, "Affiliate not found")
    state = await _refresh_connect_state(db_session, affiliate)
    await _sync_affiliate_to_ghl(db_session, affiliate)
    return RedirectResponse(
        _member_account_url(request, orgslug, state["status"]),
        status_code=303,
    )


async def _affiliate_by_portal_token(
    db_session: AsyncSession,
    token: str,
) -> BBUAffiliate:
    affiliate = (await db_session.execute(
        select(BBUAffiliate).where(BBUAffiliate.portal_token == token)
    )).scalars().first()
    if not affiliate:
        raise HTTPException(404, "Portal not found")
    return affiliate


@router.get("/portal/{token}/onboarding")
async def portal_onboarding(
    token: str,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    """Resume onboarding from an unguessable legacy portal link."""
    affiliate = await _affiliate_by_portal_token(db_session, token)
    if affiliate.status == "suspended":
        raise HTTPException(403, "Affiliate account is suspended")
    url = await _create_onboarding_link(request, affiliate, db_session)
    await _sync_affiliate_to_ghl(db_session, affiliate)
    return RedirectResponse(url, status_code=303)


@router.get("/portal/{token}/return")
async def portal_onboarding_return(
    token: str,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    affiliate = await _affiliate_by_portal_token(db_session, token)
    await _refresh_connect_state(db_session, affiliate)
    await _sync_affiliate_to_ghl(db_session, affiliate)
    return RedirectResponse(
        f"{_base_url(request)}/api/v1/bbu/affiliate/portal/{token}",
        status_code=303,
    )


@router.get("/portal/{token}/dashboard")
async def portal_connect_dashboard(
    token: str,
    db_session: AsyncSession = Depends(get_db_session),
):
    affiliate = await _affiliate_by_portal_token(db_session, token)
    if not affiliate.stripe_connect_account_id:
        raise HTTPException(409, "Payout account is not set up")
    state = await _refresh_connect_state(db_session, affiliate)
    if state["status"] != "connected":
        raise HTTPException(409, "Payout account onboarding is incomplete")
    login_link = await asyncio.to_thread(
        stripe.Account.create_login_link,
        affiliate.stripe_connect_account_id,
    )
    return RedirectResponse(login_link.url, status_code=303)


@router.get("/me/onboarding")
async def member_onboarding(
    request: Request,
    orgslug: str = "",
    db_session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    account, affiliate = await _member_account_and_affiliate(db_session, user)
    affiliate, _created = await _get_or_create_member_affiliate(
        db_session, account, affiliate
    )
    url = await _create_onboarding_link(
        request,
        affiliate,
        db_session,
        member_flow=True,
        orgslug=orgslug,
    )
    await _sync_affiliate_to_ghl(db_session, affiliate)
    return RedirectResponse(url, status_code=303)


@router.get("/me/return")
async def member_onboarding_return(
    request: Request,
    orgslug: str = "",
    db_session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    _account, affiliate = await _member_account_and_affiliate(db_session, user)
    if not affiliate:
        raise HTTPException(404, "Affiliate account not found")
    state = await _refresh_connect_state(db_session, affiliate)
    await _sync_affiliate_to_ghl(db_session, affiliate)
    return RedirectResponse(
        _member_account_url(request, orgslug, state["status"]),
        status_code=303,
    )


@router.get("/me/dashboard")
async def member_connect_dashboard(
    db_session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    _account, affiliate = await _member_account_and_affiliate(db_session, user)
    if not affiliate or not affiliate.stripe_connect_account_id:
        raise HTTPException(409, "Payout account is not set up")
    state = await _refresh_connect_state(db_session, affiliate)
    if state["status"] != "connected":
        raise HTTPException(409, "Payout account onboarding is incomplete")
    login_link = await asyncio.to_thread(
        stripe.Account.create_login_link,
        affiliate.stripe_connect_account_id,
    )
    return RedirectResponse(login_link.url, status_code=303)


@router.get("/me/status")
async def member_connect_status(
    db_session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    _account, affiliate = await _member_account_and_affiliate(db_session, user)
    if not affiliate:
        return JSONResponse(
            {"is_affiliate": False, **_connect_state(None)},
            headers=NO_CACHE_HEADERS,
        )
    state = await _refresh_connect_state(db_session, affiliate)
    return JSONResponse(
        {
            "is_affiliate": True,
            "affiliate_status": affiliate.status,
            **state,
        },
        headers=NO_CACHE_HEADERS,
    )


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
    affiliate = await _affiliate_by_portal_token(db_session, token)
    state = await _refresh_connect_state(db_session, affiliate)
    e = await _earnings(db_session, affiliate.id)
    e["details"] = await _commission_details(db_session, e["rows"])
    payouts = (await db_session.execute(
        select(BBUPayout).where(BBUPayout.affiliate_id == affiliate.id).order_by(BBUPayout.id.desc())
    )).scalars().all()
    base = _base_url(request)
    return HTMLResponse(
        portal_page(
            affiliate,
            e,
            payouts,
            base,
            connect_state=state,
            onboarding_url=(
                f"{base}/api/v1/bbu/affiliate/portal/{token}/onboarding"
            ),
            dashboard_url=(
                f"{base}/api/v1/bbu/affiliate/portal/{token}/dashboard"
            ),
        ),
        headers=NO_CACHE_HEADERS,
    )


async def _commission_details(db_session: AsyncSession, commissions: list[BBUCommission]):
    """Build the member-facing referral ledger from the order attached to each
    commission. Historical Circle affiliate sales are restored as BBUOrder rows,
    so legacy and new referrals use the same display path."""
    order_ids = [c.order_id for c in commissions if c.order_id]
    orders = {}
    products = {}
    if order_ids:
        order_rows = (await db_session.execute(
            select(BBUOrder).where(BBUOrder.id.in_(order_ids))
        )).scalars().all()
        orders = {o.id: o for o in order_rows}
        product_ids = {o.product_id for o in order_rows if o.product_id}
        if product_ids:
            product_rows = (await db_session.execute(
                select(BBUProduct).where(BBUProduct.id.in_(product_ids))
            )).scalars().all()
            products = {p.id: p.name for p in product_rows}

    details = []
    for commission in sorted(
        commissions, key=lambda row: row.created_at or "", reverse=True
    ):
        order = orders.get(commission.order_id)
        extra = (order.extra or {}) if order else {}
        details.append({
            "date": (commission.created_at or "")[:10],
            "customer": (
                extra.get("customer_name")
                or (order.email if order else "")
                or "Referral"
            ),
            "product": (
                products.get(order.product_id, "") if order else ""
            ) or extra.get("product_name", ""),
            "sale_amount_cents": order.amount_cents if order else commission.basis_cents,
            "commission_amount_cents": commission.amount_cents,
            "status": commission.status,
        })
    return details


@router.get("/me", response_class=HTMLResponse)
async def my_affiliate_portal(
    request: Request,
    orgslug: str = "",
    db_session: AsyncSession = Depends(get_db_session),
    user=Depends(get_current_user),
):
    """Open the signed-in learner's affiliate dashboard by account email.

    This restores the account-level dashboard Circle affiliates previously had;
    they no longer need an admin to locate or resend a private portal token.
    Non-affiliates see the normal join flow.
    """
    account, affiliate = await _member_account_and_affiliate(db_session, user)
    base = _base_url(request)
    safe_orgslug = _safe_orgslug(orgslug)
    if not affiliate:
        return HTMLResponse(
            member_join_page(
                _account_name(account),
                account.email,
                base,
                safe_orgslug,
            ),
            headers=NO_CACHE_HEADERS,
        )

    state = await _refresh_connect_state(db_session, affiliate)
    e = await _earnings(db_session, affiliate.id)
    e["details"] = await _commission_details(db_session, e["rows"])
    payouts = (await db_session.execute(
        select(BBUPayout).where(
            BBUPayout.affiliate_id == affiliate.id
        ).order_by(BBUPayout.id.desc())
    )).scalars().all()
    query = urlencode({"orgslug": safe_orgslug})
    return HTMLResponse(
        portal_page(
            affiliate,
            e,
            payouts,
            base,
            connect_state=state,
            onboarding_url=(
                f"{base}/api/v1/bbu/affiliate/me/onboarding?{query}"
            ),
            dashboard_url=(
                f"{base}/api/v1/bbu/affiliate/me/dashboard"
            ),
        ),
        headers=NO_CACHE_HEADERS,
    )


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
    clicks += a.legacy_visitors_count or 0
    payouts = (await db_session.execute(select(BBUPayout).where(
        BBUPayout.affiliate_id == aff_id).order_by(BBUPayout.id.desc()))).scalars().all()
    payout_rows = [{"amount": round((p.amount_cents or 0) / 100, 2), "status": p.status,
                    "period": p.period, "date": (p.created_at or "")[:10]} for p in payouts]
    return {
        "id": a.id, "name": a.name, "email": a.email, "ref_code": a.ref_code,
        "status": a.status, "rate": round(rate * 100), "payouts_enabled": bool(a.payouts_enabled),
        "referral_link": f"{base}/api/v1/bbu/r/{a.ref_code}",
        "portal_link": (f"{base}/api/v1/bbu/affiliate/portal/{a.portal_token}" if a.portal_token else ""),
        "join_link": f"{base}/api/v1/bbu/affiliate/join",
        "clicks": int(clicks), "leads": int(a.legacy_leads_count or 0),
        "converted": len(referred),
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
    while await aff.get_affiliate_by_ref(db_session, code):
        code = aff.gen_ref_code(name or email)
    rate = body.get("commission_rate")
    a = BBUAffiliate(org_id=1, name=name, email=email, ref_code=code,
                     status="active", commission_rate=(float(rate) if rate not in (None, "") else None),
                     portal_token=aff.gen_token(), created_at=aff._now().isoformat())
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return {"ok": True, "id": a.id, "ref_code": a.ref_code}


@router.post("/admin/import")
async def admin_import(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Bulk-import existing affiliates (e.g. the ThriveCart export). Preserves each
    affiliate's existing referral code so their old links keep resolving. Idempotent
    by email or ref_code. Body: {affiliates:[{name,email,ref_code}], rate?, source?,
    status?, dry_run?}."""
    body = await request.json()
    await authorize_admin(request, db_session, body.get("key", ""))
    dry = str(body.get("dry_run", True)).lower() != "false"
    rate = body.get("rate", 0.5)
    rate = float(rate) if rate not in (None, "") else None
    source = (body.get("source") or "thrivecart")[:24]
    status = (body.get("status") or "active")[:20]
    affs = body.get("affiliates") or []
    created = existing = skipped = 0
    errors = []
    for a in affs:
        email = (a.get("email") or "").strip().lower()
        name = (a.get("name") or "").strip()
        code = (a.get("ref_code") or "").strip()
        if not email or "@" not in email:
            skipped += 1
            continue
        try:
            ex = (await db_session.execute(select(BBUAffiliate).where(
                BBUAffiliate.org_id == 1,
                BBUAffiliate.email == email,
            ))).scalars().first()
            if not ex and code:
                ex = await aff.get_affiliate_by_ref(db_session, code)
            if ex:
                existing += 1
                continue
            if not code:
                code = aff.gen_ref_code(name or email)
            # avoid ref_code collisions with a different affiliate
            while await aff.get_affiliate_by_ref(db_session, code):
                code = aff.gen_ref_code(name or email)
            if dry:
                created += 1
                continue
            db_session.add(BBUAffiliate(
                org_id=1, name=name, email=email, ref_code=code, status=status,
                legacy_source=source, commission_rate=rate,
                portal_token=aff.gen_token(), created_at=aff._iso(_now())))
            await db_session.commit()
            created += 1
        except Exception as e:
            await db_session.rollback()
            errors.append(f"{email}: {type(e).__name__}: {e}")
    return {"dry_run": dry, "source": source, "input": len(affs), "created": created,
            "existing": existing, "skipped": skipped, "errors": errors[:20],
            "error_count": len(errors)}


@router.post("/admin/set-status")
async def admin_set_status(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Change an affiliate's status (active | suspended) or delete them."""
    body = await request.json()
    await authorize_admin(request, db_session, body.get("key", ""))
    a = (await db_session.execute(select(BBUAffiliate).where(
        BBUAffiliate.id == int(body.get("id", 0))))).scalars().first()
    if not a:
        raise HTTPException(404, "Affiliate not found")
    if body.get("delete"):
        await db_session.delete(a)
        await db_session.commit()
        return {"ok": True, "deleted": a.id}
    st = (body.get("status") or "").strip()
    if st in ("active", "suspended", "pending", "onboarding"):
        a.status = st
        db_session.add(a)
        await db_session.commit()
    return {"ok": True, "status": a.status}


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
            val = body[field]
            # Commission rate is entered as a PERCENTAGE in the admin UI (e.g. 50),
            # but stored as a 0-1 decimal. Normalize: any value > 1 is a percent.
            if field == "default_commission_rate":
                try:
                    fv = float(val)
                    val = fv / 100.0 if fv > 1 else fv
                except (TypeError, ValueError):
                    continue
            setattr(s, field, val)
    # The admin enters a dollar threshold; "5,000" meaning cents read as $5,000
    # and silently blocked every payout. Store cents, show and accept dollars.
    if body.get("min_payout_dollars") is not None:
        try:
            s.min_payout_cents = int(round(float(body["min_payout_dollars"]) * 100))
        except (TypeError, ValueError):
            pass
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
    if not CONNECT_WEBHOOK_SECRET:
        raise HTTPException(503, "Stripe Connect webhook is not configured")
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig,
            CONNECT_WEBHOOK_SECRET,
        )
    except Exception as e:
        raise HTTPException(400, f"Invalid webhook: {e}")
    etype = event["type"] if isinstance(event, dict) else event.type
    data = event["data"]["object"] if isinstance(event, dict) else event.data.object
    if etype == "account.updated":
        acct_id = data.get("id")
        affiliate = (await db_session.execute(
            select(BBUAffiliate).where(BBUAffiliate.stripe_connect_account_id == acct_id)
        )).scalars().first()
        if affiliate:
            _apply_connect_state(affiliate, data)
            db_session.add(affiliate)
            await db_session.commit()
            await _sync_affiliate_to_ghl(db_session, affiliate)
    return JSONResponse({"received": True})
