# AMRGuard — Master Product Blueprint

**Status:** Product reference v1.0 | **Initial market:** Rwanda | **Repository:** https://github.com/ephremdushime/amrguard

## 1. Product definition

AMRGuard is an antibiotic-specific interoperability, verification, traceability and stewardship layer that complements existing electronic medical records (EMRs), pharmacy systems and medicine supply systems. It is not a replacement EMR, independent prescribing system or competing inventory ledger.

Its central concept is the **Antibiotic Digital Thread**: an auditable chain of events connecting an authoritative prescription to verification, actual dispensing, product/batch details where available, patient-support activity and stewardship analysis.

AMRGuard must distinguish between:
- **Prescribed:** order recorded by the authoritative clinical system.
- **Received:** order ingested by AMRGuard.
- **Verified:** authenticity, status and workflow conditions checked.
- **Dispensed:** authorized pharmacy actor recorded supply.
- **Administered/taken:** only recorded when an appropriate source reports it.
- **Reminder sent/delivered:** communication event, never proof of ingestion or adherence.

## 2. Problem and intended outcomes

Antibiotic information is fragmented across clinical records, pharmacy workflows, inventory systems and patient communication. This limits reconciliation of prescriptions with dispensing, product-batch traceability, patient support and reliable stewardship indicators.

AMRGuard aims to:
1. Improve completeness and traceability of eligible antibiotic transactions.
2. Make pharmacy verification and dispensing more accountable.
3. Preserve links to source EMR and inventory records.
4. Support consent-based, instruction-driven patient communication.
5. Give authorized stewardship teams reliable utilization and workflow indicators.
6. Enable governed aggregate intelligence across participating facilities.

Do not claim traceability alone reduces AMR. Clinical and epidemiological impact requires appropriate evaluation.

## 3. Product principles

1. **Interoperate, do not replace.** Source EMRs remain authoritative for clinical prescriptions and patient identity. Inventory systems remain authoritative for stock balances.
2. **Clinical safety before automation.** AMRGuard must not independently prescribe, diagnose, change or discontinue treatment.
3. **Least data necessary.** Prefer source-system references and minimum necessary data over duplicating patient records.
4. **Human accountability.** Dispensing and clinical review require authenticated, authorized human actors.
5. **Every state change is auditable.** Preserve provenance, timestamps, actor, facility and correlation identifiers.
6. **No fabricated integration.** Mocks and canonical contracts must be labelled; partner integration is not live until authorized and tested.
7. **Resilience with explicit limits.** Offline workflows expose stale data and apply approved safety policies.
8. **Evidence-based analytics.** Every metric has a definition, denominator, scope and data-quality caveat.
9. **Privacy by design.** No patient identifiers or clinical details in QR codes, public URLs, unsecured logs or analytics prompts.
10. **Incremental delivery.** Secure the existing foundation before advanced AI or national-scale infrastructure.

## 4. Users and responsibilities

| User | Responsibilities | Access boundary |
|---|---|---|
| Prescriber | Creates/updates order in source EMR; supplies indication and instructions | Clinical actions remain in source EMR |
| Pharmacist | Verifies order, checks stock, records actual dispensing and batch details | Authorized pharmacy/facility only |
| Pharmacy assistant/reception | Supports retrieval and patient flow | No clinical approval or dispensing privilege unless separately authorized |
| Stewardship officer | Reviews alerts, utilization and intervention indicators | Assigned institution or approved aggregate scope |
| Facility administrator | Manages local users, configuration and reports | Facility-scoped administration |
| National/programme analyst | Reviews approved aggregate indicators | No default identifiable patient access |
| Patient | Receives instructions, manages preferences and reports concerns | Own approved patient-facing information |
| Platform operator | Manages technical service, integrations and subscriptions | No implicit clinical-data access |

## 5. Product modules

### 5.1 EMR interoperability
- Secure prescription intake and status synchronization.
- Source patient, practitioner, encounter and facility references.
- Terminology and medicine catalogue mapping.
- Multi-item prescription preservation.
- Duplicate-event protection and replay handling.
- Versioned partner-specific connectors and contract tests.
- FHIR/REST/HL7 only as supported by the partner's actual specification.

### 5.2 Prescription validation and stewardship rules
- Validate source, prescriber and facility references.
- Validate required medication and instruction fields.
- Check catalogue mapping and formulation.
- Detect missing indication, missing instructions and possible duplicate active orders.
- Support configurable, versioned institutional rules.
- Categorize findings as informational, review-required or hard validation failure.
- Clinical rules require qualified approval; alerts must be explainable.
- Do not silently edit or block prescriptions unless an approved policy and authorized workflow explicitly require it.

### 5.3 Pharmacy verification and dispensing
- Retrieve prescription using a short-lived QR/OTP reference.
- Authenticate staff and enforce facility/pharmacy membership.
- Verify order status, expiry, cancellation and prior dispensing.
- Record full, partial, refused or unavailable dispensing outcomes.
- Record actual quantity, formulation and product details.
- Support multiple prescription items and partial fulfilment.
- Use database transactions, idempotency keys and concurrency controls.
- Emit a dispensing event to the source system where the partner contract supports it.

### 5.4 Product and batch traceability
Capture product identifier, generic/brand, strength, form, manufacturer, batch/lot and expiry where available. Record source and confidence for each field. Do not describe pharmacy-level batch capture as end-to-end supply-chain serialization.

### 5.5 Patient support and SMS
- Record consent source, purpose, timestamp, channel and withdrawal.
- Schedule reminders only from explicit, authoritative instructions.
- Support prescribed times/intervals, start, duration, timezone, PRN and treatment changes.
- Use durable outbox, worker, provider adapter, retries, callbacks and duplicate prevention.
- Stop future reminders after cancellation/discontinuation or consent withdrawal.
- Provide opt-out and appropriate language/privacy settings.
- Distinguish queued, submitted, delivered, failed and patient-reported events.
- SMS delivery is not proof of medication ingestion or adherence.

### 5.6 Stewardship analytics
- Antibiotic utilization and dispensing trends.
- Prescription completeness and exception rates.
- AWaRe categorization using a maintained, versioned reference.
- DDD and DOT only where definitions and source data support valid calculation.
- Facility/department comparisons under approved access controls.
- Stewardship review workflow and documented interventions.
- Every metric includes period, numerator, denominator, scope, exclusions and data quality.

### 5.7 AI assistance
Initial use cases:
- Explain missing/inconsistent prescription fields.
- Summarize aggregate trends for authorized users.
- Detect candidate anomalies for human review.
- Retrieve approved guidelines with source/version citations.

AI controls:
- No autonomous prescribing, diagnosis, discontinuation or dispensing authorization.
- No unapproved clinical recommendation generation.
- No identifiable patient data sent to unapproved external models.
- Permission-filter all data before retrieval.
- Record model/version, prompt template, sources and output where appropriate.
- Evaluate accuracy, hallucination, bias, privacy leakage and human override.
- Statistical baselines and transparent rules precede predictive ML.

### 5.8 Institutional and national reporting
Provide facility dashboards first. Cross-facility reporting requires approved governance, aggregation, minimum-cell suppression where appropriate and documented permitted purposes. Laboratory resistance surveillance is a separate integration domain; AMRGuard must not imply it measures resistance without validated microbiology data.

## 6. Core user journeys

### A. Prescription-to-dispensing
1. Prescriber creates or updates an order in the source EMR.
2. Source system sends an authenticated event to AMRGuard.
3. AMRGuard validates schema, source, facility, mappings and idempotency.
4. Invalid/unmapped events are quarantined for authorized resolution; do not auto-create trusted catalogue entities from unknown codes in production.
5. Pharmacy staff authenticate and retrieve the order.
6. AMRGuard verifies current order status and pharmacy scope.
7. Pharmacist records actual item-level dispensing and batch details.
8. Transaction commits atomically; stock-system interaction follows the partner contract.
9. An auditable event and permitted status update are emitted.
10. Exceptions remain visible and reconcilable.

### B. Patient reminder
1. An authorized workflow captures and verifies consent.
2. A valid treatment event and explicit instructions are available.
3. Schedule engine validates timing and timezone.
4. Reminder jobs are written to a durable outbox.
5. Worker sends via approved SMS provider.
6. Provider callbacks update delivery status.
7. Cancellation, instruction change or consent withdrawal suppresses future messages.
8. Reports distinguish delivery from adherence.

### C. Stewardship review
1. Data pipeline produces governed indicators.
2. Rule or analytics service flags a pattern with rationale and data window.
3. Authorized reviewer inspects source records in their permitted scope.
4. Reviewer records disposition and any intervention.
5. Dashboard reports review status and outcome without overstating clinical impact.

## 7. System boundaries and source of truth

| Data domain | Authority |
|---|---|
| Patient identity and clinical encounter | Source EMR |
| Prescription and clinical instruction | Source EMR / authorized prescriber workflow |
| Actual dispensing record | Authorized pharmacy workflow, reconciled with source system |
| Stock balance | RMS/eLMIS or institutional inventory system |
| Product/batch details | Approved product/inventory source and dispensing capture |
| Consent for AMRGuard messaging | Approved consent workflow/source, with evidence |
| AMRGuard access, integration and audit events | AMRGuard |
| Aggregate indicators | Derived, governed AMRGuard analytics |

## 8. Non-functional requirements

- Strong authentication and facility-scoped authorization on every operational endpoint.
- TLS for production data exchange.
- Encryption at rest and protected secrets.
- Idempotent integration and dispensing operations.
- Database transaction integrity and concurrency safety.
- Durable background jobs and dead-letter handling.
- Observability without leaking patient data.
- Tested backup restoration and disaster recovery.
- Accessible, low-bandwidth, responsive interfaces.
- Versioned APIs, migrations and documentation.
- Defined retention, deletion and incident response policies.

## 9. Pilot strategy

Planning hypothesis only; facility participation and scope must be confirmed:
- 2–3 facilities.
- Approximately 40–60 healthcare professionals.
- Three months of controlled implementation.
- Synthetic data during engineering and demonstration.
- Real patient data only after institutional authorization, privacy/security review, data-sharing agreements, clinical governance and ethics determination where applicable.

Pilot measures:
- Eligible prescription traceability completeness.
- Ingestion and integration success.
- Dispensing record completeness.
- Batch-field completeness where supported.
- Duplicate/reconciliation exceptions.
- User adoption and usability.
- Stewardship review completion.
- SMS consent and delivery metrics.
- Implementation and support costs.

## 10. Commercial model

Potential revenue: institutional subscription; implementation and onboarding; integration services; hosting, maintenance and support; government/programme contracts; funded pilots and approved reporting services.

Do not sell identifiable patient data. Define licensing, hosting, integration, support and data-processing responsibilities separately in contracts.

## 11. Product success

AMRGuard succeeds when a participating facility can reliably reconcile an eligible antibiotic prescription with its verification and actual dispensing events; authorized staff can act safely; patient communication is consent-based and accurate; and stewardship teams can use validated indicators to improve workflows.

## 12. Engineering governance

Every change must start from repository inspection and a scoped issue; preserve working behavior unless a change is justified; include tests and migrations where relevant; include authorization and tenant-boundary tests; document API/schema changes; report exact tests and outcomes; identify limitations; and be reviewed through a pull request.

**Release rule:** Audit → Secure → Validate → Controlled pilot → Evaluate → Scale.
