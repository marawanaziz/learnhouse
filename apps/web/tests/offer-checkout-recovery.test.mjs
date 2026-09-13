import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = readFileSync(
  new URL(
    "../app/orgs/[orgslug]/(withmenu)/store/offers/[offerid]/offer-detail.tsx",
    import.meta.url,
  ),
  "utf8",
);

describe("offer checkout failure is visible and recoverable", () => {
  it("keeps the Stripe url so a blocked redirect still leaves a working link", () => {
    // The url is surfaced BEFORE navigation is attempted.
    assert.match(src, /setRetryUrl\(url\)\s*\n\s*window\.location\.href = url/);
    assert.match(
      src,
      /href=\{retryUrl\}/,
      "the fallback link must render the Stripe url",
    );
  });

  it("renders the failure inline instead of only a toast", () => {
    assert.match(src, /const \[checkoutError, setCheckoutError\] = useState<string \| null>\(null\)/);
    assert.match(src, /setCheckoutError\(/, "an error message must be set on failure");
    assert.match(src, /role="alert"/, "the error must be announced, not just toasted");
    assert.match(src, /\{checkoutError\}/, "the error must be rendered");
  });

  it("reports the upstream status when checkout returns no url", () => {
    assert.match(src, /failure_reason: 'no_checkout_url'/);
    assert.match(src, /result\?\.status/, "the HTTP status should be included in the message");
  });

  it("clears stale failure state before a retry", () => {
    assert.match(src, /setCheckoutError\(null\)\s*\n\s*setRetryUrl\(null\)/);
  });
});
