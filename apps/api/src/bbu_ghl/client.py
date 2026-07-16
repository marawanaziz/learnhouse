"""Thin async GoHighLevel API v2 client.

Models BBU state as a custom-object MODULE + structured FIELDS — never tags.
Course state lives in `custom_objects.course_enrollment` (one record per contact
per course), associated to the contact; contact-level `bbu__*` fields carry the
rollups that workflows segment and trigger on.

Env:
  BBU_GHL_PIT          Private Integration Token
  BBU_GHL_LOCATION_ID  sub-account (BBU + CFD + AR share one location)
"""
import os
from typing import Any, Optional

import httpx

BASE = "https://services.leadconnectorhq.com"
OBJ_KEY = "custom_objects.course_enrollment"

PIT = os.environ.get("BBU_GHL_PIT", "")
LOCATION_ID = os.environ.get("BBU_GHL_LOCATION_ID", "")

# Cloudflare fronts the GHL API and rejects default library user-agents with
# "Error 1010: access denied". A normal browser UA passes. Do not remove.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def is_configured() -> bool:
    return bool(PIT and LOCATION_ID)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {PIT}",
        "Version": "2021-07-28",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": _UA,
    }


class GHLClient:
    def __init__(self, timeout: float = 30.0):
        self._client = httpx.AsyncClient(timeout=timeout, headers=_headers())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._client.aclose()

    async def _req(self, method: str, path: str, **kw) -> tuple[int, Any]:
        r = await self._client.request(method, f"{BASE}{path}", **kw)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"raw": r.text[:300]}

    # ---------------------------------------------------------------- contacts
    async def upsert_contact(self, email: str, first_name: str = "",
                             last_name: str = "",
                             fields: Optional[dict] = None) -> Optional[str]:
        """Upsert by email. `fields` maps bbu__* field keys -> values."""
        body: dict = {"locationId": LOCATION_ID, "email": email}
        if first_name:
            body["firstName"] = first_name
        if last_name:
            body["lastName"] = last_name
        if fields:
            body["customFields"] = [
                {"key": k, "field_value": v} for k, v in fields.items()
                if v is not None
            ]
        st, d = await self._req("POST", "/contacts/upsert", json=body)
        if st not in (200, 201):
            raise RuntimeError(f"upsert_contact {st}: {str(d)[:200]}")
        return (d.get("contact") or {}).get("id")

    # ----------------------------------------------------- enrollment records
    async def create_enrollment(self, properties: dict) -> Optional[str]:
        st, d = await self._req("POST", f"/objects/{OBJ_KEY}/records", json={
            "locationId": LOCATION_ID, "properties": properties,
        })
        if st not in (200, 201):
            raise RuntimeError(f"create_enrollment {st}: {str(d)[:200]}")
        return (d.get("record") or {}).get("id")

    async def update_enrollment(self, record_id: str, properties: dict) -> bool:
        st, d = await self._req(
            "PUT", f"/objects/{OBJ_KEY}/records/{record_id}?locationId={LOCATION_ID}",
            json={"properties": properties},
        )
        if st not in (200, 201):
            raise RuntimeError(f"update_enrollment {st}: {str(d)[:200]}")
        return True

    # ------------------------------------------------------------ association
    async def association_id(self) -> Optional[str]:
        st, d = await self._req(
            "GET", f"/associations/?locationId={LOCATION_ID}&limit=100")
        for a in (d.get("associations") or []):
            if {a.get("firstObjectKey"), a.get("secondObjectKey")} == {"contact", OBJ_KEY}:
                return a.get("id")
        return None

    async def relate(self, association_id: str, contact_id: str,
                     record_id: str) -> bool:
        st, d = await self._req("POST", "/associations/relations", json={
            "locationId": LOCATION_ID,
            "associationId": association_id,
            "firstRecordId": contact_id,
            "secondRecordId": record_id,
        })
        # 400/409 here usually means the relation already exists — treat as ok.
        return st in (200, 201, 400, 409)
