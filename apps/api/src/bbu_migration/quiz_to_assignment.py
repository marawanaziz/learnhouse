"""BBU quiz -> native Assignment migration (admin-key gated).

Converts inline `blockQuiz` blocks (Tiptap extension, graded client-side, no
native submission records) into first-class native Assignment activities:

  * a new TYPE_ASSIGNMENT activity is inserted into the same chapter, right
    after its source lesson (reader order preserved by a per-chapter reindex);
  * a native Assignment (PASS_FAIL, auto-graded, retries on) + one QUIZ task
    carrying the same questions/answers is attached to it;
  * the inline quiz block is REMOVED from the source lesson (true replacement,
    no duplicate quiz);
  * CATCH-UP: every learner who already completed the source lesson gets a
    graded-passed submission + a completed TrailStep on the new activity, so
    adding the step does not regress anyone's course completion / certificate.

Idempotent: once a source lesson's quiz block is stripped, a re-run finds no
block there and skips it. Mounted under /api/v1/bbu/migrate.

  POST /quiz-to-assignment  {key, course_id?, dry_run=true, backfill=true, limit?}
"""
import os
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.courses.courses import Course
from src.db.courses.activities import (
    Activity, ActivityTypeEnum, ActivitySubTypeEnum, ActivityLockType,
)
from src.db.courses.chapter_activities import ChapterActivity
from src.db.courses.assignments import (
    Assignment, AssignmentTask, AssignmentTaskTypeEnum, GradingTypeEnum,
    AssignmentUserSubmission, AssignmentUserSubmissionStatus, AssignmentTaskSubmission,
)
from src.db.trails import Trail
from src.db.trail_runs import TrailRun
from src.db.trail_steps import TrailStep

router = APIRouter()

ADMIN_KEY = os.environ.get("BBU_MIGRATION_KEY") or os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")
ORG = 1


def _check(request: Request, body: dict | None = None):
    if not ADMIN_KEY:
        raise HTTPException(503, "Migration key not configured")
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key") \
        or (body or {}).get("key") or ""
    if key != ADMIN_KEY:
        raise HTTPException(403, "Forbidden")


def _now():
    return str(datetime.now())


# ------------------------------------------------------------ content helpers
def _find_quiz_blocks(node, out):
    """Collect blockQuiz nodes anywhere in a Tiptap doc."""
    if isinstance(node, dict):
        if node.get("type") == "blockQuiz":
            out.append(node)
        for v in node.values():
            _find_quiz_blocks(v, out)
    elif isinstance(node, list):
        for v in node:
            _find_quiz_blocks(v, out)


def _strip_quiz_blocks(node):
    """Return a deep copy of the doc with every blockQuiz node removed."""
    if isinstance(node, dict):
        return {k: _strip_quiz_blocks(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_strip_quiz_blocks(v) for v in node if not (
            isinstance(v, dict) and v.get("type") == "blockQuiz")]
    return node


def _to_native_quiz_contents(inline_questions):
    """Map inline blockQuiz questions -> native QUIZ task `contents`.

    inline: {question_id, question, type, answers:[{answer_id, answer, correct}]}
    native: {questions:[{questionText, questionUUID,
             options:[{text, fileID:'', type:'text', assigned_right_answer, optionUUID}]}]}
    """
    out = []
    for q in (inline_questions or []):
        opts = []
        for a in (q.get("answers") or []):
            opts.append({
                "text": a.get("answer", ""),
                "fileID": "",
                "type": "text",
                "assigned_right_answer": bool(a.get("correct")),
                "optionUUID": a.get("answer_id") or ("option_" + str(uuid4())),
            })
        out.append({
            "questionText": q.get("question", ""),
            "questionUUID": q.get("question_id") or ("question_" + str(uuid4())),
            "options": opts,
        })
    return {"questions": out}


def _perfect_submission(native_contents):
    """Build a task_submission that answers every option with its correct value
    (used for the catch-up backfill so already-finished learners read as 100%)."""
    subs = []
    for q in native_contents.get("questions", []):
        for o in q.get("options", []):
            subs.append({
                "questionUUID": q["questionUUID"],
                "optionUUID": o["optionUUID"],
                "answer": bool(o["assigned_right_answer"]),
            })
    return {"submissions": subs}


# -------------------------------------------------------------- the migration
@router.post("/quiz-to-assignment")
async def quiz_to_assignment(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    _check(request, body)

    course_id = body.get("course_id") or request.query_params.get("course_id")
    course_id = int(course_id) if course_id else None
    dry_run = str(body.get("dry_run", request.query_params.get("dry_run", "true"))).lower() != "false"
    backfill = str(body.get("backfill", request.query_params.get("backfill", "true"))).lower() != "false"
    limit = body.get("limit") or request.query_params.get("limit")
    limit = int(limit) if limit else None

    if course_id:
        courses = (await db_session.execute(select(Course).where(
            Course.id == course_id, Course.org_id == ORG))).scalars().all()
    else:
        courses = (await db_session.execute(select(Course).where(Course.org_id == ORG))).scalars().all()

    rep = {"dry_run": dry_run, "backfill": backfill, "courses": [],
           "assignments_created": 0, "questions_migrated": 0,
           "blocks_removed": 0, "backfilled_users": 0, "backfill_steps": 0,
           "errors": []}
    processed = 0

    for course in courses:
        acts = (await db_session.execute(select(Activity).where(
            Activity.course_id == course.id))).scalars().all()
        c_created = c_q = c_bf = 0
        for src in acts:
            blocks = []
            _find_quiz_blocks(src.content or {}, blocks)
            if not blocks:
                continue
            if limit is not None and processed >= limit:
                break
            processed += 1
            try:
                # gather all questions from all quiz blocks in this lesson
                inline_qs = []
                for b in blocks:
                    inline_qs.extend((b.get("attrs") or {}).get("questions") or [])
                native = _to_native_quiz_contents(inline_qs)
                nq = len(native["questions"])

                # locate the source's chapter + link row
                link = (await db_session.execute(select(ChapterActivity).where(
                    ChapterActivity.activity_id == src.id))).scalars().first()
                if not link:
                    rep["errors"].append(f"act {src.id} ({src.name}): no chapter link")
                    continue
                chapter_id = link.chapter_id

                if dry_run:
                    c_created += 1
                    c_q += nq
                    continue

                # 1) new assignment-type activity
                new_act = Activity(
                    name=f"{src.name} — Quiz",
                    activity_type=ActivityTypeEnum.TYPE_ASSIGNMENT,
                    activity_sub_type=ActivitySubTypeEnum.SUBTYPE_ASSIGNMENT_ANY,
                    content={}, details=None, published=src.published,
                    lock_type=getattr(src, "lock_type", ActivityLockType.PUBLIC),
                    org_id=course.org_id, course_id=course.id,
                    activity_uuid=f"activity_{uuid4()}",
                    creation_date=_now(), update_date=_now(),
                )
                db_session.add(new_act)
                await db_session.commit()
                await db_session.refresh(new_act)

                # 2) link into the chapter, then reindex so it sits right after src
                db_session.add(ChapterActivity(
                    order=(link.order or 0), chapter_id=chapter_id, activity_id=new_act.id,
                    course_id=course.id, org_id=course.org_id,
                    creation_date=_now(), update_date=_now(),
                ))
                await db_session.commit()
                await _reindex_chapter(db_session, chapter_id, src.id, new_act.id)

                # 3) Assignment + QUIZ task
                assignment = Assignment(
                    title=f"{src.name} — Quiz",
                    description="Auto-migrated from the lesson quiz. Answer the questions to complete this activity.",
                    due_date="", published=True,
                    grading_type=GradingTypeEnum.PASS_FAIL,
                    auto_grading=True, anti_copy_paste=False,
                    show_correct_answers=True, allow_retries=True, max_retries=0,
                    org_id=course.org_id, course_id=course.id,
                    chapter_id=chapter_id, activity_id=new_act.id,
                    assignment_uuid=f"assignment_{uuid4()}",
                    creation_date=_now(), update_date=_now(),
                )
                db_session.add(assignment)
                await db_session.commit()
                await db_session.refresh(assignment)

                task = AssignmentTask(
                    title="Quiz", description="", hint="",
                    reference_file=None,
                    assignment_type=AssignmentTaskTypeEnum.QUIZ,
                    contents=native, max_grade_value=100,
                    assignment_task_uuid=f"assignmenttask_{uuid4()}",
                    assignment_id=assignment.id, org_id=course.org_id,
                    chapter_id=chapter_id, activity_id=new_act.id, course_id=course.id,
                    creation_date=_now(), update_date=_now(),
                )
                db_session.add(task)
                await db_session.commit()
                await db_session.refresh(task)

                # 4) strip the inline quiz block from the source lesson
                src.content = _strip_quiz_blocks(src.content or {})
                src.update_date = _now()
                db_session.add(src)
                await db_session.commit()
                rep["blocks_removed"] += len(blocks)

                # 5) catch-up backfill for learners who finished the source lesson
                if backfill:
                    users, steps = await _backfill(
                        db_session, course, chapter_id, src.id, new_act.id,
                        assignment, task, native)
                    c_bf += users
                    rep["backfill_steps"] += steps

                c_created += 1
                c_q += nq
            except Exception as e:
                await db_session.rollback()
                rep["errors"].append(f"act {src.id} ({src.name}): {type(e).__name__}: {e}")

        if c_created:
            rep["courses"].append({"course_id": course.id, "course": course.name,
                                   "assignments_created": c_created, "questions": c_q,
                                   "backfilled_users": c_bf})
            rep["assignments_created"] += c_created
            rep["questions_migrated"] += c_q
            rep["backfilled_users"] += c_bf
        if limit is not None and processed >= limit:
            break

    return rep


@router.get("/quiz-to-assignment/verify")
async def quiz_to_assignment_verify(request: Request, course_id: int,
                                    db_session: AsyncSession = Depends(get_db_session)):
    """Read-only inspection of a course's native assignments after migration:
    per-assignment question count, host activity, chapter order position, and
    submission/TrailStep counts. Admin-key gated."""
    _check(request)
    course = (await db_session.execute(select(Course).where(Course.id == course_id))).scalars().first()
    if not course:
        raise HTTPException(404, "course not found")
    assignments = (await db_session.execute(select(Assignment).where(
        Assignment.course_id == course_id))).scalars().all()
    # remaining inline quiz blocks in this course (should be 0 after migration)
    acts = (await db_session.execute(select(Activity).where(Activity.course_id == course_id))).scalars().all()
    remaining_blocks = 0
    for a in acts:
        b = []
        _find_quiz_blocks(a.content or {}, b)
        remaining_blocks += len(b)
    out = []
    for asg in assignments:
        tasks = (await db_session.execute(select(AssignmentTask).where(
            AssignmentTask.assignment_id == asg.id))).scalars().all()
        nq = sum(len((t.contents or {}).get("questions") or []) for t in tasks)
        link = (await db_session.execute(select(ChapterActivity).where(
            ChapterActivity.activity_id == asg.activity_id))).scalars().first()
        subs = (await db_session.execute(select(func.count()).select_from(AssignmentUserSubmission).where(
            AssignmentUserSubmission.assignment_id == asg.id))).scalar() or 0
        steps = (await db_session.execute(select(func.count()).select_from(TrailStep).where(
            TrailStep.activity_id == asg.activity_id, TrailStep.complete == True))).scalar() or 0  # noqa: E712
        out.append({"assignment": asg.title, "activity_id": asg.activity_id,
                    "tasks": len(tasks), "questions": nq, "auto_grading": asg.auto_grading,
                    "grading_type": str(asg.grading_type), "published": asg.published,
                    "chapter_id": link.chapter_id if link else None,
                    "order": link.order if link else None,
                    "user_submissions": subs, "completed_steps": steps})
    return {"course": course.name, "assignments": len(out),
            "remaining_inline_quiz_blocks": remaining_blocks, "detail": out}


async def _reindex_chapter(db: AsyncSession, chapter_id: int, src_act_id: int, new_act_id: int):
    """Re-enumerate a chapter's ChapterActivity.order 0-based, placing new_act
    immediately after src_act (reader sorts by this order)."""
    rows = (await db.execute(select(ChapterActivity).where(
        ChapterActivity.chapter_id == chapter_id).order_by(ChapterActivity.order))).scalars().all()
    # pull the new row out, then re-insert right after the source
    new_row = next((r for r in rows if r.activity_id == new_act_id), None)
    ordered = [r for r in rows if r.activity_id != new_act_id]
    seq = []
    for r in ordered:
        seq.append(r)
        if r.activity_id == src_act_id and new_row is not None:
            seq.append(new_row)
    if new_row is not None and new_row not in seq:  # src not found — append
        seq.append(new_row)
    for i, r in enumerate(seq):
        if r.order != i:
            r.order = i
            r.update_date = _now()
            db.add(r)
    await db.commit()


async def _backfill(db: AsyncSession, course: Course, chapter_id: int,
                    src_act_id: int, new_act_id: int, assignment, task, native):
    """For every learner with a completed TrailStep on the source lesson, create
    a graded-passed submission + a completed TrailStep on the new assignment."""
    done_steps = (await db.execute(select(TrailStep).where(
        TrailStep.activity_id == src_act_id, TrailStep.complete == True))).scalars().all()  # noqa: E712
    perfect = _perfect_submission(native)
    users = steps = 0
    for st in done_steps:
        uid = st.user_id
        # skip if already backfilled
        exists = (await db.execute(select(TrailStep).where(
            TrailStep.activity_id == new_act_id, TrailStep.user_id == uid))).scalars().first()
        if exists:
            continue
        # user-level submission (graded, full marks)
        db.add(AssignmentUserSubmission(
            assignmentusersubmission_uuid=f"assignmentusersubmission_{uuid4()}",
            submission_status=AssignmentUserSubmissionStatus.GRADED,
            grade=100, overall_feedback="Auto-credited from prior lesson completion.",
            attempt_number=1, user_id=uid, assignment_id=assignment.id,
            creation_date=_now(), update_date=_now(),
        ))
        db.add(AssignmentTaskSubmission(
            assignment_task_submission_uuid=f"assignmenttasksubmission_{uuid4()}",
            task_submission=perfect, grade=100, task_submission_grade_feedback="",
            manually_graded=False, assignment_type=AssignmentTaskTypeEnum.QUIZ,
            user_id=uid, activity_id=new_act_id, course_id=course.id,
            chapter_id=chapter_id, assignment_task_id=task.id,
            creation_date=_now(), update_date=_now(),
        ))
        db.add(TrailStep(
            trailrun_id=st.trailrun_id, activity_id=new_act_id, course_id=course.id,
            trail_id=st.trail_id, org_id=course.org_id, complete=True,
            teacher_verified=False, grade="", user_id=uid,
            creation_date=_now(), update_date=_now(),
        ))
        users += 1
        steps += 1
        if users % 200 == 0:
            await db.commit()
    await db.commit()
    return users, steps
