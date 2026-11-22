import React, { useEffect, useState } from 'react';
import {
  BellRing,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  MessageSquareText,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react';
import { apiFetch } from '../authApi';
import type { OperationalRx, OperationalTransaction, StewardshipReminderRow, StewardshipReviewRow } from '../types';

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
  const [reviews, setReviews] = useState<StewardshipReviewRow[]>([]);
  const [reviewOutcome, setReviewOutcome] = useState('CONTINUE');
  const [reviewReason, setReviewReason] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [reviewBusy, setReviewBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');

  const loadReviews = () =>
    apiFetch(`${api}/api/v1/stewardship/reviews?limit=200`)
      .then((res) => (res.ok ? res.json() : []))
      .then(setReviews)
      .catch(() => setReviews([]));

  useEffect(() => {
    loadReviews();
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
      onReload();
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : 'Unable to complete review');
    } finally {
      setReviewBusy(false);
    }
  };

  const pendingReviews = reviews.filter((r) => r.status === 'PENDING');
  const dispensedRxIds = new Set(transactions.map((t) => t.prescription_id));
  const dispensedCandidates = prescriptions.filter(
    (rx) => rx.status !== 'BLOCKED' && rx.items.length && dispensedRxIds.has(rx.id),
  );

  const formatDate = (val?: string | null) => (val ? new Date(val).toLocaleString() : 'Not set');

  return (
    <>
      <div className="pageTitle">
        <div>
          <span className="eyebrow">ANTIMICROBIAL STEWARDSHIP</span>
          <h1>Stewardship review and follow-up</h1>
          <p>
            Coordinate clinical post-dispense review tasks and verified consent-based patient adherence support from
            the connected digital thread.
          </p>
        </div>
        <span className="sourceBadge">
          <ClipboardCheck size={15} /> {pendingReviews.length} reviews pending
        </span>
      </div>

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
          A review task is deterministically generated after the first recorded dispense event (due by default at Day
          3 for AWaRe watchlist review).
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

      {/* Patient Adherence Reminders & Outbox */}
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
