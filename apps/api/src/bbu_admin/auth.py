"""Shared BBU admin authorizer — accept EITHER the admin key (scripts/curl) OR a
logged-in org-1 admin session (the in-app admin pages rely on the session cookie,
so the powerful admin key never has to reach the browser)."""
import os

from fastapi import Request, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from src.security.auth import get_current_user
from src.security.org_auth import is_org_admin

ADMIN_KEY = os.environ.get("BBU_MIGRATION_KEY") or os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")


async def authorize_admin(request: Request, db: AsyncSession, body_key: str = "") -> None:
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key") or body_key
    if ADMIN_KEY and key == ADMIN_KEY:
        return
    try:
        user = await get_current_user(request, db)
        uid = getattr(user, "id", 0)
        if uid and await is_org_admin(uid, 1, db):
            return
    except Exception:
        pass
    raise HTTPException(403, "Forbidden")
