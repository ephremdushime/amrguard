import React, { useState } from 'react';
import { BookMarked, RefreshCw, ShieldCheck, Sparkles, TriangleAlert } from 'lucide-react';
import { apiFetch } from '../authApi';
import type { AIAssistanceResponse } from '../types';

interface AIAssistPanelProps {
  api: string;
  scenario: 'AGGREGATE_TREND_SUMMARY' | 'STEWARDSHIP_ALERT_EXPLAIN' | 'PRESCRIPTION_VALIDATION_EXPLAIN';
  facilityId?: number | null;
  alertId?: string | null;
  prescriptionId?: number | null;
  title?: string;
  eyebrow?: string;
  buttonLabel?: string;
}

export function AIAssistPanel({
  api,
  scenario,
  facilityId,
  alertId,
  prescriptionId,
  title = 'Bounded Clinical & Surveillance AI Assistant',
  eyebrow = 'P2-03 STRICTLY BOUNDED AI · READ-ONLY & PHI-REDACTED',
  buttonLabel = 'Generate Cited Stewardship Brief',
}: AIAssistPanelProps) {
  const [result, setResult] = useState<AIAssistanceResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const runAssist = async () => {
    setBusy(true);
    setError('');
    try {
      const payload: Record<string, unknown> = { scenario };
      if (facilityId != null) payload.facility_id = facilityId;
      if (alertId) payload.alert_id = alertId;
      if (prescriptionId != null) payload.prescription_id = prescriptionId;

      const res = await apiFetch(`${api}/api/v1/stewardship/ai-assist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to generate AI guidance');
      setResult(body as AIAssistanceResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI assistance request failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <div className="panelHead">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h2>{title}</h2>
        </div>
        <button type="button" className="primary" onClick={runAssist} disabled={busy}>
          {busy ? <RefreshCw size={14} className="spin" /> : <Sparkles size={14} />}
          {busy ? 'Evaluating…' : buttonLabel}
        </button>
      </div>

      <p className="muted" style={{ marginTop: 8 }}>
        Read-only advisory synthesis grounded in WHO AWaRe 2023 and Rwanda Standard Treatment Guidelines. Direct
        patient identifiers are scrubbed before analysis, and every query is recorded in the audit log.
      </p>

      {error && (
        <div className="result errorBox">
          <TriangleAlert size={16} />
          <div>
            <b>AI guidance unavailable</b>
            <span>{error}</span>
          </div>
        </div>
      )}

      {result && (
        <div style={{ marginTop: 14, display: 'grid', gap: 12 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <span className="statusPill success">
              <ShieldCheck size={12} style={{ marginRight: 4 }} />
              {result.phi_redacted ? 'PHI Scrubbed' : 'De-identified'}
            </span>
            <span className="statusPill">Engine: {result.model_version}</span>
            <span className="statusPill">Evaluated: {new Date(result.evaluated_at).toLocaleString()}</span>
          </div>

          <div
            style={{
              padding: 14,
              borderRadius: 7,
              border: '1px solid #cce4d3',
              background: '#f4faf5',
            }}
          >
            <strong style={{ display: 'block', fontSize: 13, color: '#183f35', marginBottom: 6 }}>
              {result.summary}
            </strong>
            <p style={{ margin: 0, fontSize: 12, lineHeight: 1.6, color: '#345249' }}>{result.clinical_rationale}</p>
          </div>

          {result.recommendations.length > 0 && (
            <div>
              <span className="eyebrow">ADVISORY RECOMMENDATIONS (NON-AUTONOMOUS)</span>
              <div style={{ marginTop: 6 }}>
                {result.recommendations.map((rec, i) => (
                  <div className="check" key={i}>
                    <ShieldCheck size={15} />
                    <span>{rec}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {result.guideline_citations.length > 0 && (
            <div>
              <span className="eyebrow">GROUNDED GUIDELINE CITATIONS</span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 6 }}>
                {result.guideline_citations.map((cit, i) => (
                  <span key={i} className="sourceBadge">
                    <BookMarked size={12} />
                    {Object.values(cit).filter(Boolean).join(' · ')}
                  </span>
                ))}
              </div>
            </div>
          )}

          {result.uncertainty_caveats.length > 0 && (
            <div className="notice" style={{ marginTop: 0 }}>
              <TriangleAlert size={15} />
              <div>
                <strong>Clinical Governance Caveats:</strong>
                <ul style={{ margin: '4px 0 0', paddingLeft: 16 }}>
                  {result.uncertainty_caveats.map((cav, i) => (
                    <li key={i}>{cav}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
