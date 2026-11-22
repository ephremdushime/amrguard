import React, { useState, useEffect } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Layers,
  PackageSearch,
  ScanLine,
  ShieldCheck,
  Split,
  Truck,
  XCircle,
} from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import type { BatchAllocation, OperationalBatch, OperationalRx, Pharmacy } from '../types';

interface DispensingWorkstationProps {
  rx: OperationalRx | null;
  pharmacies: Pharmacy[];
  currentPharmacyId: number;
  onPharmacyChange: (id: number) => void;
  batches: OperationalBatch[];
  dispensedByItem: Record<number, number>;
  credential: string;
  otp: string;
  onOtpChange: (otp: string) => void;
  onCredentialChange: (cred: string) => void;
  isVerified: boolean;
  onVerify: () => Promise<void>;
  onIssueCredential: () => Promise<void>;
  onDispense: (payload: {
    itemId: number;
    pharmacyId: number;
    allocations: BatchAllocation[];
    outcome: 'FULL' | 'PARTIAL' | 'REFUSED' | 'UNAVAILABLE';
    refusalReason?: string;
  }) => Promise<void>;
  busy: boolean;
}

export function DispensingWorkstation({
  rx,
  pharmacies,
  currentPharmacyId,
  onPharmacyChange,
  batches,
  dispensedByItem,
  credential,
  otp,
  onOtpChange,
  onCredentialChange,
  isVerified,
  onVerify,
  onIssueCredential,
  onDispense,
  busy,
}: DispensingWorkstationProps) {
  const [selectedItemId, setSelectedItemId] = useState<number>(0);
  const [useSplitBatches, setUseSplitBatches] = useState(false);
  const [singleBatchId, setSingleBatchId] = useState<number>(0);
  const [singleQty, setSingleQty] = useState<number>(1);
  const [splitAllocations, setSplitAllocations] = useState<Record<number, number>>({});
  const [outcome, setOutcome] = useState<'FULL' | 'PARTIAL' | 'REFUSED' | 'UNAVAILABLE'>('FULL');
  const [refusalReason, setRefusalReason] = useState('');
  const [errorNotice, setErrorNotice] = useState('');

  // Keep selected item valid when rx changes
  useEffect(() => {
    if (rx && rx.items.length > 0) {
      if (!selectedItemId || !rx.items.some((i) => i.id === selectedItemId)) {
        setSelectedItemId(rx.items[0].id);
      }
    }
  }, [rx, selectedItemId]);

  if (!rx) {
    return (
      <section className="panel operationsDetail">
        <div className="emptyState">
          <span>
            <PackageSearch size={28} />
          </span>
          <strong>Select a prescription order</strong>
          <p>
            Choose an incoming order from the queue to verify credentials, allocate matching batches, and record
            authorized dispensing.
          </p>
        </div>
      </section>
    );
  }

  const selectedItem = rx.items.find((i) => i.id === selectedItemId) || rx.items[0];
  const itemDispensed = (selectedItem ? dispensedByItem[selectedItem.id] : 0) || 0;
  const itemAuthorized = selectedItem ? selectedItem.authorized_quantity : 0;
  const itemRemaining = Math.max(0, itemAuthorized - itemDispensed);

  // Filter matching stock batches for this item at the selected pharmacy
  const matchingBatches = batches.filter(
    (b) =>
      b.pharmacy_id === currentPharmacyId &&
      selectedItem &&
      b.antibiotic_code === selectedItem.code &&
      b.quantity_available > 0,
  );

  // Default single batch to the first matching batch with stock
  useEffect(() => {
    if (matchingBatches.length > 0) {
      if (!singleBatchId || !matchingBatches.some((b) => b.id === singleBatchId)) {
        setSingleBatchId(matchingBatches[0].id);
        setSingleQty(Math.min(itemRemaining, matchingBatches[0].quantity_available));
      }
    } else {
      setSingleBatchId(0);
      setSingleQty(0);
    }
  }, [matchingBatches, itemRemaining, singleBatchId]);

  const handleSplitQtyChange = (batchId: number, val: number) => {
    setSplitAllocations((prev) => ({
      ...prev,
      [batchId]: Math.max(0, val),
    }));
  };

  const calculatedTotalAllocated = useSplitBatches
    ? Object.entries(splitAllocations).reduce((sum, [, q]) => sum + (q || 0), 0)
    : outcome === 'REFUSED' || outcome === 'UNAVAILABLE'
      ? 0
      : singleQty;

  const handleSubmitDispense = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorNotice('');

    if (!selectedItem) {
      setErrorNotice('No prescription item selected');
      return;
    }

    if (!isVerified) {
      setErrorNotice('Prescription credential must be verified before dispensing.');
      return;
    }

    if (outcome === 'REFUSED' || outcome === 'UNAVAILABLE') {
      if (!refusalReason.trim()) {
        setErrorNotice('Please provide a reason for the refusal or stock unavailability.');
        return;
      }
      await onDispense({
        itemId: selectedItem.id,
        pharmacyId: currentPharmacyId,
        allocations: [],
        outcome,
        refusalReason: refusalReason.trim(),
      });
      return;
    }

    let finalAllocations: BatchAllocation[] = [];
    if (useSplitBatches) {
      finalAllocations = Object.entries(splitAllocations)
        .filter(([, q]) => q > 0)
        .map(([bId, q]) => ({ batch_id: Number(bId), quantity: q }));

      if (finalAllocations.length === 0) {
        setErrorNotice('Please allocate at least 1 unit across available batches.');
        return;
      }
    } else {
      if (!singleBatchId || singleQty <= 0) {
        setErrorNotice('Please select a valid batch and enter quantity to dispense.');
        return;
      }
      finalAllocations = [{ batch_id: singleBatchId, quantity: singleQty }];
    }

    if (calculatedTotalAllocated > itemRemaining) {
      setErrorNotice(
        `Allocated quantity (${calculatedTotalAllocated}) exceeds item remaining authorization (${itemRemaining}).`,
      );
      return;
    }

    await onDispense({
      itemId: selectedItem.id,
      pharmacyId: currentPharmacyId,
      allocations: finalAllocations,
      outcome,
    });
  };

  const isEligibleForDispense = ['VALIDATED', 'ACTIVE', 'PARTIALLY_DISPENSED', 'WARNING'].includes(rx.status);

  return (
    <div className="dispensingWorkstation panel" style={{ display: 'grid', gap: 16 }}>
      {/* Header & Status */}
      <div className="panelHead" style={{ borderBottom: '1px solid var(--border)', paddingBottom: 12 }}>
        <div>
          <span className="eyebrow">PHARMACY DISPENSING WORKSTATION</span>
          <h2>
            Prescription: <b>{rx.code}</b>
          </h2>
          <small className="muted">
            Patient Ref: <b>{rx.patient_reference}</b> · Origin Facility: <b>{rx.facility.name}</b>
          </small>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className={`statusPill status-${rx.status.toLowerCase()}`}>{rx.status}</span>
        </div>
      </div>

      {/* Multi-Item Selector & Breakdown */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <span className="eyebrow" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Layers size={13} /> PRESCRIPTION ITEMS ({rx.items.length})
          </span>
          <small className="muted">Click an item below to select for dispensing</small>
        </div>

        <div className="itemBreakdownGrid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 10 }}>
          {rx.items.map((it) => {
            const itDisp = dispensedByItem[it.id] || 0;
            const itRem = Math.max(0, it.authorized_quantity - itDisp);
            const isSelected = it.id === selectedItemId;

            return (
              <button
                type="button"
                key={it.id}
                className={`itemCard ${isSelected ? 'activeItemCard' : ''}`}
                onClick={() => setSelectedItemId(it.id)}
                style={{
                  padding: '10px 14px',
                  borderRadius: 8,
                  border: isSelected ? '2px solid var(--primary, #3b82f6)' : '1px solid var(--border)',
                  background: isSelected ? 'var(--primary-subtle, #f0f7ff)' : 'var(--bg-panel)',
                  textAlign: 'left',
                  cursor: 'pointer',
                  display: 'grid',
                  gap: 4,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <strong style={{ fontSize: '14px' }}>{it.antibiotic}</strong>
                  <span
                    style={{
                      fontSize: '11px',
                      fontWeight: 600,
                      padding: '2px 6px',
                      borderRadius: 4,
                      background: itRem === 0 ? '#10b98120' : '#3b82f620',
                      color: itRem === 0 ? '#059669' : '#2563eb',
                    }}
                  >
                    {itRem === 0 ? 'COMPLETED' : `${itRem} left`}
                  </span>
                </div>

                <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  {it.strength} · {it.formulation} · {it.route}
                </div>

                <div style={{ fontSize: '11px', color: 'var(--muted)', display: 'flex', gap: 12, marginTop: 4 }}>
                  <span>Auth: <b>{it.authorized_quantity}</b></span>
                  <span>Dispensed: <b>{itDisp}</b></span>
                  <span>Remain: <b>{itRem}</b></span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Credential Verification Strip */}
      <div
        className="credentialStrip"
        style={{
          background: isVerified ? '#ecfdf5' : '#fffbeb',
          border: `1px solid ${isVerified ? '#a7f3d0' : '#fde68a'}`,
          borderRadius: 8,
          padding: '12px 16px',
          display: 'grid',
          gridTemplateColumns: 'auto 1fr auto',
          gap: 16,
          alignItems: 'center',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {isVerified ? (
            <CheckCircle2 size={24} style={{ color: '#059669' }} />
          ) : (
            <Clock3 size={24} style={{ color: '#d97706' }} />
          )}
          <div>
            <div style={{ fontWeight: 600, fontSize: '14px', color: isVerified ? '#065f46' : '#92400e' }}>
              {isVerified ? 'Prescription Credential Verified' : 'Credential Verification Required'}
            </div>
            <small style={{ color: isVerified ? '#047857' : '#b45309' }}>
              {isVerified
                ? 'Authorized for dispensing by logged-in pharmacist.'
                : 'Enter patient OTP or scan QR token to unlock dispensing.'}
            </small>
          </div>
        </div>

        {!isVerified && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input
              type="text"
              maxLength={6}
              placeholder="6-digit OTP"
              value={otp}
              onChange={(e) => onOtpChange(e.target.value.replace(/\D/g, ''))}
              style={{ width: 110, textAlign: 'center', fontWeight: 'bold', letterSpacing: 2 }}
            />
            <input
              type="text"
              placeholder="Or paste QR token"
              value={credential}
              onChange={(e) => onCredentialChange(e.target.value)}
              style={{ width: 140 }}
            />
            <button
              type="button"
              className="primary"
              onClick={onVerify}
              disabled={busy || (!otp && !credential)}
              style={{ padding: '6px 12px', fontSize: '13px' }}
            >
              <ScanLine size={14} /> Verify
            </button>
          </div>
        )}

        {isEligibleForDispense && !isVerified && !credential && !otp && (
          <button
            type="button"
            className="secondary"
            onClick={onIssueCredential}
            disabled={busy}
            style={{ fontSize: '12px', padding: '6px 10px' }}
          >
            Generate QR / OTP
          </button>
        )}

        {credential && !isVerified && (
          <div style={{ padding: 4, background: '#fff', borderRadius: 4, border: '1px solid #e2e8f0' }}>
            <QRCodeSVG value={credential} size={48} />
          </div>
        )}
      </div>

      {/* Dispensing Action Form */}
      <form onSubmit={handleSubmitDispense} style={{ display: 'grid', gap: 14 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
          {/* Pharmacy Location */}
          <label>
            Dispensing Pharmacy Location
            <select
              value={currentPharmacyId}
              onChange={(e) => onPharmacyChange(Number(e.target.value))}
              disabled={busy}
            >
              {pharmacies
                .filter((p) => p.active)
                .map((loc) => (
                  <option key={loc.id} value={loc.id}>
                    {loc.name} ({loc.district})
                  </option>
                ))}
            </select>
          </label>

          {/* Outcome Selector */}
          <label>
            Dispensing Outcome
            <select
              value={outcome}
              onChange={(e) => setOutcome(e.target.value as 'FULL' | 'PARTIAL' | 'REFUSED' | 'UNAVAILABLE')}
              disabled={busy}
            >
              <option value="FULL">Fulfill Item (Full / Balance)</option>
              <option value="PARTIAL">Partial Fulfillment</option>
              <option value="REFUSED">Exception: Patient Refused</option>
              <option value="UNAVAILABLE">Exception: Stock Unavailable</option>
            </select>
          </label>
        </div>

        {/* Exception Reason Input */}
        {(outcome === 'REFUSED' || outcome === 'UNAVAILABLE') && (
          <label style={{ background: '#fef2f2', padding: 12, borderRadius: 6, border: '1px solid #fecaca' }}>
            <span style={{ color: '#991b1b', fontWeight: 600 }}>Reason for Refusal or Unavailability</span>
            <input
              required
              type="text"
              placeholder="Document the clinical reason or stock deficit details…"
              value={refusalReason}
              onChange={(e) => setRefusalReason(e.target.value)}
              style={{ marginTop: 6 }}
            />
          </label>
        )}

        {/* Stock Allocation Section */}
        {outcome !== 'REFUSED' && outcome !== 'UNAVAILABLE' && (
          <div className="stockAllocationPanel panel" style={{ background: 'var(--bg-subtle, #f8fafc)', padding: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <div>
                <strong style={{ fontSize: '13px' }}>Batch Allocation & Depletion</strong>
                <p className="muted" style={{ margin: 0, fontSize: '11px' }}>
                  Available in-date batches for <b>{selectedItem?.antibiotic} {selectedItem?.strength}</b> at this location.
                </p>
              </div>

              {matchingBatches.length > 1 && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setUseSplitBatches(!useSplitBatches)}
                  style={{ fontSize: '11px', padding: '4px 8px', display: 'flex', alignItems: 'center', gap: 4 }}
                >
                  <Split size={12} />
                  {useSplitBatches ? 'Switch to Single Batch' : 'Split Across Multiple Batches'}
                </button>
              )}
            </div>

            {matchingBatches.length === 0 ? (
              <div className="notice" style={{ margin: 0 }}>
                <AlertTriangle size={16} />
                <span>No available in-date stock batches found for this antibiotic at the selected pharmacy.</span>
              </div>
            ) : useSplitBatches ? (
              /* Multi-Batch Split Table */
              <div style={{ display: 'grid', gap: 8 }}>
                <table style={{ width: '100%', fontSize: '12px', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)', textAlign: 'left', color: 'var(--muted)' }}>
                      <th style={{ padding: '6px 8px' }}>Batch Number</th>
                      <th style={{ padding: '6px 8px' }}>Expiry Date</th>
                      <th style={{ padding: '6px 8px' }}>Available</th>
                      <th style={{ padding: '6px 8px', width: 100 }}>Allocate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {matchingBatches.map((b) => (
                      <tr key={b.id} style={{ borderBottom: '1px solid var(--border)' }}>
                        <td style={{ padding: '6px 8px', fontWeight: 600 }}>{b.batch_number}</td>
                        <td style={{ padding: '6px 8px' }}>{b.expiry_date}</td>
                        <td style={{ padding: '6px 8px' }}>{b.quantity_available} units</td>
                        <td style={{ padding: '6px 8px' }}>
                          <input
                            type="number"
                            min={0}
                            max={Math.min(itemRemaining, b.quantity_available)}
                            value={splitAllocations[b.id] || 0}
                            onChange={(e) => handleSplitQtyChange(b.id, Number(e.target.value))}
                            style={{ width: 80, padding: '4px 6px', fontSize: '12px' }}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ textAlign: 'right', fontSize: '12px', fontWeight: 600 }}>
                  Total Allocated: <b style={{ color: calculatedTotalAllocated > itemRemaining ? '#ef4444' : '#10b981' }}>{calculatedTotalAllocated}</b> / {itemRemaining} remaining
                </div>
              </div>
            ) : (
              /* Single Batch Select */
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
                <label>
                  Stock Batch
                  <select
                    value={singleBatchId}
                    onChange={(e) => setSingleBatchId(Number(e.target.value))}
                  >
                    {matchingBatches.map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.batch_number} · {b.quantity_available} avail · Exp: {b.expiry_date}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Quantity to Dispense
                  <input
                    type="number"
                    min={1}
                    max={Math.min(
                      itemRemaining,
                      matchingBatches.find((b) => b.id === singleBatchId)?.quantity_available || 0,
                    )}
                    value={singleQty}
                    onChange={(e) => setSingleQty(Number(e.target.value))}
                  />
                </label>
              </div>
            )}
          </div>
        )}

        {/* Error notice */}
        {errorNotice && (
          <div className="result errorBox" style={{ margin: 0 }}>
            <XCircle size={16} />
            <div>
              <b>Dispensing blocked</b>
              <span>{errorNotice}</span>
            </div>
          </div>
        )}

        {/* Submit Button */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
          <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
            Authorizing staff: strictly recorded for batch audit and RMS reconciliation.
          </div>

          <button
            type="submit"
            className="primary"
            disabled={
              busy ||
              !isVerified ||
              itemRemaining === 0 ||
              (outcome !== 'REFUSED' && outcome !== 'UNAVAILABLE' && (matchingBatches.length === 0 || calculatedTotalAllocated <= 0 || calculatedTotalAllocated > itemRemaining))
            }
            style={{ padding: '8px 18px', fontSize: '14px' }}
          >
            <CheckCircle2 size={16} />
            {busy
              ? 'Authorizing Transaction…'
              : outcome === 'REFUSED' || outcome === 'UNAVAILABLE'
                ? 'Record Dispensing Exception'
                : `Authorize Dispense (${calculatedTotalAllocated} units)`}
          </button>
        </div>
      </form>
    </div>
  );
}
