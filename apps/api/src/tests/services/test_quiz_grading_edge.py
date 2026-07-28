"""
Edge-case unit tests for ``_grade_quiz_task(contents, submission_data, task_max)``.

``_grade_quiz_task`` is the server-side mirror of the client ``gradeFC`` in
``TaskQuizObject.tsx``. Its contract:

* Every valid question is worth an equal share of the task score.
* A question earns credit only when the learner's complete selected-option set
  exactly matches the answer key.
* Student answers are indexed by ``(questionUUID, optionUUID)``; a submission
  entry is only indexed when BOTH uuids are truthy. Options with no matching
  submission default to ``False`` ("not checked").
* ``grade = round(correct_options / total_options * task_max)``.
* ``0`` is returned when ``total_options == 0`` OR ``task_max <= 0``.

The happy-path cases (all-correct / partial / all-wrong / empty / zero max /
custom max) already live in ``test_assignment_grading.py::TestGradeQuizTask``.
This file deliberately does NOT repeat them; it targets the awkward inputs:
rounding, odd ``task_max``, multi-question mixes, junk/duplicate/partial
submission entries, non-dict members, and ``bool()`` coercion of the ``answer``
field. All assertions describe REAL observed behavior of the shipped function.

The JSON shapes used here mirror the real client structures in
``TaskQuizObject.tsx``:
    contents = {"questions": [{"questionUUID": str,
                               "options": [{"optionUUID": str,
                                            "assigned_right_answer": bool}]}]}
    submission_data = {"submissions": [{"questionUUID": str,
                                        "optionUUID": str,
                                        "answer": bool}]}
"""

from src.services.courses.activities.assignments import _grade_quiz_task


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _question(q_uuid, options):
    """options: list of (optionUUID, assigned_right_answer)."""
    return {
        "questionUUID": q_uuid,
        "options": [
            {"optionUUID": o_uuid, "assigned_right_answer": right}
            for o_uuid, right in options
        ],
    }


def _contents(*questions):
    return {"questions": list(questions)}


def _sub(q_uuid, o_uuid, answer):
    return {"questionUUID": q_uuid, "optionUUID": o_uuid, "answer": answer}


def _submission(*entries):
    return {"submissions": list(entries)}


# --------------------------------------------------------------------------- #
# Multiple questions, each with multiple options
# --------------------------------------------------------------------------- #
class TestMultiQuestionMultiOption:
    def test_all_options_across_all_questions_correct_is_full_marks(self):
        """Two questions x three options; every checkbox matches the key -> 6/6 -> 100."""
        contents = _contents(
            _question("q1", [("a", True), ("b", False), ("c", True)]),
            _question("q2", [("d", False), ("e", True), ("f", False)]),
        )
        sub = _submission(
            _sub("q1", "a", True),
            _sub("q1", "b", False),
            _sub("q1", "c", True),
            _sub("q2", "d", False),
            _sub("q2", "e", True),
            _sub("q2", "f", False),
        )
        assert _grade_quiz_task(contents, sub, 100) == 100

    def test_one_wrong_answer_in_twelve_questions_scores_ninety_two(self):
        """A 12-question quiz with one incorrect answer is 11/12 -> 92%."""
        questions = []
        submissions = []
        for index in range(12):
            qid = f"q{index}"
            questions.append(_question(qid, [(f"{qid}-correct", True), (f"{qid}-wrong", False)]))
            submissions.append(_sub(qid, f"{qid}-correct", index != 11))
        assert _grade_quiz_task(_contents(*questions), _submission(*submissions), 100) == 92

    def test_mixed_correctness_across_questions_is_proportional(self):
        """q1 fully right (3/3), q2 fully wrong (0/3) -> 3/6 of 100 -> 50."""
        contents = _contents(
            _question("q1", [("a", True), ("b", False), ("c", True)]),
            _question("q2", [("d", True), ("e", True), ("f", True)]),
        )
        sub = _submission(
            _sub("q1", "a", True),
            _sub("q1", "b", False),
            _sub("q1", "c", True),
            # q2 all left unchecked while all are right answers -> all wrong
            _sub("q2", "d", False),
            _sub("q2", "e", False),
            _sub("q2", "f", False),
        )
        assert _grade_quiz_task(contents, sub, 100) == 50

    def test_options_counted_across_questions_for_total(self):
        """Two questions with differing option counts: total = 2 + 3 = 5 options.

        Right answers checked: q1/a and q2/e only -> but unchecked-wrong options
        also count, so we compute explicitly: q1 a=T(right,checked ok),
        b=F(right unchecked? key F -> ok). q2 d=F key F ok, e=T key T checked ok,
        f=F key F ok. So 5/5 here -> 100.
        """
        contents = _contents(
            _question("q1", [("a", True), ("b", False)]),
            _question("q2", [("d", False), ("e", True), ("f", False)]),
        )
        sub = _submission(
            _sub("q1", "a", True),
            _sub("q2", "e", True),
        )
        # Every other option defaults to unchecked (False) which matches its
        # False key -> all 5 options correct.
        assert _grade_quiz_task(contents, sub, 100) == 100


# --------------------------------------------------------------------------- #
# Rounding behavior
# --------------------------------------------------------------------------- #
class TestRounding:
    def _question_set(self, count: int):
        return _contents(*[
            _question(f"q{i}", [(f"q{i}-right", True), (f"q{i}-wrong", False)])
            for i in range(count)
        ])

    def test_one_third_of_100_rounds_to_33(self):
        """One correct question out of three is 33.33%, rounded to 33."""
        contents = self._question_set(3)
        sub = _submission(
            _sub("q0", "q0-right", True),
        )
        assert _grade_quiz_task(contents, sub, 100) == 33

    def test_two_thirds_of_100_rounds_to_67(self):
        """Two correct questions out of three is 66.67%, rounded to 67."""
        contents = self._question_set(3)
        sub = _submission(
            _sub("q0", "q0-right", True),
            _sub("q1", "q1-right", True),
        )
        assert _grade_quiz_task(contents, sub, 100) == 67

    def test_bankers_rounding_half_to_even_one_sixth(self):
        """One correct question out of six with a max score of 3 is 0.5.

        Python rounds 0.5 to the even integer 0.
        """
        contents = self._question_set(6)
        sub = _submission(_sub("q0", "q0-right", True))
        assert _grade_quiz_task(contents, sub, 3) == 0

    def test_bankers_rounding_half_to_even_one_point_five(self):
        """One correct question out of two with a max score of 3 is 1.5 -> 2."""
        contents = self._question_set(2)
        sub = _submission(_sub("q0", "q0-right", True))
        assert _grade_quiz_task(contents, sub, 3) == 2


# --------------------------------------------------------------------------- #
# Odd / unusual task_max values
# --------------------------------------------------------------------------- #
class TestOddTaskMax:
    def _two_opt_one_correct(self):
        """Two questions, exactly one answered correctly (50%)."""
        contents = _contents(
            _question("q1", [("a", True), ("b", False)]),
            _question("q2", [("c", True), ("d", False)]),
        )
        sub = _submission(
            _sub("q1", "a", True),   # correct
        )
        return contents, sub

    def test_task_max_50_at_fifty_percent(self):
        """50% of task_max 50 -> 25."""
        contents, sub = self._two_opt_one_correct()
        assert _grade_quiz_task(contents, sub, 50) == 25

    def test_task_max_7_at_fifty_percent_rounds(self):
        """50% of 7 = 3.5 -> banker's rounding -> 4 (even)."""
        contents, sub = self._two_opt_one_correct()
        assert _grade_quiz_task(contents, sub, 7) == 4

    def test_task_max_one_at_one_third(self):
        """1/3 of task_max 1 = 0.333 -> round -> 0."""
        contents = _contents(_question("q1", [("a", True), ("b", True), ("c", True)]))
        sub = _submission(
            _sub("q1", "a", True),
            _sub("q1", "b", False),
            _sub("q1", "c", False),
        )
        assert _grade_quiz_task(contents, sub, 1) == 0

    def test_negative_task_max_returns_zero(self):
        """task_max <= 0 short-circuits to 0 even when answers are perfect."""
        contents, sub = self._two_opt_one_correct()
        assert _grade_quiz_task(contents, sub, -5) == 0


# --------------------------------------------------------------------------- #
# All-correct / all-wrong / mixed extremes
# --------------------------------------------------------------------------- #
class TestCorrectnessExtremes:
    def test_all_wrong_every_option_inverted(self):
        """Student inverts every checkbox -> 0/4 -> 0."""
        contents = _contents(
            _question("q1", [("a", True), ("b", False)]),
            _question("q2", [("c", True), ("d", False)]),
        )
        sub = _submission(
            _sub("q1", "a", False),  # key True
            _sub("q1", "b", True),   # key False
            _sub("q2", "c", False),  # key True
            _sub("q2", "d", True),   # key False
        )
        assert _grade_quiz_task(contents, sub, 100) == 0

    def test_student_checks_extra_correct_options_not_in_key(self):
        """Checking an option whose key is False is simply wrong, not bonus.

        2 options both keyed False; student checks both -> 0/2 -> 0.
        """
        contents = _contents(_question("q1", [("a", False), ("b", False)]))
        sub = _submission(
            _sub("q1", "a", True),
            _sub("q1", "b", True),
        )
        assert _grade_quiz_task(contents, sub, 100) == 0


# --------------------------------------------------------------------------- #
# Junk / unknown / duplicate submission entries
# --------------------------------------------------------------------------- #
class TestSubmissionJunk:
    def test_unknown_question_and_option_uuids_are_ignored(self):
        """Submissions for UUIDs not in the key never affect the score.

        Key: q1/a True (checked correct), q1/b False (defaults unchecked correct).
        The bogus entries reference questions/options that don't exist -> ignored.
        2/2 -> 100.
        """
        contents = _contents(_question("q1", [("a", True), ("b", False)]))
        sub = _submission(
            _sub("q1", "a", True),
            _sub("ghost_q", "ghost_o", True),
            _sub("q1", "ghost_o", True),
            _sub("ghost_q", "a", True),
        )
        assert _grade_quiz_task(contents, sub, 100) == 100

    def test_duplicate_entries_for_same_option_last_wins(self):
        """Repeated (questionUUID, optionUUID) entries overwrite; the LAST wins.

        q1/a key True. Two entries: first answer=True (would be correct), then
        answer=False (wrong). Last-write-wins, so the full question is wrong.
        """
        contents = _contents(_question("q1", [("a", True), ("b", False)]))
        sub = _submission(
            _sub("q1", "a", True),
            _sub("q1", "a", False),  # later entry overwrites the earlier one
        )
        assert _grade_quiz_task(contents, sub, 100) == 0

    def test_submission_missing_question_uuid_is_skipped(self):
        """Entry with falsy questionUUID is not indexed -> option defaults False.

        q1/a key True; the only submission for it omits questionUUID, so 'a' is
        treated as unchecked and the full question is wrong.
        """
        contents = _contents(_question("q1", [("a", True), ("b", False)]))
        sub = _submission(
            {"optionUUID": "a", "answer": True},  # no questionUUID
        )
        assert _grade_quiz_task(contents, sub, 100) == 0

    def test_submission_missing_option_uuid_is_skipped(self):
        """Entry with falsy optionUUID is not indexed -> 'a' stays unchecked.

        The required answer stays unchecked, so the question is incorrect.
        """
        contents = _contents(_question("q1", [("a", True), ("b", False)]))
        sub = _submission(
            {"questionUUID": "q1", "answer": True},  # no optionUUID
        )
        assert _grade_quiz_task(contents, sub, 100) == 0

    def test_submission_with_empty_string_uuids_is_skipped(self):
        """Empty-string UUIDs are falsy, so the guard skips them.

        'a' stays unchecked, so the question is wrong.
        """
        contents = _contents(_question("q1", [("a", True), ("b", False)]))
        sub = _submission(
            {"questionUUID": "", "optionUUID": "", "answer": True},
            {"questionUUID": "q1", "optionUUID": "", "answer": True},
            {"questionUUID": "", "optionUUID": "a", "answer": True},
        )
        assert _grade_quiz_task(contents, sub, 100) == 0

    def test_non_dict_submission_entries_are_skipped(self):
        """Strings / ints / None / lists in submissions are skipped gracefully.

        Only the real dict for q1/a is honored -> 2/2 -> 100.
        """
        contents = _contents(_question("q1", [("a", True), ("b", False)]))
        sub = {
            "submissions": [
                "not a dict",
                42,
                None,
                ["q1", "a", True],
                _sub("q1", "a", True),
            ]
        }
        assert _grade_quiz_task(contents, sub, 100) == 100


# --------------------------------------------------------------------------- #
# Junk / degenerate questions & options
# --------------------------------------------------------------------------- #
class TestQuestionJunk:
    def test_non_dict_questions_are_skipped(self):
        """Non-dict members of 'questions' are skipped; only real questions count.

        One valid question with 2 options, fully correct -> 2/2 -> 100.
        """
        contents = {
            "questions": [
                "garbage",
                None,
                123,
                _question("q1", [("a", True), ("b", False)]),
            ]
        }
        sub = _submission(_sub("q1", "a", True))
        assert _grade_quiz_task(contents, sub, 100) == 100

    def test_non_dict_options_are_skipped_but_dict_options_count(self):
        """Non-dict entries inside an options list are skipped before counting.

        Options list: ["junk", {a:True}, None, {b:False}] -> only 2 real options.
        Student checks 'a' correctly, 'b' defaults correct -> 2/2 -> 100.
        """
        contents = {
            "questions": [
                {
                    "questionUUID": "q1",
                    "options": [
                        "junk",
                        {"optionUUID": "a", "assigned_right_answer": True},
                        None,
                        {"optionUUID": "b", "assigned_right_answer": False},
                    ],
                }
            ]
        }
        sub = _submission(_sub("q1", "a", True))
        assert _grade_quiz_task(contents, sub, 100) == 100

    def test_question_with_empty_options_list_contributes_nothing(self):
        """A question with options=[] adds 0 options; total comes from others.

        q1 empty, q2 has 2 options both correct -> 2/2 -> 100.
        """
        contents = _contents(
            _question("q1", []),
            _question("q2", [("a", True), ("b", False)]),
        )
        sub = _submission(_sub("q2", "a", True))
        assert _grade_quiz_task(contents, sub, 100) == 100

    def test_question_with_no_options_key_contributes_nothing(self):
        """A question dict lacking an 'options' key -> `or []` -> 0 options.

        Only q2's 2 options count -> 2/2 -> 100.
        """
        contents = {
            "questions": [
                {"questionUUID": "q1"},  # no 'options' key at all
                _question("q2", [("a", True), ("b", False)]),
            ]
        }
        sub = _submission(_sub("q2", "a", True))
        assert _grade_quiz_task(contents, sub, 100) == 100

    def test_all_questions_have_no_options_returns_zero(self):
        """total_options == 0 -> short-circuit to 0 regardless of task_max."""
        contents = _contents(_question("q1", []), _question("q2", []))
        assert _grade_quiz_task(contents, _submission(), 100) == 0


# --------------------------------------------------------------------------- #
# bool() coercion of the `answer` field
# --------------------------------------------------------------------------- #
class TestAnswerCoercion:
    def _single_true_option(self):
        """One option whose right answer is True; isolates a single answer value."""
        return _contents(_question("q1", [("a", True)]))

    def test_string_true_is_truthy_matches_true_key(self):
        """answer='true' -> bool('true') is True -> matches True key -> 100."""
        contents = self._single_true_option()
        sub = _submission(_sub("q1", "a", "true"))
        assert _grade_quiz_task(contents, sub, 100) == 100

    def test_string_false_is_still_truthy(self):
        """SURPRISE: answer='false' is a non-empty string -> bool() True.

        Against a True key this counts as CORRECT (100), even though the literal
        text says 'false'. The server only ever stores real booleans, but this
        documents that a stringified 'false' would be mis-graded.
        """
        contents = self._single_true_option()
        sub = _submission(_sub("q1", "a", "false"))
        assert _grade_quiz_task(contents, sub, 100) == 100

    def test_empty_string_is_falsy(self):
        """answer='' -> bool('') False -> mismatches True key -> 0."""
        contents = self._single_true_option()
        sub = _submission(_sub("q1", "a", ""))
        assert _grade_quiz_task(contents, sub, 100) == 0

    def test_integer_one_is_truthy(self):
        """answer=1 -> bool(1) True -> matches True key -> 100."""
        contents = self._single_true_option()
        sub = _submission(_sub("q1", "a", 1))
        assert _grade_quiz_task(contents, sub, 100) == 100

    def test_integer_zero_is_falsy(self):
        """answer=0 -> bool(0) False -> mismatches True key -> 0."""
        contents = self._single_true_option()
        sub = _submission(_sub("q1", "a", 0))
        assert _grade_quiz_task(contents, sub, 100) == 0

    def test_none_answer_is_falsy(self):
        """answer=None -> bool(None) False -> mismatches True key -> 0."""
        contents = self._single_true_option()
        sub = _submission(_sub("q1", "a", None))
        assert _grade_quiz_task(contents, sub, 100) == 0

    def test_assigned_right_answer_truthy_non_bool_also_coerced(self):
        """The KEY side is bool()'d too: assigned_right_answer=1 behaves like True.

        Student checks the option (True) -> matches coerced-True key -> 100.
        """
        contents = {
            "questions": [
                {
                    "questionUUID": "q1",
                    "options": [{"optionUUID": "a", "assigned_right_answer": 1}],
                }
            ]
        }
        sub = _submission(_sub("q1", "a", True))
        assert _grade_quiz_task(contents, sub, 100) == 100


# --------------------------------------------------------------------------- #
# Missing top-level keys
# --------------------------------------------------------------------------- #
class TestMissingTopLevelKeys:
    def test_contents_missing_questions_key_returns_zero(self):
        """No 'questions' key -> `or []` -> total_options 0 -> 0."""
        assert _grade_quiz_task({}, _submission(_sub("q1", "a", True)), 100) == 0

    def test_submission_missing_submissions_key_treats_all_unchecked(self):
        """No 'submissions' key -> every option defaults to unchecked (False).

        The required answer is unchecked, so the full question is incorrect.
        """
        contents = _contents(_question("q1", [("a", True), ("b", False)]))
        assert _grade_quiz_task(contents, {}, 100) == 0

    def test_questions_value_explicitly_none_returns_zero(self):
        """questions=None -> `or []` -> 0 options -> 0."""
        assert _grade_quiz_task({"questions": None}, {"submissions": None}, 100) == 0

    def test_both_top_level_inputs_empty_dicts(self):
        """Empty contents and submission_data -> 0 (no options)."""
        assert _grade_quiz_task({}, {}, 100) == 0
