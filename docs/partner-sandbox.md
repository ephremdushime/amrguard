# AMRGuard partner sandbox

The sandbox is a restricted integration environment for synthetic partner payloads and approved partner test data. It is separate from the local demo and production compose deployments, uses its own PostgreSQL volume, starts with `APP_ENV=sandbox`, requires PostgreSQL and strong secrets, and applies Alembic migrations before the API starts. The partner integration key is server-to-server only: never put it in `VITE_*` variables, browser storage, frontend bundles, or a user-facing contract tester. The current browser operations UI requires a partner-approved identity-aware gateway before it can be used in the hosted sandbox; API contract calls should be made by partner test clients.

## Before deployment

Agree with the integration owner on the sandbox hostname, source system and facility identifiers, payload mappings, API authentication, test-data rules, support contacts, and test window. Do not use real patient data unless the data owner has explicitly approved that use and the required privacy/security controls are in place.

On the sandbox host, create a private `.env.sandbox` from `.env.sandbox.example`. Generate unique secrets for the database and integration key; never reuse demo or production secrets. Store them in the host's approved secret manager where available. Do not commit the filled env file.

```powershell
Copy-Item .env.sandbox.example .env.sandbox
```

For example, generate hex secrets with OpenSSL on the host:

```sh
openssl rand -hex 32
```

Set `ALLOWED_ORIGINS` to the exact HTTPS origin used by the sandbox. Keep the web service bound to loopback. Place it behind the partner-approved TLS reverse proxy or identity-aware gateway; do not publish ports 8000, 5432, or 8081 directly to the internet. Configure gateway authentication and staff authorization separately: AMRGuard currently provides service-to-service integration-key protection, not user sessions or role authorization.

## Validate and start

From the repository root on the host:

```sh
docker compose --env-file .env.sandbox -f docker-compose.sandbox.yml config
docker compose --env-file .env.sandbox -f docker-compose.sandbox.yml up --build -d
docker compose --env-file .env.sandbox -f docker-compose.sandbox.yml ps
```

The API runs migrations before startup and does not seed demo data in `sandbox`. Check `/health/ready` through the gateway. Keep OpenAPI docs restricted to partner developers and the approved network.

## Partner contract test sequence

1. Confirm the API and database health checks pass and agree a request ID/correlation convention.
2. Submit a synthetic prescription using the canonical e-Buzima intake contract and the provisioned sandbox integration key.
3. Replay the same stable source ID and confirm it is idempotent; change the content with the same ID and confirm conflict handling.
4. Call the embedded prescribing support endpoint with matching and mismatching quantities. Confirm the client displays the response in its own composer and does not treat it as unapproved treatment advice.
5. Post an RMS/eLMIS receipt event, replay it, then test a safe adjustment and a negative-stock rejection.
6. Exercise the pharmacy verification and dispense flow with approved test identities and batches; confirm the transaction links prescription, pharmacy, and batch.
7. Confirm a post-dispense review is created, record a synthetic outcome, and compare the facility analytics with the source test events.
8. Record payload mappings, API versions, expected failure responses, retry behavior, and open issues with the integration owner.

## Operations and exit criteria

- Keep sandbox and production databases, credentials, volumes, hostnames, and backups separate.
- Review logs for accidental patient identifiers; do not enable body logging for clinical payloads.
- Test backup and restore before relying on the environment. Define retention and teardown with the host owner.
- Rotate/revoke partner keys after the test window. Prefer the partner-approved OAuth/client-credential mechanism when agreed; the current key is a prototype contract.
- Treat contract tests as technical validation, not clinical, privacy, security, regulatory, or production certification.
- Do not promote to a pilot until the institution approves the hosting location, data processing, identity/authorization, clinical rule set, monitoring, incident response, and integration mappings.
