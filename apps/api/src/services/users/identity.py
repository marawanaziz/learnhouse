"""Helpers for resolving platform accounts consolidated during data reconciliation.

The historical BBU imports used exact email matching.  A learner who used one
email in Circle, another in Xperiencify, and a third in Accredible could therefore
end up with several ``User`` rows.  Reconciliation keeps the old rows as login
aliases (so an old email/password still works) and records the canonical user in
``extra_metadata.identity_reconciliation.merged_into_user_id``.

Keep this module deliberately small and dependency-light: authentication,
password reset, imports, and admin tooling all need the same resolver.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.users import User


IDENTITY_METADATA_KEY = "identity_reconciliation"


def _metadata_dict(value: Any) -> dict:
    """Normalize legacy JSONB arrays without mutating the stored value."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        merged: dict = {}
        for item in value:
            if isinstance(item, dict):
                merged.update(item)
        return merged
    return {}


def merged_into_user_id(user: User) -> int | None:
    metadata = _metadata_dict(user.extra_metadata)
    identity = metadata.get(IDENTITY_METADATA_KEY)
    if not isinstance(identity, dict):
        return None
    raw = identity.get("merged_into_user_id")
    try:
        target = int(raw)
    except (TypeError, ValueError):
        return None
    if target <= 0 or target == user.id:
        return None
    return target


async def resolve_canonical_user(
    db_session: AsyncSession,
    user: User | None,
    *,
    max_hops: int = 8,
) -> User | None:
    """Follow a validated merge chain and return its canonical ``User`` row.

    A cycle or missing target fails closed by returning the last valid user.
    Reconciliation writes one-hop mappings, but the bounded traversal protects
    older aliases if a canonical account is consolidated again later.
    """
    if user is None:
        return None
    current = user
    seen = {int(current.id or 0)}
    for _ in range(max_hops):
        target_id = merged_into_user_id(current)
        if not target_id or target_id in seen:
            return current
        target = (
            await db_session.execute(select(User).where(User.id == target_id))
        ).scalars().first()
        if target is None:
            return current
        seen.add(target_id)
        current = target
    return current


async def get_raw_user_by_email(
    db_session: AsyncSession,
    email: str,
) -> User | None:
    normalized = (email or "").strip().lower()
    return (
        await db_session.execute(select(User).where(User.email == normalized))
    ).scalars().first()


async def get_canonical_user_by_email(
    db_session: AsyncSession,
    email: str,
) -> User | None:
    return await resolve_canonical_user(
        db_session,
        await get_raw_user_by_email(db_session, email),
    )
