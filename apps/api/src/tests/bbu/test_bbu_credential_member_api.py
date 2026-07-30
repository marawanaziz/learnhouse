"""Signed-in member API coverage for the BBU credential hub."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.bbu_credentials import applications as app_svc
from src.bbu_credentials import router as credential_router
from src.core.events.database import get_db_session


async def _client_for(db):
    app = FastAPI()
    app.include_router(credential_router.router, prefix="/api/v1/bbu/credentials")

    async def override_db():
        yield db

    app.dependency_overrides[get_db_session] = override_db
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_member_hub_and_application_submission_flow(
    db, regular_user, monkeypatch
):
    monkeypatch.setattr(
        credential_router, "get_current_user", AsyncMock(return_value=regular_user)
    )
    issuance = await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=regular_user.id,
        credential_type="birth",
        credential_level="one_year_provisional",
        effective_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        source="training",
        source_ref="course_birth",
    )

    client = await _client_for(db)
    async with client:
        hub = await client.get("/api/v1/bbu/credentials/me")
        assert hub.status_code == 200
        assert hub.json()["eligibility"]["birth"]["eligible"] is True
        assert hub.json()["issuances"][0]["credential_level"] == "one_year_provisional"

        verification = await client.get(
            f"/api/v1/bbu/credentials/verify/{issuance.verification_token}"
        )
        assert verification.status_code == 200
        assert verification.json()["credential_level"] == "one_year_provisional"
        assert verification.json()["public_credential_id"] == (
            issuance.public_credential_id
        )
        assert "verification_token" not in verification.json()
        assert "source_ref" not in verification.json()

        created = await client.post(
            "/api/v1/bbu/credentials/applications",
            json={"credential_type": "birth"},
        )
        assert created.status_code == 200
        public_uuid = created.json()["public_uuid"]

        item_response = await client.post(
            f"/api/v1/bbu/credentials/applications/{public_uuid}/items",
            json={
                "training_title": "Advanced Birth Support",
                "provider": "Training Partner",
                "completion_date": "2026-05-01",
                "claimed_ceu": 15,
            },
        )
        assert item_response.status_code == 200
        item_id = item_response.json()["id"]

        monkeypatch.setattr(
            "src.services.utils.upload_content.upload_content", AsyncMock()
        )
        uploaded = await client.post(
            f"/api/v1/bbu/credentials/applications/{public_uuid}/items/{item_id}/documents",
            files={"file": ("proof.pdf", b"%PDF-1.4 proof", "application/pdf")},
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["filename"] == "proof.pdf"

        monkeypatch.setattr(
            "src.bbu_credentials.notifications.notify_submission", AsyncMock()
        )
        submitted = await client.post(
            f"/api/v1/bbu/credentials/applications/{public_uuid}/submit"
        )
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "submitted"
        assert submitted.json()["claimed_ceu_total"] == 15


@pytest.mark.asyncio
async def test_member_cannot_open_another_members_application(
    db, regular_user, admin_user, monkeypatch
):
    await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=regular_user.id,
        credential_type="postpartum",
        credential_level="three_year_full",
        effective_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        source="cross_cert",
        source_ref="course_cross",
    )
    application = await app_svc.create_application(
        db,
        org_id=1,
        user_id=regular_user.id,
        credential_type="postpartum",
    )
    monkeypatch.setattr(
        credential_router, "get_current_user", AsyncMock(return_value=admin_user)
    )
    client = await _client_for(db)
    async with client:
        response = await client.get(
            f"/api/v1/bbu/credentials/applications/{application.public_uuid}"
        )
    assert response.status_code == 404
