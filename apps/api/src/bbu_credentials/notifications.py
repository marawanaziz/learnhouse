"""Branded email notifications for BBU credential applications."""
from __future__ import annotations

import html
import logging
import os

from fastapi import Request
from sqlmodel.ext.asyncio.session import AsyncSession

from src.bbu_credentials.models import (
    BBUCredentialApplication,
    BBUCredentialIssuance,
)
from src.bbu_payments.public_url import get_bbu_public_base_url
from src.db.users import User
from src.services.email.utils import send_email
from src.services.users.emails import STYLES, _email_layout


logger = logging.getLogger(__name__)


def _credential_label(credential_type: str) -> str:
    return (
        "Birth Doula"
        if credential_type == "birth"
        else "Postpartum Doula"
    )


def _review_recipients() -> list[str]:
    raw = os.environ.get("BBU_CREDENTIAL_REVIEW_EMAILS", "")
    recipients = []
    for value in raw.replace(";", ",").split(","):
        email = value.strip()
        if email and "@" in email and email not in recipients:
            recipients.append(email)
    return recipients


def _button(label: str, url: str) -> str:
    safe_url = html.escape(url, quote=True)
    return f'<a href="{safe_url}" style="{STYLES["button"]}">{html.escape(label)}</a>'


async def notify_submission(
    request: Request,
    db: AsyncSession,
    application: BBUCredentialApplication,
    user: User,
) -> None:
    if (
        application.submission_member_notified_at
        and application.submission_admin_notified_at
    ):
        return
    from src.bbu_credentials import applications as app_svc

    application.notification_attempts = int(application.notification_attempts or 0) + 1
    base = get_bbu_public_base_url(request).rstrip("/")
    member_url = f"{base}/account/credentials"
    admin_url = (
        f"{base}/dash/operations?credential_application={application.id}"
    )
    raw_name = (
        f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username
    )
    name = html.escape(raw_name)
    label = _credential_label(application.credential_type)
    try:
        if not application.submission_member_notified_at:
            member_body = f"""
                <h1 style="{STYLES['h1']}">We received your CEU application</h1>
                <p style="{STYLES['p']}">Hi {name},</p>
                <p style="{STYLES['p']}">
                  Your {html.escape(label)} credential application has been submitted
                  with {application.claimed_ceu_total} claimed CEUs. The Birth &amp;
                  Baby University team will review your trainings and documents.
                </p>
                {_button("View your application", member_url)}
            """
            send_email(
                to=str(user.email),
                subject=f"Your BBU {label} CEU application was submitted",
                body=_email_layout(
                    "Credential application submitted",
                    member_body,
                    "You will receive another email when a decision is available.",
                ),
            )
            application.submission_member_notified_at = app_svc._now()
            db.add(application)
            await db.commit()

        recipients = _review_recipients()
        if not recipients:
            raise RuntimeError(
                "BBU_CREDENTIAL_REVIEW_EMAILS is not configured."
            )
        admin_body = f"""
            <h1 style="{STYLES['h1']}">New CEU application to review</h1>
            <p style="{STYLES['p']}">
              {name} ({html.escape(str(user.email))}) submitted a
              {html.escape(label)} application with
              {application.claimed_ceu_total} claimed CEUs.
            </p>
            {_button("Review application", admin_url)}
        """
        if not application.submission_admin_notified_at:
            for recipient in recipients:
                send_email(
                    to=recipient,
                    subject=f"New BBU CEU application: {raw_name}",
                    body=_email_layout(
                        "New credential application",
                        admin_body,
                        "Sign in to the BBU Operations dashboard to review the documents.",
                    ),
                )
            application.submission_admin_notified_at = app_svc._now()

        application.submission_notified_at = app_svc._now()
        application.notification_error = ""
        db.add(application)
        await db.commit()
    except Exception as exc:
        application.notification_error = str(exc)[:1000]
        db.add(application)
        await db.commit()
        logger.exception(
            "Credential submission notification failed for application %s",
            application.id,
        )
        raise


async def notify_decision(
    request: Request,
    db: AsyncSession,
    application: BBUCredentialApplication,
    user: User,
    *,
    credential_id: str = "",
) -> None:
    if application.decision_notified_at:
        return
    from src.bbu_credentials import applications as app_svc

    application.notification_attempts = int(application.notification_attempts or 0) + 1
    base = get_bbu_public_base_url(request).rstrip("/")
    member_url = f"{base}/account/credentials"
    name = html.escape(
        f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username
    )
    label = _credential_label(application.credential_type)

    if application.status == "approved":
        heading = "Your credential application was approved"
        subject = f"Your new BBU {label} credential is ready"
        detail = (
            f"Your new three-year {html.escape(label)} credential has been "
            f"issued{f' with credential ID {html.escape(credential_id)}' if credential_id else ''}."
        )
        footer = "Your prior certificates remain available in your credential history."
    elif application.status == "declined":
        heading = "A decision is available for your application"
        subject = f"Update on your BBU {label} CEU application"
        detail = (
            "The application was not approved. The review reason is shown below:"
            f'<br><br><strong style="color:#113d5d">'
            f"{html.escape(application.decline_reason)}</strong>"
        )
        footer = "You can review the decision and start a new application from your account."
    else:
        return

    body = f"""
        <h1 style="{STYLES['h1']}">{heading}</h1>
        <p style="{STYLES['p']}">Hi {name},</p>
        <p style="{STYLES['p']}">{detail}</p>
        {_button("View credential details", member_url)}
    """
    try:
        send_email(
            to=str(user.email),
            subject=subject,
            body=_email_layout(heading, body, footer),
        )
        application.decision_notified_at = app_svc._now()
        application.notification_error = ""
        db.add(application)
        await db.commit()
    except Exception as exc:
        application.notification_error = str(exc)[:1000]
        db.add(application)
        await db.commit()
        logger.exception(
            "Credential decision notification failed for application %s",
            application.id,
        )
        raise


async def notify_issuance(
    request: Request,
    user: User,
    issuance: BBUCredentialIssuance,
) -> None:
    """Notify a member after an administrator manually creates a certificate."""
    base = get_bbu_public_base_url(request).rstrip("/")
    member_url = f"{base}/account/credentials"
    certificate_url = (
        f"{base}/api/v1/bbu/credentials/verify/"
        f"{issuance.verification_token}/certificate.pdf"
    )
    name = html.escape(
        f"{user.first_name or ''} {user.last_name or ''}".strip()
        or user.username
    )
    label = _credential_label(issuance.credential_type)
    level = (
        "one-year provisional"
        if issuance.credential_level == "one_year_provisional"
        else "three-year full"
    )
    heading = "Your new BBU credential is ready"
    body = f"""
        <h1 style="{STYLES['h1']}">{heading}</h1>
        <p style="{STYLES['p']}">Hi {name},</p>
        <p style="{STYLES['p']}">
          A new {html.escape(level)} {html.escape(label)} credential has been
          issued with credential ID
          <strong>{html.escape(issuance.public_credential_id)}</strong>.
        </p>
        <p style="{STYLES['p']}">
          It is effective {html.escape(issuance.effective_at[:10])} and valid
          through {html.escape(issuance.expires_at[:10])}.
        </p>
        {_button("Download your certificate", certificate_url)}
        <p style="{STYLES['p']}">{_button("View credential history", member_url)}</p>
    """
    send_email(
        to=str(user.email),
        subject=f"Your new BBU {label} credential is ready",
        body=_email_layout(
            heading,
            body,
            "Your prior certificates remain available in your credential history.",
        ),
    )
