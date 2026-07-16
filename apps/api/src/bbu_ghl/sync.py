"""Push BBU platform state into GoHighLevel as MODULE records + FIELDS.

Design rule (explicit client instruction): do NOT model state as tags. Every
course a contact touches becomes a `custom_objects.course_enrollment` record
(status / dates / progress / amount / certificate as real fields), associated to
the contact. Contact-level `bbu__*` fields carry rollups so GHL workflows can
trigger and segment without a tag soup.

Everything here is fail-soft: GHL being down must never block a purchase.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.bbu_ghl.client import GHLClient, is_configured
from src.bbu_ghl.models import BBUGHLSync
from src.bbu_payments.models import BBUProduct, BBUOrder
from src.db.courses.courses import Course
from src.db.users import User

STATUS_LABELS = {
    "prospect": "Prospect", "active": "Active Student",
    "completed": "Completed", "certified": "Certified", "lapsed": "Lapsed",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


async def _mapping(db: AsyncSession, org_id: int, email: str,
                   course_uuid: str) -> Optional[BBUGHLSync]:
    return (await db.execute(
        select(BBUGHLSync).where(
            BBUGHLSync.org_id == org_id,
            BBUGHLSync.email == email,
            BBUGHLSync.course_uuid == course_uuid,
        )
    )).scalars().first()


async def _save_mapping(db: AsyncSession, org_id: int, email: str,
                        course_uuid: str, contact_id: str, record_id: str,
                        status: str):
    m = await _mapping(db, org_id, email, course_uuid)
    if not m:
        m = BBUGHLSync(org_id=org_id, email=email, course_uuid=course_uuid)
    m.ghl_contact_id = contact_id or m.ghl_contact_id
    m.ghl_record_id = record_id or m.ghl_record_id
    m.last_status = status or m.last_status
    m.updated_at = _now()
    db.add(m)
    await db.commit()


async def _rollups(db: AsyncSession, org_id: int, email: str) -> dict:
    """Compute contact-level rollups from our own DB (source of truth)."""
    orders = (await db.execute(
        select(BBUOrder).where(
            BBUOrder.org_id == org_id, BBUOrder.email == email,
            BBUOrder.status == "paid",
        )
    )).scalars().all()
    ltv = sum((o.amount_cents or 0) for o in orders) / 100
    course_uuids: set[str] = set()
    for o in orders:
        course_uuids.update(u for u in (o.course_uuids or "").split(",") if u)
    last = max(orders, key=lambda o: o.paid_at or o.created_at or "", default=None)
    last_course_name = ""
    if last and last.course_uuids:
        first_uuid = [u for u in last.course_uuids.split(",") if u]
        if first_uuid:
            c = (await db.execute(
                select(Course).where(Course.course_uuid == first_uuid[0])
            )).scalars().first()
            last_course_name = c.name if c else ""
    return {
        "bbu__courses_enrolled": len(course_uuids),
        "bbu__lifetime_value": round(ltv, 2),
        "bbu__last_course": last_course_name,
        "bbu__last_enrolled_at": (last.paid_at or last.created_at or "")[:10] if last else None,
        "bbu__student_status": STATUS_LABELS["active"] if course_uuids else STATUS_LABELS["prospect"],
    }


async def sync_order(db: AsyncSession, order: BBUOrder,
                     product: BBUProduct) -> dict:
    """Sync a paid order: upsert the contact (+rollups) and write one
    course_enrollment record per course the product grants."""
    if not is_configured():
        return {"skipped": "GHL not configured"}
    if not order.email:
        return {"skipped": "order has no email"}

    email = order.email
    user = (await db.execute(select(User).where(User.email == email))).scalars().first()
    fields = await _rollups(db, order.org_id, email)
    if user:
        fields["bbu__platform_user_id"] = str(user.id)

    made, updated = 0, 0
    async with GHLClient() as ghl:
        contact_id = await ghl.upsert_contact(
            email,
            first_name=(user.first_name if user else "") or "",
            last_name=(user.last_name if user else "") or "",
            fields=fields,
        )
        if not contact_id:
            return {"error": "no contact id"}
        await _save_mapping(db, order.org_id, email, "", contact_id, "", "")

        uuids = [u for u in (product.course_uuids or "").split(",") if u]
        if not uuids:
            # e-books and other non-course products: contact rollups only.
            return {"contact_id": contact_id, "records": 0, "kind": product.kind}

        assoc = await ghl.association_id()
        for cu in uuids:
            course = (await db.execute(
                select(Course).where(Course.course_uuid == cu)
            )).scalars().first()
            props = {
                "course_enrollment_label": course.name if course else cu,
                "course_uuid": cu,
                "status": "enrolled",
                "enrolled_date": (order.paid_at or order.created_at or _now())[:10],
                "progress_pct": 0,
                "amount_paid": round((order.amount_cents or 0) / 100, 2),
                "order_id": str(order.id),
                "source": "affiliate" if order.affiliate_ref else "store",
                "certificate_status": "none",
            }
            m = await _mapping(db, order.org_id, email, cu)
            if m and m.ghl_record_id:
                await ghl.update_enrollment(m.ghl_record_id, props)
                updated += 1
                rec_id = m.ghl_record_id
            else:
                rec_id = await ghl.create_enrollment(props)
                made += 1
                if rec_id and assoc:
                    await ghl.relate(assoc, contact_id, rec_id)
            await _save_mapping(db, order.org_id, email, cu, contact_id,
                                rec_id or "", "enrolled")

    return {"contact_id": contact_id, "created": made, "updated": updated}


async def sync_affiliate(db: AsyncSession, affiliate) -> dict:
    """Mirror affiliate state onto the contact as fields (not tags)."""
    if not is_configured():
        return {"skipped": "GHL not configured"}
    if not getattr(affiliate, "email", ""):
        return {"skipped": "affiliate has no email"}
    status_map = {
        "pending": "Pending", "onboarding": "Onboarding",
        "active": "Active", "suspended": "Suspended",
    }
    fields = {
        "bbu__affiliate_code": affiliate.ref_code or "",
        "bbu__affiliate_status": status_map.get(affiliate.status, "Pending"),
    }
    async with GHLClient() as ghl:
        contact_id = await ghl.upsert_contact(
            affiliate.email,
            first_name=(affiliate.name or "").split(" ")[0],
            last_name=" ".join((affiliate.name or "").split(" ")[1:]),
            fields=fields,
        )
    return {"contact_id": contact_id, "ref_code": affiliate.ref_code}
