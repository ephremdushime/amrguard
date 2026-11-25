import React, { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Cpu,
  Network,
  RefreshCw,
  RotateCw,
  Server,
  ShieldAlert,
  ShieldCheck,
  Terminal,
} from 'lucide-react';
import { apiFetch, type AuthUser } from '../authApi';
import { AuditTrailPanel } from '../components/AuditTrailPanel';
import { OfflineReconciliationPanel } from '../components/OfflineReconciliationPanel';
import { QuarantineCataloguePanel } from '../components/QuarantineCataloguePanel';
import { ServiceClientsPanel } from '../components/ServiceClientsPanel';
import { StaffAndFacilityAdminPanel } from '../components/StaffAndFacilityAdminPanel';
import type {
  ApiMeta,
  EMRConnectorItem,
  ObservabilityMetrics,
  OutboxDeadLetterItem,
  OutboxDispatchStats,
  Pharmacy,
} from '../types';

interface PlatformAdminWorkspaceProps {
  api: string;
  user: AuthUser;
  activeSection: string;
  refreshKey: number;
  isDev: boolean;
  onNotify: (message: string) => void;
  onUnauthorized: () => void;
}

export function PlatformAdminWorkspace({
  api,
  activeSection,
  refreshKey,
  isDev,
  onNotify,
  onUnauthorized,
}: PlatformAdminWorkspaceProps) {
  // Health & Observability state
  const [meta, setMeta] = useState<ApiMeta | null>(null);
  const [dbReady, setDbReady] = useState(false);
  const [metricsJson, setMetricsJson] = useState<ObservabilityMetrics | null>(null);
  const [prometheusText, setPrometheusText] = useState('');
  const [pharmacies, setPharmacies] = useState<Pharmacy[]>([]);

  // Integrations & Outbox DLQ state
  const [connectors, setConnectors] = useState<EMRConnectorItem[]>([]);
  const [deadLetters, setDeadLetters] = useState<OutboxDeadLetterItem[]>([]);
  const [dispatchBusy, setDispatchBusy] = useState(false);
  const [dispatchStats, setDispatchStats] = useState<OutboxDispatchStats | null>(null);
  const [retryingId, setRetryingId] = useState<number | null>(null);

  const loadSectionData = useCallback(async () => {
    try {
      if (activeSection === 'health') {
        const [metaRes, readyRes, jsonRes, promRes, phRes] = await Promise.all([
          apiFetch(`${api}/api/v1/meta`),
          fetch(`${api}/health/ready`),
          apiFetch(`${api}/api/v1/observability/metrics?format=json`),
          apiFetch(`${api}/api/v1/observability/metrics?format=prometheus`),
          apiFetch(`${api}/api/v1/pharmacies`),
        ]);
        if ([metaRes, jsonRes, promRes, phRes].some((r) => r.status === 401)) return onUnauthorized();
        if (metaRes.ok) setMeta(await metaRes.json());
        setDbReady(readyRes.ok);
        if (jsonRes.ok) setMetricsJson(await jsonRes.json());
        if (promRes.ok) setPrometheusText(await promRes.text());
        if (phRes.ok) setPharmacies(await phRes.json());
      } else if (activeSection === 'integrations') {
        const [connRes, dlqRes] = await Promise.all([
          apiFetch(`${api}/api/v1/integrations/connectors`),
          apiFetch(`${api}/api/v1/integrations/outbox/dead-letter?limit=100`),
        ]);
        if ([connRes, dlqRes].some((r) => r.status === 401)) return onUnauthorized();
        if (connRes.ok) setConnectors(await connRes.json());
        if (dlqRes.ok) setDeadLetters(await dlqRes.json());
      }
    } catch {
      onNotify('Unable to load platform administration telemetry');
    }
  }, [api, activeSection, onNotify, onUnauthorized]);

  useEffect(() => {
    loadSectionData();
  }, [loadSectionData, refreshKey]);

  const handleDispatchTick = async () => {
    setDispatchBusy(true);
    try {
      const res = await apiFetch(`${api}/api/v1/integrations/outbox/dispatch-tick`, { method: 'POST' });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Outbox tick failed');
      setDispatchStats(body as OutboxDispatchStats);
      onNotify(
        `Outbox tick complete: ${body.dispatched} dispatched, ${body.retrying} retrying, ${body.dead_letter} dead-letter`,
      );
      await loadSectionData();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Outbox dispatch failed');
    } finally {
      setDispatchBusy(false);
    }
  };

  const handleRetryDeadLetter = async (outboxId: number) => {
    setRetryingId(outboxId);
    try {
      const res = await apiFetch(`${api}/api/v1/integrations/outbox/${outboxId}/retry`, { method: 'POST' });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Retry failed');
      onNotify(`Outbox message #${outboxId} reset to PENDING for dispatch`);
      await loadSectionData();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Outbox retry error');
    } finally {
      setRetryingId(null);
    }
  };

  if (activeSection === 'identity') {
    return (
      <StaffAndFacilityAdminPanel
        api={api}
        isPlatformOperator={true}
        onNotify={onNotify}
        onUnauthorized={onUnauthorized}
      />
    );
  }

  if (activeSection === 'service-clients') {
    return (
      <ServiceClientsPanel
        api={api}
        onNotify={onNotify}
        onUnauthorized={onUnauthorized}
      />
    );
  }

  if (activeSection === 'quarantine') {
    return (
      <QuarantineCataloguePanel
        api={api}
        eyebrow="PLATFORM INTEROPERABILITY QUARANTINE & CATALOGUE"
        onNotify={onNotify}
      />
    );
  }

  if (activeSection === 'security-audit') {
    return (
      <div style={{ display: 'grid', gap: 18 }}>
        <div className="pageTitle">
          <div>
            <span className="eyebrow">PLATFORM SECURITY & TECHNICAL OPERATIONS</span>
            <h1>Authentication, Service-Client & Queue Monitoring</h1>
            <p>
              Technical security audit feed covering human authentication, session revocation, service-client activity,
              and offline sync queue health. Clinical patient prescriptions remain strictly inaccessible.
            </p>
          </div>
        </div>

        <AuditTrailPanel
          api={api}
          scopeMode="technical"
          eyebrow="TECHNICAL SECURITY AUDIT TRAIL"
          title="Authentication, Session & Service-Client Events"
        />

        <OfflineReconciliationPanel
          api={api}
          canReconcile={false}
          eyebrow="PLATFORM OFFLINE QUEUE TELEMETRY"
          title="Cross-Pharmacy Offline Sync Monitor (Read-Only)"
          onNotify={onNotify}
        />
      </div>
    );
  }

  if (activeSection === 'integrations') {
    return (
      <div style={{ display: 'grid', gap: 16 }}>
        <div className="pageTitle">
          <div>
            <span className="eyebrow">P1-05 & P3-01 INTEROPERABILITY OPERATIONS</span>
            <h1>EMR Connectors, Outbox Worker & Dead-Letter Recovery</h1>
            <p>
              Inspect registered modular EMR connectors (e-Buzima, OpenMRS), execute partner outbox dispatch batches,
              and retry failed RMS/EMR reconciliation messages.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              className="primary"
              onClick={handleDispatchTick}
              disabled={dispatchBusy}
              style={{ minHeight: 36, padding: '0 14px', display: 'inline-flex', alignItems: 'center', gap: 6 }}
            >
              <RefreshCw size={14} className={dispatchBusy ? 'spin' : ''} />
              {dispatchBusy ? 'Dispatching…' : 'Run Outbox Worker Tick'}
            </button>
            {isDev && (
              <button
                type="button"
                onClick={() => window.open(`${api}/docs`, '_blank')}
                style={{
                  minHeight: 36,
                  padding: '0 12px',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  border: '1px solid var(--line)',
                  borderRadius: 6,
                  background: '#fff',
                }}
              >
                OpenAPI Docs <ArrowRight size={14} />
              </button>
            )}
          </div>
        </div>

        {dispatchStats && (
          <div className="result successBox" style={{ marginTop: 0 }}>
            <CheckCircle2 size={16} />
            <div>
              <b>Outbox worker batch completed</b>
              <span>
                Processed: {dispatchStats.processed} · Dispatched: {dispatchStats.dispatched} · Retrying:{' '}
                {dispatchStats.retrying} · Dead-letter: {dispatchStats.dead_letter}
              </span>
            </div>
          </div>
        )}

        {/* Modular Registered Connectors */}
        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">P3-01 MODULAR CONNECTOR REGISTRY</span>
              <h2>Registered Hospital & National EMR Adapters ({connectors.length})</h2>
            </div>
            <Network size={17} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12, marginTop: 14 }}>
            {connectors.map((c) => (
              <div key={c.connector_code} className="kpiTile">
                <span className="eyebrow">{c.system_type}</span>
                <div style={{ fontWeight: 700, fontSize: 14, marginTop: 4 }}>{c.name}</div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  Code: <code>{c.connector_code}</code>
                </div>
                <div className="statusLine" style={{ marginTop: 10 }}>
                  <span className="live" /> CANONICAL ADAPTER REGISTERED
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Dead-Letter Outbox Queue with Retry Action */}
        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">OUTBOX DEAD-LETTER RECOVERY</span>
              <h2>Failed & Exhausted Partner Events ({deadLetters.length})</h2>
            </div>
            <ShieldAlert size={17} />
          </div>
          <div style={{ marginTop: 12 }}>
            {deadLetters.length ? (
              <table className="dataTable">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Destination</th>
                    <th>Event Type</th>
                    <th>Aggregate</th>
                    <th>Status / Retries</th>
                    <th>Error</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {deadLetters.map((item) => (
                    <tr key={item.id}>
                      <td>#{item.id}</td>
                      <td>
                        <strong>{item.destination_system}</strong>
                      </td>
                      <td>
                        <code>{item.event_type}</code>
                      </td>
                      <td>
                        {item.aggregate_type}:{item.aggregate_id}
                      </td>
                      <td>
                        <span className="statusPill dangerPill">
                          {item.status} ({item.retry_count})
                        </span>
                      </td>
                      <td style={{ maxWidth: 260 }}>{item.error_message || '—'}</td>
                      <td>
                        <button
                          type="button"
                          className="primary"
                          disabled={retryingId === item.id}
                          onClick={() => handleRetryDeadLetter(item.id)}
                          style={{ minHeight: 28, padding: '0 10px', display: 'inline-flex', alignItems: 'center', gap: 5 }}
                        >
                          <RotateCw size={12} className={retryingId === item.id ? 'spin' : ''} />
                          Retry
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="emptyState">
                <span>
                  <CheckCircle2 size={22} />
                </span>
                <strong>Zero dead-letter events</strong>
                <p>All RMS/eLMIS and e-Buzima partner outbox messages are healthy or awaiting next scheduled tick.</p>
              </div>
            )}
          </div>
        </section>

        <section className="panel">
          <span className="eyebrow">SERVICE-TO-SERVICE ENDPOINT CONTRACTS</span>
          <h2>Canonical Partner Ingestion & Callback Routes</h2>
          <p className="muted" style={{ marginTop: 6 }}>
            Server-to-server endpoints require provisioned per-partner service credentials (
            <code>x-amrguard-integration-key: &lt;prefix&gt;.&lt;secret&gt;</code>). Keys are never exposed in browser
            bundles.
          </p>
          <div className="endpointGrid" style={{ marginTop: 12 }}>
            <code>POST /api/v1/integrations/ebuzima/prescriptions</code>
            <code>POST /api/v1/integrations/ebuzima/fhir-bundle</code>
            <code>POST /api/v1/integrations/openmrs/medication-request</code>
            <code>POST /api/v1/integrations/rms/stock-events</code>
            <code>POST /api/v1/reminders/dispatch-tick</code>
            <code>POST /api/v1/integrations/sms/delivery-callback</code>
          </div>
        </section>
      </div>
    );
  }

  // Default section: 'health' (System Health, Prometheus Observability & Directory)
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="pageTitle">
        <div>
          <span className="eyebrow">PLATFORM ADMINISTRATION · P3-02 OBSERVABILITY</span>
          <h1>System Health, Runtime Posture & Prometheus Telemetry</h1>
          <p>
            Real-time operational telemetry, database readiness, authentication failure counters, and OpenMetrics
            scrape output for infrastructure monitoring.
          </p>
        </div>
        <span className="sourceBadge">
          <span className={dbReady ? 'live' : 'demoDot'} />
          {dbReady ? 'Database Ready' : 'Database Degraded'} · v{meta?.version || '0.7.0'}
        </span>
      </div>

      <div className="metricGrid">
        <div className="metric">
          <div className="metricIcon">
            <Server size={16} />
          </div>
          <span>Auth Mode</span>
          <strong style={{ fontSize: 15 }}>{meta?.auth_mode || '—'}</strong>
        </div>
        <div className="metric">
          <div className="metricIcon">
            <Activity size={16} />
          </div>
          <span>Total Orders / Dispenses</span>
          <strong>
            {metricsJson ? `${metricsJson.prescriptions_total} / ${metricsJson.dispenses_total}` : '—'}
          </strong>
        </div>
        <div className="metric">
          <div className="metricIcon">
            <Cpu size={16} />
          </div>
          <span>Outbox Pending</span>
          <strong>{metricsJson?.outbox_pending ?? 0}</strong>
        </div>
        <div className="metric">
          <div className="metricIcon">
            <ShieldAlert size={16} />
          </div>
          <span>Outbox Dead-Letter</span>
          <strong>{metricsJson?.outbox_dead_letter ?? 0}</strong>
        </div>
        <div className="metric">
          <div className="metricIcon">
            <ShieldCheck size={16} />
          </div>
          <span>Auth / Authz Failures</span>
          <strong>{metricsJson?.auth_failures_total ?? 0}</strong>
        </div>
        <div className="metric">
          <div className="metricIcon">
            <Network size={16} />
          </div>
          <span>Active Pharmacies</span>
          <strong>{metricsJson?.active_pharmacies ?? pharmacies.length}</strong>
        </div>
      </div>

      <div className="twoCol" style={{ margin: 0, maxWidth: 'none' }}>
        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">OPENMETRICS / PROMETHEUS EXPOSITION</span>
              <h2>Live Scrape Output (<code>/api/v1/observability/metrics</code>)</h2>
            </div>
            <Terminal size={17} />
          </div>
          <pre className="codeBlock" style={{ marginTop: 12, maxHeight: 320, overflow: 'auto' }}>
            {prometheusText || '# Loading Prometheus metrics…'}
          </pre>
        </section>

        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">PLATFORM POSTURE & DIRECTORY</span>
              <h2>Runtime Controls & Connected Pharmacies</h2>
            </div>
          </div>
          <div className="detailGrid" style={{ marginTop: 10 }}>
            <div className="detail">
              <span>Service Version</span>
              <b>
                {meta?.name || 'AMRGuard'} v{meta?.version || '0.7.0'} ({meta?.api_version || 'v1'})
              </b>
            </div>
            <div className="detail">
              <span>Cross-Facility Dispensing</span>
              <b>{meta?.cross_facility_dispensing_enabled ? 'Enabled (Network Policy)' : 'Disabled (Default)'}</b>
            </div>
            <div className="detail">
              <span>Integration Posture</span>
              <b>{meta?.integration_mode || 'adapter-ready'}</b>
            </div>
            <div className="detail">
              <span>Standards</span>
              <b>{meta?.standards || 'REST/OpenAPI · FHIR R4'}</b>
            </div>
          </div>

          <div style={{ marginTop: 14 }}>
            <span className="eyebrow">TECHNICAL PHARMACY DIRECTORY ({pharmacies.length})</span>
            <table className="dataTable" style={{ marginTop: 8 }}>
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Name</th>
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
                    <td>{p.name}</td>
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
          </div>
        </section>
      </div>
    </div>
  );
}
