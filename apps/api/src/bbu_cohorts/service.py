"""BBU cohorts — enrollment / lifecycle logic. Clean-room.

Access is granted via a native usergroup linked to the cohort's course (same
mechanism as course-gating). Completing a cohort calls the credentials engine to
upgrade the member's provisional credential to full.
"""
import calendar
import json
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.usergroups import UserGroup
from src.db.usergroup_user import UserGroupUser
from src.db.usergroup_resources import UserGroupResource
from src.bbu_cohorts.models import BBUCohort, BBUCohortMember, BBUCohortWaitlist
from src.bbu_cohorts import templates


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _add_months_iso(date_str: str, months: int) -> str:
    """date_str (ISO, may carry time) + N months → ISO date. Clamps day to the
    target month's length. Returns '' if unparseable."""
    s = (date_str or "")[:10]
    try:
        d = date.fromisoformat(s)
    except Exception:
        return ""
    m = d.month - 1 + int(months or 0)
    y = d.year + m // 12
    mo = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, mo)[1])
    return date(y, mo, day).isoformat()


async def ensure_usergroup(db: AsyncSession, cohort: BBUCohort) -> int:
    """Create (once) the cohort's access usergroup and link its course to it."""
    if cohort.usergroup_id:
        grp = (await db.execute(select(UserGroup).where(
            UserGroup.id == cohort.usergroup_id))).scalars().first()
        if grp:
            await _ensure_course_link(db, grp.id, cohort)
            return grp.id
    grp = UserGroup(org_id=cohort.org_id, name=f"{cohort.name} · Cohort",
                    description=f"cohort:{cohort.id}",
                    usergroup_uuid=f"usergroup_{uuid4()}",
                    creation_date=_now(), update_date=_now())
    db.add(grp)
    await db.commit()
    await db.refresh(grp)
    cohort.usergroup_id = grp.id
    db.add(cohort)
    await db.commit()
    await _ensure_course_link(db, grp.id, cohort)
    return grp.id


async def _ensure_course_link(db: AsyncSession, usergroup_id: int, cohort: BBUCohort):
    if not cohort.course_uuid:
        return
    link = (await db.execute(select(UserGroupResource).where(
        UserGroupResource.usergroup_id == usergroup_id,
        UserGroupResource.resource_uuid == cohort.course_uuid,
    ))).scalars().first()
    if not link:
        db.add(UserGroupResource(usergroup_id=usergroup_id,
                                 resource_uuid=cohort.course_uuid,
                                 org_id=cohort.org_id,
                                 creation_date=_now(), update_date=_now()))
        await db.commit()


async def _in_group(db: AsyncSession, usergroup_id: int, user_id: int) -> bool:
    row = (await db.execute(select(UserGroupUser).where(
        UserGroupUser.usergroup_id == usergroup_id,
        UserGroupUser.user_id == user_id,
    ))).scalars().first()
    return bool(row)


async def _add_to_group(db: AsyncSession, usergroup_id: int, org_id: int, user_id: int):
    if not await _in_group(db, usergroup_id, user_id):
        db.add(UserGroupUser(usergroup_id=usergroup_id, user_id=user_id,
                             org_id=org_id, creation_date=_now(), update_date=_now()))
        await db.commit()


async def _remove_from_group(db: AsyncSession, usergroup_id: int, user_id: int):
    row = (await db.execute(select(UserGroupUser).where(
        UserGroupUser.usergroup_id == usergroup_id,
        UserGroupUser.user_id == user_id,
    ))).scalars().first()
    if row:
        await db.delete(row)
        await db.commit()


async def active_count(db: AsyncSession, cohort_id: int) -> int:
    rows = (await db.execute(select(BBUCohortMember).where(
        BBUCohortMember.cohort_id == cohort_id,
        BBUCohortMember.status == "active",
    ))).scalars().all()
    return len(rows)


async def _member(db: AsyncSession, cohort_id: int, user_id: int):
    return (await db.execute(select(BBUCohortMember).where(
        BBUCohortMember.cohort_id == cohort_id,
        BBUCohortMember.user_id == user_id,
    ))).scalars().first()


async def enroll(db: AsyncSession, cohort: BBUCohort, user_id: int) -> dict:
    """Add a user to the cohort. Honors capacity → waitlist. Grants course access
    for active members. Idempotent."""
    await ensure_usergroup(db, cohort)
    m = await _member(db, cohort.id, user_id)
    at_capacity = cohort.capacity and (await active_count(db, cohort.id)) >= cohort.capacity
    if m and m.status in ("active", "completed"):
        return {"status": m.status, "already": True}
    target = "waitlisted" if at_capacity else "active"
    if m:
        m.status = target
        m.joined_at = m.joined_at or _now()
    else:
        m = BBUCohortMember(org_id=cohort.org_id, cohort_id=cohort.id or 0,
                            user_id=user_id, status=target, joined_at=_now())
    db.add(m)
    await db.commit()
    if target == "active":
        await _add_to_group(db, cohort.usergroup_id, cohort.org_id, user_id)
        await _zoom_register(db, cohort, user_id)
    else:
        # mark cohort full when we start waitlisting
        if cohort.status == "open":
            cohort.status = "full"
            db.add(cohort)
            await db.commit()
    return {"status": target, "already": False}


async def complete(db: AsyncSession, cohort: BBUCohort, user_id: int) -> dict:
    """Mark a member completed and upgrade their credential (mentorship trigger)."""
    m = await _member(db, cohort.id, user_id)
    if not m:
        return {"error": "not a member"}
    m.status = "completed"
    m.completed_at = _now()
    db.add(m)
    await db.commit()
    upgraded = []
    if cohort.credential_type:  # this cohort grants a credential upgrade
        try:
            from src.bbu_credentials import service as cred_svc
            ctype = "" if cohort.credential_type == "both" else cohort.credential_type
            # BBU rule: the 3-yr full cert is effective-dated to the cohort's LAST
            # DAY, not the day the admin marks completion.
            ups = await cred_svc.on_mentorship_completion(
                db, cohort.org_id, user_id, credential_type=ctype,
                cohort_ref=f"cohort:{cohort.id}",
                effective_at=(cohort.end_date or None))
            upgraded = [c.credential_type for c in ups]
        except Exception:
            import traceback
            print(f"[BBU] cohort complete credential upgrade failed:\n{traceback.format_exc()[-500:]}", flush=True)
    return {"completed": True, "credentials_upgraded": upgraded}


async def remove(db: AsyncSession, cohort: BBUCohort, user_id: int) -> dict:
    """Remove a member before completion → revoke access (blocks their cert)."""
    m = await _member(db, cohort.id, user_id)
    if not m:
        return {"error": "not a member"}
    m.status = "removed"
    db.add(m)
    await db.commit()
    if cohort.usergroup_id:
        await _remove_from_group(db, cohort.usergroup_id, user_id)
    # promote the next PAID waitlisted member if there's now room...
    await promote_waitlist(db, cohort)
    # ...then, if a seat is still free, invite the earliest interest-waitlist
    # prospect of this program to come enroll.
    if not cohort.capacity or (await active_count(db, cohort.id)) < cohort.capacity:
        try:
            await notify_waitlist(db, cohort.org_id, cohort.program, 1)
        except Exception:
            pass
    return {"removed": True}


async def promote_waitlist(db: AsyncSession, cohort: BBUCohort):
    if not cohort.capacity:
        return
    while (await active_count(db, cohort.id)) < cohort.capacity:
        nxt = (await db.execute(select(BBUCohortMember).where(
            BBUCohortMember.cohort_id == cohort.id,
            BBUCohortMember.status == "waitlisted",
        ).order_by(BBUCohortMember.id))).scalars().first()
        if not nxt:
            break
        nxt.status = "active"
        db.add(nxt)
        await db.commit()
        await _add_to_group(db, cohort.usergroup_id, cohort.org_id, nxt.user_id)


async def close(db: AsyncSession, cohort: BBUCohort, revoke_access: bool = True) -> dict:
    """Close the cohort: status=closed; optionally revoke all members' access."""
    cohort.status = "closed"
    cohort.updated_at = _now()
    db.add(cohort)
    await db.commit()
    revoked = 0
    if revoke_access and cohort.usergroup_id:
        members = (await db.execute(select(UserGroupUser).where(
            UserGroupUser.usergroup_id == cohort.usergroup_id))).scalars().all()
        for row in members:
            await db.delete(row)
            revoked += 1
        await db.commit()
    return {"closed": True, "access_revoked": revoked}


def provision_defaults(cohort: BBUCohort) -> None:
    """Seed a new cohort from its program template: workbook + weekly prompts.
    Only fills blanks — never clobbers values an admin already set."""
    if not (cohort.workbook_url or "").strip():
        cohort.workbook_url = templates.workbook_for(cohort.program)
    if not (cohort.weekly_prompts or "").strip():
        prompts = templates.prompts_for(cohort.program)
        cohort.weekly_prompts = json.dumps(prompts) if prompts else ""


async def _system_author_id(db: AsyncSession, org_id: int) -> int:
    """A user to attribute auto-posted prompts to: the lowest-id org admin."""
    from src.db.user_organizations import UserOrganization
    from src.security.rbac.constants import ADMIN_OR_MAINTAINER_ROLE_IDS
    row = (await db.execute(select(UserOrganization).where(
        UserOrganization.org_id == org_id,
        UserOrganization.role_id.in_(list(ADMIN_OR_MAINTAINER_ROLE_IDS)),
    ).order_by(UserOrganization.user_id))).scalars().first()
    return row.user_id if row else 0


async def post_due_prompts(db: AsyncSession, cohort: BBUCohort) -> int:
    """Drip the cohort's weekly prompts into its community: post each prompt whose
    week has arrived (start_date + (week-1)*7d <= today) and isn't yet posted.
    Idempotent via each prompt's posted_at. No community / no start / no author →
    no-op. Returns how many were posted this run."""
    if not cohort.community_id or not (cohort.start_date or "").strip():
        return 0
    try:
        prompts = json.loads(cohort.weekly_prompts or "[]")
    except Exception:
        return 0
    if not isinstance(prompts, list) or not prompts:
        return 0
    try:
        start = date.fromisoformat((cohort.start_date or "")[:10])
    except Exception:
        return 0
    today = date.fromisoformat(_today())
    author_id = await _system_author_id(db, cohort.org_id)
    if not author_id:
        return 0

    from src.db.communities.discussions import Discussion
    posted = 0
    for p in prompts:
        if p.get("posted_at"):
            continue
        wk = int(p.get("week", 1) or 1)
        due = start + timedelta(days=(wk - 1) * 7)
        if due > today:
            continue
        d = Discussion(
            title=p.get("title", f"Week {wk}"),
            content=p.get("content", ""),
            label="announcement",
            emoji=p.get("emoji"),
            community_id=cohort.community_id,
            org_id=cohort.org_id,
            author_id=author_id,
            discussion_uuid=f"discussion_{uuid4()}",
            upvote_count=0, is_pinned=True, is_locked=False,
            creation_date=_now(), update_date=_now(),
        )
        db.add(d)
        p["posted_at"] = _now()
        posted += 1
    if posted:
        cohort.weekly_prompts = json.dumps(prompts)
        cohort.updated_at = _now()
        db.add(cohort)
        await db.commit()
    return posted


async def _zoom_register(db: AsyncSession, cohort: BBUCohort, user_id: int) -> None:
    """Fail-soft: register a newly-active member to the cohort's Zoom series."""
    if not (cohort.zoom_meeting_id or "").strip():
        return
    try:
        from src.bbu_zoom import client as zoom
        if not zoom.is_configured():
            return
        from src.db.users import User
        u = (await db.execute(select(User).where(User.id == user_id))).scalars().first()
        if not u or not getattr(u, "email", ""):
            return
        res = await zoom.add_registrant(
            cohort.zoom_meeting_id, u.email,
            getattr(u, "first_name", "") or "", getattr(u, "last_name", "") or "")
        print(f"[BBU] zoom register cohort {cohort.id} user {user_id}: {res}", flush=True)
    except Exception:
        import traceback
        print(f"[BBU] zoom register failed cohort {cohort.id}:\n{traceback.format_exc()[-400:]}", flush=True)


async def sync_recordings(db: AsyncSession, cohort: BBUCohort) -> int:
    """Pull the cohort meeting's cloud recordings and append any new URLs to
    cohort.recordings. Idempotent (skips URLs already stored). Returns # added."""
    if not (cohort.zoom_meeting_id or "").strip():
        return 0
    try:
        from src.bbu_zoom import client as zoom
        if not zoom.is_configured():
            return 0
        urls = await zoom.get_recording_urls(cohort.zoom_meeting_id)
    except Exception:
        return 0
    if not urls:
        return 0
    existing = [r for r in (cohort.recordings or "").split("\n") if r]
    have = set(existing)
    added = [u for u in urls if u not in have]
    if not added:
        return 0
    cohort.recordings = "\n".join(existing + added)
    cohort.updated_at = _now()
    db.add(cohort)
    await db.commit()
    return len(added)


def access_until(cohort: BBUCohort) -> str:
    """The ISO date a cohort's member access is meant to lapse: (end_date, or
    start_date if no end) + access_months. '' when no anchor date is set."""
    anchor = (cohort.end_date or cohort.start_date or "")
    if not anchor or not cohort.access_months:
        return ""
    return _add_months_iso(anchor, cohort.access_months)


async def run_lifecycle(db: AsyncSession, org_id: int, dry: bool = False) -> dict:
    """Idempotent daily bookkeeping over all non-closed cohorts:
      • open/full → 'running' once start_date has passed (so the buy-into-cohort
        resolver stops enrolling new buyers into a class already in progress);
      • past its access window (access_until) → close + revoke access, enforcing
        the 6-/12-month access rule that a completed cohort promises.
    Completion is NEVER automated (dropping before completion = no cert — that's
    a deliberate admin act). Safe to re-run; returns what it changed."""
    today = _today()
    started, expired, prompts_posted, recordings_added = [], [], 0, 0
    cohorts = (await db.execute(select(BBUCohort).where(
        BBUCohort.org_id == org_id, BBUCohort.status != "closed"))).scalars().all()
    for c in cohorts:
        exp = access_until(c)
        if exp and today > exp:
            # access window is over → close and revoke (unless already closed)
            expired.append({"id": c.id, "name": c.name, "access_until": exp})
            if not dry:
                await close(db, c, revoke_access=True)
            continue
        start = (c.start_date or "")[:10]
        if c.status in ("open", "full") and start and start <= today:
            started.append({"id": c.id, "name": c.name, "start_date": start})
            if not dry:
                c.status = "running"
                c.updated_at = _now()
                db.add(c)
                await db.commit()
        # for any live (started, not closed) cohort: drip this week's community
        # prompt + pull any new Zoom recordings
        if not dry:
            try:
                prompts_posted += await post_due_prompts(db, c)
            except Exception:
                import traceback
                print(f"[BBU] prompt drip failed for cohort {c.id}:\n{traceback.format_exc()[-400:]}", flush=True)
            try:
                recordings_added += await sync_recordings(db, c)
            except Exception:
                import traceback
                print(f"[BBU] recording sync failed for cohort {c.id}:\n{traceback.format_exc()[-400:]}", flush=True)
    return {"ran": True, "dry": dry, "started": started, "expired": expired,
            "started_count": len(started), "expired_count": len(expired),
            "prompts_posted": prompts_posted, "recordings_added": recordings_added}


async def resolve_target_cohort(db: AsyncSession, org_id: int, cohort_id=None, program: str = ""):
    """Pick the cohort a purchase should enroll into: a specific cohort_id if the
    product pins one, otherwise the next UPCOMING cohort of the program that still
    has room — capacity limiting with roll-over. If every upcoming cohort is full,
    fall back to the earliest (the buyer waitlists the soonest one)."""
    if cohort_id:
        return (await db.execute(select(BBUCohort).where(
            BBUCohort.id == int(cohort_id), BBUCohort.org_id == org_id))).scalars().first()
    if program:
        rows = (await db.execute(select(BBUCohort).where(
            BBUCohort.org_id == org_id, BBUCohort.program == program,
            BBUCohort.status.in_(["open", "full"]))
        )).scalars().all()
        today = _today()
        # Only enroll into an UPCOMING cohort (start date empty/TBD or in the
        # future). A cohort that has already started keeps its status but should
        # NOT absorb new buyers — that would drop them into a class in progress.
        # An admin can always force a specific cohort by pinning cohort_id.
        upcoming = [c for c in rows if not (c.start_date or "")[:10] or (c.start_date or "")[:10] >= today]
        upcoming.sort(key=lambda c: ((c.start_date or "9999")[:10], c.id))
        if not upcoming:
            return None  # fail-soft: order completes, admin creates the next cohort
        # Prefer the earliest upcoming cohort with a free seat (roll over to the
        # next when one is full); if all are full, waitlist the soonest.
        for c in upcoming:
            if not c.capacity or (await active_count(db, c.id)) < c.capacity:
                return c
        return upcoming[0]
    return None


async def has_open_seat(db: AsyncSession, org_id: int, program: str) -> bool:
    """True if some UPCOMING cohort of the program still has a free active seat
    (or is uncapped). Drives the storefront's buy-vs-waitlist decision."""
    if not program:
        return True
    rows = (await db.execute(select(BBUCohort).where(
        BBUCohort.org_id == org_id, BBUCohort.program == program,
        BBUCohort.status.in_(["open", "full"])))).scalars().all()
    today = _today()
    for c in rows:
        start = (c.start_date or "")[:10]
        if start and start < today:
            continue
        if not c.capacity or (await active_count(db, c.id)) < c.capacity:
            return True
    return False


# --- pre-purchase waitlist (when every upcoming cohort is full) -------------

async def add_to_waitlist(db: AsyncSession, org_id: int, program: str,
                          email: str, name: str = "", phone: str = "",
                          product_id=None) -> dict:
    """Record an interested prospect (idempotent per email+program while waiting)
    and mirror them into GHL so Anna can message them. Fail-soft on the CRM push."""
    email = (email or "").strip().lower()
    if not email:
        return {"ok": False, "error": "email required"}
    existing = (await db.execute(select(BBUCohortWaitlist).where(
        BBUCohortWaitlist.org_id == org_id, BBUCohortWaitlist.program == program,
        BBUCohortWaitlist.email == email,
        BBUCohortWaitlist.status.in_(["waiting", "notified"])))).scalars().first()
    if existing:
        return {"ok": True, "already": True, "position": await waitlist_position(db, org_id, program, existing.id)}
    row = BBUCohortWaitlist(org_id=org_id, program=program, product_id=product_id,
                            email=email, name=(name or "").strip(), phone=(phone or "").strip(),
                            status="waiting", created_at=_now())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await _ghl_waitlist_push(email, name, phone, program, "waiting")
    return {"ok": True, "already": False, "position": await waitlist_position(db, org_id, program, row.id)}


async def waitlist_position(db: AsyncSession, org_id: int, program: str, row_id: int) -> int:
    rows = (await db.execute(select(BBUCohortWaitlist).where(
        BBUCohortWaitlist.org_id == org_id, BBUCohortWaitlist.program == program,
        BBUCohortWaitlist.status == "waiting").order_by(BBUCohortWaitlist.id))).scalars().all()
    for i, r in enumerate(rows, start=1):
        if r.id == row_id:
            return i
    return len(rows) + 1


async def waitlist_count(db: AsyncSession, org_id: int, program: str) -> int:
    rows = (await db.execute(select(BBUCohortWaitlist).where(
        BBUCohortWaitlist.org_id == org_id, BBUCohortWaitlist.program == program,
        BBUCohortWaitlist.status == "waiting"))).scalars().all()
    return len(rows)


async def notify_waitlist(db: AsyncSession, org_id: int, program: str, seats: int) -> list:
    """A spot (or `seats` spots) opened → tell the earliest waiting prospects to
    come enroll. Marks them 'notified' and pushes a GHL status so Anna's workflow
    can email/SMS them. Returns the entries notified."""
    if seats <= 0:
        return []
    rows = (await db.execute(select(BBUCohortWaitlist).where(
        BBUCohortWaitlist.org_id == org_id, BBUCohortWaitlist.program == program,
        BBUCohortWaitlist.status == "waiting").order_by(BBUCohortWaitlist.id).limit(seats))).scalars().all()
    notified = []
    for r in rows:
        r.status = "notified"
        r.notified_at = _now()
        db.add(r)
        await db.commit()
        await _ghl_waitlist_push(r.email, r.name, r.phone, program, "spot_open")
        notified.append(r)
    return notified


async def _ghl_waitlist_push(email: str, name: str, phone: str, program: str, status: str) -> None:
    """Fail-soft: upsert the prospect into GHL with waitlist status fields so a
    CRM workflow can message them. Never breaks the storefront."""
    try:
        from src.bbu_ghl.client import GHLClient, PIT
        if not PIT:
            return
        first, _, last = (name or "").partition(" ")
        async with GHLClient() as g:
            await g.upsert_contact(email, first_name=first, last_name=last, phone=phone, fields={
                "bbu__cohort_waitlist": program,
                "bbu__cohort_waitlist_status": status,
            })
    except Exception:
        import traceback
        print(f"[BBU] waitlist GHL push failed:\n{traceback.format_exc()[-300:]}", flush=True)


async def enroll_from_product(db: AsyncSession, org_id: int, user_id: int,
                              cohort_id=None, program: str = "") -> dict:
    """Called on a paid mentorship purchase: enroll the buyer into the resolved
    cohort (waitlists if full). Fail-soft return so it never breaks fulfillment."""
    cohort = await resolve_target_cohort(db, org_id, cohort_id, program)
    if not cohort:
        return {"enrolled": False, "reason": "no open cohort for program", "program": program}
    res = await enroll(db, cohort, user_id)
    return {"enrolled": True, "cohort_id": cohort.id, "cohort": cohort.name, **res}


async def roster(db: AsyncSession, cohort_id: int) -> list:
    return (await db.execute(select(BBUCohortMember).where(
        BBUCohortMember.cohort_id == cohort_id).order_by(BBUCohortMember.id))).scalars().all()
