import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  allowsMultipleAnswers,
  updateQuizSelection,
} from "../lib/assignments/quizSelection.ts";

const singleAnswerQuestion = {
  questionUUID: "question_1",
  options: [
    { optionUUID: "option_a", assigned_right_answer: true },
    { optionUUID: "option_b", assigned_right_answer: false },
    { optionUUID: "option_c", assigned_right_answer: false },
  ],
};

const multipleAnswerQuestion = {
  questionUUID: "question_2",
  options: [
    { optionUUID: "option_a", assigned_right_answer: true },
    { optionUUID: "option_b", assigned_right_answer: true },
    { optionUUID: "option_c", assigned_right_answer: false },
  ],
};

describe("quiz answer selection", () => {
  test("identifies questions with more than one correct answer as multi-select", () => {
    assert.equal(allowsMultipleAnswers(singleAnswerQuestion), false);
    assert.equal(allowsMultipleAnswers(multipleAnswerQuestion), true);
  });

  test("replaces the previous choice for a single-answer question", () => {
    const current = [
      { questionUUID: "question_1", optionUUID: "option_a", answer: true },
      { questionUUID: "question_1", optionUUID: "option_b", answer: false },
      { questionUUID: "other", optionUUID: "keep", answer: true },
    ];

    const updated = updateQuizSelection(current, singleAnswerQuestion, "option_b");

    assert.deepEqual(updated, [
      { questionUUID: "question_1", optionUUID: "option_a", answer: false },
      { questionUUID: "question_1", optionUUID: "option_b", answer: true },
      { questionUUID: "other", optionUUID: "keep", answer: true },
    ]);
  });

  test("does not clear a single-answer choice when it is clicked twice", () => {
    const selected = updateQuizSelection([], singleAnswerQuestion, "option_a");
    const clickedAgain = updateQuizSelection(selected, singleAnswerQuestion, "option_a");

    assert.deepEqual(clickedAgain, [
      { questionUUID: "question_1", optionUUID: "option_a", answer: true },
    ]);
  });

  test("preserves independent toggles for genuine multi-answer questions", () => {
    const first = updateQuizSelection([], multipleAnswerQuestion, "option_a");
    const second = updateQuizSelection(first, multipleAnswerQuestion, "option_b");
    const toggledOff = updateQuizSelection(second, multipleAnswerQuestion, "option_a");

    assert.deepEqual(toggledOff, [
      { questionUUID: "question_2", optionUUID: "option_a", answer: false },
      { questionUUID: "question_2", optionUUID: "option_b", answer: true },
    ]);
  });
});
