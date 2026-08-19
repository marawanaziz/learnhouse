import pytest

from src.services.users.password_reset_config import (
    CANONICAL_BBU_RESET_BASE_URL,
    RESET_EMAIL_MAX_ATTEMPTS,
    RESET_EMAIL_RATE_LIMIT_WINDOW_SECONDS,
    RESET_TOKEN_TTL_SECONDS,
    build_canonical_reset_url,
    get_canonical_reset_base_url,
    reset_code_is_expired,
)


def test_reset_policy_is_exact_and_rate_limit_is_short():
    assert RESET_TOKEN_TTL_SECONDS == 172800
    assert RESET_EMAIL_MAX_ATTEMPTS == 5
    assert RESET_EMAIL_RATE_LIMIT_WINDOW_SECONDS == 300


def test_reset_code_expiry_boundaries_are_exact():
    expiry = 1_000_000 + RESET_TOKEN_TTL_SECONDS
    assert reset_code_is_expired(expiry, now=expiry - 1) is False
    assert reset_code_is_expired(expiry, now=expiry) is True
    assert reset_code_is_expired(expiry, now=expiry + 1) is True


def test_reset_url_is_canonical_and_query_values_are_encoded(monkeypatch):
    monkeypatch.delenv("BBU_RESET_PUBLIC_BASE_URL", raising=False)
    assert get_canonical_reset_base_url() == CANONICAL_BBU_RESET_BASE_URL
    assert build_canonical_reset_url("user+tag@example.com", "ABC 123") == (
        "https://learn.birthandbabyuniversity.com/reset?"
        "email=user%2Btag%40example.com&resetCode=ABC%20123"
    )


def test_reset_url_configuration_fails_closed_for_wrong_hosts(monkeypatch):
    monkeypatch.setenv("BBU_RESET_PUBLIC_BASE_URL", "https://app-production-500b.up.railway.app")
    with pytest.raises(RuntimeError, match="canonical HTTPS BBU host"):
        get_canonical_reset_base_url()
