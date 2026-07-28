from starlette.requests import Request

from src.bbu_payments.router import _base_url


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

    assert _base_url(_request("unrecognized.example")) == "https://learn.birthandbabyuniversity.com"


def test_bbu_checkout_uses_explicitly_allowed_fallback_domain(monkeypatch):
    fallback = "app-production-500b.up.railway.app"
    monkeypatch.setenv("LEARNHOUSE_DOMAIN", "learn.birthandbabyuniversity.com")
    monkeypatch.setenv("BBU_FALLBACK_PUBLIC_DOMAINS", fallback)

    assert _base_url(_request(fallback)) == f"https://{fallback}"


def test_bbu_checkout_does_not_reflect_untrusted_host(monkeypatch):
    monkeypatch.setenv("LEARNHOUSE_DOMAIN", "learn.birthandbabyuniversity.com")
    monkeypatch.setenv("BBU_FALLBACK_PUBLIC_DOMAINS", "app-production-500b.up.railway.app")

    assert _base_url(_request("attacker.example")) == "https://learn.birthandbabyuniversity.com"
