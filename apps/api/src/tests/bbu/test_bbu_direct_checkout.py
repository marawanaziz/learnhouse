"""Direct checkout links skip the BBU form without skipping fulfillment."""

from types import SimpleNamespace

import pytest
from sqlmodel import select
from starlette.requests import Request

from src.bbu_payments import router as payments_router
from src.bbu_payments.models import BBUOrder, BBUProduct


def _request(
    path: str = "/api/v1/bbu/checkout/1",
    *,
    query: str = "",
    referer: str = "",
) -> Request:
    headers = [(b"host", b"learn.birthandbabyuniversity.com")]
    if referer:
        headers.append((b"referer", referer.encode()))
    return Request({
        "type": "http",
        "scheme": "https",
        "method": "GET",
        "path": path,
        "query_string": query.encode(),
        "headers": headers,
    })


@pytest.mark.asyncio
async def test_session_without_prefilled_email_lets_stripe_collect_it(
    db, org, monkeypatch
):
    product = BBUProduct(
        id=1,
        org_id=org.id,
        name="Certified Birth Doula Training",
        course_uuids="course_birth",
        price_cents=55000,
        currency="usd",
        stripe_product_id="prod_live_birth",
    )
    db.add(product)
    await db.commit()

    stripe_session = SimpleNamespace(
        id="cs_live_direct",
        url="https://checkout.stripe.com/c/pay/cs_live_direct",
    )
    create_calls = []

    def fake_create(**kwargs):
        create_calls.append(kwargs)
        return stripe_session

    monkeypatch.setattr(payments_router.stripe, "api_key", "sk_live_test")
    monkeypatch.setattr(
        payments_router.stripe.checkout.Session,
        "create",
        fake_create,
    )

    result = await payments_router._create_checkout_session(
        _request(),
        db,
        product_id=product.id,
        cancel_url=(
            "https://birthandbabyuniversity.com/"
            "certified-birth-doula-training/"
        ),
    )

    assert result["url"] == stripe_session.url
    assert create_calls[0]["customer_email"] is None
    assert create_calls[0]["metadata"]["bbu_product_id"] == "1"
    assert create_calls[0]["cancel_url"].endswith(
        "/certified-birth-doula-training/"
    )

    order = (
        await db.execute(
            select(BBUOrder).where(
                BBUOrder.stripe_session_id == stripe_session.id
            )
        )
    ).scalars().one()
    assert order.email == ""
    assert order.status == "pending"
    assert order.course_uuids == "course_birth"


@pytest.mark.asyncio
async def test_direct_checkout_redirects_to_stripe_and_preserves_tracking(
    db, monkeypatch
):
    captured = {}

    async def fake_session(request, db_session, **kwargs):
        captured.update(kwargs)
        return {
            "url": "https://checkout.stripe.com/c/pay/cs_live_direct",
            "session_id": "cs_live_direct",
        }

    monkeypatch.setattr(
        payments_router,
        "_create_checkout_session",
        fake_session,
    )
    request = _request(
        query=(
            "coupon=WEBINAR40&ref=CFD"
            "&return_url=https%3A%2F%2Fbirthandbabyuniversity.com"
            "%2Fcertified-birth-doula-training%2F"
        )
    )

    response = await payments_router.direct_checkout("1", request, db)

    assert response.status_code == 303
    assert response.headers["location"].startswith(
        "https://checkout.stripe.com/"
    )
    assert captured["coupon_code"] == "WEBINAR40"
    assert captured["ref"] == "CFD"
    assert captured["cancel_url"] == (
        "https://birthandbabyuniversity.com/"
        "certified-birth-doula-training/"
    )


@pytest.mark.asyncio
async def test_direct_checkout_sends_full_cohort_to_waitlist(
    db, monkeypatch
):
    async def fake_session(request, db_session, **kwargs):
        return {"waitlist": True}

    monkeypatch.setenv(
        "LEARNHOUSE_DOMAIN",
        "learn.birthandbabyuniversity.com",
    )
    monkeypatch.setattr(
        payments_router,
        "_create_checkout_session",
        fake_session,
    )

    response = await payments_router.direct_checkout(
        "26",
        _request(
            path="/api/v1/bbu/checkout/26",
            query="coupon=WEBINAR-AGENCY&ref=CFD",
        ),
        db,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "https://learn.birthandbabyuniversity.com/api/v1/bbu/buy/26"
        "?coupon=WEBINAR-AGENCY&ref=CFD"
    )


def test_direct_checkout_rejects_untrusted_cancel_destination():
    request = _request(
        query="return_url=https%3A%2F%2Fattacker.example%2Ffake-checkout"
    )

    assert payments_router._direct_checkout_cancel_url(request) == (
        "https://birthandbabyuniversity.com/"
    )


@pytest.mark.asyncio
async def test_wordpress_checkout_slug_resolves_to_product(db, org):
    product = BBUProduct(
        id=1,
        org_id=org.id,
        name="Certified Birth Doula Training",
        course_uuids="course_birth",
        price_cents=55000,
    )
    db.add(product)
    await db.commit()

    product_id = await payments_router._resolve_checkout_product_id(
        db,
        "certified-birth-doula-training",
    )

    assert product_id == 1
