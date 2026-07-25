"""BBU credentials — admin + hook API (admin-key gated).
Mounted at /api/v1/bbu/credentials."""
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.users import User
from src.db.courses.courses import Course
from src.db.courses.certifications import Certifications
from src.bbu_credentials.models import BBUCredential, BBUCeuLedger
from src.bbu_credentials import service as svc

router = APIRouter()
ADMIN_KEY = os.environ.get("BBU_MIGRATION_KEY") or os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")

# Reminder cadence (days before expiry) — the scheduled reminder job fires here.
REMINDER_DAYS = [180, 90, 60, 45, 30]


def _check(request: Request):
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key", "")
    if not ADMIN_KEY or key != ADMIN_KEY:
        raise HTTPException(403, "Forbidden")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _user_by_email(db: AsyncSession, email: str) -> User:
    u = (await db.execute(select(User).where(
        User.email == (email or "").strip().lower()))).scalars().first()
    if not u:
        raise HTTPException(404, "User not found")
    return u


@router.get("")
async def list_credentials(request: Request, org_id: int = 1, status: str = "",
                           db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    q = select(BBUCredential).where(BBUCredential.org_id == org_id)
    rows = (await db_session.execute(q)).scalars().all()
    out = []
    for c in rows:
        eff = svc.compute_effective_status(c)
        if status and eff != status:
            continue
        total = await svc.approved_ceu_total(db_session, org_id, c.user_id)
        out.append(svc.to_dict(c, total))
    return out


@router.get("/user")
async def user_credentials(request: Request, email: str, org_id: int = 1,
                           db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    u = await _user_by_email(db_session, email)
    creds = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id, BBUCredential.user_id == u.id))).scalars().all()
    total = await svc.approved_ceu_total(db_session, org_id, u.id)
    ledger = (await db_session.execute(select(BBUCeuLedger).where(
        BBUCeuLedger.org_id == org_id, BBUCeuLedger.user_id == u.id))).scalars().all()
    return {
        "email": u.email,
        "ceu_total": total,
        "credentials": [svc.to_dict(c, total) for c in creds],
        "ledger": [{"id": r.id, "ceu": r.ceu_count, "source": r.source,
                    "ref": r.source_ref, "approved": r.approved,
                    "submitted_at": r.submitted_at} for r in ledger],
    }


@router.post("/issue")
async def issue(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Manual issue. Body: {email, credential_type, mode: provisional|full, org_id?}"""
    _check(request)
    b = await request.json()
    u = await _user_by_email(db_session, b.get("email", ""))
    org_id = int(b.get("org_id", 1))
    ctype = (b.get("credential_type") or "birth").strip().lower()
    mode = (b.get("mode") or "provisional").strip().lower()
    if mode == "full":
        c = await svc.issue_full_direct(db_session, org_id, u.id, ctype,
                                        source="manual", source_ref=b.get("note", ""))
    else:
        c = await svc.issue_provisional(db_session, org_id, u.id, ctype,
                                        source_ref=b.get("note", ""))
    total = await svc.approved_ceu_total(db_session, org_id, u.id)
    return svc.to_dict(c, total)


@router.post("/award-ceu")
async def award_ceu(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Body: {email, count, source?, source_ref?, approved?, org_id?}"""
    _check(request)
    b = await request.json()
    u = await _user_by_email(db_session, b.get("email", ""))
    org_id = int(b.get("org_id", 1))
    row = await svc.award_ceu(db_session, org_id, u.id, int(b.get("count", 0)),
                              source=b.get("source", "manual"),
                              source_ref=b.get("source_ref", ""),
                              approved=bool(b.get("approved", True)))
    total = await svc.approved_ceu_total(db_session, org_id, u.id)
    return {"ledger_id": row.id, "ceu_total": total}


@router.post("/approve-ceu")
async def approve_ceu(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Approve a pending external CEU. Body: {ledger_id, org_id?}"""
    _check(request)
    b = await request.json()
    row = (await db_session.execute(select(BBUCeuLedger).where(
        BBUCeuLedger.id == int(b.get("ledger_id", 0))))).scalars().first()
    if not row:
        raise HTTPException(404, "Ledger entry not found")
    row.approved = True
    row.approved_at = _now()
    db_session.add(row)
    await db_session.commit()
    await svc.maybe_upgrade_on_ceu(db_session, row.org_id, row.user_id)
    total = await svc.approved_ceu_total(db_session, row.org_id, row.user_id)
    return {"approved": True, "ceu_total": total}


@router.post("/renew")
async def renew(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Body: {email, credential_type, org_id?}"""
    _check(request)
    b = await request.json()
    u = await _user_by_email(db_session, b.get("email", ""))
    org_id = int(b.get("org_id", 1))
    ctype = (b.get("credential_type") or "birth").strip().lower()
    cred = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id, BBUCredential.user_id == u.id,
        BBUCredential.credential_type == ctype))).scalars().first()
    if not cred:
        raise HTTPException(404, "Credential not found")
    ok, reason = await svc.renew(db_session, cred)
    total = await svc.approved_ceu_total(db_session, org_id, u.id)
    return {"renewed": ok, "reason": reason, **svc.to_dict(cred, total)}


@router.post("/on-course-complete")
async def on_course_complete(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Course-completion hook. Body: {email, course_uuid, org_id?}. Reads the
    course's certification config to decide issue/CEU/cross-cert."""
    _check(request)
    b = await request.json()
    u = await _user_by_email(db_session, b.get("email", ""))
    org_id = int(b.get("org_id", 1))
    cu = (b.get("course_uuid") or "").strip()
    course = (await db_session.execute(select(Course).where(
        Course.course_uuid == cu))).scalars().first()
    if not course:
        raise HTTPException(404, "Course not found")
    cert = (await db_session.execute(select(Certifications).where(
        Certifications.course_id == course.id))).scalars().first()
    cfg = (cert.config if cert else {}) or {}
    result = await svc.on_course_complete(db_session, org_id, u.id, cu, cfg)
    return result


@router.put("/{credential_id}/directory")
async def set_directory(credential_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    b = await request.json()
    c = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.id == credential_id))).scalars().first()
    if not c:
        raise HTTPException(404, "Credential not found")
    c.directory_opt_in = bool(b.get("opt_in", True))
    c.updated_at = _now()
    db_session.add(c)
    await db_session.commit()
    return {"id": c.id, "directory_opt_in": c.directory_opt_in}


@router.post("/refresh-statuses")
async def refresh_statuses(request: Request, org_id: int = 1,
                           db_session: AsyncSession = Depends(get_db_session)):
    """Recompute stored status for all credentials (lapse/expire the overdue)."""
    _check(request)
    rows = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id))).scalars().all()
    changed = 0
    for c in rows:
        eff = svc.compute_effective_status(c)
        if eff != c.status:
            c.status = eff
            c.updated_at = _now()
            db_session.add(c)
            changed += 1
    if changed:
        await db_session.commit()
    return {"checked": len(rows), "changed": changed}


# --------------------------------------------------------------------------- #
# Public certificate directory (2.4). No admin key — only opt-in credentials that
# are currently valid (provisional or full) are exposed; name + credential only.
# --------------------------------------------------------------------------- #
@router.get("/directory")
async def directory(q: str = "", org_id: int = 1,
                    db_session: AsyncSession = Depends(get_db_session)):
    rows = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id,
        BBUCredential.directory_opt_in == True,  # noqa: E712
    ))).scalars().all()
    uids = [c.user_id for c in rows]
    users = {}
    if uids:
        urows = (await db_session.execute(select(User).where(User.id.in_(uids)))).scalars().all()
        users = {u.id: u for u in urows}
    ql = (q or "").strip().lower()
    out = []
    for c in rows:
        eff = svc.compute_effective_status(c)
        if eff not in ("provisional", "full"):
            continue
        u = users.get(c.user_id)
        name = f"{getattr(u, 'first_name', '')} {getattr(u, 'last_name', '')}".strip() if u else ""
        if ql and ql not in name.lower() and ql not in c.credential_type.lower():
            continue
        label = {"birth": "Certified Birth Doula", "postpartum": "Certified Postpartum Doula"}.get(
            c.credential_type, c.credential_type.title())
        out.append({
            "name": name or "BBU Professional",
            "credential": label,
            "status": eff,
            "awarded": (c.full_effective_at or c.issued_at or "")[:10],
            "valid_through": (c.full_expires_at or c.provisional_expires_at or "")[:10],
        })
    out.sort(key=lambda x: x["name"].lower())
    return {"count": len(out), "results": out}


@router.get("/directory/page", response_class=HTMLResponse)
async def directory_page(org_id: int = 1, db_session: AsyncSession = Depends(get_db_session)):
    data = await directory(q="", org_id=org_id, db_session=db_session)
    rows_html = "".join(
        f"<tr><td>{r['name']}</td><td>{r['credential']}</td>"
        f"<td><span class='badge {r['status']}'>{r['status'].title()}</span></td>"
        f"<td>{r['awarded']}</td><td>{r['valid_through']}</td></tr>"
        for r in data["results"]
    ) or "<tr><td colspan='5' style='text-align:center;color:#8aa'>No public credentials yet.</td></tr>"
    return HTMLResponse(f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Certified Directory · Birth &amp; Baby University</title>
<style>
:root{{--navy:#113d5d;--sky:#7fb2d6;--ink:#1b2733}}
*{{box-sizing:border-box}}body{{margin:0;font-family:'Open Sans',system-ui,sans-serif;color:var(--ink);background:#f5f8fb}}
header{{background:var(--navy);color:#fff;padding:2.4rem 1.2rem;text-align:center}}
header h1{{margin:0 0 .3rem;font-family:'Playfair Display',Georgia,serif;font-weight:700;font-size:1.9rem}}
header p{{margin:0;opacity:.85}}
.wrap{{max-width:900px;margin:1.6rem auto;padding:0 1rem}}
input{{width:100%;padding:.8rem 1rem;border:1px solid #cdd9e5;border-radius:10px;font-size:1rem;margin-bottom:1rem}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(17,61,93,.08)}}
th,td{{padding:.8rem 1rem;text-align:left;border-bottom:1px solid #eef3f8;font-size:.93rem}}
th{{background:#eaf2f9;color:var(--navy);font-weight:600}}
.badge{{padding:.2rem .6rem;border-radius:20px;font-size:.78rem;font-weight:600}}
.badge.full{{background:#dff5e6;color:#1c7a41}}.badge.provisional{{background:#fff2d6;color:#8a6300}}
footer{{text-align:center;color:#8aa;font-size:.8rem;padding:2rem}}
</style></head><body>
<header><h1>Certified Professional Directory</h1><p>Verified Birth &amp; Baby University credential holders</p></header>
<div class=wrap>
<input id=q placeholder="Search by name or credential…" oninput="f()">
<table><thead><tr><th>Name</th><th>Credential</th><th>Status</th><th>Awarded</th><th>Valid through</th></tr></thead>
<tbody id=tb>{rows_html}</tbody></table>
</div>
<footer>Credentials shown are self-verified and current. Birth &amp; Baby University.</footer>
<script>
function f(){{var v=document.getElementById('q').value.toLowerCase();
document.querySelectorAll('#tb tr').forEach(function(r){{
r.style.display = r.innerText.toLowerCase().indexOf(v)>-1 ? '' : 'none';}});}}
</script></body></html>""")


@router.delete("/{credential_id}")
async def delete_credential(credential_id: int, request: Request,
                            db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    c = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.id == credential_id))).scalars().first()
    if not c:
        raise HTTPException(404, "Credential not found")
    await db_session.delete(c)
    await db_session.commit()
    return {"deleted": credential_id}


# Accredible credential tiers -> (credential_type, tier). Anything not listed and
# not in CEU_GROUPS is ignored so an unexpected tier never silently mis-issues.
ACCREDIBLE_GROUPS = {
    "Provisional 1 Year Certified Postpartum Doula": ("postpartum", "provisional"),
    "Certified Postpartum Doula": ("postpartum", "full"),
    "Provisional 1 Year Certified Labor Doula": ("birth", "provisional"),
    "Certified Labor Doula": ("birth", "full"),
}
ACCREDIBLE_CEU_GROUPS = {
    "Breastfeeding for Perinatal Professionals": 3,
    "Newborn Care for Perinatal Professionals": 3,
    "Comfort Measures for Perinatal Professionals": 3,
}


@router.post("/import-accredible")
async def import_accredible(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Backfill real credentials from an Accredible export so migrated doulas keep
    their TRUE issue/expiry dates (the platform's own clock would otherwise restart
    everyone). Body: {items:[{email,name,group_name,issued_on,expired_on}], dry_run?}.

    Per person+type we keep the strongest record (full beats provisional) and use
    its real dates; 'for Perinatal Professionals' rows become CEU ledger entries.
    Idempotent: re-running updates in place and never double-counts CEUs."""
    b = await request.json()
    _check(request)
    org_id = int(b.get("org_id", 1))
    dry = bool(b.get("dry_run", True))
    items = b.get("items") or []

    # 1) collapse to the strongest credential per (email, credential_type)
    best: dict = {}
    ceu_rows, skipped_groups = [], {}
    for it in items:
        email = (it.get("email") or "").strip().lower()
        grp = (it.get("group_name") or "").strip()
        if not email:
            continue
        if grp in ACCREDIBLE_CEU_GROUPS:
            ceu_rows.append((email, grp, it))
            continue
        mapped = ACCREDIBLE_GROUPS.get(grp)
        if not mapped:
            skipped_groups[grp] = skipped_groups.get(grp, 0) + 1
            continue
        ctype, tier = mapped
        key = (email, ctype)
        cur = best.get(key)
        # full outranks provisional; within a tier keep the most recently issued
        rank = 1 if tier == "full" else 0
        if not cur or rank > cur["rank"] or (rank == cur["rank"] and
                                             (it.get("issued_on") or "") > (cur["it"].get("issued_on") or "")):
            best[key] = {"rank": rank, "tier": tier, "ctype": ctype, "it": it}

    created = updated = unmatched = ceu_awarded = 0
    unmatched_emails = []
    for (email, ctype), rec in best.items():
        user = (await db_session.execute(select(User).where(User.email == email))).scalars().first()
        if not user:
            unmatched += 1
            if len(unmatched_emails) < 25:
                unmatched_emails.append(email)
            continue
        if dry:
            continue
        it, tier = rec["it"], rec["tier"]
        issued, expires = (it.get("issued_on") or ""), (it.get("expired_on") or "")
        cred = (await db_session.execute(select(BBUCredential).where(
            BBUCredential.org_id == org_id, BBUCredential.user_id == user.id,
            BBUCredential.credential_type == ctype))).scalars().first()
        if not cred:
            cred = BBUCredential(org_id=org_id, user_id=user.id, credential_type=ctype)
            created += 1
        else:
            updated += 1
        cred.issued_at = issued
        cred.source = "accredible"
        cred.source_ref = str(it.get("id") or "")
        if tier == "full":
            cred.status = "full"
            cred.full_effective_at = issued
            cred.full_expires_at = expires
            cred.provisional_expires_at = ""
        else:
            cred.status = "provisional"
            cred.provisional_expires_at = expires
            cred.full_effective_at = ""
            cred.full_expires_at = ""
        cred.updated_at = svc._now()
        db_session.add(cred)

    # 2) CEU-bearing professional courses -> ledger (idempotent per accredible id)
    for email, grp, it in ceu_rows:
        user = (await db_session.execute(select(User).where(User.email == email))).scalars().first()
        if not user:
            continue
        if dry:
            ceu_awarded += 1
            continue
        await svc.award_ceu(db_session, org_id, user.id, ACCREDIBLE_CEU_GROUPS[grp],
                            source="course", source_ref=f"accredible:{it.get('id')}")
        ceu_awarded += 1

    if not dry:
        await db_session.commit()
    return {"dry_run": dry, "input_rows": len(items),
            "people_with_credentials": len(best),
            "created": created, "updated": updated,
            "unmatched_users": unmatched, "unmatched_sample": unmatched_emails,
            "ceu_rows": len(ceu_rows), "ceu_awarded": ceu_awarded,
            "skipped_groups": skipped_groups}


@router.post("/run-reminders")
async def run_reminders(request: Request, org_id: int = 1,
                        db_session: AsyncSession = Depends(get_db_session)):
    """Scheduled reminder job (call daily via cron). For each credential entering
    a pre-expiry window (180/90/60/45/30d) it hasn't been reminded for yet, push
    the status + expiry onto the GHL contact (fields bbu__certification_status /
    _expires) so a GHL workflow can send the reminder. Idempotent per window via
    last_reminder_days. Body: {dry_run?}. Fail-soft on GHL per contact."""
    _check(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await svc.run_reminders(db_session, org_id, dry=bool(body.get("dry_run")))


@router.get("/reminders/due")
async def reminders_due(request: Request, org_id: int = 1,
                        db_session: AsyncSession = Depends(get_db_session)):
    """Which credentials fall within a reminder window (days-to-expiry near a
    REMINDER_DAYS mark, ±3 days). The scheduled job reads this then emails via
    GHL/SMTP. Read-only — safe to call from cron without side effects."""
    _check(request)
    now = svc._now_dt()
    rows = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id))).scalars().all()
    due = []
    for c in rows:
        eff = svc.compute_effective_status(c)
        exp = svc._parse(c.full_expires_at if eff == "full" else c.provisional_expires_at)
        if not exp or eff in ("lapsed", "expired"):
            continue
        days = (exp - now).days
        for mark in REMINDER_DAYS:
            if abs(days - mark) <= 3:
                due.append({"credential_id": c.id, "user_id": c.user_id,
                            "credential_type": c.credential_type, "status": eff,
                            "days_to_expiry": days, "mark": mark})
                break
    return {"count": len(due), "due": due}


@router.get("/directory/stats")
async def directory_stats(request: Request, org_id: int = 1,
                          db_session: AsyncSession = Depends(get_db_session)):
    """Diagnose why the public directory is empty: how many credentials exist,
    how many are opted in, and how many pass the effective-status filter."""
    _check(request)
    rows = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id))).scalars().all()
    by_status, by_type = {}, {}
    opted = eligible = listed = 0
    for c in rows:
        eff = svc.compute_effective_status(c)
        by_status[eff] = by_status.get(eff, 0) + 1
        by_type[c.credential_type] = by_type.get(c.credential_type, 0) + 1
        if c.directory_opt_in:
            opted += 1
        if eff in ("provisional", "full"):
            eligible += 1
            if c.directory_opt_in:
                listed += 1
    return {"total_credentials": len(rows), "opted_in": opted,
            "eligible_by_status": eligible, "currently_listed": listed,
            "by_effective_status": by_status, "by_type": by_type}


@router.post("/directory/bulk-opt-in")
async def directory_bulk_opt_in(request: Request,
                                db_session: AsyncSession = Depends(get_db_session)):
    """Opt credentials into the public directory in bulk. `directory_opt_in`
    defaults to False, so imported/auto-issued credentials never appeared in the
    public directory. Body: {org_id?, only_active?, opt_in?, dry_run?}.
    DRY-RUN by default."""
    _check(request)
    b = {}
    try:
        b = await request.json()
    except Exception:
        pass
    org_id = int(b.get("org_id") or 1)
    only_active = str(b.get("only_active", True)).lower() != "false"
    opt_in = str(b.get("opt_in", True)).lower() != "false"
    dry_run = str(b.get("dry_run", True)).lower() != "false"
    rows = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id))).scalars().all()
    changed = 0
    for c in rows:
        if only_active and svc.compute_effective_status(c) not in ("provisional", "full"):
            continue
        if bool(c.directory_opt_in) == opt_in:
            continue
        changed += 1
        if not dry_run:
            c.directory_opt_in = opt_in
            c.updated_at = svc._now()
            db_session.add(c)
    if not dry_run:
        await db_session.commit()
    return {"dry_run": dry_run, "org_id": org_id, "only_active": only_active,
            "opt_in": opt_in, "would_change" if dry_run else "changed": changed,
            "total_scanned": len(rows)}
