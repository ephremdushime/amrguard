# AMRGuard — API Authorization Matrix & Endpoint Security Inventory

**Status:** P0 Hardening Enforced v2.0 (Development & Synthetic Verification — not production-certified)  
**Date Updated:** 2026-11-19  
**Source of truth inspected:** `backend/app/main.py`, `backend/app/api/auth_routes.py`, `backend/app/core/auth.py`, `backend/app/core/authz.py`, `frontend/nginx.conf` (branch `feat/p0-security-hardening`)

---

## 1. Executive Summary

AMRGuard exposes **34 FastAPI application routes** plus **3 FastAPI OpenAPI/docs routes** (37 total HTTP endpoints; OpenAPI/docs disabled by default in `production` and blocked in `frontend/nginx.conf`):

| Endpoint Protection Class | Route Count | Implemented Enforcement Status |
|---|---:|---|
| Authenticated human-only operational routes (`OIDC/JWT` or controlled `local_session` + CSRF) | **21** | **ENFORCED** — Default-deny authentication, explicit RBAC roles, and service-layer facility/pharmacy/network tenancy checks. |
| Dual-principal operational routes (strictly separated `HUMAN` roles OR scoped `SERVICE_CLIENT`) | **6** | **ENFORCED** — Combining credentials rejected (`400`); human roles and service scopes checked independently against target facility/pharmacy. |
| Partner service-client write routes (`SERVICE_CLIENT` only via `<key_prefix>.<secret>`) | **2** | **ENFORCED** — Per-partner credentials with keyed HMAC-SHA256 digest, expiry, revocation, rotation, explicit scope, and provisioned facility/pharmacy allowlist. |
| Authentication lifecycle routes (`/api/v1/auth/login`, `/logout`, `/sessions/revoke-all`, `/me`) | **4** | **ENFORCED** — `/login` enforces Argon2id, rate limit, lockout, HttpOnly/Secure/SameSite=Strict cookie + CSRF cookie (disabled by default in `production`); `/logout`, `/sessions/revoke-all`, `/me` require authenticated human user (CSRF enforced on state changes). |
| Public liveness / readiness probes (`/health`, `/health/ready`) | **2** | **PUBLIC (HARDENED)** — `/health` omits `environment` in `production`; `/health/ready` returns generic `503` without DB details on failure. |
| Environment-gated demo routes (`/api/v1/demo/*`) | *(counted in human-only above)* | **ENFORCED + ENV-GATED** — Returns `404` outside `demo`/`test`/`development`/`funder_demo` AND requires `prescriber`/`facility_admin` scoped to `FAC-KGL-001`. |
| OpenAPI / interactive docs (`/openapi.json`, `/docs`, `/redoc`) | **3** | **DISABLED IN PRODUCTION** — `effective_enable_api_docs=False` in `production`; `frontend/nginx.conf` returns `404`. |

---

## 2. Principal Classes & Roles

1. **Human User (`HUMAN`)** — Authenticated via **institutional OIDC/OAuth2 Bearer JWT + JWKS** (`auth_method='oidc_jwt'`) OR **controlled pilot local session** (`auth_method='local_session'`, Argon2id + HttpOnly/Secure/SameSite=Strict cookie + double-submit `X-CSRF-Token` on mutations; disabled by default in `production`). Service-client keys are rejected (`403`).
2. **Integration Service Client (`SERVICE_CLIENT`)** — Authenticated via per-partner scoped key (`x-amrguard-integration-key: <prefix>.<secret>`) stored as keyed HMAC-SHA256 in `service_client_credentials` with explicit scopes and facility/pharmacy bindings. Human sessions/JWTs are rejected (`403`).
3. **Patient QR/OTP credentials** — Cryptographically random tokens stored as keyed HMAC-SHA256 digests (`CREDENTIAL_HMAC_SECRET`), strictly bound to a single `prescription_id`, rate-limited, time-limited, revocable, and automatically revoked on `COMPLETED`. **Never** accepted as proof of pharmacy staff identity.

### Canonical Human Roles (`user_role_scopes` enforced with DB `CHECK` constraint)
- `prescriber` — Facility-scoped prescription visibility, activation, credential issuance/revocation, reminders.
- `pharmacist` — Pharmacy-scoped verification, stock/batch visibility, dispensing authorization (same-facility OR conditional approved-network cross-facility per ADR-001 Decision 2), credential issuance/revocation, reviews.
- `pharmacy_assistant` — Pharmacy-scoped verification and stock reads; **cannot** authorize/commit dispensing (`403`).
- `stewardship_officer` — Facility-scoped stewardship reviews, reminders, transactions, analytics, and facility audit logs.
- `facility_admin` — Facility-scoped administration, prescriptions, transactions, analytics, and facility audit logs.
- `national_analyst` — Explicit `NATIONAL_AGGREGATE` scope for aggregate analytics only; **zero** access to individual prescriptions, dispensing, or audit logs (`403`).
- `platform_operator` — Explicit `PLATFORM` scope for pharmacy directory & technical/auth audit logs only; **zero** implicit access to clinical prescriptions or patient-linked audit records (`403`).

---

## 3. Complete Backend API Endpoint Inventory

### 3.1 System Health, Metadata & Documentation Routes

| # | Method | Route | Handler | Purpose | Sensitive Data | Enforcement Status | Auth Requirement | Required Role(s) / Scope(s) | Facility/Pharmacy Scope |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | `GET` | `/health` | `main.py:health` | Liveness check | `NONE` (`environment` omitted in prod) | `ENFORCED (PUBLIC)` | `PUBLIC` | None | None |
| 2 | `GET` | `/health/ready` | `main.py:readiness` | DB connectivity readiness | `NONE` | `ENFORCED (PUBLIC)` | `PUBLIC` | None | None |
| 3 | `GET` | `/api/v1/meta` | `main.py:meta` | Service version & posture | Operational metadata | `ENFORCED` | `HUMAN` or `SERVICE_CLIENT` | Any authenticated principal | None |
| 4 | `GET` | `/openapi.json` | FastAPI built-in | OpenAPI schema | API surface map | `DISABLED IN PROD` | Disabled in `production` + `nginx.conf` `404` | Non-prod only | None |
| 5 | `GET` | `/docs` | FastAPI built-in | Swagger UI | API surface map | `DISABLED IN PROD` | Disabled in `production` + `nginx.conf` `404` | Non-prod only | None |
| 6 | `GET` | `/redoc` | FastAPI built-in | ReDoc UI | API surface map | `DISABLED IN PROD` | Disabled in `production` + `nginx.conf` `404` | Non-prod only | None |

---

### 3.2 Authentication & Session Lifecycle Routes

| # | Method | Route | Handler | Purpose | Sensitive Data | Enforcement Status | Auth Requirement | Required Role(s) / Scope(s) | Facility/Pharmacy Scope |
|---:|---|---|---|---|---|---|---|---|---|
| 7 | `POST` | `/api/v1/auth/login` | `auth_routes.py:login` | Controlled pilot/dev Argon2id login issuing HttpOnly session + CSRF cookies | `AUDIT/SEC` | `ENFORCED` (disabled by default in `production`; rate-limited + lockout) | `PUBLIC` (only when `local_auth_enabled`) | Active local `User` account | Returns provisioned user role scopes |
| 8 | `POST` | `/api/v1/auth/logout` | `auth_routes.py:logout` | Revoke current session and clear cookies | `AUDIT/SEC` | `ENFORCED` (CSRF required) | `HUMAN` | Any authenticated human user | Own active session |
| 9 | `POST` | `/api/v1/auth/sessions/revoke-all` | `auth_routes.py:revoke_all_sessions` | Revoke all active sessions for current user | `AUDIT/SEC` | `ENFORCED` (CSRF required) | `HUMAN` | Any authenticated human user | Own active sessions |
| 10 | `GET` | `/api/v1/auth/me` | `auth_routes.py:auth_me` | Inspect current authenticated human principal & scopes | `AUDIT/SEC` | `ENFORCED` | `HUMAN` (`oidc_jwt` or `local_session`) | Any authenticated human user | Own principal only |

---

### 3.3 Partner Integration Routes (Service-to-Service & FHIR)

| # | Method | Route | Handler | Purpose | Sensitive Data | Enforcement Status | Auth Requirement | Required Role(s) / Scope(s) | Facility/Pharmacy Scope |
|---:|---|---|---|---|---|---|---|---|---|
| 11 | `POST` | `/api/v1/integrations/ebuzima/prescriptions` | `main.py:receive_prescription` | Ingest antibiotic prescription from EMR | `PHI-REF`, `CLINICAL-WRITE` | `ENFORCED` | `SERVICE_CLIENT` | `integrations:ebuzima:prescriptions:write` | Provisioned `facility_id` MUST be in client's scopes; unknown facilities rejected (`403`); unknown medicine codes rejected (`422`) in hosted envs |
| 12 | `POST` | `/api/v1/integrations/rms/stock-events` | `main.py:receive_rms_stock_event` | Ingest stock receipt/adjustment from RMS/eLMIS | `CLINICAL-WRITE` | `ENFORCED` | `SERVICE_CLIENT` | `integrations:rms:stock:write` | Provisioned `pharmacy_id` MUST be in client's scopes; unknown pharmacies rejected (`403`); unknown medicine codes rejected (`422`) in hosted envs |
| 13 | `GET` | `/api/v1/integrations/ebuzima/prescriptions/{prescription_id}/fhir` | `main.py:prescription_fhir` | Export prescription as FHIR MedicationRequest | `PHI-REF` (Read) | `ENFORCED` (audited) | `HUMAN` or `SERVICE_CLIENT` | Human: `prescriber`, `pharmacist`, `stewardship_officer`, `facility_admin`; Service: `integrations:ebuzima:prescriptions:read` | `rx.facility_id` MUST match caller's authorized facility scope |
| 14 | `GET` | `/api/v1/integrations/dispensing/{transaction_id}/fhir` | `main.py:dispensing_fhir` | Export dispensing transaction as FHIR MedicationDispense | `PHI-REF` (Read) | `ENFORCED` (audited) | `HUMAN` or `SERVICE_CLIENT` | Human: `pharmacist`, `stewardship_officer`, `facility_admin`; Service: `integrations:dispensing:read` | `tx.pharmacy_id` or `rx.facility_id` MUST match caller's authorized scope |

---

### 3.4 Prescription Lifecycle & Verification Routes

| # | Method | Route | Handler | Purpose | Sensitive Data | Enforcement Status | Auth Requirement | Required Role(s) / Scope(s) | Facility/Pharmacy Scope |
|---:|---|---|---|---|---|---|---|---|---|
| 15 | `GET` | `/api/v1/prescriptions` | `main.py:list_prescriptions` | List prescriptions | `PHI-REF` (Read) | `ENFORCED` | `HUMAN` | `prescriber`, `pharmacist`, `pharmacy_assistant`, `stewardship_officer`, `facility_admin` | Strictly filtered to caller's authorized `facility_id`(s) |
| 16 | `GET` | `/api/v1/prescriptions/{prescription_id}` | `main.py:get_prescription` | Read single prescription details | `PHI-REF` (Read) | `ENFORCED` (audited) | `HUMAN` | `prescriber`, `pharmacist`, `pharmacy_assistant`, `stewardship_officer`, `facility_admin` | `rx.facility_id` MUST be in caller's authorized facility scope (`403` otherwise) |
| 17 | `POST` | `/api/v1/prescriptions/{prescription_id}/activate` | `main.py:activate_prescription` | Transition `VALIDATED`/`WARNING` -> `ACTIVE` | `CLINICAL-WRITE` | `ENFORCED` (expiry checked + audited) | `HUMAN` or `SERVICE_CLIENT` | Human: `prescriber`, `pharmacist`, `facility_admin`; Service: `integrations:ebuzima:prescriptions:write` | `rx.facility_id` MUST match caller's authorized facility scope |
| 18 | `POST` | `/api/v1/prescriptions/{prescription_id}/credential` | `main.py:create_credential` | Issue/reissue keyed-HMAC OTP & QR token | `PHI-REF`, `CLINICAL-WRITE`, `AUDIT/SEC` | `ENFORCED` (rate-limited + expiry checked + audited) | `HUMAN` or `SERVICE_CLIENT` | Human: `prescriber`, `pharmacist`, `facility_admin`; Service: `integrations:ebuzima:credentials:write` | `rx.facility_id` MUST match caller's authorized facility scope; preserves `PARTIALLY_DISPENSED` |
| 19 | `POST` | `/api/v1/prescriptions/{prescription_id}/credential/revoke` | `main.py:revoke_credential` | Explicitly revoke active QR/OTP credential | `CLINICAL-WRITE`, `AUDIT/SEC` | `ENFORCED` (audited) | `HUMAN` | `prescriber`, `pharmacist`, `facility_admin` | `rx.facility_id` MUST match caller's authorized facility scope |
| 20 | `POST` | `/api/v1/verification` | `main.py:verify` | Verify QR token or OTP in JSON body | `PHI-REF` (Read), `AUDIT/SEC` | `ENFORCED` (rate-limited + scope checked + audited) | `HUMAN` | `pharmacist`, `pharmacy_assistant` | Caller's active pharmacy MUST match `rx.facility_id` OR satisfy conditional approved-network cross-facility rules |
| 21 | `POST` | `/api/v1/verification/otp` | `main.py:verify_otp` | Deprecated query-string OTP verification | `PHI-REF`, `AUDIT/SEC` | `ENFORCED + DEPRECATED` (`410 Gone` in `production`) | `HUMAN` | `pharmacist`, `pharmacy_assistant` | Same pharmacy/network scope & rate-limiting as `/api/v1/verification`; blocked in `production` |

---

### 3.5 Pharmacy, Stock, Dispensing & Traceability Routes

| # | Method | Route | Handler | Purpose | Sensitive Data | Enforcement Status | Auth Requirement | Required Role(s) / Scope(s) | Facility/Pharmacy Scope |
|---:|---|---|---|---|---|---|---|---|---|
| 22 | `GET` | `/api/v1/pharmacies` | `main.py:pharmacies` | List pharmacy locations | Operational metadata | `ENFORCED` | `HUMAN` | `pharmacist`, `pharmacy_assistant`, `prescriber`, `stewardship_officer`, `facility_admin`, `platform_operator` | Filtered to caller's authorized `pharmacy_id`(s) (full technical directory for `platform_operator`) |
| 23 | `GET` | `/api/v1/pharmacies/{pharmacy_id}/stock` | `main.py:pharmacy_stock` | List stock batches for a pharmacy | Operational stock data | `ENFORCED` | `HUMAN` | `pharmacist`, `pharmacy_assistant`, `stewardship_officer`, `facility_admin` | Path `pharmacy_id` MUST be in caller's authorized pharmacy scope (`403` otherwise) |
| 24 | `GET` | `/api/v1/stock/batches` | `main.py:list_stock_batches` | List stock batches | Operational stock data | `ENFORCED` | `HUMAN` | `pharmacist`, `pharmacy_assistant`, `stewardship_officer`, `facility_admin` | Filtered to caller's authorized `pharmacy_id`(s); unauthorized `pharmacy_id` filter rejected (`403`) |
| 25 | `POST` | `/api/v1/prescriptions/{prescription_id}/dispense` | `main.py:dispense` | Commit dispensing transaction & decrement stock atomically | `PHI-REF`, `CLINICAL-WRITE`, `AUDIT/SEC` | `ENFORCED` (locked, idempotency required, expiry/batch/credential-binding/network checked, audited) | `HUMAN` (strictly authenticated pharmacist) | `pharmacist` ONLY | Actor MUST be authorized for `request.pharmacy_id`; `batch.pharmacy_id == request.pharmacy_id`; credential MUST match `{prescription_id}`; same-facility OR conditional cross-facility network + opt-in + medicine permission; persists `actor_user_id`, `prescribing_facility_id`, `dispensing_facility_id`, `is_cross_facility` |
| 26 | `GET` | `/api/v1/transactions` | `main.py:transactions` | List dispensing transactions | `PHI-REF` (Read) | `ENFORCED` | `HUMAN` | `pharmacist`, `stewardship_officer`, `facility_admin` | Filtered strictly to caller's authorized `pharmacy_id`(s) or prescribing `facility_id`(s) |
| 27 | `GET` | `/api/v1/traceability/batches/{batch_id}` | `main.py:batch_trace` | Batch event ledger & linked dispenses | `PHI-REF` (Read) | `ENFORCED` | `HUMAN` | `pharmacist`, `stewardship_officer`, `facility_admin` | Batch's `pharmacy_id` MUST be in caller's authorized pharmacy scope (`403` otherwise) |

---

### 3.6 Stewardship, Reminders, Analytics & Audit Routes

| # | Method | Route | Handler | Purpose | Sensitive Data | Enforcement Status | Auth Requirement | Required Role(s) / Scope(s) | Facility/Pharmacy Scope |
|---:|---|---|---|---|---|---|---|---|---|
| 28 | `POST` | `/api/v1/stewardship/support` | `main.py:stewardship_support` | Embeddable non-prescriptive quantity/rule check | Clinical regimen input | `ENFORCED` | `HUMAN` or `SERVICE_CLIENT` | Human: `prescriber`, `pharmacist`, `stewardship_officer`; Service: `stewardship:support:read` | Authenticated clinical role or scoped EMR service client |
| 29 | `POST` | `/api/v1/prescriptions/{prescription_id}/stewardship-reminder` | `main.py:schedule_stewardship_reminder` | Queue post-course reminder with consent ref | `PHI-REF`, `CLINICAL-WRITE` | `ENFORCED` (audited) | `HUMAN` | `prescriber`, `pharmacist`, `stewardship_officer` | `rx.facility_id` MUST be in caller's authorized facility scope |
| 30 | `GET` | `/api/v1/stewardship/reminders` | `main.py:list_stewardship_reminders` | List scheduled reminders | `PHI-REF` (Read) | `ENFORCED` | `HUMAN` | `pharmacist`, `stewardship_officer`, `facility_admin` | Filtered strictly to prescriptions in caller's authorized `facility_id`(s) |
| 31 | `GET` | `/api/v1/stewardship/reviews` | `main.py:list_stewardship_reviews` | List post-dispense stewardship reviews | `PHI-REF` (Read) | `ENFORCED` | `HUMAN` | `stewardship_officer`, `pharmacist`, `facility_admin` | Filtered strictly to prescriptions in caller's authorized `facility_id`(s) |
| 32 | `POST` | `/api/v1/stewardship/reviews/{review_id}/complete` | `main.py:complete_stewardship_review` | Record stewardship review disposition | `PHI-REF`, `CLINICAL-WRITE`, `AUDIT/SEC` | `ENFORCED` (records `reviewer_user_id` + audited) | `HUMAN` | `stewardship_officer`, `pharmacist` | Linked prescription's `facility_id` MUST be in caller's authorized facility scope |
| 33 | `GET` | `/api/v1/analytics/summary` | `main.py:analytics` | Operational counts & reconciliation/review rates | Aggregate operational data | `ENFORCED` | `HUMAN` | `stewardship_officer`, `facility_admin`, `pharmacist`, `national_analyst` | Scoped to caller's authorized `facility_id`(s)/`pharmacy_id`(s); global aggregate allowed ONLY for `national_analyst` (`NATIONAL_AGGREGATE` scope) |
| 34 | `GET` | `/api/v1/analytics/facilities` | `main.py:facility_analytics` | Per-facility operational breakdown | Facility performance data | `ENFORCED` | `HUMAN` | `stewardship_officer`, `facility_admin`, `national_analyst` | Filtered strictly to caller's authorized `facility_id`(s); all active facilities ONLY for `national_analyst` |
| 35 | `GET` | `/api/v1/audit` | `main.py:audit_events` | Read structured audit trail | `AUDIT/SEC`, `PHI-REF` | `ENFORCED` (audited) | `HUMAN` | `facility_admin`, `stewardship_officer`, `platform_operator` | `facility_admin`/`stewardship_officer`: filtered strictly to caller's `facility_id`(s); `platform_operator`: technical/auth entities ONLY (zero clinical prescription rows) |

---

### 3.7 Demo / Non-Production Routes

| # | Method | Route | Handler | Purpose | Sensitive Data | Enforcement Status | Auth Requirement | Required Role(s) / Scope(s) | Facility/Pharmacy Scope |
|---:|---|---|---|---|---|---|---|---|---|
| 36 | `POST` | `/api/v1/demo/prescriptions` | `main.py:create_demo_prescription` | Create synthetic demo prescription | Synthetic only | `ENFORCED + ENV-GATED` (`404` in `sandbox`/`production`) | `HUMAN` | `prescriber`, `facility_admin` | Must hold scope on synthetic demo facility `FAC-KGL-001` |
| 37 | `POST` | `/api/v1/demo/risk-scenario` | `main.py:demo_risk_scenario` | Create deliberately blocked synthetic prescription | Synthetic only | `ENFORCED + ENV-GATED` (`404` in `sandbox`/`production`) | `HUMAN` | `prescriber`, `facility_admin` | Must hold scope on synthetic demo facility `FAC-KGL-001` |
