import { useAssignments } from '@components/Contexts/Assignments/AssignmentContext';
import { useAssignmentSubmission, useAssignmentTaskSubmissions } from '@components/Contexts/Assignments/AssignmentSubmissionContext';
import { useAssignmentsTask, useAssignmentsTaskDispatch } from '@components/Contexts/Assignments/AssignmentsTaskContext';
import { useLHSession } from '@components/Contexts/LHSessionContext';
import AssignmentBoxUI from '@components/Objects/Activities/Assignment/AssignmentBoxUI';
import { getAssignmentTask, getAssignmentTaskSubmissionsUser, handleAssignmentTaskSubmission, updateAssignmentTask } from '@services/courses/assignments';
import { Check, Info, Minus, Plus, PlusCircle, X } from 'lucide-react';
import React, { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { v4 as uuidv4 } from 'uuid';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query/keys';
import { applyManualGrade } from './applyManualGrade';
import { registerAssignmentDraftSave } from '@/lib/assignments/draftSaveRegistry';
import { allowsMultipleAnswers, updateQuizSelection } from '@/lib/assignments/quizSelection';

type QuizSchema = {
    questionText: string;
    questionUUID?: string;
    options: {
        optionUUID?: string;
        text: string;
        fileID: string;
        type: 'text' | 'image' | 'audio' | 'video';
        assigned_right_answer: boolean;
    }[];
};

type QuizSubmitSchema = {
    questions: QuizSchema[];
    submissions: {
        questionUUID: string;
        optionUUID: string;
        answer: boolean
    }[];
    assignment_task_submission_uuid?: string;
};

type TaskQuizObjectProps = {
    view: 'teacher' | 'student' | 'grading';
    user_id?: string; // Only for read-only view
    assignmentTaskUUID?: string;
};

type Submission = {
    questionUUID: string;
    optionUUID: string;
    answer: boolean;
};

function TaskQuizObject({ view, assignmentTaskUUID, user_id }: TaskQuizObjectProps) {
    const { t } = useTranslation()
    const session = useLHSession() as any;
    const access_token = session?.data?.tokens?.access_token;
    const assignmentTaskState = useAssignmentsTask() as any;
    const assignmentTaskStateHook = useAssignmentsTaskDispatch() as any;
    const assignment = useAssignments() as any;
    const taskSubmissionsMap = useAssignmentTaskSubmissions();
    const queryClient = useQueryClient();
    // Reveal correct answers to the student only after the submission is
    // GRADED AND the teacher opted into it on the assignment. Before grading
    // we still hide the answer key (the assignment hasn't been evaluated yet)
    // and on opt-out we never reveal, so the student sees only their own
    // choices + score.
    const assignmentSubmission = useAssignmentSubmission() as any;
    const submissionIsGraded = Array.isArray(assignmentSubmission)
        && assignmentSubmission.length > 0
        && assignmentSubmission[0].submission_status === 'GRADED';
    const showCorrectAnswers = view === 'student'
        && submissionIsGraded
        && !!assignment?.assignment_object?.show_correct_answers;


    /* TEACHER VIEW CODE */
    const [questions, setQuestions] = useState<QuizSchema[]>([
        { questionText: '', questionUUID: 'question_' + uuidv4(), options: [{ text: '', fileID: '', type: 'text', assigned_right_answer: false, optionUUID: 'option_' + uuidv4() }] },
    ]);

    const handleQuestionChange = (index: number, value: string) => {
        const updatedQuestions = [...questions];
        updatedQuestions[index].questionText = value;
        setQuestions(updatedQuestions);
    };

    const handleOptionChange = (qIndex: number, oIndex: number, value: string) => {
        const updatedQuestions = [...questions];
        updatedQuestions[qIndex].options[oIndex].text = value;
        setQuestions(updatedQuestions);
    };

    const addOption = (qIndex: number) => {
        const updatedQuestions = [...questions];
        updatedQuestions[qIndex].options.push({ text: '', fileID: '', type: 'text', assigned_right_answer: false, optionUUID: 'option_' + uuidv4() });
        setQuestions(updatedQuestions);
    };

    const removeOption = (qIndex: number, oIndex: number) => {
        const updatedQuestions = [...questions];
        if (updatedQuestions[qIndex].options.length > 1) {
            updatedQuestions[qIndex].options.splice(oIndex, 1);
            setQuestions(updatedQuestions);
        } else {
            toast.error('Cannot delete the last option. At least one option is required.');
        }
    };

    const addQuestion = () => {
        setQuestions([...questions, { questionText: '', questionUUID: 'question_' + uuidv4(), options: [{ text: '', fileID: '', type: 'text', assigned_right_answer: false, optionUUID: 'option_' + uuidv4() }] }]);
    };

    const removeQuestion = (qIndex: number) => {
        const updatedQuestions = [...questions];
        updatedQuestions.splice(qIndex, 1);
        setQuestions(updatedQuestions);
    };

    const toggleOption = (qIndex: number, oIndex: number) => {
        const updatedQuestions = [...questions];
        // Find the option to toggle
        const optionToToggle = updatedQuestions[qIndex].options[oIndex];
        // Toggle the 'correct' property of the option
        optionToToggle.assigned_right_answer = !optionToToggle.assigned_right_answer;
        setQuestions(updatedQuestions);
    };

    const saveFC = async () => {
        // Save the quiz to the server
        const values = {
            contents: {
                questions,
            },
        };
        const res = await updateAssignmentTask(values, assignmentTaskState.assignmentTask.assignment_task_uuid, assignment.assignment_object.assignment_uuid, access_token);
        if (res) {
            assignmentTaskStateHook({
                type: 'reload',
            });
            toast.success(t('dashboard.assignments.editor.toasts.task_saved'));
        } else {
            toast.error(t('dashboard.assignments.editor.toasts.task_save_error'));
        }
    };
    /* TEACHER VIEW CODE */

    /* STUDENT VIEW CODE */
    const [userSubmissions, setUserSubmissions] = useState<QuizSubmitSchema>({
        questions: [],
        submissions: [],
    });
    const [initialUserSubmissions, setInitialUserSubmissions] = useState<QuizSubmitSchema>({
        questions: [],
        submissions: [],
    });
    const [showSavingDisclaimer, setShowSavingDisclaimer] = useState<boolean>(false);
    const [assignmentTaskOutsideProvider, setAssignmentTaskOutsideProvider] = useState<any>(null);
    const userSubmissionsRef = React.useRef<QuizSubmitSchema>(userSubmissions);
    const questionsRef = React.useRef<QuizSchema[]>(questions);
    const saveQueueRef = React.useRef<Promise<void>>(Promise.resolve());

    useEffect(() => {
        userSubmissionsRef.current = userSubmissions;
    }, [userSubmissions]);

    useEffect(() => {
        questionsRef.current = questions;
    }, [questions]);

    async function chooseOption(qIndex: number, oIndex: number) {
        const currentUserSubmissions = userSubmissionsRef.current;
        const question = questionsRef.current[qIndex];
        const option = question?.options[oIndex];

        if (!question || !option) return;

        const questionUUID = question.questionUUID;
        const optionUUID = option.optionUUID;

        if (!questionUUID || !optionUUID) return;

        const updatedSubmissions = updateQuizSelection(
            currentUserSubmissions.submissions,
            question,
            optionUUID
        );

        const nextUserSubmissions = {
            ...currentUserSubmissions,
            submissions: updatedSubmissions,
        };
        userSubmissionsRef.current = nextUserSubmissions;
        setUserSubmissions(nextUserSubmissions);
    }

    // Used only by grading view — student view hydrates from useAssignments() context
    async function getAssignmentTaskUI() {
        if (assignmentTaskUUID) {
            const res = await getAssignmentTask(assignmentTaskUUID, access_token);
            if (res.success) {
                setAssignmentTaskOutsideProvider(res.data);
                setQuestions(res.data.contents.questions);
            }

        }
    }

    function hydrateTaskFromContext() {
        if (!assignmentTaskUUID) return;
        const task = assignment?.assignment_tasks?.find(
            (t: any) => t.assignment_task_uuid === assignmentTaskUUID
        );
        if (task) {
            setAssignmentTaskOutsideProvider(task);
            if (task.contents?.questions) {
                setQuestions(task.contents.questions);
            }
        }
    }

    function hydrateSubmissionFromBatch() {
        if (!assignmentTaskUUID) return;
        const sub = taskSubmissionsMap?.[assignmentTaskUUID] ?? null;
        if (sub) {
            const hydratedSubmission = {
                ...sub.task_submission,
                assignment_task_submission_uuid: sub.assignment_task_submission_uuid,
            };
            userSubmissionsRef.current = hydratedSubmission;
            setUserSubmissions(hydratedSubmission);
            setInitialUserSubmissions({
                ...sub.task_submission,
                assignment_task_submission_uuid: sub.assignment_task_submission_uuid,
            });
        }
    }

    // Detect changes between initial and current submissions
    useEffect(() => {
        const hasChanges = JSON.stringify(initialUserSubmissions.submissions) !== JSON.stringify(userSubmissions.submissions);
        setShowSavingDisclaimer(hasChanges);
    }, [userSubmissions, initialUserSubmissions.submissions]);



    const submitFC = React.useCallback(async () => {
        if (!assignmentTaskUUID || !assignment?.assignment_object?.assignment_uuid) {
            return;
        }

        const queuedSave = saveQueueRef.current
            .catch(() => undefined)
            .then(async () => {
                const currentUserSubmissions = userSubmissionsRef.current;
                const currentQuestions = questionsRef.current;

                // Ensure every option is represented. The server grades both
                // selected (true) and unselected (false) answers.
                const updatedSubmissions: Submission[] = currentQuestions.flatMap(question => {
                    return question.options.map(option => {
                        const existingSubmission = currentUserSubmissions.submissions.find(
                            submission => submission.questionUUID === question.questionUUID && submission.optionUUID === option.optionUUID
                        );

                        return existingSubmission || {
                            questionUUID: question.questionUUID || '',
                            optionUUID: option.optionUUID || '',
                            answer: false
                        };
                    });
                });

                const updatedUserSubmissions: QuizSubmitSchema = {
                    ...currentUserSubmissions,
                    submissions: updatedSubmissions
                };
                const values = {
                    assignment_task_submission_uuid: currentUserSubmissions.assignment_task_submission_uuid || null,
                    task_submission: updatedUserSubmissions,
                    grade: 0,
                    task_submission_grade_feedback: '',
                };

                const res = await handleAssignmentTaskSubmission(
                    values,
                    assignmentTaskUUID,
                    assignment.assignment_object.assignment_uuid,
                    access_token
                );
                if (!res.success) {
                    throw new Error(res.data?.detail || 'Quiz answers could not be saved');
                }

                assignmentTaskStateHook({ type: 'reload' });
                setShowSavingDisclaimer(false);
                const savedSubmissionWithUUID = {
                    ...updatedUserSubmissions,
                    assignment_task_submission_uuid:
                        res.data?.assignment_task_submission_uuid ||
                        currentUserSubmissions.assignment_task_submission_uuid
                };
                // A learner can click again while this request is in flight.
                // Preserve that newer local answer set and only merge in the
                // server UUID; the changed-vs-saved comparison will schedule
                // the follow-up save instead of reverting their click.
                const latestSubmissionWithUUID = {
                    ...userSubmissionsRef.current,
                    assignment_task_submission_uuid:
                        savedSubmissionWithUUID.assignment_task_submission_uuid
                };
                userSubmissionsRef.current = latestSubmissionWithUUID;
                setUserSubmissions(latestSubmissionWithUUID);
                setInitialUserSubmissions(savedSubmissionWithUUID);
                queryClient.invalidateQueries({
                    queryKey: queryKeys.assignments.taskSubmission(
                        assignment.assignment_object.assignment_uuid
                    )
                });
            });

        saveQueueRef.current = queuedSave;

        try {
            await queuedSave;
        } catch (error) {
            toast.error(t('dashboard.assignments.editor.toasts.task_save_error'));
            throw error;
        }
    }, [
        access_token,
        assignment,
        assignmentTaskStateHook,
        assignmentTaskUUID,
        queryClient,
        t,
    ]);

    useEffect(() => {
        if (
            view !== 'student' ||
            !assignmentTaskUUID ||
            !assignment?.assignment_object?.assignment_uuid
        ) {
            return;
        }

        return registerAssignmentDraftSave(
            assignment.assignment_object.assignment_uuid,
            assignmentTaskUUID,
            submitFC
        );
    }, [assignment, assignmentTaskUUID, submitFC, view]);

    /* STUDENT VIEW CODE */

    // Auto-save (team request Jul 2026): a short moment after the student
    // changes an answer, persist it automatically — no manual "Save progress"
    // click required. Debounced so rapid toggles collapse into one save.
    const autoSaveTimer = React.useRef<any>(null);
    useEffect(() => {
        if (view !== 'student') return;
        const hasChanges = JSON.stringify(initialUserSubmissions.submissions) !== JSON.stringify(userSubmissions.submissions);
        if (!hasChanges) return;
        if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current);
        autoSaveTimer.current = setTimeout(() => {
            submitFC().catch(() => undefined);
        }, 800);
        return () => { if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current); };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [userSubmissions]);

    /* GRADING VIEW CODE */
    const [userSubmissionObject, setUserSubmissionObject] = useState<any>(null);
    async function getAssignmentTaskSubmissionFromIdentifiedUserUI() {
        if (assignmentTaskUUID && user_id) {
            const res = await getAssignmentTaskSubmissionsUser(assignmentTaskUUID, user_id, assignment.assignment_object.assignment_uuid, access_token);
            if (res.success) {
                setUserSubmissions({
                    ...res.data.task_submission,
                    assignment_task_submission_uuid: res.data.assignment_task_submission_uuid
                });
                setUserSubmissionObject(res.data);
                setInitialUserSubmissions({
                    ...res.data.task_submission,
                    assignment_task_submission_uuid: res.data.assignment_task_submission_uuid
                });
            }

        }
    }

    async function gradeCustomFC(grade: number, feedback?: string) {
        await applyManualGrade({
            grade,
            feedback,
            maxPoints: assignmentTaskOutsideProvider?.max_grade_value || 100,
            assignmentTaskUUID,
            assignmentUUID: assignment.assignment_object.assignment_uuid,
            accessToken: access_token,
            username: session?.data?.user?.username,
            assignmentTaskSubmissionUUID: userSubmissions.assignment_task_submission_uuid,
            taskSubmissionPayload: userSubmissions,
            onSuccess: getAssignmentTaskSubmissionFromIdentifiedUserUI,
        });
    }

    async function gradeFC() {
        if (assignmentTaskUUID) {
            const maxPoints = assignmentTaskOutsideProvider?.max_grade_value || 100;
            const gradableQuestions = questions.filter((question) =>
                !!question.questionUUID && question.options.some((option) => !!option.optionUUID)
            );
            const correctQuestions = gradableQuestions.filter((question) => {
                const expected = new Set(
                    question.options
                        .filter((option) => option.optionUUID && option.assigned_right_answer)
                        .map((option) => option.optionUUID)
                );
                const selected = new Set(
                    userSubmissions.submissions
                        .filter((submission) =>
                            submission.questionUUID === question.questionUUID &&
                            submission.answer &&
                            question.options.some((option) => option.optionUUID === submission.optionUUID)
                        )
                        .map((submission) => submission.optionUUID)
                );

                return selected.size === expected.size && [...selected].every((optionUUID) => expected.has(optionUUID));
            }).length;
            const finalGrade = gradableQuestions.length
                ? Math.round((correctQuestions / gradableQuestions.length) * maxPoints)
                : 0;

            // Save the grade to the server
            const values = {
                assignment_task_submission_uuid: userSubmissions.assignment_task_submission_uuid,
                task_submission: userSubmissions,
                grade: finalGrade,
                task_submission_grade_feedback: 'Auto graded by system',
                manually_graded: false,
            };

            const res = await handleAssignmentTaskSubmission(values, assignmentTaskUUID, assignment.assignment_object.assignment_uuid, access_token);
            if (res) {
                getAssignmentTaskSubmissionFromIdentifiedUserUI();
                toast.success(`Task graded successfully with ${finalGrade} points`);
            } else {
                toast.error('Error grading task, please retry later.');
            }
        }
    }



    /* GRADING VIEW CODE */

    useEffect(() => {
        assignmentTaskStateHook({
            setSelectedAssignmentTaskUUID: assignmentTaskUUID,
        });
        // Teacher area
        if (view == 'teacher' && assignmentTaskState.assignmentTask.contents?.questions) {
            setQuestions(assignmentTaskState.assignmentTask.contents.questions);
        }
        // Student area: hydrate from already-fetched context payloads.
        else if (view == 'student') {
            hydrateTaskFromContext();
            hydrateSubmissionFromBatch();
        }

        // Grading area: per-task fetches are fine here (one task at a time).
        else if (view == 'grading') {
            getAssignmentTaskUI();
            getAssignmentTaskSubmissionFromIdentifiedUserUI();

        }
    }, [assignmentTaskState, assignment, assignmentTaskStateHook, access_token, taskSubmissionsMap]);

    if (questions && questions.length >= 0) {
        return (
            <AssignmentBoxUI submitFC={submitFC} saveFC={saveFC} gradeFC={gradeFC} gradeCustomFC={gradeCustomFC} view={view} currentPoints={userSubmissionObject?.grade} currentFeedback={userSubmissionObject?.task_submission_grade_feedback} maxPoints={assignmentTaskOutsideProvider?.max_grade_value} showSavingDisclaimer={showSavingDisclaimer} type="quiz" autoGradable={true}>
                <div className="flex flex-col space-y-6">
                    {questions && questions.map((question, qIndex) => (
                        <div key={qIndex} className="flex flex-col space-y-1.5">
                            <div className="flex space-x-2 items-center">
                                {view === 'teacher' ? (
                                    <input
                                        value={question.questionText}
                                        onChange={(e) => handleQuestionChange(qIndex, e.target.value)}
                                        placeholder="Question"
                                        className="w-full px-3 text-neutral-600 bg-[#00008b00] border-2 border-gray-200 rounded-md border-dotted text-sm font-bold"
                                    />
                                ) : (
                                    <p className="w-full px-3 text-neutral-600 bg-[#00008b00] border-2 border-gray-200 rounded-md border-dotted text-sm font-bold">
                                        {question.questionText}
                                    </p>
                                )}
                                {view === 'teacher' && (
                                    <div
                                        className="w-[20px] flex-none flex items-center h-[20px] rounded-lg bg-slate-200/60 text-slate-500 hover:bg-slate-300 text-sm transition-all ease-linear cursor-pointer"
                                        onClick={() => removeQuestion(qIndex)}
                                    >
                                        <Minus size={12} className="mx-auto" />
                                    </div>
                                )}
                            </div>
                            <div
                                className="flex flex-col space-y-2"
                                role={view === 'student' && !allowsMultipleAnswers(question) ? 'radiogroup' : undefined}
                                aria-label={view === 'student' ? question.questionText : undefined}
                            >
                                {question.options.map((option, oIndex) => {
                                    const isSelected = !!userSubmissions.submissions.find(
                                        (submission) =>
                                            submission.questionUUID === question.questionUUID &&
                                            submission.optionUUID === option.optionUUID &&
                                            submission.answer
                                    );
                                    const isMultiSelect = allowsMultipleAnswers(question);
                                    const isInteractive = view === 'student' && !submissionIsGraded;

                                    return (
                                    <div className="flex" key={oIndex}>
                                        <div
                                            onClick={() => isInteractive && chooseOption(qIndex, oIndex)}
                                            onKeyDown={(event) => {
                                                if (isInteractive && (event.key === 'Enter' || event.key === ' ')) {
                                                    event.preventDefault();
                                                    chooseOption(qIndex, oIndex);
                                                }
                                            }}
                                            role={view === 'student' ? (isMultiSelect ? 'checkbox' : 'radio') : undefined}
                                            aria-checked={view === 'student' ? isSelected : undefined}
                                            aria-disabled={view === 'student' ? submissionIsGraded : undefined}
                                            tabIndex={isInteractive ? 0 : undefined}
                                            className={`answer border-2 pr-2 shadow-sm w-full flex items-center space-x-2 min-h-[42px] hover:shadow-md rounded-lg text-sm duration-150 ease-linear nice-shadow ${
                                                isSelected
                                                    ? 'border-[#113d5d] bg-[#eef6fa] text-[#113d5d]'
                                                    : 'border-transparent bg-white text-neutral-600'
                                            } ${isInteractive ? 'cursor-pointer active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#113d5d] focus-visible:ring-offset-2' : ''}`}
                                        >
                                            <div className={`font-bold text-base flex items-center self-stretch w-[40px] rounded-l-md ${
                                                isSelected ? 'text-white bg-[#113d5d]' : 'text-slate-800 bg-slate-100/80'
                                            }`}>
                                                <p className="mx-auto font-bold text-sm">{String.fromCharCode(65 + oIndex)}</p>
                                            </div>
                                            {view === 'teacher' ? (
                                                <input
                                                    type="text"
                                                    value={option.text}
                                                    onChange={(e) => handleOptionChange(qIndex, oIndex, e.target.value)}
                                                    placeholder="Option"
                                                    className="w-full mx-2 px-3 pr-6 text-neutral-600 bg-[#00008b00] border-2 border-gray-200 rounded-md border-dotted text-sm font-bold"
                                                />
                                            ) : (
                                                <p className={`w-full mx-2 px-3 pr-6 bg-[#00008b00] text-sm font-bold ${
                                                    isSelected ? 'text-[#113d5d]' : 'text-neutral-600'
                                                }`}>
                                                    {option.text}
                                                </p>
                                            )}
                                            {view === 'teacher' && (
                                                <>
                                                    <div
                                                        className={`w-fit flex-none flex text-xs px-2 py-0.5 space-x-1 items-center h-fit rounded-lg ${option.assigned_right_answer ? 'bg-lime-200 text-lime-600' : 'bg-rose-200/60 text-rose-500'
                                                            } hover:bg-lime-300 text-sm transition-all ease-linear cursor-pointer`}
                                                        onClick={() => toggleOption(qIndex, oIndex)}
                                                    >
                                                        {option.assigned_right_answer ? <Check size={12} className="mx-auto" /> : <X size={12} className="mx-auto" />}
                                                        {option.assigned_right_answer ? (
                                                            <p className="mx-auto font-bold text-xs">True</p>
                                                        ) : (
                                                            <p className="mx-auto font-bold text-xs">False</p>
                                                        )}
                                                    </div>
                                                    <div
                                                        className="w-[20px] flex-none flex items-center h-[20px] rounded-lg bg-slate-200/60 text-slate-500 hover:bg-slate-300 text-sm transition-all ease-linear cursor-pointer"
                                                        onClick={() => removeOption(qIndex, oIndex)}
                                                    >
                                                        <Minus size={12} className="mx-auto" />
                                                    </div>
                                                </>
                                            )}
                                            {view === 'grading' && (
                                                <>
                                                    <div
                                                        className={`w-fit flex-none flex text-xs px-2 py-0.5 space-x-1 items-center h-fit rounded-lg ${option.assigned_right_answer ? 'bg-lime-200 text-lime-600' : 'bg-rose-200/60 text-rose-500'
                                                            } hover:bg-lime-300 text-sm transition-all ease-linear cursor-pointer`}
                                                    >
                                                        {option.assigned_right_answer ? <Check size={12} className="mx-auto" /> : <X size={12} className="mx-auto" />}
                                                        {option.assigned_right_answer ? (
                                                            <p className="mx-auto font-bold text-xs">Marked as True</p>
                                                        ) : (
                                                            <p className="mx-auto font-bold text-xs">Marked as False</p>
                                                        )}
                                                    </div>

                                                </>
                                            )}
                                            {view === 'student' && showCorrectAnswers && (
                                                <div className={`w-fit flex-none flex text-[10px] px-2 py-0.5 space-x-1 items-center h-fit rounded-lg ${
                                                    option.assigned_right_answer
                                                        ? 'bg-emerald-50 text-emerald-700'
                                                        : 'bg-rose-50 text-rose-600'
                                                }`}>
                                                    {option.assigned_right_answer ? <Check size={10} /> : <X size={10} />}
                                                    <p className='font-bold'>
                                                        {option.assigned_right_answer
                                                            ? t('assignments.quiz.correct_answer')
                                                            : t('assignments.quiz.incorrect_answer')}
                                                    </p>
                                                </div>
                                            )}
                                            {view === 'student' && (
                                                <div
                                                    aria-hidden="true"
                                                    className={`w-[22px] flex-none flex items-center h-[22px] ${
                                                        isMultiSelect ? 'rounded-md' : 'rounded-full'
                                                    } border-2 ${
                                                        isSelected
                                                            ? 'bg-[#113d5d] border-[#113d5d] text-white'
                                                            : 'bg-white border-slate-300 text-transparent'
                                                    } text-sm transition-all ease-linear`}
                                                >
                                                    {isSelected ? (
                                                        <Check size={12} className="mx-auto" />
                                                    ) : (
                                                        <span className="mx-auto w-2 h-2" />
                                                    )}
                                                </div>
                                            )}
                                            {view === 'grading' && (
                                                <>
                                                   
                                                    <div className={`w-[20px] flex-none flex items-center h-[20px] rounded-lg ${
                                                        userSubmissions.submissions.find(
                                                            (submission) =>
                                                                submission.questionUUID === question.questionUUID &&
                                                                submission.optionUUID === option.optionUUID &&
                                                                submission.answer
                                                        )
                                                            ? "bg-green-200/60 text-green-500"
                                                            : "bg-slate-200/60 text-slate-500"
                                                    } text-sm`}>
                                                        {userSubmissions.submissions.find(
                                                            (submission) =>
                                                                submission.questionUUID === question.questionUUID &&
                                                                submission.optionUUID === option.optionUUID &&
                                                                submission.answer
                                                        ) ? (
                                                            <Check size={12} className="mx-auto" />
                                                        ) : (
                                                            <X size={12} className="mx-auto" />
                                                        )}
                                                    </div>
                                                </>
                                            )}

                                        </div>
                                        {view === 'teacher' && oIndex === question.options.length - 1 && questions[qIndex].options.length <= 4 && (
                                            <div className="flex justify-center mx-auto px-2">
                                                <div
                                                    className="outline text-xs outline-3 outline-white px-2 shadow-sm w-full flex items-center h-[30px] hover:bg-opacity-100 hover:shadow-md rounded-lg bg-white duration-150 cursor-pointer ease-linear nice-shadow"
                                                    onClick={() => addOption(qIndex)}
                                                >
                                                    <Plus size={14} className="inline-block" />
                                                    <span></span>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                    );
                                })}
                            </div>
                        </div>
                    ))}
                </div>
                {view === 'teacher' && questions.length <= 5 && (
                    <div className="flex justify-center mx-auto px-2">
                        <div
                            className="flex w-full my-2 py-2 px-4 bg-white text-slate text-xs rounded-md nice-shadow hover:shadow-xs cursor-pointer space-x-3 items-center transition duration-150 ease-linear"
                            onClick={addQuestion}
                        >
                            <PlusCircle size={14} className="inline-block" />
                            <span>Add Question</span>
                        </div>
                    </div>
                )}
            </AssignmentBoxUI>
        );
    }
    else {
        return <div className='flex flex-row space-x-2 text-sm items-center'>
            <Info size={12} />
            <p>No questions found</p>
        </div>;
    }
}

export default TaskQuizObject;
