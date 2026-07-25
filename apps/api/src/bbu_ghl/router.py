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
