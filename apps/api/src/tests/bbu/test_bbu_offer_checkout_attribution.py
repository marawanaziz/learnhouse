"""A purchase from an offer page must carry affiliate attribution.

Regression coverage for a real defect found on the live runtime: a buyer who
followed a generic shop referral link, browsed the shop, and bought through an
offer page (`/store/offers/{offer_uuid}`) recorded no affiliate at all.

There were two independent breaks and fixing either alone fixed nothing:

1. The Next server action `getOfferCheckoutSession` builds its URL from
   `getAPIUrl()`, which falls back to a server-to-server API URL when there is
   no `window`. The request therefore never reaches the backend with the
   browser's cookies, and it carried no cookie of its own.
2. `offers_router.checkout` hardcoded `"affiliate_ref": ""` into the Stripe
   session metadata and created the `BBUOrder` with no `affiliate_ref`.

The native buy path (`bbu_payments/router.py`) already did this correctly and is
the reference for both halves.
"""

import re
from pathlib import Path

import pytest
from starlette.requests import Request

from src.bbu_payments import offers_router
from src.bbu_payments.router import REF_COOKIE

BASE = "https://learn.birthandbabyuniversity.com"
API_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = API_ROOT.parents[1] / "web"


def _request(query="", cookie=None):
    headers = []
    if cookie is not None:
        headers.append((b"cookie", f"{REF_COOKIE}={cookie}".encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/payments/1/offers/abc/checkout",
        "query_string": query.encode(),
        "headers": headers,
        "scheme": "https",
        "client": ("127.0.0.1", 1234),
        "server": ("learn.birthandbabyuniversity.com", 443),
    }
    return Request(scope)


# --------------------------------------------------------------------------- #
# Backend resolution
# --------------------------------------------------------------------------- #

def test_cookie_is_resolved_when_nothing_else_is_supplied():
    assert offers_router._resolve_affiliate_ref(_request(cookie="mbfmama")) == "mbfmama"


def test_explicit_body_ref_is_honoured():
    assert offers_router._resolve_affiliate_ref(_request(cookie="mbfmama"), {"ref": "other"}) == "other"


def test_explicit_query_ref_is_honoured():
    assert offers_router._resolve_affiliate_ref(_request(query="ref=querycode", cookie="mbfmama")) == "querycode"


def test_missing_ref_resolves_to_empty_not_a_guess():
    assert offers_router._resolve_affiliate_ref(_request()) == ""


def test_ref_is_stripped_and_whitespace_only_becomes_empty():
    assert offers_router._resolve_affiliate_ref(_request(cookie="  mbfmama  ")) == "mbfmama"
    assert offers_router._resolve_affiliate_ref(_request(cookie="   ")) == ""


def test_no_body_argument_is_safe():
    # request.json() can fail and leave body as {}; passing None must not raise.
    assert offers_router._resolve_affiliate_ref(_request(cookie="mbfmama"), None) == "mbfmama"
    assert offers_router._resolve_affiliate_ref(_request(), None) == ""


# --------------------------------------------------------------------------- #
# The handler must actually USE the resolved ref, on both stamps
# --------------------------------------------------------------------------- #

def _checkout_source() -> str:
    return (API_ROOT / "bbu_payments" / "offers_router.py").read_text()


def test_handler_stamps_ref_into_the_stripe_session_metadata():
    src = _checkout_source()
    assert '"affiliate_ref": ref,' in src, "the Stripe metadata must carry the resolved ref"
    assert '"affiliate_ref": "",' not in src, "the hardcoded empty ref must be gone"


def test_handler_stamps_ref_onto_the_order_row():
    src = _checkout_source()
    assert re.search(r"course_uuids=merged_courses,\s*affiliate_ref=ref,", src), (
        "BBUOrder must be created with affiliate_ref so the recorded order carries attribution"
    )


def test_handler_uses_the_shared_resolver():
    src = _checkout_source()
    assert "_resolve_affiliate_ref(request, body)" in src


def test_fulfilment_fallback_reads_the_same_metadata_key():
    """_fulfill already backfills order.affiliate_ref from session metadata, so
    the order row and the Stripe metadata must agree on the key name."""
    router_src = (API_ROOT / "bbu_payments" / "router.py").read_text()
    assert '"affiliate_ref": ref},' in router_src, "native path stamps the same key"
    assert '.get("affiliate_ref", "")' in router_src, "fulfilment reads the same key"


# --------------------------------------------------------------------------- #
# The server action must forward the cookie
# --------------------------------------------------------------------------- #

def _offers_service_source() -> str:
    return (WEB_ROOT / "services" / "payments" / "offers.ts").read_text()


def test_server_action_reads_the_incoming_referral_cookie():
    src = _offers_service_source()
    assert "from 'next/headers'" in src or 'from "next/headers"' in src
    assert "cookies()" in src, (
        "a server action has no browser cookie jar, so it must read cookies() explicitly"
    )
    assert "bbu_ref" in src


def test_server_action_forwards_the_cookie_header():
    src = _offers_service_source()
    assert "Cookie:" in src, "the outbound request must carry the referral cookie"
    assert "ref" in src


def test_server_action_sends_ref_in_the_body_too():
    src = _offers_service_source()
    assert "{ bumps, ref }" in src, "the body must carry the ref as a belt-and-braces path"


def test_global_request_helper_was_not_changed():
    """The fix must stay local to the offer call; the shared helper is used by
    every API call in the app."""
    src = (WEB_ROOT / "services" / "utils" / "ts" / "requests.ts").read_text()
    assert "Cookie:" not in src, (
        "RequestBodyWithAuthHeader is generic; it must not start attaching cookies"
    )


# --------------------------------------------------------------------------- #
# The other two fixes in this tree must survive
# --------------------------------------------------------------------------- #

def test_six_128_checkout_recovery_is_preserved():
    src = (WEB_ROOT / "app" / "orgs" / "[orgslug]" / "(withmenu)" / "store"
           / "offers" / "[offerid]" / "offer-detail.tsx").read_text()
    assert "setRetryUrl(url)" in src
    assert "checkoutError" in src
    assert "role=\"alert\"" in src


def test_six_126_waitlist_script_still_parses():
    """The waitlist repair lives in branding.py; a broken apostrophe there
    re-breaks the form. The emitted-script parse test lives in
    test_bbu_affiliate_referral_links.py."""
    src = (API_ROOT / "bbu_payments" / "branding.py").read_text()
    assert "?(' You're #'" not in src, "the broken single-quoted form must stay gone"
    # In source the quote is escaped: (d.position?(\" You're #\"+d.position+...
    assert '?(' + chr(92) + '" You' + chr(39) + 're #' + chr(92) + '"' in src, (
        "the repaired double-quoted prefix must be present"
    )
