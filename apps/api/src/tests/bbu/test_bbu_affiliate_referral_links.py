"""The public affiliate referral entry point must land on the shop, not /login.

Regression coverage for the reported defect: a referral link redirected to the
site root, which is a signed-in dashboard that answers a signed-out visitor with
a 307 to /login. A visitor sent to buy a class never saw one.
"""

import re

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
# Control characters. A TAB survives query decoding and is not removed by
# str.strip() for a value like "/\tevil.com", and clients that drop tabs turn
# that into a protocol-relative escape; CR/LF can split the Location header.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "raw",
    [
        "/\tevil.com",           # the reported gap: a literal TAB
        "/\t\t/evil.com",
        "/\r\nX-Injected: 1",
        "/a\x00b",
        "/\x1f/evil.com",
        "/\x7f/evil.com",
        "/api/v1/bbu/buy/6\tnope",
        "/store\n/evil.com",
    ],
)
def test_control_characters_are_rejected(raw):
    assert aff._safe_next_path(raw) == "/store"


def test_control_char_detector_covers_c0_and_del():
    assert aff._has_control_chars("/a\tb") is True
    assert aff._has_control_chars("/a\nb") is True
    assert aff._has_control_chars("/a\x00b") is True
    assert aff._has_control_chars("/a\x7fb") is True
    assert aff._has_control_chars("/api/v1/bbu/buy/6") is False
    assert aff._has_control_chars("/store?x=1&y=2") is False


def test_referral_url_with_a_control_char_falls_back_to_the_store():
    assert aff.referral_url(BASE, "mbfmama", "/\tevil.com") == f"{BASE}/api/v1/bbu/r/mbfmama"


def test_a_leading_tab_is_stripped_and_the_remainder_is_still_checked():
    # A leading tab IS removed by strip(), which must not be mistaken for safety:
    # what survives is re-validated.
    assert aff._safe_next_path(" \t/api/v1/bbu/buy/6") == "/api/v1/bbu/buy/6"
    assert aff._safe_next_path(" \t//evil.com") == "/store"


# --------------------------------------------------------------------------- #
# The dashboard must actually RENDER the links, not merely build them.
# Previously `_course_row` read `c['referral_link']` while both portal callers
# pass the catalogue rows from `_referral_courses`, which carry only `next_path`
# and no link, so 11 rows rendered 11 blank copy fields.
# --------------------------------------------------------------------------- #

def _catalogue():
    """The exact 11 public products live /api/v1/bbu/products returns.

    Ids match the observed catalogue (29, 5, 6, 9, 10, 11, 12, 13, 14, 15, 16).
    """
    return [
        {"id": i, "name": n, "kind": kind, "price_cents": price,
         "next_path": f"/api/v1/bbu/buy/{i}"}
        for i, n, kind, price in [
            (29, "Preparing for Your Hospital Birth in Chicago", "course", 9700),
            (5, "Intro to Childbirth", "course", 9700),
            (6, "Breastfeeding", "course", 4700),
            (9, "Birth Prep eBook & Guide", "ebook", 1700),
            (10, "Newborn Care Basics eBook & Guide", "ebook", 1700),
            (11, "Preparing for Your Hospital Birth", "course", 9700),
            (12, "Comfort Measures", "course", 6700),
            (13, "Preparing for Your VBAC", "course", 6700),
            (14, "Bringing Home Baby", "course", 9700),
            (15, "Newborn Care 101", "course", 4700),
            (16, "All Access Class Pass", "bundle", 14900),
        ]
    ]


def _affiliate():
    from src.bbu_payments.models import BBUAffiliate

    return BBUAffiliate(id=51, org_id=1, name="Erica Estrada",
                        email="erica@mybrestfriend.com", ref_code="mbfmama",
                        status="onboarding", commission_rate=0.5)


def _render(courses, status="restricted"):
    from src.bbu_payments.affiliate_branding import portal_page

    return portal_page(
        _affiliate(),
        {"sales": 0, "pending": 0, "available": 0, "paid": 0, "details": []},
        [], BASE,
        connect_state={"status": status, "currently_due_count": 5},
        courses=courses,
    )


def test_portal_renders_a_nonempty_link_for_every_course():
    courses = _catalogue()
    html = _render(courses)

    assert "Links for each class" in html
    values = re.findall(r"<input[^>]*?readonly value='([^']*)'", html)
    assert len(values) == len(courses) + 1, "one shop field plus one per course"
    assert values[0].endswith("/r/mbfmama"), "the shop link stays the plain one"
    course_values = values[1:]
    assert len(course_values) == 11
    assert all(v.strip() for v in course_values), "every course row must carry a real link"
    for pid in (6, 12, 16):
        assert f"/r/mbfmama?next=%2Fapi%2Fv1%2Fbbu%2Fbuy%2F{pid}" in html


def test_catalogue_rows_without_a_link_key_still_render_distinct_links():
    """This is the real caller contract: `_referral_courses` returns next_path only."""
    rows = _catalogue()
    assert all("referral_link" not in r for r in rows)

    values = re.findall(r"<input[^>]*?readonly value='([^']*)'", _render(rows))[1:]
    assert all(v.strip() for v in values)
    assert len(set(values)) == 11, "each course must get its own distinct link"


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


# --------------------------------------------------------------------------- #
# The waitlist page emits an inline script. It previously contained
# (' You're #'+d.position) - a single-quoted JS string holding an apostrophe -
# so the whole script failed to parse and the "Join the waitlist" button bound
# nothing. Parse the EMITTED script; do not trust the Python source.
# --------------------------------------------------------------------------- #

def _emitted_waitlist_script():
    import re as _re

    from src.bbu_payments.branding import waitlist_page
    from src.bbu_payments.models import BBUProduct

    product = BBUProduct(id=26, org_id=1, name="Doula Mentorship", kind="cohort",
                         price_cents=60000, public=True)
    html = waitlist_page(product, BASE, "Doula Mentorship")
    blocks = _re.findall(r"<script[^>]*>(.*?)</script>", html, _re.S)
    assert blocks, "waitlist page must emit an inline script"
    return "\n".join(blocks)


def test_emitted_waitlist_script_parses():
    import shutil
    import subprocess
    import tempfile

    script = _emitted_waitlist_script()
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available to parse the emitted script")

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(script)
        path = fh.name
    try:
        proc = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert proc.returncode == 0, (
            "emitted waitlist script does not parse:\n" + proc.stderr[:600]
        )
    finally:
        import os as _os
        _os.unlink(path)


def test_emitted_waitlist_script_keeps_the_apostrophe_inside_a_double_quoted_string():
    script = _emitted_waitlist_script()
    assert "You're #" in script, "the position prefix must still be rendered"
    # The apostrophe in "You're" must not be delimited by single quotes.
    assert "(' You're #'" not in script, "the old single-quoted form must be gone"
    assert '(" You\'re #"' in script, "the prefix must be double-quoted"
