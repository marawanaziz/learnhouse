import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

const signupSource = readFileSync(
  fileURLToPath(new URL("../app/auth/signup/signup.tsx", import.meta.url)),
  "utf8"
);
const inviteSource = readFileSync(
  fileURLToPath(new URL("../app/auth/signup/InviteOnlySignUp.tsx", import.meta.url)),
  "utf8"
);

describe("Project BOLD invitation onboarding", () => {
  test("reads the invite code from the current signup URL and submits that exact value", () => {
    assert.match(signupSource, /const inviteCodeParam = searchParams\.get\('inviteCode'\)/);
    assert.match(signupSource, /setInviteCode\(inviteCodeParam\)/);
    assert.match(inviteSource, /signUpWithInviteCode\(values, props\.inviteCode\)/);
    assert.match(signupSource, /invite_code: inviteCode/);
  });

  test("uses the host-resolved BOLD profile for the invited form copy", () => {
    assert.match(inviteSource, /const brand = useBrand\(\)/);
    assert.match(inviteSource, /brand\.key === 'bold'/);
    assert.match(inviteSource, /brand\.partnershipLine/);
  });
});
