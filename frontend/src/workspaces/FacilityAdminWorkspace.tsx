import React, { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  AlertOctagon,
  Building2,
  CheckCircle2,
  GitBranch,
  Network,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react';
import { apiFetch, type AuthUser } from '../authApi';
import { AuditTrailPanel } from '../components/AuditTrailPanel';
import { OfflineReconciliationPanel } from '../components/OfflineReconciliationPanel';
import { QuarantineCataloguePanel } from '../components/QuarantineCataloguePanel';
import { StaffAndFacilityAdminPanel } from '../components/StaffAndFacilityAdminPanel';
import { TraceabilityView } from '../components/TraceabilityView';
import type {
  FacilityMeasure,
  ObservabilityMetrics,
  OperationalBatch,
  OperationalRx,
  OperationalTransaction,
  OperationsSummary,
  OutboxDeadLetterItem,
  Pharmacy,
} from '../types';

interface FacilityAdminWorkspaceProps {
  api: string;
  user: AuthUser;
  activeSection: string;
  refreshKey: number;
  onNotify: (message: string) => void;
  onUnauthorized: () => void;
}

export function FacilityAdminWorkspace({
  api,
  activeSection,
  refreshKey,
  onNotify,
  onUnauthorized,
}: FacilityAdminWorkspaceProps) {
  // Overview state
  const [summary, setSummary] = useState<OperationsSummary | null>(null);
  const [facilities, setFacilities] = useState<FacilityMeasure[]>([]);
  const [pharmacies, setPharmacies] = useState<Pharmacy[]>([]);
  const [telemetry, setTelemetry] = useState<ObservabilityMetrics | null>(null);

  // Exceptions state
  const [blockedRx, setBlockedRx] = useState<OperationalRx[]>([]);
  const [deadLetters, setDeadLetters] = useState<OutboxDeadLetterItem[]>([]);

  // Audit & Traceability state
  const [batches, setBatches] = useState<OperationalBatch[]>([]);
  const [transactions, setTransactions] = useState<OperationalTransaction[]>([]);

  const loadSectionData = useCallback(async () => {
    try {
      if (activeSection === 'overview') {
        const [sumRes, facRes, phRes, obsRes] = await Promise.all([
          apiFetch(`${api}/api/v1/analytics/summary`),
          apiFetch(`${api}/api/v1/analytics/facilities`),
          apiFetch(`${api}/api/v1/pharmacies`),
          apiFetch(`${api}/api/v1/observability/metrics?format=json`),
        ]);
        if ([sumRes, facRes, phRes, obsRes].some((r) => r.status === 401)) return onUnauthorized();
        if (sumRes.ok) setSummary(await sumRes.json());
        if (facRes.ok) {
          const data = await facRes.json();
          setFacilities(data.facilities || []);
        }
        if (phRes.ok) setPharmacies(await phRes.json());
        if (obsRes.ok) setTelemetry(await obsRes.json());
      } else if (activeSection === 'exceptions') {
        const [rxRes, dlqRes] = await Promise.all([
          apiFetch(`${api}/api/v1/prescriptions?limit=200`),
          apiFetch(`${api}/api/v1/integrations/outbox/dead-letter?limit=100`),
        ]);
        if ([rxRes, dlqRes].some((r) => r.status === 401)) return onUnauthorized();
        if (rxRes.ok) {
          const allRx: OperationalRx[] = await rxRes.json();
          setBlockedRx(allRx.filter((r) => r.status === 'BLOCKED' || r.status === 'WARNING'));
        }
        if (dlqRes.ok) setDeadLetters(await dlqRes.json());
      } else if (activeSection === 'audit') {
        const [bRes, txRes] = await Promise.all([
          apiFetch(`${api}/api/v1/stock/batches`),
          apiFetch(`${api}/api/v1/transactions?limit=200`),
        ]);
        if ([bRes, txRes].some((r) => r.status === 401)) return onUnauthorized();
        if (bRes.ok) setBatches(await bRes.json());
        if (txRes.ok) setTransactions(await txRes.json());
      }
    } catch {
      onNotify('Unable to load facility administration data');
    }
  }, [api, activeSection, onNotify, onUnauthorized]);

  useEffect(() => {
    loadSectionData();
  }, [loadSectionData, refreshKey]);

  if (activeSection === 'users') {
    return (
      <StaffAndFacilityAdminPanel
        api={api}
        isPlatformOperator={false}
        onNotify={onNotify}
        onUnauthorized={onUnauthorized}
      />
    );
  }

  if (activeSection === 'quarantine') {
    return (
      <QuarantineCataloguePanel
        api={api}
        eyebrow="FACILITY CATALOGUE & INBOUND QUARANTINE"
        onNotify={onNotify}
      />
    );
  }

  if (activeSection === 'exceptions') {
    return (
      <div style={{ display: 'grid', gap: 16 }}>
        <div className="pageTitle">
          <div>
            <span className="eyebrow">FACILITY EXCEPTION MANAGEMENT</span>
            <h1>Blocked Prescriptions, Offline Sync & Outbox Failures</h1>
            <p>
              Operational exception cockpit for facility administrators: reconcile offline dispensing bundles, monitor
              blocked/warning prescriptions, and inspect failed partner reconciliation outbox events.
            </p>
          </div>
          <span className="sourceBadge">
            <AlertOctagon size={14} /> {blockedRx.length} flagged orders · {deadLetters.length} DLQ events
          </span>
        </div>

        <OfflineReconciliationPanel
          api={api}
          canReconcile={true}
          eyebrow="FACILITY OFFLINE RECONCILIATION"
          title="Pharmacy Offline Dispensing Queue"
          onNotify={onNotify}
        />

        <div className="twoCol" style={{ margin: 0, maxWidth: 'none' }}>
          <section className="panel">
            <div className="panelHead">
              <div>
                <span className="eyebrow">PRESCRIPTION VALIDATION EXCEPTIONS</span>
                <h2>Blocked & Warning Orders ({blockedRx.length})</h2>
              </div>
              <TriangleAlert size={17} />
            </div>
            <div style={{ marginTop: 12, maxHeight: 320, overflowY: 'auto', display: 'grid', gap: 8 }}>
              {blockedRx.length ? (
                blockedRx.map((rx) => (
                  <div key={rx.id} className="reviewItem reviewPending" style={{ gridTemplateColumns: '1fr', gap: 4 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <strong>
                        {rx.code} · {rx.patient_reference}
                      </strong>
                      <span className="statusPill dangerPill">{rx.status}</span>
                    </div>
                    <small>
                      {rx.items[0]?.antibiotic} ({rx.items[0]?.authorized_quantity} units) · Source{' '}
                      <code>{rx.external_id}</code>
                    </small>
                  </div>
                ))
              ) : (
                <div className="emptyState">
                  <span>
                    <CheckCircle2 size={22} />
                  </span>
                  <strong>No blocked or warning prescriptions</strong>
                  <p>All ingested prescriptions for your facility passed deterministic regimen checks.</p>
                </div>
              )}
            </div>
          </section>

          <section className="panel">
            <div className="panelHead">
              <div>
                <span className="eyebrow">PARTNER OUTBOX DEAD-LETTER QUEUE</span>
                <h2>Failed Sync Events ({deadLetters.length})</h2>
              </div>
              <Network size={17} />
            </div>
            <p className="muted" style={{ marginTop: 6 }}>
              Read-only facility visibility into partner delivery failures. Manual retry dispatch is restricted to
              Platform Operators.
            </p>
            <div style={{ marginTop: 10, maxHeight: 280, overflowY: 'auto', display: 'grid', gap: 8 }}>
              {deadLetters.length ? (
                deadLetters.map((item) => (
                  <div key={item.id} className="reviewItem reviewPending" style={{ gridTemplateColumns: '1fr', gap: 4 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <strong>
                        #{item.id} · {item.destination_system} · {item.event_type}
                      </strong>
                      <span className="statusPill dangerPill">{item.status}</span>
                    </div>
                    <small>
                      Aggregate: {item.aggregate_type}:{item.aggregate_id} · Retries: {item.retry_count}
                    </small>
                    {item.error_message && <small style={{ color: '#a34d46' }}>{item.error_message}</small>}
                  </div>
                ))
              ) : (
                <div className="emptyState">
                  <span>
                    <CheckCircle2 size={22} />
                  </span>
                  <strong>Outbox dead-letter queue is empty</strong>
                  <p>No RMS or e-Buzima reconciliation messages are currently stuck in dead-letter state.</p>
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    );
  }

  if (activeSection === 'audit') {
    return (
      <div style={{ display: 'grid', gap: 18 }}>
        <AuditTrailPanel
          api={api}
          scopeMode="facility"
          eyebrow="FACILITY GOVERNANCE AUDIT"
          title="Facility-Scoped Audit Trail"
        />
        <TraceabilityView api={api} batches={batches} transactions={transactions} />
      </div>
    );
  }

  // Default section: 'overview'
  const validationRate = summary
    ? Math.round((summary.validated / Math.max(summary.prescriptions, 1)) * 100)
    : 0;

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="pageTitle">
        <div>
          <span className="eyebrow">FACILITY ADMINISTRATION WORKSPACE</span>
          <h1>Facility Operations, Pharmacies & Governance Posture</h1>
          <p>
            Site-level oversight of antibiotic prescription reconciliation, connected pharmacies, stewardship review
            completion, and operational health strictly scoped to your authorized facility.
          </p>
        </div>
        <span className="sourceBadge">
          <Building2 size={14} /> {facilities[0]?.facility_name || 'Authorized Facility'} · {pharmacies.length}{' '}
          pharmacies
        </span>
      </div>

      <div className="metricGrid">
        <div className="metric">
          <div className="metricIcon">
            <ShieldCheck size={16} />
          </div>
          <span>Validation Rate</span>
          <strong>{validationRate}%</strong>
        </div>
        <div className="metric">
          <div className="metricIcon">
            <GitBranch size={16} />
          </div>
          <span>Rx Reconciliation</span>
          <strong>{summary?.prescription_dispense_reconciliation_rate ?? 0}%</strong>
        </div>
        <div className="metric">
          <div className="metricIcon">
            <TriangleAlert size={16} />
          </div>
          <span>Blocked Orders</span>
          <strong>{summary?.blocked ?? 0}</strong>
        </div>
        <div className="metric">
          <div className="metricIcon">
            <Activity size={16} />
          </div>
          <span>Review Completion</span>
          <strong>{summary?.stewardship_review_completion_rate ?? 0}%</strong>
        </div>
        <div className="metric">
          <div className="metricIcon">
            <Network size={16} />
          </div>
          <span>Outbox Pending / DLQ</span>
          <strong>
            {telemetry ? `${telemetry.outbox_pending} / ${telemetry.outbox_dead_letter}` : '—'}
          </strong>
        </div>
        <div className="metric">
          <div className="metricIcon">
            <Building2 size={16} />
          </div>
          <span>Active Pharmacies</span>
          <strong>{pharmacies.filter((p) => p.active).length}</strong>
        </div>
      </div>

      <div className="twoCol" style={{ margin: 0, maxWidth: 'none' }}>
        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">SITE PERFORMANCE</span>
              <h2>Authorized Facility Breakdown</h2>
            </div>
            <span className="statusPill">{facilities.length} facility</span>
          </div>
          <div style={{ marginTop: 12 }}>
            {facilities.length ? (
              facilities.map((fac) => (
                <div className="facilityMeasureRow" key={fac.facility_code}>
                  <div>
                    <b>{fac.facility_name}</b>
                    <small>
                      {fac.facility_code} · {fac.district}
                    </small>
                  </div>
                  <span>{fac.prescriptions} orders</span>
                  <span>{fac.reconciliation_rate}% reconciled</span>
                  <span>{fac.review_completion_rate}% reviewed</span>
                </div>
              ))
            ) : (
              <p className="muted">No facility operational metrics recorded yet.</p>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">CONNECTED DISPENSING SITES</span>
              <h2>Facility Pharmacy Directory ({pharmacies.length})</h2>
            </div>
          </div>
          <div style={{ marginTop: 12 }}>
            {pharmacies.length ? (
              <table className="dataTable">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Pharmacy Name</th>
                    <th>District</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {pharmacies.map((p) => (
                    <tr key={p.id}>
                      <td>
                        <code>{p.code}</code>
                      </td>
                      <td>
                        <strong>{p.name}</strong>
                      </td>
                      <td>{p.district}</td>
                      <td>
                        <span className={`statusPill ${p.active ? 'success' : ''}`}>
                          {p.active ? 'ACTIVE' : 'INACTIVE'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">No pharmacies provisioned for this facility.</p>
            )}
          </div>
        </section>
      </div>

      <div className="notice" style={{ marginTop: 0 }}>
        <ShieldCheck size={15} />
        <span>
          <strong>Identity Provisioning Boundary (ADR-001):</strong> Staff role scopes (`prescriber`, `pharmacist`,
          `stewardship_officer`) are governed centrally via institutional OIDC claims or controlled pilot provisioning.
          Use Quarantine & Exceptions tabs for day-to-day operational reconciliation.
        </span>
      </div>
    </div>
  );
}
