# Restricted funder demo

This deployment is a private, synthetic-data walkthrough for funders and invited reviewers. It is isolated from the partner sandbox and production: it has its own `funder_demo_postgres_data` volume, a distinct `APP_ENV=funder_demo`, an independent database and service credential, and no direct host ports for PostgreSQL or the API. Do not use patient data, partner payloads, or production credentials here.

## Access model

The web app is protected by HTTP Basic Auth at Nginx. Put the loopback-bound web port behind a TLS reverse proxy or an access-controlled VPN/identity-aware gateway. Limit invitation distribution, set an expiry for accounts or the demo window, and rotate the demo password after the review. Basic Auth is an extra demo gate, not staff identity, role-based authorization, or a substitute for a properly secured host and gateway. The API remains on the private Compose network; integration endpoints require a separate server-side integration key that must not be shared with browser users.

The `/health` endpoint is public to the local health checker only. `/health/ready` is behind the Basic Auth gate. Do not expose the bound host port directly to the internet.

## Configure on the demo host

Copy the example file to a private env file and set unique values:

```powershell
Copy-Item .env.funder-demo.example .env.funder-demo
```

Generate different random values for `POSTGRES_PASSWORD`, `INTEGRATION_API_KEY`, and `FUNDER_DEMO_PASSWORD` (for example, `openssl rand -hex 32`). Use the approved demo hostname in `ALLOWED_ORIGINS` and `https://` only. Keep `.env.funder-demo` in the host secret store or otherwise restricted; never commit it or put service keys in frontend build settings.

## Start and check

From the repository root on the host:

```sh
docker compose --env-file .env.funder-demo -f docker-compose.funder-demo.yml config
docker compose --env-file .env.funder-demo -f docker-compose.funder-demo.yml up --build -d
docker compose --env-file .env.funder-demo -f docker-compose.funder-demo.yml ps
```

Alembic migrations run before the API starts. On first boot, the app seeds synthetic facility, pharmacy, prescriber, antibiotic catalog, and batch data. The funder demo routes are enabled only in this environment and do not create demo prescriptions until a reviewer chooses the walkthrough. The demo risk scenario creates only a synthetic blocked order.

After TLS/gateway routing is configured, open the approved demo hostname and use the separate `FUNDER_DEMO_USER` / `FUNDER_DEMO_PASSWORD`. Test the complete product sequence: create a synthetic prescription, review checks, generate and verify the short-lived credential, dispense from the synthetic batch, inspect traceability, and review stewardship/analytics.

## Refresh and stop

To reset the demonstration to its seeded starting state, stop the stack and remove only this project's named volume after confirming the env file points at the funder demo compose project:

```sh
docker compose --env-file .env.funder-demo -f docker-compose.funder-demo.yml down
docker volume ls
```

Have the host operator verify the exact volume name (`amrguard_funder_demo_postgres_data`) before removing it. Removing the volume permanently deletes demo records. Otherwise leave the volume intact for repeat sessions. After the demo window, stop the stack, remove/revoke access, rotate or retire the secrets, and retain or delete data according to the host owner's retention policy.

## Demo limitations to disclose

- Metrics are synthetic operational workflow values, not clinical evidence, national statistics, or demonstrated impact.
- Clinical rules and review timing are illustrative; no prescribing recommendation is approved.
- e-Buzima, RMS/eLMIS, pharmacy, SMS and identity systems are not connected. The app demonstrates AMRGuard-side contracts and a local pharmacy workflow only.
- Basic Auth only restricts the demo webpage. Any broader use needs approved identity, roles, security review, privacy governance, monitoring, backup/restore, and operational ownership.
