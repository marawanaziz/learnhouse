# Implementation Plan — Fix BBU registration doula Yes/No selector

## Implementation Approach

1. Resolve the exact anonymous registration route from the Breastfeeding class flow and capture pre-edit desktop/mobile behavior.
2. Trace the rendered control through the web form state and API contract to identify the root cause.
3. Make the smallest fix using the existing form/control pattern; preserve required validation and submitted values.
4. Add focused automated regression coverage for Yes, No, keyboard/pointer selection, focus, state persistence, and unanswered validation.
5. Run narrow tests, lint/type/build/e2e checks appropriate to the touched code, inspect the diff, commit and push the verified revision.
6. Run the registered deployment path, retain the previous revision for rollback, and record the deployment identifier.
7. Freshly verify the production route on desktop and mobile after the mutation, including both values, keyboard/touch behavior, validation, forward progress, no unintended account/charge, and no stale/login masquerade.

## Components and Files

Expected scope is the web registration component(s), its focused test(s), and this work package. The API is changed only if source/live evidence shows a mismatched field contract; otherwise no server file changes.

## Execution Sequence

Pre-edit live evidence → source trace/root cause → minimal patch → focused tests → full relevant checks → commit/push → authenticated standard production deploy → fresh destination verification → durable notes/knowledge receipt and closeout.

## Test Strategy

Use the repository's existing web test/lint/type/build scripts. Add or update a component/e2e test that asserts both option values, keyboard and pointer activation, focus visibility, controlled-state persistence, unanswered validation, and that unrelated required fields still block. Exercise the real route manually/e2e before and after deployment at desktop and mobile viewports, stopping before final account creation.

## Deployment and Rollback

Environment: production `https://learn.birthandbabyuniversity.com/`. Recovery point: current healthy Git revision before the fix, preserved by Git and the deployment provider. Deploy only the committed/pushed candidate through the existing authenticated BBU path; record revision and deployment ID. Roll back to the prior healthy revision if route load, registration progression, or other required fields regress. Verify the live asset/route rather than trusting a deploy command alone.

## Approval Boundaries

Owner's current instruction explicitly authorizes this named production bug fix and deployment. No pause is required unless target identity changes, a credential/passkey action is requested, or a materially different production mutation is discovered. No email send is authorized or needed.

## Readiness Decision

Readiness: READY
