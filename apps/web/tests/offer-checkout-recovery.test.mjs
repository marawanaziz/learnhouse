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
    assert.match(src, /setRetryUrl\(url\)/);
    assert.match(src, /window\.location\.href = url/);
    assert.ok(
      src.indexOf("setRetryUrl(url)") < src.indexOf("window.location.href = url"),
      "the url must be retained before navigation is attempted",
    );
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

  it("survives the unmount so the link is there on the way back", () => {
    // The success path navigates away; the component unmounts and in-memory
    // state is lost, so the retained url has to be persisted.
    assert.match(src, /sessionStorage\.setItem\(retryKey, url\)/);
    assert.match(src, /sessionStorage\.getItem\(retryKey\)/);
    assert.match(src, /setRetryUrl\(saved\)/);
    // A fresh attempt must not surface a stale checkout url.
    assert.match(src, /sessionStorage\.removeItem\(retryKey\)/);
    // Storage can throw in private mode; it must never break the flow.
    assert.match(src, /catch \{\s*\/\* storage unavailable/);
  });

  it("imports useEffect for the one-time restore", () => {
    assert.match(src, /import React, \{ useEffect, useState \} from 'react'/);
  });
});
