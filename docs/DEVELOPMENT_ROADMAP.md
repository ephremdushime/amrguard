# AMRGuard — Development Roadmap, Work Packages and Acceptance Criteria

**Status:** Engineering execution reference v1.0  
**Strategy:** Audit → Secure → Validate → Controlled pilot → Evaluate → Scale  
**Rule:** Do not start all workstreams simultaneously. Complete dependencies and evidence gates.

## 1. Current baseline and known blockers

The prior repository review was static inspection. It did not execute tests, migrations, Docker builds, penetration tests or live integrations.

Findings to verify and remediate:
- Operational API routes did not consistently enforce authentication and authorization.
- Credential issuance and dispensing did not adequately bind authenticated staff identity, role and facility scope.
- Frontend API headers were empty in the inspected implementation.
- Reminder functionality was not a complete dose-level SMS service; provider adapter, worker, callbacks, retries and reconciliation were not implemented in the reviewed baseline.
- Consent was represented by caller-supplied data without independent evidence verification.
- FHIR mapping handled only the first prescription item in the reviewed code.
- Inbound unknown codes could be dynamically created rather than quarantined for approval.
- Quantity assumptions may not support all formulations and dosing patterns.
- Integration secrets and replay protections require strengthening.
- Database concurrency and transaction behavior need PostgreSQL integration tests.

These findings must be checked against the current branch before coding. Do not assume they have been fixed.

## 2. Workstream priorities

- **P0 — Safety/security blockers:** close before real patient data or live dispensing.
- **P1 — Pilot-critical capability:** needed for a controlled institutional pilot.
- **P2 — Value expansion:** stewardship analytics, advanced interoperability and AI.
- **P3 — Scale:** national and regional operations.

## 3. Phase 0 — Baseline and repository stabilization

Tasks:
- [ ] Confirm target branch and latest commit.
- [ ] Inspect repository structure and current audit PR.
- [ ] Create reproducible backend environment.
- [ ] Run backend test suite and record exact result.
- [ ] Install frontend dependencies using lockfile.
- [ ] Run frontend typecheck and production build.
- [ ] Review Alembic migration chain and head.
- [ ] Build and start Docker Compose in isolated local environment.
- [ ] Identify missing and flaky tests.
- [ ] Produce issue-by-issue defect register.

Acceptance:
- Baseline report contains commands, environment versions, pass/fail output and known gaps.
- No production database is modified.
- Existing demo behavior and current APIs are documented.
- No claim of passing tests without actual logs.

## 4. Phase 1 — P0 identity, authorization and audit

### P0.1 Identity strategy
- [ ] Select pilot identity model with institutional stakeholders.
- [ ] Define human-user and service-client authentication separately.
- [ ] Define role and facility/pharmacy scope model.
- [ ] Define credential lifecycle, expiry, revocation and recovery.
- [ ] Keep secrets out of browser bundles and source control.

Acceptance: identity flow documented; token/session validation tested; disabled/revoked accounts denied.

### P0.2 Route inventory and protection
- [ ] Inventory every operational API route.
- [ ] Classify public, authenticated, partner-service and admin endpoints.
- [ ] Apply authentication dependencies consistently.
- [ ] Apply resource-level and facility-level authorization.
- [ ] Deny by default.
- [ ] Verify reads, exports, audit and reminder endpoints as well as writes.

Acceptance tests:
- Unauthenticated request is denied.
- Wrong role is denied.
- User from facility A cannot read or mutate facility B data.
- Pharmacy user cannot perform platform administration.
- Service client accesses only explicitly scoped integration endpoints.

### P0.3 Dispensing actor and credential binding
- [ ] Require authenticated dispensing actor.
- [ ] Verify actor is active and assigned to requested facility/pharmacy.
- [ ] Bind QR/OTP to prescription and intended workflow, not staff identity.
- [ ] Enforce expiry, revocation, rate limits and replay protection.
- [ ] Record actor, facility, pharmacy, event time and outcome.

Acceptance: no dispense can be committed without valid staff authorization and correct facility scope.

### P0.4 Transaction integrity
- [ ] Add idempotency constraints.
- [ ] Use database transactions for dispensing state changes.
- [ ] Protect against concurrent duplicate dispensing.
- [ ] Define partial dispensing and cancellation semantics.
- [ ] Add PostgreSQL integration tests.
- [ ] Verify rollback behavior on failure.

Acceptance: concurrent duplicate requests create at most one valid transaction; failures do not leave partial dispensing state.

### P0.5 Audit
- [ ] Define audit event schema.
- [ ] Capture security-sensitive reads and writes as policy requires.
- [ ] Make audit records append-only to normal application roles.
- [ ] Protect audit access and minimize sensitive metadata.
- [ ] Add correlation IDs and clock synchronization.

Acceptance: tests demonstrate attribution for credential issuance, verification, dispensing, cancellation, privileged access and configuration changes.

## 5. Phase 2 — Core traceability and integration reliability

### P1.1 Prescription ingestion
- [ ] Validate partner identity, schema and facility mapping.
- [ ] Preserve every prescription item.
- [ ] Preserve source order ID, source version and provenance.
- [ ] Add idempotent event ingestion.
- [ ] Quarantine unknown or ambiguous medicine/facility/practitioner codes.
- [ ] Add reconciliation view for failed events.

Acceptance: duplicate source event does not duplicate an order; all items survive mapping; unknown codes cannot silently become approved catalogue entries.

### P1.2 Catalogue and quantity model
- [ ] Define medicine concept and formulation model.
- [ ] Define units of measure and packaging.
- [ ] Support liquids, packs, injectables, split tablets and other approved forms.
- [ ] Represent explicit dose, route, timing, duration, quantity and PRN instructions.
- [ ] Version and approve source mappings.

Acceptance: representative formulation cases calculate and validate quantities correctly; ambiguous cases require manual resolution.

### P1.3 Dispensing and batch traceability
- [ ] Record actual quantity dispensed per prescription item.
- [ ] Support full and partial dispensing.
- [ ] Support multiple batches per item.
- [ ] Record expiry and product source where available.
- [ ] Define stock integration contract and reconciliation behavior.
- [ ] Emit downstream events through outbox.

Acceptance: end-to-end synthetic test reconstructs prescription → verification → item-level dispense → batch links → reconciliation history.

### P1.4 Partner adapters
- [ ] Obtain official e-Buzima integration specification and sandbox access.
- [ ] Confirm source of truth and status update contract.
- [ ] Obtain RMS/eLMIS interface specification and sandbox access.
- [ ] Implement adapters only against approved contracts.
- [ ] Add contract tests and integration monitoring.

Acceptance: partner sandbox test evidence and sign-off. Until then, connector remains mock/canonical and is labelled accordingly.

## 6. Phase 3 — Patient consent and SMS

### P1.5 Consent evidence
- [ ] Define consent purpose, channel, language and evidence requirements.
- [ ] Integrate approved consent source or capture workflow.
- [ ] Record capture actor, timestamp, policy version and withdrawal.
- [ ] Re-check consent immediately before sending.

Acceptance: no message without valid consent for the relevant purpose/channel; withdrawal suppresses future sends.

### P1.6 Dose-level schedule model
- [ ] Define explicit schedule schema and timezone.
- [ ] Support start, end, prescribed times/intervals, PRN and instruction changes.
- [ ] Reject unsupported or ambiguous schedules.
- [ ] Link each occurrence to prescription item and source version.
- [ ] Cancel/recompute schedule on prescription update or discontinuation.

Acceptance: schedule generation matches test prescriptions exactly; no guessed schedule from frequency count alone.

### P1.7 Messaging infrastructure
- [ ] Select approved SMS provider and assess data-processing terms.
- [ ] Implement provider adapter.
- [ ] Implement durable outbox and worker.
- [ ] Add bounded retry with backoff.
- [ ] Add delivery callbacks and reconciliation.
- [ ] Add idempotency and duplicate suppression.
- [ ] Add opt-out and failed-message review.
- [ ] Add language-reviewed templates.

Acceptance: tests cover provider success, transient/permanent failure, duplicate callback, retry exhaustion, consent withdrawal and prescription cancellation.

### P1.8 Patient education
- [ ] Draft approved patient information in relevant languages.
- [ ] Obtain clinical review.
- [ ] Test comprehension and readability.
- [ ] Ensure messages do not reveal sensitive diagnoses on shared phones.

Acceptance: clinical sign-off and user testing completed before patient-facing rollout.

## 7. Phase 4 — Stewardship and reporting

### P2.1 Metric dictionary
- [ ] Define each metric, numerator, denominator, exclusions and time window.
- [ ] Define facility and department attribution.
- [ ] Define AWaRe reference version.
- [ ] Define valid use cases for DDD and DOT.
- [ ] Define minimum data-quality thresholds.

### P2.2 Dashboards
- [ ] Prescription completeness.
- [ ] Prescription-to-dispense traceability.
- [ ] Partial dispensing and exceptions.
- [ ] Antibiotic class and AWaRe distribution.
- [ ] Review queue and intervention outcomes.
- [ ] Integration and data-quality status.

Acceptance: dashboard values reconcile with synthetic source records and are permission-filtered.

### P2.3 Stewardship workflow
- [ ] Version clinical rules.
- [ ] Assign clinical approver and effective dates.
- [ ] Record alert rationale and source data.
- [ ] Add review disposition and intervention tracking.
- [ ] Monitor false-positive burden.

Acceptance: clinical governance approval; reviewer actions auditable; alerts are not represented as diagnoses.

## 8. Phase 5 — AI capabilities

Before any AI feature:
- [ ] Define intended use and prohibited use.
- [ ] Identify data classification and model data boundary.
- [ ] Create representative evaluation dataset with synthetic/de-identified data.
- [ ] Define accuracy, calibration, false-positive and failure metrics.
- [ ] Add human review and override.
- [ ] Log model/version and evidence sources.
- [ ] Perform privacy and security review.

Initial features:
- Missing-field explanation assistant.
- Aggregate natural-language analytics.
- Explainable anomaly candidate detection.
- Evidence-linked guideline retrieval.

Acceptance: evaluation report approved; model cannot mutate prescriptions or authorize dispensing; outputs disclose uncertainty and source limitations.

## 9. Phase 6 — Pilot readiness

Governance prerequisites:
- [ ] Identify facility sponsor and clinical safety owner.
- [ ] Confirm controller/processor responsibilities.
- [ ] Complete privacy impact assessment and applicable regulatory steps.
- [ ] Obtain data-sharing and integration agreements.
- [ ] Obtain ethics determination if research/evaluation requires it.
- [ ] Approve clinical SOPs and escalation paths.
- [ ] Train users and document competency.
- [ ] Establish incident response and support arrangements.

Technical prerequisites:
- [ ] All P0 issues closed.
- [ ] PostgreSQL integration tests pass.
- [ ] Staging deployment repeatable.
- [ ] Security assessment completed.
- [ ] Backups and restore tested.
- [ ] Monitoring and alerting active.
- [ ] Synthetic acceptance testing signed off.
- [ ] Rollback and downtime procedures rehearsed.

Pilot design hypothesis:
- 2–3 facilities.
- Approximately 40–60 healthcare professionals.
- Three months.
- RE-AIM evaluation structure.
- Synthetic data during development; real data only after all approvals.

Pilot outcomes: adoption/reach; workflow fidelity; prescription traceability completeness; dispensing documentation quality; integration reliability; user experience; SMS consent/delivery performance; cost/support burden; implementation barriers and unintended effects.

These numbers are planning assumptions, not commitments or confirmed partners.

## 10. Phase 7 — Scale readiness

- [ ] Demonstrated pilot value and safety.
- [ ] Approved national interoperability approach.
- [ ] Capacity and performance testing.
- [ ] Multi-facility tenant isolation assessment.
- [ ] Disaster recovery exercise.
- [ ] Support and service-level model.
- [ ] Sustainable procurement and pricing plan.
- [ ] Change management and release governance.
- [ ] Independent security review.
- [ ] National reporting governance.

## 11. Suggested GitHub issue breakdown

1. P0 route inventory and endpoint classification.
2. P0 authentication dependency coverage.
3. P0 facility/pharmacy authorization enforcement.
4. P0 authenticated dispensing actor attribution.
5. P0 QR/OTP expiry, revocation and replay controls.
6. P0 dispensing idempotency and concurrency tests.
7. P0 audit event completeness.
8. P1 multi-item FHIR mapping.
9. P1 unknown catalogue code quarantine.
10. P1 formulation-aware quantity model.
11. P1 item-level dispensing and batch linkage.
12. P1 partner inbox/outbox and reconciliation.
13. P1 consent evidence and withdrawal.
14. P1 explicit dose-level schedule model.
15. P1 SMS provider adapter and worker.
16. P1 retries, callbacks and dead-letter handling.
17. P2 stewardship metric dictionary.
18. P2 facility dashboards and role filtering.
19. P2 clinical rule governance workflow.
20. P2 AI evaluation and safety gate.
21. Pilot DPIA, SOP and operational readiness pack.

## 12. Release gates

| Gate | Required evidence | Allowed environment |
|---|---|---|
| G0 Baseline | Reproducible tests and defect register | Local/CI |
| G1 Secure core | AuthZ, audit, transaction and concurrency tests | Synthetic staging |
| G2 Traceability | End-to-end prescription/dispense reconciliation | Synthetic staging |
| G3 Patient messaging | Consent, schedule, provider and callback tests | Provider sandbox |
| G4 Pilot readiness | Governance approvals, security review, restore test, SOPs | Authorized pilot |
| G5 Scale readiness | Pilot evaluation, operational support, capacity and DR evidence | Production planning |

**Hard stop:** No real patient data or live clinical dispensing until G1, G2, applicable governance prerequisites and facility authorization are satisfied. Patient messaging additionally requires G3 and approved consent/provider arrangements.

## 13. Definition of done for every pull request

A PR is complete only when it includes:
- Scoped problem statement and issue link.
- Code and migration where required.
- Tests for normal, invalid and unauthorized cases.
- Security and privacy impact notes.
- Updated API and architecture documentation.
- Actual test command output.
- Deployment and rollback notes.
- Known limitations.
- Reviewer approval.

A green frontend build alone is not evidence of clinical safety or production readiness.
