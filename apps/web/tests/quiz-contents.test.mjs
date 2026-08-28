import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { normalizeQuizQuestions } from "../lib/assignments/quizContents.ts";

describe("quiz content normalization", () => {
  test("keeps native learner task questions and options populated", () => {
    const questions = normalizeQuizQuestions({
      questions: [{
        questionText: "Which answer is correct?",
        questionUUID: "q1",
        options: [{
          text: "The answer",
          optionUUID: "a1",
          fileID: "",
          type: "text",
          assigned_right_answer: true,
        }],
      }],
    });

    assert.deepEqual(questions[0], {
      questionText: "Which answer is correct?",
      questionUUID: "q1",
      options: [{
        text: "The answer",
        optionUUID: "a1",
        fileID: "",
        type: "text",
        assigned_right_answer: true,
      }],
    });
  });

  test("normalizes legacy inline quiz data and serialized contents", () => {
    const questions = normalizeQuizQuestions(JSON.stringify({
      questions: [{
        question: "Pick one",
        question_id: "legacy-q",
        answers: [{ answer: "Yes", answer_id: "legacy-a", correct: true }],
      }],
    }));

    assert.equal(questions[0].questionText, "Pick one");
    assert.equal(questions[0].questionUUID, "legacy-q");
    assert.equal(questions[0].options[0].text, "Yes");
    assert.equal(questions[0].options[0].optionUUID, "legacy-a");
    assert.equal(questions[0].options[0].assigned_right_answer, true);
  });

  test("returns no blank placeholder question for missing or invalid contents", () => {
    assert.deepEqual(normalizeQuizQuestions(null), []);
    assert.deepEqual(normalizeQuizQuestions("not-json"), []);
    assert.deepEqual(normalizeQuizQuestions({ questions: null }), []);
  });
});
