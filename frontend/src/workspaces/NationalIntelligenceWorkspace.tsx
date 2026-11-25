import React, { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  BookOpen,
  Download,
  Globe2,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react';
import { apiFetch, type AuthUser } from '../authApi';
import { AIAssistPanel } from '../components/AIAssistPanel';
import type {
  FacilityMeasure,
  GovernedMetricsResponse,
  NationalSurveillanceExport,
  ObservabilityMetrics,
  OperationsSummary,
  WhoAwareCatalogItem,
} from '../types';

interface NationalIntelligenceWorkspaceProps {
  api: string;
  user: AuthUser;
  activeSection: string;
  refreshKey: number;
  onNotify: (message: string) => void;
  onUnauthorized: () => void;
}

export function NationalIntelligenceWorkspace({
  api,
  activeSection,
  refreshKey,
  onNotify,
  onUnauthorized,
}: NationalIntelligenceWorkspaceProps) {
  // Surveillance export section
  const [districtFilter, setDistrictFilter] = useState('');
  const [periodStart, setPeriodStart] = useState('');
  const [periodEnd, setPeriodEnd] = useState('');
  const [surveillance, setSurveillance] = useState<NationalSurveillanceExport | null>(null);
  const [survLoading, setSurvLoading] = useState(false);

  // Facility comparisons section
  const [summary, setSummary] = useState<OperationsSummary | null>(null);
  const [facilities, setFacilities] = useState<FacilityMeasure[]>([]);
  const [metrics, setMetrics] = useState<GovernedMetricsResponse | null>(null);

  // AI & AWaRe Reference section
  const [awareCatalog, setAwareCatalog] = useState<WhoAwareCatalogItem[]>([]);
  const [telemetry, setTelemetry] = useState<ObservabilityMetrics | null>(null);

  const loadSurveillance = useCallback(async () => {
    setSurvLoading(true);
    try {
      const params = new URLSearchParams();
      if (districtFilter.trim()) params.set('district', districtFilter.trim());
      if (periodStart) params.set('period_start', periodStart);
      if (periodEnd) params.set('period_end', periodEnd);
      const query = params.toString() ? `?${params.toString()}` : '';
      const res = await apiFetch(`${api}/api/v1/national/surveillance/export${query}`);
      if (res.status === 401) return onUnauthorized();
      if (res.ok) {
        setSurveillance(await res.json());
      } else {
        const body = await res.json().catch(() => ({}));
        onNotify(body.detail || 'Unable to load national surveillance export');
      }
    } finally {
      setSurvLoading(false);
    }
  }, [api, districtFilter, periodStart, periodEnd, onNotify, onUnauthorized]);

  const loadSectionData = useCallback(async () => {
    try {
      if (activeSection === 'surveillance') {
        await loadSurveillance();
      } else if (activeSection === 'facilities') {
        const [sumRes, facRes, metRes] = await Promise.all([
          apiFetch(`${api}/api/v1/analytics/summary`),
          apiFetch(`${api}/api/v1/analytics/facilities`),
          apiFetch(`${api}/api/v1/stewardship/metrics`),
        ]);
        if ([sumRes, facRes, metRes].some((r) => r.status === 401)) return onUnauthorized();
        if (sumRes.ok) setSummary(await sumRes.json());
        if (facRes.ok) {
          const data = await facRes.json();
          setFacilities(data.facilities || []);
        }
        if (metRes.ok) setMetrics(await metRes.json());
      } else if (activeSection === 'ai-insights') {
        const [catRes, obsRes] = await Promise.all([
          apiFetch(`${api}/api/v1/stewardship/aware-catalog`),
          apiFetch(`${api}/api/v1/observability/metrics?format=json`),
        ]);
        if ([catRes, obsRes].some((r) => r.status === 401)) return onUnauthorized();
        if (catRes.ok) setAwareCatalog(await catRes.json());
        if (obsRes.ok) setTelemetry(await obsRes.json());
      }
    } catch {
      onNotify('Unable to load national intelligence data');
    }
  }, [api, activeSection, loadSurveillance, onNotify, onUnauthorized]);

  useEffect(() => {
    loadSectionData();
  }, [loadSectionData, refreshKey]);

  const downloadJsonExport = () => {
    if (!surveillance) return;
    const blob = new Blob([JSON.stringify(surveillance, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `amrguard-national-surveillance-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    onNotify('Downloaded privacy-preserved WHO GLASS surveillance feed (JSON)');
  };

  if (activeSection === 'facilities') {
    return (
      <div style={{ display: 'grid', gap: 16 }}>
        <div className="pageTitle">
          <div>
            <span className="eyebrow">NATIONAL PROGRAMME PERFORMANCE</span>
            <h1>Multi-Facility Reconciliation & Governed KPIs</h1>
            <p>
              Aggregate cross-facility indicators with strict privacy boundaries. Individual patient prescriptions,
              dispensing records, and clinical audit logs are never exposed to national analyst scopes.
            </p>
          </div>
          <span className="sourceBadge">
            <Globe2 size={14} /> {facilities.length} reporting facilities
          </span>
        </div>

        <div className="metricGrid four">
          <div className="metric">
            <div className="metricIcon">
              <ShieldCheck size={16} />
            </div>
            <span>Aggregate Orders</span>
            <strong>{summary?.prescriptions ?? 0}</strong>
          </div>
          <div className="metric">
            <div className="metricIcon">
              <Activity size={16} />
            </div>
            <span>Dispense Reconciliation</span>
            <strong>{summary?.prescription_dispense_reconciliation_rate ?? 0}%</strong>
          </div>
          <div className="metric">
            <div className="metricIcon">
              <TriangleAlert size={16} />
            </div>
            <span>Quantity Discrepancies</span>
            <strong>{summary?.blocked ?? 0}</strong>
          </div>
          <div className="metric">
            <div className="metricIcon">
              <Globe2 size={16} />
            </div>
            <span>Review Completion</span>
            <strong>{summary?.stewardship_review_completion_rate ?? 0}%</strong>
          </div>
        </div>

        {metrics && (
          <section className="panel">
            <div className="panelHead">
              <div>
                <span className="eyebrow">GOVERNED METRICS DICTIONARY</span>
                <h2>National KPI Benchmarks</h2>
              </div>
              <small className="muted">Minimum cell suppression threshold: &lt;5 counts</small>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(185px, 1fr))', gap: 10, marginTop: 14 }}>
              {metrics.metrics.map((m) => (
                <div key={m.metric_code} className="kpiTile">
                  <span className="eyebrow">{m.category}</span>
                  <div style={{ fontWeight: 700, fontSize: 12, marginTop: 3 }}>{m.name}</div>
                  <strong style={{ display: 'block', fontSize: 22, margin: '6px 0 4px' }}>
                    {m.value ?? '—'} {m.unit}
                  </strong>
                  <div style={{ fontSize: 10, color: 'var(--muted)', display: 'flex', justifyContent: 'space-between' }}>
                    <span>Target: {m.target_benchmark || 'N/A'}</span>
                    <b style={{ color: m.benchmark_met ? '#16a34a' : '#d97706' }}>
                      {m.benchmark_met ? 'Met' : 'Watch'}
                    </b>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">FACILITY COMPARISON TABLE</span>
              <h2>Participating Pilot & Programme Sites ({facilities.length})</h2>
            </div>
          </div>
          <div style={{ marginTop: 12 }}>
            {facilities.length ? (
              <table className="dataTable">
                <thead>
                  <tr>
                    <th>Facility</th>
                    <th>District</th>
                    <th>Orders</th>
                    <th>Reconciliation Rate</th>
                    <th>Stewardship Reviews Completed</th>
                  </tr>
                </thead>
                <tbody>
                  {facilities.map((f) => (
                    <tr key={f.facility_code}>
                      <td>
                        <strong>{f.facility_name}</strong>
                        <div style={{ fontSize: 10, color: 'var(--muted)' }}>{f.facility_code}</div>
                      </td>
                      <td>{f.district}</td>
                      <td>{f.prescriptions}</td>
                      <td>
                        <span className="statusPill">{f.reconciliation_rate}%</span>
                      </td>
                      <td>
                        <span className="statusPill">{f.review_completion_rate}%</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">No active reporting facilities found.</p>
            )}
          </div>
        </section>
      </div>
    );
  }

  if (activeSection === 'ai-insights') {
    return (
      <div style={{ display: 'grid', gap: 16 }}>
        <div className="pageTitle">
          <div>
            <span className="eyebrow">NATIONAL SURVEILLANCE BRIEFING</span>
            <h1>Bounded AI Trend Analysis & WHO AWaRe Reference</h1>
            <p>
              Generate cited national stewardship summaries grounded in WHO AWaRe 2023 benchmarks and inspect aggregate
              platform utilization telemetry.
            </p>
          </div>
        </div>

        <AIAssistPanel
          api={api}
          scenario="AGGREGATE_TREND_SUMMARY"
          title="National Antibiotic Stewardship Trend Brief"
          buttonLabel="Generate National Trend Summary"
        />

        {telemetry && (
          <section className="panel">
            <span className="eyebrow">AGGREGATE PLATFORM TELEMETRY</span>
            <h2>National Network Throughput</h2>
            <div className="metricGrid four" style={{ marginTop: 12, marginBottom: 0 }}>
              <div className="metric">
                <span>Total Prescriptions</span>
                <strong>{telemetry.prescriptions_total}</strong>
              </div>
              <div className="metric">
                <span>Dispensing Events</span>
                <strong>{telemetry.dispenses_total}</strong>
              </div>
              <div className="metric">
                <span>Active Pharmacies</span>
                <strong>{telemetry.active_pharmacies}</strong>
              </div>
              <div className="metric">
                <span>Active Stock Batches</span>
                <strong>{telemetry.active_batches}</strong>
              </div>
            </div>
          </section>
        )}

        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">WHO AWARE 2023 CATALOGUE</span>
              <h2>National Classification Reference ({awareCatalog.length})</h2>
            </div>
            <BookOpen size={17} />
          </div>
          <div style={{ marginTop: 12, maxHeight: 340, overflowY: 'auto' }}>
            <table className="dataTable">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Generic Name</th>
                  <th>WHO AWaRe Group</th>
                  <th>ATC</th>
                  <th>Version</th>
                </tr>
              </thead>
              <tbody>
                {awareCatalog.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <code>{item.antibiotic_code}</code>
                    </td>
                    <td>{item.generic_name}</td>
                    <td>
                      <span className={`statusPill aware-${item.category.toLowerCase()}`}>{item.category}</span>
                    </td>
                    <td>
                      <code>{item.atc_code || '—'}</code>
                    </td>
                    <td>{item.version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    );
  }

  // Default section: 'surveillance' (WHO GLASS / RBC National Export)
  const renderSuppressedCell = (val: number | null) =>
    val === null ? (
      <span className="statusPill" title="Suppressed because count is between 1 and 4 (<5 minimum cell threshold)">
        &lt;5 (Masked)
      </span>
    ) : (
      <strong>{val}</strong>
    );

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="pageTitle">
        <div>
          <span className="eyebrow">P3-01 NATIONAL ANTIMICROBIAL SURVEILLANCE</span>
          <h1>WHO GLASS & RBC District Surveillance Feed</h1>
          <p>
            Multi-district antibiotic consumption and Days of Therapy (DOT) aggregation with mandatory minimum-cell
            suppression (&lt;5 counts masked) to prevent patient re-identification in small health-center cohorts.
          </p>
        </div>
        <button
          type="button"
          className="primary"
          onClick={downloadJsonExport}
          disabled={!surveillance}
          style={{ minHeight: 36, padding: '0 14px', display: 'inline-flex', alignItems: 'center', gap: 7 }}
        >
          <Download size={14} /> Export GLASS Feed (JSON)
        </button>
      </div>

      {/* Filters */}
      <section className="panel">
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <label style={{ display: 'grid', gap: 5, flex: '1 1 180px' }}>
            District Filter (Optional)
            <input
              type="text"
              placeholder="e.g. Gasabo"
              value={districtFilter}
              onChange={(e) => setDistrictFilter(e.target.value)}
              style={{ height: 36, padding: '0 10px', border: '1px solid var(--line)', borderRadius: 6 }}
            />
          </label>
          <label style={{ display: 'grid', gap: 5 }}>
            Period Start
            <input
              type="date"
              value={periodStart}
              onChange={(e) => setPeriodStart(e.target.value)}
              style={{ height: 36, padding: '0 10px', border: '1px solid var(--line)', borderRadius: 6 }}
            />
          </label>
          <label style={{ display: 'grid', gap: 5 }}>
            Period End
            <input
              type="date"
              value={periodEnd}
              onChange={(e) => setPeriodEnd(e.target.value)}
              style={{ height: 36, padding: '0 10px', border: '1px solid var(--line)', borderRadius: 6 }}
            />
          </label>
          <button
            type="button"
            className="primary"
            onClick={loadSurveillance}
            disabled={survLoading}
            style={{ height: 36, padding: '0 14px', display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <RefreshCw size={13} className={survLoading ? 'spin' : ''} />
            {survLoading ? 'Querying…' : 'Apply Filters'}
          </button>
        </div>
      </section>

      {surveillance && (
        <>
          <div className="metricGrid four">
            <div className="metric">
              <span>Evaluated Orders</span>
              <strong>{surveillance.national_summary.total_evaluated_orders}</strong>
            </div>
            <div className="metric">
              <span>Total Units Consumed</span>
              <strong>{surveillance.national_summary.total_units_consumed}</strong>
            </div>
            <div className="metric">
              <span>Estimated Days of Therapy (DOT)</span>
              <strong>{surveillance.national_summary.total_estimated_dot}</strong>
            </div>
            <div className="metric">
              <span>WHO Access Share (Target ≥60%)</span>
              <strong
                style={{
                  color: surveillance.national_summary.meets_who_access_benchmark ? '#16a34a' : '#d97706',
                }}
              >
                {surveillance.national_summary.access_percentage}%
              </strong>
            </div>
          </div>

          <section className="panel">
            <div className="panelHead">
              <div>
                <span className="eyebrow">WHO AWARE NATIONAL PROPORTION</span>
                <h2>Access / Watch / Reserve Distribution</h2>
              </div>
              <span className="statusPill">
                <LockKeyhole size={11} style={{ marginRight: 4 }} />
                {surveillance.cell_suppression_applied
                  ? `Suppression Applied (<${surveillance.methodology.minimum_cell_suppression_threshold})`
                  : `Threshold <${surveillance.methodology.minimum_cell_suppression_threshold} Active`}
              </span>
            </div>

            <div className="awareBar" style={{ marginTop: 14 }}>
              <div style={{ width: `${surveillance.national_summary.access_percentage}%`, background: '#16a34a' }}>
                {surveillance.national_summary.access_percentage > 8
                  ? `Access ${surveillance.national_summary.access_percentage}%`
                  : ''}
              </div>
              <div style={{ width: `${surveillance.national_summary.watch_percentage}%`, background: '#f59e0b' }}>
                {surveillance.national_summary.watch_percentage > 8
                  ? `Watch ${surveillance.national_summary.watch_percentage}%`
                  : ''}
              </div>
              <div style={{ width: `${surveillance.national_summary.reserve_percentage}%`, background: '#dc2626' }}>
                {surveillance.national_summary.reserve_percentage > 5
                  ? `Reserve ${surveillance.national_summary.reserve_percentage}%`
                  : ''}
              </div>
            </div>

            <div style={{ marginTop: 16 }}>
              {surveillance.district_breakdowns.length ? (
                <table className="dataTable">
                  <thead>
                    <tr>
                      <th>District</th>
                      <th>Orders</th>
                      <th>Units</th>
                      <th>Est. DOT</th>
                      <th>Access</th>
                      <th>Watch</th>
                      <th>Reserve</th>
                      <th>Privacy Guard</th>
                    </tr>
                  </thead>
                  <tbody>
                    {surveillance.district_breakdowns.map((row) => (
                      <tr key={row.district}>
                        <td>
                          <strong>{row.district}</strong>
                        </td>
                        <td>{row.total_orders}</td>
                        <td>{row.total_units}</td>
                        <td>{row.total_dot}</td>
                        <td>{renderSuppressedCell(row.aware_counts.ACCESS)}</td>
                        <td>{renderSuppressedCell(row.aware_counts.WATCH)}</td>
                        <td>{renderSuppressedCell(row.aware_counts.RESERVE)}</td>
                        <td>
                          <span className="statusPill">
                            {row.cell_suppression_applied ? 'Small-cell masked' : 'Unmasked'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="emptyState">
                  <span>
                    <Globe2 size={22} />
                  </span>
                  <strong>No district surveillance orders in selected period</strong>
                  <p>
                    Orders recorded across connected facilities aggregate here automatically with small-cell privacy
                    suppression.
                  </p>
                </div>
              )}
            </div>

            <div className="notice" style={{ marginTop: 14 }}>
              <LockKeyhole size={15} />
              <span>
                <strong>Methodology:</strong> {surveillance.methodology.standard}. National Analyst scope enforces
                aggregate-only surveillance access; patient-identifiable dispensing and clinical logs are inaccessible
                at the API boundary.
              </span>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
