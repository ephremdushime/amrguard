import React, { useState } from 'react';
import { ArrowRight, CheckCircle2, Network, RefreshCw, Send, ShieldCheck, TriangleAlert, Wifi } from 'lucide-react';
import { apiFetch } from '../authApi';

interface IntegrationsViewProps {
  api: string;
  online: boolean;
  inboundCount: number;
}

export function IntegrationsView({ api, online, inboundCount }: IntegrationsViewProps) {
  const [payload, setPayload] = useState(
    JSON.stringify(
      {
        resourceType: 'Bundle',
        type: 'collection',
        id: 'EBZ-FHIR-DEMO-001',
        entry: [
          {
            resource: {
              resourceType: 'MedicationRequest',
              id: 'MR-DEMO-01',
              status: 'active',
              intent: 'order',
              subject: { reference: 'Patient/SYNTH-PAT-001', display: 'Synthetic Patient' },
              recorder: { reference: 'Organization/FAC-KGL-001' },
              medicationCodeableConcept: {
                coding: [
                  {
                    system: 'http://moh.gov.rw/drugs',
                    code: 'AMX500CAP',
                    display: 'Amoxicillin 500 mg Capsule',
                  },
                ],
                text: 'Amoxicillin 500 mg',
              },
              dosageInstruction: [
                {
                  timing: { repeat: { frequency: 3, period: 1, periodUnit: 'd' } },
                  doseAndRate: [{ doseQuantity: { value: 500, unit: 'mg' } }],
                  route: { coding: [{ display: 'Oral' }] },
                },
              ],
              dispenseRequest: {
                expectedSupplyDuration: { value: 5, unit: 'days' },
                quantity: { value: 15, unit: 'capsules' },
              },
              reasonCode: [{ text: 'Community-acquired upper respiratory tract infection' }],
            },
          },
        ],
      },
      null,
      2,
    ),
  );

  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [outboxBusy, setOutboxBusy] = useState(false);
  const [outboxResult, setOutboxResult] = useState<string | null>(null);
  const [error, setError] = useState('');

  const sourceStatus = inboundCount
    ? `${inboundCount} INBOUND ORDERS RECEIVED`
    : 'CONTRACT READY · WAITING INBOUND ORDERS';

  const triggerOutboxDispatch = async () => {
    setOutboxBusy(true);
    setOutboxResult(null);
    try {
      const res = await apiFetch(`${api}/api/v1/integrations/outbox/dispatch-tick`, {
        method: 'POST',
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Outbox tick failed');
      setOutboxResult(
        `Dispatched: ${data.dispatched}, Retrying: ${data.retrying}, Dead-letter: ${data.dead_letter} (Processed: ${data.processed})`,
      );
    } catch (err) {
      setOutboxResult(err instanceof Error ? err.message : 'Outbox tick failed');
    } finally {
      setOutboxBusy(false);
    }
  };

  return (
    <>
      <div className="pageTitle">
        <div>
          <span className="eyebrow">INTEGRATION OPERATIONS</span>
          <h1>Connect through existing health & supply systems</h1>
          <p>
            AMRGuard exposes canonical contracts and partner adapters. Test partner-shaped FHIR payloads and trigger
            transactional outbox reconciliation with the central store.
          </p>
        </div>
        <span className="sourceBadge">
          <span className={online ? 'live' : 'demoDot'} />
          {online ? 'AMRGuard adapters healthy' : 'AMRGuard services connecting'}
        </span>
      </div>

      <div className="integrationGrid">
        {[
          [
            'e-Buzima EMR',
            'Clinical Source',
            'Authenticated FHIR R4 & JSON prescription ingestion, unmapped code quarantine, and status synchronization',
            sourceStatus,
          ],
          [
            'RMS / eLMIS',
            'Supply Chain',
            'Idempotent stock receipt and adjustment events with batch audit history and dispense consumption ledger',
            'CONTRACT READY · NO STOCK FEED',
          ],
          [
            'Pharmacy Software',
            'Dispensing / Inventory',
            'Dispense reconciliation is captured against prescription and batch; outbox worker dispatches stock updates',
            'PORTAL ACTIVE · OUTBOX READY',
          ],
          [
            'SMS Provider Gateway',
            'Stewardship Support',
            'Consent-verified dose-level adherence reminder queue; keyed phone hashing; neutral multi-language templates',
            'GATEWAY ADAPTER READY',
          ],
        ].map(([title, role, desc, status]) => (
          <div className="panel integrationCard" key={title}>
            <div className="integrationIcon">
              <Network size={19} />
            </div>
            <span className="eyebrow">{role}</span>
            <h2>{title}</h2>
            <p>{desc}</p>
            <div className="statusLine">
              <span
                className={status.includes('RECEIVED') || status.includes('ACTIVE') || status.includes('READY') ? 'live' : 'demoDot'}
              />
              {status}
            </div>
          </div>
        ))}
      </div>

      {/* Outbox Processor Trigger Panel */}
      <section className="panel" style={{ marginTop: 16 }}>
        <div className="panelHead">
          <div>
            <span className="eyebrow">TRANSACTIONAL OUTBOX PROCESSOR</span>
            <h2>Background partner reconciliation worker</h2>
          </div>
          <button type="button" className="primary" onClick={triggerOutboxDispatch} disabled={outboxBusy}>
            <RefreshCw size={15} className={outboxBusy ? 'spin' : ''} />
            {outboxBusy ? 'Dispatching outbox…' : 'Run Outbox Worker Tick'}
          </button>
        </div>
        <p className="muted">
          Dispensing events commit atomically with a durable <code>integration_outbox</code> record. The background
          processor leases pending events, invokes partner transport clients (RMS consumption & e-Buzima dispense
          callbacks), handles exponential backoff, and escalates to dead-letter on exhaustion.
        </p>
        {outboxResult && (
          <div className="notice" style={{ marginTop: 8 }}>
            <CheckCircle2 size={16} />
            <span>
              <strong>Outbox Worker Status:</strong> {outboxResult}
            </span>
          </div>
        )}
      </section>

      {/* Partner Contract Previewer */}
      <div className="panel contract" style={{ marginTop: 16 }}>
        <div className="panelHead">
          <div>
            <span className="eyebrow">PARTNER CONTRACT PREVIEWER · FHIR R4</span>
            <h2>Inspect canonical intake contracts</h2>
          </div>
          <button type="button" onClick={() => window.open(api + '/docs', '_blank')}>
            Open API Reference <ArrowRight size={16} />
          </button>
        </div>

        <p className="muted">
          Preview the canonical partner FHIR payload below. Ingestion endpoints require server-to-server integration
          credentials; partner keys must NEVER be embedded in browser builds.
        </p>

        <label className="payloadField">
          Sample FHIR R4 Bundle Payload
          <textarea
            spellCheck={false}
            rows={14}
            value={payload}
            onChange={(e) => setPayload(e.target.value)}
            style={{ fontFamily: 'monospace', fontSize: '12px' }}
          />
        </label>

        <div className="endpointGrid" style={{ marginTop: 14 }}>
          <code>POST /api/v1/integrations/ebuzima/fhir-bundle</code>
          <code>POST /api/v1/integrations/ebuzima/prescriptions</code>
          <code>POST /api/v1/integrations/rms/stock-events</code>
          <code>POST /api/v1/integrations/outbox/dispatch-tick</code>
          <code>GET /api/v1/integrations/outbox/dead-letter</code>
          <code>POST /api/v1/integrations/sms/delivery-callback</code>
        </div>

        <div className="notice" style={{ marginTop: 14 }}>
          <Wifi size={17} />
          <span>
            Partner-specific field mapping, credentials, sandbox certification, and institutional governance remain
            prerequisites. Use synthetic payloads exclusively during testing.
          </span>
        </div>
      </div>
    </>
  );
}
