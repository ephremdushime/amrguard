# AMRGuard — Technical Architecture and Engineering Standards

**Status:** Architecture reference v1.0  
**Scope:** Target architecture for incremental evolution of the existing repository  
**Important:** This describes intended architecture. It does not assert every component is implemented or validated.

## 1. Architecture decisions

1. Retain current FastAPI, SQLAlchemy, Alembic, PostgreSQL-oriented backend and existing frontend unless evidence supports a change.
2. Begin with a modular monolith and clear domain boundaries. Do not split into microservices prematurely.
3. Treat source EMRs and inventory systems as authoritative for their respective domains.
4. Use synchronous APIs for interactive verification and transaction commands; use durable asynchronous processing for integration events, reminders, analytics and reporting.
5. Make external integrations adapter-based and contract-tested.
6. Use transactional outbox/inbox patterns for reliable event processing.
7. Enforce authentication, authorization and facility scope in backend services, not only in the UI or reverse proxy.
8. Separate operational transaction data from analytics read models where justified.
9. Use synthetic data in development and demonstrations.

## 2. Logical components

### 2.1 Client applications
- Pharmacy workstation interface.
- Stewardship and facility administration dashboard.
- Patient communication/preferences interface.
- Platform operations interface.

Clients must not contain integration secrets. API requests must carry authenticated user credentials or a supported session. Backend remains the policy enforcement point.

### 2.2 API and identity boundary
Responsibilities: authentication and token/session validation; role and facility claims; request validation and rate limiting; API versioning; correlation ID propagation; consistent error envelopes; audit of security-relevant access and actions.

Identity options for pilot must be selected with participating institutions: institutional OIDC/OAuth2 where available, or a controlled pilot identity service with secure credential lifecycle. Do not invent identity provider configuration before partner requirements are known.

### 2.3 Domain modules
Recommended package boundaries:
- identity: users, roles, permissions, sessions and service identities.
- organizations: organizations, facilities, departments and pharmacy locations.
- patient_refs: source-system patient references and minimal necessary demographics.
- integrations: partner registry, credentials, inbox, adapters, mapping and retries.
- prescriptions: orders, items, source provenance, status and validation.
- catalogue: medicine concepts, formulations, units, mappings and versioning.
- dispensing: transactions, items, exceptions and authorization.
- traceability: product, batch and lot details linked to transactions.
- consent: consent evidence, purpose, channel, status and withdrawal.
- messaging: reminder schedules, outbox, provider adapters, callbacks and retries.
- stewardship: rules, alerts, review and intervention records.
- analytics: metric definitions, aggregate read models and reporting.
- audit: append-only audit events and access review.
- platform_admin: deployment configuration, subscriptions and support controls.

Adapt names to actual repository structure after code inspection; do not create parallel duplicate modules.

## 3. Data flow and transaction boundaries

### 3.1 Prescription ingestion
1. Receive partner request over TLS.
2. Authenticate partner identity; validate credential scope and facility mapping.
3. Validate payload schema and partner contract version.
4. Validate source event ID and idempotency key.
5. Store raw/minimized inbound event or safe diagnostic metadata according to retention policy.
6. Map source codes using pre-approved mapping tables.
7. Quarantine unknown or ambiguous codes for authorized resolution.
8. Persist prescription header and all items in one transaction.
9. Record source provenance and integration audit event.
10. Acknowledge only after durable commit.

### 3.2 Dispensing
1. Authenticate staff.
2. Authorize staff against requested facility and pharmacy.
3. Resolve QR/OTP securely; do not accept a credential as proof of staff identity.
4. Confirm order status, expiry, revocation and eligible pharmacy scope.
5. Validate item-level quantity and formulation.
6. Apply idempotency and concurrency controls.
7. Commit dispensing transaction and audit event atomically.
8. Use an outbox event for downstream stock/source-system updates.
9. Reconcile asynchronous partner response; expose pending/failure states.

Do not hold a database transaction open while waiting for a remote RMS or EMR network call. Define reservation, compensation and reconciliation semantics with each partner.

### 3.3 Reminder processing
1. Verify consent and allowed purpose.
2. Read explicit administration instructions from an authoritative source.
3. Reject unsupported or ambiguous schedules for manual resolution; never infer exact dose times from frequency count alone.
4. Generate dose-level reminder occurrences.
5. Persist schedule and outbox messages transactionally.
6. Worker claims messages with leases/locking.
7. Provider adapter submits with stable idempotency key where supported.
8. Callback updates provider delivery status.
9. Retry transient errors with bounded exponential backoff and jitter.
10. Route exhausted failures to dead-letter review.
11. Re-check consent, prescription status and schedule validity immediately before send.

## 4. Core data model

Use UUIDs or equivalent non-guessable internal identifiers. Preserve external identifiers in namespaced fields.

### Organization and access
- organizations(id, name, status)
- facilities(id, organization_id, source_code, name, status)
- pharmacies(id, facility_id, source_code, name, status)
- users(id, identity_subject, status)
- roles(id, code)
- user_role_scopes(user_id, role_id, organization_id, facility_id, pharmacy_id)
- service_clients(id, partner_id, scopes, credential_reference, status)

Access scope must be explicit. Avoid nullable-scope logic that accidentally grants global access.

### Source references
- patient_references(id, source_system, source_patient_id, facility_id, encrypted/minimized attributes)
- practitioner_references(id, source_system, source_practitioner_id, facility_id)
- encounter_references(id, source_system, source_encounter_id, facility_id)

Do not use a locally invented patient identifier as a replacement for source EMR identity.

### Prescription
- prescriptions(id, source_system, source_order_id, patient_reference_id, encounter_reference_id, prescriber_reference_id, facility_id, status, authored_at, valid_until, source_version, provenance)
- prescription_items(id, prescription_id, item_sequence, medicine_concept_id, formulation_id, strength, dose_value, dose_unit, route, explicit_timing, frequency_text, duration, quantity, quantity_unit, prn, indication_reference, instructions, status)
- prescription_events(id, prescription_id, event_type, source_event_id, occurred_at, recorded_at, actor_reference, payload_hash)

Enforce uniqueness on source-system plus source-order ID and partner event identifiers where appropriate. Preserve all prescription items.

### Medicine catalogue
- medicine_concepts(id, coding_system, code, display, version, status)
- formulations(id, medicine_concept_id, strength, dose_form, route, unit_of_measure, pack_definition)
- medicine_mappings(id, source_system, source_code, target_concept_id, mapping_version, approval_status, valid_from, valid_to)

Unknown production codes must be quarantined, not silently created as approved catalogue entries.

### Dispensing and traceability
- dispensing_transactions(id, prescription_id, pharmacy_id, actor_user_id, status, idempotency_key, occurred_at, committed_at)
- dispensing_items(id, transaction_id, prescription_item_id, quantity_dispensed, quantity_unit, formulation_id)
- product_batches(id, product_reference, batch_number, expiry_date, manufacturer_reference, source_system)
- dispensing_batch_links(id, dispensing_item_id, product_batch_id, quantity_from_batch)
- dispensing_events(id, transaction_id, event_type, actor, timestamp, correlation_id)

Support partial dispensing and multiple batches per item. Do not assume one administration equals one stock unit. Quantity validation must account for formulation, packaging, variable doses, liquids, split tablets, loading/tapering and PRN semantics under approved rules.

### Consent and messaging
- consent_records(id, patient_reference_id, purpose, channel, status, captured_at, captured_by, source_reference, evidence_reference, withdrawn_at, policy_version)
- reminder_schedules(id, prescription_id, prescription_item_id, consent_id, timezone, schedule_spec, status, source_version)
- reminder_occurrences(id, schedule_id, due_at, status, deduplication_key)
- message_outbox(id, occurrence_id, provider, destination_token/reference, template_version, status, attempt_count, next_attempt_at)
- message_delivery_events(id, outbox_id, provider_message_id, status, event_at, sanitized_payload_reference)

Protect phone numbers and restrict access. Avoid unnecessary message-body content or sensitive data in logs.

### Stewardship and audit
- stewardship_rules(id, code, version, rule_definition, approval_status, effective_from, effective_to)
- stewardship_alerts(id, rule_id, subject_reference, facility_id, severity, rationale, status, created_at)
- stewardship_reviews(id, alert_id, reviewer_id, disposition, notes_reference, reviewed_at)
- audit_events(id, actor_type, actor_id, action, resource_type, resource_id, facility_id, occurred_at, correlation_id, outcome, metadata_minimized, integrity_reference)

Audit events should be append-only for application roles. Corrections are new events, not destructive edits.

## 5. API design principles

- Version public/partner APIs (for example, /api/v1/...).
- Use OpenAPI contracts and generated client checks where practical.
- Validate input using strict schemas.
- Return consistent errors with machine-readable codes.
- Use pagination and bounded filters.
- Avoid PHI in URLs and query strings.
- Require idempotency for non-repeatable commands.
- Apply object-level authorization to every resource lookup.
- Do not rely on obscurity of UUIDs.
- Add rate limits and abuse monitoring to credential issuance and verification.

Candidate API groups:
- /api/v1/integrations/{partner}/prescriptions
- /api/v1/prescriptions/{id}
- /api/v1/prescriptions/{id}/validation
- /api/v1/pharmacy/verification
- /api/v1/dispensing
- /api/v1/traceability
- /api/v1/consents
- /api/v1/reminder-schedules
- /api/v1/stewardship/alerts
- /api/v1/analytics/...
- /api/v1/admin/...

These are proposed resource boundaries, not a claim that current routes match them. Inspect and map existing APIs before changing route names.

## 6. Interoperability strategy

Use partner-specific adapters behind canonical internal models.

Where the partner supports FHIR R4:
- Map prescription orders to MedicationRequest.
- Map actual supply events to MedicationDispense.
- Use MedicationAdministration only when administration is actually recorded; never infer it from a dispense.
- Use Provenance and AuditEvent concepts as appropriate for origin and security-relevant events.

References:
- FHIR R4 MedicationRequest: https://hl7.org/fhir/R4/medicationrequest.html
- FHIR R4 MedicationDispense: https://hl7.org/fhir/R4/medicationdispense.html
- FHIR R4 Security: https://hl7.org/fhir/R4/security.html

FHIR is a data exchange specification, not an authentication or authorization protocol. Production exchanges require TLS, client authentication, authorization policy, audit, input validation and partner-approved profiles.

For RMS/eLMIS, do not assume an API, stock semantics or reservation capability. Obtain partner documentation and sandbox access. Define whether AMRGuard reads stock, reserves stock, posts decrements or only records dispensing for later reconciliation.

Partner onboarding checklist:
- Technical and business owners.
- API specification and version.
- Authentication and scopes.
- Facility and catalogue mapping.
- Sandbox and synthetic fixtures.
- Error and retry semantics.
- Rate limits and availability commitments.
- Data controller/processor roles.
- Audit and retention requirements.
- Contract tests and sign-off.

## 7. Security architecture

### Authentication and authorization
- Protect every operational endpoint.
- Authenticate human users and service clients separately.
- Apply RBAC plus facility/pharmacy/resource scope.
- Verify scope in service layer for every read and write.
- Deny by default.
- Separate platform administration from clinical access.
- Step-up authentication for sensitive actions if required by policy.

### QR/OTP
- Use cryptographically secure random tokens.
- Store only a hash or keyed digest.
- Bind credential to prescription, intended facility/workflow and expiry.
- Support revocation and replay protection.
- Rate-limit issuance and verification.
- Do not let a patient token authenticate pharmacy staff.

### Integration security
- Per-partner credentials and minimum scopes.
- Secret rotation/revocation.
- TLS and, where agreed, mTLS or signed requests.
- Timestamp/nonce or equivalent replay controls.
- Idempotency and payload integrity.
- Monitoring and alerting.

### Data and infrastructure
- Encryption in transit and at rest.
- Managed secrets; no secrets in source control or browser bundles.
- Safe logs with PHI redaction.
- Secure backups and tested restores.
- Dependency and container scanning.
- Least-privilege database accounts.
- Network segmentation as defense-in-depth, never the only access control.

## 8. Reliability and observability

- Structured logs with correlation IDs.
- Metrics for API latency, errors, ingestion lag, outbox age, provider failures and reconciliation backlog.
- Traces across API, database and partner adapters where feasible.
- Alerts on failed jobs, dead letters, repeated auth failures and integration degradation.
- Health/readiness endpoints that do not leak internals.
- NTP-synchronized clocks.
- Defined RPO/RTO approved by operator.
- Documented backup, restore and disaster-recovery exercises.

## 9. Offline operation

Offline mode is a controlled capability, not a bypass:
- Cache only minimum necessary data.
- Encrypt local storage.
- Define maximum cache age.
- Display last synchronization and stale status.
- Queue uniquely identified events locally.
- Use idempotent synchronization.
- Detect conflicts and never silently overwrite.
- Define approved policy for revoked, expired or unavailable prescriptions.
- Reconcile and audit all offline events after reconnection.

## 10. Testing strategy

Required layers:
1. Unit tests for domain rules and mappings.
2. API tests for validation and error contracts.
3. PostgreSQL integration tests for transaction semantics.
4. Authorization tests for unauthenticated, wrong-role and cross-facility access.
5. Concurrency tests for duplicate and simultaneous dispensing.
6. Contract tests for each partner adapter.
7. Worker tests for retry, duplicate suppression and callbacks.
8. Migration tests from supported schema versions.
9. Container build and startup tests.
10. Backup/restore tests.
11. Security scans and targeted penetration testing.
12. Usability testing with representative staff using synthetic data.

High-risk scenarios:
- Multi-item prescription mapping.
- Unknown catalogue code quarantine.
- Expired/revoked QR/OTP.
- Wrong pharmacy/facility.
- Concurrent duplicate dispensing.
- Partial dispense and multiple batches.
- Remote stock service timeout.
- Duplicate inbound event.
- Prescription cancellation during reminder scheduling.
- Consent withdrawal before send.
- SMS provider timeout and duplicate callback.
- Offline conflict and reconciliation.

## 11. Deployment environments

- **Local development:** synthetic fixtures, local secrets only.
- **CI:** ephemeral database and deterministic tests; no patient data.
- **Demo:** isolated synthetic data, clearly labelled mock integrations.
- **Staging:** partner sandbox where authorized, production-like controls.
- **Pilot:** approved hosting, access controls, monitoring, backups, signed agreements and trained users.
- **Production:** formal operational support, change control, disaster recovery and security review.

Never run migrations against an existing operational database as baseline testing without a verified backup, approved change window and rollback plan.

## 12. Architecture decision records

Create an ADR before material decisions such as identity provider/session model, modular monolith boundaries, event/outbox technology, FHIR version and partner profiles, SMS provider and data-processing terms, offline retention/reconciliation, hosting and disaster recovery, analytics separation, and AI provider/data boundary.

Each ADR records context, options, decision, consequences, owner and date.
