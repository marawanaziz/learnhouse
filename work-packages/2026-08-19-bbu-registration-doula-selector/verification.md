# Verification Report — Fix BBU registration doula Yes/No selector

## Acceptance Results

- PASS — Anonymous reproduction on the real BBU flow (`/` → `/login` → Sign up → `/signup`) at desktop `1440x900` and mobile touch `390x844` found the BBU question and its native controlled `<select>`; programmatic selection worked, but keyboard ArrowDown could not advance from the first option because React restored the controlled value. Blank native submission also stopped before Formik validation.
- PASS — Root cause was the controlled native `<select>` inside the Radix form boundary combined with native constraint validation: the browser/Radix validity gate intercepted submission and the controlled select could snap back after native keyboard changes. The API already accepts the existing exact values `professional` and `family`; no server change was needed.
- PASS — The selector is now a controlled, labelled radio group with independently selectable Yes (`professional`) and No (`family`) inputs, visible mouse/touch targets, keyboard focus styling, `aria-required`, invalid/described-by state, and the original Formik required validator.
- PASS — Formik remains responsible for all required checks; native `required` attributes were removed only from the three controls whose native gate prevented Formik from reporting errors. Email, password, username, and password-strength validation rules remain unchanged.
- PASS — Fresh production verification confirmed blank-submit validation, pointer/touch selection, keyboard Space selection, persistence, validation clearing, exact submitted values, no redirect masquerade, and zero real account/charge mutations.

## Acceptance Criteria

- [x] Live anonymous route reproduced pre-edit at desktop and mobile, with the selector failure and exact root cause documented.
- [x] Yes and No are selectable by pointer/touch/keyboard, persist in state, show focus, and clear only the targeted required validation.
- [x] Automated tests cover both values and unanswered regression without weakening other required fields.
- [x] Relevant lint/type/unit/component/e2e checks pass.
- [x] Verified revision is deployed to production and fresh desktop/mobile destination checks after deployment confirm Yes and No paths advance without unintended accounts/charges.

## Checks Run

- `node --test apps/web/tests/bbu-registration-selector.test.mjs`: PASS, 3 tests.
- Targeted ESLint for `OpenSignup.tsx`, `Form.tsx`, and the regression test: PASS.
- `tsc --noEmit --pretty false --ignoreDeprecations 6.0`: PASS.
- `next build`: PASS; compilation, TypeScript, static page generation, and route output completed. Existing NFT tracing and Sentry `disableLogger` deprecation warnings only.
- `git diff --check`: PASS.
- Deployment safety preflight: PASS, preflight `sha256:1b6c21ef9e3099c0b7f55f560d2020254b69f498ed62fb8bb89802bc2ee028d0`; five gates passed with one bounded production service impact and prior revision `e363034e98328deed7a637bbeaec11b3360c7879` as rollback reference.
- Initial live reproduction: PASS evidence captured 2026-08-19T20:55:53.965123Z desktop and 2026-08-19T20:55:59.346688Z mobile; the defect was reproduced before editing.
- Fresh production desktop/mobile browser readback: PASS at 2026-08-19T21:24:48.835162Z–2026-08-19T21:24:53.725098Z; clean anonymous contexts, exact `/signup` URL, no stale select, two radios, blank validation, mouse/touch/keyboard behavior, focus-visible state, zero signup POSTs, zero accounts, zero charges.
- Fresh intercepted-submit readback: PASS at 2026-08-19T21:25:20.120872Z desktop and 2026-08-19T21:25:22.750686Z mobile; the live bundle emitted `professional` for Yes and `family` for No while the request was intercepted before leaving the browser, so no account or charge was created.

## Destination Readback

The exact destination is [BBU registration](https://learn.birthandbabyuniversity.com/signup), reached from the live BBU root/login flow. Final verification stayed on `/signup` and did not land on a login page, redirect, or stale asset. Canonical health returned HTTP 200 after deployment.

The final readback used fresh contexts at desktop `1440x900` and mobile touch `390x844`; contexts and browser sessions were closed after each check.

## Security Review

No credentials, authenticated sessions, Gmail surfaces, learner records, accounts, payments, or charges were mutated. The production checks used anonymous synthetic data only; the valid-submit checks intercepted the request in-browser before transmission. No Gmail thread was read or changed. Per the owner override, no email, reply, draft, or forward was created on thread `1a01b94b83f28f85`.

## Deployment Receipt

Source revisions: `b6d781b5af6f1e766e8c64ba43028bb190fd7c3` introduced the radio-group fix; final `b442afc1` moved the existing required validation gate fully into Formik and was pushed to `exec/2026-08-14-indira-certificate-support`.

Final Railway deployment: `1d73b2d1-306a-4e4e-983a-6127a58a6eb1`, status `SUCCESS`, image digest `sha256:60c8d86a1bdbf17fa9986d162cd52ee3a1c106aaa177caa5bad03dfb3e9c26be`. Deployment URL: https://railway.com/project/64b4caa6-d0ec-4ccf-b76a-f173a09b4395/service/0bc30d9f-f95d-460d-9447-962544bca3c0?id=1d73b2d1-306a-4e4e-983a-6127a58a6eb1&

## Remaining Risks

No known task blocker remains. The only non-task warnings are the pre-existing Next.js NFT tracing and Sentry deprecation warnings. No valid production registration was submitted.

## Completion Verdict

Verdict: PASS

The BBU registration Yes/No selector is deployed and independently verified on desktop and mobile, with preserved values, accessible interaction, reliable Formik validation, correct `professional`/`family` submission values, and no unintended account or charge mutation. No new email or draft was created on Miranda thread `1a01b94b83f28f85`.
