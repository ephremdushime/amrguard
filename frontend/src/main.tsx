import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  ArrowRight,
  Boxes,
  CheckCircle2,
  Clock3,
  FileCheck2,
  FileSearch,
  GitBranch,
  Layers,
  LockKeyhole,
  Network,
  PackageSearch,
  ScanLine,
  ShieldCheck,
  TriangleAlert,
  Truck,
  Wifi,
} from 'lucide-react';
import { apiFetch, setCsrfToken, type AuthUser } from './authApi';
import type {
  BatchAllocation,
  FacilityMeasure,
  OperationalBatch,
  OperationalRx,
  OperationalTransaction,
  OperationsSummary,
  Pharmacy,
  PrescriptionOrder,
  StewardshipReminderRow,
} from './types';
import { AuthHeader } from './components/AuthHeader';
import { LoginForm } from './components/LoginForm';
import { PrescriptionQueue } from './components/PrescriptionQueue';
import { DispensingWorkstation } from './components/DispensingWorkstation';
import { ConsentReminderModal } from './components/ConsentReminderModal';
import { TraceabilityView } from './components/TraceabilityView';
import { StewardshipView } from './components/StewardshipView';
import { IntegrationsView } from './components/IntegrationsView';
import './style.css';
import './style-v2.css';

const API = import.meta.env.VITE_API_URL || (import.meta.env.PROD ? '' : 'http://localhost:8000');
const FUNDER_DEMO = import.meta.env.VITE_FUNDER_DEMO === '1';
const IS_OPERATIONS = import.meta.env.PROD && !FUNDER_DEMO;

const fallbackSummary: OperationsSummary = {
  prescriptions: 0,
  validated: 0,
  blocked: 0,
  dispensing_transactions: 0,
  units_dispensed: 0,
  active_batches: 0,
  connected_pharmacies: 0,
};

async function fetchJsonOrFallback<T>(
  url: string,
  defaultValue: T,
): Promise<{ ok: boolean; unauthorized: boolean; data: T }> {
  try {
    const response = await apiFetch(url);
    if (response.status === 401) return { ok: false, unauthorized: true, data: defaultValue };
    if (!response.ok) return { ok: false, unauthorized: false, data: defaultValue };
    const data = await response.json();
    return { ok: true, unauthorized: false, data };
  } catch {
    return { ok: false, unauthorized: false, data: defaultValue };
  }
}

function App() {
  const [authChecked, setAuthChecked] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [page, setPage] = useState('Overview');
  const [summary, setSummary] = useState<OperationsSummary>(fallbackSummary);
  const [online, setOnline] = useState(false);
  const [prescriptions, setPrescriptions] = useState<OperationalRx[]>([]);
  const [selectedRx, setSelectedRx] = useState<OperationalRx | null>(null);
  const [transactions, setTransactions] = useState<OperationalTransaction[]>([]);
  const [reminders, setReminders] = useState<StewardshipReminderRow[]>([]);
  const [pharmacies, setPharmacies] = useState<Pharmacy[]>([]);
  const [batches, setBatches] = useState<OperationalBatch[]>([]);
  const [currentPharmacyId, setCurrentPharmacyId] = useState<number>(1);
  const [credential, setCredential] = useState('');
  const [otp, setOtp] = useState('');
  const [verified, setVerified] = useState(false);
  const [dispensedByItem, setDispensedByItem] = useState<Record<number, number>>({});
  const [toast, setToast] = useState('');
  const [busy, setBusy] = useState(false);
  const [consentModalRx, setConsentModalRx] = useState<OperationalRx | null>(null);

  const checkSession = async () => {
    try {
      const health = await fetch(`${API}/health`);
      setOnline(health.ok);
      const me = await apiFetch(`${API}/api/v1/auth/me`);
      if (me.ok) {
        const u = await me.json();
        setUser(u);
      } else {
        setUser(null);
      }
    } catch {
      setOnline(false);
      setUser(null);
    } finally {
      setAuthChecked(true);
    }
  };

  const loadData = async () => {
    try {
      const [summaryRes, pharmacyRes, rxRes, txRes, batchRes, reminderRes] = await Promise.all([
        fetchJsonOrFallback<OperationsSummary>(`${API}/api/v1/analytics/summary`, fallbackSummary),
        fetchJsonOrFallback<Pharmacy[]>(`${API}/api/v1/pharmacies`, []),
        fetchJsonOrFallback<OperationalRx[]>(`${API}/api/v1/prescriptions?limit=200`, []),
        fetchJsonOrFallback<OperationalTransaction[]>(`${API}/api/v1/transactions?limit=200`, []),
        fetchJsonOrFallback<OperationalBatch[]>(`${API}/api/v1/stock/batches`, []),
        fetchJsonOrFallback<StewardshipReminderRow[]>(`${API}/api/v1/stewardship/reminders?limit=200`, []),
      ]);

      if ([summaryRes, pharmacyRes, rxRes, txRes, batchRes, reminderRes].some((r) => r.unauthorized)) {
        setUser(null);
        return;
      }

      setSummary(summaryRes.data);
      setPharmacies(pharmacyRes.data);
      if (pharmacyRes.data[0] && !pharmacyRes.data.some((p) => p.id === currentPharmacyId)) {
        setCurrentPharmacyId(pharmacyRes.data[0].id);
      }
      setPrescriptions(rxRes.data);
      if (selectedRx) {
        const updated = rxRes.data.find((o) => o.id === selectedRx.id);
        if (updated) setSelectedRx(updated);
      } else if (rxRes.data[0]) {
        setSelectedRx(rxRes.data[0]);
      }
      setTransactions(txRes.data);
      setBatches(batchRes.data);
      setReminders(reminderRes.data);
      setOnline(true);
    } catch {
      setOnline(false);
    }
  };

  useEffect(() => {
    checkSession();
  }, []);

  useEffect(() => {
    if (user) loadData();
  }, [user]);

  useEffect(() => {
    if (user && currentPharmacyId) {
      apiFetch(`${API}/api/v1/pharmacies/${currentPharmacyId}/stock`)
        .then((r) => (r.ok ? r.json() : []))
        .then((stock: OperationalBatch[]) => {
          setBatches((prev) => {
            const others = prev.filter((b) => b.pharmacy_id !== currentPharmacyId);
            return [...others, ...stock];
          });
        })
        .catch(() => {});
    }
  }, [user, currentPharmacyId]);

  const signOut = async () => {
    try {
      await apiFetch(`${API}/api/v1/auth/logout`, { method: 'POST' });
    } finally {
      setCsrfToken('');
      setUser(null);
      setSelectedRx(null);
      setVerified(false);
      setToast('Signed out');
    }
  };

  const handleIssueCredential = async () => {
    if (!selectedRx) return;
    try {
      const res = await apiFetch(`${API}/api/v1/prescriptions/${selectedRx.id}/credential`, { method: 'POST' });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to generate credential');
      setCredential(body.qr_token);
      setOtp(body.otp);
      setSelectedRx({
        ...selectedRx,
        status: selectedRx.status === 'PARTIALLY_DISPENSED' ? 'PARTIALLY_DISPENSED' : 'ACTIVE',
      });
      setToast('Secure QR and OTP credential issued');
    } catch (err: unknown) {
      setToast(err instanceof Error ? err.message : 'Error generating credential');
    }
  };

  const handleVerifyCredential = async () => {
    const credToVerify = otp || credential;
    if (!credToVerify) {
      setToast('Enter an OTP or scanned QR credential first');
      return;
    }
    try {
      const res = await apiFetch(`${API}/api/v1/verification`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential: credToVerify }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Credential verification failed');
      setVerified(true);
      if (body.prescription) setSelectedRx(body.prescription);
      setToast('Credential verified successfully');
    } catch (err: unknown) {
      setVerified(false);
      setToast(err instanceof Error ? err.message : 'Verification denied');
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
            await apiFetch(`${API}/api/v1/prescriptions/${selectedRx.id}/credential/revoke`, { method: 'POST' });
          } catch {
            // best effort revocation
          }
        }
        setToast(`Exception recorded: ${payload.outcome} — ${payload.refusalReason || 'Documented'}`);
        await loadData();
        return;
      }

      const idempotencyKey = `amrguard-${crypto.randomUUID()}`;
      const res = await apiFetch(`${API}/api/v1/prescriptions/${selectedRx.id}/dispense`, {
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
      if (!res.ok) throw new Error(body.detail || 'Dispensing denied by transaction policy');

      const totalQty = payload.allocations.reduce((sum, a) => sum + a.quantity, 0);
      setDispensedByItem((current) => ({
        ...current,
        [payload.itemId]: (current[payload.itemId] || 0) + totalQty,
      }));

      setSelectedRx({
        ...selectedRx,
        status: body.prescription_status,
      });

      setToast(`Dispensing authorized: ${totalQty} units recorded (Tx: ${body.transaction_id})`);
      await loadData();
    } catch (err: unknown) {
      setToast(err instanceof Error ? err.message : 'Dispensing failed');
    } finally {
      setBusy(false);
    }
  };

  const handleCreatePrescription = async (order: PrescriptionOrder) => {
    const external = `EBZ-DEMO-${Date.now()}`;
    try {
      const res = await apiFetch(`${API}/api/v1/demo/prescriptions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...order, external_id: external }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to create prescription');
      setSelectedRx(body.prescription);
      setVerified(false);
      setDispensedByItem({});
      setPage('Dispensing');
      setToast('Prescription validated and saved');
      await loadData();
    } catch (err: unknown) {
      setToast(err instanceof Error ? err.message : 'Prescription creation error');
    }
  };

  const demoCreate = () =>
    handleCreatePrescription({
      patient_reference: 'PATIENT-DEMO-001',
      antibiotic_code: 'AMX500CAP',
      generic_name: 'Amoxicillin',
      strength: '500 mg',
      formulation: 'Capsule',
      route: 'Oral',
      dose: 500,
      frequency_per_day: 3,
      duration_days: 5,
      quantity: 15,
      indication: 'Upper respiratory tract infection (community-acquired)',
      expires_at: new Date(Date.now() + 72 * 60 * 60 * 1000).toISOString(),
    });

  const navigation = IS_OPERATIONS
    ? ['Overview', 'Prescriptions', 'Dispensing', 'Batch Traceability', 'Stewardship', 'AMR Intelligence', 'Integrations']
    : ['Overview', 'Prescriptions', 'Dispensing', 'Batch Traceability', 'Stewardship', 'AMR Intelligence', 'Safety Controls', 'Integrations'];

  if (!authChecked) {
    return (
      <div className="app">
        <main style={{ marginLeft: 0, width: '100%' }}>
          <div className="panel" style={{ maxWidth: 460, margin: '80px auto', textAlign: 'center' }}>
            <span className="eyebrow">AMRGUARD SECURITY BOUNDARY</span>
            <h2>Checking authenticated session…</h2>
            <p className="muted">Validating institutional credentials and session boundary.</p>
          </div>
        </main>
      </div>
    );
  }

  if (!user) {
    return (
      <LoginForm
        api={API}
        online={online}
        onAuthenticated={(signedIn) => {
          if (signedIn.csrf_token) setCsrfToken(signedIn.csrf_token);
          setUser(signedIn);
        }}
      />
    );
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandMark">
            <ShieldCheck size={22} />
          </div>
          <div>
            <strong>AMRGuard</strong>
            <span>Antibiotic transaction layer</span>
          </div>
        </div>

        <div className="demoLabel">
          {IS_OPERATIONS ? 'OPERATIONS WORKSPACE' : FUNDER_DEMO ? 'FUNDER DEMO' : 'DEVELOPMENT WORKSPACE'}
        </div>

        <nav>
          {navigation.map((item) => (
            <button
              type="button"
              className={page === item ? 'active' : ''}
              onClick={() => setPage(item)}
              key={item}
            >
              {item}
            </button>
          ))}
        </nav>

        <div className="sideFoot">
          <span className={online ? 'live' : 'demoDot'} />
          <span>{user.display_name || user.username}</span>
          <small>{user.roles.join(', ')}</small>
        </div>
      </aside>

      <main>
        <AuthHeader
          user={user}
          page={page}
          online={online}
          onRefresh={loadData}
          onSignOut={signOut}
        />

        {page === 'Overview' && (
          <Overview
            summary={summary}
            online={online}
            onNavigate={setPage}
            demoCreate={demoCreate}
          />
        )}

        {page === 'Prescriptions' && (
          <PrescriberWorkspace
            rx={selectedRx}
            prescriptions={prescriptions}
            onCreate={handleCreatePrescription}
            onSelectRx={(rx) => {
              setSelectedRx(rx);
              setPage('Dispensing');
            }}
          />
        )}

        {page === 'Dispensing' && (
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
              title="Prescription Queue"
              eyebrow="PHARMACY INTAKE"
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
            />
          </div>
        )}

        {page === 'Batch Traceability' && (
          <TraceabilityView
            api={API}
            batches={batches}
            transactions={transactions}
          />
        )}

        {page === 'Stewardship' && (
          <StewardshipView
            api={API}
            prescriptions={prescriptions}
            transactions={transactions}
            reminders={reminders}
            onReload={loadData}
            onOpenConsentModal={(rx) => setConsentModalRx(rx)}
          />
        )}

        {page === 'AMR Intelligence' && <Analytics summary={summary} />}

        {page === 'Safety Controls' && import.meta.env.DEV && <RiskControls api={API} />}

        {page === 'Integrations' && (
          <IntegrationsView
            api={API}
            online={online}
            inboundCount={prescriptions.filter((order) => !order.external_id.startsWith('EBZ-DEMO-')).length}
          />
        )}

        {consentModalRx && (
          <ConsentReminderModal
            api={API}
            prescriptionId={consentModalRx.id}
            prescriptionCode={consentModalRx.code}
            patientReference={consentModalRx.patient_reference}
            facilityId={1}
            isOpen={Boolean(consentModalRx)}
            onClose={() => setConsentModalRx(null)}
            onSuccess={() => {
              setConsentModalRx(null);
              loadData();
              setToast('Patient SMS consent recorded and reminder scheduled');
            }}
          />
        )}

        {toast && (
          <div className="toast" onClick={() => setToast('')}>
            <CheckCircle2 size={16} />
            <span>{toast}</span>
          </div>
        )}
      </main>
    </div>
  );
}

function PageTitle({
  eyebrow,
  title,
  desc,
  action,
}: {
  eyebrow: string;
  title: string;
  desc: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="pageTitle">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{desc}</p>
      </div>
      {action}
    </div>
  );
}

function Overview({
  summary,
  online,
  onNavigate,
  demoCreate,
}: {
  summary: OperationsSummary;
  online: boolean;
  onNavigate: (p: string) => void;
  demoCreate: () => void;
}) {
  const completion = summary.prescriptions
    ? Math.round((summary.validated / summary.prescriptions) * 100)
    : 0;

  return (
    <div className="pitchOverview">
      <section className="pitchHero">
        <div className="heroCopy">
          <span className="heroKicker">
            <span className={online ? 'live' : 'demoDot'} /> RWANDA · ANTIMICROBIAL RESISTANCE RESPONSE
          </span>
          <h1>
            Every antibiotic.
            <br />
            <em>Accounted for.</em>
          </h1>
          <p>
            AMRGuard connects prescriptions to verified dispensing and batch traceability — adding a trusted
            transaction layer to Rwanda’s digital health ecosystem.
          </p>
          <div className="heroActions">
            <button className="heroPrimary" onClick={demoCreate}>
              <ScanLine size={16} /> Run the product demo <ArrowRight size={16} />
            </button>
            <button className="heroSecondary" onClick={() => onNavigate('Integrations')}>
              Explore integration model
            </button>
          </div>
          <div className="heroTrust">
            <ShieldCheck size={15} /> Designed to complement existing clinical and supply systems
          </div>
        </div>

        <div className="heroVisual" aria-label="AMRGuard prescription verification and traceability illustration">
          <div className="orbit orbitOuter" />
          <div className="orbit orbitInner" />
          <div className="heroNode heroNodeSource">
            <span className="nodeIcon">
              <FileCheck2 size={18} />
            </span>
            <small>PRESCRIPTION</small>
            <b>e-Buzima</b>
            <i>Order received</i>
          </div>
          <div className="heroNode heroNodeCore">
            <div className="coreHalo" />
            <span className="coreIcon">
              <ShieldCheck size={28} />
            </span>
            <b>AMRGuard</b>
            <small>VERIFY · TRACE · LEARN</small>
          </div>
          <div className="heroNode heroNodePharmacy">
            <span className="nodeIcon">
              <Boxes size={18} />
            </span>
            <small>DISPENSE</small>
            <b>Pharmacy</b>
            <i>Batch linked</i>
          </div>
          <div className="heroConnector connectorOne" />
          <div className="heroConnector connectorTwo" />
          <span className="visualCaption">A connected antibiotic journey</span>
        </div>
      </section>

      <section className="proofStrip">
        <div>
          <span>LIVE WORKFLOW</span>
          <b>Prescription → verified dispense</b>
        </div>
        <div>
          <span>BUILT FOR INTEROPERABILITY</span>
          <b>API contracts · system adapters</b>
        </div>
        <div>
          <span>ACCOUNTABILITY</span>
          <b>Batch-level transaction trail</b>
        </div>
        <div className="proofStatus">
          <span>SYSTEM STATUS</span>
          <b>
            <i className={online ? 'live' : 'demoDot'} />
            {online ? 'Demo environment online' : 'Connecting to demo API'}
          </b>
        </div>
      </section>

      <section className="pitchSectionHead">
        <div>
          <span className="eyebrow">THE CONTROL LAYER</span>
          <h2>
            Visibility from the first order
            <br />
            to the last tablet.
          </h2>
        </div>
        <p>
          One connected workflow helps health systems see what was prescribed, what was dispensed, and which
          supply batch moved through the pharmacy.
        </p>
      </section>

      <section className="journeyCards">
        <button className="journeyCard" onClick={() => onNavigate('Prescriptions')}>
          <span className="journeyNumber">01 / INTAKE</span>
          <span className="journeyIcon">
            <FileCheck2 size={19} />
          </span>
          <b>Validate the order</b>
          <p>Capture antibiotic-specific prescription details and check regimen quantity before pharmacy fulfillment.</p>
          <span className="cardLink">
            Prescription workspace <ArrowRight size={14} />
          </span>
        </button>

        <button className="journeyCard" onClick={() => onNavigate('Dispensing')}>
          <span className="journeyNumber">02 / VERIFY</span>
          <span className="journeyIcon">
            <ScanLine size={19} />
          </span>
          <b>Authorize dispensing</b>
          <p>Verify a time-limited prescription credential against pharmacy identity, available stock, and quantity.</p>
          <span className="cardLink">
            Pharmacy workflow <ArrowRight size={14} />
          </span>
        </button>

        <button className="journeyCard" onClick={() => onNavigate('Batch Traceability')}>
          <span className="journeyNumber">03 / TRACE</span>
          <span className="journeyIcon">
            <GitBranch size={19} />
          </span>
          <b>Follow every batch</b>
          <p>Connect dispensing transactions to their pharmacy, prescription, and medicine batch for audit.</p>
          <span className="cardLink">
            Traceability view <ArrowRight size={14} />
          </span>
        </button>

        <button className="journeyCard" onClick={() => onNavigate('AMR Intelligence')}>
          <span className="journeyNumber">04 / LEARN</span>
          <span className="journeyIcon">
            <Activity size={19} />
          </span>
          <b>Turn activity into insight</b>
          <p>Build a clearer picture of utilization, dispensing patterns, stock movement, and stewardship signals.</p>
          <span className="cardLink">
            AMR intelligence <ArrowRight size={14} />
          </span>
        </button>
      </section>

      <section className="pitchMetrics">
        <div>
          <span>ORDERS IN DEMO</span>
          <b>{summary.prescriptions.toLocaleString()}</b>
        </div>
        <div>
          <span>VALIDATION RATE</span>
          <b>{completion}%</b>
        </div>
        <div>
          <span>RECORDED DISPENSES</span>
          <b>{summary.dispensing_transactions.toLocaleString()}</b>
        </div>
      </section>

      <div className="pitchBottomNote">
        <span>DEMO DATA · NOT NATIONAL STATISTICS</span>
        <p>
          Partner integrations are contract-ready demonstrations. Live e-Buzima, RMS and pharmacy connections require
          approved specifications and certification.
        </p>
        <button onClick={() => onNavigate('Integrations')}>
          See integration readiness <ArrowRight size={15} />
        </button>
      </div>
    </div>
  );
}

function PrescriberWorkspace({
  rx,
  prescriptions,
  onCreate,
  onSelectRx,
}: {
  rx: OperationalRx | null;
  prescriptions: OperationalRx[];
  onCreate: (order: PrescriptionOrder) => void;
  onSelectRx: (rx: OperationalRx) => void;
}) {
  const [patient, setPatient] = useState('');
  const [dose, setDose] = useState(500);
  const [frequency, setFrequency] = useState(3);
  const [duration, setDuration] = useState(5);
  const [indication, setIndication] = useState('');
  const [lifetime, setLifetime] = useState(72);
  const [support, setSupport] = useState<any>(null);
  const quantity = frequency * duration;

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(
      () =>
        apiFetch(`${API}/api/v1/stewardship/support`, {
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
          .catch(() => {}),
      180,
    );
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [dose, frequency, duration, quantity, indication]);

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onCreate({
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
    });
  };

  return (
    <>
      <PageTitle
        eyebrow="PRESCRIBER WORKSPACE"
        title="Write antibiotic prescription"
        desc="AMRGuard transaction checks appear alongside the prescribing workflow; the clinician remains in control of the order."
      />
      <div className="orderWorkspace" style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 16 }}>
        <form className="panel prescriptionForm" onSubmit={submit}>
          <div className="formSectionHead">
            <span className="eyebrow">01 / PATIENT & MEDICATION</span>
            <span className="statusPill">Required fields</span>
          </div>

          <label>
            Patient Reference / Encounter ID
            <input
              required
              minLength={1}
              maxLength={150}
              placeholder="e.g. RW-PAT-2026-00412"
              value={patient}
              onChange={(e) => setPatient(e.target.value)}
            />
          </label>

          <label>
            Antibiotic Catalogue Item
            <select value="AMX500CAP" disabled>
              <option value="AMX500CAP">Amoxicillin 500 mg · Capsule · Oral (Access Group)</option>
            </select>
          </label>

          <div className="formSectionHead regimenHead">
            <span className="eyebrow">02 / REGIMEN</span>
          </div>

          <div className="prescriptionFields" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
            <label>
              Dose (mg)
              <input
                required
                type="number"
                min={1}
                step="any"
                value={dose}
                onChange={(e) => setDose(Number(e.target.value))}
              />
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

          <label>
            Prescribing Indication
            <textarea
              required
              minLength={1}
              maxLength={300}
              rows={3}
              placeholder="Document clinical diagnosis or clinical indication"
              value={indication}
              onChange={(e) => setIndication(e.target.value)}
            />
          </label>

          <div className="calculatedQuantity">
            <div>
              <span>Calculated Regimen Units</span>
              <small>
                {frequency} doses/day × {duration} days
              </small>
            </div>
            <strong>
              {quantity}
              <small> units</small>
            </strong>
          </div>

          <StewardshipSupportCard support={support} />

          <div className="formSectionHead regimenHead">
            <span className="eyebrow">03 / PRESCRIPTION LIFETIME</span>
          </div>

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
            <small className="fieldHint">Expires {new Date(Date.now() + lifetime * 60 * 60 * 1000).toLocaleString()}</small>
          </label>

          <button className="primary full" type="submit">
            <FileCheck2 size={17} /> Validate and issue prescription
          </button>
        </form>

        <div className="prescriptionAside" style={{ display: 'grid', gap: 14 }}>
          {rx ? (
            <div className="panel">
              <span className="eyebrow">LATEST CREATED ORDER</span>
              <h2>{rx.code}</h2>
              <div className="summaryStrip">
                <div>
                  <span>Patient</span>
                  <b>{rx.patient_reference}</b>
                </div>
                <div>
                  <span>Medicine</span>
                  <b>{rx.items[0]?.antibiotic}</b>
                </div>
                <div>
                  <span>Quantity</span>
                  <b>{rx.items[0]?.authorized_quantity}</b>
                </div>
                <div>
                  <span>Status</span>
                  <b>{rx.status}</b>
                </div>
              </div>
              <button className="primary full" onClick={() => onSelectRx(rx)}>
                Open in Dispensing Workstation <ArrowRight size={16} />
              </button>
            </div>
          ) : (
            <div className="panel">
              <span className="eyebrow">INTAKE REGISTER</span>
              <h2>{prescriptions.length} Active Prescriptions</h2>
              <p className="muted">Prescriptions authored here or received via e-Buzima appear in the register.</p>
              <div style={{ maxHeight: 280, overflowY: 'auto', display: 'grid', gap: 6 }}>
                {prescriptions.slice(0, 5).map((p) => (
                  <button
                    type="button"
                    key={p.id}
                    onClick={() => onSelectRx(p)}
                    style={{
                      textAlign: 'left',
                      padding: '8px 12px',
                      borderRadius: 6,
                      border: '1px solid var(--border)',
                      background: 'var(--bg-subtle, #f8fafc)',
                      cursor: 'pointer',
                    }}
                  >
                    <strong>{p.code}</strong> — {p.items[0]?.antibiotic}
                    <div style={{ fontSize: '11px', color: 'var(--muted)' }}>
                      Patient: {p.patient_reference} · {p.status}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="panel sourceNote">
            <span className="eyebrow">INTEGRATION FEATURE</span>
            <h2>Embedded Decision Support</h2>
            <p className="muted">
              Partner EMRs (such as e-Buzima) query this endpoint during order composition to display national AWaRe
              guidance and review points without disrupting clinical workflow.
            </p>
            <code className="supportEndpoint">POST /api/v1/stewardship/support</code>
          </div>
        </div>
      </div>
    </>
  );
}

function StewardshipSupportCard({ support }: { support: any }) {
  if (!support) {
    return (
      <div className="embeddedSupport">
        <div className="supportHead">
          <span className="supportGlyph">
            <ShieldCheck size={17} />
          </span>
          <div>
            <b>AMRGuard Prescribing Support</b>
            <small>Evaluating clinical regimen…</small>
          </div>
        </div>
      </div>
    );
  }

  const error = support.decision === 'REVIEW_REQUIRED';
  return (
    <div className={`embeddedSupport ${error ? 'supportError' : ''}`}>
      <div className="supportHead">
        <span className="supportGlyph">{error ? <TriangleAlert size={17} /> : <ShieldCheck size={17} />}</span>
        <div>
          <b>AMRGuard Prescribing Support</b>
          <small>Contextual check · clinician retains prescription control</small>
        </div>
        <span className={`supportDecision ${error ? '' : 'supportPass'}`}>{error ? 'REVIEW' : 'CHECKED'}</span>
      </div>
      <div className="supportMessage">{support.display?.message}</div>
      <div className="supportFacts">
        <span>
          <b>{support.stewardship?.aware_category || 'Access'}</b>
          <small>AWaRe classification</small>
        </span>
        <span>
          <b>Day 3</b>
          <small>Suggested review point</small>
        </span>
      </div>
      <p className="supportPrompt">{support.stewardship?.review_prompt}</p>
      <small className="supportGovernance">Transaction checks only · no clinical recommendation · local guideline governance</small>
    </div>
  );
}

function Analytics({ summary }: { summary: OperationsSummary }) {
  const rate = Math.round((summary.validated / Math.max(summary.prescriptions, 1)) * 100);
  const [facilities, setFacilities] = useState<FacilityMeasure[]>([]);

  useEffect(() => {
    apiFetch(`${API}/api/v1/analytics/facilities`)
      .then((response) => (response.ok ? response.json() : { facilities: [] }))
      .then((body) => setFacilities(body.facilities || []))
      .catch(() => setFacilities([]));
  }, []);

  return (
    <>
      <PageTitle
        eyebrow="PILOT MEASUREMENT"
        title="Stewardship workflow measures"
        desc="Operational measures for a facility pilot. Use agreed baselines and reviewed denominators before interpreting outcomes; demo counts are not national statistics."
      />
      <div className="metricGrid three">
        {[
          ['Prescription validation rate', `${rate}%`, ShieldCheck],
          ['Prescription-to-dispense reconciliation', `${summary.prescription_dispense_reconciliation_rate ?? 0}%`, GitBranch],
          ['Stewardship review completion', `${summary.stewardship_review_completion_rate ?? 0}%`, Activity],
          ['Pending clinical reviews', summary.pending_stewardship_reviews ?? 0, Clock3],
          ['Quantity checks requiring review', summary.blocked, TriangleAlert],
          ['Participating pharmacies', summary.connected_pharmacies ?? 0, Network],
        ].map(([t, v, Icon]: any) => (
          <div className="metric" key={t}>
            <div className="metricIcon">
              <Icon size={18} />
            </div>
            <span>{t}</span>
            <strong>{v}</strong>
          </div>
        ))}
      </div>

      <div className="twoCol" style={{ marginTop: 18 }}>
        <div className="panel chart">
          <div className="panelHead">
            <h2>Prescription and dispense flow</h2>
            <span>Operational data</span>
          </div>
          {[
            ['Orders received', summary.prescriptions],
            ['Validated or active', summary.validated],
            ['Orders with a dispense', summary.prescriptions_with_dispense ?? 0],
            ['Dispense transactions', summary.dispensing_transactions],
          ].map(([n, v]: any) => (
            <div className="barRow" key={n}>
              <span>{n}</span>
              <div>
                <i style={{ width: `${Math.min(100, (Number(v) / Math.max(summary.prescriptions, 1)) * 100)}%` }} />
              </div>
              <b>{Number(v).toLocaleString()}</b>
            </div>
          ))}
        </div>

        <div className="panel">
          <span className="eyebrow">PILOT LEARNING QUESTIONS</span>
          <h2>What the workflow measures</h2>
          {[
            'Prescription completeness and quantity discrepancy rates',
            'How often prescribed orders reconcile to pharmacy dispensing',
            'Time to complete post-dispense stewardship reviews',
            'Review outcomes (continue, change, stop, refer) and reasons',
            'Data coverage and audit trail completeness by facility',
          ].map((x) => (
            <div className="check" key={x}>
              <Activity size={17} />
              <span>{x}</span>
            </div>
          ))}
          <div className="notice" style={{ marginTop: 16 }}>
            <TriangleAlert size={16} />
            <span>Agree definitions, denominators, governance, and baseline with pilot facilities before reporting impact.</span>
          </div>
        </div>
      </div>

      <section className="panel facilityMeasures" style={{ marginTop: 18 }}>
        <div className="panelHead">
          <div>
            <span className="eyebrow">FACILITY BREAKDOWN</span>
            <h2>Data coverage by pilot site</h2>
          </div>
          <span className="statusPill">{facilities.length} facilities</span>
        </div>
        {facilities.length ? (
          facilities.map((facility) => (
            <div className="facilityMeasureRow" key={facility.facility_code}>
              <div>
                <b>{facility.facility_name}</b>
                <small>
                  {facility.facility_code} · {facility.district}
                </small>
              </div>
              <span>{facility.prescriptions} prescriptions</span>
              <span>{facility.reconciliation_rate}% reconciled</span>
              <span>{facility.review_completion_rate}% reviews complete</span>
            </div>
          ))
        ) : (
          <p className="muted">Facility-level measures appear when facilities have authorized pilot data.</p>
        )}
      </section>
    </>
  );
}

function RiskControls({ api }: { api: string }) {
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      const r = await apiFetch(`${api}/api/v1/demo/risk-scenario`, { method: 'POST' });
      const j = await r.json();
      setResult(j);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageTitle
        eyebrow="SAFETY & CONTROL DEMO"
        title="Deterministic validation blocking"
        desc="A deliberate invalid prescription demonstrates how AMRGuard stops a quantity mismatch before it reaches pharmacy dispensing."
      />
      <div className="twoCol">
        <div className="panel">
          <span className="eyebrow">CONTROL SCENARIO</span>
          <h2>Intentional quantity mismatch</h2>
          <div className="orderCard">
            <div>
              <span>Regimen</span>
              <strong>500 mg · 3× daily · 5 days</strong>
            </div>
            <div>
              <span>Expected units</span>
              <strong>15</strong>
            </div>
            <div>
              <span>Submitted</span>
              <strong>20</strong>
            </div>
          </div>
          <div className="notice">
            <TriangleAlert size={17} />
            <span>AMRGuard blocks mismatches according to configured validation policy before pharmacy credentials can be issued.</span>
          </div>
          <button className="primary full" onClick={run} disabled={busy}>
            <TriangleAlert size={17} />
            {busy ? 'Running scenario…' : 'Run blocked-prescription demo'}
          </button>
        </div>

        <div className="panel">
          {result ? (
            <>
              <span className="eyebrow">RESULT</span>
              <h2>{result.prescription?.code}</h2>
              <div className="result errorBox">
                <TriangleAlert size={20} />
                <div>
                  <b>BLOCKED</b>
                  <span>Quantity mismatch detected. Expected 15 units; submitted 20 units.</span>
                </div>
              </div>
              <div className="detailGrid" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10, marginTop: 14 }}>
                <div className="detail">
                  <span>Status</span>
                  <b>{result.prescription?.status || 'BLOCKED'}</b>
                </div>
                <div className="detail">
                  <span>External Source</span>
                  <b>{result.prescription?.external_id || '—'}</b>
                </div>
                <div className="detail">
                  <span>Rule Code</span>
                  <b>QUANTITY_MISMATCH</b>
                </div>
                <div className="detail">
                  <span>Severity</span>
                  <b>BLOCK</b>
                </div>
              </div>
            </>
          ) : (
            <>
              <span className="eyebrow">DEMO RESULT</span>
              <h2>Awaiting scenario</h2>
              <p className="muted">Run the scenario to create a deliberately blocked prescription and inspect the validation issue.</p>
            </>
          )}
        </div>
      </div>
    </>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
