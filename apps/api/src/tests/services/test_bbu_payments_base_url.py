from starlette.requests import Request

from src.bbu_payments.affiliate_router import _base_url as affiliate_base_url
from src.bbu_payments.offers_router import _base_from_request
from src.bbu_payments.public_url import get_bbu_public_base_url
from src.bbu_seats.router import _base as seats_base_url


def _request(host: str) -> Request:
    return Request({
        "type": "http",
        "scheme": "https",
        "path": "/",
        "headers": [(b"host", host.encode())],
    })


def test_bbu_checkout_uses_configured_domain_by_default(monkeypatch):
    monkeypatch.setenv("LEARNHOUSE_DOMAIN", "learn.birthandbabyuniversity.com")
    monkeypatch.delenv("BBU_FALLBACK_PUBLIC_DOMAINS", raising=False)

    assert get_bbu_public_base_url(_request("unrecognized.example")) == "https://learn.birthandbabyuniversity.com"


def test_bbu_checkout_uses_explicitly_allowed_fallback_domain(monkeypatch):
    fallback = "app-production-500b.up.railway.app"
    monkeypatch.setenv("LEARNHOUSE_DOMAIN", "learn.birthandbabyuniversity.com")
    monkeypatch.setenv("BBU_FALLBACK_PUBLIC_DOMAINS", fallback)

    assert get_bbu_public_base_url(_request(fallback)) == f"https://{fallback}"


def test_bbu_checkout_does_not_reflect_untrusted_host(monkeypatch):
    monkeypatch.setenv("LEARNHOUSE_DOMAIN", "learn.birthandbabyuniversity.com")
    monkeypatch.setenv("BBU_FALLBACK_PUBLIC_DOMAINS", "app-production-500b.up.railway.app")

    assert get_bbu_public_base_url(_request("attacker.example")) == "https://learn.birthandbabyuniversity.com"


def test_all_bbu_public_link_flows_honor_the_allowed_fallback(monkeypatch):
    fallback = "app-production-500b.up.railway.app"
    monkeypatch.setenv("LEARNHOUSE_DOMAIN", "learn.birthandbabyuniversity.com")
    monkeypatch.setenv("BBU_FALLBACK_PUBLIC_DOMAINS", fallback)
    request = _request(fallback)

    assert affiliate_base_url(request) == f"https://{fallback}"
    assert _base_from_request(request) == f"https://{fallback}"
    assert seats_base_url(request) == f"https://{fallback}"
