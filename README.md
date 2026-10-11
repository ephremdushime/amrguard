# AMRGuard

**Antibiotic-specific interoperability and transaction layer.**

AMRGuard connects authenticated antibiotic prescriptions with pharmacy verification and dispensing while providing batch-level traceability and antibiotic-use analytics. It is designed to complement existing clinical, supply-chain, pharmacy and insurance systems rather than replace them.

## Current scope

AMRGuard receives prescribing orders from e-Buzima and handles validation, pharmacy credentialing, dispensing authorization, stock/batch traceability, audit records, and stewardship reminder scheduling. The repository contains canonical integration contracts, not live government endpoint mappings or partner credentials. Production activation requires the institution's approved specifications, identity/access controls, clinical governance, privacy review, and operational sign-off.

### Core workflow

`e-Buzima -> AMRGuard validation -> QR/OTP -> Pharmacy verification -> stock/batch check -> dispensing -> traceability -> analytics`

### Run locally

Backend:

```bash
cd backend
python -m venv .venv
# activate the environment
pip install -r requirements.txt
uvicorn app.main:app --reload
```

For an existing database already tracked by Alembic, apply pending migrations from `backend` before startup:

```bash
alembic upgrade head
```

The stewardship review queue requires the new `0005_stewardship_reviews` migration. Back up existing databases before upgrading. Unversioned legacy demo databases are not modified automatically; migrate a copy or configure a fresh local database first.

Frontend:

```bash
cd frontend
npm install
npm run dev
```

API docs: `http://localhost:8000/docs`

### Environment

Copy `.env.example` to `.env`. For production, configure PostgreSQL, a strong integration secret, restricted CORS origins, HTTPS and the approved authentication mechanism.

### Production deployment

The default `docker-compose.yml` is for local development only. `docker-compose.prod.yml` is a restricted single-host deployment baseline, not a complete production identity or regulatory solution. It binds the web service to loopback by default. Put it behind the institution's TLS and identity-aware gateway with authentication and role-based authorization for every user; AMRGuard does not yet implement user sessions or pharmacy/prescriber roles. Create a private `.env` file from `.env.production.example`, set unique values, then run:

```bash
docker compose --env-file .env -f docker-compose.prod.yml config
docker compose --env-file .env -f docker-compose.prod.yml up --build -d
```

Generate secrets with `openssl rand -hex 32`; use a different value for the database password and integration key. Set `ALLOWED_ORIGINS` to the exact public HTTPS origin, such as `https://amrguard.example.org`. The API and database are private to the Compose network; Nginx serves the built frontend and proxies API/docs on the same origin. Migrations run before the API starts, and production does not auto-create tables or seed demo data. Back up the `postgres_data` volume and test restores before relying on it.

This is not yet a certified production health system. Before operational use, complete identity and role authorization at the gateway, managed secrets/key rotation, TLS/network controls, centralized audit/metrics, tested backup and restore, approved clinical formulary/rules, e-Buzima and RMS contract certification, pharmacy onboarding, SMS provider delivery callbacks, consent governance, and privacy/security review. Do not expose this service publicly until those controls have been approved.

### Partner sandbox

For a separate, restricted integration environment using synthetic or explicitly approved partner test data, see [docs/partner-sandbox.md](docs/partner-sandbox.md). It uses `docker-compose.sandbox.yml` and `.env.sandbox`; keep the integration key server-side and put the web service behind the partner-approved TLS and identity gateway.

### Restricted funder demo

For an isolated synthetic-data walkthrough for invited reviewers, see [docs/funder-demo.md](docs/funder-demo.md). It uses `docker-compose.funder-demo.yml`, its own database volume, and a web Basic Auth gate; keep it behind TLS and an access-controlled gateway.

### Testing

Run:

```bash
pytest -q
```

The included tests cover health, external prescription idempotency, credential verification, quantity enforcement and dispensing idempotency. Clinical rule thresholds in demo seed data are explicitly illustrative and must be replaced with approved guidance before real use.

## Integration philosophy

AMRGuard exposes stable internal API contracts and isolates external dependencies in adapters. The current inbound prescription route is `POST /api/v1/integrations/ebuzima/prescriptions` and the stock movement route is `POST /api/v1/integrations/rms/stock-events`; both require the configured integration key in `x-amrguard-integration-key`. These are AMRGuard canonical contracts, not claims about external government endpoint names. When the institution supplies approved e-Buzima, RMS/eLMIS, pharmacy, identity, or SMS specifications, certified adapters must map those contracts and handle retries, signatures, delivery acknowledgements, and operational monitoring.


## v0.7.0 Pitch-final additions
- Deliberate risk-control demo scenario for showing a blocked quantity mismatch.
- Transaction and audit surfaces remain API-backed.
- Demo-only scenario endpoint is disabled outside development/demo/test environments.
- Pitch language distinguishes demonstration adapters from live institutional integrations.

## Embedded stewardship pilot features
- `POST /api/v1/stewardship/support` returns an embeddable quantity check and review prompt for a source prescribing screen. It does not provide treatment recommendations; AWaRe remains unclassified without a verified catalogue.
- A successful dispense creates an auditable post-dispense review task. Complete it through `POST /api/v1/stewardship/reviews/{id}/complete` with an outcome, reason, and reviewer reference.
- Analytics include prescription/dispense reconciliation and review completion, with an optional facility breakdown. Agree pilot denominators and data governance before reporting results.
- Development Integrations includes a synthetic contract tester for the canonical prescription intake endpoint. It is not connected to e-Buzima; use synthetic data and sandbox credentials only.

## Pitch demonstration
1. Create a valid antibiotic prescription through the e-Buzima simulator.
2. Review AMRGuard validation.
3. Generate the short-lived QR/OTP credential.
4. Verify it from the pharmacy workflow.
5. Select an antibiotic batch and dispense the authorized quantity.
6. Open traceability to show the batch → pharmacy → prescription → transaction chain.
7. Return to analytics to show the transaction reflected in the data layer.
8. Run the risk scenario to demonstrate that an intentionally mismatched quantity is blocked.

AMRGuard is an integration-ready MVP, not a claim of live e-Buzima/RMS integration or production certification.
