import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const courseActionsSource = readFileSync(
  new URL(
    "../components/Objects/Courses/CourseActions/CourseActionsMobile.tsx",
    import.meta.url,
  ),
  "utf8",
);

describe("paid course access link", () => {
  it("opens the offer detail route with the offer UUID", () => {
    assert.match(
      courseActionsSource,
      /`\/store\/offers\/\$\{offer\.offer_uuid\}`/,
    );
    assert.doesNotMatch(
      courseActionsSource,
      /`\/store\/offers\/\$\{offer\.offer_id\}`/,
    );
  });
});
