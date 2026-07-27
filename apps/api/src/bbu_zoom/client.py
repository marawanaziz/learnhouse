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

# BBU runs webinars from more than one Zoom account — the BBU account and the
# original Chicago Family Doulas one. A single credential set made every meeting
# hosted on the other account invisible to the cohort picker. Extra accounts are
# configured as ZOOM_ACCOUNT_ID_2 / ZOOM_CLIENT_ID_2 / ZOOM_CLIENT_SECRET_2
# (…_3 and so on); each is optional and simply skipped when unset.
def _accounts() -> list:
    out = []
    if ACCOUNT_ID and CLIENT_ID and CLIENT_SECRET:
        out.append({"label": os.environ.get("ZOOM_LABEL", "BBU"),
                    "account_id": ACCOUNT_ID, "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET})
    for n in range(2, 6):
        a = os.environ.get(f"ZOOM_ACCOUNT_ID_{n}", "")
        c = os.environ.get(f"ZOOM_CLIENT_ID_{n}", "")
        sec = os.environ.get(f"ZOOM_CLIENT_SECRET_{n}", "")
        if a and c and sec:
            out.append({"label": os.environ.get(f"ZOOM_LABEL_{n}", f"Account {n}"),
                        "account_id": a, "client_id": c, "client_secret": sec})
    return out


# per-account token cache, keyed by account id
_tokens: dict = {}


async def _token_for(acct: dict) -> str:
    cached = _tokens.get(acct["account_id"])
    if cached and cached["exp"] - 60 > time.time():
        return cached["value"]
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(_TOKEN_URL,
                         params={"grant_type": "account_credentials",
                                 "account_id": acct["account_id"]},
                         auth=(acct["client_id"], acct["client_secret"]))
        r.raise_for_status()
        data = r.json()
    tok = data.get("access_token", "")
    _tokens[acct["account_id"]] = {
        "value": tok, "exp": time.time() + int(data.get("expires_in", 3600) or 3600)}
    return tok

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


async def list_meetings() -> list:
    """List the account's scheduled meetings + webinars, for the cohort Zoom-ID
    picker. Iterates hosts (users) → their scheduled meetings (incl. recurring)
    + webinars. Returns [{id, topic, kind, host}] sorted by topic; [] when the
    integration isn't configured or on any error (caller shows a manual field)."""
    accounts = _accounts()
    if not accounts:
        return []
    rows = []
    async with httpx.AsyncClient(timeout=25) as c:
      for _acct in accounts:
        try:
            hdr = {"Authorization": f"Bearer {await _token_for(_acct)}",
                   "Content-Type": "application/json"}
        except Exception:
            continue
        try:
            r = await c.get(f"{_API}/users", params={"status": "active", "page_size": 300}, headers=hdr)
            users = r.json().get("users", []) if r.status_code == 200 else []
        except Exception:
            users = []
        for u in users:
            uid, email = u.get("id"), u.get("email", "")
            if not uid:
                continue
            try:
                r = await c.get(f"{_API}/users/{uid}/meetings",
                                params={"type": "scheduled", "page_size": 300}, headers=hdr)
                for m in (r.json().get("meetings", []) if r.status_code == 200 else []):
                    rows.append({"id": str(m.get("id")), "topic": m.get("topic", ""),
                                 "kind": "meeting", "host": email,
                                 "account": _acct["label"]})
            except Exception:
                pass
            try:
                r = await c.get(f"{_API}/users/{uid}/webinars",
                                params={"page_size": 300}, headers=hdr)
                for w in (r.json().get("webinars", []) if r.status_code == 200 else []):
                    rows.append({"id": str(w.get("id")), "topic": w.get("topic", ""),
                                 "kind": "webinar", "host": email,
                                 "account": _acct["label"]})
            except Exception:
                pass
    dedup = {r["id"]: r for r in rows if r.get("id")}
    return sorted(dedup.values(), key=lambda x: (x["topic"] or "").lower())


async def get_recording_urls(meeting_id: str) -> list:
    """Return share/play URLs for a meeting's cloud recordings ([] on any issue).

    Tries every configured account: a meeting hosted on the Chicago Family Doulas
    account is not visible to the BBU token, so a single-account lookup silently
    returned nothing for half the webinars.
    """
    if not meeting_id or not _accounts():
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
