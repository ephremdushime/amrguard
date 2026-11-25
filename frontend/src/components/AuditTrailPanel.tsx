import React, { useCallback, useEffect, useState } from 'react';
import { LockKeyhole, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { apiFetch } from '../authApi';
import type { AuditEventItem } from '../types';

interface AuditTrailPanelProps {
  api: string;
  scopeMode: 'facility' | 'technical';
  eyebrow?: string;
  title?: string;
}

export function AuditTrailPanel({
  api,
  scopeMode,
  eyebrow = 'APPEND-ONLY AUDIT TRAIL',
  title = 'Accountability & Security Event Ledger',
}: AuditTrailPanelProps) {
  const [events, setEvents] = useState<AuditEventItem[]>([]);
  const [search, setSearch] = useState('');
  const [outcomeFilter, setOutcomeFilter] = useState<'ALL' | 'SUCCESS' | 'DENIED'>('ALL');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadAudit = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch(`${api}/api/v1/audit?limit=100`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || 'Unable to load audit events');
      }
      setEvents(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load audit events');
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    loadAudit();
  }, [loadAudit]);

  const filtered = events.filter((ev) => {
    if (outcomeFilter !== 'ALL' && (ev.outcome || 'SUCCESS') !== outcomeFilter) return false;
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      ev.event_type.toLowerCase().includes(q) ||
      ev.entity_type.toLowerCase().includes(q) ||
      ev.entity_id.toLowerCase().includes(q) ||
      (ev.actor_id || '').toLowerCase().includes(q) ||
      (ev.correlation_id || '').toLowerCase().includes(q) ||
      ev.source_system.toLowerCase().includes(q)
    );
  });

  return (
    <section className="panel">
      <div className="panelHead">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h2>
            {title} ({filtered.length})
          </h2>
        </div>
        <button type="button" onClick={loadAudit} disabled={loading}>
          <RefreshCw size={13} className={loading ? 'spin' : ''} />
          {loading ? 'Refreshing…' : 'Refresh Log'}
        </button>
      </div>

      <div className="notice" style={{ marginTop: 10 }}>
        <LockKeyhole size={15} />
        <span>
          {scopeMode === 'technical'
            ? 'Platform Operator Boundary: Backend strictly restricts this feed to technical & security entities (Authentication, UserSession, ServiceClient, Endpoint). Zero clinical patient records are exposed.'
            : 'Facility Tenancy Boundary: Backend strictly filters audit records to your authorized facility scope. Protected by append-only ORM and PostgreSQL trigger immutability controls.'}
        </span>
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 14, alignItems: 'center' }}>
        <div style={{ position: 'relative', flex: '1 1 260px' }}>
          <Search size={14} style={{ position: 'absolute', left: 10, top: 11, color: 'var(--muted)' }} />
          <input
            type="text"
            placeholder="Filter by event type, actor, entity, correlation ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: '100%', padding: '8px 10px 8px 30px', border: '1px solid var(--line)', borderRadius: 6 }}
          />
        </div>
        <div className="filterChips">
          {(['ALL', 'SUCCESS', 'DENIED'] as const).map((out) => (
            <button
              key={out}
              type="button"
              className={outcomeFilter === out ? 'primary' : ''}
              onClick={() => setOutcomeFilter(out)}
            >
              {out}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="result errorBox">
          <div>
            <b>Audit access notice</b>
            <span>{error}</span>
          </div>
        </div>
      )}

      <div style={{ marginTop: 14, maxHeight: 460, overflowY: 'auto' }}>
        {filtered.length ? (
          <table className="dataTable">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Event</th>
                <th>Entity</th>
                <th>Actor</th>
                <th>Outcome</th>
                <th>Correlation ID</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((ev) => (
                <tr key={ev.id}>
                  <td style={{ whiteSpace: 'nowrap' }}>{new Date(ev.created_at).toLocaleString()}</td>
                  <td>
                    <strong>{ev.event_type}</strong>
                    <div style={{ fontSize: 10, color: 'var(--muted)' }}>{ev.source_system}</div>
                  </td>
                  <td>
                    {ev.entity_type} <code>#{ev.entity_id}</code>
                  </td>
                  <td>
                    <span>{ev.actor_id || 'SYSTEM'}</span>
                    {ev.actor_type && <div style={{ fontSize: 10, color: 'var(--muted)' }}>{ev.actor_type}</div>}
                  </td>
                  <td>
                    <span className={`statusPill ${(ev.outcome || 'SUCCESS') === 'SUCCESS' ? 'success' : 'dangerPill'}`}>
                      {ev.outcome || 'SUCCESS'}
                    </span>
                  </td>
                  <td>
                    <code>{ev.correlation_id ? ev.correlation_id.slice(0, 12) : '—'}</code>
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
            <strong>No matching audit records</strong>
            <p>All authentication, authorization, prescribing, dispensing, and governance events are captured here.</p>
          </div>
        )}
      </div>
    </section>
  );
}
