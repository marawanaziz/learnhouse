"""Shared, non-secret password-reset policy and URL construction."""

import os
from time import time
from urllib.parse import quote, urlparse


RESET_TOKEN_TTL_SECONDS = 48 * 60 * 60
RESET_EMAIL_MAX_ATTEMPTS = 5
RESET_EMAIL_RATE_LIMIT_WINDOW_SECONDS = 5 * 60
CANONICAL_BBU_RESET_BASE_URL = "https://learn.birthandbabyuniversity.com"


def get_canonical_reset_base_url() -> str:
    """Fail closed unless the configured reset origin is the canonical BBU host."""
    configured = os.environ.get(
        "BBU_RESET_PUBLIC_BASE_URL", CANONICAL_BBU_RESET_BASE_URL
    ).rstrip("/")
    parsed = urlparse(configured)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "learn.birthandbabyuniversity.com"
        or parsed.port is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "BBU_RESET_PUBLIC_BASE_URL must be the canonical HTTPS BBU host"
        )
    return CANONICAL_BBU_RESET_BASE_URL


def build_canonical_reset_url(email: str, reset_code: str) -> str:
    """Build a canonical reset URL without logging its secret values."""
    return (
        f"{get_canonical_reset_base_url()}/reset?email={quote(str(email), safe='')}"
        f"&resetCode={quote(reset_code, safe='')}"
    )


def reset_code_is_expired(expires_at: int, now: int | None = None) -> bool:
    """Treat the exact expiry second as expired for exact 48-hour validity."""
    return (int(time()) if now is None else now) >= expires_at
