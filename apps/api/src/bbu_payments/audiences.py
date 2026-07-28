"""Which catalogue a given person should see.

Anna's model: a perinatal professional shouldn't wade through newborn classes to
find their doula training, a family shouldn't be shown professional certifications,
and Project Bold cohorts should only see their own labelled versions. This is a
*presentation* filter, layered over — never replacing — the access gating that
decides what someone may actually open.

Two rules keep it safe:
  * a product with no audience tag is visible to everyone, so tagging is opt-in
    and nothing disappears from the store by accident;
  * filtering never grants access. Someone who reaches a hidden product by direct
    link still hits the usual purchase/usergroup gate.
"""
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.bbu_payments.models import BBUAudience, BBUProduct

RETAIL_AUDIENCES = {"family", "professional", "spanish_family"}


def tags_of(product: BBUProduct) -> list:
    return [t.strip().lower() for t in (product.audiences or "").split(",") if t.strip()]


async def all_audiences(db: AsyncSession, org_id: int = 1) -> list:
    return (await db.execute(select(BBUAudience).where(
        BBUAudience.org_id == org_id, BBUAudience.active == True  # noqa: E712
    ).order_by(BBUAudience.sort_order, BBUAudience.name))).scalars().all()


async def public_default_slugs(db: AsyncSession, org_id: int = 1) -> list:
    return [a.slug for a in await all_audiences(db, org_id) if a.is_public_default]


async def slugs_for_user(db: AsyncSession, user_id: int, org_id: int = 1) -> list:
    """Audiences this person belongs to, via their usergroup membership.

    Signed-out or ungrouped visitors fall back to the public default, so the
    storefront still shows the retail catalogue rather than nothing at all.
    """
    auds = await all_audiences(db, org_id)
    if not user_id:
        return [a.slug for a in auds if a.is_public_default]

    from src.db.usergroup_user import UserGroupUser
    mine = {r.usergroup_id for r in (await db.execute(select(UserGroupUser).where(
        UserGroupUser.user_id == user_id))).scalars().all()}
    slugs = [a.slug for a in auds if a.usergroup_id and a.usergroup_id in mine]
    return slugs or [a.slug for a in auds if a.is_public_default]


async def preferred_store_slug(
    db: AsyncSession,
    user_id: int,
    org_id: int = 1,
) -> str:
    """Map cohort audiences to the retail tab they should see by default."""
    slugs = set(await slugs_for_user(db, user_id, org_id))
    if "professional" in slugs or "bold_professional" in slugs:
        return "professional"
    if "spanish_family" in slugs or "bold_spanish_family" in slugs:
        return "spanish_family"
    return "family"


async def exclude_owned_products(
    db: AsyncSession,
    products: list,
    user_id: int,
    org_id: int = 1,
) -> list:
    """Hide course offers whose complete course set is already unlocked."""
    if not user_id:
        return products

    from src.db.usergroup_resources import UserGroupResource
    from src.db.usergroup_user import UserGroupUser

    group_ids = (
        await db.execute(
            select(UserGroupUser.usergroup_id).where(
                UserGroupUser.user_id == user_id,
                UserGroupUser.org_id == org_id,
            )
        )
    ).scalars().all()
    if not group_ids:
        return products
    resource_uuids = set(
        (
            await db.execute(
                select(UserGroupResource.resource_uuid).where(
                    UserGroupResource.usergroup_id.in_(group_ids)
                )
            )
        ).scalars().all()
    )

    visible = []
    for product in products:
        course_uuids = {
            item.strip()
            for item in (product.course_uuids or "").split(",")
            if item.strip()
        }
        if course_uuids and course_uuids.issubset(resource_uuids):
            continue
        visible.append(product)
    return visible


def visible_to(product: BBUProduct, slugs: list) -> bool:
    tags = tags_of(product)
    if not tags:
        return True          # untagged stays public
    return any(t in slugs for t in tags)


async def filter_products(db: AsyncSession, products: list, user_id: int = 0,
                          org_id: int = 1, audience: str = "") -> list:
    """Narrow a product list to what this viewer should see.

    `audience` lets the viewer deliberately look at another segment — Anna's
    "are you interested in offering classes for your clients? view them here".
    It only ever changes what is *displayed*.
    """
    if audience:
        slugs = [audience.strip().lower()]
    else:
        slugs = await slugs_for_user(db, user_id, org_id)
    return [p for p in products if visible_to(p, slugs)]
