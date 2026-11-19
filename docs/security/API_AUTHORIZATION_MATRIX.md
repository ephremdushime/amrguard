# AMRGuard — API Authorization Matrix & Endpoint Security Inventory

**Status:** Baseline Security Inventory v1.0 (P0 Task 1)  
**Date:** 2026-11-19  
**Source of truth inspected:** `backend/app/main.py`, `backend/app/core/security.py`, `backend/app/core/config.py`, `frontend/nginx.conf`, `frontend/nginx.funder-demo.conf` (commit `237fe77` on `main`)

---

## 1. Executive Summary

AMRGuard currently exposes **29 FastAPI application routes** plus **3 FastAPI documentation/schema routes** (32 total HTTP endpoints):

| Current Protection Class | Route Count | Risk Assessment |
|---|---:|---|
| Completely unauthenticated operational clinical/pharmacy/FHIR/audit/reminder routes | **17** | **CRITICAL (P0 blocker)** — Anonymous callers can read prescriptions/patient references, issue QR/OTP credentials, verify OTPs, dispense antibiotics, read cross-facility audit logs, and export FHIR resources even when `APP_ENV=production`. |
| Weakly gated by `require_funder_demo_ui_or_integration_key` (single shared key; bypassed when empty or in `funder_demo`; no user/role/facility checks) | **5** | **CRITICAL (P0 blocker)** — No human actor identity, no RBAC, no facility isolation; incompatible with browser UI in `sandbox`/`production` without leaking integration secrets. |
| Weakly gated by `require_integration_key` (single shared key; bypassed when empty outside `sandbox`/`funder_demo`/`production`; no per-partner scoping) | **2** | **HIGH (P0/P1)** — Single shared secret across e-Buzima and RMS/eLMIS; no partner identity, scope isolation, replay window, or unknown-code quarantine. |
| Environment-gated demo routes (`404` outside `demo`/`test`/`development`/`funder_demo`) | **2** | **MEDIUM (P0)** — Properly blocked in `production`/`sandbox`, but unauthenticated in `funder_demo`/`development`. |
| Health & service metadata routes (`/health`, `/health/ready`, `/api/v1/meta`) | **3** | **LOW–MEDIUM** — `/health` leaks `environment`; `/api/v1/meta` exposes security posture notes. |
| OpenAPI / interactive docs (`/openapi.json`, `/docs`, `/redoc`) | **3** | **MEDIUM** — Publicly proxied by `frontend/nginx.conf` in production compose configuration; should be restricted or disabled in production. |

**Security Baseline Verdict:** The API is **not safe** for real patient data, hospital deployment, or live dispensing. No human user authentication, role-based access control (RBAC), facility scoping, or pharmacy scoping is implemented anywhere in the backend.

---

## 2. Target Security Policy & Principal Classes

Every endpoint MUST enforce **default-deny** authentication and authorization in backend dependencies and service layers (never relying solely on frontend hiding or reverse-proxy rules):

### Principal Types (Strictly Separated)
1. **Human User (`HUMAN`)** — Authenticated via approved institutional OIDC/OAuth2 or controlled pilot identity session (see `docs/security/ADR-001-IDENTITY-AND-AUTHZ.md`). Never authenticated via `INTEGRATION_API_KEY` or a patient QR/OTP token.
2. **Integration Service Client (`SERVICE_CLIENT`)** — Authenticated via partner-specific credentials / OAuth2 client credentials / mTLS with explicit least-privilege scopes and facility/pharmacy allowlists. Cannot perform human clinical dispensing or stewardship review completion unless explicitly contracted and audited as an upstream system mirror.
3. **Public (`PUBLIC`)** — Strictly limited to minimal liveness/readiness probes that leak zero internal state, topology, or clinical data.

### Target Human Roles (per `PRODUCT_MASTER_BLUEPRINT.md` §4)
| Role Code | Responsibilities | Scope Boundary |
|---|---|---|
| `prescriber` | View own facility prescriptions; issue/revoke patient verification credentials if authorized by facility workflow | Assigned `facility_id` only |
| `pharmacist` | Verify QR/OTP credentials; view eligible prescriptions and assigned pharmacy stock; authorize & record dispensing; view batch traceability for assigned pharmacy | Assigned `pharmacy_id` (and parent `facility_id`) only |
| `pharmacy_assistant` | Support retrieval/verification flow; view assigned pharmacy stock | Assigned `pharmacy_id` only; **cannot** authorize/commit dispensing unless explicitly granted `pharmacist` role |
| `stewardship_officer` | Review alerts/tasks; record stewardship review dispositions; view facility prescriptions, transactions, reminders, and facility analytics | Assigned `facility_id` (or approved multi-facility organization scope) |
| `facility_admin` | Manage facility users/role scopes, facility configuration, facility audit logs, and facility reports | Assigned `facility_id` only |
| `national_analyst` | View approved de-identified aggregate indicators across participating facilities | Aggregate read-only; **no default identifiable patient/prescription access** |
| `platform_operator` | Technical deployment, partner service-client administration, integration monitoring | Technical/admin only; **no implicit clinical-data access** |

---

## 3. Complete Backend API Endpoint Inventory

### Legend
- **Sensitive Data:**
  - `PHI-REF`: Patient reference, clinical indication, regimen, consent reference, or prescriber link.
  - `CLINICAL-WRITE`: Mutates prescription status, credentials, dispensing state, stock ledger, or clinical review records.
  - `AUDIT/SEC`: Security audit trails, credentials, or operational metadata.
  - `NONE`: Non-clinical liveness/readiness only.
- **Current Status:**
  - `UNPROTECTED`: Zero authentication or authorization in backend.
  - `WEAK-SHARED-KEY`: Uses `require_integration_key` (single shared key; no-op when env var empty in dev/demo/test; no partner/facility scope).
  - `WEAK-SHARED-KEY-OR-DEMO-BYPASS`: Uses `require_funder_demo_ui_or_integration_key` (bypassed completely in `funder_demo` or when key is empty; no user/role/facility scope).
  - `ENV-GATED-ONLY`: Returns `404` outside `demo`/`test`/`development`/`funder_demo`, unauthenticated where enabled.
  - `PUBLIC-LEAK`: Unauthenticated and leaks internal environment/config metadata.

---

### 3.1 System Health, Metadata & Documentation Routes

| # | Method | Route | Handler (`main.py`) | Purpose | Sensitive Data | Current Protection Status | Target Auth Requirement | Target Role(s) / Scope(s) | Target Facility/Pharmacy Scope |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | `GET` | `/health` | `health` (L93) | Liveness check | `NONE` (currently leaks `app_env`) | `PUBLIC-LEAK` | `PUBLIC` (remove `environment` leak in prod) | None | None |
| 2 | `GET` | `/health/ready` | `readiness` (L96) | DB connectivity readiness check | `NONE` | `UNPROTECTED` (OK for internal probe; restrict externally) | `PUBLIC` (internal/orchestrator network; no DB error details leaked) | None | None |
| 3 | `GET` | `/api/v1/meta` | `meta` (L101) | Service version and integration posture summary | `AUDIT/SEC` (reveals security mode & `demo_data`) | `PUBLIC-LEAK` | `HUMAN` or `SERVICE_CLIENT` (or strip security details if public) | Any authenticated principal | None |
| 4 | `GET` | `/openapi.json` | FastAPI built-in | OpenAPI schema export | `AUDIT/SEC` (API surface map) | `UNPROTECTED` (proxied openly in `nginx.conf`) | Disabled or restricted to non-prod / `platform_operator` | `platform_operator` (non-prod only by default) | None |
| 5 | `GET` | `/docs` | FastAPI built-in | Swagger UI | `AUDIT/SEC` | `UNPROTECTED` (proxied openly in `nginx.conf`) | Disabled in production | `platform_operator` (non-prod only) | None |
| 6 | `GET` | `/redoc` | FastAPI built-in | ReDoc UI | `AUDIT/SEC` | `UNPROTECTED` (proxied openly in `nginx.conf`) | Disabled in production | `platform_operator` (non-prod only) | None |

---

### 3.2 Partner Integration Routes (Service-to-Service)

| # | Method | Route | Handler (`main.py`) | Purpose | Sensitive Data | Current Protection Status | Target Auth Requirement | Target Role(s) / Scope(s) | Target Facility/Pharmacy Scope |
|---:|---|---|---|---|---|---|---|---|---|
| 7 | `POST` | `/api/v1/integrations/ebuzima/prescriptions` | `receive_prescription` (L139) | Ingest antibiotic prescription from EMR | `PHI-REF`, `CLINICAL-WRITE` | `WEAK-SHARED-KEY` — shared key; bypassed if empty; auto-creates `Facility`, `Prescriber`, `Antibiotic` | `SERVICE_CLIENT` | Scope: `integrations:ebuzima:prescriptions:write` | `prescriber.facility_code` MUST belong to client's `allowed_facility_ids` |
| 8 | `POST` | `/api/v1/integrations/rms/stock-events` | `receive_rms_stock_event` (L217) | Ingest stock receipt/adjustment from RMS/eLMIS | `CLINICAL-WRITE` (supply ledger) | `WEAK-SHARED-KEY` — same key as e-Buzima; auto-creates `Pharmacy`, `Antibiotic` | `SERVICE_CLIENT` | Scope: `integrations:rms:stock:write` | `pharmacy_code` MUST belong to client's `allowed_pharmacy_ids` (or authorized org) |
| 9 | `GET` | `/api/v1/integrations/ebuzima/prescriptions/{prescription_id}/fhir` | `prescription_fhir` (L428) | Export prescription as FHIR MedicationRequest (currently loses items `> 0`) | `PHI-REF` (Read) | `UNPROTECTED` (**CRITICAL**) | `SERVICE_CLIENT` or `HUMAN` | Service scope: `integrations:ebuzima:prescriptions:read`; Human: `prescriber`, `pharmacist`, `stewardship_officer`, `facility_admin` | Prescription's `facility_id` MUST match caller's authorized facility scope |
| 10 | `GET` | `/api/v1/integrations/dispensing/{transaction_id}/fhir` | `dispensing_fhir` (L434) | Export dispensing transaction as FHIR MedicationDispense | `PHI-REF` (Read) | `UNPROTECTED` (**CRITICAL**) | `SERVICE_CLIENT` or `HUMAN` | Service scope: `integrations:dispensing:read`; Human: `pharmacist`, `stewardship_officer`, `facility_admin` | Transaction's `pharmacy_id` / prescription's `facility_id` MUST match caller's scope |

---

### 3.3 Prescription Lifecycle & Verification Routes

| # | Method | Route | Handler (`main.py`) | Purpose | Sensitive Data | Current Protection Status | Target Auth Requirement | Target Role(s) / Scope(s) | Target Facility/Pharmacy Scope |
|---:|---|---|---|---|---|---|---|---|---|
| 11 | `GET` | `/api/v1/prescriptions` | `list_prescriptions` (L199) | List prescriptions across system | `PHI-REF` (Read) | `UNPROTECTED` (**CRITICAL** — cross-facility leak) | `HUMAN` | `prescriber`, `pharmacist`, `pharmacy_assistant`, `stewardship_officer`, `facility_admin` | Strictly filtered to caller's authorized `facility_id`(s) (never global by default) |
| 12 | `GET` | `/api/v1/prescriptions/{prescription_id}` | `get_prescription` (L161) | Read full prescription details & indication | `PHI-REF` (Read) | `UNPROTECTED` (**CRITICAL** — IDOR across facilities) | `HUMAN` | `prescriber`, `pharmacist`, `pharmacy_assistant`, `stewardship_officer`, `facility_admin` | Resource `rx.facility_id` MUST be in caller's authorized facility scope (or verified active handoff to caller's pharmacy) |
| 13 | `POST` | `/api/v1/prescriptions/{prescription_id}/activate` | `activate_prescription` (L349) | Transition prescription `VALIDATED`/`WARNING` -> `ACTIVE` | `CLINICAL-WRITE` | `UNPROTECTED` (**CRITICAL**) | `HUMAN` (or `SERVICE_CLIENT` if EMR-triggered) | Human: `prescriber`, `pharmacist`, `facility_admin`; Service: `integrations:ebuzima:prescriptions:write` | Resource `rx.facility_id` MUST match caller's facility scope |
| 14 | `POST` | `/api/v1/prescriptions/{prescription_id}/credential` | `create_credential` (L167) | Issue/reissue 6-digit OTP & QR token; activates prescription | `PHI-REF`, `CLINICAL-WRITE`, `AUDIT/SEC` | `UNPROTECTED` (**CRITICAL** — anonymous credential minting) | `HUMAN` (or `SERVICE_CLIENT` EMR handoff) | Human: `prescriber`, `pharmacist`, `facility_admin`; Service: `integrations:ebuzima:credentials:write` | Resource `rx.facility_id` MUST match caller's facility scope; rate-limited; actor recorded in audit |
| 15 | `POST` | `/api/v1/verification` | `verify` (L191) | Verify QR token or OTP; returns full prescription detail | `PHI-REF` (Read), `AUDIT/SEC` | `UNPROTECTED` (**CRITICAL** — no staff auth, no rate limit, brute-forceable OTP) | `HUMAN` | `pharmacist`, `pharmacy_assistant` | Caller MUST belong to an active pharmacy eligible to fulfill `rx.facility_id` (same facility or approved network); rate-limited; credential does NOT authenticate staff |
| 16 | `POST` | `/api/v1/verification/otp` | `verify_otp` (L195) | Verify 6-digit OTP via **URL query param** `?otp=` | `PHI-REF` (Read), `AUDIT/SEC` (OTP leaked in URL/logs) | `UNPROTECTED` (**CRITICAL** — plus OTP in query string defect) | `HUMAN` (**Deprecate query-string OTP**; prefer `POST /api/v1/verification` body) | `pharmacist`, `pharmacy_assistant` | Same pharmacy/facility scope & rate-limiting as `/api/v1/verification` |

---

### 3.4 Pharmacy, Stock, Dispensing & Traceability Routes

| # | Method | Route | Handler (`main.py`) | Purpose | Sensitive Data | Current Protection Status | Target Auth Requirement | Target Role(s) / Scope(s) | Target Facility/Pharmacy Scope |
|---:|---|---|---|---|---|---|---|---|---|
| 17 | `GET` | `/api/v1/pharmacies` | `pharmacies` (L366) | List pharmacy locations | Operational metadata | `UNPROTECTED` | `HUMAN` | `pharmacist`, `pharmacy_assistant`, `prescriber`, `stewardship_officer`, `facility_admin`, `platform_operator` | Filtered to caller's authorized `pharmacy_id`(s) / `facility_id`(s) |
| 18 | `GET` | `/api/v1/pharmacies/{pharmacy_id}/stock` | `pharmacy_stock` (L370) | List stock batches for a pharmacy | Operational stock data | `UNPROTECTED` (**HIGH** — cross-pharmacy read) | `HUMAN` | `pharmacist`, `pharmacy_assistant`, `stewardship_officer`, `facility_admin` | Path `pharmacy_id` MUST be in caller's authorized pharmacy/facility scope |
| 19 | `GET` | `/api/v1/stock/batches` | `list_stock_batches` (L206) | List stock batches across pharmacies | Operational stock data | `UNPROTECTED` (**HIGH** — cross-pharmacy read) | `HUMAN` | `pharmacist`, `pharmacy_assistant`, `stewardship_officer`, `facility_admin` | Strictly filtered to caller's authorized `pharmacy_id`(s) / `facility_id`(s); reject unauthorized `pharmacy_id` query filter with `403` |
| 20 | `POST` | `/api/v1/prescriptions/{prescription_id}/dispense` | `dispense` (L375) | Commit dispensing transaction, decrement stock, update prescription, create review | `PHI-REF`, `CLINICAL-WRITE`, `AUDIT/SEC` | `UNPROTECTED` (**CRITICAL** — no staff auth; ignores `cred_rx.id == rx.id`; does not check expired batch; optional `idempotency_key`; no `actor_user_id`) | `HUMAN` (strictly authenticated pharmacy staff) | `pharmacist` (ONLY — never `pharmacy_assistant` unless explicitly authorized; never anonymous or service key) | `request.pharmacy_id` MUST be assigned to authenticated actor; `batch.pharmacy_id == request.pharmacy_id`; `rx.facility_id` eligible for pharmacy; credential MUST belong to `{prescription_id}` |
| 21 | `GET` | `/api/v1/transactions` | `transactions` (L357) | List dispensing transactions | `PHI-REF` (Read — prescription & payment refs) | `UNPROTECTED` (**CRITICAL** — cross-facility/pharmacy leak) | `HUMAN` | `pharmacist`, `stewardship_officer`, `facility_admin` | Strictly filtered to caller's authorized `pharmacy_id`(s) / `facility_id`(s) |
| 22 | `GET` | `/api/v1/traceability/batches/{batch_id}` | `batch_trace` (L413) | Batch event ledger and linked prescriptions/transactions | `PHI-REF` (Read — linked prescriptions & external IDs) | `UNPROTECTED` (**CRITICAL** — cross-pharmacy/facility leak) | `HUMAN` | `pharmacist`, `stewardship_officer`, `facility_admin` | Batch's `pharmacy_id` (and parent facility) MUST be in caller's authorized scope |

---

### 3.5 Stewardship, Reminders, Analytics & Audit Routes

| # | Method | Route | Handler (`main.py`) | Purpose | Sensitive Data | Current Protection Status | Target Auth Requirement | Target Role(s) / Scope(s) | Target Facility/Pharmacy Scope |
|---:|---|---|---|---|---|---|---|---|---|
| 23 | `POST` | `/api/v1/stewardship/support` | `stewardship_support` (L105 — **IndentationError at L106!**) | Embeddable non-prescriptive quantity/rule check | Clinical regimen input (non-persisted) | `WEAK-SHARED-KEY-OR-DEMO-BYPASS` + **Syntax broken on `main`** | `HUMAN` or `SERVICE_CLIENT` | Human: `prescriber`, `pharmacist`, `stewardship_officer`; Service: `stewardship:support:read` | Facility context recorded for future facility-specific approved rulesets |
| 24 | `POST` | `/api/v1/prescriptions/{prescription_id}/stewardship-reminder` | `schedule_stewardship_reminder` (L252) | Record consent ref & queue post-course reminder | `PHI-REF`, `CLINICAL-WRITE` | `UNPROTECTED` (**CRITICAL**) | `HUMAN` | `pharmacist`, `prescriber`, `stewardship_officer` | Resource `rx.facility_id` MUST be in caller's authorized facility scope; actor recorded in audit |
| 25 | `GET` | `/api/v1/stewardship/reminders` | `list_stewardship_reminders` (L269) | List scheduled reminders & consent references | `PHI-REF` (Read) | `UNPROTECTED` (**CRITICAL** — cross-facility leak) | `HUMAN` | `pharmacist`, `stewardship_officer`, `facility_admin` | Strictly filtered to prescriptions within caller's authorized `facility_id`(s) |
| 26 | `GET` | `/api/v1/stewardship/reviews` | `list_stewardship_reviews` (L280) | List post-dispense stewardship review queue (`patient_reference`, `facility_id`) | `PHI-REF` (Read) | `WEAK-SHARED-KEY-OR-DEMO-BYPASS` (**CRITICAL** — exposes patient refs across all facilities) | `HUMAN` | `stewardship_officer`, `pharmacist`, `facility_admin` | Strictly filtered to caller's authorized `facility_id`(s) |
| 27 | `POST` | `/api/v1/stewardship/reviews/{review_id}/complete` | `complete_stewardship_review` (L290) | Record stewardship review outcome/disposition | `PHI-REF`, `CLINICAL-WRITE`, `AUDIT/SEC` | `WEAK-SHARED-KEY-OR-DEMO-BYPASS` (**CRITICAL** — caller-supplied `reviewer_reference`, no user/facility check) | `HUMAN` | `stewardship_officer` (or explicitly authorized `pharmacist`) | Review's prescription `facility_id` MUST be in caller's authorized facility scope; derive `reviewer_user_id` from authenticated principal |
| 28 | `GET` | `/api/v1/analytics/summary` | `analytics` (L445) | Operational counts & reconciliation/review rates | Aggregate operational data | `WEAK-SHARED-KEY-OR-DEMO-BYPASS` (global unfiltered aggregates) | `HUMAN` | `stewardship_officer`, `facility_admin`, `national_analyst`, `pharmacist` (facility-scoped) | Scoped to caller's authorized `facility_id`(s); global aggregate allowed ONLY for `national_analyst` under governance policy |
| 29 | `GET` | `/api/v1/analytics/facilities` | `facility_analytics` (L453) | Per-facility operational breakdown | Facility performance data | `WEAK-SHARED-KEY-OR-DEMO-BYPASS` (cross-facility disclosure) | `HUMAN` | `facility_admin`, `stewardship_officer` (own facility only), `national_analyst` (approved multi-facility scope) | Filtered strictly to caller's authorized `facility_id`(s) unless `national_analyst` |
| 30 | `GET` | `/api/v1/audit` | `audit_events` (L440) | Read system audit log (`entity_id`, `details` JSON) | `AUDIT/SEC`, `PHI-REF` (in details) | `UNPROTECTED` (**CRITICAL** — anonymous read of full system audit trail) | `HUMAN` | `facility_admin`, `stewardship_officer` (facility-scoped), `platform_operator` (technical/non-PHI events only) | Strictly filtered to caller's `facility_id` (or technical events for `platform_operator`) |

---

### 3.6 Demo / Non-Production Routes

| # | Method | Route | Handler (`main.py`) | Purpose | Sensitive Data | Current Protection Status | Target Auth Requirement | Target Role(s) / Scope(s) | Target Facility/Pharmacy Scope |
|---:|---|---|---|---|---|---|---|---|---|
| 31 | `POST` | `/api/v1/demo/prescriptions` | `create_demo_prescription` (L299) | Create synthetic demo prescription | Synthetic only | `ENV-GATED-ONLY` (`404` in `sandbox`/`production`) | Keep hard-disabled (`404`) in `sandbox`/`production`; require authenticated demo user or explicit dev/demo guard | `prescriber` / `demo_user` (non-prod only) | Synthetic demo facility `FAC-KGL-001` only |
| 32 | `POST` | `/api/v1/demo/risk-scenario` | `demo_risk_scenario` (L323) | Create intentionally blocked synthetic prescription | Synthetic only | `ENV-GATED-ONLY` (`404` in `sandbox`/`production`) | Keep hard-disabled (`404`) in `sandbox`/`production`; require authenticated demo user in `funder_demo`/dev | `prescriber` / `demo_user` (non-prod only) | Synthetic demo facility `FAC-KGL-001` only |

---

## 4. Critical Code-Verified Security Defects Beyond Missing Route Auth

Direct inspection of `backend/` and `frontend/` identified additional high-severity defects that MUST be closed in P0:

1. **Cross-Prescription Credential Bypass in `dispense()` (`backend/app/main.py:389`):**
   - `verify_credential(request.credential, db)` returns the `Prescription` linked to the credential, **but `dispense()` discards the return value and never checks `cred_rx.id == rx.id`**.
   - Impact: A valid OTP/QR generated for Prescription A can be used to authorize dispensing of Prescription B.
2. **Unconsumed / Non-Revocable Credentials & Unchecked Prescription/Batch Expiry (`backend/app/main.py:167-189, 349-355, 389-410`):**
   - `dispense()` invokes `verify_credential(request.credential, db)` with default `consume=False`, so `cred.used_count` is never incremented and credentials remain reusable until TTL expiry even after full dispensing (`COMPLETED`).
   - `verify_credential()`, `create_credential()`, and `activate_prescription()` do not check `rx.expires_at`.
   - `create_credential()` overwrites `rx.status = 'ACTIVE'` even when `rx.status == 'PARTIALLY_DISPENSED'`.
   - `dispense()` does not reject expired stock batches (`batch.expiry_date < date.today()`), and its idempotency replay response returns `prior.status` (transaction status) rather than the actual prescription status.
   - No endpoint or mechanism exists to revoke an active QR/OTP credential.
3. **Unsalted SHA-256 OTP Hashing (`backend/app/services/security.py:3`):**
   - 6-digit OTPs (only $10^6$ values) are stored as plain unsalted SHA-256 hashes, making offline brute force trivial if database backups are exposed. Must migrate to keyed HMAC-SHA256 bound to prescription ID + credential salt/pepper.
4. **OTP Transmitted in URL Query String (`backend/app/main.py:195`):**
   - `POST /api/v1/verification/otp?otp=123456` places a bearer secret in URL query parameters, which reverse proxies and web servers record in access logs.
5. **Broken Startup on `main` (`backend/app/main.py:106`):**
   - `IndentationError: unexpected indent` on `def stewardship_support(...)` prevents the FastAPI module from importing.
6. **Zero Organizational / Facility-to-Pharmacy Tenancy Links (`backend/app/models/core.py:9-14`):**
   - `Pharmacy` has no `facility_id` or `organization_id`; `Facility` has no `organization_id`; `DispensingTransaction` has no `actor_user_id`; `AuditEvent` has no `actor_type`, `actor_id`, `facility_id`, `pharmacy_id`, `correlation_id`, or `outcome`.
7. **Frontend Incompatible with Protected APIs (`frontend/src/main.tsx:9`):**
   - `apiHeaders = {}` sends no user credentials; `production`/`sandbox` deployments return `401` on `/api/v1/analytics/summary`, `/api/v1/stewardship/reviews`, and `/api/v1/stewardship/support` for any browser client.
8. **Optional Idempotency Key on Dispensing (`backend/app/schemas/prescriptions.py:34`):**
   - `idempotency_key` is optional (`None`), allowing duplicate dispenses when omitted by clients or network retries.
9. **Production Proxy & CORS Hardening Gaps:**
   - `docker-compose.prod.yml:28` uses `--forwarded-allow-ips='*'`.
   - `backend/app/main.py:48` sets `allow_methods=['*']` and `allow_headers=['*']` with `allow_credentials=True`.
   - `frontend/nginx.conf:37-50` proxies `/openapi.json`, `/docs`, and `/redoc` openly in production.

---

## 5. Verification Checklist for P0 Exit Gate (G1)

Before marking P0 complete, automated tests (including PostgreSQL integration tests) MUST verify:
- [ ] Every non-public endpoint returns `401 Unauthorized` without valid authentication credentials.
- [ ] Expired, malformed, tampered, or revoked credentials/tokens return `401 Unauthorized`.
- [ ] Authenticated users with wrong roles receive `403 Forbidden` (e.g., `pharmacy_assistant` attempting `/dispense`; `pharmacist` attempting admin/audit routes).
- [ ] Cross-facility reads and writes return `403 Forbidden` or empty filtered lists (Facility A user cannot inspect, activate, credential, dispense, remind, review, or audit Facility B prescriptions).
- [ ] Cross-pharmacy reads and writes return `403 Forbidden` (Pharmacy A pharmacist cannot inspect Pharmacy B stock or dispense from Pharmacy B batches).
- [ ] Service clients cannot access human-only dispensing/admin endpoints, and an e-Buzima service client cannot call RMS stock-event endpoints (and vice versa).
- [ ] Dispensing rejects mismatched prescription credentials (`cred_rx.id != rx.id`), expired credentials, revoked credentials, expired prescriptions, expired stock batches, and duplicate concurrent requests.
- [ ] Audit log captures `actor_type`, `actor_id`, `facility_id`, `pharmacy_id`, `correlation_id`, and `outcome` for authentication, credential issuance/revocation, verification, dispensing, failed authorization, status transitions, and stewardship reviews.
