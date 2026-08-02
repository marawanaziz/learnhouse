import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

const activitySource = readFileSync(
  fileURLToPath(
    new URL(
      "../app/orgs/[orgslug]/(withmenu)/course/[courseuuid]/activity/[activityid]/activity.tsx",
      import.meta.url
    )
  ),
  "utf8"
);

const activityErrorSource = readFileSync(
  fileURLToPath(
    new URL(
      "../app/orgs/[orgslug]/(withmenu)/course/[courseuuid]/activity/[activityid]/error.tsx",
      import.meta.url
    )
  ),
  "utf8"
);

describe("quiz result continuation", () => {
  test("offers passing learners a primary Continue action", () => {
    assert.match(activitySource, /isPassing && \([\s\S]*continueAfterPass[\s\S]*Continue/);
    assert.match(activitySource, /nextActivity[\s\S]*activity\/end/);
  });

  test("keeps retry availability gated by the assignment policy", () => {
    assert.match(activitySource, /const canRetry = allowRetries/);
    assert.match(activitySource, /canRetry \?/);
  });
});

describe("course activity error recovery", () => {
  test("attempts a bounded automatic recovery", () => {
    assert.match(activityErrorSource, /lh:activity-recovery/);
    assert.match(activityErrorSource, /Date\.now\(\) - previousAttempt > 30_000/);
    assert.match(activityErrorSource, /reset\(\)[\s\S]*router\.refresh\(\)/);
  });

  test("uses a full reload for the learner's manual recovery action", () => {
    assert.match(activityErrorSource, /sessionStorage\.removeItem/);
    assert.match(activityErrorSource, /window\.location\.reload\(\)/);
  });
});
