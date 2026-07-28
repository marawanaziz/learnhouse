"""Regression tests for BBU audience assignment and owned-course filtering."""
from datetime import datetime

import pytest
from sqlmodel import select

from src.bbu_migration.registration import assign_registration_audience
from src.bbu_payments.audiences import exclude_owned_products
from src.bbu_payments import coupons as coupon_svc
from src.bbu_payments.models import BBUCoupon, BBUProduct
from src.bbu_payments.offers_router import _automatic_discount_percent
from src.db.usergroup_resources import UserGroupResource
from src.db.usergroup_user import UserGroupUser
from src.db.usergroups import UserGroup


async def _group(db, org_id: int, name: str, suffix: str) -> UserGroup:
    group = UserGroup(
        org_id=org_id,
        name=name,
        description=name,
        usergroup_uuid=f"usergroup_{suffix}",
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


@pytest.mark.asyncio
async def test_registration_assigns_professional_group(db, org, regular_user):
    group = await _group(db, org.id, "BBU Professionals", "professional")

    assigned = await assign_registration_audience(
        db,
        regular_user.id,
        org.id,
        {"bbu_audience": "professional"},
    )

    membership = (
        await db.execute(
            select(UserGroupUser).where(
                UserGroupUser.usergroup_id == group.id,
                UserGroupUser.user_id == regular_user.id,
            )
        )
    ).scalars().first()
    assert assigned == "professional"
    assert membership is not None


@pytest.mark.asyncio
async def test_registration_defaults_unknown_answer_to_family(
    db, org, regular_user
):
    group = await _group(db, org.id, "Family", "family")

    assigned = await assign_registration_audience(
        db,
        regular_user.id,
        org.id,
        {"bbu_audience": "unexpected"},
    )

    membership = (
        await db.execute(
            select(UserGroupUser).where(
                UserGroupUser.usergroup_id == group.id,
                UserGroupUser.user_id == regular_user.id,
            )
        )
    ).scalars().first()
    assert assigned == "family"
    assert membership is not None


@pytest.mark.asyncio
async def test_store_excludes_fully_unlocked_course_offer(
    db, org, regular_user
):
    group = await _group(db, org.id, "CFD Birth Families", "cfd_birth")
    now = str(datetime.now())
    db.add(
        UserGroupUser(
            usergroup_id=group.id,
            user_id=regular_user.id,
            org_id=org.id,
            creation_date=now,
            update_date=now,
        )
    )
    db.add(
        UserGroupResource(
            usergroup_id=group.id,
            resource_uuid="course_unlocked",
            org_id=org.id,
            creation_date=now,
            update_date=now,
        )
    )
    await db.commit()

    unlocked = BBUProduct(
        id=1,
        org_id=org.id,
        name="Unlocked",
        course_uuids="course_unlocked",
    )
    available = BBUProduct(
        id=2,
        org_id=org.id,
        name="Available",
        course_uuids="course_other",
    )
    ebook = BBUProduct(
        id=3,
        org_id=org.id,
        name="Guide",
        kind="ebook",
        course_uuids="",
    )

    result = await exclude_owned_products(
        db,
        [unlocked, available, ebook],
        regular_user.id,
        org.id,
    )
    assert [product.name for product in result] == ["Available", "Guide"]


@pytest.mark.asyncio
async def test_cfd_postpartum_member_receives_exact_product_discount(
    db, org, regular_user
):
    group = await _group(
        db,
        org.id,
        "CFD Postpartum Families",
        "cfd_postpartum",
    )
    now = str(datetime.now())
    db.add(
        UserGroupUser(
            usergroup_id=group.id,
            user_id=regular_user.id,
            org_id=org.id,
            creation_date=now,
            update_date=now,
        )
    )
    db.add(
        BBUCoupon(
            org_id=org.id,
            code="CFDPOSTPARTUM50",
            kind="percent",
            percent_off=50,
            applies_to="9",
            active=True,
            created_at=now,
        )
    )
    await db.commit()
    included = BBUProduct(
        id=9,
        org_id=org.id,
        name="Included Postpartum Class",
        price_cents=9700,
    )
    excluded = BBUProduct(
        id=10,
        org_id=org.id,
        name="Other Class",
        price_cents=9700,
    )

    assert (
        await _automatic_discount_percent(
            db, regular_user.id, included
        )
        == 50
    )
    assert (
        await _automatic_discount_percent(
            db, regular_user.id, excluded
        )
        == 0
    )


@pytest.mark.asyncio
async def test_server_applied_coupon_redemption_is_recorded(db, org):
    coupon = BBUCoupon(
        org_id=org.id,
        code="CFDPOSTPARTUM50",
        kind="percent",
        percent_off=50,
        applies_to="9",
        active=True,
        stripe_coupon_id="coupon_private_123",
        created_at=str(datetime.now()),
    )
    db.add(coupon)
    await db.commit()

    code, discount = await coupon_svc.record_redemption_from_session(
        db,
        org.id,
        {
            "discounts": [{"coupon": "coupon_private_123"}],
            "total_details": {"amount_discount": 4850},
        },
    )
    await db.commit()
    await db.refresh(coupon)

    assert code == "CFDPOSTPARTUM50"
    assert discount == 4850
    assert coupon.times_redeemed == 1
