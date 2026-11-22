import React, { useState } from 'react';
import { BellRing, CheckCircle2, ShieldCheck, TriangleAlert, X } from 'lucide-react';
import { apiFetch } from '../authApi';

interface ConsentReminderModalProps {
  api: string;
  prescriptionId: number;
  prescriptionCode: string;
  patientReference: string;
  facilityId: number;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function ConsentReminderModal({
  api,
  prescriptionId,
  prescriptionCode,
  patientReference,
  facilityId,
  isOpen,
  onClose,
  onSuccess,
}: ConsentReminderModalProps) {
  const [phoneNumber, setPhoneNumber] = useState('');
  const [language, setLanguage] = useState<'rw' | 'en' | 'fr'>('rw');
  const [evidenceRef, setEvidenceRef] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!confirmed) return;
    setBusy(true);
    setError('');

    try {
      // 1. Capture consent record
      const consentRes = await apiFetch(`${api}/api/v1/consent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          patient_reference: patientReference,
          phone_number: phoneNumber.trim(),
          purpose: 'STEWARDSHIP_REMINDER',
          channel: 'SMS',
          language,
          facility_id: facilityId,
          evidence_reference: evidenceRef.trim() || undefined,
          policy_version: '2026.1',
        }),
      });

      const consentBody = await consentRes.json();
      if (!consentRes.ok) {
        throw new Error(consentBody.detail || 'Failed to capture consent record');
      }

      // 2. Schedule dose-level reminder engine
      const scheduleRes = await apiFetch(
        `${api}/api/v1/prescriptions/${prescriptionId}/reminders/schedule`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            consent_record_id: consentBody.id,
            language,
            timezone: 'Africa/Kigali',
          }),
        },
      );

      const scheduleBody = await scheduleRes.json();
      if (!scheduleRes.ok) {
        throw new Error(scheduleBody.detail || 'Failed to schedule dose reminders');
      }

      onSuccess();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error capturing consent and schedule');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: 16,
      }}
    >
      <div
        className="panel"
        style={{
          maxWidth: 500,
          width: '100%',
          maxHeight: '90vh',
          overflowY: 'auto',
          position: 'relative',
          padding: 24,
          borderRadius: 12,
        }}
      >
        <button
          type="button"
          onClick={onClose}
          style={{
            position: 'absolute',
            top: 16,
            right: 16,
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
          }}
        >
          <X size={20} />
        </button>

        <span className="eyebrow" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <ShieldCheck size={14} /> PATIENT CONSENT & DOSE REMINDERS
        </span>

        <h2 style={{ margin: '4px 0 8px' }}>Course Adherence Support</h2>
        <p className="muted" style={{ fontSize: '13px', marginBottom: 16 }}>
          Prescription <b>{prescriptionCode}</b> (Patient: <b>{patientReference}</b>).
          Consent is cryptographically verified before any SMS is queued. Phone numbers are stored as keyed hashes.
        </p>

        <form onSubmit={handleSubmit} style={{ display: 'grid', gap: 14 }}>
          <label>
            Patient Phone Number (E.164)
            <input
              required
              type="tel"
              placeholder="+250 788 123 456"
              value={phoneNumber}
              onChange={(e) => setPhoneNumber(e.target.value)}
            />
          </label>

          <label>
            Preferred Notification Language
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value as 'rw' | 'en' | 'fr')}
            >
              <option value="rw">Kinyarwanda (Ikinyarwanda)</option>
              <option value="en">English</option>
              <option value="fr">French (Français)</option>
            </select>
          </label>

          <label>
            Consent Evidence Reference (Optional)
            <input
              type="text"
              placeholder="e.g. Consent Form #1042 or Paper Intake ID"
              value={evidenceRef}
              onChange={(e) => setEvidenceRef(e.target.value)}
            />
          </label>

          <div
            className="smsPreview"
            style={{
              background: 'var(--bg-subtle, #f8fafc)',
              padding: 12,
              borderRadius: 6,
              border: '1px solid var(--border)',
            }}
          >
            <span className="eyebrow" style={{ fontSize: '10px' }}>
              MESSAGE TEMPLATE PREVIEW ({language.toUpperCase()})
            </span>
            <p style={{ margin: '4px 0 0', fontSize: '12px', fontStyle: 'italic' }}>
              {language === 'rw' &&
                'AMRGuard: Igihe cyo gufata umuti wanyu kigeze. Mukurikize amabwiriza muganga yabahaye.'}
              {language === 'en' &&
                'AMRGuard: Time for your prescribed antibiotic dose. Take with water as directed by your clinician.'}
              {language === 'fr' &&
                "AMRGuard: C'est l'heure de votre prise d'antibiotique. Suivez les instructions de votre médecin."}
            </p>
          </div>

          <label
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 8,
              fontSize: '12px',
              cursor: 'pointer',
              userSelect: 'none',
            }}
          >
            <input
              required
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              style={{ marginTop: 2 }}
            />
            <span>
              I confirm the patient (or guardian) has explicitly consented to receive non-promotional dose reminder
              notifications for this prescription course.
            </span>
          </label>

          <div className="notice" style={{ margin: 0, fontSize: '11px' }}>
            <TriangleAlert size={14} />
            <span>
              <strong>Clinical Invariant:</strong> SMS delivery confirmations reflect telecom transmission only, not
              verified medication ingestion. Patient may opt out anytime by replying STOP or YEKA.
            </span>
          </div>

          {error && (
            <div className="result errorBox" style={{ margin: 0 }}>
              <TriangleAlert size={16} />
              <div>
                <b>Failed to record consent</b>
                <span>{error}</span>
              </div>
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 8 }}>
            <button type="button" className="secondary" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="primary" disabled={busy || !confirmed || !phoneNumber.trim()}>
              <BellRing size={15} />
              {busy ? 'Enrolling Patient…' : 'Record Consent & Schedule Reminders'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
