import React, { useEffect, useState } from 'react';
import { Activity, ArrowRight, Clock3, GitBranch, PackageSearch, RefreshCw, ShieldCheck } from 'lucide-react';
import { apiFetch } from '../authApi';
import type { OperationalBatch, OperationalTransaction, TraceResponse } from '../types';

interface TraceabilityViewProps {
  api: string;
  batches: OperationalBatch[];
  transactions: OperationalTransaction[];
}

export function TraceabilityView({ api, batches, transactions }: TraceabilityViewProps) {
  const [selectedBatchId, setSelectedBatchId] = useState<number>(batches[0]?.id || 0);
  const [trace, setTrace] = useState<TraceResponse | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!selectedBatchId) {
      setTrace(null);
      return;
    }
    let cancelled = false;
    setBusy(true);
    setError('');

    apiFetch(`${api}/api/v1/traceability/batches/${selectedBatchId}`)
      .then(async (res) => {
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail || 'Unable to load batch history');
        return body as TraceResponse;
      })
      .then((data) => {
        if (!cancelled) setTrace(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });

    return () => {
      cancelled = true;
    };
  }, [api, selectedBatchId]);

  const selectedBatch = batches.find((b) => b.id === selectedBatchId);
  const formatDate = (val?: string | null) => (val ? new Date(val).toLocaleString() : 'Not set');

  return (
    <>
      <div className="pageTitle">
        <div>
          <span className="eyebrow">ANTIBIOTIC TRACEABILITY</span>
          <h1>Batch and transaction history</h1>
          <p>
            Trace each antibiotic batch from central medical store reference through pharmacy stock movements and
            patient dispensing transactions.
          </p>
        </div>
        <span className="sourceBadge">
          <PackageSearch size={15} /> {batches.length} tracked batches
        </span>
      </div>

      <div className="traceToolbar panel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <label style={{ margin: 0, flex: 1, maxWidth: 480 }}>
          Select Antibiotic Batch
          <select
            value={selectedBatchId || ''}
            onChange={(e) => setSelectedBatchId(Number(e.target.value))}
          >
            <option value="">Choose a batch to trace…</option>
            {batches.map((item) => (
              <option key={item.id} value={item.id}>
                {item.batch_number} · {item.antibiotic} ({item.strength}) · {item.pharmacy_name} ·{' '}
                {item.quantity_available} available
              </option>
            ))}
          </select>
        </label>
        <div className="traceToolbarMeta">
          <span className="eyebrow">DISPENSING TRANSACTIONS</span>
          <strong>{transactions.length}</strong>
        </div>
      </div>

      {!batches.length && (
        <div className="panel">
          <div className="emptyState">
            <span>
              <PackageSearch size={28} />
            </span>
            <strong>No stock batches synchronized</strong>
            <p>
              The RMS/eLMIS stock adapter has not supplied batch records yet. Once synchronized, batch expiry, source
              references, and dispensing links will appear here.
            </p>
          </div>
        </div>
      )}

      {error && <div className="notice">{error}</div>}
      {busy && (
        <div className="panel" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <RefreshCw size={18} className="spin" /> Loading batch transaction history…
        </div>
      )}

      {trace && selectedBatch && (
        <>
          <section className="traceSummary panel">
            <div>
              <span className="eyebrow">{trace.batch.batch_number}</span>
              <h2>
                {trace.batch.antibiotic} {trace.batch.strength}
              </h2>
              <p>
                Pharmacy: <b>{trace.batch.pharmacy}</b> (Code: {selectedBatch.pharmacy_code})
              </p>
            </div>
            <div className="traceFacts">
              <div>
                <span>Available Units</span>
                <b>{trace.batch.current_quantity}</b>
              </div>
              <div>
                <span>Batch Expiry</span>
                <b>{formatDate(trace.batch.expiry_date)}</b>
              </div>
              <div>
                <span>Origin Reference</span>
                <b>{trace.batch.source_reference || 'Not provided'}</b>
              </div>
            </div>
          </section>

          <section className="panel traceEvents">
            <div className="panelHead">
              <div>
                <span className="eyebrow">BATCH EVENT LEDGER</span>
                <h2>Supply, stock and movement events</h2>
              </div>
              <Activity size={18} />
            </div>
            {trace.events.length ? (
              trace.events.map((event, index) => (
                <div className="eventRow" key={`${event.type}-${event.reference}-${index}`}>
                  <span className="timelineDot">{index + 1}</span>
                  <div>
                    <strong>{event.type.replaceAll('_', ' ')}</strong>
                    <small>
                      Source: {event.source} · {formatDate(event.created_at)}
                    </small>
                  </div>
                  <b>
                    {event.quantity > 0 ? '+' : ''}
                    {event.quantity}
                  </b>
                  <code>{event.reference || '—'}</code>
                </div>
              ))
            ) : (
              <div className="emptyState">
                <span>
                  <Clock3 size={24} />
                </span>
                <strong>Batch registered; no movement events yet</strong>
                <p>Receipt, adjustment and dispensing events will accumulate here as connected systems report them.</p>
              </div>
            )}
          </section>

          <section className="panel traceEvents">
            <div className="panelHead">
              <div>
                <span className="eyebrow">PRESCRIPTION LINKS</span>
                <h2>{trace.linked_transactions.length} linked dispenses</h2>
              </div>
            </div>
            {trace.linked_transactions.length ? (
              trace.linked_transactions.map((link) => (
                <div className="eventRow linkedRow" key={link.transaction_id}>
                  <span className="statusPill success">{link.status}</span>
                  <div>
                    <strong>{link.prescription_code}</strong>
                    <small>
                      Source {link.external_id} · {formatDate(link.created_at)}
                    </small>
                  </div>
                  <b>{link.quantity} units</b>
                  <code>{link.transaction_id}</code>
                </div>
              ))
            ) : (
              <div className="emptyState">
                <span>
                  <ArrowRight size={24} />
                </span>
                <strong>No dispenses linked to this batch</strong>
                <p>A prescription and recorded dispense will automatically create the cross-system trace link.</p>
              </div>
            )}
          </section>
        </>
      )}

      <section className="panel transactionList">
        <div className="panelHead">
          <div>
            <span className="eyebrow">RECENT DISPENSING</span>
            <h2>Transaction register</h2>
          </div>
        </div>
        {transactions.length ? (
          transactions.map((tx) => (
            <div className="eventRow" key={tx.transaction_id}>
              <span className="statusPill success">{tx.status}</span>
              <div>
                <strong>{tx.prescription_code || `Prescription ${tx.prescription_id}`}</strong>
                <small>
                  Pharmacy {tx.pharmacy_id} · Batch {tx.batch_id} · {formatDate(tx.created_at)}
                </small>
              </div>
              <b>{tx.quantity} units</b>
              <code>{tx.transaction_id}</code>
            </div>
          ))
        ) : (
          <p className="muted">No dispensing transactions have been recorded yet.</p>
        )}
      </section>
    </>
  );
}
