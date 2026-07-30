# PRD: CEU Credential Applications and Credential Operations Rework

## 1. Introduction

Birth & Baby University needs a reliable workflow for previously trained and
certified members to renew or convert an existing BBU credential through
continuing education units (CEUs).

The current Operations credential section is not suitable for this workflow.
It searches for a member by an exact email address, treats course certificates
and professional credentials as unrelated records, mutates a single credential
record in place, and does not support applications, document uploads, review
decisions, rejection reasons, or versioned certificate history.

The replacement will provide:

- A signed-in member application flow for eligible BBU credential holders
- Itemized CEU training entries and private supporting-document uploads
- A streamlined admin application queue and unified member credential record
- Approval and decline decisions with an audit trail
- Complete support for one-year provisional credentials issued after qualifying
  BBU full-course training
- A new three-year credential issuance, certificate, credential ID, and QR code
  for every approved application
- Preservation of all prior credential and certificate history

## 2. Confirmed Business Rules

1. Only signed-in members who were previously trained and certified by BBU may
   apply.
2. Qualifying prior training may be either the applicable full BBU training or
   the applicable BBU cross-certification training.
3. The workflow must not create a first-time credential for a member with no
   qualifying BBU training or certification history.
4. An eligible member may apply for the credential type supported by their
   existing history: Birth Doula or Postpartum.
5. Successful completion of a qualifying full BBU training may issue a one-year
   provisional credential for the applicable credential type.
6. A one-year credential must have its own effective date, expiration date,
   certificate, credential ID, QR verification link, status, and history.
7. An active, expired, or lapsed one-year credential remains qualifying history
   for a CEU application.
8. A one-year credential may transition to a three-year full credential through
   either the approved CEU process or the existing approved mentorship path.
9. Approval through this CEU workflow always creates a new full three-year
   credential, regardless of whether the prior credential is provisional, full,
   expired, or lapsed.
10. The prior one-year issuance remains unchanged in credential history after
    the new three-year credential is approved.
11. The applicant must list each outside training separately and enter the CEUs
   claimed for each training.
12. The applicant must provide supporting documents.
13. At least 15 approved CEUs are required.
14. The admin may adjust the approved CEUs for each submitted training. The
   approved total is calculated from those reviewed amounts.
15. Reaching 15 CEUs must not automatically issue or renew a credential. A
    deliberate admin approval is required.
16. The new credential's effective date defaults to the approval date.
17. The admin may choose an earlier effective date during approval.
18. The expiration date is always calculated as exactly three calendar years
    after the effective date. The admin does not enter it independently.
19. Approval creates a new certificate with a new credential ID and QR code.
20. Previous credential and certificate records remain available in history.
21. A decline requires a reason that is visible to the applicant.
22. BBU admins receive an email when an application is submitted.
23. The applicant receives email confirmation on submission and an email when a
    decision is made.

## 3. Goals

- Make every eligible BBU member discoverable and manageable from one
  credential record without retyping an email address.
- Allow an eligible member to complete and submit a CEU application without
  contacting support.
- Correctly issue, display, verify, remind, expire, and preserve one-year
  provisional credentials.
- Give admins one queue for pending applications, supporting documents, CEU
  review, and decisions.
- Prevent credential issuance below the 15-approved-CEU threshold.
- Generate a verifiable three-year credential without overwriting prior
  credential history.
- Remove ambiguity between course-completion certificates and professional BBU
  credentials.
- Make every credential-changing admin action traceable and safe to retry.

## 4. User Stories

### US-001: Reconcile qualifying BBU history

**Description:** As a previously trained BBU member, I want the platform to
recognize my full-course or cross-certification history so that I am not
incorrectly blocked from applying.

**Acceptance Criteria:**

- [ ] Qualifying course and cross-certification mappings are defined by stable
      course/certification identifiers, not course-name text matching.
- [ ] Existing professional credential records, imported Accredible records,
      and mapped course certificates are considered during reconciliation.
- [ ] A member is eligible only for the credential type supported by their
      qualifying history.
- [ ] A member with no qualifying history receives a clear ineligible message
      and cannot create or submit an application.
- [ ] Reconciliation produces an exception report for records that cannot be
      mapped automatically.
- [ ] Re-running reconciliation does not create duplicate credentials or
      eligibility records.
- [ ] Unit and integration tests pass.

### US-002: Add versioned credential issuance records

**Description:** As a BBU administrator, I want each credential issuance stored
as its own immutable record so that renewals do not erase prior history.

**Acceptance Criteria:**

- [ ] Each issuance stores user ID, organization ID, credential type, status,
      source, effective date, expiration date, public credential ID, public
      verification token, and creation metadata.
- [ ] A credential holder may have multiple historical issuances of the same
      credential type.
- [ ] The current credential is derived explicitly and does not require deleting
      or overwriting an earlier issuance.
- [ ] Existing credential records are migrated into initial issuance-history
      rows without changing their effective or expiration dates.
- [ ] Public credential IDs are unique and are safe to display.
- [ ] Verification tokens are unique and are not based on a predictable
      sequential database ID.
- [ ] Database constraints prevent duplicate approval issuance for one
      application.
- [ ] Migration and rollback checks pass against a production-shaped database.

### US-003: Add a member credential hub

**Description:** As a signed-in member, I want one place to see my BBU training
certificates, professional credentials, CEU applications, and eligibility so
that I understand my complete record.

**Acceptance Criteria:**

- [ ] The page clearly separates `Training certificates`, `Professional
      credentials`, and `CEU applications`.
- [ ] Each professional credential shows type, status, effective date,
      expiration date, credential ID, and certificate link.
- [ ] Historical and current credentials are visually distinguished.
- [ ] Eligible credential types show an `Apply through CEUs` action.
- [ ] Ineligible credential types explain that prior BBU training or
      cross-certification is required.
- [ ] A member can view the status and decision history for each submitted
      application.
- [ ] Verify in browser using the browser-testing skill.
- [ ] Typecheck and lint pass.

### US-004: Create and edit an itemized CEU application

**Description:** As an eligible member, I want to save each outside training and
its supporting documentation so that BBU can review my CEUs.

**Acceptance Criteria:**

- [ ] The application is tied to the signed-in user's internal user ID and one
      eligible credential type.
- [ ] A member can save a draft and return later.
- [ ] Each CEU entry contains training title, training provider, completion
      date, claimed CEUs, and at least one supporting document.
- [ ] Claimed CEUs must be a positive number.
- [ ] Supporting files accept PDF, JPG, JPEG, and PNG only.
- [ ] Files are validated by content and extension, limited to 10 MB each, and
      limited to 10 files per application.
- [ ] Uploaded documents are private and accessible only to the applicant and
      authorized BBU admins.
- [ ] The form shows the running claimed-CEU total.
- [ ] Draft applications do not notify admins.
- [ ] Verify in browser using the browser-testing skill.
- [ ] Typecheck, lint, and upload security tests pass.

### US-005: Validate and submit an application

**Description:** As an eligible member, I want clear validation before
submission so that I know my application is ready for review.

**Acceptance Criteria:**

- [ ] Submission is blocked when the claimed total is below 15 CEUs.
- [ ] Submission is blocked when any CEU entry is incomplete or has no
      supporting document.
- [ ] Submission rechecks eligibility on the server.
- [ ] A submitted application becomes read-only for the applicant.
- [ ] The member sees a confirmation page and the submission timestamp.
- [ ] Repeated submission requests do not create duplicate applications or
      notifications.
- [ ] The application status becomes `submitted`.
- [ ] Verify in browser using the browser-testing skill.
- [ ] API and UI tests pass.

### US-006: Send submission notifications

**Description:** As a BBU administrator, I want an email alert for each new
submission so that no application is missed.

**Acceptance Criteria:**

- [ ] A branded admin email is sent once when an application is submitted.
- [ ] Admin recipients come from a configurable BBU credential-review recipient
      list.
- [ ] The email includes member name, member email, credential type, claimed CEU
      total, submission date, and a direct link to the admin review page.
- [ ] The applicant receives a branded confirmation email.
- [ ] Notification delivery is retried safely and never duplicates a credential
      application or approval.
- [ ] Notification failures are logged and visible to admins without losing the
      submitted application.
- [ ] Email tests pass with the configured platform SMTP service.

### US-007: Replace email-based Operations lookup with a unified member record

**Description:** As a BBU administrator, I want to select a member once and
manage the correct account so that email differences do not produce false
`User not found` errors or target the wrong person.

**Acceptance Criteria:**

- [ ] Operations search supports member name, canonical email, and internal user
      ID.
- [ ] Selecting a result loads the member by internal user ID.
- [ ] All read and write actions use user ID and record ID after selection,
      rather than a free-typed email.
- [ ] The member record shows account details, mapped BBU training certificates,
      all professional credential history, CEU ledger entries, and CEU
      applications.
- [ ] Course certificates and professional credentials are labeled as separate
      record types.
- [ ] A `Manage` action on registry and application rows opens the same member
      record.
- [ ] Not-found and no-credential states are distinct and clearly worded.
- [ ] Ambiguous search results require an explicit admin selection.
- [ ] Existing credential registry filters and CSV export continue to work.
- [ ] Verify in browser using the browser-testing skill.
- [ ] Regression tests cover a member whose searched or historical email differs
      from the current canonical account email.

### US-008: Add a streamlined application review queue

**Description:** As a BBU administrator, I want a focused queue of applications
so that I can review pending work quickly.

**Acceptance Criteria:**

- [ ] The Credentials section opens with summary counts and an application
      queue.
- [ ] Queue filters include `Submitted`, `Approved`, `Declined`, credential type,
      member search, and submission-date range.
- [ ] Each row shows member, credential type, claimed CEUs, status, and age of
      application.
- [ ] Opening an application shows the member's qualifying history, current
      credential, every CEU entry, and every supporting document.
- [ ] Documents open through an authenticated endpoint and never expose the raw
      storage path.
- [ ] The admin can enter an approved CEU amount and optional review note for
      each CEU entry.
- [ ] The approved total is calculated by the system.
- [ ] The decision controls remain disabled until all entries have been reviewed.
- [ ] Verify in browser using the browser-testing skill.
- [ ] Typecheck, lint, and API tests pass.

### US-009: Decline an application with a reason

**Description:** As a BBU administrator, I want to decline an application with a
clear reason so that the member understands the decision.

**Acceptance Criteria:**

- [ ] Decline requires a non-empty reason and a confirmation step.
- [ ] The application stores the reviewer, decision timestamp, and reason.
- [ ] The applicant can see the decline reason in the member credential hub.
- [ ] A branded decline email contains the reason and a link to the application.
- [ ] Declining does not alter the member's existing credential or CEU ledger.
- [ ] A declined application remains in history.
- [ ] A member may start a new application after a decline.
- [ ] Repeating the decline request is idempotent and sends no duplicate email.
- [ ] Verify in browser using the browser-testing skill.

### US-010: Approve an application and issue a three-year credential

**Description:** As a BBU administrator, I want approval to create the correct
credential atomically so that dates, history, and CEUs cannot get out of sync.

**Acceptance Criteria:**

- [ ] Approval is blocked when the approved CEU total is below 15.
- [ ] Approval is blocked when the applicant no longer has qualifying BBU
      history.
- [ ] The effective date defaults to the approval date.
- [ ] The admin may choose an earlier effective date but not a future date.
- [ ] Expiration is calculated as exactly three calendar years after the
      effective date, including a defined February 29 handling rule.
- [ ] Approval creates a new immutable credential issuance with a new public
      credential ID and verification token.
- [ ] The prior credential remains unchanged and visible in history.
- [ ] Approved CEU entries are recorded in the CEU ledger and linked to the
      application.
- [ ] The application, CEU ledger rows, and credential issuance are committed in
      one database transaction.
- [ ] Repeating the approval request returns the already-created issuance and
      does not create another credential.
- [ ] Approval stores the reviewer and decision timestamp.
- [ ] Unit and integration tests cover full, provisional, expired, and lapsed
      prior credentials.

### US-011: Generate and verify the new certificate

**Description:** As an approved member, I want a downloadable, verifiable
certificate so that I can prove my current BBU credential.

**Acceptance Criteria:**

- [ ] The certificate uses the BBU color scheme and approved certificate
      artwork.
- [ ] It displays member name, credential type, public credential ID, effective
      date, and expiration date.
- [ ] It includes a QR code pointing to a public verification page on
      `learn.birthandbabyuniversity.com`.
- [ ] The verification page shows only the public credential facts needed to
      verify authenticity.
- [ ] The member can download the certificate as a PDF.
- [ ] Historical certificates remain downloadable and verifiable.
- [ ] The applicant receives an approval email with a link to the new
      certificate.
- [ ] Verify the rendered certificate, PDF download, and QR destination in a
      browser.
- [ ] Typecheck, lint, and verification-route tests pass.

### US-012: Preserve controlled admin credential actions

**Description:** As an authorized BBU administrator, I want a safe way to
correct or manually issue a credential in exceptional cases without returning
to the unreliable free-email action form.

**Acceptance Criteria:**

- [ ] Manual actions are available only after selecting a specific member
      record by internal user ID.
- [ ] The admin must choose the credential type, effective date, action reason,
      and source.
- [ ] Any manual issuance creates a new issuance-history row and does not
      overwrite history.
- [ ] Potentially destructive corrections require confirmation.
- [ ] Every action records the admin, timestamp, reason, before state, and after
      state.
- [ ] Manual issue cannot bypass the rule against a first-time CEU credential;
      a separate support/backfill source and reason are required.
- [ ] Verify in browser using the browser-testing skill.
- [ ] Authorization and audit tests pass.

### US-013: Add complete audit history

**Description:** As a BBU administrator, I want to know who changed an
application or credential and why so that decisions can be reviewed later.

**Acceptance Criteria:**

- [ ] Audit events cover draft submission, review edits, document access,
      approval, decline, manual issuance, and corrections.
- [ ] Each event stores actor, action, target record, timestamp, and relevant
      before/after values.
- [ ] Audit events are append-only from the application.
- [ ] Admins can view the timeline from the member/application record.
- [ ] Applicant-facing history excludes internal-only review notes and audit
      metadata.
- [ ] Audit tests pass.

### US-014: Reconcile production data and release safely

**Description:** As the platform owner, I want the rework released without
losing or silently changing existing credential data.

**Acceptance Criteria:**

- [ ] A read-only pre-migration report counts users, course certificates,
      professional credentials, unmapped records, and duplicate candidates.
- [ ] The migration is idempotent and produces a post-migration reconciliation
      report.
- [ ] No existing credential dates, IDs, statuses, or certificate UUIDs are
      silently discarded.
- [ ] Automated tests cover eligibility, state transitions, authorization,
      uploads, date calculations, idempotency, and notifications.
- [ ] The complete member and admin flows are tested with controlled Birth Doula
      and Postpartum test accounts.
- [ ] The flow is browser-tested on desktop and mobile widths.
- [ ] Production is released behind a feature flag.
- [ ] Production smoke tests do not modify a real member's credential.
- [ ] Error monitoring confirms no new credential-route 4xx/5xx spike after
      release.

### US-015: Support the complete one-year credential lifecycle

**Description:** As a BBU member who completed qualifying full-course training,
I want my one-year credential to work everywhere in the platform so that I can
use it, verify it, and later move to a three-year credential.

**Acceptance Criteria:**

- [ ] A qualifying full-course completion can create a one-year provisional
      issuance for the mapped Birth Doula or Postpartum credential type.
- [ ] A one-year issuance has a unique credential ID, public verification token,
      effective date, expiration date, and downloadable certificate.
- [ ] The expiration date is calculated as exactly one calendar year after the
      effective date.
- [ ] The member credential hub labels it clearly as `One-year provisional`.
- [ ] The admin registry can filter and report one-year provisional credentials
      separately from three-year full credentials.
- [ ] Active one-year credentials participate in the existing expiration
      reminder schedule.
- [ ] An overdue one-year credential becomes `lapsed` but remains visible and
      verifiable as historical credential evidence.
- [ ] An active or lapsed one-year credential remains eligible for the
      applicable CEU application.
- [ ] Approved CEU or mentorship transition creates a separate three-year
      issuance and retains the one-year issuance unchanged in history.
- [ ] Cross-certification continues to issue the applicable three-year
      credential directly and does not create an unnecessary one-year
      credential.
- [ ] Authorized admins can issue or correct a one-year credential from a
      selected member record with a required source and audit reason.
- [ ] Unit tests cover one-year issuance, leap-day expiration, lapse,
      reminders, CEU transition, mentorship transition, and idempotency.
- [ ] Verify the one-year certificate, registry display, member display, and
      transition history in a browser.

## 5. Functional Requirements

- **FR-1:** The system must require an authenticated member session for all
  applicant actions.
- **FR-2:** The system must determine eligibility from stable mappings of prior
  BBU credential history, full-training certificates, cross-certification
  certificates, and imported BBU credential records.
- **FR-3:** The system must scope eligibility to Birth Doula and/or Postpartum
  independently.
- **FR-4:** The system must prohibit CEU applications for a first-time
  credential.
- **FR-5:** The system must allow at most one draft or submitted application per
  member and credential type at a time.
- **FR-6:** The system must support draft, submitted, approved, and declined
  application states.
- **FR-7:** The system must store each claimed training and CEU amount as a
  separate application item.
- **FR-8:** The system must store an admin-approved CEU amount separately from
  the member's claimed amount.
- **FR-9:** The system must derive the approved total from reviewed application
  items.
- **FR-10:** The system must require at least 15 claimed CEUs to submit and at
  least 15 approved CEUs to approve.
- **FR-11:** The system must require at least one supporting document for each
  CEU item.
- **FR-12:** Supporting documents must be privately stored and served through
  authenticated, ownership-checked endpoints.
- **FR-13:** A submitted application must be read-only to the applicant.
- **FR-14:** The system must notify configured BBU admins once after submission.
- **FR-15:** The system must notify the applicant after submission and decision.
- **FR-16:** Decline must require and retain an applicant-visible reason.
- **FR-17:** Approval must default the effective date to the approval date and
  allow an admin-selected earlier date.
- **FR-18:** The system must derive expiration as effective date plus three
  calendar years.
- **FR-19:** Approval must create a new immutable issuance with a unique
  credential ID and verification token.
- **FR-20:** Approval must never overwrite or delete a prior issuance.
- **FR-21:** Approval, ledger creation, and application state change must be one
  idempotent database transaction.
- **FR-22:** Accumulating 15 CEUs in the general ledger must not automatically
  upgrade or renew a credential without an approved application or an explicit
  authorized admin action.
- **FR-23:** Admin member selection and all subsequent actions must use internal
  record IDs, not a re-entered email address.
- **FR-24:** The unified admin record must show course certificates,
  professional credentials, CEUs, and applications as distinct but related
  data.
- **FR-25:** Certificate verification must remain available for both current and
  historical credential issuances.
- **FR-26:** Every credential-changing action must create an append-only audit
  event.
- **FR-27:** All endpoints must enforce organization membership, record
  ownership, and admin authorization server-side.
- **FR-28:** Qualifying full-course completion must support issuing a one-year
  provisional credential for the mapped Birth Doula or Postpartum type.
- **FR-29:** A one-year credential must expire exactly one calendar year after
  its effective date and become lapsed when overdue.
- **FR-30:** A one-year credential must have the same certificate download,
  public credential ID, QR verification, directory, reminder, registry, export,
  and history capabilities as a three-year credential.
- **FR-31:** A one-year credential, whether active or lapsed, must satisfy the
  prior-BBU-credential eligibility gate for the matching CEU application type.
- **FR-32:** Approval of a CEU application tied to a one-year credential must
  create a separate three-year issuance and must not mutate or delete the
  one-year issuance.
- **FR-33:** Existing mentorship completion may transition a one-year
  provisional credential into a separate three-year full issuance while
  preserving the one-year history.
- **FR-34:** Qualifying cross-certification must continue to issue a three-year
  full credential directly.

## 6. Data Model

### `bbu_credential_application`

- `id`
- `public_uuid`
- `org_id`
- `user_id`
- `credential_type` (`birth` or `postpartum`)
- `qualifying_source_type`
- `qualifying_source_id`
- `status` (`draft`, `submitted`, `approved`, `declined`)
- `claimed_ceu_total`
- `approved_ceu_total`
- `submitted_at`
- `reviewed_at`
- `reviewed_by_user_id`
- `decline_reason`
- `approved_issuance_id`
- `created_at`
- `updated_at`

### `bbu_credential_application_ceu`

- `id`
- `application_id`
- `training_title`
- `provider`
- `completion_date`
- `claimed_ceu`
- `approved_ceu`
- `admin_note`
- `created_at`
- `updated_at`

### `bbu_credential_application_document`

- `id`
- `application_id`
- `application_ceu_id`
- `storage_key`
- `original_filename`
- `content_type`
- `byte_size`
- `uploaded_at`

### `bbu_credential_issuance`

- `id`
- `public_credential_id`
- `verification_token`
- `org_id`
- `user_id`
- `credential_type`
- `credential_level` (`one_year_provisional` or `three_year_full`)
- `term_years` (`1` or `3`)
- `status`
- `source`
- `source_application_id`
- `effective_at`
- `expires_at`
- `issued_by_user_id`
- `created_at`

### `bbu_credential_audit_event`

- `id`
- `org_id`
- `actor_user_id`
- `action`
- `target_type`
- `target_id`
- `before_data`
- `after_data`
- `reason`
- `created_at`

The existing `bbu_credential` record may remain as a compatibility/current-state
projection during the migration, but issuance history is the source of truth for
certificates and renewal history.

## 7. Streamlined User Experience

### Member flow

1. Member opens `Credentials`.
2. The page shows training certificates, professional credentials, and previous
   applications.
3. One-year credentials are labeled `One-year provisional`; three-year
   credentials are labeled `Three-year full`.
4. If eligible, the member selects `Apply through CEUs` for Birth Doula or
   Postpartum.
5. The member adds each training, claimed CEUs, and its supporting documents.
6. The member may save a draft.
7. At 15 or more claimed CEUs with complete documentation, the member submits.
8. The member sees `Submitted — awaiting BBU review`.
9. After review, the member sees either:
   - `Approved`, with the new credential and certificate download; or
   - `Declined`, with Anna's reason and the option to start a new application.

### Admin flow

1. Admin opens `Operations → Credentials`.
2. The default view shows pending applications and summary counts.
3. Admin opens an application; no email re-entry is required.
4. The review screen shows prior qualifying training, current credential, CEU
   items, and documents.
5. Admin enters the approved CEUs for each item.
6. Admin either:
   - declines with a required reason; or
   - approves when the approved total is at least 15, using today's effective
     date or an earlier selected date.
7. Approval generates the new issuance, three-year expiration, credential ID,
   QR verification page, downloadable certificate, ledger entries, and emails
   in one controlled workflow.

## 8. Technical Considerations

- Reuse the platform's existing authenticated upload validation and S3/R2 or
  filesystem abstraction, but use a credential-application-specific private
  directory and download authorization endpoint.
- Reuse the existing BBU certificate visual treatment, PDF export capability,
  and QR-generation infrastructure where practical.
- Treat one-year provisional and three-year full credentials as versioned
  issuances with different terms, not as one mutable row that changes its dates
  in place.
- Do not use `CertificateUser.created_at` as the only professional credential
  effective date. Backdated CEU credentials require explicit effective and
  expiration fields.
- Replace current exact-email credential actions with user-ID and record-ID
  routes.
- Remove the implicit provisional-to-full side effect from generic CEU ledger
  additions. Credential changes must occur through an approved application,
  mentorship completion, course rule, or explicit audited admin action.
- Use a transactional outbox or equivalent idempotent job record for decision
  emails so an SMTP retry cannot repeat an approval.
- Add unique constraints for active application scope and
  application-to-issuance linkage.
- Keep public verification data minimal: member name, credential type,
  credential ID, effective date, expiration date, and current validity.
- Preserve the existing credential registry and reminders by deriving the
  current issuance for each member and type.

## 9. Release Plan

### Phase 1: Inventory and reconciliation

- Produce a read-only production report of course certificates, BBU
  credentials, Accredible imports, unmapped records, and duplicate candidates.
- Confirm the stable qualifying course/certification mappings for Birth Doula
  and Postpartum full and cross-certification training.
- Fix existing member-to-credential relationships before enabling applications.

### Phase 2: Data foundation

- Add application, CEU item, document, issuance history, and audit tables.
- Migrate existing one-year provisional and three-year full credential records
  into issuance history while retaining their original dates and status.
- Add idempotency and authorization tests.

### Phase 3: Unified admin Credentials area

- Replace the email action form with member search and ID-based selection.
- Add the unified member record and application queue.
- Preserve registry filters and export.

### Phase 4: Member application flow

- Add eligibility display, drafts, itemized CEUs, uploads, submission, and
  applicant status history.
- Add branded submission notifications.

### Phase 5: Review, approval, and certificate generation

- Add per-item CEU review, required decline reasons, effective-date approval,
  immutable issuance, new credential IDs, QR verification, PDF certificates,
  and decision emails.
- Verify both the one-year issuance path and the one-year-to-three-year
  transition path.

### Phase 6: Verification and controlled production rollout

- Run automated API, security, migration, and date-calculation tests.
- Browser-test the full Birth Doula and Postpartum paths at desktop and mobile
  sizes.
- Release behind a feature flag.
- Run read-only production reconciliation and controlled test-account smoke
  tests.
- Enable member access after admin sign-off.

## 10. Non-Goals

- No public or anonymous CEU application form.
- No application from a signed-in member without prior qualifying BBU history.
- No first-time credential earned only through outside CEUs.
- No credential issuance based only on a member-entered total.
- No approval below 15 approved CEUs.
- No automatically calculated effective date based on the prior expiration.
- No independently editable expiration date.
- No replacement or deletion of prior credential history.
- No conversion of a one-year credential by overwriting its existing issuance
  row.
- No automatic credential change merely because a general CEU ledger reaches
  15.
- No payment or application-fee workflow in this scope.
- No reviewer chat or multi-step committee approval in the first release.

## 11. Success Metrics

- 100% of mapped existing BBU credential holders can be opened from Operations
  without an exact-email 404.
- 100% of approved CEU applications have at least 15 approved CEUs.
- 100% of approvals produce one and only one new issuance.
- 100% of new issuances have a unique credential ID, three-year expiration,
  downloadable certificate, and working QR verification link.
- 100% of declines retain an applicant-visible reason.
- 0 prior credential records are overwritten or lost during migration.
- 100% of one-year credentials display the correct term, effective date,
  expiration date, certificate, QR verification, and historical status.
- 0 supporting documents are accessible without applicant ownership or BBU
  admin authorization.
- Admins can open a pending application and reach a decision without retyping
  the member's email.

## 12. Final Configuration Before Release

These are deployment settings rather than unresolved workflow questions:

- Stable course/certification IDs that qualify for Birth Doula full training
- Stable course/certification IDs that qualify for Birth Doula cross-cert
- Stable course/certification IDs that qualify for Postpartum full training
- Stable course/certification IDs that qualify for Postpartum cross-cert
- BBU credential-review email recipient list
- Final approved certificate labels and artwork for Birth Doula and Postpartum
