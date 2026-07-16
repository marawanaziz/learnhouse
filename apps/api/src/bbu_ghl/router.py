"""BBU -> GHL sync admin endpoints (admin-key gated).

  GET  /bbu/ghl/health            config + connectivity check
  POST /bbu/ghl/sync/order/{id}   re-sync one paid order (idempotent)
  POST /bbu/ghl/backfill          bulk-sync paid orders. Guarded: requires
                                  confirm=true and honours a `limit`, because
                                  it writes into the client's live CRM.
"""
import os

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.bbu_ghl import sync as ghl_sync
from src.bbu_ghl.client import GHLClient, is_configured, LOCATION_ID
from src.bbu_payments.models import BBUProduct, BBUOrder

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
