import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Inbox,
  Plus,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  XCircle,
} from 'lucide-react';
import { apiFetch } from '../authApi';
import type { MedicineMappingItem, QuarantineInboxItem } from '../types';

interface QuarantineCataloguePanelProps {
  api: string;
  eyebrow?: string;
  onNotify?: (msg: string) => void;
}

export function QuarantineCataloguePanel({
  api,
  eyebrow = 'P1-02 CATALOGUE GOVERNANCE & QUARANTINE',
  onNotify,
}: QuarantineCataloguePanelProps) {
  const [statusFilter, setStatusFilter] = useState<'QUARANTINED' | 'PROCESSED' | 'REJECTED'>('QUARANTINED');
  const [items, setItems] = useState<QuarantineInboxItem[]>([]);
  const [mappings, setMappings] = useState<MedicineMappingItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [notesById, setNotesById] = useState<Record<number, string>>({});
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');

  // Catalogue mapping form state
  const [sourceSystem, setSourceSystem] = useState('e-Buzima');
  const [sourceCode, setSourceCode] = useState('');
  const [sourceDescription, setSourceDescription] = useState('');
  const [conceptId, setConceptId] = useState(1);
  const [approvalStatus, setApprovalStatus] = useState<'APPROVED' | 'PENDING' | 'REJECTED'>('APPROVED');
  const [mappingBusy, setMappingBusy] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [qRes, mRes] = await Promise.all([
        apiFetch(`${api}/api/v1/integrations/inbox/quarantine?status=${statusFilter}&limit=100`),
        apiFetch(`${api}/api/v1/catalogue/mappings?limit=100`),
      ]);
      if (qRes.ok) {
        setItems(await qRes.json());
      } else {
        setItems([]);
      }
      if (mRes.ok) {
        setMappings(await mRes.json());
      } else {
        setMappings([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load quarantine and catalogue records');
    } finally {
      setLoading(false);
    }
  }, [api, statusFilter]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const resolveEntry = async (inboxId: number, action: 'REPLAY' | 'REJECT') => {
    setBusyId(inboxId);
    setError('');
    setFeedback('');
    try {
      const res = await apiFetch(`${api}/api/v1/integrations/inbox/quarantine/${inboxId}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action,
          notes: (notesById[inboxId] || '').trim() || undefined,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || `Failed to ${action.toLowerCase()} quarantine item`);
      const msg = `Quarantine #${inboxId} resolved (${body.status}).`;
      setFeedback(msg);
      onNotify?.(msg);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Resolution error');
    } finally {
      setBusyId(null);
    }
  };

  const handleSaveMapping = async (e: React.FormEvent) => {
    e.preventDefault();
    setMappingBusy(true);
    setError('');
    setFeedback('');
    try {
      const res = await apiFetch(`${api}/api/v1/catalogue/mappings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_system: sourceSystem.trim(),
          source_code: sourceCode.trim(),
          source_description: sourceDescription.trim() || undefined,
          medicine_concept_id: Number(conceptId),
          approval_status: approvalStatus,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to save catalogue mapping');
      const msg = `Saved mapping ${body.source_system}:${body.source_code} (${body.approval_status}).`;
      setFeedback(msg);
      onNotify?.(msg);
      setSourceCode('');
      setSourceDescription('');
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Mapping save failed');
    } finally {
      setMappingBusy(false);
    }
  };

  const formatDate = (val?: string | null) => (val ? new Date(val).toLocaleString() : '—');

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="pageTitle">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h1>Integration Quarantine & Approved Catalogue</h1>
          <p>
            Inbound partner payloads containing unknown facility or antibiotic codes are quarantined rather than
            auto-created. Approve canonical code mappings first, then replay or reject held messages.
          </p>
        </div>
        <button type="button" onClick={loadData} disabled={loading} className="sourceBadge" style={{ cursor: 'pointer' }}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} />
          {loading ? 'Refreshing…' : `${items.length} ${statusFilter.toLowerCase()} · ${mappings.length} mappings`}
        </button>
      </div>

      {feedback && (
        <div className="result successBox" style={{ marginTop: 0 }}>
          <CheckCircle2 size={16} />
          <div>
            <b>Action recorded</b>
            <span>{feedback}</span>
          </div>
        </div>
      )}

      {error && (
        <div className="result errorBox" style={{ marginTop: 0 }}>
          <AlertTriangle size={16} />
          <div>
            <b>Operation error</b>
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Quarantine Queue */}
      <section className="panel">
        <div className="panelHead">
          <div>
            <span className="eyebrow">INTEGRATION INBOX QUARANTINE</span>
            <h2>Held Inbound Partner Payloads</h2>
          </div>
          <div className="filterChips">
            {(['QUARANTINED', 'PROCESSED', 'REJECTED'] as const).map((st) => (
              <button
                key={st}
                type="button"
                className={statusFilter === st ? 'primary' : ''}
                onClick={() => setStatusFilter(st)}
              >
                {st}
              </button>
            ))}
          </div>
        </div>

        <div style={{ marginTop: 14, display: 'grid', gap: 10 }}>
          {items.length ? (
            items.map((item) => (
              <div
                key={item.id}
                className={`reviewItem ${item.status === 'QUARANTINED' ? 'reviewPending' : ''}`}
                style={{ gridTemplateColumns: '1fr', gap: 8 }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className="statusPill">{item.status}</span>
                    <strong>
                      #{item.id} · {item.source_system} · {item.event_type}
                    </strong>
                    <code>{item.external_id}</code>
                  </div>
                  <small>{formatDate(item.created_at)}</small>
                </div>

                <div style={{ fontSize: '12px', color: 'var(--ink)' }}>
                  <ShieldAlert size={13} style={{ verticalAlign: 'middle', marginRight: 5, color: 'var(--amber)' }} />
                  {item.quarantine_reason}
                  {item.unresolved_code && (
                    <>
                      {' '}
                      · Unresolved code: <code>{item.unresolved_code}</code>
                    </>
                  )}
                </div>

                {item.resolution_notes && (
                  <small>
                    Resolution notes: <b>{item.resolution_notes}</b> ({formatDate(item.resolved_at)})
                  </small>
                )}

                {item.status === 'QUARANTINED' && (
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 4 }}>
                    <input
                      type="text"
                      placeholder="Resolution notes (e.g. mapped AMX_LOCAL -> AMX500CAP)…"
                      value={notesById[item.id] || ''}
                      onChange={(e) => setNotesById((prev) => ({ ...prev, [item.id]: e.target.value }))}
                      style={{ flex: '1 1 260px', padding: '7px 10px', border: '1px solid var(--line)', borderRadius: 6 }}
                    />
                    <button
                      type="button"
                      className="primary"
                      disabled={busyId === item.id}
                      onClick={() => resolveEntry(item.id, 'REPLAY')}
                      style={{ minHeight: 34, padding: '0 12px', display: 'inline-flex', alignItems: 'center', gap: 6 }}
                    >
                      <RotateCcw size={13} /> Replay Payload
                    </button>
                    <button
                      type="button"
                      disabled={busyId === item.id}
                      onClick={() => resolveEntry(item.id, 'REJECT')}
                      style={{
                        minHeight: 34,
                        padding: '0 12px',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 6,
                        border: '1px solid #ebc6bd',
                        borderRadius: 6,
                        background: '#fbefec',
                        color: '#a34d46',
                      }}
                    >
                      <XCircle size={13} /> Reject
                    </button>
                  </div>
                )}
              </div>
            ))
          ) : (
            <div className="emptyState">
              <span>
                <Inbox size={22} />
              </span>
              <strong>No {statusFilter.toLowerCase()} payloads in inbox</strong>
              <p>
                Partner prescriptions or RMS stock events with unrecognized facility or antibiotic codes will appear
                here for controlled resolution.
              </p>
            </div>
          )}
        </div>
      </section>

      {/* Approved Catalogue Mappings */}
      <div className="twoCol" style={{ margin: 0, maxWidth: 'none' }}>
        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">APPROVED TERMINOLOGY MAPPINGS</span>
              <h2>Partner Code Register ({mappings.length})</h2>
            </div>
            <BookOpen size={18} />
          </div>

          <div style={{ marginTop: 12, maxHeight: 340, overflowY: 'auto' }}>
            {mappings.length ? (
              <table className="dataTable">
                <thead>
                  <tr>
                    <th>Partner</th>
                    <th>Source Code</th>
                    <th>Concept ID</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {mappings.map((m) => (
                    <tr key={m.id}>
                      <td>{m.source_system}</td>
                      <td>
                        <code>{m.source_code}</code>
                        {m.source_description && (
                          <div style={{ fontSize: 10, color: 'var(--muted)' }}>{m.source_description}</div>
                        )}
                      </td>
                      <td>#{m.medicine_concept_id}</td>
                      <td>
                        <span className={`statusPill ${m.approval_status === 'APPROVED' ? 'success' : ''}`}>
                          {m.approval_status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="emptyState">
                <span>
                  <BookOpen size={22} />
                </span>
                <strong>No partner code overrides registered</strong>
                <p>Canonical antibiotic codes (e.g. AMX500CAP) match directly; partner aliases can be mapped here.</p>
              </div>
            )}
          </div>
        </section>

        <section className="panel">
          <span className="eyebrow">CATALOGUE GOVERNANCE ACTION</span>
          <h2>Register or Approve Code Mapping</h2>
          <p className="muted" style={{ marginBottom: 12 }}>
            Bind an external EMR/RMS medicine code to an approved canonical <code>MedicineConcept</code> ID.
          </p>

          <form onSubmit={handleSaveMapping} className="reviewForm" style={{ background: 'transparent', padding: 0, border: 0 }}>
            <label>
              Source Partner System
              <input
                required
                value={sourceSystem}
                onChange={(e) => setSourceSystem(e.target.value)}
                placeholder="e.g. e-Buzima, OpenMRS, RMS"
              />
            </label>
            <label>
              External Source Code
              <input
                required
                value={sourceCode}
                onChange={(e) => setSourceCode(e.target.value)}
                placeholder="e.g. EBZ-AMOX-500"
              />
            </label>
            <label>
              Description (Optional)
              <input
                value={sourceDescription}
                onChange={(e) => setSourceDescription(e.target.value)}
                placeholder="Partner formulary label"
              />
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <label>
                Canonical Concept ID
                <input
                  required
                  type="number"
                  min={1}
                  value={conceptId}
                  onChange={(e) => setConceptId(Number(e.target.value))}
                />
              </label>
              <label>
                Approval Status
                <select
                  value={approvalStatus}
                  onChange={(e) => setApprovalStatus(e.target.value as 'APPROVED' | 'PENDING' | 'REJECTED')}
                >
                  <option value="APPROVED">APPROVED</option>
                  <option value="PENDING">PENDING</option>
                  <option value="REJECTED">REJECTED</option>
                </select>
              </label>
            </div>
            <button className="primary full" type="submit" disabled={mappingBusy}>
              <Plus size={15} />
              {mappingBusy ? 'Saving mapping…' : 'Save Catalogue Mapping'}
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}
