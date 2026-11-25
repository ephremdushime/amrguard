import React, { useCallback, useEffect, useState } from 'react';
import {
  BellRing,
  BookOpen,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
  X,
  XCircle,
} from 'lucide-react';
import { apiFetch, type AuthUser } from '../authApi';
import { AIAssistPanel } from '../components/AIAssistPanel';
import { AuditTrailPanel } from '../components/AuditTrailPanel';
import { ConsentReminderModal } from '../components/ConsentReminderModal';
import { TraceabilityView } from '../components/TraceabilityView';
import type {
  ConsentRecordItem,
  GovernedMetricsResponse,
  OperationalBatch,
  OperationalRx,
  OperationalTransaction,
  StewardshipAlertItem,
  StewardshipReminderRow,
  StewardshipReviewRow,
  StewardshipRuleItem,
  WhoAwareCatalogItem,
} from '../types';

interface StewardshipWorkspaceProps {
  api: string;
  user: AuthUser;
  activeSection: string;
  refreshKey: number;
  onNotify: (message: string) => void;
  onUnauthorized: () => void;
}

export function StewardshipWorkspace({
  api,
  user,
  activeSection,
  refreshKey,
  onNotify,
  onUnauthorized,
}: StewardshipWorkspaceProps) {
  const facilityId = user.scopes.find((s) => s.facility_id != null)?.facility_id || 1;

  // Overview section
  const [metrics, setMetrics] = useState<GovernedMetricsResponse | null>(null);
  const [awareCatalog, setAwareCatalog] = useState<WhoAwareCatalogItem[]>([]);
  const [rules, setRules] = useState<StewardshipRuleItem[]>([]);
  const [catalogSearch, setCatalogSearch] = useState('');

  // Reviews & Alerts section
  const [alerts, setAlerts] = useState<StewardshipAlertItem[]>([]);
  const [alertFilter, setAlertFilter] = useState<'OPEN' | 'RESOLVED' | 'OVERRIDDEN' | 'ALL'>('OPEN');
  const [selectedAlert, setSelectedAlert] = useState<StewardshipAlertItem | null>(null);
  const [alertOutcome, setAlertOutcome] = useState<'ACCEPTED' | 'OVERRIDDEN_WITH_REASON' | 'FALSE_POSITIVE_FLAGGED'>('ACCEPTED');
  const [alertReason, setAlertReason] = useState('');
  const [alertBusy, setAlertBusy] = useState(false);

  const [reviews, setReviews] = useState<StewardshipReviewRow[]>([]);
  const [reviewOutcome, setReviewOutcome] = useState('CONTINUE');
  const [reviewReason, setReviewReason] = useState('');
  const [reviewerRef, setReviewerRef] = useState(user.display_name || user.username || '');
  const [reviewBusy, setReviewBusy] = useState(false);

  // Adherence & Consent section
  const [consents, setConsents] = useState<ConsentRecordItem[]>([]);
  const [reminders, setReminders] = useState<StewardshipReminderRow[]>([]);
  const [prescriptions, setPrescriptions] = useState<OperationalRx[]>([]);
  const [transactions, setTransactions] = useState<OperationalTransaction[]>([]);
  const [consentModalRx, setConsentModalRx] = useState<OperationalRx | null>(null);
  const [withdrawingId, setWithdrawingId] = useState<number | null>(null);

  // Traceability section
  const [batches, setBatches] = useState<OperationalBatch[]>([]);

  const loadSectionData = useCallback(async () => {
    try {
      if (activeSection === 'overview') {
        const [mRes, aRes, rRes] = await Promise.all([
          apiFetch(`${api}/api/v1/stewardship/metrics`),
          apiFetch(`${api}/api/v1/stewardship/aware-catalog`),
          apiFetch(`${api}/api/v1/stewardship/rules`),
        ]);
        if ([mRes, aRes, rRes].some((r) => r.status === 401)) return onUnauthorized();
        if (mRes.ok) setMetrics(await mRes.json());
        if (aRes.ok) setAwareCatalog(await aRes.json());
        if (rRes.ok) setRules(await rRes.json());
      } else if (activeSection === 'reviews') {
        const [alRes, revRes] = await Promise.all([
          apiFetch(`${api}/api/v1/stewardship/alerts?limit=100`),
          apiFetch(`${api}/api/v1/stewardship/reviews?limit=200`),
        ]);
        if ([alRes, revRes].some((r) => r.status === 401)) return onUnauthorized();
        if (alRes.ok) setAlerts(await alRes.json());
        if (revRes.ok) setReviews(await revRes.json());
      } else if (activeSection === 'adherence') {
        const [cRes, remRes, rxRes, txRes] = await Promise.all([
          apiFetch(`${api}/api/v1/consent`),
          apiFetch(`${api}/api/v1/stewardship/reminders?limit=200`),
          apiFetch(`${api}/api/v1/prescriptions?limit=200`),
          apiFetch(`${api}/api/v1/transactions?limit=200`),
        ]);
        if ([cRes, remRes, rxRes, txRes].some((r) => r.status === 401)) return onUnauthorized();
        if (cRes.ok) setConsents(await cRes.json());
        if (remRes.ok) setReminders(await remRes.json());
        if (rxRes.ok) setPrescriptions(await rxRes.json());
        if (txRes.ok) setTransactions(await txRes.json());
      } else if (activeSection === 'traceability') {
        const [bRes, txRes] = await Promise.all([
          apiFetch(`${api}/api/v1/stock/batches`),
          apiFetch(`${api}/api/v1/transactions?limit=200`),
        ]);
        if ([bRes, txRes].some((r) => r.status === 401)) return onUnauthorized();
        if (bRes.ok) setBatches(await bRes.json());
        if (txRes.ok) setTransactions(await txRes.json());
      }
    } catch {
      onNotify('Unable to load stewardship workspace data');
    }
  }, [api, activeSection, onNotify, onUnauthorized]);

  useEffect(() => {
    loadSectionData();
  }, [loadSectionData, refreshKey]);

  const handleAlertDisposition = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedAlert) return;
    setAlertBusy(true);
    try {
      const res = await apiFetch(`${api}/api/v1/stewardship/alerts/${selectedAlert.alert_id}/disposition`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outcome: alertOutcome, reason: alertReason.trim() }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to record disposition');
      onNotify(`Alert ${selectedAlert.alert_id} marked ${alertOutcome}`);
      setSelectedAlert(null);
      setAlertReason('');
      await loadSectionData();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Alert disposition error');
    } finally {
      setAlertBusy(false);
    }
  };

  const handleCompleteReview = async (e: React.FormEvent) => {
    e.preventDefault();
    const pending = reviews.find((r) => r.status === 'PENDING');
    if (!pending) return;
    setReviewBusy(true);
    try {
      const res = await apiFetch(`${api}/api/v1/stewardship/reviews/${pending.id}/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          outcome: reviewOutcome,
          reason: reviewReason.trim(),
          reviewer_reference: reviewerRef.trim() || undefined,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to complete review');
      setReviewReason('');
      onNotify(`Completed stewardship review for ${pending.prescription_code} (${reviewOutcome})`);
      await loadSectionData();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Review completion error');
    } finally {
      setReviewBusy(false);
    }
  };

  const handleWithdrawConsent = async (consentId: number) => {
    setWithdrawingId(consentId);
    try {
      const res = await apiFetch(`${api}/api/v1/consent/${consentId}/withdraw`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'PATIENT_REQUEST_CLINIC_WITHDRAWAL' }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to withdraw consent');
      onNotify(`Consent #${consentId} withdrawn; future reminder occurrences cancelled`);
      await loadSectionData();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Consent withdrawal error');
    } finally {
      setWithdrawingId(null);
    }
  };

  if (activeSection === 'traceability') {
    return (
      <div style={{ display: 'grid', gap: 18 }}>
        <TraceabilityView api={api} batches={batches} transactions={transactions} />
        <AuditTrailPanel
          api={api}
          scopeMode="facility"
          eyebrow="FACILITY STEWARDSHIP AUDIT"
          title="Facility Clinical & Stewardship Audit Log"
        />
      </div>
    );
  }

  if (activeSection === 'adherence') {
    const dispensedIds = new Set(transactions.map((t) => t.prescription_id));
    const eligibleRx = prescriptions.filter((rx) => rx.status !== 'BLOCKED' && dispensedIds.has(rx.id));

    return (
      <div style={{ display: 'grid', gap: 16 }}>
        <div className="pageTitle">
          <div>
            <span className="eyebrow">P1-06 & P1-07 PATIENT SUPPORT</span>
            <h1>Verified Consent & Dose-Level Reminder Register</h1>
            <p>
              Manage cryptographically hashed patient SMS consent records, withdraw consent with immediate reminder
              suppression, and enroll dispensed prescriptions into Africa/Kigali dose schedules.
            </p>
          </div>
          <span className="sourceBadge">
            <BellRing size={14} /> {consents.filter((c) => c.status === 'ACTIVE').length} active consents ·{' '}
            {reminders.length} reminders
          </span>
        </div>

        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">PATIENT CONSENT LEDGER</span>
              <h2>Informed SMS Consent Records ({consents.length})</h2>
            </div>
          </div>
          <div style={{ marginTop: 12 }}>
            {consents.length ? (
              <table className="dataTable">
                <thead>
                  <tr>
                    <th>Patient Ref</th>
                    <th>Masked Phone</th>
                    <th>Purpose / Lang</th>
                    <th>Status</th>
                    <th>Policy</th>
                    <th>Captured</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {consents.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <strong>{c.patient_reference}</strong>
                      </td>
                      <td>
                        <code>{c.recipient_phone_masked}</code>
                      </td>
                      <td>
                        {c.purpose} ({c.language.toUpperCase()})
                      </td>
                      <td>
                        <span className={`statusPill ${c.status === 'ACTIVE' ? 'success' : 'dangerPill'}`}>
                          {c.status}
                        </span>
                      </td>
                      <td>{c.policy_version}</td>
                      <td>{new Date(c.captured_at).toLocaleString()}</td>
                      <td>
                        {c.status === 'ACTIVE' ? (
                          <button
                            type="button"
                            disabled={withdrawingId === c.id}
                            onClick={() => handleWithdrawConsent(c.id)}
                            style={{
                              minHeight: 28,
                              padding: '0 9px',
                              border: '1px solid #ebc6bd',
                              borderRadius: 5,
                              background: '#fbefec',
                              color: '#a34d46',
                              fontSize: 10,
                            }}
                          >
                            <XCircle size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} />
                            Withdraw
                          </button>
                        ) : (
                          <span className="muted">Withdrawn</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="emptyState">
                <span>
                  <ShieldCheck size={22} />
                </span>
                <strong>No patient consents recorded yet</strong>
                <p>Capture explicit patient consent for a dispensed prescription below to enroll dose reminders.</p>
              </div>
            )}
          </div>
        </section>

        <div className="twoCol" style={{ margin: 0, maxWidth: 'none' }}>
          <section className="panel">
            <span className="eyebrow">ENROLL DISPENSED PRESCRIPTION</span>
            <h2>Eligible Courses ({eligibleRx.length})</h2>
            <div style={{ display: 'grid', gap: 8, marginTop: 12 }}>
              {eligibleRx.length ? (
                eligibleRx.map((rx) => (
                  <div
                    key={rx.id}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '10px 12px',
                      borderRadius: 6,
                      border: '1px solid var(--line)',
                      background: '#fbfdfb',
                    }}
                  >
                    <div>
                      <strong>{rx.code}</strong> · {rx.patient_reference}
                      <div style={{ fontSize: 10, color: 'var(--muted)' }}>
                        {rx.items[0]?.antibiotic} ({rx.items[0]?.authorized_quantity} units)
                      </div>
                    </div>
                    <button
                      type="button"
                      className="primary"
                      onClick={() => setConsentModalRx(rx)}
                      style={{ minHeight: 32, padding: '0 10px', display: 'inline-flex', alignItems: 'center', gap: 5 }}
                    >
                      <BellRing size={13} /> Enroll
                    </button>
                  </div>
                ))
              ) : (
                <p className="muted">Dispensed prescriptions eligible for adherence support appear here.</p>
              )}
            </div>
          </section>

          <section className="panel">
            <div className="panelHead">
              <div>
                <span className="eyebrow">SCHEDULED REMINDERS</span>
                <h2>Reminder Outbox ({reminders.length})</h2>
              </div>
              <Clock3 size={17} />
            </div>
            <div style={{ marginTop: 10, maxHeight: 320, overflowY: 'auto' }}>
              {reminders.length ? (
                reminders.map((rem) => (
                  <div className="reminderRow" key={rem.id}>
                    <span className="statusPill">{rem.status}</span>
                    <strong>{rem.prescription_code}</strong>
                    <small>{new Date(rem.scheduled_at).toLocaleString()}</small>
                    <span className="consentRecorded">
                      <CheckCircle2 size={13} /> Consent verified
                    </span>
                  </div>
                ))
              ) : (
                <p className="muted">No scheduled reminders queued yet.</p>
              )}
            </div>
          </section>
        </div>

        {consentModalRx && (
          <ConsentReminderModal
            api={api}
            prescriptionId={consentModalRx.id}
            prescriptionCode={consentModalRx.code}
            patientReference={consentModalRx.patient_reference}
            facilityId={consentModalRx.facility.id || facilityId}
            isOpen={Boolean(consentModalRx)}
            onClose={() => setConsentModalRx(null)}
            onSuccess={() => {
              setConsentModalRx(null);
              loadSectionData();
              onNotify('Patient SMS consent recorded and dose reminders scheduled');
            }}
          />
        )}
      </div>
    );
  }

  if (activeSection === 'reviews') {
    const openAlerts = alerts.filter((a) => a.status === 'OPEN');
    const filteredAlerts = alertFilter === 'ALL' ? alerts : alerts.filter((a) => a.status === alertFilter);
    const pendingReviews = reviews.filter((r) => r.status === 'PENDING');

    return (
      <div style={{ display: 'grid', gap: 16 }}>
        <div className="pageTitle">
          <div>
            <span className="eyebrow">STEWARDSHIP CLINICAL INTERVENTIONS</span>
            <h1>Rules-Engine Alerts & Day-3 Reassessment Queue</h1>
            <p>
              Disposition automated formulary & duration alerts, complete post-dispense clinical reviews, and consult
              bounded AI citations before intervention.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <span className="sourceBadge">
              <ShieldAlert size={14} /> {openAlerts.length} open alerts
            </span>
            <span className="sourceBadge">
              <ClipboardCheck size={14} /> {pendingReviews.length} pending reviews
            </span>
          </div>
        </div>

        {/* Alerts */}
        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">P2-02 STEWARDSHIP ALERTS</span>
              <h2>Active Clinical Rules Alerts</h2>
            </div>
            <div className="filterChips">
              {(['OPEN', 'RESOLVED', 'OVERRIDDEN', 'ALL'] as const).map((f) => (
                <button key={f} type="button" className={alertFilter === f ? 'primary' : ''} onClick={() => setAlertFilter(f)}>
                  {f}
                </button>
              ))}
            </div>
          </div>

          <div className="reviewGrid">
            <div className="reviewList" style={{ maxHeight: 380, overflowY: 'auto' }}>
              {filteredAlerts.length ? (
                filteredAlerts.map((a) => (
                  <div
                    key={a.alert_id}
                    className={`reviewItem ${a.status === 'OPEN' ? 'reviewPending' : ''}`}
                    style={{
                      cursor: 'pointer',
                      borderColor: selectedAlert?.alert_id === a.alert_id ? 'var(--green)' : undefined,
                    }}
                    onClick={() => setSelectedAlert(a)}
                  >
                    <span className="statusPill">{a.severity}</span>
                    <div>
                      <strong>
                        {a.rule_code} · Rx #{a.prescription_id}
                      </strong>
                      <small style={{ display: 'block', marginTop: 2 }}>{a.message}</small>
                      {a.disposition_outcome && (
                        <span className="reviewOutcome">
                          Disposition: <b>{a.disposition_outcome}</b> · {a.disposition_reason}
                        </span>
                      )}
                    </div>
                  </div>
                ))
              ) : (
                <div className="emptyState">
                  <span>
                    <CheckCircle2 size={22} />
                  </span>
                  <strong>No {alertFilter.toLowerCase()} alerts</strong>
                  <p>Evaluated facility prescriptions are aligned with active stewardship rules.</p>
                </div>
              )}
            </div>

            {selectedAlert && (
              <div style={{ display: 'grid', gap: 12 }}>
                {selectedAlert.status === 'OPEN' && (
                  <form className="reviewForm" onSubmit={handleAlertDisposition}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span className="eyebrow">DISPOSITION ALERT</span>
                      <button type="button" onClick={() => setSelectedAlert(null)} style={{ background: 'none', border: 0 }}>
                        <X size={15} />
                      </button>
                    </div>
                    <strong>
                      {selectedAlert.rule_code} (Rx #{selectedAlert.prescription_id})
                    </strong>
                    <label>
                      Disposition Action
                      <select
                        value={alertOutcome}
                        onChange={(e) =>
                          setAlertOutcome(
                            e.target.value as 'ACCEPTED' | 'OVERRIDDEN_WITH_REASON' | 'FALSE_POSITIVE_FLAGGED',
                          )
                        }
                      >
                        <option value="ACCEPTED">Accept Guideline Recommendation</option>
                        <option value="OVERRIDDEN_WITH_REASON">Override with Clinical Rationale</option>
                        <option value="FALSE_POSITIVE_FLAGGED">Flag False Positive</option>
                      </select>
                    </label>
                    <label>
                      Clinical Rationale
                      <textarea
                        required
                        minLength={3}
                        maxLength={500}
                        rows={3}
                        value={alertReason}
                        onChange={(e) => setAlertReason(e.target.value)}
                      />
                    </label>
                    <button className="primary full" type="submit" disabled={alertBusy}>
                      <ClipboardCheck size={15} />
                      {alertBusy ? 'Saving…' : 'Record Disposition'}
                    </button>
                  </form>
                )}

                <AIAssistPanel
                  api={api}
                  scenario="STEWARDSHIP_ALERT_EXPLAIN"
                  alertId={selectedAlert.alert_id}
                  title={`AI Rationale: ${selectedAlert.rule_code}`}
                  buttonLabel="Explain Alert with Citations"
                />
              </div>
            )}
          </div>
        </section>

        {/* Post-dispense reviews */}
        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">POST-DISPENSE REASSESSMENT</span>
              <h2>Day-3 Stewardship Review Queue</h2>
            </div>
            <span className="statusPill">
              {reviews.filter((r) => r.status === 'COMPLETED').length} completed · {pendingReviews.length} pending
            </span>
          </div>

          <div className="reviewGrid">
            <div className="reviewList" style={{ maxHeight: 360, overflowY: 'auto' }}>
              {reviews.length ? (
                reviews.map((r) => (
                  <div key={r.id} className={`reviewItem ${r.status === 'PENDING' ? 'reviewPending' : ''}`}>
                    <span className="statusPill">{r.status}</span>
                    <div>
                      <strong>
                        {r.prescription_code} · {r.patient_reference}
                      </strong>
                      <small style={{ display: 'block' }}>Due {new Date(r.due_at).toLocaleString()}</small>
                      {r.outcome && (
                        <span className="reviewOutcome">
                          Outcome: <b>{r.outcome}</b> · {r.reason}
                        </span>
                      )}
                    </div>
                  </div>
                ))
              ) : (
                <div className="emptyState">
                  <span>
                    <ClipboardCheck size={22} />
                  </span>
                  <strong>No post-dispense reviews queued</strong>
                  <p>Reviews are generated automatically when pharmacy dispensing transactions commit.</p>
                </div>
              )}
            </div>

            {pendingReviews.length > 0 && (
              <form className="reviewForm" onSubmit={handleCompleteReview}>
                <span className="eyebrow">COMPLETE NEXT PENDING REVIEW</span>
                <strong>{pendingReviews[0].prescription_code}</strong>
                <label>
                  Outcome
                  <select value={reviewOutcome} onChange={(e) => setReviewOutcome(e.target.value)}>
                    <option value="CONTINUE">Continue as prescribed</option>
                    <option value="CHANGE">Change / de-escalate therapy</option>
                    <option value="STOP">Stop antibiotic therapy</option>
                    <option value="REFER">Refer to infectious disease specialist</option>
                  </select>
                </label>
                <label>
                  Clinical Rationale
                  <textarea
                    required
                    minLength={3}
                    maxLength={500}
                    rows={3}
                    value={reviewReason}
                    onChange={(e) => setReviewReason(e.target.value)}
                    placeholder="Record clinical reassessment and microbiology notes…"
                  />
                </label>
                <label>
                  Reviewer Reference
                  <input
                    required
                    minLength={2}
                    maxLength={150}
                    value={reviewerRef}
                    onChange={(e) => setReviewerRef(e.target.value)}
                  />
                </label>
                <button className="primary full" type="submit" disabled={reviewBusy}>
                  <ClipboardCheck size={15} />
                  {reviewBusy ? 'Saving review…' : 'Complete Review'}
                </button>
              </form>
            )}
          </div>
        </section>
      </div>
    );
  }

  // Default section: 'overview' (WHO AWaRe, Governed Metrics, Active Rules, AI Brief)
  const filteredCatalog = awareCatalog.filter(
    (c) =>
      !catalogSearch.trim() ||
      c.generic_name.toLowerCase().includes(catalogSearch.toLowerCase()) ||
      c.antibiotic_code.toLowerCase().includes(catalogSearch.toLowerCase()) ||
      c.category.toLowerCase().includes(catalogSearch.toLowerCase()),
  );

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="pageTitle">
        <div>
          <span className="eyebrow">ANTIMICROBIAL STEWARDSHIP WORKSPACE</span>
          <h1>WHO AWaRe Utilization & Clinical Governance</h1>
          <p>
            Facility-scoped stewardship KPIs, WHO 60% Access target tracking, active governed clinical rules, and
            bounded AI trend analysis.
          </p>
        </div>
        {metrics?.aware_breakdown && (
          <span className={`statusPill ${metrics.aware_breakdown.meets_who_access_target ? 'success' : ''}`}>
            {metrics.aware_breakdown.meets_who_access_target
              ? 'WHO Target Met (≥60% Access)'
              : 'Below 60% WHO Access Target'}
          </span>
        )}
      </div>

      {/* AWaRe bar + 5 KPIs */}
      {metrics && (
        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">P2-01 GOVERNED METRICS DICTIONARY</span>
              <h2>WHO AWaRe Proportion & Facility KPIs</h2>
            </div>
            <small className="muted">Evaluated {new Date(metrics.evaluated_at).toLocaleString()}</small>
          </div>

          <div className="awareBar" style={{ marginTop: 14 }}>
            <div style={{ width: `${metrics.aware_breakdown.access_percentage}%`, background: '#16a34a' }}>
              {metrics.aware_breakdown.access_percentage > 8 ? `Access ${metrics.aware_breakdown.access_percentage}%` : ''}
            </div>
            <div style={{ width: `${metrics.aware_breakdown.watch_percentage}%`, background: '#f59e0b' }}>
              {metrics.aware_breakdown.watch_percentage > 8 ? `Watch ${metrics.aware_breakdown.watch_percentage}%` : ''}
            </div>
            <div style={{ width: `${metrics.aware_breakdown.reserve_percentage}%`, background: '#dc2626' }}>
              {metrics.aware_breakdown.reserve_percentage > 5 ? `Reserve ${metrics.aware_breakdown.reserve_percentage}%` : ''}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10, marginTop: 14 }}>
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

          {metrics.data_quality_caveats.length > 0 && (
            <div className="notice" style={{ marginTop: 12 }}>
              <TriangleAlert size={15} />
              <span>{metrics.data_quality_caveats.join(' · ')}</span>
            </div>
          )}
        </section>
      )}

      {/* Bounded AI Trend Summary */}
      <AIAssistPanel
        api={api}
        scenario="AGGREGATE_TREND_SUMMARY"
        facilityId={facilityId}
        title="Facility Stewardship Trend Brief (Bounded AI)"
        buttonLabel="Summarize Facility Stewardship Trends"
      />

      {/* Active Rules + WHO AWaRe Formulary */}
      <div className="twoCol" style={{ margin: 0, maxWidth: 'none' }}>
        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">ACTIVE CLINICAL GOVERNANCE</span>
              <h2>Governed Stewardship Rules ({rules.length})</h2>
            </div>
            <ShieldCheck size={17} />
          </div>
          <div style={{ marginTop: 12, display: 'grid', gap: 8 }}>
            {rules.map((r) => (
              <div key={r.id} className="reviewItem" style={{ gridTemplateColumns: '1fr', gap: 4 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <strong>
                    {r.rule_code} · {r.title}
                  </strong>
                  <span className="statusPill">{r.severity}</span>
                </div>
                <small>{r.description}</small>
                <small style={{ color: '#396b59' }}>Rationale: {r.clinical_rationale}</small>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">WHO AWARE 2023 REFERENCE</span>
              <h2>Antibiotic Classifications ({filteredCatalog.length})</h2>
            </div>
            <BookOpen size={17} />
          </div>
          <input
            type="text"
            placeholder="Filter generic name, code, or Access/Watch/Reserve…"
            value={catalogSearch}
            onChange={(e) => setCatalogSearch(e.target.value)}
            style={{ width: '100%', padding: '7px 10px', border: '1px solid var(--line)', borderRadius: 6, marginTop: 10 }}
          />
          <div style={{ marginTop: 10, maxHeight: 320, overflowY: 'auto' }}>
            <table className="dataTable">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Generic Name</th>
                  <th>Category</th>
                  <th>ATC</th>
                </tr>
              </thead>
              <tbody>
                {filteredCatalog.map((item) => (
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
