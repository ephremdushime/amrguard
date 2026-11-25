import React, { useCallback, useEffect, useState } from 'react';
import {
  CheckCircle2,
  Copy,
  KeyRound,
  Plus,
  RefreshCw,
  RotateCw,
  ShieldAlert,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { apiFetch } from '../authApi';
import type { AdminServiceClient, AdminServiceKeyIssued } from '../types';

interface ServiceClientsPanelProps {
  api: string;
  onNotify?: (msg: string) => void;
  onUnauthorized?: () => void;
}

const CANONICAL_SERVICE_SCOPES = [
  'integrations:ebuzima:prescriptions:write',
  'integrations:ebuzima:prescriptions:read',
  'integrations:ebuzima:credentials:write',
  'integrations:openmrs:prescriptions:write',
  'integrations:rms:stock:write',
  'integrations:dispensing:read',
  'stewardship:support:read',
  'integrations:sms:dispatch',
  'integrations:sms:callback',
  'integrations:sms:inbound',
  'integrations:outbox:dispatch',
];

export function ServiceClientsPanel({ api, onNotify, onUnauthorized }: ServiceClientsPanelProps) {
  const [clients, setClients] = useState<AdminServiceClient[]>([]);
  const [loading, setLoading] = useState(false);
  const [issuedKey, setIssuedKey] = useState<AdminServiceKeyIssued | null>(null);
  const [error, setError] = useState('');

  // Create form
  const [clientCode, setClientCode] = useState('');
  const [name, setName] = useState('');
  const [partnerType, setPartnerType] = useState<'EMR' | 'SUPPLY_CHAIN' | 'INTEGRATION_GATEWAY' | 'SYSTEM_WORKER'>('EMR');
  const [scope, setScope] = useState(CANONICAL_SERVICE_SCOPES[0]);
  const [facilityId, setFacilityId] = useState('1');
  const [pharmacyId, setPharmacyId] = useState('');
  const [expiresInDays, setExpiresInDays] = useState(90);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  const loadClients = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch(`${api}/api/v1/admin/service-clients`);
      if (res.status === 401) {
        onUnauthorized?.();
        return;
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || 'Unable to load service clients');
      }
      setClients(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load service clients');
    } finally {
      setLoading(false);
    }
  }, [api, onUnauthorized]);

  useEffect(() => {
    loadClients();
  }, [loadClients]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    setError('');
    try {
      const res = await apiFetch(`${api}/api/v1/admin/service-clients`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_code: clientCode.trim(),
          name: name.trim(),
          partner_type: partnerType,
          expires_in_days: expiresInDays,
          scopes: [
            {
              scope,
              facility_id: facilityId.trim() ? Number(facilityId) : null,
              pharmacy_id: pharmacyId.trim() ? Number(pharmacyId) : null,
            },
          ],
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to provision service client');
      setIssuedKey(body as AdminServiceKeyIssued);
      setClientCode('');
      setName('');
      onNotify?.(`Provisioned partner service client ${body.client_code}`);
      await loadClients();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Service client creation failed');
    } finally {
      setCreating(false);
    }
  };

  const handleRotate = async (clientId: number, revokePrevious: boolean) => {
    setBusyId(clientId);
    setError('');
    try {
      const res = await apiFetch(`${api}/api/v1/admin/service-clients/${clientId}/rotate-key`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revoke_previous: revokePrevious, expires_in_days: 90 }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Key rotation failed');
      setIssuedKey(body as AdminServiceKeyIssued);
      onNotify?.(`Rotated service key for ${body.client_code} (${body.revoked_previous_count} prior revoked)`);
      await loadClients();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Key rotation failed');
    } finally {
      setBusyId(null);
    }
  };

  const handleRevokeCredential = async (clientId: number, credId: number) => {
    setBusyId(credId);
    setError('');
    try {
      const res = await apiFetch(`${api}/api/v1/admin/service-clients/${clientId}/credentials/${credId}/revoke`, {
        method: 'POST',
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Revocation failed');
      onNotify?.(`Revoked credential ${body.key_prefix}`);
      await loadClients();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Credential revocation failed');
    } finally {
      setBusyId(null);
    }
  };

  const copyApiKey = async () => {
    if (!issuedKey) return;
    try {
      await navigator.clipboard.writeText(issuedKey.api_key);
      onNotify?.('Copied one-time API key to clipboard');
    } catch {
      onNotify?.('Copy manually from the one-time disclosure box');
    }
  };

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="pageTitle">
        <div>
          <span className="eyebrow">PLATFORM CREDENTIAL LIFECYCLE · MACHINE-TO-MACHINE</span>
          <h1>Partner Service Clients & Key Rotation</h1>
          <p>
            Provision strictly scoped machine credentials for e-Buzima, OpenMRS, RMS/eLMIS, and SMS gateways. Secrets
            are stored strictly as keyed HMAC-SHA256 digests and disclosed only once upon creation or rotation.
          </p>
        </div>
        <button type="button" onClick={loadClients} disabled={loading} className="sourceBadge" style={{ cursor: 'pointer' }}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> {clients.length} service clients
        </button>
      </div>

      {issuedKey && (
        <section
          className="panel"
          style={{ borderColor: '#82b7a0', background: '#f2faf5', display: 'grid', gap: 10 }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <CheckCircle2 size={18} color="#126b5b" />
              <strong>One-Time Service Key Issued — {issuedKey.client_code}</strong>
            </div>
            <button
              type="button"
              className="primary"
              onClick={copyApiKey}
              style={{ minHeight: 30, padding: '0 12px', display: 'inline-flex', alignItems: 'center', gap: 6 }}
            >
              <Copy size={13} /> Copy Key
            </button>
          </div>
          <pre className="codeBlock" style={{ margin: 0 }}>
            x-amrguard-integration-key: {issuedKey.api_key}
          </pre>
          <small style={{ color: '#2b5849' }}>
            {issuedKey.disclosure_notice} · Prefix: <code>{issuedKey.key_prefix}</code> · Expires:{' '}
            {issuedKey.expires_at ? new Date(issuedKey.expires_at).toLocaleString() : 'Never'}
          </small>
        </section>
      )}

      {error && (
        <div className="result errorBox" style={{ marginTop: 0 }}>
          <ShieldAlert size={16} />
          <div>
            <b>Service client operation error</b>
            <span>{error}</span>
          </div>
        </div>
      )}

      <div className="twoCol" style={{ margin: 0, maxWidth: 'none' }}>
        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">PROVISIONED PARTNER CLIENTS</span>
              <h2>Active Clients & Credentials ({clients.length})</h2>
            </div>
            <KeyRound size={17} />
          </div>

          <div style={{ marginTop: 12, display: 'grid', gap: 12, maxHeight: 540, overflowY: 'auto' }}>
            {clients.map((c) => (
              <div key={c.id} className="kpiTile" style={{ display: 'grid', gap: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 6 }}>
                  <div>
                    <strong>{c.name}</strong>{' '}
                    <code>{c.client_code}</code>
                    <div style={{ fontSize: 10, color: 'var(--muted)' }}>Partner Type: {c.partner_type}</div>
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button
                      type="button"
                      className="primary"
                      disabled={busyId === c.id}
                      onClick={() => handleRotate(c.id, true)}
                      style={{ minHeight: 28, padding: '0 10px', display: 'inline-flex', alignItems: 'center', gap: 5 }}
                    >
                      <RotateCw size={12} /> Rotate (Revoke Old)
                    </button>
                    <button
                      type="button"
                      disabled={busyId === c.id}
                      onClick={() => handleRotate(c.id, false)}
                      style={{
                        minHeight: 28,
                        padding: '0 10px',
                        border: '1px solid var(--line)',
                        borderRadius: 5,
                        background: '#fff',
                        fontSize: 10,
                      }}
                    >
                      Dual-Key Overlap
                    </button>
                  </div>
                </div>

                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                  {c.scopes.map((sc) => (
                    <span key={sc.id} className="statusPill">
                      {sc.scope}
                      {sc.facility_id ? ` [Fac #${sc.facility_id}]` : ''}
                      {sc.pharmacy_id ? ` [Ph #${sc.pharmacy_id}]` : ''}
                    </span>
                  ))}
                </div>

                <div style={{ borderTop: '1px solid var(--line)', paddingTop: 6 }}>
                  {c.credentials.map((cred) => (
                    <div
                      key={cred.id}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: 11,
                        padding: '4px 0',
                      }}
                    >
                      <span>
                        <code>{cred.key_prefix}.••••••••</code>{' '}
                        <span className={`statusPill ${cred.active ? 'success' : 'dangerPill'}`}>
                          {cred.active ? 'ACTIVE' : 'REVOKED/EXPIRED'}
                        </span>
                      </span>
                      {cred.active && (
                        <button
                          type="button"
                          disabled={busyId === cred.id}
                          onClick={() => handleRevokeCredential(c.id, cred.id)}
                          style={{
                            border: '1px solid #ebc6bd',
                            background: '#fbefec',
                            color: '#a34d46',
                            borderRadius: 5,
                            padding: '2px 7px',
                            fontSize: 10,
                          }}
                        >
                          <XCircle size={11} style={{ verticalAlign: 'middle', marginRight: 3 }} /> Revoke
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">NEW PARTNER CREDENTIAL</span>
              <h2>Provision Scoped Service Client</h2>
            </div>
            <ShieldCheck size={17} />
          </div>
          <form onSubmit={handleCreate} className="reviewForm" style={{ marginTop: 12, background: 'transparent', border: 0, padding: 0 }}>
            <label>
              Client Code
              <input
                required
                minLength={3}
                value={clientCode}
                onChange={(e) => setClientCode(e.target.value)}
                placeholder="e.g. openmrs-kigali-hospital"
              />
            </label>
            <label>
              Display Name
              <input
                required
                minLength={2}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Kigali Teaching Hospital OpenMRS Adapter"
              />
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <label>
                Partner Type
                <select
                  value={partnerType}
                  onChange={(e) =>
                    setPartnerType(e.target.value as 'EMR' | 'SUPPLY_CHAIN' | 'INTEGRATION_GATEWAY' | 'SYSTEM_WORKER')
                  }
                >
                  <option value="EMR">EMR</option>
                  <option value="SUPPLY_CHAIN">SUPPLY_CHAIN</option>
                  <option value="INTEGRATION_GATEWAY">INTEGRATION_GATEWAY</option>
                  <option value="SYSTEM_WORKER">SYSTEM_WORKER</option>
                </select>
              </label>
              <label>
                Key Expiry (Days)
                <input
                  required
                  type="number"
                  min={1}
                  max={365}
                  value={expiresInDays}
                  onChange={(e) => setExpiresInDays(Number(e.target.value))}
                />
              </label>
            </div>
            <label>
              Initial Scope
              <select value={scope} onChange={(e) => setScope(e.target.value)}>
                {CANONICAL_SERVICE_SCOPES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <label>
                Bound Facility ID (Optional)
                <input
                  type="number"
                  min={1}
                  value={facilityId}
                  onChange={(e) => setFacilityId(e.target.value)}
                  placeholder="e.g. 1"
                />
              </label>
              <label>
                Bound Pharmacy ID (Optional)
                <input
                  type="number"
                  min={1}
                  value={pharmacyId}
                  onChange={(e) => setPharmacyId(e.target.value)}
                  placeholder="Optional"
                />
              </label>
            </div>
            <button className="primary full" type="submit" disabled={creating}>
              <Plus size={15} />
              {creating ? 'Provisioning client…' : 'Create Client & Issue Key'}
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}
