"""BBU quiz -> native Assignment migration (admin-key gated).

BBU's lesson quizzes are dedicated **quiz-only** activities (a lesson whose only
content is one inline `blockQuiz`). This converts each such lesson IN PLACE into
a first-class native Assignment activity:

  * the SAME activity is retyped TYPE_ASSIGNMENT (its inline quiz block removed);
  * a native Assignment (PASS_FAIL, auto-graded, retries on) + one QUIZ task
    carrying the same questions/answers is attached to that activity;
  * because it is the same activity id, every learner's existing completion
    (TrailStep) carries over untouched — nobody's course progress / certificate
    regresses, and no new step is inserted into the course.

Optional submission backfill: for learners who already completed the lesson, a
graded-passed AssignmentUserSubmission is written so the admin submission list
shows them as passed (their TrailStep already exists, so it is left as-is).

Idempotent: once an activity is retyped to TYPE_ASSIGNMENT its quiz block is
gone, so a re-run skips it. Mounted under /api/v1/bbu/migrate.

  POST /quiz-to-assignment        {key, course_id?, dry_run=true, backfill=true, limit?}
  GET  /quiz-to-assignment/verify        ?course_id=  (admin)
  GET  /quiz-to-assignment/inspect       ?course_id=  (admin)
  POST /quiz-to-assignment/fix-split-course  {key, course_id}  (clean up husks from the old split approach)
"""
import os
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.courses.courses import Course
from src.db.courses.activities import Activity, ActivityTypeEnum, ActivitySubTypeEnum
from src.db.courses.chapter_activities import ChapterActivity
from src.db.courses.assignments import (
    Assignment, AssignmentTask, AssignmentTaskTypeEnum, GradingTypeEnum,
    AssignmentUserSubmission, AssignmentUserSubmissionStatus, AssignmentTaskSubmission,
)
from src.db.trail_steps import TrailStep
from src.services.courses.activities.assignments import (
    _grade_quiz_task,
    compute_assignment_grade,
)

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
    if isinstance(node, dict):
        if node.get("type") == "blockQuiz":
            out.append(node)
        for v in node.values():
            _find_quiz_blocks(v, out)
    elif isinstance(node, list):
        for v in node:
            _find_quiz_blocks(v, out)


def _strip_quiz_blocks(node):
    if isinstance(node, dict):
        return {k: _strip_quiz_blocks(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_strip_quiz_blocks(v) for v in node if not (
            isinstance(v, dict) and v.get("type") == "blockQuiz")]
    return node


def _count_content_blocks(node):
    """Meaningful non-quiz content blocks (to tell quiz-only from mixed lessons)."""
    n = 0
    if isinstance(node, dict):
        t = node.get("type")
        if t and t not in ("doc", "blockQuiz"):
            txt = node.get("text")
            if txt and str(txt).strip():
                n += 1
            elif t in ("image", "video", "blockVideo", "blockImage", "blockPDF",
                       "blockEmbed", "heading", "blockquote", "codeBlock", "bulletList",
                       "orderedList", "blockMathequation", "blockAudio", "blockFile"):
                n += 1
        for v in node.values():
            n += _count_content_blocks(v)
    elif isinstance(node, list):
        for v in node:
            n += _count_content_blocks(v)
    return n


def _to_native_quiz_contents(inline_questions):
    """inline blockQuiz questions -> native QUIZ task `contents`."""
    out = []
    for q in (inline_questions or []):
        opts = []
        for a in (q.get("answers") or []):
            opts.append({
                "text": a.get("answer", ""), "fileID": "", "type": "text",
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
    subs = []
    for q in native_contents.get("questions", []):
        for o in q.get("options", []):
            subs.append({"questionUUID": q["questionUUID"], "optionUUID": o["optionUUID"],
                         "answer": bool(o["assigned_right_answer"])})
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

    rep = {"dry_run": dry_run, "backfill": backfill, "mode": "in_place", "courses": [],
           "assignments_created": 0, "questions_migrated": 0, "blocks_removed": 0,
           "mixed_lessons_skipped": 0, "backfilled_submissions": 0, "errors": []}
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
            # only convert quiz-only lessons in place; a mixed lesson (quiz +
            # real content) would lose its content if retyped, so skip + report.
            other = _count_content_blocks(src.content or {})
            if other > 0:
                rep["mixed_lessons_skipped"] += 1
                rep["errors"].append(f"act {src.id} ({src.name}): mixed lesson ({other} content blocks) — skipped")
                continue
            if limit is not None and processed >= limit:
                break
            processed += 1
            try:
                inline_qs = []
                for b in blocks:
                    inline_qs.extend((b.get("attrs") or {}).get("questions") or [])
                native = _to_native_quiz_contents(inline_qs)
                nq = len(native["questions"])
                link = (await db_session.execute(select(ChapterActivity).where(
                    ChapterActivity.activity_id == src.id))).scalars().first()
                chapter_id = link.chapter_id if link else 0

                if dry_run:
                    c_created += 1
                    c_q += nq
                    continue

                # 1) retype the SAME activity to an assignment, strip the quiz block
                src.activity_type = ActivityTypeEnum.TYPE_ASSIGNMENT
                src.activity_sub_type = ActivitySubTypeEnum.SUBTYPE_ASSIGNMENT_ANY
                src.content = _strip_quiz_blocks(src.content or {})
                src.update_date = _now()
                db_session.add(src)
                await db_session.commit()
                rep["blocks_removed"] += len(blocks)

                # 2) Assignment + QUIZ task attached to the same activity id
                assignment = Assignment(
                    title=src.name or "Quiz",
                    description="Answer the questions below to complete this activity.",
                    due_date="", published=True, grading_type=GradingTypeEnum.PASS_FAIL,
                    auto_grading=True, anti_copy_paste=False, show_correct_answers=True,
                    allow_retries=True, max_retries=0, org_id=course.org_id,
                    course_id=course.id, chapter_id=chapter_id, activity_id=src.id,
                    assignment_uuid=f"assignment_{uuid4()}",
                    creation_date=_now(), update_date=_now(),
                )
                db_session.add(assignment)
                await db_session.commit()
                await db_session.refresh(assignment)

                task = AssignmentTask(
                    title="Quiz", description="", hint="", reference_file=None,
                    assignment_type=AssignmentTaskTypeEnum.QUIZ, contents=native,
                    max_grade_value=100, assignment_task_uuid=f"assignmenttask_{uuid4()}",
                    assignment_id=assignment.id, org_id=course.org_id,
                    chapter_id=chapter_id, activity_id=src.id, course_id=course.id,
                    creation_date=_now(), update_date=_now(),
                )
                db_session.add(task)
                await db_session.commit()
                await db_session.refresh(task)

                # 3) optional: credit prior completers with a graded-passed
                #    submission (their existing TrailStep already keeps them done)
                if backfill:
                    c_bf += await _backfill_submissions(
                        db_session, course, chapter_id, src.id, assignment, task, native)

                c_created += 1
                c_q += nq
            except Exception as e:
                await db_session.rollback()
                rep["errors"].append(f"act {src.id} ({src.name}): {type(e).__name__}: {e}")

        if c_created:
            rep["courses"].append({"course_id": course.id, "course": course.name,
                                   "assignments_created": c_created, "questions": c_q,
                                   "backfilled_submissions": c_bf})
            rep["assignments_created"] += c_created
            rep["questions_migrated"] += c_q
            rep["backfilled_submissions"] += c_bf
        if limit is not None and processed >= limit:
            break

    return rep


async def _backfill_submissions(db: AsyncSession, course: Course, chapter_id: int,
                                activity_id: int, assignment, task, native):
    """Credit learners who already completed this activity with a graded-passed
    native submission (no TrailStep writes — their completion already exists)."""
    done_steps = (await db.execute(select(TrailStep).where(
        TrailStep.activity_id == activity_id, TrailStep.complete == True))).scalars().all()  # noqa: E712
    perfect = _perfect_submission(native)
    n = 0
    for st in done_steps:
        uid = st.user_id
        exists = (await db.execute(select(AssignmentUserSubmission).where(
            AssignmentUserSubmission.assignment_id == assignment.id,
            AssignmentUserSubmission.user_id == uid))).scalars().first()
        if exists:
            continue
        db.add(AssignmentUserSubmission(
            assignmentusersubmission_uuid=f"assignmentusersubmission_{uuid4()}",
            submission_status=AssignmentUserSubmissionStatus.GRADED,
            grade=100, overall_feedback="Credited from prior lesson completion.",
            attempt_number=1, user_id=uid, assignment_id=assignment.id,
            creation_date=_now(), update_date=_now(),
        ))
        db.add(AssignmentTaskSubmission(
            assignment_task_submission_uuid=f"assignmenttasksubmission_{uuid4()}",
            task_submission=perfect, grade=100, task_submission_grade_feedback="",
            manually_graded=False, assignment_type=AssignmentTaskTypeEnum.QUIZ,
            user_id=uid, activity_id=activity_id, course_id=course.id,
            chapter_id=chapter_id, assignment_task_id=task.id,
            creation_date=_now(), update_date=_now(),
        ))
        n += 1
        if n % 200 == 0:
            await db.commit()
    await db.commit()
    return n


@router.post("/regrade-native-quizzes")
async def regrade_native_quizzes(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Recalculate existing BBU native-quiz attempts using per-question scoring.

    This is intentionally admin-key gated and dry-run by default. It updates
    only automatically graded quiz tasks; instructor overrides remain intact.
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    _check(request, body)

    dry_run = str(body.get("dry_run", request.query_params.get("dry_run", "true"))).lower() != "false"
    quiz_tasks = (await db_session.execute(select(AssignmentTask).where(
        AssignmentTask.org_id == ORG,
        AssignmentTask.assignment_type == AssignmentTaskTypeEnum.QUIZ,
    ))).scalars().all()
    tasks_by_id = {task.id: task for task in quiz_tasks if task.id is not None}
    if not tasks_by_id:
        return {"dry_run": dry_run, "quiz_submissions_checked": 0,
                "task_scores_changed": 0, "assignment_scores_changed": 0}

    task_submissions = (await db_session.execute(select(AssignmentTaskSubmission).where(
        AssignmentTaskSubmission.assignment_task_id.in_(list(tasks_by_id)),
    ))).scalars().all()

    checked = task_changes = assignment_changes = 0
    affected_assignments: set[tuple[int, int]] = set()
    regraded_scores: dict[int, int] = {}
    for task_submission in task_submissions:
        if task_submission.manually_graded:
            continue
        task = tasks_by_id.get(task_submission.assignment_task_id)
        if not task:
            continue
        checked += 1
        score = _grade_quiz_task(
            task.contents or {}, task_submission.task_submission or {}, int(task.max_grade_value or 0)
        )
        if task_submission.id is not None:
            regraded_scores[task_submission.id] = score
        if int(task_submission.grade or 0) == score:
            continue
        task_changes += 1
        affected_assignments.add((task.assignment_id, task_submission.user_id))
        if not dry_run:
            task_submission.grade = score
            task_submission.update_date = _now()
            db_session.add(task_submission)

    # Recalculate the saved assignment aggregate for every learner whose quiz
    # task changed. Some assignments can contain multiple tasks, so use the
    # complete task set rather than assuming quiz-only content.
    for assignment_id, user_id in affected_assignments:
        assignment = (await db_session.execute(select(Assignment).where(
            Assignment.id == assignment_id
        ))).scalars().first()
        if not assignment:
            continue
        assignment_tasks = (await db_session.execute(select(AssignmentTask).where(
            AssignmentTask.assignment_id == assignment_id
        ))).scalars().all()
        assignment_task_ids = [task.id for task in assignment_tasks if task.id is not None]
        task_scores = {}
        if assignment_task_ids:
            rows = (await db_session.execute(select(AssignmentTaskSubmission).where(
                AssignmentTaskSubmission.user_id == user_id,
                AssignmentTaskSubmission.assignment_task_id.in_(assignment_task_ids),
            ))).scalars().all()
            task_scores = {
                row.assignment_task_id: regraded_scores.get(row.id, int(row.grade or 0))
                for row in rows
            }
        raw_grade = sum(task_scores.values())
        max_grade = sum(int(task.max_grade_value or 0) for task in assignment_tasks)
        recalculated_grade = compute_assignment_grade(
            raw_grade, max_grade, assignment.grading_type
        )["grade"]
        submission = (await db_session.execute(select(AssignmentUserSubmission).where(
            AssignmentUserSubmission.assignment_id == assignment_id,
            AssignmentUserSubmission.user_id == user_id,
        ))).scalars().first()
        if submission and int(submission.grade or 0) != recalculated_grade:
            assignment_changes += 1
            if not dry_run:
                submission.grade = recalculated_grade
                submission.update_date = _now()
                db_session.add(submission)

    if not dry_run:
        await db_session.commit()
    return {
        "dry_run": dry_run,
        "quiz_submissions_checked": checked,
        "task_scores_changed": task_changes,
        "assignment_scores_changed": assignment_changes,
    }


# --------------------------------------------------- fix the old split course
@router.post("/quiz-to-assignment/fix-split-course")
async def fix_split_course(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Reconcile a course migrated with the earlier SPLIT approach: delete the
    now-empty husk lessons (0 content, 0 completions) and strip the redundant
    ' — Quiz' suffix from the split assignment + its host activity."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    _check(request, body)
    course_id = int(body.get("course_id") or request.query_params.get("course_id") or 0)
    if not course_id:
        raise HTTPException(400, "course_id required")

    acts = (await db_session.execute(select(Activity).where(
        Activity.course_id == course_id))).scalars().all()
    deleted_husks, renamed = 0, 0
    for a in acts:
        # rename split assignment activities: "X — Quiz" -> "X"
        if str(a.activity_type).endswith("TYPE_ASSIGNMENT") and (a.name or "").endswith(" — Quiz"):
            base = a.name[: -len(" — Quiz")]
            a.name = base
            a.update_date = _now()
            db_session.add(a)
            asg = (await db_session.execute(select(Assignment).where(
                Assignment.activity_id == a.id))).scalars().first()
            if asg:
                asg.title = base
                asg.update_date = _now()
                db_session.add(asg)
            renamed += 1
    await db_session.commit()

    for a in acts:
        # delete empty dynamic husks with no completions
        if not str(a.activity_type).endswith("TYPE_DYNAMIC"):
            continue
        if _count_content_blocks(a.content or {}) > 0:
            continue
        qb = []
        _find_quiz_blocks(a.content or {}, qb)
        if qb:
            continue
        steps = (await db_session.execute(select(func.count()).select_from(TrailStep).where(
            TrailStep.activity_id == a.id, TrailStep.complete == True))).scalar() or 0  # noqa: E712
        if steps > 0:
            continue  # keep — someone completed it
        # cascade removes ChapterActivity + TrailStep rows for this activity
        await db_session.execute(select(ChapterActivity).where(ChapterActivity.activity_id == a.id))
        links = (await db_session.execute(select(ChapterActivity).where(
            ChapterActivity.activity_id == a.id))).scalars().all()
        for lk in links:
            await db_session.delete(lk)
        await db_session.delete(a)
        deleted_husks += 1
    await db_session.commit()
    return {"course_id": course_id, "renamed_assignments": renamed, "deleted_husks": deleted_husks}


# ---------------------------------------------------------- read-only inspect
@router.get("/quiz-to-assignment/verify")
async def quiz_to_assignment_verify(request: Request, course_id: int,
                                    db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    course = (await db_session.execute(select(Course).where(Course.id == course_id))).scalars().first()
    if not course:
        raise HTTPException(404, "course not found")
    assignments = (await db_session.execute(select(Assignment).where(
        Assignment.course_id == course_id))).scalars().all()
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
                    "order": link.order if link else None,
                    "user_submissions": subs, "completed_steps": steps})
    out.sort(key=lambda x: (x["order"] if x["order"] is not None else 0))
    return {"course": course.name, "assignments": len(out),
            "remaining_inline_quiz_blocks": remaining_blocks, "detail": out}


@router.get("/quiz-to-assignment/inspect")
async def quiz_inspect(request: Request, course_id: int,
                       db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    acts = (await db_session.execute(select(Activity).where(
        Activity.course_id == course_id))).scalars().all()
    rows = []
    quiz_only = mixed = husks = 0
    for a in acts:
        blocks = []
        _find_quiz_blocks(a.content or {}, blocks)
        other = _count_content_blocks(a.content or {})
        has_quiz = len(blocks) > 0
        is_husk = (not has_quiz and other == 0 and str(a.activity_type).endswith("TYPE_DYNAMIC"))
        if has_quiz:
            quiz_only += 1 if other == 0 else 0
            mixed += 1 if other > 0 else 0
        if is_husk:
            husks += 1
        rows.append({"activity_id": a.id, "name": a.name,
                     "type": str(a.activity_type).replace("ActivityTypeEnum.", ""),
                     "has_quiz_block": has_quiz,
                     "quiz_questions": sum(len((b.get('attrs') or {}).get('questions') or []) for b in blocks),
                     "other_content_blocks": other})
    return {"course_id": course_id, "activities": len(acts),
            "quiz_only_lessons": quiz_only, "mixed_lessons": mixed,
            "empty_husks": husks, "rows": rows}
