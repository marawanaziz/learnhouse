import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

const authContextSource = readFileSync(
  fileURLToPath(
    new URL("../components/Contexts/AuthContext.tsx", import.meta.url)
  ),
  "utf8"
);

const adminAuthorizationSource = readFileSync(
  fileURLToPath(
    new URL("../components/Security/AdminAuthorization.tsx", import.meta.url)
  ),
  "utf8"
);

describe("session recovery during rolling deploys", () => {
  test("retries temporary auth and session failures", () => {
    assert.match(authContextSource, /AUTH_REQUEST_RETRY_DELAYS_MS/);
    assert.match(authContextSource, /status === 429 \|\| status >= 500/);
    assert.match(authContextSource, /fetchWithAuthRetry\(\(\) => fetch/);
  });

  test("does not clear the session marker after a transient exception", () => {
    assert.match(
      authContextSource,
      /A temporary backend outage is not a logout[\s\S]*setStatus\('loading'\)/
    );
    assert.match(
      authContextSource,
      /Initial session restore is temporarily unavailable/
    );
    assert.match(authContextSource, /setTimeout\(initSession, 2000\)/);
  });

  test("does not dereference a missing organization while redirecting", () => {
    assert.match(
      adminAuthorizationSource,
      /getUriWithOrg\(org\?\.slug \|\| '', '\/login'\)/
    );
    assert.doesNotMatch(
      adminAuthorizationSource,
      /getUriWithOrg\(org\.slug, '\/login'\)/
    );
  });
});
