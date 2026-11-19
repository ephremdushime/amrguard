# ADR-001: Identity, Authentication, and Authorization Architecture

**Status:** Proposed — Pending Product Owner / Institutional Decision on Human IdP Mode  
**Date:** 2026-11-19  
**Owner:** Lead Engineering / Product Owner / Institutional ICT Stakeholders  
**References:** `docs/TECHNICAL_ARCHITECTURE.md` (§2.2, §4, §7, §12), `docs/DEVELOPMENT_ROADMAP.md` (P0.1–P0.5), `docs/security/API_AUTHORIZATION_MATRIX.md`

---

## 1. Context

Static and code-level inspection of AMRGuard (`main` at commit `237fe77`) confirmed:
- The backend has **no human user model, no role model, no session/token verifier, and no facility/pharmacy authorization layer**.
- The only authentication primitive is `require_integration_key` (`backend/app/core/security.py`), a single static shared header (`x-amrguard-integration-key`) that is bypassed when empty in dev/demo/test and bypassed completely in `funder_demo` via `require_funder_demo_ui_or_integration_key`.
- 17 operational routes (prescriptions, credentials, verification, dispensing, stock, traceability, FHIR exports, reminders, audit logs) have **zero authentication**.
- The frontend (`frontend/src/main.tsx`) sends empty headers (`apiHeaders = {}`).
- Per non-negotiable safety rules, we **must not** invent an institutional identity provider or deploy an insecure temporary login mechanism, and human users and integration service clients must have strictly separate authentication paths.

---

## 2. Architectural Principles (Non-Negotiable)

1. **Strict Separation of Human Users and Service Clients:**
   - Human users authenticate via OIDC/OAuth2 or controlled pilot user sessions (`actor_type = "HUMAN"`).
   - Partner integrations (e-Buzima, RMS/eLMIS) authenticate via partner-specific service client credentials / OAuth2 client credentials / mTLS (`actor_type = "SERVICE_CLIENT"`).
   - Patient QR/OTP verification tokens **never** authenticate pharmacy staff; they bind only to a specific prescription verification/dispensing workflow.
2. **IdP-Agnostic Internal Authorization Core:**
   - Regardless of which human IdP is selected with institutional partners, AMRGuard's internal `Principal`, `Role`, `Organization`, `Facility`, `Pharmacy`, and `UserRoleScope` model MUST enforce RBAC and tenant scoping inside the FastAPI backend and service layer.
3. **Explicit, Non-Nullable Scope Semantics:**
   - Never treat `facility_id IS NULL` as "global access". Every `user_role_scopes` record MUST declare an explicit `scope_type` (`PHARMACY`, `FACILITY`, `ORGANIZATION`, `NATIONAL_AGGREGATE`, `PLATFORM`) and a database `CHECK` constraint enforcing that the corresponding target ID is non-null (and all narrower/unrelated IDs are null).
4. **Default Deny:**
   - Every operational route requires an explicit authentication dependency and explicit permission + resource scope check. Unauthenticated or out-of-scope requests fail closed (`401` / `403`) and emit a security audit event.

---

## 3. Decision 1: Human User Authentication Mode (Requires Approval)

### Option A — Institutional OIDC / OAuth2 Federation (Recommended where partner IdP exists)
- **How it works:** Hospital/MoH Identity Provider (e.g., Keycloak, Entra ID, or Rwanda health SSO) issues RS256/ES256 JWT tokens. AMRGuard validates signature via configured JWKS URI, `iss`, `aud`, `exp`, `nbf`, and maps `(issuer, sub)` to a pre-provisioned active AMRGuard `User` record and `UserRoleScope` assignments (or approved role-claim mapping). For browser apps, use Authorization Code + PKCE (ideally via Backend-for-Frontend HttpOnly/Secure/SameSite cookies so tokens are not exposed to JS `localStorage`).
- **Pros:** Meets institutional SSO, MFA, offboarding, and password-policy requirements; AMRGuard handles no staff passwords.
- **Cons:** Requires institutional IdP metadata (`issuer`, `jwks_uri`, client ID, claim mapping) before live pilot deployment.

### Option B — Controlled Pilot Identity Service + OIDC-Ready Interface (Recommended if pilot facilities lack an OIDC IdP)
- **How it works:** Implement a pluggable `IdentityAuthenticator` interface in `backend/app/core/auth.py` supporting:
  1. `OIDCJWTAuthenticator` (validates OIDC JWTs against JWKS for institutional SSO and automated tests), AND
  2. `LocalSessionAuthenticator` (controlled pilot mode: Argon2id password hashing, opaque random session tokens stored as HMAC-SHA256 digests in PostgreSQL `user_sessions` table, HttpOnly + Secure + SameSite=Strict cookies or Bearer opaque session tokens, short idle/absolute TTL, explicit logout/revocation, account lockout/rate limiting, forced password rotation, disabled-account denial).
- **Pros:** Unblocks secure synthetic staging, end-to-end browser workflow testing, and pilot hospitals that do not yet operate an OIDC IdP, while maintaining a zero-rewrite migration path to institutional OIDC (Option A) by keeping the exact same `Principal` and RBAC/scope layer.
- **Cons:** Requires strict credential lifecycle governance (password policy, lockout, rotation, backup/audit) when pilot local accounts are enabled.

### Option C — Trusted Identity-Aware Reverse Proxy / Gateway Assertion (Not Recommended Alone)
- **How it works:** Institutional gateway (e.g., OAuth2-Proxy / Envoy / Kong) authenticates staff and forwards signed identity assertions (JWT or mTLS-authenticated header) to AMRGuard.
- **Pros:** Offloads login UI to institutional infrastructure.
- **Cons:** Dangerous if misconfigured (header spoofing if backend port is reachable directly); still requires AMRGuard internal RBAC/scope enforcement and signed token verification (which makes it functionally a subset of Option A).

### Engineering Recommendation
Adopt **Option B's pluggable architecture** (standard `OIDC/JWT` verifier + optional controlled `LocalSessionAuthenticator` disabled by default in `production` unless explicitly approved via configuration flag `AUTH_MODE=oidc|pilot_local`), **subject to Product Owner approval** before enabling local password login in any non-development environment.

---

## 4. Decision 2: Service-Client Authentication (No External Blocker)

Replace the single shared `INTEGRATION_API_KEY` with a dedicated `service_clients` + `service_client_credentials` model:
- Each partner (e.g., `ebuzima-facility-a`, `rms-central`) has its own `ServiceClient` record with:
  - `id`, `client_code`, `partner_type` (`EMR`, `SUPPLY_CHAIN`, `PHARMACY_POS`)
  - Explicit `scopes` (e.g., `integrations:ebuzima:prescriptions:write`, `integrations:rms:stock:write`)
  - Explicit `allowed_facility_ids` / `allowed_pharmacy_ids`
  - `status` (`ACTIVE`, `SUSPENDED`, `REVOKED`)
- Credentials stored as `key_prefix` (for indexed lookup/audit) + `secret_hash` (keyed HMAC-SHA256 / Argon2id), with `expires_at` and `revoked_at` to support zero-downtime key rotation.
- **Backward compatibility during transition:** Keep `x-amrguard-integration-key` header support mapped strictly to scoped `ServiceClient` lookup (never granting global/human privileges), and remove the empty-key bypass in all operational paths. Add OAuth2 `client_credentials` / signed-request (HMAC timestamp+nonce) adapter support when partner contracts specify them.

---

## 5. Target Data Model Additions for P0 Security

New tables / columns (to be delivered via reversible Alembic migrations):
1. `organizations(id, code, name, status, created_at)`
2. `facilities`: add `organization_id` FK (nullable only during backfill migration, enforced non-null for new operational facilities).
3. `pharmacies`: add `facility_id` FK (nullable for standalone retail pharmacies) and `organization_id` FK.
4. `users(id, identity_issuer, identity_subject, username, display_name, email, password_hash_nullable, status, failed_login_attempts, locked_until, created_at, updated_at)` — unique `(identity_issuer, identity_subject)`.
5. `roles(id, code, description)` — seeded with canonical role codes (`prescriber`, `pharmacist`, `pharmacy_assistant`, `stewardship_officer`, `facility_admin`, `national_analyst`, `platform_operator`).
6. `user_role_scopes(id, user_id, role_id, scope_type, organization_id, facility_id, pharmacy_id, active, granted_by_user_id, created_at, revoked_at)` — with DB `CHECK` constraint enforcing scope integrity.
7. `user_sessions(id, user_id, token_hash, created_at, last_seen_at, expires_at, revoked_at, ip_address_truncated, user_agent_hash)` (if Option B approved).
8. `service_clients(id, client_code, name, partner_type, status, created_at)` + `service_client_scopes` + `service_client_credentials(id, service_client_id, key_prefix, secret_hash, expires_at, revoked_at, created_at)`.
9. `prescription_credentials`: add `issued_by_user_id`, `issued_at`, `intended_pharmacy_id`, `revoked_at`, `revoked_by_user_id`, `failed_attempts`, `token_salt` (for keyed HMAC-SHA256 digests).
10. `dispensing_transactions`: add `actor_user_id` FK -> `users.id` (nullable for legacy rows only; required for all new dispenses).
11. `stewardship_reviews`: add `reviewer_user_id` FK -> `users.id`.
12. `audit_events`: extend with `actor_type`, `actor_id`, `facility_id`, `pharmacy_id`, `correlation_id`, `outcome` (`SUCCESS`, `DENIED`, `FAILURE`), plus PostgreSQL trigger/role protections preventing `UPDATE`/`DELETE` by the application role.

---

## 6. Institutional & Product Owner Decisions Required

Before finalizing P0 Task 2 (Human Authentication), please confirm:
1. **Pilot Human Identity Mode:** Approve **Option A (OIDC/OAuth2 JWT + JWKS only)**, **Option B (OIDC + Controlled Pilot Local Sessions with Argon2id & HttpOnly cookies)**, or **Option C (Gateway-signed JWT assertion)**?
2. **Cross-Facility Dispensing Policy:** In the Rwanda hospital/community pharmacy pilot, may a standalone community pharmacy dispense a prescription issued by Hospital Facility A (via valid QR/OTP + approved pharmacy network), or is dispensing strictly restricted to pharmacies linked to the prescribing facility?
3. **Credential Consumption Policy:** Should a prescription QR/OTP be revoked/invalidated automatically once `rx.status == 'COMPLETED'`, and should partial dispenses allow reuse within TTL or require fresh verification?
4. **Python Runtime Target:** Local workstation uses Python `3.15.2` while `backend/Dockerfile` pins `python:3.13-slim` and `backend/requirements.txt` pins `psycopg[binary]==3.2.6` / `pydantic==2.11.3` (which lack Python 3.15 wheels). Should we standardize development on Python 3.13 (Docker / pyenv) or update `requirements.txt` pins for Python 3.13+ compatibility?
