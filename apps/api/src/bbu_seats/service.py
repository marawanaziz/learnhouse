"""BBU reseller seats — generation + owner-portal helpers. Clean-room.

Purchase auto-generates a batch of single-use codes tied to the buyer (the agency
owner) via a shared owner_token; the owner uses that token for a self-serve
portal to view/copy/share the codes. Recipients redeem on their own.
"""
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.bbu_seats.models import BBUSeatCode

_ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous 0/O/1/I


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def gen_code(prefix: str = "BBU") -> str:
    body = "".join(secrets.choice(_ALPHA) for _ in range(10))
    return f"{prefix}-{body[:5]}-{body[5:]}"


async def generate_batch(db: AsyncSession, org_id: int, count: int,
                         course_uuids: list, owner_email: str = "",
                         product_id=None, batch_label: str = "",
                         owner_token: str = "") -> dict:
    """Create `count` unused seat codes tied to course_uuids + an owner_token
    (shared across the batch, keys the owner portal). Returns the batch summary."""
    owner_token = owner_token or f"seatown_{uuid4().hex}"
    label = batch_label or f"batch-{_now()[:10]}"
    cu = ",".join([u for u in course_uuids if u])
    codes = []
    for _ in range(max(0, int(count))):
        code = gen_code()
        while (await db.execute(select(BBUSeatCode).where(BBUSeatCode.code == code))).scalars().first():
            code = gen_code()
        db.add(BBUSeatCode(org_id=org_id, code=code, batch_label=label,
                           course_uuids=cu, product_id=product_id,
                           owner_email=(owner_email or "").strip().lower(),
                           owner_token=owner_token, status="unused", created_at=_now()))
        codes.append(code)
    await db.commit()
    return {"owner_token": owner_token, "batch_label": label, "codes": codes, "count": len(codes)}


async def owner_seats(db: AsyncSession, owner_token: str) -> list:
    if not owner_token:
        return []
    return (await db.execute(select(BBUSeatCode).where(
        BBUSeatCode.owner_token == owner_token).order_by(BBUSeatCode.id))).scalars().all()
