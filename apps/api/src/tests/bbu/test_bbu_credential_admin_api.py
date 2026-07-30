"""Operations credential queue and ID-based member management coverage."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from src.bbu_admin import console
from src.bbu_credentials import applications as app_svc
from src.bbu_credentials.models import BBUCredentialIssuance
from src.core.events.database import get_db_session


async def _client_for(db):
    app = FastAPI()
    app.include_router(console.router, prefix="/api/v1/bbu/admin")

    async def override_db():
        yield db

    app.dependency_overrides[get_db_session] = override_db
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _submitted_application(db, user_id: int):
    await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=user_id,
        credential_type="birth",
        credential_level="one_year_provisional",
        effective_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        source="training",
        source_ref="course_birth",
    )
    application = await app_svc.create_application(
        db, org_id=1, user_id=user_id, credential_type="birth"
    )
    items = []
    for index, claimed in enumerate((10, 8), start=1):
        item = await app_svc.add_application_item(
            db,
            application,
            training_title=f"Training {index}",
            provider=f"Provider {index}",
            completion_date=f"2026-0{index}-01",
            claimed_ceu=claimed,
        )
        await app_svc.add_document_record(
            db,
            application,
            item,
            storage_key=f"proof-{index}.pdf",
            original_filename=f"proof-{index}.pdf",
            content_type="application/pdf",
            byte_size=100,
        )
        items.append(item)
    await app_svc.submit_application(db, application)
    return application, items


@pytest.mark.asyncio
async def test_admin_search_queue_review_and_approval_use_internal_ids(
    db, regular_user, admin_user, monkeypatch
):
    application, items = await _submitted_application(db, regular_user.id)
    monkeypatch.setattr(console, "authorize_admin", AsyncMock())
    monkeypatch.setattr(
        console, "get_current_user", AsyncMock(return_value=admin_user)
    )
    monkeypatch.setattr(
        "src.bbu_credentials.notifications.notify_decision", AsyncMock()
    )

    client = await _client_for(db)
    async with client:
        search = await client.get(
            "/api/v1/bbu/admin/credentials/members?q=regular"
        )
        assert search.status_code == 200
        assert search.json()["results"][0]["user_id"] == regular_user.id

        member = await client.get(
            f"/api/v1/bbu/admin/credentials/member/{regular_user.id}"
        )
        assert member.status_code == 200
        assert member.json()["issuances"][0]["credential_level"] == "one_year_provisional"
        assert member.json()["applications"][0]["id"] == application.id

        queue = await client.get(
            "/api/v1/bbu/admin/credential-applications?status=submitted"
        )
        assert queue.status_code == 200
        assert queue.json()["rows"][0]["user_id"] == regular_user.id

        for item, approved in zip(items, (9, 6)):
            review = await client.post(
                f"/api/v1/bbu/admin/credential-applications/{application.id}/items/{item.id}/review",
                json={"approved_ceu": approved, "admin_note": "Reviewed"},
            )
            assert review.status_code == 200

        decision = await client.post(
            f"/api/v1/bbu/admin/credential-applications/{application.id}/decision",
            json={"decision": "approve", "effective_at": "2026-03-10"},
        )
        assert decision.status_code == 200
        assert decision.json()["status"] == "approved"
        assert decision.json()["issuance"]["credential_level"] == "three_year_full"

    history = (
        await db.execute(
            select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.user_id == regular_user.id
            )
        )
    ).scalars().all()
    assert len(history) == 2


@pytest.mark.asyncio
async def test_admin_decline_requires_reason(
    db, regular_user, admin_user, monkeypatch
):
    application, _ = await _submitted_application(db, regular_user.id)
    monkeypatch.setattr(console, "authorize_admin", AsyncMock())
    monkeypatch.setattr(
        console, "get_current_user", AsyncMock(return_value=admin_user)
    )
    client = await _client_for(db)
    async with client:
        response = await client.post(
            f"/api/v1/bbu/admin/credential-applications/{application.id}/decision",
            json={"decision": "decline", "reason": ""},
        )
    assert response.status_code == 400
    assert "reason" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_admin_console_deep_link_and_notification_retry(
    db, regular_user, admin_user, monkeypatch
):
    application, _ = await _submitted_application(db, regular_user.id)
    monkeypatch.setattr(console, "authorize_admin", AsyncMock())
    monkeypatch.setattr(
        console, "get_current_user", AsyncMock(return_value=admin_user)
    )
    notify = AsyncMock()
    monkeypatch.setattr(
        "src.bbu_credentials.notifications.notify_submission", notify
    )
    client = await _client_for(db)
    async with client:
        page = await client.get(
            f"/api/v1/bbu/admin/?credential_application={application.id}"
        )
        assert page.status_code == 200
        assert "initialCredentialApplication" in page.text
        assert "CEU applications" in page.text

        retry = await client.post(
            f"/api/v1/bbu/admin/credential-applications/{application.id}/retry-notification",
            json={},
        )
        assert retry.status_code == 200
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_can_issue_one_year_then_three_year_from_member_record(
    db, regular_user, admin_user, monkeypatch
):
    monkeypatch.setattr(console, "authorize_admin", AsyncMock())
    monkeypatch.setattr(
        console, "get_current_user", AsyncMock(return_value=admin_user)
    )
    client = await _client_for(db)
    async with client:
        one_year = await client.post(
            f"/api/v1/bbu/admin/credentials/member/{regular_user.id}/manual-issue",
            json={
                "credential_type": "postpartum",
                "credential_level": "one_year_provisional",
                "effective_at": "2025-04-01",
                "reason": "Correcting a verified historical credential.",
            },
        )
        assert one_year.status_code == 200
        assert one_year.json()["issuance"]["term_years"] == 1

        three_year = await client.post(
            f"/api/v1/bbu/admin/credentials/member/{regular_user.id}/manual-issue",
            json={
                "credential_type": "postpartum",
                "credential_level": "three_year_full",
                "effective_at": "2026-04-01",
                "reason": "Verified exception approved by credentialing.",
            },
        )
        assert three_year.status_code == 200
        assert three_year.json()["issuance"]["term_years"] == 3
        assert three_year.json()["issuance"]["supersedes_issuance_id"] == (
            one_year.json()["issuance"]["id"]
        )

        member = await client.get(
            f"/api/v1/bbu/admin/credentials/member/{regular_user.id}"
        )
        levels = [
            row["credential_level"] for row in member.json()["issuances"]
        ]
        assert levels == ["three_year_full", "one_year_provisional"]


@pytest.mark.asyncio
async def test_manual_issue_rejects_future_dates_and_notifies_member(
    db, regular_user, admin_user, monkeypatch
):
    monkeypatch.setattr(console, "authorize_admin", AsyncMock())
    monkeypatch.setattr(
        console, "get_current_user", AsyncMock(return_value=admin_user)
    )
    notify = AsyncMock()
    monkeypatch.setattr(
        "src.bbu_credentials.notifications.notify_issuance", notify
    )
    client = await _client_for(db)
    async with client:
        future = await client.post(
            f"/api/v1/bbu/admin/credentials/member/{regular_user.id}/manual-issue",
            json={
                "credential_type": "birth",
                "credential_level": "three_year_full",
                "effective_at": "2099-01-01",
                "reason": "Invalid future test.",
            },
        )
        issued = await client.post(
            f"/api/v1/bbu/admin/credentials/member/{regular_user.id}/manual-issue",
            json={
                "credential_type": "birth",
                "credential_level": "three_year_full",
                "effective_at": "2026-04-01",
                "reason": "Verified credentialing exception.",
            },
        )

    assert future.status_code == 400
    assert "future" in future.json()["detail"].lower()
    assert issued.status_code == 200
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_legacy_credential_action_endpoint_is_retired(
    db, regular_user, monkeypatch
):
    monkeypatch.setattr(console, "authorize_admin", AsyncMock())
    client = await _client_for(db)
    async with client:
        response = await client.post(
            "/api/v1/bbu/admin/credentials/action",
            json={
                "email": str(regular_user.email),
                "action": "award_ceu",
                "count": 15,
            },
        )

    assert response.status_code == 410
    assert "member record" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_admin_console_offers_certificate_download_and_data_review(
    db, monkeypatch
):
    monkeypatch.setattr(console, "authorize_admin", AsyncMock())
    client = await _client_for(db)
    async with client:
        page = await client.get("/api/v1/bbu/admin/")

    assert page.status_code == 200
    assert "certificate.pdf" in page.text
    assert "Credential data review" in page.text
