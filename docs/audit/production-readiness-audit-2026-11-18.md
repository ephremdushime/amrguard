# AMRGuard production-readiness audit

**Audit date:** 2026-11-18  
**Repository reviewed:** `ephremdushime/amrguard`  
**Reviewed ref:** `main`  
**Review type:** Static source/configuration review through GitHub. No code was executed; no tests, migrations, container builds, penetration tests, or live integrations were run.

## Executive assessment

AMRGuard has a credible MVP foundation for antibiotic prescription intake, pharmacy dispensing control, batch traceability, audit events, stewardship review tasks, and canonical integration contracts. It is not ready for real patient data or live hospital operations.

The primary release blockers are unauthenticated operational APIs, absent user/role authorization, and incomplete reminder delivery. The repository should be hardened in place; a rewrite is not justified by this review.

## Findings

### P0 — Blockers before any real-patient pilot

1. **Operational API routes lack authentication and authorization.** The integration-key dependency is applied to e-Buzima prescription intake and RMS stock events, and selected stewardship/analytics routes. Prescription reads, prescription lists, pharmacy/stock reads, credential issuance, verification, activation, dispensing, transactions, traceability, FHIR exports, audit events, and reminder listing are not consistently protected. The frontend's `apiHeaders` is an empty object. The reverse proxy forwards `/api/` to the backend without an identity gateway configuration in this repository. A deployment behind a private network is not a substitute for application-level authorization. Implement authenticated staff sessions or an institution-approved identity gateway with server-side role enforcement on every route; enforce facility/pharmacy tenancy and least privilege.

2. **Credential issuance and dispensing can be invoked without an authenticated staff identity.** The credential endpoint issues a QR/OTP for eligible prescriptions, and the dispense endpoint accepts a credential plus a pharmacy ID but does not establish which authenticated staff member is acting. Before a pilot, bind actions to authenticated prescriber/pharmacy users, facility scope, approved pharmacy membership, and immutable actor identity in audit events.

3. **Reminder feature is not a dose-reminder service and cannot send SMS.** The current reminder model allows one reminder per prescription. The scheduling endpoint sets a single `scheduled_at` at the end of the course, rather than creating each prescribed dose event. It returns `PENDING_PROVIDER` and explicitly reports `delivery_configured: false`; there is no SMS provider adapter, worker/queue, retry policy, delivery callback, or delivery reconciliation. Do not present this as patient adherence messaging. Design a dose schedule per prescription item from explicit prescriber instructions, then a durable outbox/worker with consent validation, approved message templates, provider delivery callbacks, retries, opt-out handling, and delivery audit. A reminder sent or delivered must not be represented as proof of ingestion.

4. **Consent evidence is not independently verified.** The endpoint accepts a boolean and caller-supplied `consent_reference`. Integrate with an approved consent capture/source-of-truth process and verify consent status, purpose, channel, language, timestamp, withdrawal, and contact resolution before dispatch.

### P1 — Required before a controlled pilot

5. **FHIR mapping loses multi-item prescriptions.** `prescription_to_medication_request` reads only `rx.items[0]`. The core supports multiple prescription items, so the FHIR export is incomplete for multi-item orders. Return a Bundle or documented collection of MedicationRequest resources and validate against the partner's agreed FHIR version/profiles/terminologies.

6. **Frequency-per-day is insufficient for reliable dose scheduling.** The prescription schema stores `frequency_per_day`, not explicit administration times, interval, start time, timezone, PRN status, or patient-specific instructions. Do not infer an exact every-12-hour schedule from a count alone. Agree a canonical regimen contract with source EMRs; retain source timing instructions and map them to a validated schedule.

7. **Catalog records can be created from inbound payloads.** Prescription intake dynamically creates facilities, prescribers, and antibiotics when unknown codes arrive. This is useful for demos but unsafe as a production trust model. Require pre-provisioned/approved facility, prescriber, and medicine catalog mappings; quarantine unknown values for reconciliation rather than silently treating them as trusted.

8. **Clinical quantity validation assumes one unit per administration.** The validation service explicitly assumes unit-dose solid forms and computes frequency × duration. It does not safely cover liquids, packs, variable dose units, split tablets, loading doses, tapering regimens, or PRN orders. Keep it as a narrow transaction check; do not present demo thresholds as clinical decision support. Obtain clinical governance and a verified formulary/ruleset before enabling clinical rules.

9. **Single shared integration secret is only a starter control.** Use partner-specific credentials, scopes, key rotation, request signing or an approved OAuth2/mTLS mechanism, replay protection, rate limiting, and per-source monitoring. Never place integration credentials in browser code.

10. **Dispensing concurrency and replay behavior need database-backed tests.** The dispense flow uses row locking and idempotency keys, but correctness must be demonstrated on the actual PostgreSQL deployment and under concurrent duplicate requests. Add transaction rollback, concurrent stock decrement, duplicate idempotency key, expired credential, wrong-pharmacy, and partial-dispense tests.

11. **Audit and data-access endpoints expose sensitive operational details unless protected.** The review list includes patient references and facility identifiers; prescription and traceability responses expose external identifiers. Apply role/facility-scoped authorization, data minimization, retention controls, and audit access logging.

12. **FHIR and other integration contracts are canonical AMRGuard contracts only.** The repository correctly states that live e-Buzima/RMS endpoints and mappings are not certified. Obtain signed-off partner schemas, sandbox credentials, field mapping, retry/acknowledgement behavior, and end-to-end contract tests before describing an integration as live.

### P2 — Operational maturity

13. Add structured logs, metrics, alerting, request correlation, integration failure queues, dead-letter handling, and incident procedures.
14. Complete tested backup/restore, migration rollback strategy, disaster recovery objectives, secrets management, TLS/identity gateway configuration, and security testing.
15. Add CI workflows and enforce backend tests, frontend typecheck/build, migration checks, dependency/security scans, and container checks on every pull request. The repository's Actions runs endpoint returned zero workflow runs at the time of review; this is not evidence that local tests pass or fail.
16. Establish pilot governance: data controller/processor roles, DPIA/privacy review, ethics determination where research is intended, clinical safety owner, incident reporting, training, SOPs, and facility acceptance criteria.

## Positive foundations worth retaining

- FastAPI and SQLAlchemy backend with Alembic migrations.
- PostgreSQL-oriented sandbox and production Compose configurations.
- Canonical prescription and stock-event APIs protected by an integration-key check.
- QR/OTP credential hashing and expiry.
- Quantity checks, stock checks, dispense transaction records, and idempotency support.
- Batch-to-transaction traceability and audit event model.
- Stewardship review queue and consent-aware reminder outbox model.
- Synthetic-data partner sandbox and funder-demo deployment separation.
- Documentation that explicitly distinguishes canonical contracts from live institutional integrations.

## Recommended remediation sequence

1. **Security boundary first:** implement authentication, role/facility authorization, protect every data/action route, and test anonymous access is denied.
2. **Pilot workflow hardening:** validate pharmacy onboarding, credential lifecycle, dispensing transactions, concurrency, idempotency, and audit actor attribution on PostgreSQL.
3. **Integration adapters:** implement one partner-approved e-Buzima adapter and one RMS/eLMIS adapter against actual sandbox specifications; preserve canonical internal contracts.
4. **Patient messaging:** redesign reminder data model as per-dose schedules and outbox events; integrate SMS provider sandbox, consent source, callbacks, retries, opt-out, and delivery status.
5. **Clinical governance:** approved catalog, terminology, unit conversion, regimen mapping, stewardship protocols, and clinical safety sign-off.
6. **Deployment validation:** CI, security testing, backup/restore rehearsal, monitoring, runbooks, and controlled site acceptance.

## Pilot gate

Do not process real patient data or enable live dispensing through AMRGuard until P0 findings are closed, the partner integrations are approved, P1 workflow tests pass on the target deployment, and the institution's clinical, privacy, security, and operational owners have signed off. Start with synthetic data and a restricted partner environment while approvals are pending.

## Scope boundary

This audit is a static review of the current repository snapshot. It is not a penetration test, clinical validation, regulatory determination, legal opinion, or certification of the deployed system.
