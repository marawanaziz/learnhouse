"""Regression coverage for signed-in affiliate payout onboarding."""

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from src.bbu_payments import affiliate_router
from src.bbu_payments.affiliate_branding import member_join_page, portal_page
from src.bbu_payments.models import BBUAffiliate


def _request(host: str = "learn.birthandbabyuniversity.com") -> Request:
    return Request({
        "type": "http",
        "scheme": "https",
        "path": "/api/v1/bbu/affiliate/me",
        "headers": [(b"host", host.encode())],
    })


class _DB:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1


def test_connect_state_covers_every_member_facing_state():
    assert affiliate_router._connect_state(None)["status"] == "not_started"
    assert affiliate_router._connect_state({
        "payouts_enabled": False,
        "details_submitted": False,
        "requirements": {"currently_due": ["individual.id_number"]},
    }) == {
        "status": "incomplete",
        "payouts_enabled": False,
        "details_submitted": False,
        "currently_due_count": 1,
        "disabled_reason": "",
    }
    assert affiliate_router._connect_state({
        "payouts_enabled": False,
        "details_submitted": True,
        "requirements": {
            "currently_due": [],
            "disabled_reason": "requirements.pending_verification",
        },
    })["status"] == "restricted"
    assert affiliate_router._connect_state({
        "payouts_enabled": False,
        "details_submitted": True,
        "requirements": {"currently_due": []},
    })["status"] == "pending_review"
    assert affiliate_router._connect_state({
        "payouts_enabled": True,
        "details_submitted": True,
        "requirements": {"currently_due": []},
    })["status"] == "connected"


def test_apply_connect_state_never_reactivates_suspended_affiliate():
    affiliate = BBUAffiliate(
        id=4,
        org_id=1,
        email="suspended@example.com",
        ref_code="suspended",
        status="suspended",
    )

    affiliate_router._apply_connect_state(
        affiliate,
        {"payouts_enabled": True, "details_submitted": True},
    )

    assert affiliate.payouts_enabled is True
    assert affiliate.status == "suspended"


@pytest.mark.asyncio
async def test_member_onboarding_reuses_existing_stripe_account(monkeypatch):
    affiliate = BBUAffiliate(
        id=7,
        org_id=1,
        email="affiliate@example.com",
        ref_code="existing-code",
        status="onboarding",
        stripe_connect_account_id="acct_existing",
        portal_token="private-token",
    )
    db = _DB()
    captured = {}

    def fail_account_create(**_kwargs):
        raise AssertionError("existing Stripe account must be reused")

    def create_account_link(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(url="https://connect.stripe.test/onboarding")

    monkeypatch.setattr(affiliate_router.stripe, "api_key", "sk_test")
    monkeypatch.setattr(
        affiliate_router.stripe.Account, "create", fail_account_create
    )
    monkeypatch.setattr(
        affiliate_router.stripe.AccountLink, "create", create_account_link
    )

    url = await affiliate_router._create_onboarding_link(
        _request(),
        affiliate,
        db,
        member_flow=True,
        orgslug="birth-and-baby-university",
    )

    assert url == "https://connect.stripe.test/onboarding"
    assert captured["account"] == "acct_existing"
    assert captured["type"] == "account_onboarding"
    assert captured["collection_options"] == {"fields": "eventually_due"}
    assert "/affiliate/me/onboarding?orgslug=birth-and-baby-university" in (
        captured["refresh_url"]
    )
    assert "/affiliate/me/return?orgslug=birth-and-baby-university" in (
        captured["return_url"]
    )
    assert db.commits == 0


@pytest.mark.asyncio
async def test_member_onboarding_persists_new_account_before_link(monkeypatch):
    affiliate = BBUAffiliate(
        id=8,
        org_id=1,
        email="new@example.com",
        ref_code="new-code",
        status="pending",
        portal_token="private-token",
    )
    db = _DB()
    captured = {}

    def create_account(**kwargs):
        captured["account"] = kwargs
        return SimpleNamespace(id="acct_new")

    def create_account_link(**kwargs):
        assert affiliate.stripe_connect_account_id == "acct_new"
        assert db.commits == 1
        captured["link"] = kwargs
        return SimpleNamespace(url="https://connect.stripe.test/new")

    monkeypatch.setattr(affiliate_router.stripe, "api_key", "sk_test")
    monkeypatch.setattr(affiliate_router.stripe.Account, "create", create_account)
    monkeypatch.setattr(
        affiliate_router.stripe.AccountLink, "create", create_account_link
    )

    await affiliate_router._create_onboarding_link(
        _request(),
        affiliate,
        db,
        member_flow=True,
        orgslug="birth-and-baby-university",
    )

    assert affiliate.stripe_connect_account_id == "acct_new"
    assert affiliate.status == "onboarding"
    assert captured["account"]["idempotency_key"] == "bbu_affiliate_connect_8"
    assert captured["link"]["account"] == "acct_new"


def test_member_join_page_uses_signed_identity_without_email_form():
    html = member_join_page(
        "Jane Doe",
        "jane@example.com",
        "https://learn.birthandbabyuniversity.com",
        "birth-and-baby-university",
    )

    assert "Jane Doe" in html
    assert "jane@example.com" in html
    assert "Become an affiliate &amp; set up payouts" in html
    assert "me/onboarding?orgslug=birth-and-baby-university" in html
    assert "id='email'" not in html


def test_member_redirect_rejects_untrusted_org_path(monkeypatch):
    monkeypatch.setattr(
        affiliate_router,
        "_base_url",
        lambda _request: "https://learn.birthandbabyuniversity.com",
    )

    url = affiliate_router._member_account_url(
        _request(),
        "example.com/../../admin?next=https://evil.example",
        "connected",
    )

    assert url == (
        "https://learn.birthandbabyuniversity.com/"
        "account/affiliate?stripe=connected"
    )


@pytest.mark.asyncio
async def test_connect_webhook_refuses_unsigned_fallback(monkeypatch):
    monkeypatch.setattr(affiliate_router, "CONNECT_WEBHOOK_SECRET", "")

    with pytest.raises(affiliate_router.HTTPException) as error:
        await affiliate_router.connect_webhook(_request(), _DB())

    assert error.value.status_code == 503


def test_portal_shows_incomplete_and_connected_payout_states():
    affiliate = BBUAffiliate(
        id=9,
        org_id=1,
        name="Jane Doe",
        email="jane@example.com",
        ref_code="jane-code",
        status="onboarding",
        portal_token="private-token",
    )
    earnings = {
        "sales": 1,
        "pending": 0,
        "available": 8750,
        "paid": 0,
        "details": [],
    }
    incomplete = portal_page(
        affiliate,
        earnings,
        [],
        "https://learn.birthandbabyuniversity.com",
        connect_state={"status": "incomplete", "currently_due_count": 2},
        onboarding_url="https://learn.example/me/onboarding",
    )
    connected = portal_page(
        affiliate,
        earnings,
        [],
        "https://learn.birthandbabyuniversity.com",
        connect_state={"status": "connected"},
        dashboard_url="https://learn.example/me/dashboard",
    )

    assert "Finish your payout setup" in incomplete
    assert "commissions will continue accumulating" in incomplete
    assert "Stripe currently needs 2 more items" in incomplete
    assert "$87.50" in incomplete
    assert "Payout account connected" in connected
    assert "Manage payout account" in connected


def test_portal_escapes_imported_affiliate_history():
    affiliate = BBUAffiliate(
        id=10,
        org_id=1,
        name="<script>alert(1)</script>",
        email="safe@example.com",
        ref_code="safe-code",
        status="active",
        portal_token="private-token",
    )
    earnings = {
        "sales": 1,
        "pending": 0,
        "available": 0,
        "paid": 0,
        "details": [{
            "date": "2026-07-29",
            "customer": "<img src=x onerror=alert(1)>",
            "product": "Newborn Care",
            "sale_amount_cents": 10000,
            "commission_amount_cents": 5000,
            "status": "available",
        }],
    }

    html = portal_page(
        affiliate,
        earnings,
        [],
        "https://learn.birthandbabyuniversity.com",
        connect_state={"status": "not_started"},
        onboarding_url="https://learn.example/me/onboarding",
    )

    assert "<script>alert(1)</script>" not in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
