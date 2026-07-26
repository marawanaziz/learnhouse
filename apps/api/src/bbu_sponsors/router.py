"""Sponsored access — free enrollment that never touches Stripe.

Three ways in, one ledger behind them:
  * bulk    — paste the emails a funder is covering; accounts are created and
              enrolled immediately, recipient does nothing
  * link    — one shareable /join/<token> URL, capped by the sponsor's seat limit
  * code    — individual single-use codes (the existing bbu_seats engine, tagged
              to the sponsor so its redemptions land in the same report)

Mounted at /api/v1/bbu/sponsors.
"""
import csv
import io

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.users import User
from src.security.auth import get_current_user
from src.bbu_admin.auth import authorize_admin
from src.bbu_payments.branding import _shell
from src.bbu_sponsors.models import BBUSponsor, BBUSponsoredEnrollment
from src.bbu_sponsors import service as svc

router = APIRouter()
ORG = 1

# Marks a seat-code batch as belonging to a sponsor, so redeeming one attributes
# the person to that funder instead of vanishing into an untracked batch.
BATCH_PREFIX = "sponsor:"


def batch_label_for(sponsor: BBUSponsor) -> str:
    return f"{BATCH_PREFIX}{sponsor.id}:{sponsor.name}"


def sponsor_id_from_batch(label: str) -> int:
    if not (label or "").startswith(BATCH_PREFIX):
        return 0
    try:
        return int(label[len(BATCH_PREFIX):].split(":", 1)[0])
    except Exception:
        return 0


@router.get("")
async def list_sponsors(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await authorize_admin(request, db_session)
    rows = (await db_session.execute(select(BBUSponsor).where(
        BBUSponsor.org_id == ORG).order_by(BBUSponsor.name))).scalars().all()
    out = []
    for s in rows:
        used = await svc.seats_used(db_session, s)
        out.append({
            "id": s.id, "name": s.name, "kind": s.kind, "active": bool(s.active),
            "courses": len(svc.course_list(s.course_uuids)),
            "course_uuids": s.course_uuids,
            "seat_limit": s.seat_limit, "seats_used": used,
            "join_enabled": bool(s.join_enabled), "join_token": s.join_token,
            "legacy_codes": s.legacy_codes, "notes": s.notes,
        })
    return out


@router.post("")
async def upsert_sponsor(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    b = await request.json()
    await authorize_admin(request, db_session, b.get("key", ""))
    sid = b.get("id")
    s = None
    if sid:
        s = (await db_session.execute(select(BBUSponsor).where(
            BBUSponsor.id == int(sid), BBUSponsor.org_id == ORG))).scalars().first()
    if s is None:
        s = BBUSponsor(org_id=ORG, created_at=svc.now())
    for f in ("name", "kind", "course_uuids", "legacy_codes", "notes"):
        if f in b:
            setattr(s, f, (b.get(f) or "").strip())
    if "seat_limit" in b:
        s.seat_limit = max(0, int(b.get("seat_limit") or 0))
    if "active" in b:
        s.active = bool(b["active"])
    if b.get("join_enabled") is not None:
        s.join_enabled = bool(b["join_enabled"])
        if s.join_enabled and not s.join_token:
            s.join_token = svc.new_token()
    if b.get("rotate_token"):
        s.join_token = svc.new_token()
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    return {"ok": True, "id": s.id, "join_token": s.join_token}


@router.post("/{sid}/bulk-enroll")
async def bulk_enroll(sid: int, request: Request,
                      db_session: AsyncSession = Depends(get_db_session)):
    """Body: {emails: [...] | text: "a@b.com, c@d.com"} — enrol everyone at once."""
    b = await request.json()
    await authorize_admin(request, db_session, b.get("key", ""))
    s = (await db_session.execute(select(BBUSponsor).where(
        BBUSponsor.id == sid, BBUSponsor.org_id == ORG))).scalars().first()
    if not s:
        raise HTTPException(404, "Sponsor not found")

    raw = b.get("emails")
    if not raw:
        text = (b.get("text") or "").replace(";", ",").replace("\n", ",")
        raw = [x.strip() for x in text.split(",")]
    seen, results = set(), []
    for entry in raw:
        email = (entry or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        if b.get("dry_run"):
            results.append({"email": email, "status": "would_enroll"})
        else:
            results.append(await svc.enroll(db_session, s, email, method="bulk"))
    counts: dict = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"sponsor": s.name, "dry_run": bool(b.get("dry_run")),
            "counts": counts, "results": results[:200]}


@router.post("/{sid}/codes")
async def make_codes(sid: int, request: Request,
                     db_session: AsyncSession = Depends(get_db_session)):
    """Generate single-use codes tagged to this sponsor (bbu_seats engine)."""
    b = await request.json()
    await authorize_admin(request, db_session, b.get("key", ""))
    s = (await db_session.execute(select(BBUSponsor).where(
        BBUSponsor.id == sid, BBUSponsor.org_id == ORG))).scalars().first()
    if not s:
        raise HTTPException(404, "Sponsor not found")
    count = max(1, min(500, int(b.get("count") or 1)))
    if s.seat_limit:
        left = s.seat_limit - await svc.seats_used(db_session, s)
        if count > left:
            raise HTTPException(400, f"Only {max(0, left)} seats left for {s.name}")

    from src.bbu_seats.models import BBUSeatCode
    from src.bbu_seats.router import _gen_code, _now as seat_now
    codes = []
    for _ in range(count):
        c = _gen_code("BBU")
        db_session.add(BBUSeatCode(
            org_id=ORG, code=c, batch_label=batch_label_for(s),
            course_uuids=s.course_uuids, owner_email=(b.get("owner_email") or "").strip(),
            status="unused", created_at=seat_now()))
        codes.append(c)
    await db_session.commit()
    return {"sponsor": s.name, "count": len(codes), "codes": codes}


@router.post("/{sid}/remove")
async def remove_enrollment(sid: int, request: Request,
                            db_session: AsyncSession = Depends(get_db_session)):
    """Body: {email, revoke_access?}. Take someone off a sponsor.

    A grant report goes to a funder, so a row added by mistake has to be
    removable. Attribution is dropped by default; `revoke_access` also pulls
    them out of the covered courses' access groups.
    """
    b = await request.json()
    await authorize_admin(request, db_session, b.get("key", ""))
    s = (await db_session.execute(select(BBUSponsor).where(
        BBUSponsor.id == sid, BBUSponsor.org_id == ORG))).scalars().first()
    if not s:
        raise HTTPException(404, "Sponsor not found")
    email = (b.get("email") or "").strip().lower()
    rows = (await db_session.execute(select(BBUSponsoredEnrollment).where(
        BBUSponsoredEnrollment.sponsor_id == sid,
        BBUSponsoredEnrollment.email == email))).scalars().all()
    if not rows:
        raise HTTPException(404, "Not enrolled under this sponsor")

    revoked = 0
    if b.get("revoke_access"):
        from src.db.usergroups import UserGroup
        from src.db.usergroup_user import UserGroupUser
        user = (await db_session.execute(select(User).where(
            User.email == email))).scalars().first()
        if user:
            for cu in svc.course_list(s.course_uuids):
                grp = (await db_session.execute(select(UserGroup).where(
                    UserGroup.org_id == ORG,
                    UserGroup.description == cu))).scalars().first()
                if not grp:
                    continue
                link = (await db_session.execute(select(UserGroupUser).where(
                    UserGroupUser.usergroup_id == grp.id,
                    UserGroupUser.user_id == user.id))).scalars().first()
                if link:
                    await db_session.delete(link)
                    revoked += 1
    for r in rows:
        await db_session.delete(r)
    await db_session.commit()
    return {"removed": len(rows), "courses_revoked": revoked, "email": email}


@router.get("/{sid}/report")
async def sponsor_report(sid: int, request: Request, fmt: str = "json",
                         db_session: AsyncSession = Depends(get_db_session)):
    await authorize_admin(request, db_session)
    s = (await db_session.execute(select(BBUSponsor).where(
        BBUSponsor.id == sid, BBUSponsor.org_id == ORG))).scalars().first()
    if not s:
        raise HTTPException(404, "Sponsor not found")
    rep = await svc.report(db_session, ORG, s)
    if fmt != "csv":
        return rep
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["sponsor", "name", "email", "date", "granted_via", "source", "courses"])
    for r in rep["rows"]:
        w.writerow([s.name, r["name"], r["email"], r["date"], r["via"],
                    r["source"], r["courses"]])
    safe = "".join(ch for ch in s.name if ch.isalnum() or ch in "-_") or "sponsor"
    return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{safe}-sponsored.csv"'})


# ---------------------------------------------------------------- join link
@router.get("/join/{token}", response_class=HTMLResponse)
async def join_page(token: str, request: Request,
                    db_session: AsyncSession = Depends(get_db_session)):
    s = (await db_session.execute(select(BBUSponsor).where(
        BBUSponsor.join_token == token, BBUSponsor.org_id == ORG))).scalars().first()
    if not s or not s.join_enabled or not s.active:
        return HTMLResponse(_shell("Link not active",
            "<p>This invitation link isn't active. Please check with whoever sent it.</p>"),
            status_code=404)
    if not await svc.has_capacity(db_session, s):
        return HTMLResponse(_shell("All seats claimed",
            f"<p>Every sponsored seat from {s.name} has been claimed. "
            "Please contact them if you think this is a mistake.</p>"))
    body = f"""
      <p style="font-size:1.05rem">Your access is sponsored by <b>{s.name}</b> —
      there's nothing to pay.</p>
      <form method="post" action="/api/v1/bbu/sponsors/join/{token}" style="margin-top:1.2rem">
        <input name="name" placeholder="Your name" style="width:100%;padding:.7rem;margin-bottom:.6rem">
        <input name="email" type="email" required placeholder="Your email"
               style="width:100%;padding:.7rem;margin-bottom:.9rem">
        <button type="submit" style="width:100%;padding:.8rem;font-weight:700">
          Claim my free access</button>
      </form>
      <p class=muted style="margin-top:1rem;font-size:.85rem">
        We'll email you a link to set your password.</p>"""
    return HTMLResponse(_shell("Claim your sponsored access", body))


@router.post("/join/{token}", response_class=HTMLResponse)
async def join_submit(token: str, request: Request,
                      db_session: AsyncSession = Depends(get_db_session)):
    s = (await db_session.execute(select(BBUSponsor).where(
        BBUSponsor.join_token == token, BBUSponsor.org_id == ORG))).scalars().first()
    if not s or not s.join_enabled or not s.active:
        raise HTTPException(404, "Link not active")
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    name = (form.get("name") or "").strip()
    res = await svc.enroll(db_session, s, email, name=name, method="link")
    if res["status"] == "enrolled":
        msg = (f"<p>You're in — {res['courses']} course(s) unlocked, "
               f"sponsored by {s.name}.</p><p>Check your email to set a password, "
               "then sign in to start.</p>")
    elif res["status"] == "already_enrolled":
        msg = "<p>You've already claimed this — just sign in with this email.</p>"
    else:
        msg = f"<p>We couldn't complete that: {res.get('reason', 'unknown error')}</p>"
    return HTMLResponse(_shell("Sponsored access", msg))
