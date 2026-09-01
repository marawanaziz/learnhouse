"""Members profile payload coverage for professional credential history."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.bbu_credentials import applications as app_svc
from src.bbu_people import router as people_router
from src.core.events.database import get_db_session


async def _client_for(db, authenticated_user):
    app = FastAPI()
    route_dependency = people_router.get_current_user
    app.include_router(people_router.router, prefix="/api/v1/bbu/people")
    app.dependency_overrides[route_dependency] = lambda: authenticated_user

    async def override_db():
        yield db

    app.dependency_overrides[get_db_session] = override_db
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_members_profile_exposes_professional_issuances_for_admin_actions(
    db, regular_user, admin_user, monkeypatch
):
    issuance = await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=regular_user.id,
        credential_type="postpartum",
        credential_level="three_year_full",
        effective_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        source="training",
        source_ref="postpartum-training",
    )
    monkeypatch.setattr(people_router, "is_org_admin", AsyncMock(return_value=True))

    client = await _client_for(db, admin_user)
    async with client:
        response = await client.get(f"/api/v1/bbu/people/{regular_user.id}")

    assert response.status_code == 200
    rows = response.json()["credential_issuances"]
    assert rows[0]["id"] == issuance.id
    assert rows[0]["credential_type"] == "postpartum"
    assert rows[0]["verification_token"] == issuance.verification_token
    assert rows[0]["is_current"] is True
