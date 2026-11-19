# ADR-001: Identity, Authentication, Authorization, and Runtime Architecture

**Status:** Approved (Development & Synthetic Testing Only — does not authorize production deployment, real patient data, live dispensing, or certified partner claims)  
**Date Approved:** 2026-11-19  
**Owner:** Product Owner / Lead Engineering / Institutional ICT Stakeholders  
**References:** `docs/PRODUCT_MASTER_BLUEPRINT.md`, `docs/TECHNICAL_ARCHITECTURE.md` (§2.2, §4, §7, §12), `docs/DEVELOPMENT_ROADMAP.md` (P0.1–P0.5), `docs/security/API_AUTHORIZATION_MATRIX.md`

---

## 1. Context

Baseline inspection of AMRGuard (`main` at commit `237fe77`) established that:
- The backend had no human user model, no role model, no session or OIDC token verifier, and no facility/pharmacy authorization layer.
- Only `require_integration_key` (`backend/app/core/security.py`) existed — a single static shared header (`x-amrguard-integration-key`) bypassed when empty outside `sandbox`/`funder_demo`/`production` and bypassed completely in `funder_demo` via `require_funder_demo_ui_or_integration_key`.
- 17 operational routes had zero authentication or authorization.
- The frontend (`frontend/src/main.tsx`) sent empty headers (`apiHeaders = {}`).
- `backend/Dockerfile` targeted Python `3.13-slim` while host environments varied, and no PostgreSQL concurrency/locking/audit-immutability test suite existed.

---

## 2. Recorded Decisions (Approved 2026-11-19)

### Decision 1 — Human Identity Provider Mode (`P0-02`): APPROVED — Option B (Pluggable OIDC/OAuth2 + Controlled Local Pilot Sessions)
- **Institutional OIDC/OAuth2 JWT authentication with JWKS validation** is the default and primary human authentication path (`OIDCJWTAuthenticator`), validating signature (`RS256`/`ES256`), `iss`, `aud`, `exp`, `nbf`, and mapping `(iss, sub)` to an active pre-provisioned AMRGuard `User` and active `UserRoleScope` grants.
- **Controlled local sessions** (`LocalSessionAuthenticator`) are supported for local development, synthetic staging, and explicitly authorized pilot environments:
  - Password hashing uses **Argon2id** (`argon2-cffi`).
  - Sessions use cryptographically random opaque tokens stored only as keyed HMAC-SHA256 digests in `user_sessions`, delivered via **`HttpOnly`, `Secure` (enabled by default; disabled only via explicit local-HTTP dev config), `SameSite=Strict`** cookies.
  - **CSRF protection** is enforced on all cookie-authenticated state-changing requests (`POST`, `PUT`, `PATCH`, `DELETE`) via a double-submit `X-CSRF-Token` header verified against a hashed per-session CSRF secret using constant-time comparison.
  - **Session lifecycle:** idle expiry, absolute expiry, explicit logout revocation (`POST /api/v1/auth/logout`), and revoke-all-sessions (`POST /api/v1/auth/sessions/revoke-all`).
  - **Account & brute-force protection:** sliding-window login rate limiting, per-account failed-attempt lockout (`failed_login_attempts`, `locked_until`), and immediate denial for inactive/disabled accounts.
  - **Production safeguard:** Local authentication is **disabled by default in `production`** (`AUTH_MODE=oidc`, `ALLOW_LOCAL_AUTH=false`) and is rejected by startup validation in `production` unless both `ALLOW_LOCAL_AUTH=true` AND an explicit non-empty `LOCAL_AUTH_PRODUCTION_APPROVAL_REF` are provided.
- **Strict separation of human and service-client auth:**
  - Human endpoints accept `HUMAN` principals (`oidc_jwt` or `local_session`) only; service-client credentials cannot authenticate as human clinical staff.
  - Partner integration endpoints accept `SERVICE_CLIENT` principals via per-partner scoped credentials (`service_clients`, `service_client_scopes`, `service_client_credentials`) with key prefix + keyed HMAC-SHA256 digest, expiry, rotation, and revocation.
  - Patient QR/OTP verification tokens **never** authenticate pharmacy staff.

### Decision 2 — Cross-Facility Dispensing Policy (`P0-03`): APPROVED — Conditional Cross-Facility Dispensing
- Facility-level and pharmacy-level isolation remain **strictly default-deny**.
- Same-facility dispensing requires an authenticated active `pharmacist` assigned to an active `pharmacy` whose `facility_id == prescription.facility_id`.
- An authorized retail or community pharmacy (`pharmacy.facility_id != prescription.facility_id`) may dispense a prescription originating from another facility **only when ALL of the following hold**:
  1. Deployment configuration explicitly enables cross-facility dispensing (`CROSS_FACILITY_DISPENSING_ENABLED=true`; **default: `false`**).
  2. The prescription explicitly permits external dispensing (`prescription.allow_external_dispensing == True`; **default: `False`**).
  3. An active `PharmacyNetwork` explicitly links **both** the prescribing facility (`pharmacy_network_facilities.active == True`) AND the dispensing pharmacy (`pharmacy_network_pharmacies.active == True`).
  4. Medicine permissions on the pharmacy's network membership explicitly permit the prescribed antibiotic (`allow_all_medicines == True` or `antibiotic.code` exists in `pharmacy_network_medicine_permissions` with `active == True`).
  5. The dispensing staff member is authenticated with the `pharmacist` role scoped to that dispensing pharmacy, the QR/OTP credential is valid and bound to the prescription, the prescription is valid/non-expired, and the stock batch is non-expired and belongs to that pharmacy.
  6. Both `prescribing_facility_id` (`rx.facility_id`) and `dispensing_facility_id` (`pharmacy.facility_id`, nullable for standalone retail pharmacies) plus `pharmacy_id`, `actor_user_id`, and `is_cross_facility=True` are persisted on `dispensing_transactions` and recorded in `audit_events`.
- A valid QR/OTP alone never authorizes dispensing or cross-facility access.

### Decision 3 — Python Runtime & Dependency Alignment (`P0-07`): APPROVED — Python 3.13
- Standardize local development, Docker (`backend/Dockerfile`), and GitHub Actions CI on **Python 3.13** (`backend/.python-version` = `3.13`).
- Pin all backend dependencies to versions verified against Python 3.13. Do not expand supported runtime range to Python 3.14–3.15 without a separate compatibility assessment.
- **Justified new dependencies added for P0:**
  - `argon2-cffi==23.1.0`: OWASP-recommended Argon2id password hashing required by Decision 1.
  - `PyJWT[crypto]==2.10.1`: Standards-compliant OIDC/OAuth2 JWT + JWKS (`RS256`/`ES256`) signature validation required by Decision 1.

### Decision 4 — PostgreSQL Concurrency & Integration Testing (`P0-06`): APPROVED
- Execute PostgreSQL 16 integration, locking, concurrency, stock-consistency, and append-only audit-trigger tests against an **isolated, disposable container/test database containing synthetic data only**.
- Never connect test harnesses or baseline migrations to an operational or production database.

---

## 3. Data Model Additions (Migration `0006_p0_security_rbac_audit`)

1. **Tenancy & Networks:**
   - `organizations(id, code, name, active, created_at)`
   - `facilities`: add `organization_id` (nullable FK for safe migration of existing rows)
   - `pharmacies`: add `organization_id`, `facility_id` (nullable for standalone retail pharmacies), `pharmacy_type` (`FACILITY_PHARMACY` | `COMMUNITY_PHARMACY`)
   - `pharmacy_networks(id, code, name, active, created_at)`
   - `pharmacy_network_facilities(id, network_id, facility_id, active, created_at)`
   - `pharmacy_network_pharmacies(id, network_id, pharmacy_id, allow_all_medicines, active, created_at)`
   - `pharmacy_network_medicine_permissions(id, network_id, pharmacy_id, antibiotic_code, active, created_at)`
2. **Human Identity & Explicit-Scope RBAC:**
   - `users(id, identity_issuer, identity_subject, username, display_name, email, password_hash, active, failed_login_attempts, locked_until, must_change_password, created_at, updated_at)`
   - `roles(id, code, description)`
   - `user_role_scopes(id, user_id, role_id, scope_type, organization_id, facility_id, pharmacy_id, active, granted_by_user_id, created_at, revoked_at)` — enforced via DB `CHECK` constraint `ck_user_role_scopes_explicit_scope` so nullable fields can never accidentally grant global access.
   - `user_sessions(id, user_id, token_hash, csrf_token_hash, created_at, last_seen_at, expires_at, absolute_expires_at, revoked_at, ip_address_truncated, user_agent_hash)`
3. **Scoped Service Clients:**
   - `service_clients(id, client_code, name, partner_type, active, created_at)`
   - `service_client_scopes(id, service_client_id, scope, facility_id, pharmacy_id, active)`
   - `service_client_credentials(id, service_client_id, key_prefix, secret_hash, expires_at, revoked_at, created_at)`
4. **Accountability & Tamper-Resistant Audit:**
   - `prescriptions`: add `allow_external_dispensing` (default `false`)
   - `prescription_credentials`: add `token_salt`, `issued_by_user_id`, `issued_at`, `intended_pharmacy_id`, `revoked_at`, `revoked_by_user_id`, `failed_attempts`
   - `dispensing_transactions`: add `actor_user_id`, `prescribing_facility_id`, `dispensing_facility_id`, `is_cross_facility`
   - `stewardship_reviews`: add `reviewer_user_id`
   - `audit_events`: add `actor_type`, `actor_id`, `facility_id`, `pharmacy_id`, `correlation_id`, `outcome` + PostgreSQL `BEFORE UPDATE OR DELETE` trigger `trg_audit_events_append_only` blocking modification/deletion at the database layer (complemented by SQLAlchemy ORM `before_update`/`before_delete` guards).

---

## 4. Consequences & Boundaries

- **Positive:** Every operational endpoint enforces default-deny auth + RBAC + facility/pharmacy scoping; human and service-client paths are strictly isolated; dispensing is fully attributable across both same-facility and approved-network cross-facility workflows; audit records are append-only in PostgreSQL.
- **Limitations / Follow-ons:**
  - Single-instance sliding-window rate limiting should be backed by shared Redis state before horizontal multi-replica deployment (P3).
  - Live institutional OIDC metadata (`OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`) and formal hospital pharmacy network provisioning must be agreed with participating institutions before pilot go-live.
  - Database-role least-privilege grants (`REVOKE UPDATE, DELETE ON audit_events` for the app DB role) should be applied in staging/pilot PostgreSQL provisioning in addition to the trigger.
