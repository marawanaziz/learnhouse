"""BBU credentials — state machine + CEU ledger logic. Clean-room.

All rules are constants here (not hard-coded across call sites) so they can be
tuned in one place: 1-year provisional window, 3-year full window, 15-CEU upgrade
& renewal threshold.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.bbu_credentials.models import BBUCredential, BBUCeuLedger

PROVISIONAL_YEARS = 1
FULL_YEARS = 3
CROSS_CERT_YEARS = 3
CEU_THRESHOLD = 15
REMINDER_DAYS = [180, 90, 60, 45, 30]  # pre-expiry reminder windows


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _parse(s: str):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _add_years(dt: datetime, years: int) -> datetime:
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:            # Feb 29 -> Feb 28
        return dt.replace(year=dt.year + years, day=28)


def _iso_in_years(years: int, base: datetime = None) -> str:
    return _add_years(base or _now_dt(), years).isoformat()


# --------------------------------------------------------------------------- #
# CEU ledger
# --------------------------------------------------------------------------- #
async def approved_ceu_total(db: AsyncSession, org_id: int, user_id: int) -> int:
    rows = (await db.execute(select(BBUCeuLedger).where(
        BBUCeuLedger.org_id == org_id, BBUCeuLedger.user_id == user_id,
        BBUCeuLedger.approved == True,  # noqa: E712
    ))).scalars().all()
    return sum(int(r.ceu_count or 0) for r in rows)


async def award_ceu(db: AsyncSession, org_id: int, user_id: int, count: int,
                    source: str = "course", source_ref: str = "",
                    approved: bool = True) -> BBUCeuLedger:
    """Add CEUs. Idempotent per (user, source_ref) when source_ref is set so a
    re-fired course completion doesn't double-count.

    Recording CEUs deliberately does *not* change a professional credential.
    A credential transition requires an approved CEU application, mentorship
    completion, a configured course rule, or an explicit audited admin action.
    """
    if source_ref:
        existing = (await db.execute(select(BBUCeuLedger).where(
            BBUCeuLedger.org_id == org_id, BBUCeuLedger.user_id == user_id,
            BBUCeuLedger.source_ref == source_ref,
        ))).scalars().first()
        if existing:
            return existing
    row = BBUCeuLedger(org_id=org_id, user_id=user_id, ceu_count=int(count),
                       source=source, source_ref=source_ref, approved=approved,
                       submitted_at=_now(), approved_at=_now() if approved else "")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# --------------------------------------------------------------------------- #
# Credential lifecycle
# --------------------------------------------------------------------------- #
async def _active_credential(db: AsyncSession, org_id: int, user_id: int,
                             credential_type: str):
    return (await db.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id, BBUCredential.user_id == user_id,
        BBUCredential.credential_type == credential_type,
    ))).scalars().first()


async def issue_provisional(db: AsyncSession, org_id: int, user_id: int,
                            credential_type: str, source_ref: str = "") -> BBUCredential:
    """Training complete → provisional credential (1yr). Idempotent per type:
    never downgrades an existing full credential."""
    cred = await _active_credential(db, org_id, user_id, credential_type)
    now = _now_dt()
    prior = None
    from src.bbu_credentials import applications as app_svc

    if cred:
        if cred.status in ("full", "provisional"):
            # Imported/pre-history credentials still need one immutable
            # issuance, but an idempotent course hook must not make duplicates.
            from src.bbu_credentials.models import BBUCredentialIssuance
            existing_history = (await db.execute(select(BBUCredentialIssuance).where(
                BBUCredentialIssuance.org_id == org_id,
                BBUCredentialIssuance.user_id == user_id,
                BBUCredentialIssuance.credential_type == credential_type,
            ))).scalars().first()
            if not existing_history:
                await app_svc.reconcile_legacy_credential(db, cred)
            return cred          # already active — don't reset the clock
        # lapsed/expired -> re-issue provisional afresh
        prior = await app_svc.reconcile_legacy_credential(db, cred)
        cred.status = "provisional"
        cred.issued_at = now.isoformat()
        cred.provisional_expires_at = _iso_in_years(PROVISIONAL_YEARS, now)
        cred.full_effective_at = ""
        cred.full_expires_at = ""
        cred.source = "training"
        cred.source_ref = source_ref
        cred.updated_at = now.isoformat()
    else:
        cred = BBUCredential(
            org_id=org_id, user_id=user_id, credential_type=credential_type,
            status="provisional", issued_at=now.isoformat(),
            provisional_expires_at=_iso_in_years(PROVISIONAL_YEARS, now),
            source="training", source_ref=source_ref, updated_at=now.isoformat())
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    await app_svc.create_issuance(
        db, org_id=org_id, user_id=user_id, credential_type=credential_type,
        credential_level="one_year_provisional", effective_at=cred.issued_at,
        expires_at=cred.provisional_expires_at, source="training",
        source_ref=f"{source_ref or 'credential'}:{cred.issued_at}",
        supersedes_issuance_id=prior.id if prior else None,
    )
    return cred


async def issue_full_direct(db: AsyncSession, org_id: int, user_id: int,
                            credential_type: str, source: str = "cross_cert",
                            source_ref: str = "") -> BBUCredential:
    """Cross-cert → full (3yr) immediately."""
    from src.bbu_credentials.models import BBUCredentialIssuance
    if source_ref:
        already_issued = (await db.execute(select(BBUCredentialIssuance).where(
            BBUCredentialIssuance.org_id == org_id,
            BBUCredentialIssuance.user_id == user_id,
            BBUCredentialIssuance.credential_type == credential_type,
            BBUCredentialIssuance.source == source,
            BBUCredentialIssuance.source_ref == source_ref,
        ))).scalars().first()
        if already_issued:
            existing_cred = await _active_credential(
                db, org_id, user_id, credential_type)
            if existing_cred:
                return existing_cred
    cred = await _active_credential(db, org_id, user_id, credential_type)
    from src.bbu_credentials import applications as app_svc
    prior = None
    if cred:
        existing_history = (await db.execute(select(BBUCredentialIssuance).where(
            BBUCredentialIssuance.org_id == org_id,
            BBUCredentialIssuance.user_id == user_id,
            BBUCredentialIssuance.credential_type == credential_type,
        ))).scalars().all()
        if existing_history:
            prior = max(existing_history, key=lambda row: row.id or 0)
        elif (cred.source or "") == source and (cred.source_ref or "") == source_ref:
            # The current row already represents this exact event; copy its
            # original dates instead of restarting the clock.
            await app_svc.reconcile_legacy_credential(db, cred)
            return cred
        else:
            prior = await app_svc.reconcile_legacy_credential(db, cred)
    now = _now_dt()
    if not cred:
        cred = BBUCredential(org_id=org_id, user_id=user_id,
                             credential_type=credential_type)
    cred.status = "full"
    if not cred.issued_at:
        cred.issued_at = now.isoformat()
    cred.full_effective_at = now.isoformat()
    cred.full_expires_at = _iso_in_years(CROSS_CERT_YEARS, now)
    cred.source = source
    cred.source_ref = source_ref
    cred.renewal_ceu_baseline = await approved_ceu_total(db, org_id, user_id)
    cred.updated_at = now.isoformat()
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    await app_svc.create_issuance(
        db, org_id=org_id, user_id=user_id, credential_type=credential_type,
        credential_level="three_year_full", effective_at=cred.full_effective_at,
        expires_at=cred.full_expires_at, source=source,
        source_ref=source_ref or f"credential:{cred.id}:{cred.full_effective_at}",
        supersedes_issuance_id=prior.id if prior else None,
        directory_opt_in=bool(cred.directory_opt_in),
    )
    return cred


async def upgrade_to_full(db: AsyncSession, cred: BBUCredential,
                          effective_at: datetime = None,
                          source: str = "mentorship",
                          source_ref: str = "") -> BBUCredential:
    from src.bbu_credentials import applications as app_svc
    from src.bbu_credentials.models import BBUCredentialIssuance
    history = (await db.execute(select(BBUCredentialIssuance).where(
        BBUCredentialIssuance.org_id == cred.org_id,
        BBUCredentialIssuance.user_id == cred.user_id,
        BBUCredentialIssuance.credential_type == cred.credential_type,
    ))).scalars().all()
    prior = (max(history, key=lambda row: row.id or 0)
             if history else await app_svc.reconcile_legacy_credential(db, cred))
    now = effective_at or _now_dt()
    cred.status = "full"
    cred.full_effective_at = now.isoformat()
    cred.full_expires_at = _iso_in_years(FULL_YEARS, now)
    cred.renewal_ceu_baseline = await approved_ceu_total(db, cred.org_id, cred.user_id)
    cred.updated_at = _now()
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    await app_svc.create_issuance(
        db, org_id=cred.org_id, user_id=cred.user_id,
        credential_type=cred.credential_type,
        credential_level="three_year_full", effective_at=cred.full_effective_at,
        expires_at=cred.full_expires_at, source=source,
        source_ref=source_ref or f"credential:{cred.id}:{cred.full_effective_at}",
        supersedes_issuance_id=prior.id if prior else None,
        directory_opt_in=bool(cred.directory_opt_in),
    )
    return cred


async def maybe_upgrade_on_ceu(db: AsyncSession, org_id: int, user_id: int):
    """Compatibility no-op.

    Older hooks called this after adding a CEU ledger row. The approved client
    workflow now requires an application and explicit admin decision, so a
    ledger total alone must never issue a credential.
    """
    return []


async def on_mentorship_completion(db: AsyncSession, org_id: int, user_id: int,
                                   credential_type: str = "", cohort_ref: str = "",
                                   effective_at=None):
    """Cohort/mentorship finished → upgrade the user's provisional credential(s)
    to full. Per BBU rule the 3-year full cert is **effective-dated to the
    cohort's LAST DAY** (pass effective_at = cohort.end_date), not the day the
    admin marks completion; falls back to now if none given. If credential_type
    is empty/both, upgrade whatever provisional credentials the user holds (type
    derived from their prior training)."""
    # accept an ISO date/datetime string or a datetime
    if isinstance(effective_at, str):
        effective_at = _parse(effective_at)
    q = select(BBUCredential).where(
        BBUCredential.org_id == org_id, BBUCredential.user_id == user_id,
        BBUCredential.status == "provisional")
    if credential_type in ("birth", "postpartum"):
        q = q.where(BBUCredential.credential_type == credential_type)
    creds = (await db.execute(q)).scalars().all()
    upgraded = []
    for c in creds:
        await upgrade_to_full(
            db, c, effective_at=effective_at, source="mentorship",
            source_ref=cohort_ref or f"mentorship:{c.id}:{effective_at or _now()}")
        upgraded.append(c)
    return upgraded


async def renew(db: AsyncSession, cred: BBUCredential) -> tuple:
    """Renew a full credential for another 3yr — requires 15 CEUs earned since
    the current full window began (baseline). Returns (ok, reason)."""
    total = await approved_ceu_total(db, cred.org_id, cred.user_id)
    earned = total - int(cred.renewal_ceu_baseline or 0)
    if earned < CEU_THRESHOLD:
        return False, f"Needs {CEU_THRESHOLD} CEUs to renew (has {max(0, earned)})."
    from src.bbu_credentials import applications as app_svc
    from src.bbu_credentials.models import BBUCredentialIssuance
    history = (await db.execute(select(BBUCredentialIssuance).where(
        BBUCredentialIssuance.org_id == cred.org_id,
        BBUCredentialIssuance.user_id == cred.user_id,
        BBUCredentialIssuance.credential_type == cred.credential_type,
    ))).scalars().all()
    prior = (max(history, key=lambda row: row.id or 0)
             if history else await app_svc.reconcile_legacy_credential(db, cred))
    now = _now_dt()
    cred.status = "full"
    cred.full_effective_at = now.isoformat()
    cred.full_expires_at = _iso_in_years(FULL_YEARS, now)
    cred.renewal_ceu_baseline = total
    cred.updated_at = now.isoformat()
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    await app_svc.create_issuance(
        db, org_id=cred.org_id, user_id=cred.user_id,
        credential_type=cred.credential_type,
        credential_level="three_year_full", effective_at=cred.full_effective_at,
        expires_at=cred.full_expires_at, source="manual_renewal",
        source_ref=f"credential:{cred.id}:{cred.full_effective_at}",
        supersedes_issuance_id=prior.id if prior else None,
        directory_opt_in=bool(cred.directory_opt_in),
    )
    return True, ""


def compute_effective_status(cred: BBUCredential) -> str:
    """Pure: what the status SHOULD be given the clock (no DB write)."""
    now = _now_dt()
    if cred.status == "provisional":
        exp = _parse(cred.provisional_expires_at)
        if exp and exp < now:
            return "lapsed"
        return "provisional"
    if cred.status == "full":
        exp = _parse(cred.full_expires_at)
        if exp and exp < now:
            return "expired"
        return "full"
    return cred.status


async def refresh_status(db: AsyncSession, cred: BBUCredential) -> BBUCredential:
    eff = compute_effective_status(cred)
    if eff != cred.status:
        cred.status = eff
        cred.updated_at = _now()
        db.add(cred)
        await db.commit()
        await db.refresh(cred)
    return cred


def to_dict(cred: BBUCredential, ceu_total: int = None) -> dict:
    d = {
        "id": cred.id,
        "user_id": cred.user_id,
        "credential_type": cred.credential_type,
        "status": compute_effective_status(cred),
        "stored_status": cred.status,
        "issued_at": cred.issued_at,
        "provisional_expires_at": cred.provisional_expires_at,
        "full_effective_at": cred.full_effective_at,
        "full_expires_at": cred.full_expires_at,
        "source": cred.source,
        "directory_opt_in": bool(cred.directory_opt_in),
    }
    if ceu_total is not None:
        d["ceu_total"] = ceu_total
        d["ceu_toward_renewal"] = max(0, ceu_total - int(cred.renewal_ceu_baseline or 0))
    return d


# --------------------------------------------------------------------------- #
# Course-completion entry point — reads the course's cert config to decide what
# to do (issue/CEU/cross-cert). Config flags live on Certifications.config:
#   bbu_credential_type: "birth"|"postpartum"|""   (which credential a training grants)
#   bbu_is_cross_cert:   bool                       (issue full directly)
#   bbu_ceu_value:       int                        (CEUs awarded on completion)
# --------------------------------------------------------------------------- #
async def run_reminders(db: AsyncSession, org_id: int = 1, dry: bool = False) -> dict:
    """Flag credentials entering a pre-expiry reminder window they haven't been
    reminded for, and push status+expiry onto the GHL contact so a workflow can
    send the reminder. Idempotent per window (last_reminder_days). Fail-soft on
    GHL. Callable from the API endpoint AND the in-process daily scheduler."""
    from src.db.users import User
    now = _now_dt()
    rows = (await db.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id))).scalars().all()
    pending = []
    for c in rows:
        eff = compute_effective_status(c)
        if eff not in ("provisional", "full"):
            continue
        exp = _parse(c.full_expires_at if eff == "full" else c.provisional_expires_at)
        if not exp:
            continue
        days = (exp - now).days
        if days < 0 or days > max(REMINDER_DAYS):
            continue
        window = min(m for m in REMINDER_DAYS if days <= m)
        if window == (c.last_reminder_days or 0):
            continue
        pending.append((c, eff, exp, days, window))

    if dry:
        return {"dry_run": True, "would_fire": len(pending),
                "due": [{"credential_id": c.id, "user_id": c.user_id,
                         "credential_type": c.credential_type,
                         "days_to_expiry": days, "window": window}
                        for (c, eff, exp, days, window) in pending]}

    from src.bbu_ghl.client import GHLClient, is_configured
    ghl_ok = is_configured()
    ghl = GHLClient() if ghl_ok else None
    if ghl:
        await ghl.__aenter__()
    fired = []
    try:
        for (c, eff, exp, days, window) in pending:
            entry = {"credential_id": c.id, "credential_type": c.credential_type,
                     "window": window, "pushed": False}
            if ghl:
                u = (await db.execute(select(User).where(
                    User.id == c.user_id))).scalars().first()
                if u and u.email:
                    label = f"{eff.title()} · renew within {window} days"
                    try:
                        await ghl.upsert_contact(u.email, fields={
                            "bbu__certification_status": label,
                            "bbu__certification_expires": exp.date().isoformat(),
                        })
                        entry["pushed"] = True
                    except Exception as e:
                        entry["push_error"] = str(e)[:100]
            # Only mark the window done once the reminder actually went out, so a
            # transient GHL failure (or a run before GHL is configured) retries
            # next time instead of silently dropping the reminder.
            if entry["pushed"]:
                c.last_reminder_days = window
                c.updated_at = _now()
                db.add(c)
            fired.append(entry)
        await db.commit()
    finally:
        if ghl:
            await ghl.__aexit__(None, None, None)
    return {"dry_run": False,
            "fired": sum(1 for e in fired if e.get("pushed")),
            "processed": len(fired), "ghl_configured": ghl_ok,
            "results": fired}


async def on_course_complete(db: AsyncSession, org_id: int, user_id: int,
                             course_uuid: str, cert_config: dict) -> dict:
    cfg = cert_config or {}
    ctype = (cfg.get("bbu_credential_type") or "").strip().lower()
    is_cross = bool(cfg.get("bbu_is_cross_cert"))
    ceu_value = int(cfg.get("bbu_ceu_value") or 0)
    actions = []
    if ceu_value > 0:
        await award_ceu(db, org_id, user_id, ceu_value, source="course",
                        source_ref=f"{course_uuid}:{user_id}")
        actions.append(f"+{ceu_value} CEU")
    if ctype in ("birth", "postpartum"):
        if is_cross:
            await issue_full_direct(db, org_id, user_id, ctype,
                                    source="cross_cert", source_ref=course_uuid)
            actions.append(f"{ctype} full (cross-cert)")
        else:
            await issue_provisional(db, org_id, user_id, ctype, source_ref=course_uuid)
            actions.append(f"{ctype} provisional")
    return {"actions": actions}
