import { describe, expect, test } from "bun:test";

import { getResumeActivity } from "../services/courses/courseResume.ts";

const course = {
  course_uuid: "course_demo",
  chapters: [
    {
      activities: [
        { id: 10, activity_uuid: "activity_first" },
        { id: 11, activity_uuid: "activity_second" },
        { id: 12, activity_uuid: "activity_third" },
      ],
    },
  ],
};

describe("getResumeActivity", () => {
  test("continues at the first unfinished lesson", () => {
    const activity = getResumeActivity(course, {
      steps: [{ activity_id: 10, complete: true }],
    });
    expect(activity?.activity_uuid).toBe("activity_second");
  });

  test("opens the final lesson when the course is complete", () => {
    const activity = getResumeActivity(course, {
      steps: [
        { activity_id: 10, complete: true },
        { activity_id: 11, complete: true },
        { activity_id: 12, complete: true },
      ],
    });
    expect(activity?.activity_uuid).toBe("activity_third");
  });
});
