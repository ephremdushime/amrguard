# AMRGuard — Disaster Recovery & Backup/Restore Runbook

**Document Version:** 1.0  
**Effective Date:** 2026-11-23  
**Status:** Approved for Institutional & Pilot Deployments  
**Classification:** Operational Security & Business Continuity  

---

## 1. Objectives & SLO Targets

| Metric | Target | Rationale |
|---|---|---|
| **RPO (Recovery Point Objective)** | **$\le$ 15 minutes** | Maximum allowable data loss during catastrophe. Point-in-time recovery (WAL archiving / automated 15-minute snapshots) ensures clinical and dispensing transaction loss is minimized. |
| **RTO (Recovery Time Objective)** | **$\le$ 30 minutes** | Maximum allowable downtime before prescription verification and emergency offline dispensing failover are operational. |
| **Integrity Assurance** | **SHA-256 Checksum** | Every backup artifact is cryptographically hashed and verified before storage and upon recovery rehearsal. |

---

## 2. Backup Strategy

### 2.1 Automated Snapshot Schedule
- **Production PostgreSQL:**
  - Continuous WAL (Write-Ahead Logging) archiving to encrypted, versioned object storage.
  - Hourly base snapshots (`pg_dump -Fc` or volume snapshot) with 30-day retention.
  - Nightly cold verification restore to isolated staging environment.
- **Pilot SQLite / Standalone Mode:**
  - Automated transactional snapshot via `sqlite3.backup()` API using `scripts/backup_restore_drill.py`.
  - Immutable SHA-256 checksum recorded alongside every `.db` archive.

### 2.2 Storage & Security
- Backups are encrypted at rest using AES-256.
- Write-Once-Read-Many (WORM) storage policy applies to prevent ransomware tampering.
- Access to backup buckets is restricted to the platform operator service principal with multi-factor authentication.

---

## 3. Disaster Recovery Execution Procedure

### Phase 1: Incident Assessment & Declaration (T + 0 to T + 5 min)
1. Incident Commander confirms loss of primary database or infrastructure.
2. Direct all edge health facility workstations into **Offline Dispensing Mode** (local policy-bound queue operates autonomously).

### Phase 2: Snapshot Retrieval & Verification (T + 5 to T + 12 min)
1. Identify the latest valid backup snapshot matching target RPO ($\le$ 15 min).
2. Retrieve the snapshot and verify its SHA-256 integrity checksum:
   ```bash
   sha256sum amrguard_backup_TIMESTAMP.db
   ```
3. If checksum mismatch is detected, failover to immediate predecessor snapshot.

### Phase 3: Database Restoration (T + 12 to T + 22 min)
1. Provision target recovery database instance.
2. Execute restoration command:
   ```bash
   # Automated script
   python scripts/backup_restore_drill.py <BACKUP_FILE>
   ```
3. Verify that database triggers and constraints are active:
   - `trg_audit_events_append_only` (PostgreSQL)
   - `chk_user_role_scopes_exclusive` (Exclusive tenancy scope)

### Phase 4: Integrity Verification & Service Resumption (T + 22 to T + 30 min)
1. Execute health readiness probe:
   ```bash
   curl -f http://localhost:8000/health/ready
   ```
2. Verify table counts for Prescriptions, DispensingTransactions, StockBatches, and AuditEvents.
3. Switch DNS/ingress routing to recovered instance.
4. Trigger pending offline queue reconciliation:
   ```bash
   POST /api/v1/dispensing/offline-reconcile
   ```
5. Declare recovery complete and notify MoH/RBC emergency operations center.

---

## 4. Rehearsal Cadence & Governance
- **Automated Drill:** Executed in CI and during every release build.
- **Manual Tabletop Drill:** Semi-annual live rehearsal with clinical and ICT teams.
- **Audit Requirement:** All drill reports are logged in the platform compliance register.
