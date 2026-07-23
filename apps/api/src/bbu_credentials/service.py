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
    re-fired course completion doesn't double-count."""
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
    if approved:
        await maybe_upgrade_on_ceu(db, org_id, user_id)
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
    if cred:
        if cred.status in ("full", "provisional"):
            return cred          # already active — don't reset the clock
        # lapsed/expired -> re-issue provisional afresh
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
    return cred


async def issue_full_direct(db: AsyncSession, org_id: int, user_id: int,
                            credential_type: str, source: str = "cross_cert",
                            source_ref: str = "") -> BBUCredential:
    """Cross-cert → full (3yr) immediately."""
    cred = await _active_credential(db, org_id, user_id, credential_type)
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
    return cred


async def upgrade_to_full(db: AsyncSession, cred: BBUCredential,
                          effective_at: datetime = None) -> BBUCredential:
    now = effective_at or _now_dt()
    cred.status = "full"
    cred.full_effective_at = now.isoformat()
    cred.full_expires_at = _iso_in_years(FULL_YEARS, now)
    cred.renewal_ceu_baseline = await approved_ceu_total(db, cred.org_id, cred.user_id)
    cred.updated_at = _now()
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    return cred


async def maybe_upgrade_on_ceu(db: AsyncSession, org_id: int, user_id: int):
    """If the user has any provisional credential and >=15 approved CEUs, upgrade."""
    total = await approved_ceu_total(db, org_id, user_id)
    if total < CEU_THRESHOLD:
        return
    creds = (await db.execute(select(BBUCredential).where(
        BBUCredential.org_id == org_id, BBUCredential.user_id == user_id,
        BBUCredential.status == "provisional",
    ))).scalars().all()
    for c in creds:
        await upgrade_to_full(db, c)


async def on_mentorship_completion(db: AsyncSession, org_id: int, user_id: int,
                                   credential_type: str = "", cohort_ref: str = ""):
    """Cohort/mentorship finished → upgrade the user's provisional credential(s)
    to full, effective now. If credential_type is empty/both, upgrade whatever
    provisional credentials the user holds (type derived from prior training)."""
    q = select(BBUCredential).where(
        BBUCredential.org_id == org_id, BBUCredential.user_id == user_id,
        BBUCredential.status == "provisional")
    if credential_type in ("birth", "postpartum"):
        q = q.where(BBUCredential.credential_type == credential_type)
    creds = (await db.execute(q)).scalars().all()
    upgraded = []
    for c in creds:
        await upgrade_to_full(db, c)
        upgraded.append(c)
    return upgraded


async def renew(db: AsyncSession, cred: BBUCredential) -> tuple:
    """Renew a full credential for another 3yr — requires 15 CEUs earned since
    the current full window began (baseline). Returns (ok, reason)."""
    total = await approved_ceu_total(db, cred.org_id, cred.user_id)
    earned = total - int(cred.renewal_ceu_baseline or 0)
    if earned < CEU_THRESHOLD:
        return False, f"Needs {CEU_THRESHOLD} CEUs to renew (has {max(0, earned)})."
    now = _now_dt()
    cred.status = "full"
    cred.full_effective_at = now.isoformat()
    cred.full_expires_at = _iso_in_years(FULL_YEARS, now)
    cred.renewal_ceu_baseline = total
    cred.updated_at = now.isoformat()
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
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
