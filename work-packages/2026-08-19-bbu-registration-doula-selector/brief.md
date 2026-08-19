# Build Brief — Fix BBU registration doula Yes/No selector

## Outcome

Repair the required registration question on the real BBU learner signup flow so a new visitor can independently select Yes or No for the doula-professional question with mouse, touch, or keyboard, retain the selected value, clear validation, and advance registration without weakening any other required field.

## Active Scope and Repository

- Scope: `client:cfd-bbu-ar`
- Work-package root: `.`
- Implementation repository/environment: `/srv/t3-workspace/clients/cfd-bbu-ar/repos/learnhouse-bbu`, branch `exec/2026-08-14-indira-certificate-support`; production `https://learn.birthandbabyuniversity.com/`; exact route to be resolved from the anonymous Breastfeeding class signup/login flow.

## Evidence Reviewed

- `/srv/t3-workspace/shared-memory/runtime-core.md`, client `AGENTS.md`, `context.json`, client scope and knowledge status.
- Repository `CONTRIBUTING.md`, `README.md`, app manifests, and current Git status; no nested repository instructions were present.
- Owner-provided Gmail thread `1a01b94b83f28f85`: Miranda reports Yes and No cannot be selected on phone, computer, or desktop download program; prior workaround created learner 3893, but the global field defect remains.
- Live reproduction is a required pre-edit gate and will be recorded here before implementation, with desktop and mobile viewport evidence and no account/charge creation.

## Requirements

- Both options are independently selectable by pointer/touch and keyboard.
- The selected value persists in the controlled form state and is represented by the correct submitted value.
- Required-field validation appears when unanswered and clears after either option is selected; other required fields remain enforced.
- Registration can advance/submit from the exact production route without unintended account creation or charge during verification.
- Focus indication and accessible labels/association remain present.
- Focused automated coverage covers Yes, No, unanswered regression, and keyboard/pointer interaction.

## Non-Goals

- Do not remove the question or its required validation.
- Do not change account, enrollment, billing, course-access, authentication, or unrelated registration fields.
- Do not send email or modify the existing Miranda thread.
- Do not create infrastructure or alter credentials.

## Architecture and Data Flow

The web registration component is the source of truth for the two-option control and form validation; the API registration contract remains authoritative for the submitted field name/value. Reuse the existing form primitives and update only the broken control wiring/markup/style and the minimum matching server validation if live/source evidence proves it is required. A pointer/keyboard event updates the controlled form state, validation consumes that state, and the existing registration request receives the selected Yes/No value. Failure states are an unanswered required field (validation error) or a rejected request; neither is bypassed.

## Integrations and Provider Boundaries

Production deployment is the existing authenticated BBU platform deployment path for this repository. No new provider, model, integration, credential, or infrastructure is introduced.

## Security and Client Isolation

Work is limited to client `cfd-bbu-ar`, the registered LearnHouse BBU repository, and the named production host. No credentials are read into output or committed. Anonymous verification uses synthetic, new-user-safe values and stops before account creation or charge. The owner explicitly authorized implementation and deployment of this named production bug fix; deployment is the bounded yellow effect. Existing authenticated deployment credentials and client scopes are reused without modification.

## Assumptions and Decisions

The active implementation repository is the `learnhouse-bbu` entry in `context.json`; the mobile shell and preview wrapper are not separate production sources. The current Git revision is the recovery point; deployment rollback is to the prior healthy revision. No unresolved product choice is known—the exact route and root cause will be established by live/source reproduction.

## Acceptance Criteria

- [x] Live anonymous route reproduced pre-edit at desktop and mobile, with the selector failure and exact root cause documented.
- [x] Yes and No are selectable by pointer/touch/keyboard, persist in state, show focus, and clear only the targeted required validation.
- [x] Automated tests cover both values and unanswered regression without weakening other required fields.
- [x] Relevant lint/type/unit/component/e2e checks pass.
- [x] Verified revision is deployed to production and fresh desktop/mobile destination checks after deployment confirm Yes and No paths advance without unintended accounts/charges.
