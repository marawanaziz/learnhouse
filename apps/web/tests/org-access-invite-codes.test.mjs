import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

const orgAccessSource = readFileSync(
  fileURLToPath(
    new URL(
      "../components/Dashboard/Pages/Users/OrgAccess/OrgAccess.tsx",
      import.meta.url
    )
  ),
  "utf8"
);

describe("organization invite-code management", () => {
  test("stays interactive while public signup is open", () => {
    assert.doesNotMatch(
      orgAccessSource,
      /joinMethod == 'open' \? 'opacity-20 pointer-events-none'/
    );
    assert.match(
      orgAccessSource,
      /Invite codes also work in open organizations/
    );
  });
});
