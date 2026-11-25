import React, { useCallback, useEffect, useState } from 'react';
import {
  Building2,
  CheckCircle2,
  Network,
  Plus,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  Unlock,
  UserPlus,
  Users,
  XCircle,
} from 'lucide-react';
import { apiFetch } from '../authApi';
import type {
  AdminFacility,
  AdminOrganization,
  AdminPharmacy,
  AdminPharmacyNetwork,
  AdminRole,
  AdminUser,
} from '../types';

interface StaffAndFacilityAdminPanelProps {
  api: string;
  isPlatformOperator: boolean;
  onNotify?: (msg: string) => void;
  onUnauthorized?: () => void;
}

export function StaffAndFacilityAdminPanel({
  api,
  isPlatformOperator,
  onNotify,
  onUnauthorized,
}: StaffAndFacilityAdminPanelProps) {
  const [orgs, setOrgs] = useState<AdminOrganization[]>([]);
  const [facilities, setFacilities] = useState<AdminFacility[]>([]);
  const [pharmacies, setPharmacies] = useState<AdminPharmacy[]>([]);
  const [networks, setNetworks] = useState<AdminPharmacyNetwork[]>([]);
  const [roles, setRoles] = useState<AdminRole[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [feedback, setFeedback] = useState('');

  // New user form
  const [newUsername, setNewUsername] = useState('');
  const [newDisplayName, setNewDisplayName] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRoleCode, setNewRoleCode] = useState('pharmacist');
  const [newScopeType, setNewScopeType] = useState<'FACILITY' | 'PHARMACY' | 'NATIONAL_AGGREGATE' | 'PLATFORM'>('PHARMACY');
  const [newFacilityId, setNewFacilityId] = useState<number>(0);
  const [newPharmacyId, setNewPharmacyId] = useState<number>(0);

  // New facility / pharmacy / network forms
  const [facCode, setFacCode] = useState('');
  const [facName, setFacName] = useState('');
  const [facDistrict, setFacDistrict] = useState('Gasabo');
  const [facOrgId, setFacOrgId] = useState<number>(0);

  const [phCode, setPhCode] = useState('');
  const [phName, setPhName] = useState('');
  const [phDistrict, setPhDistrict] = useState('Gasabo');
  const [phFacilityId, setPhFacilityId] = useState<number>(0);
  const [phType, setPhType] = useState<'FACILITY_PHARMACY' | 'COMMUNITY_RETAIL' | 'NETWORK_PARTNER'>('FACILITY_PHARMACY');

  const [netCode, setNetCode] = useState('');
  const [netName, setNetName] = useState('');

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [orgRes, facRes, phRes, netRes, roleRes, userRes] = await Promise.all([
        apiFetch(`${api}/api/v1/admin/organizations`),
        apiFetch(`${api}/api/v1/admin/facilities`),
        apiFetch(`${api}/api/v1/admin/pharmacies`),
        apiFetch(`${api}/api/v1/admin/networks`),
        apiFetch(`${api}/api/v1/admin/roles`),
        apiFetch(`${api}/api/v1/admin/users`),
      ]);
      if ([orgRes, facRes, phRes, netRes, roleRes, userRes].some((r) => r.status === 401)) {
        onUnauthorized?.();
        return;
      }
      const orgList: AdminOrganization[] = orgRes.ok ? await orgRes.json() : [];
      const facList: AdminFacility[] = facRes.ok ? await facRes.json() : [];
      const phList: AdminPharmacy[] = phRes.ok ? await phRes.json() : [];
      const netList: AdminPharmacyNetwork[] = netRes.ok ? await netRes.json() : [];
      const roleList: AdminRole[] = roleRes.ok ? await roleRes.json() : [];
      const userList: AdminUser[] = userRes.ok ? await userRes.json() : [];

      setOrgs(orgList);
      setFacilities(facList);
      setPharmacies(phList);
      setNetworks(netList);
      setRoles(roleList);
      setUsers(userList);

      if (orgList[0] && !facOrgId) setFacOrgId(orgList[0].id);
      if (facList[0]) {
        if (!newFacilityId) setNewFacilityId(facList[0].id);
        if (!phFacilityId) setPhFacilityId(facList[0].id);
      }
      if (phList[0] && !newPharmacyId) setNewPharmacyId(phList[0].id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load governance directory');
    } finally {
      setLoading(false);
    }
  }, [api, facOrgId, newFacilityId, newPharmacyId, phFacilityId, onUnauthorized]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setFeedback('');
    try {
      const initialScope: Record<string, unknown> = {
        role_code: newRoleCode,
        scope_type: newScopeType,
      };
      if (newScopeType === 'FACILITY') initialScope.facility_id = newFacilityId;
      if (newScopeType === 'PHARMACY') initialScope.pharmacy_id = newPharmacyId;

      const res = await apiFetch(`${api}/api/v1/admin/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: newUsername.trim(),
          display_name: newDisplayName.trim(),
          email: newEmail.trim() || undefined,
          auth_provider: 'local',
          password: newPassword,
          initial_scope: initialScope,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to provision user');
      const msg = `Provisioned staff account ${body.username} (${newRoleCode} · ${newScopeType}).`;
      setFeedback(msg);
      onNotify?.(msg);
      setNewUsername('');
      setNewDisplayName('');
      setNewEmail('');
      setNewPassword('');
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create user');
    }
  };

  const handleToggleUser = async (u: AdminUser, patch: { active?: boolean; unlock?: boolean }) => {
    setError('');
    setFeedback('');
    try {
      const res = await apiFetch(`${api}/api/v1/admin/users/${u.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to update user');
      const msg = patch.unlock
        ? `Unlocked account ${u.username}.`
        : `Account ${u.username} is now ${body.active ? 'ACTIVE' : 'DISABLED'}.`;
      setFeedback(msg);
      onNotify?.(msg);
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'User update failed');
    }
  };

  const handleRevokeScope = async (userId: number, scopeId: number) => {
    setError('');
    setFeedback('');
    try {
      const res = await apiFetch(`${api}/api/v1/admin/users/${userId}/role-scopes/${scopeId}/revoke`, {
        method: 'POST',
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to revoke scope');
      const msg = `Revoked role scope #${scopeId} (${body.role_code}).`;
      setFeedback(msg);
      onNotify?.(msg);
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scope revocation failed');
    }
  };

  const handleCreateFacility = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setFeedback('');
    try {
      const res = await apiFetch(`${api}/api/v1/admin/facilities`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: facCode.trim(),
          name: facName.trim(),
          district: facDistrict.trim(),
          organization_id: facOrgId || undefined,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to create facility');
      const msg = `Provisioned facility ${body.code} (${body.name}).`;
      setFeedback(msg);
      onNotify?.(msg);
      setFacCode('');
      setFacName('');
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Facility creation failed');
    }
  };

  const handleCreatePharmacy = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setFeedback('');
    try {
      const res = await apiFetch(`${api}/api/v1/admin/pharmacies`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: phCode.trim(),
          name: phName.trim(),
          district: phDistrict.trim(),
          facility_id: phType === 'FACILITY_PHARMACY' ? phFacilityId || undefined : undefined,
          pharmacy_type: isPlatformOperator ? phType : 'FACILITY_PHARMACY',
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to create pharmacy');
      const msg = `Provisioned pharmacy ${body.code} (${body.name}).`;
      setFeedback(msg);
      onNotify?.(msg);
      setPhCode('');
      setPhName('');
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Pharmacy creation failed');
    }
  };

  const handleCreateNetwork = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setFeedback('');
    try {
      const res = await apiFetch(`${api}/api/v1/admin/networks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: netCode.trim(), name: netName.trim() }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Unable to create pharmacy network');
      const msg = `Created cross-facility dispensing network ${body.code}.`;
      setFeedback(msg);
      onNotify?.(msg);
      setNetCode('');
      setNetName('');
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network creation failed');
    }
  };

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="pageTitle">
        <div>
          <span className="eyebrow">
            {isPlatformOperator ? 'PLATFORM IDENTITY & TENANCY GOVERNANCE' : 'FACILITY STAFF & PHARMACY GOVERNANCE'}
          </span>
          <h1>
            {isPlatformOperator
              ? 'Organizations, Facilities, Networks & Staff Identity'
              : 'Facility Staff Accounts, Role Scopes & Pharmacies'}
          </h1>
          <p>
            {isPlatformOperator
              ? 'Centrally govern organizations, health facilities, cross-facility dispensing networks, and institutional staff role scopes with full append-only audit trails.'
              : 'Provision and manage staff role scopes and facility pharmacies strictly within your authorized facility boundary. Privilege escalation to national or platform roles is blocked server-side.'}
          </p>
        </div>
        <button type="button" onClick={loadAll} disabled={loading} className="sourceBadge" style={{ cursor: 'pointer' }}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} />
          {users.length} users · {facilities.length} facilities · {pharmacies.length} pharmacies
        </button>
      </div>

      {feedback && (
        <div className="result successBox" style={{ marginTop: 0 }}>
          <CheckCircle2 size={16} />
          <div>
            <b>Governance change applied</b>
            <span>{feedback}</span>
          </div>
        </div>
      )}

      {error && (
        <div className="result errorBox" style={{ marginTop: 0 }}>
          <TriangleAlert size={16} />
          <div>
            <b>Governance action denied</b>
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Staff Directory + Provisioning */}
      <div className="twoCol" style={{ margin: 0, maxWidth: 'none' }}>
        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">SCOPED HUMAN DIRECTORY</span>
              <h2>Staff Accounts & Role Scopes ({users.length})</h2>
            </div>
            <Users size={17} />
          </div>
          <div style={{ marginTop: 12, maxHeight: 420, overflowY: 'auto', display: 'grid', gap: 8 }}>
            {users.map((u) => (
              <div key={u.id} className="kpiTile" style={{ display: 'grid', gap: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 6 }}>
                  <div>
                    <strong>{u.display_name}</strong>{' '}
                    <code>{u.username}</code>
                    {u.email && <small style={{ display: 'block', color: 'var(--muted)' }}>{u.email}</small>}
                  </div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <span className={`statusPill ${u.active ? 'success' : 'dangerPill'}`}>
                      {u.active ? 'ACTIVE' : 'DISABLED'}
                    </span>
                    {u.locked_until && (
                      <button
                        type="button"
                        onClick={() => handleToggleUser(u, { unlock: true })}
                        style={{ minHeight: 26, padding: '0 8px', border: '1px solid var(--line)', borderRadius: 5, background: '#fff', fontSize: 10 }}
                      >
                        <Unlock size={11} style={{ marginRight: 3, verticalAlign: 'middle' }} /> Unlock
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => handleToggleUser(u, { active: !u.active })}
                      style={{ minHeight: 26, padding: '0 8px', border: '1px solid var(--line)', borderRadius: 5, background: '#fff', fontSize: 10 }}
                    >
                      {u.active ? 'Disable' : 'Reactivate'}
                    </button>
                  </div>
                </div>

                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {u.scopes
                    .filter((sc) => sc.active)
                    .map((sc) => (
                      <span
                        key={sc.id}
                        className="sourceBadge"
                        style={{ padding: '4px 8px', fontSize: 10 }}
                      >
                        <ShieldCheck size={11} />
                        {sc.role_code} · {sc.scope_type}
                        {sc.facility_id ? ` #${sc.facility_id}` : ''}
                        {sc.pharmacy_id ? ` #${sc.pharmacy_id}` : ''}
                        <button
                          type="button"
                          title="Revoke scope"
                          onClick={() => handleRevokeScope(u.id, sc.id)}
                          style={{ background: 'none', border: 0, padding: 0, marginLeft: 4, color: '#a34d46' }}
                        >
                          <XCircle size={12} />
                        </button>
                      </span>
                    ))}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">PROVISION STAFF ACCOUNT</span>
              <h2>Create Scoped Institutional User</h2>
            </div>
            <UserPlus size={17} />
          </div>
          <form onSubmit={handleCreateUser} className="reviewForm" style={{ marginTop: 12, background: 'transparent', border: 0, padding: 0 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <label>
                Username
                <input
                  required
                  minLength={3}
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  placeholder="e.g. kigali.pharmacist2"
                />
              </label>
              <label>
                Display Name
                <input
                  required
                  minLength={2}
                  value={newDisplayName}
                  onChange={(e) => setNewDisplayName(e.target.value)}
                  placeholder="e.g. Aline Uwase"
                />
              </label>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <label>
                Email (Optional)
                <input
                  type="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  placeholder="staff@hospital.gov.rw"
                />
              </label>
              <label>
                Initial Password (min 12 chars)
                <input
                  required
                  type="password"
                  minLength={12}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Strong pilot password"
                />
              </label>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <label>
                Assigned Canonical Role
                <select value={newRoleCode} onChange={(e) => setNewRoleCode(e.target.value)}>
                  {roles.map((r) => (
                    <option key={r.code} value={r.code}>
                      {r.code}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Explicit Scope Type
                <select
                  value={newScopeType}
                  onChange={(e) =>
                    setNewScopeType(e.target.value as 'FACILITY' | 'PHARMACY' | 'NATIONAL_AGGREGATE' | 'PLATFORM')
                  }
                >
                  <option value="PHARMACY">PHARMACY</option>
                  <option value="FACILITY">FACILITY</option>
                  {isPlatformOperator && <option value="NATIONAL_AGGREGATE">NATIONAL_AGGREGATE</option>}
                  {isPlatformOperator && <option value="PLATFORM">PLATFORM</option>}
                </select>
              </label>
            </div>

            {newScopeType === 'FACILITY' && (
              <label>
                Target Facility
                <select value={newFacilityId} onChange={(e) => setNewFacilityId(Number(e.target.value))}>
                  {facilities.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name} ({f.code})
                    </option>
                  ))}
                </select>
              </label>
            )}

            {newScopeType === 'PHARMACY' && (
              <label>
                Target Pharmacy
                <select value={newPharmacyId} onChange={(e) => setNewPharmacyId(Number(e.target.value))}>
                  {pharmacies.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.code})
                    </option>
                  ))}
                </select>
              </label>
            )}

            <button className="primary full" type="submit">
              <UserPlus size={15} /> Provision User & Role Scope
            </button>
          </form>
        </section>
      </div>

      {/* Pharmacies, Facilities & Networks */}
      <div className="twoCol" style={{ margin: 0, maxWidth: 'none' }}>
        <section className="panel">
          <div className="panelHead">
            <div>
              <span className="eyebrow">PHARMACY PROVISIONING</span>
              <h2>Register Dispensing Location</h2>
            </div>
            <Building2 size={17} />
          </div>
          <form onSubmit={handleCreatePharmacy} className="reviewForm" style={{ marginTop: 12, background: 'transparent', border: 0, padding: 0 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <label>
                Pharmacy Code
                <input required value={phCode} onChange={(e) => setPhCode(e.target.value)} placeholder="e.g. PHA-KGL-002" />
              </label>
              <label>
                District
                <input required value={phDistrict} onChange={(e) => setPhDistrict(e.target.value)} />
              </label>
            </div>
            <label>
              Pharmacy Name
              <input required value={phName} onChange={(e) => setPhName(e.target.value)} placeholder="e.g. Outpatient Pharmacy Wing B" />
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <label>
                Linked Facility
                <select value={phFacilityId} onChange={(e) => setPhFacilityId(Number(e.target.value))}>
                  {facilities.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name} ({f.code})
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Pharmacy Type
                <select
                  value={phType}
                  disabled={!isPlatformOperator}
                  onChange={(e) => setPhType(e.target.value as 'FACILITY_PHARMACY' | 'COMMUNITY_RETAIL' | 'NETWORK_PARTNER')}
                >
                  <option value="FACILITY_PHARMACY">FACILITY_PHARMACY</option>
                  {isPlatformOperator && <option value="COMMUNITY_RETAIL">COMMUNITY_RETAIL</option>}
                  {isPlatformOperator && <option value="NETWORK_PARTNER">NETWORK_PARTNER</option>}
                </select>
              </label>
            </div>
            <button className="primary full" type="submit">
              <Plus size={15} /> Register Pharmacy
            </button>
          </form>
        </section>

        {isPlatformOperator ? (
          <section className="panel" style={{ display: 'grid', gap: 16 }}>
            <div>
              <div className="panelHead">
                <div>
                  <span className="eyebrow">FACILITY PROVISIONING</span>
                  <h2>Onboard Health Facility</h2>
                </div>
                <Building2 size={17} />
              </div>
              <form onSubmit={handleCreateFacility} className="reviewForm" style={{ marginTop: 10, background: 'transparent', border: 0, padding: 0 }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <label>
                    Facility Code
                    <input required value={facCode} onChange={(e) => setFacCode(e.target.value)} placeholder="e.g. FAC-HGL-002" />
                  </label>
                  <label>
                    District
                    <input required value={facDistrict} onChange={(e) => setFacDistrict(e.target.value)} />
                  </label>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8 }}>
                  <label>
                    Facility Name
                    <input required value={facName} onChange={(e) => setFacName(e.target.value)} placeholder="e.g. Nyarugenge District Hospital" />
                  </label>
                  <label>
                    Organization
                    <select value={facOrgId} onChange={(e) => setFacOrgId(Number(e.target.value))}>
                      {orgs.map((o) => (
                        <option key={o.id} value={o.id}>
                          {o.code}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <button className="primary full" type="submit">
                  <Plus size={15} /> Provision Facility
                </button>
              </form>
            </div>

            <div style={{ borderTop: '1px solid var(--line)', paddingTop: 14 }}>
              <div className="panelHead">
                <div>
                  <span className="eyebrow">ADR-001 CONDITIONAL CROSS-FACILITY NETWORKS ({networks.length})</span>
                  <h2>Create Pharmacy Network</h2>
                </div>
                <Network size={17} />
              </div>
              <form onSubmit={handleCreateNetwork} style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
                <input
                  required
                  value={netCode}
                  onChange={(e) => setNetCode(e.target.value)}
                  placeholder="NET-KGL-001"
                  style={{ flex: '1 1 120px', height: 34, padding: '0 8px', border: '1px solid var(--line)', borderRadius: 6 }}
                />
                <input
                  required
                  value={netName}
                  onChange={(e) => setNetName(e.target.value)}
                  placeholder="Kigali Approved Retail Network"
                  style={{ flex: '2 1 180px', height: 34, padding: '0 8px', border: '1px solid var(--line)', borderRadius: 6 }}
                />
                <button type="submit" className="primary" style={{ height: 34, padding: '0 12px' }}>
                  Create Network
                </button>
              </form>
            </div>
          </section>
        ) : (
          <section className="panel">
            <div className="panelHead">
              <div>
                <span className="eyebrow">CROSS-FACILITY DISPENSING NETWORKS</span>
                <h2>Authorized Networks ({networks.length})</h2>
              </div>
              <Network size={17} />
            </div>
            <p className="muted" style={{ marginTop: 8 }}>
              Conditional cross-facility dispensing (ADR-001 Decision 2) is disabled by default and requires an active
              network agreement provisioned by Platform Administration.
            </p>
            <div style={{ marginTop: 10, display: 'grid', gap: 8 }}>
              {networks.length ? (
                networks.map((n) => (
                  <div key={n.id} className="kpiTile">
                    <strong>
                      {n.name} (<code>{n.code}</code>)
                    </strong>
                    <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                      {n.facilities.length} facilities · {n.pharmacies.length} pharmacies
                    </div>
                  </div>
                ))
              ) : (
                <p className="muted">No cross-facility networks linked to this facility.</p>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
