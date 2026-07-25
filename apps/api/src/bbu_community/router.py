"""BBU community moderation — Report / Flag a post or comment.

Clean-room (no ee imports). Adds a lightweight report/flag flow on top of the
native communities: any signed-in member can flag a discussion or comment;
admins review the queue and mark each report actioned or dismissed. The table
auto-creates on startup via SQLModel.metadata.create_all.

Mounted at /api/v1/bbu/community.
  POST /report                 learner — flag a post/comment
  GET  /reports?status=open    admin  — review queue (JSON)
  POST /reports/{id}/resolve   admin  — actioned | dismissed
  GET  /admin                  admin  — HTML moderation queue (embedded page)
"""
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.security.auth import get_current_user, resolve_acting_user_id
from src.security.org_auth import is_org_admin
from src.db.users import User, AnonymousUser
from src.db.communities.discussions import Discussion

router = APIRouter()
ORG = 1
ADMIN_KEY = os.environ.get("BBU_MIGRATION_KEY") or os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")


class BBUPostReport(SQLModel, table=True):
    __tablename__ = "bbu_post_report"
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(default=ORG, index=True)
    community_id: Optional[int] = Field(default=None)
    discussion_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, ForeignKey("discussion.id", ondelete="CASCADE")))
    comment_id: Optional[int] = Field(default=None)
    reporter_user_id: int = Field(default=0, index=True)
    reporter_email: str = Field(default="", sa_column=Column(String(255)))
    reason: str = Field(default="other", sa_column=Column(String(60)))
    details: str = Field(default="", sa_column=Column(Text))
    status: str = Field(default="open", sa_column=Column(String(20), index=True))  # open|actioned|dismissed
    created_at: str = Field(default="")
    resolved_at: str = Field(default="")
    resolved_by: int = Field(default=0)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _acting_uid(user) -> int:
    if user and not isinstance(user, AnonymousUser):
        return resolve_acting_user_id(user) or 0
    return 0


async def _guard_admin(request: Request, db: AsyncSession, user) -> None:
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key", "")
    if ADMIN_KEY and key == ADMIN_KEY:
        return
    uid = await _acting_uid(user)
    if uid and await is_org_admin(uid, ORG, db):
        return
    raise HTTPException(403, "Forbidden")


# ---------------------------------------------------------------- learner: report
@router.post("/report")
async def report_post(request: Request, db_session: AsyncSession = Depends(get_db_session),
                      user=Depends(get_current_user)):
    uid = await _acting_uid(user)
    if not uid:
        raise HTTPException(401, "Sign in to report a post")
    body = await request.json()
    discussion_id = body.get("discussion_id")
    comment_id = body.get("comment_id")
    if not discussion_id and not comment_id:
        raise HTTPException(400, "discussion_id or comment_id required")
    community_id = body.get("community_id")
    if discussion_id and not community_id:
        d = (await db_session.execute(select(Discussion).where(
            Discussion.id == int(discussion_id)))).scalars().first()
        community_id = d.community_id if d else None
    u = (await db_session.execute(select(User).where(User.id == uid))).scalars().first()
    # de-dupe: one open report per user per target
    dupe = (await db_session.execute(select(BBUPostReport).where(
        BBUPostReport.reporter_user_id == uid, BBUPostReport.status == "open",
        BBUPostReport.discussion_id == (int(discussion_id) if discussion_id else None),
        BBUPostReport.comment_id == (int(comment_id) if comment_id else None),
    ))).scalars().first()
    if dupe:
        return {"ok": True, "already_reported": True}
    rep = BBUPostReport(
        org_id=ORG, community_id=community_id,
        discussion_id=int(discussion_id) if discussion_id else None,
        comment_id=int(comment_id) if comment_id else None,
        reporter_user_id=uid, reporter_email=(u.email if u else ""),
        reason=(body.get("reason") or "other")[:60], details=(body.get("details") or "")[:2000],
        status="open", created_at=_now(),
    )
    db_session.add(rep)
    await db_session.commit()
    return {"ok": True}


# ---------------------------------------------------------------- admin: queue
@router.get("/reports")
async def list_reports(request: Request, status: str = "open",
                       db_session: AsyncSession = Depends(get_db_session),
                       user=Depends(get_current_user)):
    await _guard_admin(request, db_session, user)
    q = select(BBUPostReport).where(BBUPostReport.org_id == ORG)
    if status and status != "all":
        q = q.where(BBUPostReport.status == status)
    rows = (await db_session.execute(q.order_by(BBUPostReport.id.desc()).limit(300))).scalars().all()
    out = []
    for r in rows:
        title = ""
        if r.discussion_id:
            d = (await db_session.execute(select(Discussion).where(
                Discussion.id == r.discussion_id))).scalars().first()
            title = (d.title if d else "(deleted)")
        out.append({"id": r.id, "target": ("comment" if r.comment_id else "discussion"),
                    "discussion_id": r.discussion_id, "comment_id": r.comment_id,
                    "title": title, "reason": r.reason, "details": r.details,
                    "reporter": r.reporter_email, "status": r.status, "date": (r.created_at or "")[:16]})
    return {"total": len(out), "reports": out}


@router.post("/reports/{report_id}/resolve")
async def resolve_report(report_id: int, request: Request,
                         db_session: AsyncSession = Depends(get_db_session),
                         user=Depends(get_current_user)):
    await _guard_admin(request, db_session, user)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    action = (body.get("action") or "dismissed")
    r = (await db_session.execute(select(BBUPostReport).where(
        BBUPostReport.id == report_id))).scalars().first()
    if not r:
        raise HTTPException(404, "Report not found")
    r.status = "actioned" if action == "actioned" else "dismissed"
    r.resolved_at = _now()
    r.resolved_by = await _acting_uid(user)
    db_session.add(r)
    await db_session.commit()
    return {"ok": True, "status": r.status}


# ---------------------------------------------------------------- admin: HTML page
@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db_session: AsyncSession = Depends(get_db_session),
                     user=Depends(get_current_user)):
    await _guard_admin(request, db_session, user)
    data = await list_reports(request, "open", db_session, user)
    rows = "".join(
        f"<tr style='border-bottom:1px solid #e2ebf2'>"
        f"<td style='padding:10px 8px'><b>{r['title'] or '—'}</b><br>"
        f"<span style='color:#6b6f79;font-size:.8rem'>{r['target']} #{r['discussion_id'] or r['comment_id']}</span></td>"
        f"<td style='padding:10px 8px'>{r['reason']}<br><span style='color:#6b6f79;font-size:.82rem'>{r['details'][:140]}</span></td>"
        f"<td style='padding:10px 8px;font-size:.82rem'>{r['reporter']}<br>{r['date']}</td>"
        f"<td style='padding:10px 8px;white-space:nowrap'>"
        f"<button onclick=\"res({r['id']},'actioned')\" style='border:1px solid #f0c9c9;background:#fdf3f3;color:#a12a2a;border-radius:999px;padding:5px 11px;font-size:.78rem;cursor:pointer;font-weight:700'>Remove/Action</button> "
        f"<button onclick=\"res({r['id']},'dismissed')\" style='border:1px solid #cfe0ec;background:#f4f9fd;color:#113d5d;border-radius:999px;padding:5px 11px;font-size:.78rem;cursor:pointer;font-weight:700'>Dismiss</button></td>"
        f"</tr>"
        for r in data["reports"]
    ) or "<tr><td colspan=4 style='padding:20px;color:#6b6f79'>No open reports. 🎉</td></tr>"
    key = request.query_params.get("key", "")
    html = f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'>
<title>Flagged posts</title>
<style>body{{font-family:'League Spartan',-apple-system,sans-serif;margin:0;background:#f1f8fd;color:#113d5d}}
.wrap{{max-width:1000px;margin:0 auto;padding:26px 20px}}h1{{font-family:'Playfair Display',serif;margin:0 0 4px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 6px 18px rgba(17,61,93,.05)}}
th{{text-align:left;padding:12px 8px;background:#3a91c6;color:#fff;font-size:.75rem;text-transform:uppercase}}</style></head>
<body><div class=wrap>
<h1>Flagged posts</h1><p style='color:#6b6f79'>Community reports awaiting review.</p>
<table><thead><tr><th>Post</th><th>Reason</th><th>Reported by</th><th>Action</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<script>
var KEY={('"'+key+'"') if key else 'null'};
async function res(id,action){{
  var u='/api/v1/bbu/community/reports/'+id+'/resolve'+(KEY?('?key='+encodeURIComponent(KEY)):'');
  var r=await fetch(u,{{method:'POST',headers:{{'Content-Type':'application/json'}},credentials:'include',body:JSON.stringify({{action:action}})}});
  if(r.ok)location.reload();else alert('Error');
}}
</script></body></html>"""
    return HTMLResponse(html)
