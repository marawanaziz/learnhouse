import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

const signupSource = readFileSync(
  fileURLToPath(new URL("../app/auth/signup/OpenSignup.tsx", import.meta.url)),
  "utf8"
);

describe("BBU registration audience selector", () => {
  test("keeps both audience values as independently selectable controlled radios", () => {
    assert.match(signupSource, /role="radiogroup"/);
    assert.equal((signupSource.match(/type="radio"/g) || []).length, 1);
    assert.match(signupSource, /value: 'professional'/);
    assert.match(signupSource, /value: 'family'/);
    assert.match(signupSource, /checked=\{formik\.values\.bbu_audience === option\.value\}/);
    assert.match(signupSource, /onChange=\{formik\.handleChange\}/);
    assert.match(signupSource, /focus-within:ring-2/);
  });

  test("preserves required validation while allowing Formik to report it", () => {
    assert.match(signupSource, /if \(isBbu && !values\.bbu_audience\)/);
    assert.match(signupSource, /<FormLayout onSubmit=\{formik\.handleSubmit\} noValidate>/);
    assert.match(signupSource, /aria-required="true"/);
    assert.match(signupSource, /aria-describedby=\{formik\.touched\.bbu_audience/);
    assert.match(signupSource, /extra_metadata:[\s\S]*bbu_audience/);
    assert.doesNotMatch(signupSource, /\brequired\b/);
  });

  test("does not weaken the other existing required validators", () => {
    assert.match(signupSource, /if \(!values\.email\)/);
    assert.match(signupSource, /if \(!values\.password\)/);
    assert.match(signupSource, /if \(!values\.username\)/);
    assert.match(signupSource, /validatePasswordStrength\(values\.password\)/);
  });
});
