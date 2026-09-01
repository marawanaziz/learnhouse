"""BBU people / customer profiles — API. Mounted at /api/v1/bbu/people.

- POST /bbu/people/quiz-submit : learner (session/bearer) — persist a quiz attempt.
- GET  /bbu/people             : admin — searchable roster with rollups.
- GET  /bbu/people/{user_id}   : admin — full customer profile (the drill-down).
"""
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select, func, or_
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.security.auth import get_current_user, resolve_acting_user_id
from src.security.org_auth import is_org_admin
from src.db.users import User, AnonymousUser
from src.db.user_organizations import UserOrganization
from src.db.trail_runs import TrailRun
from src.db.trail_steps import TrailStep
from src.db.courses.courses import Course
from src.db.courses.activities import Activity
from src.db.courses.certifications import CertificateUser, Certifications
from src.bbu_payments.models import BBUOrder
from src.bbu_credentials.models import BBUCredential, BBUCeuLedger
from src.bbu_credentials import applications as credential_app_svc
from src.bbu_cohorts.models import BBUCohort, BBUCohortMember
from src.bbu_people.models import BBUQuizSubmission

router = APIRouter()
ORG = 1
ADMIN_KEY = os.environ.get("BBU_MIGRATION_KEY") or os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _guard(request: Request, db: AsyncSession, user):
    """Admin gate for people/profile reads. Accepts the BBU admin key (header or
    query) OR an org-admin session — the injected `user` carries the bearer token
    the dashboard sends (imperative get_current_user would miss it)."""
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key", "")
    if ADMIN_KEY and key == ADMIN_KEY:
        return
    if user and not isinstance(user, AnonymousUser):
        uid = resolve_acting_user_id(user)
        if uid and await is_org_admin(uid, ORG, db):
            return
    raise HTTPException(403, "Forbidden")


def _fullname(u: User) -> str:
    return f"{getattr(u,'first_name','') or ''} {getattr(u,'last_name','') or ''}".strip() or getattr(u, "username", "")


# ---------------------------------------------------------------- quiz capture
@router.post("/quiz-submit")
async def quiz_submit(request: Request, db_session: AsyncSession = Depends(get_db_session),
                      user=Depends(get_current_user)):
    """Persist a learner's quiz attempt (answers + score). Called by the reader
    when a quiz is submitted. Recomputes correctness server-side from the payload."""
    uid = resolve_acting_user_id(user) if user and not isinstance(user, AnonymousUser) else 0
    if not uid:
        raise HTTPException(401, "Sign in required")
    b = await request.json()
    questions = b.get("questions") or []
    user_answers = b.get("user_answers") or []
    breakdown, correct_count = [], 0
    for q in questions:
        qid = q.get("question_id")
        opts = q.get("answers") or []
        id2text = {a.get("answer_id"): a.get("answer", "") for a in opts}
        correct_ids = {a.get("answer_id") for a in opts if a.get("correct")}
        your_ids = {ua.get("answer_id") for ua in user_answers if ua.get("question_id") == qid}
        is_correct = your_ids == correct_ids and len(correct_ids) > 0
        if is_correct:
            correct_count += 1
        breakdown.append({
            "question": q.get("question", ""),
            "options": [a.get("answer", "") for a in opts],
            "your_answers": [id2text.get(i, "") for i in your_ids],
            "correct_answers": [id2text.get(i, "") for i in correct_ids],
            "is_correct": is_correct,
        })
    total = len(questions)
    score = round(100 * correct_count / total) if total else 0
    passed = total > 0 and correct_count == total
    prev = (await db_session.execute(select(func.count()).select_from(BBUQuizSubmission).where(
        BBUQuizSubmission.user_id == uid,
        BBUQuizSubmission.activity_uuid == (b.get("activity_uuid") or "")))).scalar() or 0
    row = BBUQuizSubmission(
        org_id=ORG, user_id=uid, activity_uuid=(b.get("activity_uuid") or ""),
        course_uuid=(b.get("course_uuid") or ""), activity_name=(b.get("activity_name") or ""),
        score=score, passed=passed, correct_count=correct_count, total_questions=total,
        attempt=int(prev) + 1, answers=breakdown, created_at=_now())
    db_session.add(row)
    await db_session.commit()
    return {"ok": True, "score": score, "passed": passed}


# ------------------------------------------------------ quiz-block scan (scope)
def _walk_quiz_blocks(node, out):
    """Recursively collect blockQuiz nodes from a Tiptap doc."""
    if isinstance(node, dict):
        if node.get("type") == "blockQuiz":
            out.append(node)
        for v in node.values():
            _walk_quiz_blocks(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_quiz_blocks(v, out)


@router.get("/_quiz-scan")
async def quiz_scan(request: Request, db_session: AsyncSession = Depends(get_db_session),
                    user=Depends(get_current_user)):
    """Read-only: count inline quiz blocks + questions per course. Scopes the
    quiz->assignment migration (how many activities/blocks/questions exist)."""
    await _guard(request, db_session, user)
    courses = (await db_session.execute(select(Course).where(Course.org_id == ORG))).scalars().all()
    per_course, tot_act, tot_blocks, tot_q = [], 0, 0, 0
    for c in courses:
        acts = (await db_session.execute(select(Activity).where(Activity.course_id == c.id))).scalars().all()
        c_act = c_blocks = c_q = 0
        for a in acts:
            blocks = []
            _walk_quiz_blocks(a.content or {}, blocks)
            if blocks:
                c_act += 1
                c_blocks += len(blocks)
                for b in blocks:
                    c_q += len((b.get("attrs") or {}).get("questions") or [])
        if c_blocks:
            per_course.append({"course_id": c.id, "course": c.name,
                               "activities_with_quiz": c_act, "quiz_blocks": c_blocks, "questions": c_q})
            tot_act += c_act
            tot_blocks += c_blocks
            tot_q += c_q
    per_course.sort(key=lambda x: -x["quiz_blocks"])
    return {"courses_with_quiz": len(per_course), "total_activities_with_quiz": tot_act,
            "total_quiz_blocks": tot_blocks, "total_questions": tot_q, "per_course": per_course}


# ---------------------------------------------------------------- roster list
@router.get("")
async def people_list(request: Request, q: str = "", limit: int = 25, offset: int = 0,
                      db_session: AsyncSession = Depends(get_db_session),
                      user=Depends(get_current_user)):
    await _guard(request, db_session, user)
    base = select(User).join(UserOrganization, UserOrganization.user_id == User.id).where(
        UserOrganization.org_id == ORG)
    if q.strip():
        like = f"%{q.strip()}%"
        base = base.where(or_(User.email.ilike(like), User.first_name.ilike(like),
                              User.last_name.ilike(like), User.username.ilike(like)))
    total = (await db_session.execute(
        select(func.count()).select_from(base.subquery()))).scalar() or 0
    users = (await db_session.execute(
        base.order_by(User.id.desc()).offset(offset).limit(min(100, limit)))).scalars().all()
    # Published-activity count per course, computed once and reused for every row.
    # A course counts as "completed" when the learner has a completed TrailStep for
    # every published activity — LearnHouse never flips TrailRun.status to COMPLETED,
    # so status is unreliable; step-progress is the real signal (matches the profile).
    act_rows = (await db_session.execute(
        select(Activity.course_id, func.count()).where(
            Activity.published == True).group_by(Activity.course_id))).all()  # noqa: E712
    act_counts = {cid: n for cid, n in act_rows}
    people = []
    for u in users:
        runs = (await db_session.execute(select(TrailRun).where(TrailRun.user_id == u.id))).scalars().all()
        enrolled = len(runs)
        completed = 0
        if runs:
            run_ids = [r.id for r in runs]
            step_rows = (await db_session.execute(
                select(TrailStep.trailrun_id, func.count()).where(
                    TrailStep.trailrun_id.in_(run_ids),
                    TrailStep.complete == True).group_by(TrailStep.trailrun_id))).all()  # noqa: E712
            done_by_run = {rid: n for rid, n in step_rows}
            for r in runs:
                need = act_counts.get(r.course_id, 0)
                if need and done_by_run.get(r.id, 0) >= need:
                    completed += 1
        certs = (await db_session.execute(select(func.count()).select_from(CertificateUser).where(
            CertificateUser.user_id == u.id))).scalar() or 0
        spend = (await db_session.execute(select(func.coalesce(func.sum(BBUOrder.amount_cents), 0)).where(
            BBUOrder.status == "paid", or_(BBUOrder.user_id == u.id, BBUOrder.email == u.email)))).scalar() or 0
        cred = (await db_session.execute(select(BBUCredential).where(
            BBUCredential.user_id == u.id).order_by(BBUCredential.id.desc()))).scalars().first()
        people.append({
            "user_id": u.id, "name": _fullname(u), "email": u.email,
            "enrolled": enrolled, "completed": completed, "certificates": certs,
            "credential": (cred.status if cred else ""),
            "spend": round((spend or 0) / 100, 2),
        })
    return {"total": total, "limit": limit, "offset": offset, "people": people}


# ---------------------------------------------------------------- full profile
@router.get("/{user_id}")
async def profile(user_id: int, request: Request,
                  db_session: AsyncSession = Depends(get_db_session),
                  user=Depends(get_current_user)):
    await _guard(request, db_session, user)
    u = (await db_session.execute(select(User).where(User.id == user_id))).scalars().first()
    if not u:
        raise HTTPException(404, "User not found")

    # --- enrollments + progress ---
    runs = (await db_session.execute(select(TrailRun).where(TrailRun.user_id == user_id))).scalars().all()
    enrollments = []
    for r in runs:
        course = (await db_session.execute(select(Course).where(Course.id == r.course_id))).scalars().first()
        total_acts = (await db_session.execute(select(func.count()).select_from(Activity).where(
            Activity.course_id == r.course_id, Activity.published == True))).scalar() or 0  # noqa: E712
        done = (await db_session.execute(select(func.count()).select_from(TrailStep).where(
            TrailStep.trailrun_id == r.id, TrailStep.complete == True))).scalar() or 0  # noqa: E712
        cert_ids = (await db_session.execute(select(Certifications.id).where(
            Certifications.course_id == r.course_id))).scalars().all()
        cert = None
        if cert_ids:
            cert = (await db_session.execute(select(CertificateUser).where(
                CertificateUser.user_id == user_id,
                CertificateUser.certification_id.in_(list(cert_ids))))).scalars().first()
        pct = (round(100 * done / total_acts) if total_acts else 0)
        # LearnHouse leaves TrailRun.status at In_Progress even at 100%, so derive a
        # truthful display status from actual step-progress (matches the roster count).
        disp_status = "Completed" if (total_acts and done >= total_acts) else (
            "In Progress" if done else "Not Started")
        enrollments.append({
            "course": (course.name if course else f"course {r.course_id}"),
            "course_uuid": (course.course_uuid if course else ""),
            "status": disp_status,
            "completed_steps": int(done), "total_steps": int(total_acts),
            "progress": pct,
            "has_certificate": bool(cert),
        })

    # --- quiz results (latest attempt per activity, with the answer breakdown) ---
    qsubs = (await db_session.execute(select(BBUQuizSubmission).where(
        BBUQuizSubmission.user_id == user_id).order_by(BBUQuizSubmission.id.desc()))).scalars().all()
    seen, quizzes = set(), []
    for s in qsubs:
        if s.activity_uuid in seen:
            continue
        seen.add(s.activity_uuid)
        quizzes.append({
            "activity": s.activity_name or s.activity_uuid, "score": s.score, "passed": s.passed,
            "correct": s.correct_count, "total": s.total_questions, "attempts": s.attempt,
            "date": (s.created_at or "")[:10], "answers": s.answers or [],
        })

    # --- certificates ---
    cert_rows = (await db_session.execute(select(CertificateUser).where(
        CertificateUser.user_id == user_id))).scalars().all()
    certificates = []
    for c in cert_rows:
        cdef = (await db_session.execute(select(Certifications).where(
            Certifications.id == c.certification_id))).scalars().first()
        course = None
        if cdef:
            course = (await db_session.execute(select(Course).where(Course.id == cdef.course_id))).scalars().first()
        # uuid is what makes the row openable -- without it the profile can only
        # print the course name, which is what Anna hit on the Jul 24 walkthrough
        # ("she could just click on those certificates, right?").
        certificates.append({"course": (course.name if course else "Certificate"),
                             "issued": (getattr(c, "created_at", "") or "")[:10],
                             "uuid": c.user_certification_uuid,
                             # /certificates/{id}/verify -- NOT /orgs/{slug}/...
                             # The page lives under an (withmenu) route group, which
                             # is a Next.js layout grouping and contributes no URL
                             # segment. Verified against the live app: the /orgs form
                             # 404s.
                             "verify_url": f"/certificates/{c.user_certification_uuid}/verify"})

    # --- credentials + CEU ---
    creds = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == ORG, BBUCredential.user_id == user_id))).scalars().all()
    ceu_total = (await db_session.execute(select(func.coalesce(func.sum(BBUCeuLedger.ceu_count), 0)).where(
        BBUCeuLedger.org_id == ORG, BBUCeuLedger.user_id == user_id, BBUCeuLedger.approved == True))).scalar() or 0  # noqa: E712
    credentials = [{
        "type": c.credential_type, "status": c.status,
        "issued": (c.full_effective_at or c.issued_at or "")[:10],
        "expires": (c.full_expires_at or c.provisional_expires_at or "")[:10],
    } for c in creds]
    credential_issuances = credential_app_svc.issuance_history_to_dicts(
        await credential_app_svc.list_user_issuances(db_session, ORG, user_id)
    )

    # --- cohorts ---
    cms = (await db_session.execute(select(BBUCohortMember).where(
        BBUCohortMember.user_id == user_id))).scalars().all()
    cohorts = []
    for m in cms:
        co = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == m.cohort_id))).scalars().first()
        cohorts.append({"cohort": (co.name if co else f"cohort {m.cohort_id}"), "status": m.status})

    # --- purchases ---
    orders = (await db_session.execute(select(BBUOrder).where(
        or_(BBUOrder.user_id == user_id, BBUOrder.email == u.email)).order_by(BBUOrder.id.desc()))).scalars().all()
    purchases = [{
        "amount": round((o.amount_cents or 0) / 100, 2), "status": o.status,
        "date": (o.paid_at or o.created_at or "")[:10],
    } for o in orders]

    return {
        "user_id": u.id, "name": _fullname(u), "email": u.email,
        "username": getattr(u, "username", ""),
        "ceu_total": int(ceu_total),
        "lifetime_spend": round(sum((o.amount_cents or 0) for o in orders if o.status == "paid") / 100, 2),
        "enrollments": enrollments, "quizzes": quizzes, "certificates": certificates,
        "credentials": credentials, "credential_issuances": credential_issuances,
        "cohorts": cohorts, "purchases": purchases,
    }
