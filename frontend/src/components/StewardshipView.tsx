import React, { useEffect, useState } from 'react';
import {
  Activity,
  AlertCircle,
  BellRing,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Clock3,
  FileText,
  Info,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
  X,
} from 'lucide-react';
import { apiFetch } from '../authApi';
import type {
  GovernedMetricsResponse,
  OperationalRx,
  OperationalTransaction,
  StewardshipAlertItem,
  StewardshipReminderRow,
  StewardshipReviewRow,
} from '../types';

interface StewardshipViewProps {
  api: string;
  prescriptions: OperationalRx[];
  transactions: OperationalTransaction[];
  reminders: StewardshipReminderRow[];
  onReload: () => void;
  onOpenConsentModal: (rx: OperationalRx) => void;
}

export function StewardshipView({
  api,
  prescriptions,
  transactions,
  reminders,
  onReload,
  onOpenConsentModal,
}: StewardshipViewProps) {
  // Existing review state
  const [reviews, setReviews] = useState<StewardshipReviewRow[]>([]);
  const [reviewOutcome, setReviewOutcome] = useState('CONTINUE');
  const [reviewReason, setReviewReason] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [reviewBusy, setReviewBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');

  // P2 Governed Metrics and AWaRe state
  const [metrics, setMetrics] = useState<GovernedMetricsResponse | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [showCaveats, setShowCaveats] = useState(false);

  // P2 Governed Alerts state
  const [alerts, setAlerts] = useState<StewardshipAlertItem[]>([]);
  const [alertFilter, setAlertFilter] = useState<'ALL' | 'OPEN' | 'RESOLVED' | 'OVERRIDDEN'>('OPEN');
  const [selectedAlert, setSelectedAlert] = useState<StewardshipAlertItem | null>(null);
  const [alertOutcome, setAlertOutcome] = useState<'ACCEPTED' | 'OVERRIDDEN_WITH_REASON' | 'FALSE_POSITIVE_FLAGGED'>('ACCEPTED');
  const [alertReason, setAlertReason] = useState('');
  const [alertBusy, setAlertBusy] = useState(false);
  const [alertMessage, setAlertMessage] = useState('');

  const loadReviews = () =>
    apiFetch(`${api}/api/v1/stewardship/reviews?limit=200`)
      .then((res) => (res.ok ? res.json() : []))
      .then(setReviews)
      .catch(() => setReviews([]));

  const loadMetrics = () => {
    setMetricsLoading(true);
    return apiFetch(`${api}/api/v1/stewardship/metrics`)
      .then((res) => (res.ok ? res.json() : null))
      .then(setMetrics)
      .catch(() => setMetrics(null))
      .finally(() => setMetricsLoading(false));
  };

  const loadAlerts = () =>
    apiFetch(`${api}/api/v1/stewardship/alerts?limit=100`)
      .then((res) => (res.ok ? res.json() : []))
      .then(setAlerts)
      .catch(() => setAlerts([]));

  useEffect(() => {
    loadReviews();
    loadMetrics();
    loadAlerts();
  }, [api]);

  const completeReview = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const pending = reviews.find((r) => r.status === 'PENDING');
    if (!pending) return;

    setReviewBusy(true);
    setStatusMessage('');
    try {
      const res = await apiFetch(`${api}/api/v1/stewardship/reviews/${pending.id}/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          outcome: reviewOutcome,
          reason: reviewReason.trim(),
          reviewer_reference: reviewer.trim() || undefined,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to complete review');

      setReviewReason('');
      setReviewOutcome('CONTINUE');
      setStatusMessage(`Review for prescription ${pending.prescription_code} completed (${reviewOutcome}).`);
      await loadReviews();
      await loadMetrics();
      onReload();
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : 'Unable to complete review');
    } finally {
      setReviewBusy(false);
    }
  };

  const handleAlertDisposition = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!selectedAlert) return;

    setAlertBusy(true);
    setAlertMessage('');
    try {
      const res = await apiFetch(`${api}/api/v1/stewardship/alerts/${selectedAlert.alert_id}/disposition`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          outcome: alertOutcome,
          reason: alertReason.trim(),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Unable to record alert disposition');

      setAlertMessage(`Alert ${selectedAlert.alert_id} recorded as ${alertOutcome}.`);
      setSelectedAlert(null);
      setAlertReason('');
      setAlertOutcome('ACCEPTED');
      await loadAlerts();
      await loadMetrics();
      onReload();
    } catch (err) {
      setAlertMessage(err instanceof Error ? err.message : 'Error recording disposition');
    } finally {
      setAlertBusy(false);
    }
  };

  const pendingReviews = reviews.filter((r) => r.status === 'PENDING');
  const openAlerts = alerts.filter((a) => a.status === 'OPEN');
  const filteredAlerts = alerts.filter((a) => {
    if (alertFilter === 'ALL') return true;
    return a.status === alertFilter;
  });

  const dispensedRxIds = new Set(transactions.map((t) => t.prescription_id));
  const dispensedCandidates = prescriptions.filter(
    (rx) => rx.status !== 'BLOCKED' && rx.items.length && dispensedRxIds.has(rx.id),
  );

  const formatDate = (val?: string | null) => (val ? new Date(val).toLocaleString() : 'Not set');

  const getSeverityBadgeClass = (sev: string) => {
    switch (sev) {
      case 'BLOCK':
        return 'status-blocked';
      case 'REVIEW_REQUIRED':
        return 'status-warning';
      default:
        return 'status-active';
    }
  };

  return (
    <>
      <div className="pageTitle">
        <div>
          <span className="eyebrow">ANTIMICROBIAL STEWARDSHIP & WHO AWARE INTELLIGENCE</span>
          <h1>Clinical Stewardship & Surveillance</h1>
          <p>
            Governed antimicrobial stewardship indicators, WHO AWaRe classification intelligence, rules-engine alerts,
            and verified patient course adherence.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <span className="sourceBadge">
            <ShieldAlert size={15} /> {openAlerts.length} rules alerts open
          </span>
          <span className="sourceBadge">
            <ClipboardCheck size={15} /> {pendingReviews.length} reviews pending
          </span>
        </div>
      </div>

      {/* =========================================================================
          P2-01: GOVERNED METRICS & WHO AWARE INTELLIGENCE PANEL
         ========================================================================= */}
      <section className="panel" style={{ marginBottom: 20 }}>
        <div className="panelHead">
          <div>
            <span className="eyebrow">P2-01 GOVERNED METRICS DICTIONARY</span>
            <h2>WHO AWaRe Utilization & Stewardship Surveillance</h2>
          </div>
          {metrics?.aware_breakdown && (
            <span
              className={`statusPill ${
                metrics.aware_breakdown.meets_who_access_target ? 'status-validated' : 'status-warning'
              }`}
            >
              {metrics.aware_breakdown.meets_who_access_target ? (
                <>
                  <CheckCircle2 size={13} style={{ marginRight: 4 }} />
                  WHO Target Met (≥60% Access)
                </>
              ) : (
                <>
                  <TriangleAlert size={13} style={{ marginRight: 4 }} />
                  Below 60% Access Target
                </>
              )}
            </span>
          )}
        </div>

        {metrics?.aware_breakdown && (
          <div style={{ marginTop: 14 }}>
            {/* Proportion Bar */}
            <div
              style={{
                display: 'flex',
                height: 24,
                borderRadius: 6,
                overflow: 'hidden',
                background: '#e2e8f0',
                border: '1px solid var(--border)',
              }}
            >
              <div
                style={{
                  width: `${metrics.aware_breakdown.access_percentage}%`,
                  background: '#16a34a',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#fff',
                  fontSize: '11px',
                  fontWeight: 600,
                  transition: 'width 0.4s ease',
                }}
                title={`Access: ${metrics.aware_breakdown.access_percentage}%`}
              >
                {metrics.aware_breakdown.access_percentage > 10 ? `${metrics.aware_breakdown.access_percentage}%` : ''}
              </div>
              <div
                style={{
                  width: `${metrics.aware_breakdown.watch_percentage}%`,
                  background: '#f59e0b',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#fff',
                  fontSize: '11px',
                  fontWeight: 600,
                  transition: 'width 0.4s ease',
                }}
                title={`Watch: ${metrics.aware_breakdown.watch_percentage}%`}
              >
                {metrics.aware_breakdown.watch_percentage > 10 ? `${metrics.aware_breakdown.watch_percentage}%` : ''}
              </div>
              <div
                style={{
                  width: `${metrics.aware_breakdown.reserve_percentage}%`,
                  background: '#dc2626',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#fff',
                  fontSize: '11px',
                  fontWeight: 600,
                  transition: 'width 0.4s ease',
                }}
                title={`Reserve: ${metrics.aware_breakdown.reserve_percentage}%`}
              >
                {metrics.aware_breakdown.reserve_percentage > 5 ? `${metrics.aware_breakdown.reserve_percentage}%` : ''}
              </div>
            </div>

            {/* Legend */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: 12,
                marginTop: 10,
                fontSize: '12px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 12, height: 12, borderRadius: 3, background: '#16a34a' }} />
                <strong>Access:</strong> {metrics.aware_breakdown.access_percentage}% (
                {metrics.aware_breakdown.access_count} orders)
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 12, height: 12, borderRadius: 3, background: '#f59e0b' }} />
                <strong>Watch:</strong> {metrics.aware_breakdown.watch_percentage}% (
                {metrics.aware_breakdown.watch_count} orders)
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 12, height: 12, borderRadius: 3, background: '#dc2626' }} />
                <strong>Reserve:</strong> {metrics.aware_breakdown.reserve_percentage}% (
                {metrics.aware_breakdown.reserve_count} orders)
              </div>
              <div style={{ color: 'var(--muted)', fontSize: '11px' }}>
                Benchmark: {metrics.aware_breakdown.who_benchmark}
              </div>
            </div>
          </div>
        )}

        {/* 5 Governed KPI Cards */}
        {metrics && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
              gap: 12,
              marginTop: 16,
            }}
          >
            {metrics.metrics.map((m) => (
              <div
                key={m.metric_code}
                style={{
                  padding: '10px 14px',
                  borderRadius: 6,
                  border: '1px solid var(--border)',
                  background: 'var(--bg-subtle, #f8fafc)',
                }}
              >
                <div style={{ fontSize: '11px', color: 'var(--muted)', fontWeight: 600 }}>{m.name}</div>
                <div style={{ fontSize: '20px', fontWeight: 700, margin: '4px 0', color: 'var(--text)' }}>
                  {m.value} {m.unit}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px' }}>
                  <span style={{ color: 'var(--muted)' }}>Target: {m.target_benchmark || 'N/A'}</span>
                  {m.benchmark_met !== undefined && (
                    <span style={{ color: m.benchmark_met ? '#16a34a' : '#d97706', fontWeight: 600 }}>
                      {m.benchmark_met ? 'Met' : 'Sub-target'}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Data Quality Caveats toggle */}
        <div style={{ marginTop: 14 }}>
          <button
            type="button"
            onClick={() => setShowCaveats(!showCaveats)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--muted)',
              fontSize: '11px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              padding: 0,
            }}
          >
            <Info size={12} />
            {showCaveats ? 'Hide Data Quality Caveats' : 'View Data Quality & Minimum-Cell Suppression Policy'}
          </button>
          {showCaveats && metrics?.data_quality_caveats && (
            <ul
              style={{
                marginTop: 8,
                paddingLeft: 20,
                fontSize: '11px',
                color: 'var(--muted)',
                lineHeight: 1.5,
              }}
            >
              {metrics.data_quality_caveats.map((c, idx) => (
                <li key={idx}>{c}</li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* =========================================================================
          P2-02: GOVERNED STEWARDSHIP RULES & ALERTS QUEUE
         ========================================================================= */}
      <section className="panel" style={{ marginBottom: 20 }}>
        <div className="panelHead">
          <div>
            <span className="eyebrow">P2-02 CLINICALLY GOVERNED RULES ENGINE</span>
            <h2>Stewardship Decision Alerts & Dispositions</h2>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {(['OPEN', 'RESOLVED', 'OVERRIDDEN', 'ALL'] as const).map((filter) => (
              <button
                key={filter}
                type="button"
                onClick={() => setAlertFilter(filter)}
                className={alertFilter === filter ? 'primary' : ''}
                style={{
                  fontSize: '11px',
                  padding: '3px 8px',
                  borderRadius: 4,
                  cursor: 'pointer',
                }}
              >
                {filter} {filter === 'OPEN' && `(${openAlerts.length})`}
              </button>
            ))}
          </div>
        </div>

        <p className="muted" style={{ marginBottom: 12 }}>
          Structured alerts are generated during prescription intake by the governed rules engine (Access first-line
          priority, 7-day duration ceiling, Reserve pre-authorization). Clinicians and stewardship officers can record
          auditable review dispositions with clinical rationale.
        </p>

        {alertMessage && (
          <p className="reminderStatus" role="status" style={{ marginBottom: 12 }}>
            {alertMessage}
          </p>
        )}

        <div className="reviewGrid">
          <div className="reviewList" style={{ maxHeight: 380, overflowY: 'auto' }}>
            {filteredAlerts.length ? (
              filteredAlerts.map((a) => (
                <div
                  key={a.alert_id}
                  className={`reviewItem ${a.status === 'OPEN' ? 'reviewPending' : ''}`}
                  style={{
                    cursor: a.status === 'OPEN' ? 'pointer' : 'default',
                    borderColor: selectedAlert?.alert_id === a.alert_id ? 'var(--primary)' : undefined,
                  }}
                  onClick={() => a.status === 'OPEN' && setSelectedAlert(a)}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span className={`statusPill ${getSeverityBadgeClass(a.severity)}`}>{a.severity}</span>
                    <span style={{ fontSize: '11px', color: 'var(--muted)' }}>{formatDate(a.created_at)}</span>
                  </div>
                  <strong style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
                    <ShieldAlert size={14} color="#d97706" /> {a.rule_code} · Prescription #{a.prescription_id}
                  </strong>
                  <p style={{ margin: '4px 0', fontSize: '12px' }}>{a.message}</p>
                  {a.clinical_evidence && (
                    <small style={{ color: 'var(--muted)', display: 'block' }}>Evidence: {a.clinical_evidence}</small>
                  )}
                  {a.disposition_outcome ? (
                    <span className="reviewOutcome" style={{ marginTop: 6 }}>
                      Disposition: <b>{a.disposition_outcome}</b> · {a.disposition_reason}
                    </span>
                  ) : (
                    <span style={{ fontSize: '11px', color: 'var(--primary)', fontWeight: 600, marginTop: 4 }}>
                      Click to record disposition →
                    </span>
                  )}
                </div>
              ))
            ) : (
              <div className="emptyState">
                <span>
                  <CheckCircle2 size={24} color="#16a34a" />
                </span>
                <strong>No {alertFilter.toLowerCase()} stewardship alerts</strong>
                <p>Prescriptions conform to active formulary rules and duration limits.</p>
              </div>
            )}
          </div>

          {/* Disposition Review Action Panel */}
          {selectedAlert && (
            <form className="reviewForm" onSubmit={handleAlertDisposition}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="eyebrow">ALERT DISPOSITION REVIEW</span>
                <button
                  type="button"
                  onClick={() => setSelectedAlert(null)}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 2 }}
                >
                  <X size={16} />
                </button>
              </div>
              <strong style={{ fontSize: '13px' }}>
                {selectedAlert.rule_code} (Rx #{selectedAlert.prescription_id})
              </strong>
              <p style={{ fontSize: '12px', color: 'var(--muted)', margin: '4px 0 8px 0' }}>
                {selectedAlert.message}
              </p>

              <label>
                Disposition Action
                <select
                  value={alertOutcome}
                  onChange={(e) =>
                    setAlertOutcome(e.target.value as 'ACCEPTED' | 'OVERRIDDEN_WITH_REASON' | 'FALSE_POSITIVE_FLAGGED')
                  }
                >
                  <option value="ACCEPTED">Accept Guideline Recommendation (De-escalate / Modify)</option>
                  <option value="OVERRIDDEN_WITH_REASON">Override with Clinical Rationale (Document Exception)</option>
                  <option value="FALSE_POSITIVE_FLAGGED">Flag as False Positive (Rule Calibration Feedback)</option>
                </select>
              </label>

              <label>
                Clinical Rationale / Notes (Mandatory)
                <textarea
                  required
                  minLength={5}
                  maxLength={500}
                  rows={3}
                  placeholder="Record micro culture results, patient-specific resistance profile, or justification…"
                  value={alertReason}
                  onChange={(e) => setAlertReason(e.target.value)}
                />
              </label>

              <button className="primary full" type="submit" disabled={alertBusy}>
                <ClipboardCheck size={16} />
                {alertBusy ? 'Recording disposition…' : 'Record Alert Disposition'}
              </button>
            </form>
          )}
        </div>
      </section>

      {/* =========================================================================
          POST-DISPENSE CLINICAL REVIEW QUEUE
         ========================================================================= */}
      <section className="panel reviewWorkspace">
        <div className="panelHead">
          <div>
            <span className="eyebrow">POST-DISPENSE CLINICAL REVIEW QUEUE</span>
            <h2>Review response and treatment reassessment</h2>
          </div>
          <span className="statusPill">
            {reviews.filter((r) => r.status === 'COMPLETED').length} completed · {pendingReviews.length} pending
          </span>
        </div>

        <p className="muted">
          A review task is deterministically generated after the first recorded dispense event (due by default at Day 3
          for AWaRe watchlist review).
        </p>

        <div className="reviewGrid">
          <div className="reviewList" style={{ maxHeight: 380, overflowY: 'auto' }}>
            {reviews.length ? (
              reviews.map((r) => (
                <div className={`reviewItem ${r.status === 'PENDING' ? 'reviewPending' : ''}`} key={r.id}>
                  <span className={`statusPill status-${r.status.toLowerCase()}`}>{r.status}</span>
                  <strong>{r.prescription_code}</strong>
                  <small>
                    Patient Ref: {r.patient_reference} · Due {formatDate(r.due_at)}
                  </small>
                  {r.outcome ? (
                    <span className="reviewOutcome">
                      Outcome: <b>{r.outcome}</b> · {r.reason}
                    </span>
                  ) : (
                    <small>Dispense transaction recorded · Pending clinical review</small>
                  )}
                </div>
              ))
            ) : (
              <div className="emptyState">
                <span>
                  <ClipboardCheck size={24} />
                </span>
                <strong>No review tasks queued</strong>
                <p>A post-dispense review will automatically appear after pharmacy dispensing is recorded.</p>
              </div>
            )}
          </div>

          {pendingReviews.length > 0 && (
            <form className="reviewForm" onSubmit={completeReview}>
              <span className="eyebrow">RECORD STEWARDSHIP REVIEW</span>
              <label>
                Review Outcome
                <select value={reviewOutcome} onChange={(e) => setReviewOutcome(e.target.value)}>
                  <option value="CONTINUE">Continue as prescribed</option>
                  <option value="CHANGE">Change treatment plan / de-escalate</option>
                  <option value="STOP">Stop antibiotic therapy</option>
                  <option value="REFER">Refer for specialist infectious disease review</option>
                </select>
              </label>

              <label>
                Clinical Rationale / Notes
                <textarea
                  required
                  minLength={3}
                  maxLength={500}
                  rows={3}
                  placeholder="Record clinical indication check, culture results, or de-escalation rationale…"
                  value={reviewReason}
                  onChange={(e) => setReviewReason(e.target.value)}
                />
              </label>

              <label>
                Reviewing Clinician Reference
                <input
                  required
                  minLength={2}
                  maxLength={150}
                  placeholder="Staff or facility user reference"
                  value={reviewer}
                  onChange={(e) => setReviewer(e.target.value)}
                />
              </label>

              <button className="primary full" type="submit" disabled={reviewBusy}>
                <ClipboardCheck size={16} />
                {reviewBusy ? 'Saving review…' : 'Complete Stewardship Review'}
              </button>
            </form>
          )}
        </div>

        {statusMessage && (
          <p className="reminderStatus" role="status" style={{ marginTop: 12 }}>
            {statusMessage}
          </p>
        )}

        <div className="notice" style={{ marginTop: 12 }}>
          <TriangleAlert size={16} />
          <span>
            Stewardship tasks assist clinical teams in adhering to Rwanda national AMS guidelines; they never
            autonomously alter treatment or overrule clinicians.
          </span>
        </div>
      </section>

      {/* =========================================================================
          PATIENT COURSE ADHERENCE & DOSE REMINDERS OUTBOX
         ========================================================================= */}
      <div className="twoCol reminderLayout">
        <section className="panel reminderForm">
          <span className="eyebrow">PATIENT COURSE ADHERENCE</span>
          <h2>Enroll in Dose Reminders</h2>
          <p className="muted">
            Enrolls an active prescription into the deterministic dose-level reminder engine. Requires verified patient
            consent. Phone numbers are cryptographically hashed and never exposed in plaintext.
          </p>

          <div style={{ display: 'grid', gap: 10, marginTop: 14 }}>
            <span className="eyebrow">ELIGIBLE DISPENSED PRESCRIPTIONS</span>
            {dispensedCandidates.length ? (
              dispensedCandidates.map((rx) => (
                <div
                  key={rx.id}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '8px 12px',
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-subtle, #f8fafc)',
                  }}
                >
                  <div>
                    <strong>{rx.code}</strong> · {rx.patient_reference}
                    <div style={{ fontSize: '11px', color: 'var(--muted)' }}>
                      {rx.items[0]?.antibiotic} ({rx.items[0]?.authorized_quantity} units)
                    </div>
                  </div>
                  <button
                    type="button"
                    className="primary"
                    onClick={() => onOpenConsentModal(rx)}
                    style={{ fontSize: '12px', padding: '5px 10px' }}
                  >
                    <BellRing size={13} /> Capture Consent
                  </button>
                </div>
              ))
            ) : (
              <p className="muted" style={{ fontSize: '12px' }}>
                No dispensed prescriptions eligible for adherence enrollment. Complete a dispense first.
              </p>
            )}
          </div>
        </section>

        <section className="panel reminderRegister">
          <div className="panelHead">
            <div>
              <span className="eyebrow">REMINDER OUTBOX REGISTER</span>
              <h2>{reminders.length} scheduled reminders</h2>
            </div>
            <Clock3 size={18} />
          </div>

          <div style={{ maxHeight: 340, overflowY: 'auto' }}>
            {reminders.length ? (
              reminders.map((rem) => (
                <div className="reminderRow" key={rem.id}>
                  <span className={`statusPill status-${rem.status.toLowerCase()}`}>{rem.status}</span>
                  <strong>{rem.prescription_code}</strong>
                  <small>{formatDate(rem.scheduled_at)}</small>
                  <span className="consentRecorded">
                    <CheckCircle2 size={14} /> Consent verified
                  </span>
                </div>
              ))
            ) : (
              <div className="emptyState">
                <span>
                  <BellRing size={24} />
                </span>
                <strong>No reminders scheduled</strong>
                <p>
                  Schedules appear here with consent verification status and planned send time. Delivery receipts are
                  audited separately from ingestion.
                </p>
              </div>
            )}
          </div>

          <div className="notice" style={{ marginTop: 12 }}>
            <TriangleAlert size={16} />
            <span>
              SMS delivery receipts confirm telecom network transmission only; they never constitute clinical proof of
              medication ingestion.
            </span>
          </div>
        </section>
      </div>
    </>
  );
}
