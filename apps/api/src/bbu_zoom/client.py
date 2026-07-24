"""Zoom Server-to-Server OAuth client — cohort meeting automation. Clean-room.

Powers two cohort features (both fail-soft, both no-op when Zoom isn't configured):
  • auto-register a member to the cohort's recurring meeting/webinar on enrollment
  • pull the cohort meeting's cloud recordings so they show in the cohort

Credentials come from env (set on Railway from the "CFD Events Sync" S2S app):
  ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID / ZOOM_CLIENT_SECRET
Registrant-add needs the app to hold meeting:write / webinar:write; recording read
needs cloud_recording:read. Missing scope → logged + skipped, never fatal.
"""
import base64
import os
import time

import httpx

ACCOUNT_ID = os.environ.get("ZOOM_ACCOUNT_ID", "")
CLIENT_ID = os.environ.get("ZOOM_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("ZOOM_CLIENT_SECRET", "")

_TOKEN_URL = "https://zoom.us/oauth/token"
_API = "https://api.zoom.us/v2"

# module-level token cache (access_token, expires_at_epoch)
_token = {"value": "", "exp": 0.0}


def is_configured() -> bool:
    return bool(ACCOUNT_ID and CLIENT_ID and CLIENT_SECRET)


async def _get_token() -> str:
    if _token["value"] and _token["exp"] - 60 > time.time():
        return _token["value"]
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(_TOKEN_URL, params={
            "grant_type": "account_credentials", "account_id": ACCOUNT_ID,
        }, headers={"Authorization": f"Basic {basic}"})
    r.raise_for_status()
    data = r.json()
    _token["value"] = data.get("access_token", "")
    _token["exp"] = time.time() + int(data.get("expires_in", 3600) or 3600)
    return _token["value"]


async def _headers() -> dict:
    return {"Authorization": f"Bearer {await _get_token()}", "Content-Type": "application/json"}


async def add_registrant(meeting_id: str, email: str, first_name: str = "",
                         last_name: str = "") -> dict:
    """Register an attendee to a Zoom meeting OR webinar (tries meeting, falls
    back to webinar). Returns {ok, join_url?, error?}. Never raises."""
    if not is_configured() or not meeting_id or not email:
        return {"ok": False, "error": "not configured or missing id/email"}
    body = {"email": email, "first_name": first_name or email.split("@")[0], "last_name": last_name or "-"}
    try:
        hdr = await _headers()
    except Exception as e:
        return {"ok": False, "error": f"token: {e}"}
    async with httpx.AsyncClient(timeout=20) as c:
        for path in (f"/meetings/{meeting_id}/registrants", f"/webinars/{meeting_id}/registrants"):
            try:
                r = await c.post(f"{_API}{path}", json=body, headers=hdr)
                if r.status_code in (200, 201):
                    j = r.json()
                    return {"ok": True, "join_url": j.get("join_url", ""), "kind": path.split("/")[1]}
                # 300/404 usually means "wrong type" → try the other endpoint
                if r.status_code not in (300, 404):
                    return {"ok": False, "error": f"{r.status_code}: {r.text[:200]}"}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "not a registrable meeting or webinar"}


async def get_recording_urls(meeting_id: str) -> list:
    """Return share/play URLs for a meeting's cloud recordings ([] on any issue)."""
    if not is_configured() or not meeting_id:
        return []
    try:
        hdr = await _headers()
        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.get(f"{_API}/meetings/{meeting_id}/recordings", headers=hdr)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []
    urls = []
    share = data.get("share_url")
    if share:
        urls.append(share)
    for f in data.get("recording_files", []) or []:
        u = f.get("play_url") or f.get("download_url")
        if u and f.get("file_type") in (None, "MP4", "M4A", "SHARE"):
            urls.append(u)
    # de-dupe, preserve order
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out
