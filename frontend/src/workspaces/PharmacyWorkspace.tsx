import React, { useCallback, useEffect, useState } from 'react';
import { Boxes, CheckCircle2, CloudOff, FileCheck2, ShieldCheck, Truck } from 'lucide-react';
import { apiFetch, type AuthUser } from '../authApi';
import { DispensingWorkstation } from '../components/DispensingWorkstation';
import { OfflineReconciliationPanel } from '../components/OfflineReconciliationPanel';
import { PrescriptionQueue } from '../components/PrescriptionQueue';
import { TraceabilityView } from '../components/TraceabilityView';
import type {
  BatchAllocation,
  OperationalBatch,
  OperationalRx,
  OperationalTransaction,
  Pharmacy,
} from '../types';

interface PharmacyWorkspaceProps {
  api: string;
  user: AuthUser;
  activeSection: string;
  refreshKey: number;
  onNotify: (message: string) => void;
  onUnauthorized: () => void;
}

export function PharmacyWorkspace({
  api,
  user,
  activeSection,
  refreshKey,
  onNotify,
  onUnauthorized,
}: PharmacyWorkspaceProps) {
  const isPharmacist = user.roles.includes('pharmacist');

  const [pharmacies, setPharmacies] = useState<Pharmacy[]>([]);
  const [currentPharmacyId, setCurrentPharmacyId] = useState<number>(0);
  const [prescriptions, setPrescriptions] = useState<OperationalRx[]>([]);
  const [selectedRx, setSelectedRx] = useState<OperationalRx | null>(null);
  const [batches, setBatches] = useState<OperationalBatch[]>([]);
  const [transactions, setTransactions] = useState<OperationalTransaction[]>([]);
  const [credential, setCredential] = useState('');
  const [otp, setOtp] = useState('');
  const [verified, setVerified] = useState(false);
  const [dispensedByItem, setDispensedByItem] = useState<Record<number, number>>({});
  const [busy, setBusy] = useState(false);

  const loadWorkspaceData = useCallback(async () => {
    try {
      const requests: Array<Promise<Response>> = [
        apiFetch(`${api}/api/v1/pharmacies`),
        apiFetch(`${api}/api/v1/prescriptions?limit=200`),
        apiFetch(`${api}/api/v1/stock/batches`),
      ];
      if (isPharmacist) {
        requests.push(apiFetch(`${api}/api/v1/transactions?limit=200`));
      }

      const responses = await Promise.all(requests);
      if (responses.some((r) => r.status === 401)) {
        onUnauthorized();
        return;
      }

      const [phRes, rxRes, batchRes, txRes] = responses;
      const phList: Pharmacy[] = phRes.ok ? await phRes.json() : [];
      const rxList: OperationalRx[] = rxRes.ok ? await rxRes.json() : [];
      const batchList: OperationalBatch[] = batchRes.ok ? await batchRes.json() : [];
      const txList: OperationalTransaction[] = txRes && txRes.ok ? await txRes.json() : [];

      setPharmacies(phList);
      setCurrentPharmacyId((prev) =>
        phList.some((p) => p.id === prev) ? prev : phList[0]?.id || 0,
      );
      setPrescriptions(rxList);
      setSelectedRx((prev) => {
        if (prev) {
          const updated = rxList.find((item) => item.id === prev.id);
          if (updated) return updated;
        }
        return rxList[0] || null;
      });
      setBatches(batchList);
      setTransactions(txList);
    } catch {
      onNotify('Unable to refresh pharmacy operational data');
    }
  }, [api, isPharmacist, onNotify, onUnauthorized]);

  useEffect(() => {
    loadWorkspaceData();
  }, [loadWorkspaceData, refreshKey]);

  useEffect(() => {
    if (!currentPharmacyId) return;
    apiFetch(`${api}/api/v1/pharmacies/${currentPharmacyId}/stock`)
      .then((res) => (res.ok ? res.json() : []))
      .then((stock: OperationalBatch[]) => {
        setBatches((prev) => {
          const others = prev.filter((b) => b.pharmacy_id !== currentPharmacyId);
          return [...others, ...stock];
        });
      })
      .catch(() => {});
  }, [api, currentPharmacyId]);

  const handleIssueCredential = async () => {
    if (!selectedRx) return;
    try {
      const res = await apiFetch(`${api}/api/v1/prescriptions/${selectedRx.id}/credential`, {
        method: 'POST',
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to generate credential');
      setCredential(body.qr_token);
      setOtp(body.otp);
      setSelectedRx({
        ...selectedRx,
        status: selectedRx.status === 'PARTIALLY_DISPENSED' ? 'PARTIALLY_DISPENSED' : 'ACTIVE',
      });
      onNotify('Short-lived QR & OTP credential issued');
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Credential issuance failed');
    }
  };

  const handleVerifyCredential = async () => {
    const credToVerify = otp || credential;
    if (!credToVerify) {
      onNotify('Enter an OTP or scanned QR token first');
      return;
    }
    try {
      const res = await apiFetch(`${api}/api/v1/verification`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential: credToVerify }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Credential verification failed');
      setVerified(true);
      if (body.prescription) setSelectedRx(body.prescription);
      onNotify('Credential verified against authorized pharmacy scope');
    } catch (err) {
      setVerified(false);
      onNotify(err instanceof Error ? err.message : 'Verification denied');
    }
  };

  const handleDispense = async (payload: {
    itemId: number;
    pharmacyId: number;
    allocations: BatchAllocation[];
    outcome: 'FULL' | 'PARTIAL' | 'REFUSED' | 'UNAVAILABLE';
    refusalReason?: string;
  }) => {
    if (!selectedRx) return;
    setBusy(true);
    try {
      if (payload.outcome === 'REFUSED' || payload.outcome === 'UNAVAILABLE') {
        if (credential || otp) {
          try {
            await apiFetch(`${api}/api/v1/prescriptions/${selectedRx.id}/credential/revoke`, {
              method: 'POST',
            });
          } catch {
            // best effort revocation
          }
        }
        onNotify(`Dispensing exception documented: ${payload.outcome} — ${payload.refusalReason || ''}`);
        await loadWorkspaceData();
        return;
      }

      const idempotencyKey = `amrguard-${crypto.randomUUID()}`;
      const res = await apiFetch(`${api}/api/v1/prescriptions/${selectedRx.id}/dispense`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pharmacy_id: payload.pharmacyId,
          item_id: payload.itemId,
          allocations: payload.allocations,
          credential: otp || credential,
          idempotency_key: idempotencyKey,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Dispensing denied by policy');

      const totalQty = payload.allocations.reduce((sum, a) => sum + a.quantity, 0);
      setDispensedByItem((prev) => ({
        ...prev,
        [payload.itemId]: (prev[payload.itemId] || 0) + totalQty,
      }));
      setSelectedRx({ ...selectedRx, status: body.prescription_status });
      onNotify(`Dispensed ${totalQty} units · Tx ${body.transaction_id} · RMS outbox queued`);
      await loadWorkspaceData();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Dispensing failed');
    } finally {
      setBusy(false);
    }
  };

  if (activeSection === 'traceability' && isPharmacist) {
    return <TraceabilityView api={api} batches={batches} transactions={transactions} />;
  }

  if (activeSection === 'offline') {
    return (
      <div style={{ display: 'grid', gap: 16 }}>
        <div className="pageTitle">
          <div>
            <span className="eyebrow">PHARMACY CONTINUITY · P3-02</span>
            <h1>Offline Dispensing Queue & Reconciliation</h1>
            <p>
              Review cryptographically signed offline dispensing bundles recorded during facility connectivity
              disruptions and reconcile them atomically against central prescription state and pharmacy stock.
            </p>
          </div>
          <span className="sourceBadge">
            <CloudOff size={14} /> {pharmacies.find((p) => p.id === currentPharmacyId)?.name || 'Scoped Pharmacy'}
          </span>
        </div>

        <OfflineReconciliationPanel
          api={api}
          canReconcile={isPharmacist}
          pharmacyId={currentPharmacyId || undefined}
          onNotify={onNotify}
        />
      </div>
    );
  }

  const actionableCount = prescriptions.filter((rx) =>
    ['VALIDATED', 'ACTIVE', 'PARTIALLY_DISPENSED', 'WARNING'].includes(rx.status),
  ).length;
  const activeBatchesCount = batches.filter((b) => b.quantity_available > 0).length;

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="pageTitle">
        <div>
          <span className="eyebrow">PHARMACY DISPENSING WORKSPACE</span>
          <h1>Prescription Verification & Dispensing</h1>
          <p>
            Verify patient QR/OTP credentials against pharmacy tenancy scope, allocate in-date stock batches, and
            commit atomic dispensing transactions with automatic RMS/e-Buzima outbox reconciliation.
          </p>
        </div>
        <span className="sourceBadge">
          <ShieldCheck size={14} />
          {isPharmacist ? 'Licensed Pharmacist · Dispensing Enabled' : 'Pharmacy Assistant · Verification Only'}
        </span>
      </div>

      <div className="metricGrid four">
        <div className="metric">
          <div className="metricIcon">
            <FileCheck2 size={16} />
          </div>
          <span>Actionable Orders</span>
          <strong>{actionableCount}</strong>
        </div>
        <div className="metric">
          <div className="metricIcon">
            <Boxes size={16} />
          </div>
          <span>In-Date Stock Batches</span>
          <strong>{activeBatchesCount}</strong>
        </div>
        <div className="metric">
          <div className="metricIcon">
            <CheckCircle2 size={16} />
          </div>
          <span>{isPharmacist ? 'Recorded Dispenses' : 'Scoped Pharmacies'}</span>
          <strong>{isPharmacist ? transactions.length : pharmacies.length}</strong>
        </div>
        <div className="metric">
          <div className="metricIcon">
            <Truck size={16} />
          </div>
          <span>Inventory Authority</span>
          <strong style={{ fontSize: 13 }}>RMS Reconciled</strong>
        </div>
      </div>

      <div className="dispensingLayout" style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 340px) 1fr', gap: 16 }}>
        <PrescriptionQueue
          prescriptions={prescriptions}
          selectedRx={selectedRx}
          onSelect={(rx) => {
            setSelectedRx(rx);
            setVerified(false);
            setCredential('');
            setOtp('');
          }}
          title="Incoming Queue"
          eyebrow="SCOPED PHARMACY INTAKE"
        />
        <DispensingWorkstation
          rx={selectedRx}
          pharmacies={pharmacies}
          currentPharmacyId={currentPharmacyId}
          onPharmacyChange={setCurrentPharmacyId}
          batches={batches}
          dispensedByItem={dispensedByItem}
          credential={credential}
          otp={otp}
          onOtpChange={setOtp}
          onCredentialChange={setCredential}
          isVerified={verified}
          onVerify={handleVerifyCredential}
          onIssueCredential={handleIssueCredential}
          onDispense={handleDispense}
          busy={busy}
          canDispense={isPharmacist}
          canIssueCredential={isPharmacist}
        />
      </div>

      <div className="notice" style={{ marginTop: 0 }}>
        <Truck size={15} />
        <span>
          <strong>Inventory Boundary:</strong> RMS/eLMIS remains the authoritative central supply-chain ledger. Local
          pharmacy batch balances act as an operational projection reconciled via atomic{' '}
          <code>RMS_DISPENSE_RECONCILE</code> outbox messages.
        </span>
      </div>
    </div>
  );
}
