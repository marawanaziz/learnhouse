import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

/**
 * Negative control for the retained-checkout-link recovery.
 *
 * `offer-checkout-recovery.test.mjs` asserts that specific lines are present in
 * the offer-detail source. An assertion that only ever sees a source that
 * already satisfies it proves nothing about whether it can fail: a test whose
 * pattern never matches anything would look identical.
 *
 * This file applies the same predicates to the real source AND to deliberately
 * broken variants, and requires the broken ones to FAIL. If a future edit
 * hollows out an assertion (or a regex stops matching what it claims to match),
 * the control stops failing and this test goes red.
 */

const src = readFileSync(
  new URL(
    "../app/orgs/[orgslug]/(withmenu)/store/offers/[offerid]/offer-detail.tsx",
    import.meta.url,
  ),
  "utf8",
);

/** The behaviours the recovery depends on, as predicates over a source string. */
const predicates = {
  "retains the url before navigating": (s) =>
    s.indexOf("setRetryUrl(url)") !== -1 &&
    s.indexOf("setRetryUrl(url)") < s.indexOf("window.location.href = url"),
  "renders the retained url as a link": (s) => /href=\{retryUrl\}/.test(s),
  "surfaces the failure inline": (s) => /role="alert"/.test(s) && /\{checkoutError\}/.test(s),
  "clears stale state before a retry": (s) =>
    /setCheckoutError\(null\)\s*\n\s*setRetryUrl\(null\)/.test(s),
  "persists the url across unmount": (s) =>
    /sessionStorage\.setItem\(retryKey, url\)/.test(s),
  "restores the url on mount": (s) =>
    /sessionStorage\.getItem\(retryKey\)/.test(s) && /setRetryUrl\(saved\)/.test(s),
  "clears the stored url on a fresh attempt": (s) =>
    /sessionStorage\.removeItem\(retryKey\)/.test(s),
  "survives storage denial": (s) =>
    /catch \{\s*\/\* storage unavailable/.test(s) &&
    /catch \{\s*\/\* private mode or storage disabled/.test(s),
};

/** Broken variants, each removing exactly one behaviour. */
const brokenVariants = {
  "no retained url": (s) => s.replace(/setRetryUrl\(url\)/g, "void 0"),
  "retained url rendered nowhere": (s) => s.replace(/href=\{retryUrl\}/g, 'href="#"'),
  "failure only toasted": (s) => s.replace(/role="alert"/g, "").replace(/\{checkoutError\}/g, ""),
  "stale state kept on retry": (s) =>
    s.replace(/setCheckoutError\(null\)\s*\n\s*setRetryUrl\(null\)/, "void 0"),
  "url never persisted": (s) => s.replace(/sessionStorage\.setItem\(retryKey, url\)/g, "void 0"),
  "url never restored": (s) => s.replace(/setRetryUrl\(saved\)/g, "void 0"),
  "stored url not cleared": (s) => s.replace(/sessionStorage\.removeItem\(retryKey\)/g, "void 0"),
  "storage denial unhandled": (s) =>
    s.replace(/catch \{\s*\/\* storage unavailable/g, "catch {").replace(
      /catch \{\s*\/\* private mode or storage disabled/g,
      "catch {",
    ),
};

const predicateFor = {
  "retains the url before navigating": "no retained url",
  "renders the retained url as a link": "retained url rendered nowhere",
  "surfaces the failure inline": "failure only toasted",
  "clears stale state before a retry": "stale state kept on retry",
  "persists the url across unmount": "url never persisted",
  "restores the url on mount": "url never restored",
  "clears the stored url on a fresh attempt": "stored url not cleared",
  "survives storage denial": "storage denial unhandled",
};

describe("retained checkout link: predicates and their negative controls", () => {
  it("the real source satisfies every predicate", () => {
    for (const [name, predicate] of Object.entries(predicates)) {
      assert.ok(predicate(src), `real source must satisfy: ${name}`);
    }
  });

  for (const [name, predicate] of Object.entries(predicates)) {
    it(`negative control: "${name}" fails on its broken variant`, () => {
      const variantName = predicateFor[name];
      const broken = brokenVariants[variantName](src);
      assert.notEqual(broken, src, `variant "${variantName}" must actually change the source`);
      assert.ok(
        !predicate(broken),
        `predicate "${name}" passed on broken variant "${variantName}" - it cannot detect a regression`,
      );
    });
  }

  it("a wholly broken source fails every predicate", () => {
    const empty = "export default function OfferDetailClient() { return null }";
    for (const [name, predicate] of Object.entries(predicates)) {
      assert.ok(!predicate(empty), `predicate "${name}" passed on an empty source`);
    }
  });
});
