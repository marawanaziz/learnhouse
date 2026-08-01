from datetime import datetime

import pytest

from src.db.users import User
from src.security.auth import authenticate_user
from src.security.security import security_hash_password
from src.services.users.identity import (
    get_canonical_user_by_email,
    merged_into_user_id,
    resolve_canonical_user,
)
from src.services.users.users import security_get_user


def _user(user_id: int, email: str, password: str, *, metadata=None) -> User:
    return User(
        id=user_id,
        username=f"identity-user-{user_id}",
        first_name="Stacie",
        last_name="Green",
        email=email,
        password=security_hash_password(password),
        user_uuid=f"user_identity_{user_id}",
        extra_metadata=metadata or {},
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    )


@pytest.mark.asyncio
async def test_alias_resolves_to_canonical_user(db, mock_request):
    canonical = _user(101, "canonical@example.com", "CanonicalPassword123!")
    alias = _user(
        102,
        "historical@example.com",
        "HistoricalPassword123!",
        metadata={
            "identity_reconciliation": {
                "merged_into_user_id": 101,
                "canonical_email": "canonical@example.com",
            }
        },
    )
    db.add(canonical)
    db.add(alias)
    await db.commit()

    assert merged_into_user_id(alias) == 101
    assert (await resolve_canonical_user(db, alias)).id == 101
    assert (await get_canonical_user_by_email(db, alias.email)).id == 101
    assert (await security_get_user(mock_request, db, alias.email)).id == 101


@pytest.mark.asyncio
async def test_alias_login_accepts_legacy_or_canonical_password(db, mock_request):
    canonical = _user(111, "canonical-login@example.com", "CanonicalPassword123!")
    alias = _user(
        112,
        "old-login@example.com",
        "HistoricalPassword123!",
        metadata={"identity_reconciliation": {"merged_into_user_id": 111}},
    )
    db.add(canonical)
    db.add(alias)
    await db.commit()

    legacy_login = await authenticate_user(
        mock_request, alias.email, "HistoricalPassword123!", db
    )
    canonical_login = await authenticate_user(
        mock_request, alias.email, "CanonicalPassword123!", db
    )

    assert legacy_login and legacy_login.id == 111
    assert canonical_login and canonical_login.id == 111
    assert not await authenticate_user(mock_request, alias.email, "wrong", db)


@pytest.mark.asyncio
async def test_broken_or_cyclic_alias_fails_closed(db):
    broken = _user(
        121,
        "broken@example.com",
        "Password123!",
        metadata={"identity_reconciliation": {"merged_into_user_id": 999}},
    )
    first = _user(
        122,
        "cycle-one@example.com",
        "Password123!",
        metadata={"identity_reconciliation": {"merged_into_user_id": 123}},
    )
    second = _user(
        123,
        "cycle-two@example.com",
        "Password123!",
        metadata={"identity_reconciliation": {"merged_into_user_id": 122}},
    )
    db.add(broken)
    db.add(first)
    db.add(second)
    await db.commit()

    assert (await resolve_canonical_user(db, broken)).id == 121
    resolved_cycle = await resolve_canonical_user(db, first)
    assert resolved_cycle.id in {122, 123}
