"""The public affiliate referral entry point must land on the shop, not /login.

Regression coverage for the reported defect: a referral link redirected to the
site root, which is a signed-in dashboard that answers a signed-out visitor with
a 307 to /login. A visitor sent to buy a class never saw one.
"""

import pytest
from starlette.requests import Request

from src.bbu_payments import affiliates as aff
from src.bbu_payments import router as payments_router

BASE = "https://learn.birthandbabyuniversity.com"


class _Scalars:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class _Result:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return _Scalars(self.value)


class _Session:
    """Minimal stand-in for the async DB session used by the route."""

    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return _Result(self.results.pop(0) if self.results else None)

    def add(self, _obj):
        return None

    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


def _request(path="/api/v1/bbu/r/CODE", query=""):
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": query.encode(),
        "headers": [(b"host", b"learn.birthandbabyuniversity.com")],
        "scheme": "https",
        "client": ("127.0.0.1", 1234),
        "server": ("learn.birthandbabyuniversity.com", 443),
    }
    return Request(scope)


# --------------------------------------------------------------------------- #
# The link builder
# --------------------------------------------------------------------------- #

def test_bare_referral_link_lands_on_the_store_not_the_root():
    url = aff.referral_url(BASE, "mbfmama")

    assert url == f"{BASE}/api/v1/bbu/r/mbfmama"
    assert "/r/mbfmama?" not in url, "the plain link must not carry a next= to the root"


def test_referral_landing_default_is_the_public_shop():
    assert aff.DEFAULT_REFERRAL_LANDING == "/store"


@pytest.mark.parametrize("product_id", [5, 6, 12, 16])
def test_per_course_link_targets_that_product_checkout(product_id):
    url = aff.referral_url(BASE, "mbfmama", f"/api/v1/bbu/buy/{product_id}")

    assert url.startswith(f"{BASE}/api/v1/bbu/r/mbfmama?next=")
    assert url.endswith(f"%2Fapi%2Fv1%2Fbbu%2Fbuy%2F{product_id}")


def test_ref_code_is_url_quoted():
    assert aff.referral_url(BASE, "a b/c") == f"{BASE}/api/v1/bbu/r/a%20b%2Fc"


@pytest.mark.parametrize(
    "hostile",
    [
        "//evil.example.com",
        "https://evil.example.com/x",
        "http://evil.example.com",
        "/\\evil.example.com",
        "/api/v1/bbu/buy/6?x=\\evil",
        "",
        "   ",
        "relative/path",
    ],
)
def test_hostile_or_relative_destinations_fall_back_to_the_store(hostile):
    assert aff._safe_next_path(hostile) == "/store"


def test_legitimate_site_relative_destination_is_kept():
    assert aff._safe_next_path("/api/v1/bbu/buy/6") == "/api/v1/bbu/buy/6"


def test_plain_store_destination_is_not_double_encoded():
    # Asking for the store explicitly must produce the same link as asking for
    # nothing, so the two forms cannot drift apart.
    assert aff.referral_url(BASE, "mbfmama", "/store") == aff.referral_url(BASE, "mbfmama")
    assert aff.referral_url(BASE, "mbfmama", "") == aff.referral_url(BASE, "mbfmama")


# --------------------------------------------------------------------------- #
# The live route
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_referral_route_defaults_to_the_store(monkeypatch):
    from src.bbu_payments.models import BBUAffiliate

    monkeypatch.setattr(aff, "get_settings", _fake_settings)
    monkeypatch.setattr(aff, "log_click", _noop)
    db = _Session(BBUAffiliate(id=51, org_id=1, ref_code="mbfmama", status="onboarding"))

    resp = await payments_router.referral_redirect("mbfmama", _request(), db)

    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/store")
    assert resp.headers["location"] != f"{BASE}/", "must not land on the login wall"
    assert "bbu_ref=mbfmama" in resp.headers["set-cookie"]


@pytest.mark.asyncio
async def test_referral_route_honours_a_course_destination(monkeypatch):
    from src.bbu_payments.models import BBUAffiliate

    monkeypatch.setattr(aff, "get_settings", _fake_settings)
    monkeypatch.setattr(aff, "log_click", _noop)
    db = _Session(BBUAffiliate(id=51, org_id=1, ref_code="mbfmama", status="onboarding"))

    resp = await payments_router.referral_redirect(
        "mbfmama", _request(query="next=/api/v1/bbu/buy/6"), db
    )

    assert resp.headers["location"].endswith("/api/v1/bbu/buy/6")
    assert "bbu_ref=mbfmama" in resp.headers["set-cookie"]


@pytest.mark.asyncio
async def test_referral_route_refuses_an_offsite_destination(monkeypatch):
    from src.bbu_payments.models import BBUAffiliate

    monkeypatch.setattr(aff, "get_settings", _fake_settings)
    monkeypatch.setattr(aff, "log_click", _noop)
    db = _Session(BBUAffiliate(id=51, org_id=1, ref_code="mbfmama", status="onboarding"))

    resp = await payments_router.referral_redirect(
        "mbfmama", _request(query="next=//evil.example.com"), db
    )

    assert resp.headers["location"].endswith("/store"), "must never redirect off-site"


async def _fake_settings(_db, _org_id=1):
    from src.bbu_payments.models import BBUAffiliateSettings

    return BBUAffiliateSettings(org_id=1, attribution_window_days=60)


async def _noop(*_args, **_kwargs):
    return None
