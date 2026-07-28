"""Safe public-origin selection for BBU links and third-party redirects."""
import os

from fastapi import Request


def get_bbu_public_base_url(request: Request) -> str:
    """Return the public origin for BBU pages, emails, and Stripe redirects.

    The configured custom domain is canonical. During a domain cutover, hosts
    listed in ``BBU_FALLBACK_PUBLIC_DOMAINS`` (comma-separated hostnames) are
    also accepted. Never reflect an arbitrary Host header: these URLs may be
    sent to Stripe or copied into public emails.
    """
    canonical_domain = os.environ.get("LEARNHOUSE_DOMAIN") or request.url.netloc
    request_host = request.headers.get("host") or request.url.netloc
    request_host = request_host.split(",", 1)[0].strip().lower().split(":", 1)[0]
    fallback_domains = {
        domain.strip().lower()
        for domain in os.environ.get("BBU_FALLBACK_PUBLIC_DOMAINS", "").split(",")
        if domain.strip()
    }
    domain = request_host if request_host in fallback_domains else canonical_domain
    scheme = "https" if os.environ.get("LEARNHOUSE_SSL", "true") == "true" else "http"
    return f"{scheme}://{domain}"
