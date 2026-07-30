"""Credential email delivery is retryable without duplicating successful sends."""
from unittest.mock import Mock

import pytest
from starlette.requests import Request

from src.bbu_credentials import notifications
from src.bbu_credentials.models import BBUCredentialApplication


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"host", b"learn.birthandbabyuniversity.com")],
            "scheme": "https",
            "server": ("learn.birthandbabyuniversity.com", 443),
            "query_string": b"",
        }
    )


@pytest.mark.asyncio
async def test_submission_email_retry_skips_member_after_member_send_succeeds(
    db, regular_user, monkeypatch
):
    application = BBUCredentialApplication(
        public_uuid="credential_application_email_test",
        org_id=1,
        user_id=regular_user.id,
        credential_type="birth",
        status="submitted",
        claimed_ceu_total=15,
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)
    monkeypatch.setenv("LEARNHOUSE_DOMAIN", "learn.birthandbabyuniversity.com")
    monkeypatch.setenv("BBU_CREDENTIAL_REVIEW_EMAILS", "anna@example.com")

    first_send = Mock()

    def fail_admin(*, to, subject, body):
        first_send(to=to, subject=subject, body=body)
        if to == "anna@example.com":
            raise RuntimeError("SMTP temporarily unavailable")

    monkeypatch.setattr(notifications, "send_email", fail_admin)
    with pytest.raises(RuntimeError):
        await notifications.notify_submission(
            _request(), db, application, regular_user
        )

    assert application.submission_member_notified_at
    assert not application.submission_admin_notified_at
    assert "SMTP temporarily unavailable" in application.notification_error
    assert application.notification_attempts == 1

    successful_retry = Mock()
    monkeypatch.setattr(notifications, "send_email", successful_retry)
    await notifications.notify_submission(
        _request(), db, application, regular_user
    )

    assert successful_retry.call_count == 1
    assert successful_retry.call_args.kwargs["to"] == "anna@example.com"
    assert application.submission_admin_notified_at
    assert application.submission_notified_at
    assert application.notification_error == ""
    assert application.notification_attempts == 2
