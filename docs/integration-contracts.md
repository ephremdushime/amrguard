# AMRGuard Integration Contracts

This document defines the AMRGuard-side canonical HTTP contracts. It is not an e-Buzima, RMS/eLMIS, pharmacy, identity-provider, or SMS-provider specification. The external system owner must approve field mappings, credentials, transport security, retry behavior, and production certification before an adapter is enabled.

## Authentication and transport

- Use HTTPS between every system boundary.
- Server-to-server intake requests must send `x-amrguard-integration-key` with the provisioned secret. Rotate the secret under the institution's key-management policy.
- Never expose the integration key in browser code, `VITE_*` build variables, browser storage, or frontend JavaScript. Use it only in an approved server-side adapter or partner test client.
- Do not expose the API directly to the public internet. Put the web/API behind the institution's identity-aware gateway and role authorization.
- Each inbound event must have a stable source identifier. Reuse of an identifier with the same payload is an idempotent replay; reuse with changed content is a conflict.

## e-Buzima prescription intake

`POST /api/v1/integrations/ebuzima/prescriptions`

Required fields are `external_id`, `patient_reference`, `prescriber`, and one or more `items`. Each item carries the canonical medicine code, product description, dose, frequency/day, duration, quantity, and indication. `expires_at` is optional but, when present, must be future-dated. Quantity/rule failures return a persisted blocked/warning decision and issue list; duplicate `external_id` returns the existing prescription without creating a second order.

```json
{
  "external_id": "EBZ-RX-000123",
  "patient_reference": "PATIENT-REFERENCE",
  "prescriber": {
    "external_user_id": "PRESCRIBER-REFERENCE",
    "name": "Prescriber Name",
    "facility_code": "FACILITY-CODE",
    "facility_name": "Facility Name",
    "district": "District"
  },
  "items": [{
    "antibiotic_code": "APPROVED-CATALOG-CODE",
    "generic_name": "Medicine name",
    "strength": "Product strength",
    "formulation": "Formulation",
    "route": "Route",
    "dose": 500,
    "frequency_per_day": 2,
    "duration_days": 5,
    "quantity": 10,
    "indication": "Approved indication"
  }],
  "expires_at": "2026-10-15T12:00:00Z"
}
```

The payload is illustrative. The actual mapping from the institution's e-Buzima schema and approved formulary must be reviewed before use.

## RMS/eLMIS stock movements

`POST /api/v1/integrations/rms/stock-events`

The endpoint accepts `source_system` (`RMS` or `eLMIS`), stable `source_reference`, pharmacy identity, catalog identity, batch number/expiry, event type (`RECEIPT` or `ADJUSTMENT`), and signed integer `quantity_delta`. Receipts must be positive. Adjustments may be positive or negative, but cannot make available stock negative. A new batch can only be created by a receipt. Replaying an identical source event returns its existing event; changing the content for an existing source reference returns `409`.

## Pharmacy dispense

The pharmacy workflow verifies a short-lived QR/OTP credential and calls `POST /api/v1/prescriptions/{id}/dispense` with pharmacy, batch, quantity, credential, and a unique idempotency key. The API checks prescription expiry/status, pharmacy-to-batch ownership, antibiotic match, authorized remaining quantity, stock availability, and writes the stock movement, transaction, and audit event atomically. The institution must map pharmacy-user identity/roles at its gateway; this application does not yet implement staff sessions or role-based authorization.

## Batch traceability

- `GET /api/v1/stock/batches` lists the current normalized batch catalogue.
- `GET /api/v1/traceability/batches/{batch_id}` returns batch origin, ordered stock events, linked dispensing transactions, prescription IDs, and source external IDs.
- Source references must be retained by each upstream adapter for reconciliation.

## Stewardship reminders

`POST /api/v1/prescriptions/{id}/stewardship-reminder` requires `consent=true` and a `consent_reference` from the approved consent record system. The API refuses scheduling before an actual dispense and schedules against the first dispense plus the prescribed duration. AMRGuard does not store a phone number. The outbox remains `PENDING_PROVIDER`; an approved SMS adapter must resolve the patient destination through an authorized patient system, send the approved neutral message, and report provider delivery status before delivery can be claimed.

## Embedded prescribing support

`POST /api/v1/stewardship/support` accepts an antibiotic code, regimen, quantity and indication and returns a structured response suitable for rendering inside the source EMR's order composer. It currently checks the unit-dose quantity relationship and reports that clinical guidance must be confirmed locally. It is not a treatment recommendation and does not replace the source system's prescribing workflow. AWaRe is returned as `UNCLASSIFIED` until a governed product catalogue with verified mappings is configured.

## Post-dispense stewardship review

After the first successful dispense, AMRGuard creates one `POST_DISPENSE` review task with a configurable pilot default due date (currently three days). `GET /api/v1/stewardship/reviews` lists tasks. `POST /api/v1/stewardship/reviews/{id}/complete` records `CONTINUE`, `CHANGE`, `STOP`, or `REFER`, a reason, and the reviewer reference. Reviews are audit logged and linked to their prescription and latest dispense transaction. The due date is workflow configuration, not clinical guidance.

## Pilot measurement

`GET /api/v1/analytics/summary` includes prescription-to-dispense reconciliation and stewardship review completion counts/rates. Agree denominator, period, eligible cohort, and facility attribution with pilot partners before interpreting results. These operational rates are not impact claims or national estimates.

## Partner contract tester

The development UI includes a local contract tester for canonical e-Buzima-shaped prescription intake. It requires the configured integration key, submits only to the AMRGuard API, and is not connected to e-Buzima. Use synthetic payloads and approved sandbox credentials only.

## Release prerequisites

- Signed-off e-Buzima and RMS/eLMIS field mappings plus sandbox contract tests.
- Approved pharmacy identity/role integration and facility/pharmacy onboarding.
- Approved catalog/formulary and governed antibiotic rules; current demo seed rules are not suitable for clinical decisions.
- Identity-aware access control, consent/privacy review, security testing, rate limiting, monitoring, key rotation, and backup/restore rehearsal.
- SMS gateway configuration, delivery callback verification, consent evidence mapping, and patient communications approval.
- Migration review and rollback/backup plan for the deployment database.
