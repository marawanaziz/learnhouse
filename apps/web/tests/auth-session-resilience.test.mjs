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

const authRouteSource = readFileSync(
  fileURLToPath(
    new URL("../app/api/auth/[...path]/route.ts", import.meta.url)
  ),
  "utf8"
);

const proxySource = readFileSync(
  fileURLToPath(new URL("../proxy.ts", import.meta.url)),
  "utf8"
);

const serverSessionSource = readFileSync(
  fileURLToPath(new URL("../lib/auth/server.ts", import.meta.url)),
  "utf8"
);

const authCookiesSource = readFileSync(
  fileURLToPath(new URL("../services/auth/cookies.ts", import.meta.url)),
  "utf8"
);

const tokenExchangeSource = readFileSync(
  fileURLToPath(new URL("../app/api/auth/token-exchange/route.ts", import.meta.url)),
  "utf8"
);

const activityPageSource = readFileSync(
  fileURLToPath(
    new URL(
      "../app/orgs/[orgslug]/(withmenu)/course/[courseuuid]/activity/[activityid]/page.tsx",
      import.meta.url
    )
  ),
  "utf8"
);

const activityHookSource = readFileSync(
  fileURLToPath(new URL("../hooks/queries/useActivity.ts", import.meta.url)),
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
    assert.doesNotMatch(authContextSource, /if \(!hasSessionMarker\(\)\)/);
    assert.match(
      authContextSource,
      /Always ask the same-origin refresh route whether secure auth cookies/
    );
  });

  test("repairs the readable marker from valid secure cookies", () => {
    assert.match(
      authRouteSource,
      /response\.cookies\.set\('LH_session', '1'/
    );
    assert.match(proxySource, /req\.cookies\.get\('LH_access'\)/);
    assert.match(proxySource, /req\.cookies\.get\('LH_refresh'\)/);
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

  test("never rotates a one-time refresh token from a Server Component", () => {
    assert.match(serverSessionSource, /getServerAPIUrl\(\).*users\/session/);
    assert.doesNotMatch(serverSessionSource, /fetch\([^\n]*auth\/refresh/);
    assert.match(
      serverSessionSource,
      /Only `\/api\/auth\/refresh` may rotate tokens/
    );
  });

  test("validates fast-path JWTs and coalesces concurrent refreshes", () => {
    assert.match(authRouteSource, /users\/session/);
    assert.match(authRouteSource, /coalescedRefresh/);
    assert.match(authRouteSource, /inFlightRefreshes/);
    assert.match(authRouteSource, /auth_refresh_failure/);
    assert.doesNotMatch(
      authRouteSource,
      /return it without round-tripping to the backend/
    );
  });

  test("clears former parent-domain cookies and mirrors rotated tokens", () => {
    assert.match(authCookiesSource, /getLegacyCookieDomains/);
    assert.match(authCookiesSource, /hostParts\.slice\(1\)/);
    assert.match(authRouteSource, /clearLegacyAuthCookies\(response, request\)/);
    assert.match(tokenExchangeSource, /refresh_token = refreshData\.refresh_token/);
    assert.match(tokenExchangeSource, /clearLegacyAuthCookies\(response, request\)/);
  });

  test("keeps protected metadata and client queries fail-safe during restore", () => {
    assert.match(activityPageSource, /Metadata must never take down a protected learner page/);
    assert.match(activityPageSource, /Course activity —/);
    assert.match(activityPageSource, /\.catch\(\(\) => null\)/);
    assert.match(activityHookSource, /session\?\.status === 'authenticated'/);
    assert.match(activityHookSource, /options\?\.requireAuth/);
  });
});
