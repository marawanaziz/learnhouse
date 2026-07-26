"""BBU -> GHL sync admin endpoints (admin-key gated).

  GET  /bbu/ghl/health            config + connectivity check
  POST /bbu/ghl/sync/order/{id}   re-sync one paid order (idempotent)
  POST /bbu/ghl/backfill          bulk-sync paid orders. Guarded: requires
                                  confirm=true and honours a `limit`, because
                                  it writes into the client's live CRM.
"""
import os
import json
import redis
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.bbu_ghl import sync as ghl_sync
from src.bbu_ghl.client import GHLClient, is_configured, LOCATION_ID
from src.bbu_payments.models import BBUProduct, BBUOrder
from src.db.users import User
from src.db.user_organizations import UserOrganization
from src.db.organizations import Organization
from src.services.users.password_reset import generate_secure_reset_code
from config.config import get_learnhouse_config

router = APIRouter()

ADMIN_KEY = os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")


def _check(request: Request):
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key", "")
    if not ADMIN_KEY or key != ADMIN_KEY:
        raise HTTPException(403, "Forbidden")


@router.get("/health")
async def health(request: Request):
    _check(request)
    if not is_configured():
        return {"configured": False,
                "hint": "set BBU_GHL_PIT and BBU_GHL_LOCATION_ID"}
    async with GHLClient() as ghl:
        assoc = await ghl.association_id()
    return {"configured": True, "location_id": LOCATION_ID,
            "association_id": assoc,
            "module": "custom_objects.course_enrollment"}


@router.post("/sync/order/{order_id}")
async def sync_order(order_id: int, request: Request,
                     db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    order = (await db_session.execute(
        select(BBUOrder).where(BBUOrder.id == order_id)
    )).scalars().first()
    if not order:
        raise HTTPException(404, "Order not found")
    product = (await db_session.execute(
        select(BBUProduct).where(BBUProduct.id == order.product_id)
    )).scalars().first()
    if not product:
        raise HTTPException(404, "Product not found")
    return await ghl_sync.sync_order(db_session, order, product)


@router.post("/backfill")
async def backfill(request: Request,
                   db_session: AsyncSession = Depends(get_db_session)):
    """Bulk-sync paid orders into GHL. Writes to the client's live CRM, so it
    is explicit-opt-in: pass confirm=true. Default limit keeps a mistake small."""
    _check(request)
    confirm = request.query_params.get("confirm") == "true"
    limit = int(request.query_params.get("limit", "25"))
    orders = (await db_session.execute(
        select(BBUOrder).where(BBUOrder.status == "paid").limit(limit)
    )).scalars().all()
    if not confirm:
        return {"dry_run": True, "would_sync": len(orders),
                "hint": "re-call with confirm=true to execute"}
    results, errors = 0, []
    for o in orders:
        try:
            p = (await db_session.execute(
                select(BBUProduct).where(BBUProduct.id == o.product_id)
            )).scalars().first()
            if not p:
                continue
            await ghl_sync.sync_order(db_session, o, p)
            results += 1
        except Exception as e:
            errors.append(f"order {o.id}: {e}")
    return {"synced": results, "errors": errors[:10], "error_count": len(errors)}


@router.post("/password-setup-blast")
async def password_setup_blast(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Mint per-user password-setup (reset) links and push them into GHL as a
    contact field + a trigger tag, so a GHL workflow can send the 'set your
    password' email (the Monday launch email). Links use a long TTL so they stay
    valid through launch. Body: {test_email?, limit?, ttl_days?, tag?, base_url?,
    dry_run?}. DRY-RUN by default (counts targets, writes nothing)."""
    _check(request)
    if not is_configured():
        raise HTTPException(503, "GHL not configured (BBU_GHL_PIT / BBU_GHL_LOCATION_ID)")
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    dry_run = str(body.get("dry_run", True)).lower() != "false"
    test_email = (body.get("test_email") or "").strip().lower()
    limit = int(body.get("limit") or 0)
    ttl = int(body.get("ttl_days") or 45) * 86400
    tag = body.get("tag") or "bbu-password-setup"
    base = (body.get("base_url") or os.environ.get("BBU_PUBLIC_BASE_URL")
            or "https://app-production-500b.up.railway.app").rstrip("/")

    org = (await db_session.execute(select(Organization).where(Organization.id == 1))).scalars().first()
    if not org:
        raise HTTPException(404, "org 1 not found")

    if test_email:
        users = (await db_session.execute(select(User).where(User.email == test_email))).scalars().all()
    else:
        q = (select(User).join(UserOrganization, UserOrganization.user_id == User.id)
             .where(UserOrganization.org_id == 1))
        users = (await db_session.execute(q)).scalars().all()
        if limit:
            users = users[:limit]

    if dry_run:
        return {"dry_run": True, "targets": len(users), "ttl_days": ttl // 86400,
                "tag": tag, "sample": [u.email for u in users[:5]]}

    r = redis.Redis.from_url(get_learnhouse_config().redis_config.redis_connection_string)
    pushed = 0
    errors = []
    async with GHLClient() as ghl:
        field_key = await ghl.ensure_text_field("BBU Password Reset URL")
        for u in users:
            try:
                code = generate_secure_reset_code(8)
                obj = {"reset_code": code,
                       "reset_code_expires": int(datetime.now().timestamp()) + ttl,
                       "reset_code_type": "password_reset",
                       "created_at": datetime.now().isoformat(),
                       "created_by": u.user_uuid, "org_uuid": org.org_uuid}
                r.set(f"pwd_reset:user:{u.user_uuid}:org:{org.org_uuid}:code:{code}",
                      json.dumps(obj), ex=ttl)
                url = f"{base}/reset?email={quote(u.email)}&resetCode={code}"
                await ghl.upsert_contact(email=u.email, first_name=u.first_name or "",
                                         last_name=u.last_name or "",
                                         fields={field_key: url}, tags=[tag])
                pushed += 1
            except Exception as e:
                errors.append(f"{u.email}: {type(e).__name__}: {e}")
    return {"dry_run": False, "targets": len(users), "pushed": pushed,
            "ghl_field_key": field_key, "tag": tag, "reset_link_ttl_days": ttl // 86400,
            "errors": errors[:20], "error_count": len(errors)}


# ===========================================================================
# Email enablement: push the merge-field data GHL workflows need.
# Each blast writes contact fields + a trigger tag; the GHL workflow listens
# on the tag and sends the matching template.
# ===========================================================================
@router.post("/affiliate-blast")
async def affiliate_blast(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Push each affiliate's portal + referral link into GHL and tag them so the
    affiliate welcome/newsletter workflow can send. Body: {tag?, dry_run?, limit?}.
    DRY-RUN by default."""
    _check(request)
    if not is_configured():
        raise HTTPException(503, "GHL not configured")
    from src.bbu_payments.models import BBUAffiliate
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    dry_run = str(body.get("dry_run", True)).lower() != "false"
    tag = body.get("tag") or "bbu-affiliate-welcome"
    limit = int(body.get("limit") or 0)
    base = (body.get("base_url") or os.environ.get("BBU_PUBLIC_BASE_URL")
            or "https://app-production-500b.up.railway.app").rstrip("/")

    rows = (await db_session.execute(select(BBUAffiliate).where(
        BBUAffiliate.org_id == 1))).scalars().all()
    rows = [a for a in rows if (a.email or "").strip()]
    if limit:
        rows = rows[:limit]
    if dry_run:
        return {"dry_run": True, "targets": len(rows), "tag": tag,
                "sample": [a.email for a in rows[:5]]}

    pushed, errors = 0, []
    async with GHLClient() as ghl:
        portal_key = await ghl.ensure_text_field("BBU Affiliate Portal URL")
        ref_key = await ghl.ensure_text_field("BBU Affiliate Referral URL")
        for a in rows:
            try:
                portal = f"{base}/api/v1/bbu/affiliate/portal?token={a.portal_token}" if getattr(a, "portal_token", "") else f"{base}/api/v1/bbu/affiliate/portal"
                ref = f"{base}/?ref={a.ref_code}"
                nm = (a.name or "").strip().split(" ", 1)
                await ghl.upsert_contact(
                    email=a.email.strip().lower(),
                    first_name=(nm[0] if nm and nm[0] else ""),
                    last_name=(nm[1] if len(nm) > 1 else ""),
                    fields={portal_key: portal, ref_key: ref}, tags=[tag])
                pushed += 1
            except Exception as e:
                errors.append(f"{a.email}: {type(e).__name__}: {e}")
    return {"dry_run": False, "targets": len(rows), "pushed": pushed, "tag": tag,
            "fields": {"portal": portal_key, "referral": ref_key},
            "errors": errors[:15], "error_count": len(errors)}


# Anna's renewal cadence (Jul 2026): 6mo before, 3mo before, monthly, weekly in
# the final month; after expiry at ~1 month, ~3 months, ~1 year.
RENEWAL_STAGES = [
    ("bbu-renewal-6mo",          165,  195),
    ("bbu-renewal-3mo",           75,  105),
    ("bbu-renewal-monthly",       31,   74),
    ("bbu-renewal-weekly",         0,   30),
    ("bbu-renewal-expired-1mo",  -45,   -1),
    ("bbu-renewal-expired-3mo", -135,  -46),
    ("bbu-renewal-expired-1yr", -395, -320),
]


@router.post("/renewal-sync")
async def renewal_sync(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Tag credential holders into the right renewal-cadence bucket and push the
    merge fields the renewal emails use (type, expiry, renew link). Designed to
    run daily. Body: {dry_run?}. DRY-RUN by default."""
    _check(request)
    if not is_configured():
        raise HTTPException(503, "GHL not configured")
    from src.bbu_credentials.models import BBUCredential
    from src.bbu_credentials import service as cred_svc
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    dry_run = str(body.get("dry_run", True)).lower() != "false"
    base = (body.get("base_url") or os.environ.get("BBU_PUBLIC_BASE_URL")
            or "https://app-production-500b.up.railway.app").rstrip("/")

    creds = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == 1))).scalars().all()
    now = cred_svc._now_dt()
    buckets: dict = {}
    plan = []
    for c in creds:
        exp_raw = (c.full_expires_at if c.status == "full" else c.provisional_expires_at) or ""
        exp = cred_svc._parse(exp_raw)
        if not exp:
            continue
        days = (exp - now).days
        stage = next((t for t, lo, hi in RENEWAL_STAGES if lo <= days <= hi), None)
        if not stage:
            continue
        u = (await db_session.execute(select(User).where(User.id == c.user_id))).scalars().first()
        if not u or not (u.email or "").strip():
            continue
        buckets[stage] = buckets.get(stage, 0) + 1
        plan.append((u, c, stage, exp_raw[:10], days))

    if dry_run:
        return {"dry_run": True, "matched": len(plan), "by_stage": buckets}

    pushed, errors = 0, []
    async with GHLClient() as ghl:
        f_type = await ghl.ensure_text_field("BBU Credential Type")
        f_exp = await ghl.ensure_text_field("BBU Credential Expires")
        f_renew = await ghl.ensure_text_field("BBU Renew URL")
        for u, c, stage, exp_s, days in plan:
            try:
                await ghl.upsert_contact(
                    email=u.email.strip().lower(),
                    first_name=u.first_name or "", last_name=u.last_name or "",
                    fields={f_type: (c.credential_type or "").title(),
                            f_exp: exp_s,
                            f_renew: f"{base}/store"},
                    tags=[stage])
                pushed += 1
            except Exception as e:
                errors.append(f"{u.email}: {type(e).__name__}: {e}")
    return {"dry_run": False, "matched": len(plan), "pushed": pushed,
            "by_stage": buckets, "errors": errors[:15], "error_count": len(errors)}


# ===========================================================================
# Direct campaign sender.
# GHL workflows cannot be created over the API (POST /workflows/ -> 404), so we
# send through the Conversations API instead. Merge fields are rendered HERE
# (per contact, from LearnHouse data) because a direct send does not run GHL's
# template substitution.
# ===========================================================================
def _render(html: str, ctx: dict) -> str:
    out = html
    for k, v in ctx.items():
        out = out.replace("{{contact.%s}}" % k, v or "")
    return out


@router.post("/send-campaign")
async def send_campaign(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Send one of the BBU GHL templates to a live audience, rendering each
    contact's real merge values. Body:
      {template_name, audience: 'password_setup'|'affiliates'|'renewal:<tag>',
       test_email?, limit?, dry_run?}
    DRY-RUN by default. `test_email` sends to exactly one address."""
    _check(request)
    if not is_configured():
        raise HTTPException(503, "GHL not configured")
    body = await request.json()
    dry_run = str(body.get("dry_run", True)).lower() != "false"
    tmpl_name = (body.get("template_name") or "").strip()
    audience = (body.get("audience") or "password_setup").strip()
    test_email = (body.get("test_email") or "").strip().lower()
    limit = int(body.get("limit") or 0)
    base = (os.environ.get("BBU_PUBLIC_BASE_URL")
            or "https://app-production-500b.up.railway.app").rstrip("/")
    if not tmpl_name:
        raise HTTPException(400, "template_name required")

    async with GHLClient() as ghl:
        # locate the stored template
        st, d = await ghl._req("GET", f"/emails/builder?locationId={LOCATION_ID}&limit=200")
        items = (d or {}).get("builders") or []
        tmpl = next((t for t in items
                     if tmpl_name.lower() in ((t.get("name") or "")).lower()), None)
        if not tmpl:
            raise HTTPException(404, f"template '{tmpl_name}' not found in GHL")
        subject = tmpl.get("subject") or tmpl.get("name") or "Birth & Baby University"
        html = tmpl.get("html") or ""
        if not html:
            st2, d2 = await ghl._req(
                "GET", f"/emails/builder/{LOCATION_ID}/{tmpl.get('id')}")
            html = (d2 or {}).get("html") or ""
        if not html:
            raise HTTPException(422, "template has no HTML body")

        # build the audience with per-contact merge context
        targets = []
        if test_email:
            u = (await db_session.execute(select(User).where(User.email == test_email))).scalars().first()
            targets.append((test_email, (u.first_name if u else ""), {}))
        elif audience == "affiliates":
            from src.bbu_payments.models import BBUAffiliate
            rows = (await db_session.execute(select(BBUAffiliate).where(
                BBUAffiliate.org_id == 1))).scalars().all()
            for a in rows:
                if not (a.email or "").strip():
                    continue
                targets.append((a.email.strip().lower(), (a.name or "").split(" ")[0], {
                    "bbu_affiliate_portal_url": f"{base}/api/v1/bbu/affiliate/portal?token={getattr(a,'portal_token','')}",
                    "bbu_affiliate_referral_url": f"{base}/?ref={a.ref_code}",
                }))
        else:  # password_setup — reuse the reset URLs already pushed to GHL
            q = (select(User).join(UserOrganization, UserOrganization.user_id == User.id)
                 .where(UserOrganization.org_id == 1))
            users = (await db_session.execute(q)).scalars().all()
            for u in users:
                targets.append((u.email, u.first_name or "", {}))
        if limit:
            targets = targets[:limit]

        if dry_run:
            return {"dry_run": True, "template": tmpl.get("name"), "subject": subject,
                    "audience": audience, "recipients": len(targets),
                    "sample": [e for e, _, _ in targets[:5]]}

        sent, errors = 0, []
        for email, first, ctx in targets:
            try:
                contact = await ghl.find_contact(email)
                if not contact:
                    errors.append(f"{email}: no GHL contact")
                    continue
                merged = dict(ctx)
                # pull any field already stored on the GHL contact (e.g. reset URL)
                for cf in (contact.get("customFields") or []):
                    k = (cf.get("key") or "").replace("contact.", "")
                    if k:
                        merged.setdefault(k, cf.get("value") or cf.get("field_value") or "")
                merged.setdefault("first_name", first)
                await ghl.send_email(contact["id"], subject, _render(html, merged))
                sent += 1
            except Exception as e:
                errors.append(f"{email}: {type(e).__name__}: {e}")
        return {"dry_run": False, "template": tmpl.get("name"), "recipients": len(targets),
                "sent": sent, "errors": errors[:20], "error_count": len(errors)}
