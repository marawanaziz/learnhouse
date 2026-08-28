export type QuizOption = {
  optionUUID?: string;
  text: string;
  fileID: string;
  type: 'text' | 'image' | 'audio' | 'video';
  assigned_right_answer: boolean;
};

export type QuizQuestion = {
  questionText: string;
  questionUUID?: string;
  options: QuizOption[];
};

const asRecord = (value: unknown): Record<string, any> | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, any>
    : null;

function parseContents(contents: unknown): unknown {
  if (typeof contents !== 'string') return contents;
  try {
    return JSON.parse(contents);
  } catch {
    return null;
  }
}

/**
 * Normalize native assignment and legacy inline-quiz payloads before they
 * reach the learner renderer. Older BBU records use question/answers and
 * answer/correct, while native tasks use questionText/options and
 * text/assigned_right_answer. A task's JSON may also arrive serialized.
 */
export function normalizeQuizQuestions(contents: unknown): QuizQuestion[] {
  let value: any = parseContents(contents);
  const root = asRecord(value);

  if (root) {
    value = root.questions ?? asRecord(root.quiz)?.questions ?? [];
    value = parseContents(value);
  }

  if (!Array.isArray(value)) return [];

  return value.flatMap((rawQuestion): QuizQuestion[] => {
    const question = asRecord(rawQuestion);
    if (!question) return [];

    const rawOptions = question.options ?? question.answers ?? [];
    const options = Array.isArray(rawOptions)
      ? rawOptions.flatMap((rawOption): QuizOption[] => {
          const option = asRecord(rawOption);
          if (!option) return [];
          return [{
            optionUUID: option.optionUUID ?? option.answer_id,
            text: String(option.text ?? option.answer ?? ''),
            fileID: String(option.fileID ?? ''),
            type: ['text', 'image', 'audio', 'video'].includes(option.type)
              ? option.type
              : 'text',
            assigned_right_answer: Boolean(
              option.assigned_right_answer ?? option.correct ?? false
            ),
          }];
        })
      : [];

    return [{
      questionText: String(question.questionText ?? question.question ?? ''),
      questionUUID: question.questionUUID ?? question.question_id,
      options,
    }];
  });
}
