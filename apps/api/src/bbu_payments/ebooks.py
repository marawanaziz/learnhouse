"""BBU e-books — sell digital PDFs through the storefront and deliver them
securely on purchase. Replaces the Thrivecart sale + Experiencify email chain.

  POST /bbu/ebook/upload        (admin-key)  store a PDF, create an ebook product
  GET  /bbu/ebook/download/{t}              stream the PDF for a paid order token

Files are stored under the content volume (EBOOK_DIR); they are never public —
downloads require a valid paid-order token, so the PDF can't be shared by URL.
"""
import os
import secrets

from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.bbu_payments.models import BBUProduct, BBUOrder

router = APIRouter()

ADMIN_KEY = os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")
# The API runs with CWD /app/api; the persistent content volume is mounted at
# /app/api/content. Keep e-books beside other uploaded content.
EBOOK_DIR = os.path.join("content", "ebooks")
os.makedirs(EBOOK_DIR, exist_ok=True)


def _check_admin(request: Request, body_key: str = ""):
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key") or body_key
    if not ADMIN_KEY or key != ADMIN_KEY:
        raise HTTPException(403, "Forbidden")


@router.post("/upload")
async def upload_ebook(
    request: Request,
    file_object: UploadFile,
    name: str = Form(...),
    price_cents: int = Form(...),
    description: str = Form(""),
    key: str = Form(""),
    db_session: AsyncSession = Depends(get_db_session),
):
    """Store a PDF and create (or update) an ebook product for it."""
    _check_admin(request, key)
    safe = "".join(c for c in (file_object.filename or "ebook.pdf") if c.isalnum() or c in "._- ")
    stored = f"{secrets.token_hex(8)}_{safe}"
    dest = os.path.join(EBOOK_DIR, stored)
    with open(dest, "wb") as f:
        while chunk := await file_object.read(1 << 20):
            f.write(chunk)

    existing = (await db_session.execute(
        select(BBUProduct).where(BBUProduct.name == name, BBUProduct.org_id == 1)
    )).scalars().first()
    if existing:
        p = existing
        p.kind = "ebook"; p.price_cents = price_cents; p.description = description or p.description
        p.asset_path = dest; p.asset_filename = safe; p.public = True
    else:
        p = BBUProduct(org_id=1, name=name, kind="ebook", price_cents=price_cents,
                       description=description, public=True, asset_path=dest, asset_filename=safe)
        db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return {"product_id": p.id, "name": p.name, "price_cents": p.price_cents,
            "asset_filename": p.asset_filename}


@router.get("/download/{token}")
async def download_ebook(token: str, db_session: AsyncSession = Depends(get_db_session)):
    """Stream the PDF for a paid order identified by its download token."""
    order = (await db_session.execute(
        select(BBUOrder).where(BBUOrder.download_token == token)
    )).scalars().first()
    if not order or order.status != "paid":
        raise HTTPException(404, "Not found or payment not completed")
    product = (await db_session.execute(
        select(BBUProduct).where(BBUProduct.id == order.product_id)
    )).scalars().first()
    if not product or product.kind != "ebook" or not product.asset_path:
        raise HTTPException(404, "E-book not available")
    if not os.path.exists(product.asset_path):
        raise HTTPException(404, "File missing")
    return FileResponse(product.asset_path, media_type="application/pdf",
                        filename=product.asset_filename or "ebook.pdf")


@router.post("/product/{product_id}")
async def update_ebook(
    product_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    """Admin: edit an ebook product (price, name, description, visibility).
    Body is JSON; any of price_cents / name / description / public may be set."""
    _check_admin(request, request.query_params.get("key", ""))
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    p = (await db_session.execute(
        select(BBUProduct).where(BBUProduct.id == product_id)
    )).scalars().first()
    if not p:
        raise HTTPException(404, "Product not found")
    if "price_cents" in body:
        p.price_cents = int(body["price_cents"])
    if "name" in body:
        p.name = str(body["name"])
    if "description" in body:
        p.description = str(body["description"])
    if "image_url" in body:
        p.image_url = str(body["image_url"])
    if "public" in body:
        p.public = bool(body["public"])
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return {"product_id": p.id, "name": p.name, "price_cents": p.price_cents,
            "public": p.public}


@router.delete("/product/{product_id}")
async def delete_ebook(
    product_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    """Admin: delete an ebook product and remove its stored file."""
    _check_admin(request, request.query_params.get("key", ""))
    p = (await db_session.execute(
        select(BBUProduct).where(BBUProduct.id == product_id)
    )).scalars().first()
    if not p:
        raise HTTPException(404, "Product not found")
    path = p.asset_path
    await db_session.delete(p)
    await db_session.commit()
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
    return {"deleted": product_id}


def ensure_download_token(order: BBUOrder) -> str:
    """Assign a delivery token to a paid ebook order (idempotent)."""
    if not order.download_token:
        order.download_token = secrets.token_urlsafe(24)
    return order.download_token
