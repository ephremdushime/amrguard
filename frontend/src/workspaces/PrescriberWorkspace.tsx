import React, { useCallback, useEffect, useState } from 'react';
import {
  BellRing,
  CheckCircle2,
  ClipboardCheck,
  Code2,
  FileCheck2,
  KeyRound,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
  X,
  XCircle,
} from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import { apiFetch, type AuthUser } from '../authApi';
import { AIAssistPanel } from '../components/AIAssistPanel';
import { ConsentReminderModal } from '../components/ConsentReminderModal';
import { PrescriptionQueue } from '../components/PrescriptionQueue';
import type { OperationalRx, PrescriptionOrder, StewardshipAlertItem } from '../types';

interface PrescriberWorkspaceProps {
  api: string;
  user: AuthUser;
  activeSection: string;
  refreshKey: number;
  isDev: boolean;
  onNotify: (message: string) => void;
  onUnauthorized: () => void;
}

export function PrescriberWorkspace({
  api,
  user,
  activeSection,
  refreshKey,
  isDev,
  onNotify,
  onUnauthorized,
}: PrescriberWorkspaceProps) {
  const facilityId = user.scopes.find((s) => s.facility_id != null)?.facility_id || 1;

  // Orders state
  const [prescriptions, setPrescriptions] = useState<OperationalRx[]>([]);
  const [selectedRx, setSelectedRx] = useState<OperationalRx | null>(null);
  const [issuedCred, setIssuedCred] = useState<{ otp: string; qr_token: string; expires_at: string } | null>(null);
  const [fhirJson, setFhirJson] = useState<string>('');
  const [consentModalRx, setConsentModalRx] = useState<OperationalRx | null>(null);

  // Synthetic order composer state (dev/demo only)
  const [patient, setPatient] = useState('');
  const [dose, setDose] = useState(500);
  const [frequency, setFrequency] = useState(3);
  const [duration, setDuration] = useState(5);
  const [indication, setIndication] = useState('');
  const [lifetime, setLifetime] = useState(72);
  const [support, setSupport] = useState<{
    decision?: string;
    display?: { message?: string };
    stewardship?: { aware_category?: string; review_prompt?: string };
  } | null>(null);
  const quantity = frequency * duration;

  // Alerts state
  const [alerts, setAlerts] = useState<StewardshipAlertItem[]>([]);
  const [selectedAlert, setSelectedAlert] = useState<StewardshipAlertItem | null>(null);
  const [alertOutcome, setAlertOutcome] = useState<'ACCEPTED' | 'OVERRIDDEN_WITH_REASON' | 'FALSE_POSITIVE_FLAGGED'>('ACCEPTED');
  const [alertReason, setAlertReason] = useState('');
  const [alertBusy, setAlertBusy] = useState(false);

  // Dev risk scenario state
  const [riskResult, setRiskResult] = useState<{ prescription?: { code?: string; status?: string; external_id?: string } } | null>(null);
  const [riskBusy, setRiskBusy] = useState(false);

  const loadPrescriptions = useCallback(async () => {
    const res = await apiFetch(`${api}/api/v1/prescriptions?limit=200`);
    if (res.status === 401) {
      onUnauthorized();
      return;
    }
    if (res.ok) {
      const list: OperationalRx[] = await res.json();
      setPrescriptions(list);
      setSelectedRx((prev) => {
        if (prev) {
          const found = list.find((r) => r.id === prev.id);
          if (found) return found;
        }
        return list[0] || null;
      });
    }
  }, [api, onUnauthorized]);

  const loadAlerts = useCallback(async () => {
    const res = await apiFetch(`${api}/api/v1/stewardship/alerts?limit=100`);
    if (res.status === 401) {
      onUnauthorized();
      return;
    }
    if (res.ok) {
      setAlerts(await res.json());
    }
  }, [api, onUnauthorized]);

  useEffect(() => {
    if (activeSection === 'orders') {
      loadPrescriptions();
    } else if (activeSection === 'alerts') {
      loadAlerts();
    }
  }, [activeSection, loadPrescriptions, loadAlerts, refreshKey]);

  // Embedded stewardship support check on regimen changes (orders section)
  useEffect(() => {
    if (activeSection !== 'orders') return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      apiFetch(`${api}/api/v1/stewardship/support`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          antibiotic_code: 'AMX500CAP',
          generic_name: 'Amoxicillin',
          dose,
          frequency_per_day: frequency,
          duration_days: duration,
          quantity,
          indication: indication || 'Not entered',
        }),
      })
        .then((r) => (r.ok ? r.json() : null))
        .then(setSupport)
        .catch(() => {});
    }, 200);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [api, activeSection, dose, frequency, duration, quantity, indication]);

  const handleCreateDemoOrder = async (e: React.FormEvent) => {
    e.preventDefault();
    const order: PrescriptionOrder = {
      external_id: `EBZ-DEMO-${Date.now()}`,
      patient_reference: patient.trim(),
      antibiotic_code: 'AMX500CAP',
      generic_name: 'Amoxicillin',
      strength: '500 mg',
      formulation: 'Capsule',
      route: 'Oral',
      dose,
      frequency_per_day: frequency,
      duration_days: duration,
      quantity,
      indication: indication.trim(),
      expires_at: new Date(Date.now() + lifetime * 60 * 60 * 1000).toISOString(),
    };
    try {
      const res = await apiFetch(`${api}/api/v1/demo/prescriptions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(order),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to create prescription');
      setSelectedRx(body.prescription);
      setIssuedCred(null);
      setFhirJson('');
      setPatient('');
      setIndication('');
      onNotify(`Prescription ${body.prescription?.code || ''} validated and recorded`);
      await loadPrescriptions();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Unable to create prescription');
    }
  };

  const handleIssueCredential = async () => {
    if (!selectedRx) return;
    try {
      const res = await apiFetch(`${api}/api/v1/prescriptions/${selectedRx.id}/credential`, { method: 'POST' });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to issue credential');
      setIssuedCred({ otp: body.otp, qr_token: body.qr_token, expires_at: body.expires_at });
      onNotify(`Issued QR/OTP credential for ${selectedRx.code}`);
      await loadPrescriptions();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Credential issuance failed');
    }
  };

  const handleRevokeCredential = async () => {
    if (!selectedRx) return;
    try {
      const res = await apiFetch(`${api}/api/v1/prescriptions/${selectedRx.id}/credential/revoke`, { method: 'POST' });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to revoke credential');
      setIssuedCred(null);
      onNotify(`Active credential revoked for ${selectedRx.code}`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Revocation failed');
    }
  };

  const handleExportFhir = async () => {
    if (!selectedRx) return;
    try {
      const res = await apiFetch(`${api}/api/v1/integrations/ebuzima/prescriptions/${selectedRx.id}/fhir?bundle=true`);
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'FHIR export failed');
      setFhirJson(JSON.stringify(body, null, 2));
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'FHIR export error');
    }
  };

  const handleDispositionAlert = async (e: React.FormEvent) => {
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
      onNotify(`Alert ${selectedAlert.alert_id} dispositioned (${alertOutcome})`);
      setSelectedAlert(null);
      setAlertReason('');
      await loadAlerts();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Alert disposition error');
    } finally {
      setAlertBusy(false);
    }
  };

  const runRiskScenario = async () => {
    setRiskBusy(true);
    try {
      const res = await apiFetch(`${api}/api/v1/demo/risk-scenario`, { method: 'POST' });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Risk scenario blocked or disabled');
      setRiskResult(body);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Risk scenario failed');
    } finally {
      setRiskBusy(false);
    }
  };

  if (activeSection === 'alerts') {
    const openAlerts = alerts.filter((a) => a.status === 'OPEN');
    return (
      <div style={{ display: 'grid', gap: 16 }}>
        <div className="pageTitle">
          <div>
            <span className="eyebrow">PRESCRIBER CLINICAL DECISION SUPPORT</span>
            <h1>Stewardship Alerts & Bounded AI Guidance</h1>
            <p>
              Review rules-engine alerts generated on your facility&apos;s antibiotic prescriptions, record clinical
              dispositions, and inspect read-only guideline citations.
            </p>
          </div>
          <span className="sourceBadge">
            <ShieldAlert size={14} /> {openAlerts.length} open alerts · {alerts.length} total
          </span>
        </div>

        <section className="panel">
          <div className="reviewGrid">
            <div className="reviewList" style={{ maxHeight: 420, overflowY: 'auto' }}>
              {alerts.length ? (
                alerts.map((a) => (
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
                      <small style={{ display: 'block', marginTop: 3 }}>{a.message}</small>
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
                  <strong>No clinical stewardship alerts</strong>
                  <p>Facility prescriptions currently satisfy active stewardship rules.</p>
                </div>
              )}
            </div>

            {selectedAlert && (
              <div style={{ display: 'grid', gap: 12 }}>
                {selectedAlert.status === 'OPEN' && (
                  <form className="reviewForm" onSubmit={handleDispositionAlert}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span className="eyebrow">RECORD CLINICAL DISPOSITION</span>
                      <button
                        type="button"
                        onClick={() => setSelectedAlert(null)}
                        style={{ background: 'none', border: 'none', padding: 2 }}
                      >
                        <X size={15} />
                      </button>
                    </div>
                    <strong>
                      {selectedAlert.rule_code} (Rx #{selectedAlert.prescription_id})
                    </strong>
                    <label>
                      Outcome
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
                        placeholder="Document diagnostic findings or sensitivity rationale…"
                      />
                    </label>
                    <button className="primary full" type="submit" disabled={alertBusy}>
                      <ClipboardCheck size={15} />
                      {alertBusy ? 'Recording…' : 'Submit Disposition'}
                    </button>
                  </form>
                )}

                <AIAssistPanel
                  api={api}
                  scenario="STEWARDSHIP_ALERT_EXPLAIN"
                  alertId={selectedAlert.alert_id}
                  title={`Explain Alert ${selectedAlert.rule_code}`}
                  buttonLabel="Explain Selected Alert"
                />
              </div>
            )}
          </div>
        </section>
      </div>
    );
  }

  if (activeSection === 'safety' && isDev) {
    return (
      <div style={{ display: 'grid', gap: 16 }}>
        <div className="pageTitle">
          <div>
            <span className="eyebrow">NON-PRODUCTION VALIDATION CHECK</span>
            <h1>Deterministic Quantity-Mismatch Blocking</h1>
            <p>
              Verify that AMRGuard blocks mismatched antibiotic quantities before pharmacy credentials can be issued.
              This diagnostic route is disabled (`404`) in sandbox and production environments.
            </p>
          </div>
        </div>
        <div className="twoCol" style={{ margin: 0, maxWidth: 'none' }}>
          <div className="panel">
            <span className="eyebrow">TEST SCENARIO</span>
            <h2>Intentional Quantity Mismatch (15 expected vs 20 submitted)</h2>
            <div className="orderCard">
              <div>
                <span>Regimen</span>
                <strong>500 mg · 3×/day · 5 days</strong>
              </div>
              <div>
                <span>Expected</span>
                <strong>15 units</strong>
              </div>
              <div>
                <span>Submitted</span>
                <strong>20 units</strong>
              </div>
            </div>
            <button className="primary full" onClick={runRiskScenario} disabled={riskBusy}>
              <TriangleAlert size={16} />
              {riskBusy ? 'Running validation test…' : 'Trigger Blocked Prescription Test'}
            </button>
          </div>

          <div className="panel">
            {riskResult ? (
              <>
                <span className="eyebrow">VALIDATION OUTPUT</span>
                <h2>{riskResult.prescription?.code}</h2>
                <div className="result errorBox">
                  <TriangleAlert size={18} />
                  <div>
                    <b>BLOCKED ({riskResult.prescription?.status || 'BLOCKED'})</b>
                    <span>
                      External Ref {riskResult.prescription?.external_id || '—'} · Rule <code>QUANTITY_MISMATCH</code>
                    </span>
                  </div>
                </div>
              </>
            ) : (
              <div className="emptyState">
                <span>
                  <ShieldCheck size={22} />
                </span>
                <strong>Ready for validation test</strong>
                <p>Run the scenario to confirm deterministic blocking before credential generation.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  const supportError = support?.decision === 'REVIEW_REQUIRED';

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="pageTitle">
        <div>
          <span className="eyebrow">PRESCRIBER WORKSPACE · FACILITY SCOPED</span>
          <h1>Prescription Register, Credentials & Embedded Support</h1>
          <p>
            Inspect facility antibiotic orders ingested from source EMRs, issue or revoke short-lived pharmacy QR/OTP
            credentials, export multi-item FHIR R4 bundles, and test embedded stewardship checks.
          </p>
        </div>
        <span className="sourceBadge">
          <FileCheck2 size={14} /> {prescriptions.length} facility orders
        </span>
      </div>

      {/* Operational Facility Register + Selected Order Actions */}
      <div className="operationsGrid" style={{ maxWidth: 'none', margin: 0 }}>
        <PrescriptionQueue
          prescriptions={prescriptions}
          selectedRx={selectedRx}
          onSelect={(rx) => {
            setSelectedRx(rx);
            setIssuedCred(null);
            setFhirJson('');
          }}
          title="Facility Orders"
          eyebrow="SCOPED PRESCRIPTIONS"
        />

        <div style={{ display: 'grid', gap: 14 }}>
          {selectedRx ? (
            <section className="panel" style={{ display: 'grid', gap: 14 }}>
              <div className="panelHead">
                <div>
                  <span className="eyebrow">PRESCRIPTION DETAIL · {selectedRx.external_id}</span>
                  <h2>{selectedRx.code}</h2>
                </div>
                <span className="statusPill">{selectedRx.status}</span>
              </div>

              <div className="summaryStrip" style={{ margin: 0 }}>
                <div>
                  <span>Patient Ref</span>
                  <b>{selectedRx.patient_reference}</b>
                </div>
                <div>
                  <span>Prescriber</span>
                  <b>{selectedRx.prescriber.name}</b>
                </div>
                <div>
                  <span>Facility</span>
                  <b>{selectedRx.facility.name}</b>
                </div>
                <div>
                  <span>Items</span>
                  <b>{selectedRx.items.length}</b>
                </div>
              </div>

              <div style={{ display: 'grid', gap: 8 }}>
                {selectedRx.items.map((item) => (
                  <div
                    key={item.id}
                    style={{
                      padding: '10px 12px',
                      border: '1px solid var(--line)',
                      borderRadius: 6,
                      background: '#fbfdfb',
                    }}
                  >
                    <strong>
                      {item.antibiotic} {item.strength} ({item.formulation} · {item.route})
                    </strong>
                    <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 3 }}>
                      Dose: {item.dose} · {item.frequency_per_day}×/day · {item.duration_days} days · Authorized Qty:{' '}
                      <b>{item.authorized_quantity}</b> · Indication: {item.indication}
                    </div>
                  </div>
                ))}
              </div>

              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button
                  type="button"
                  className="primary"
                  onClick={handleIssueCredential}
                  disabled={selectedRx.status === 'BLOCKED' || selectedRx.status === 'COMPLETED'}
                  style={{ minHeight: 34, padding: '0 12px', display: 'inline-flex', alignItems: 'center', gap: 6 }}
                >
                  <KeyRound size={14} /> Issue QR / OTP Credential
                </button>
                <button
                  type="button"
                  onClick={handleRevokeCredential}
                  style={{ minHeight: 34, padding: '0 12px', display: 'inline-flex', alignItems: 'center', gap: 6, border: '1px solid var(--line)', borderRadius: 6, background: '#fff' }}
                >
                  <XCircle size={14} /> Revoke Active Credential
                </button>
                <button
                  type="button"
                  onClick={() => setConsentModalRx(selectedRx)}
                  style={{ minHeight: 34, padding: '0 12px', display: 'inline-flex', alignItems: 'center', gap: 6, border: '1px solid var(--line)', borderRadius: 6, background: '#fff' }}
                >
                  <BellRing size={14} /> Capture Patient SMS Consent
                </button>
                <button
                  type="button"
                  onClick={handleExportFhir}
                  style={{ minHeight: 34, padding: '0 12px', display: 'inline-flex', alignItems: 'center', gap: 6, border: '1px solid var(--line)', borderRadius: 6, background: '#fff' }}
                >
                  <Code2 size={14} /> Export FHIR R4 Bundle
                </button>
              </div>

              {issuedCred && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 16,
                    padding: 12,
                    borderRadius: 6,
                    background: '#f2faf6',
                    border: '1px solid #bfe5d7',
                    flexWrap: 'wrap',
                  }}
                >
                  <QRCodeSVG value={issuedCred.qr_token} size={74} />
                  <div>
                    <span className="eyebrow">ACTIVE PHARMACY CREDENTIAL (10-MIN TTL)</span>
                    <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: 2, marginTop: 4 }}>
                      OTP: {issuedCred.otp}
                    </div>
                    <small style={{ display: 'block', color: 'var(--muted)' }}>
                      QR Token: <code>{issuedCred.qr_token}</code>
                    </small>
                    <small style={{ display: 'block', color: 'var(--muted)' }}>
                      Expires: {new Date(issuedCred.expires_at).toLocaleString()}
                    </small>
                  </div>
                </div>
              )}

              {fhirJson && (
                <div>
                  <span className="eyebrow">FHIR R4 BUNDLE EXPORT (MULTI-ITEM)</span>
                  <pre className="codeBlock" style={{ maxHeight: 220, overflow: 'auto', marginTop: 6 }}>
                    {fhirJson}
                  </pre>
                </div>
              )}
            </section>
          ) : null}

          {selectedRx && (
            <AIAssistPanel
              api={api}
              scenario="PRESCRIPTION_VALIDATION_EXPLAIN"
              prescriptionId={selectedRx.id}
              title={`Explain Validation for ${selectedRx.code}`}
              buttonLabel="Explain Prescription Check"
            />
          )}
        </div>
      </div>

      {/* Non-production EMR Intake Simulator */}
      {isDev && (
        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">SYNTHETIC EMR INTAKE SIMULATOR (DEV / PILOT ONLY)</span>
              <h2>Simulate e-Buzima Order with Embedded Stewardship Support</h2>
            </div>
            <span className="statusPill">Disabled in production</span>
          </div>
          <p className="muted" style={{ marginTop: 6, marginBottom: 14 }}>
            In production, prescriptions originate in e-Buzima or OpenMRS via signed service-client ingestion. This
            local simulator exercises <code>POST /api/v1/stewardship/support</code> and creates synthetic pilot orders.
          </p>

          <form className="prescriptionForm" onSubmit={handleCreateDemoOrder}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <label>
                Patient Reference / Encounter ID
                <input
                  required
                  placeholder="e.g. RW-PAT-2026-00412"
                  value={patient}
                  onChange={(e) => setPatient(e.target.value)}
                />
              </label>
              <label>
                Antibiotic Catalogue Item
                <select value="AMX500CAP" disabled>
                  <option value="AMX500CAP">Amoxicillin 500 mg · Capsule · Oral (WHO Access)</option>
                </select>
              </label>
            </div>

            <div className="prescriptionFields">
              <label>
                Dose (mg)
                <input required type="number" min={1} value={dose} onChange={(e) => setDose(Number(e.target.value))} />
              </label>
              <label>
                Times / Day
                <input
                  required
                  type="number"
                  min={1}
                  max={8}
                  value={frequency}
                  onChange={(e) => setFrequency(Number(e.target.value))}
                />
              </label>
              <label>
                Duration (Days)
                <input
                  required
                  type="number"
                  min={1}
                  max={365}
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value))}
                />
              </label>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
              <label>
                Clinical Indication
                <input
                  required
                  placeholder="Document clinical indication…"
                  value={indication}
                  onChange={(e) => setIndication(e.target.value)}
                />
              </label>
              <label>
                Valid for (hours)
                <input
                  required
                  type="number"
                  min={1}
                  max={720}
                  value={lifetime}
                  onChange={(e) => setLifetime(Number(e.target.value))}
                />
              </label>
            </div>

            <div className={`embeddedSupport ${supportError ? 'supportError' : ''}`} style={{ margin: '4px 0' }}>
              <div className="supportHead">
                <span className="supportGlyph">
                  {supportError ? <TriangleAlert size={16} /> : <ShieldCheck size={16} />}
                </span>
                <div>
                  <b>Embedded Stewardship Support · {quantity} calculated units</b>
                  <small>
                    AWaRe: {support?.stewardship?.aware_category || 'ACCESS'} ·{' '}
                    {support?.display?.message || 'Evaluating regimen…'}
                  </small>
                </div>
                <span className={`supportDecision ${supportError ? '' : 'supportPass'}`}>
                  {supportError ? 'REVIEW' : 'CHECKED'}
                </span>
              </div>
            </div>

            <button className="primary full" type="submit">
              <FileCheck2 size={16} /> Create Synthetic Pilot Order
            </button>
          </form>
        </section>
      )}

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
            onNotify('Patient SMS consent verified and dose reminders scheduled');
          }}
        />
      )}
    </div>
  );
}
