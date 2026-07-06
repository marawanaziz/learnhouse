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
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.courses.courses import Course
from src.bbu_payments.models import BBUProduct, BBUOrder
from src.bbu_payments.branding import store_page, checkout_page, success_page

router = APIRouter()

stripe.api_key = os.environ.get("BBU_STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.environ.get("BBU_STRIPE_WEBHOOK_SECRET", "")
PUB_KEY = os.environ.get("BBU_STRIPE_PUBLISHABLE_KEY", "")


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


@router.get("/store", response_class=HTMLResponse)
async def store(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    rows = await _list_products(db_session)
    return HTMLResponse(store_page(rows, _base_url(request)))


@router.get("/buy/{product_id}", response_class=HTMLResponse)
async def buy(product_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    p = (await db_session.execute(select(BBUProduct).where(BBUProduct.id == product_id))).scalars().first()
    if not p:
        raise HTTPException(404, "Product not found")
    return HTMLResponse(checkout_page(p, PUB_KEY, _base_url(request)))


@router.get("/success", response_class=HTMLResponse)
async def success(request: Request, session_id: str = "", db_session: AsyncSession = Depends(get_db_session)):
    order = None
    if session_id:
        # Belt-and-suspenders fulfillment: don't rely solely on the async
        # webhook. Retrieve the session server-side and fulfill if it's paid.
        if stripe.api_key:
            try:
                sess = stripe.checkout.Session.retrieve(session_id)
                if sess.get("payment_status") == "paid":
                    await _fulfill(db_session, dict(sess))
            except Exception:
                pass
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
        # HSA/FSA cards + Klarna surface automatically where eligible.
        automatic_payment_methods={"enabled": True},
        success_url=f"{base}/api/v1/bbu/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base}/api/v1/bbu/buy/{p.id}",
        metadata={"bbu_product_id": str(p.id), "course_uuids": p.course_uuids},
    )

    order = BBUOrder(
        org_id=p.org_id, product_id=p.id, stripe_session_id=session.id,
        email=email, amount_cents=p.price_cents, currency=p.currency,
        status="pending", course_uuids=p.course_uuids,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db_session.add(order)
    await db_session.commit()
    return {"url": session.url, "session_id": session.id}


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
    if session_obj.get("customer_details", {}).get("email") and not order.email:
        order.email = session_obj["customer_details"]["email"]
    db_session.add(order)
    await db_session.commit()


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
    data = (event["data"]["object"] if isinstance(event, dict) else event.data.object)
    if etype == "checkout.session.completed":
        await _fulfill(db_session, dict(data))
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
    return JSONResponse({"received": True})
