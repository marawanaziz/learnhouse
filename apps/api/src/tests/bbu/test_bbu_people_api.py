"""Members profile payload coverage for professional credential history."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from src.bbu_credentials import applications as app_svc
from src.bbu_credentials.models import BBUCredential
from src.db.users import User
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


async def _credential_only_user(db, first_name, last_name, email):
    user = User(
        username=email.split("@", 1)[0],
        first_name=first_name,
        last_name=last_name,
        email=email,
        password="hashed_password",
        user_uuid=f"user_{email.split('@', 1)[0]}",
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _people(client, query="", limit=25, offset=0):
    return await client.get(
        "/api/v1/bbu/people",
        params={"q": query, "limit": limit, "offset": offset},
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


@pytest.mark.asyncio
async def test_people_list_includes_credential_only_user_and_full_name_search(
    db, admin_user, monkeypatch
):
    user = await _credential_only_user(
        db, "Sydney", "Billings", "sydney-credential-only@test.com"
    )
    await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=user.id,
        credential_type="birth",
        credential_level="one_year_provisional",
        effective_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        source="training",
        source_ref="sydney-like-birth",
    )
    monkeypatch.setattr(people_router, "is_org_admin", AsyncMock(return_value=True))

    client = await _client_for(db, admin_user)
    async with client:
        response = await _people(client, "Sydney Billings")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["people"][0]["user_id"] == user.id
    assert response.json()["people"][0]["name"] == "Sydney Billings"


@pytest.mark.asyncio
async def test_people_list_excludes_credential_only_user_from_other_org(
    db, admin_user, other_org, monkeypatch
):
    user = await _credential_only_user(
        db, "Foreign", "Credential", "foreign-credential@test.com"
    )
    await app_svc.create_issuance(
        db,
        org_id=other_org.id,
        user_id=user.id,
        credential_type="birth",
        credential_level="one_year_provisional",
        effective_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        source="training",
        source_ref="foreign-birth",
    )
    monkeypatch.setattr(people_router, "is_org_admin", AsyncMock(return_value=True))

    client = await _client_for(db, admin_user)
    async with client:
        response = await _people(client, "foreign-credential@test.com")

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["people"] == []


@pytest.mark.asyncio
async def test_people_list_deduplicates_legacy_and_issuance_records(
    db, admin_user, monkeypatch
):
    user = await _credential_only_user(
        db, "Dual", "Credential", "dual-credential@test.com"
    )
    await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=user.id,
        credential_type="postpartum",
        credential_level="one_year_provisional",
        effective_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        source="training",
        source_ref="dual-postpartum",
    )
    db.add(BBUCredential(org_id=1, user_id=user.id, credential_type="postpartum"))
    await db.commit()
    monkeypatch.setattr(people_router, "is_org_admin", AsyncMock(return_value=True))

    client = await _client_for(db, admin_user)
    async with client:
        response = await _people(client, "Dual Credential")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [row["user_id"] for row in response.json()["people"]] == [user.id]


@pytest.mark.asyncio
async def test_people_list_pagination_and_counts_are_consistent(
    db, admin_user, monkeypatch
):
    users = []
    for index in range(3):
        user = await _credential_only_user(
            db,
            "Page",
            f"Credential{index}",
            f"page-credential-{index}@test.com",
        )
        users.append(user)
        await app_svc.create_issuance(
            db,
            org_id=1,
            user_id=user.id,
            credential_type="birth",
            credential_level="one_year_provisional",
            effective_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            source="training",
            source_ref=f"page-birth-{index}",
        )
    monkeypatch.setattr(people_router, "is_org_admin", AsyncMock(return_value=True))

    client = await _client_for(db, admin_user)
    async with client:
        first = await _people(client, "Page Credential", limit=2, offset=0)
        second = await _people(client, "Page Credential", limit=2, offset=2)

    first_body, second_body = first.json(), second.json()
    assert first.status_code == second.status_code == 200
    assert first_body["total"] == second_body["total"] == 3
    assert len(first_body["people"]) == 2
    assert len(second_body["people"]) == 1
    assert set(row["user_id"] for row in first_body["people"]).isdisjoint(
        row["user_id"] for row in second_body["people"]
    )
    assert set(row["user_id"] for row in first_body["people"] + second_body["people"]) == {
        user.id for user in users
    }


@pytest.mark.asyncio
async def test_people_list_preserves_existing_org_roster_members(
    db, regular_user, admin_user, monkeypatch
):
    monkeypatch.setattr(people_router, "is_org_admin", AsyncMock(return_value=True))

    client = await _client_for(db, admin_user)
    async with client:
        response = await _people(client, "regular@test.com")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["people"][0]["user_id"] == regular_user.id


@pytest.mark.asyncio
async def test_profile_returns_org_scoped_issuances_for_credential_only_member(
    db, admin_user, monkeypatch
):
    user = await _credential_only_user(
        db, "Profile", "Credential", "profile-credential@test.com"
    )
    issuance = await app_svc.create_issuance(
        db,
        org_id=1,
        user_id=user.id,
        credential_type="postpartum",
        credential_level="one_year_provisional",
        effective_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        source="training",
        source_ref="profile-postpartum",
    )
    monkeypatch.setattr(people_router, "is_org_admin", AsyncMock(return_value=True))

    client = await _client_for(db, admin_user)
    async with client:
        response = await client.get(f"/api/v1/bbu/people/{user.id}")

    assert response.status_code == 200
    rows = response.json()["credential_issuances"]
    assert [row["id"] for row in rows] == [issuance.id]
    assert response.json()["certificates"] == []
