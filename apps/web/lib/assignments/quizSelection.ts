export type QuizSelection = {
  questionUUID: string;
  optionUUID: string;
  answer: boolean;
};

export type QuizQuestionForSelection = {
  questionUUID?: string;
  options: Array<{
    optionUUID?: string;
    assigned_right_answer?: boolean;
  }>;
};

export function allowsMultipleAnswers(question: QuizQuestionForSelection): boolean {
  return question.options.filter((option) => option.assigned_right_answer).length > 1;
}

export function updateQuizSelection(
  submissions: QuizSelection[],
  question: QuizQuestionForSelection,
  optionUUID: string
): QuizSelection[] {
  const questionUUID = question.questionUUID;
  if (!questionUUID) return submissions;

  if (allowsMultipleAnswers(question)) {
    const existingIndex = submissions.findIndex(
      (submission) =>
        submission.questionUUID === questionUUID && submission.optionUUID === optionUUID
    );

    if (existingIndex === -1) {
      return [...submissions, { questionUUID, optionUUID, answer: true }];
    }

    return submissions.map((submission, index) =>
      index === existingIndex
        ? { ...submission, answer: !submission.answer }
        : submission
    );
  }

  const hasSelectedOption = submissions.some(
    (submission) =>
      submission.questionUUID === questionUUID && submission.optionUUID === optionUUID
  );
  const nextSubmissions = submissions.map((submission) =>
    submission.questionUUID === questionUUID
      ? { ...submission, answer: submission.optionUUID === optionUUID }
      : submission
  );

  return hasSelectedOption
    ? nextSubmissions
    : [...nextSubmissions, { questionUUID, optionUUID, answer: true }];
}
