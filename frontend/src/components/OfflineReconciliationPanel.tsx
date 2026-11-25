import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, CloudOff, RefreshCw, RotateCw, ShieldCheck } from 'lucide-react';
import { apiFetch } from '../authApi';
import type { OfflineDispenseItem } from '../types';

interface OfflineReconciliationPanelProps {
  api: string;
  canReconcile: boolean;
  pharmacyId?: number;
  eyebrow?: string;
  title?: string;
  onNotify?: (msg: string) => void;
}

export function OfflineReconciliationPanel({
  api,
  canReconcile,
  pharmacyId,
  eyebrow = 'P3-02 POLICY-BOUND OFFLINE DISPENSING QUEUE',
  title = 'Offline Bundles & Central Reconciliation',
  onNotify,
}: OfflineReconciliationPanelProps) {
  const [records, setRecords] = useState<OfflineDispenseItem[]>([]);
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'PENDING' | 'RECONCILED' | 'CONFLICT' | 'REJECTED'>('ALL');
  const [loading, setLoading] = useState(false);
  const [busyBundle, setBusyBundle] = useState<string | null>(null);
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ limit: '100' });
      if (pharmacyId) params.set('pharmacy_id', String(pharmacyId));
      if (statusFilter !== 'ALL') params.set('status', statusFilter);
      const res = await apiFetch(`${api}/api/v1/dispensing/offline-queue?${params.toString()}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || 'Unable to load offline queue');
      }
      setRecords(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load offline queue');
      setRecords([]);
    } finally {
      setLoading(false);
    }
  }, [api, pharmacyId, statusFilter]);

  useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  const handleReconcile = async (bundleId: string) => {
    setBusyBundle(bundleId);
    setError('');
    setFeedback('');
    try {
      const res = await apiFetch(`${api}/api/v1/dispensing/offline-reconcile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bundle_id: bundleId }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Reconciliation failed');
      const msg =
        body.status === 'RECONCILED'
          ? `Bundle ${bundleId} reconciled into transaction ${body.transaction_id}.`
          : `Bundle ${bundleId} flagged ${body.status}: ${body.conflict_reason || 'See details'}.`;
      setFeedback(msg);
      onNotify?.(msg);
      await loadQueue();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reconciliation error');
    } finally {
      setBusyBundle(null);
    }
  };

  const pendingCount = records.filter((r) => r.status === 'PENDING').length;
  const conflictCount = records.filter((r) => r.status === 'CONFLICT').length;

  return (
    <section className="panel">
      <div className="panelHead">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h2>{title}</h2>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <div className="filterChips">
            {(['ALL', 'PENDING', 'CONFLICT', 'RECONCILED', 'REJECTED'] as const).map((st) => (
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
          <button type="button" onClick={loadQueue} disabled={loading}>
            <RefreshCw size={13} className={loading ? 'spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      <p className="muted" style={{ marginTop: 8 }}>
        Signed offline bundles captured during facility network outages are verified via HMAC-SHA256 before central
        stock decrement, conflict detection (already dispensed / insufficient stock), and RMS outbox dispatch.
        {pendingCount > 0 || conflictCount > 0 ? (
          <>
            {' '}
            <strong>
              {pendingCount} pending · {conflictCount} conflict(s).
            </strong>
          </>
        ) : null}
      </p>

      {!canReconcile && (
        <div className="notice" style={{ marginTop: 10 }}>
          <ShieldCheck size={15} />
          <span>
            Read-only queue visibility: reconciling offline bundles into stock transactions requires{' '}
            <b>Pharmacist</b> or <b>Facility Admin</b> authority.
          </span>
        </div>
      )}

      {feedback && (
        <div className="result successBox">
          <CheckCircle2 size={16} />
          <div>
            <b>Reconciliation updated</b>
            <span>{feedback}</span>
          </div>
        </div>
      )}

      {error && (
        <div className="result errorBox">
          <AlertTriangle size={16} />
          <div>
            <b>Queue notice</b>
            <span>{error}</span>
          </div>
        </div>
      )}

      <div style={{ marginTop: 14 }}>
        {records.length ? (
          <table className="dataTable">
            <thead>
              <tr>
                <th>Bundle ID</th>
                <th>Offline Tx</th>
                <th>Pharmacy</th>
                <th>Status</th>
                <th>Conflict / Notes</th>
                <th>Created</th>
                {canReconcile && <th>Action</th>}
              </tr>
            </thead>
            <tbody>
              {records.map((rec) => (
                <tr key={rec.id}>
                  <td>
                    <code>{rec.bundle_id}</code>
                  </td>
                  <td>
                    <code>{rec.offline_transaction_id}</code>
                  </td>
                  <td>Pharmacy #{rec.pharmacy_id}</td>
                  <td>
                    <span className={`statusPill ${rec.status === 'RECONCILED' ? 'success' : ''}`}>
                      {rec.status}
                    </span>
                  </td>
                  <td>{rec.conflict_reason || '—'}</td>
                  <td>{new Date(rec.created_at).toLocaleString()}</td>
                  {canReconcile && (
                    <td>
                      {rec.status === 'PENDING' ? (
                        <button
                          type="button"
                          className="primary"
                          disabled={busyBundle === rec.bundle_id}
                          onClick={() => handleReconcile(rec.bundle_id)}
                          style={{ minHeight: 30, padding: '0 10px', display: 'inline-flex', alignItems: 'center', gap: 5 }}
                        >
                          <RotateCw size={12} className={busyBundle === rec.bundle_id ? 'spin' : ''} />
                          Reconcile
                        </button>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="emptyState">
            <span>
              <CloudOff size={22} />
            </span>
            <strong>No offline dispensing bundles queued</strong>
            <p>
              Offline bundles uploaded via <code>POST /api/v1/dispensing/offline-queue</code> appear here for atomic
              reconciliation when connectivity returns.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
