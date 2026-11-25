import React, { useState } from 'react';
import { LockKeyhole, ShieldCheck, TriangleAlert } from 'lucide-react';
import { apiFetch, type AuthUser } from '../authApi';

interface LoginFormProps {
  api: string;
  online: boolean;
  onAuthenticated: (u: AuthUser) => void;
}

const PILOT_ACCOUNTS = [
  { username: 'demo.pharmacist', label: 'Pharmacist', workspace: 'Pharmacy Workspace' },
  { username: 'demo.assistant', label: 'Pharmacy Assistant', workspace: 'Pharmacy (Verify Only)' },
  { username: 'demo.prescriber', label: 'Prescriber', workspace: 'Prescriber Workspace' },
  { username: 'demo.steward', label: 'Stewardship Officer', workspace: 'Stewardship Workspace' },
  { username: 'demo.admin', label: 'Facility Admin', workspace: 'Facility Administration' },
  { username: 'demo.analyst', label: 'National Analyst', workspace: 'National Intelligence' },
  { username: 'demo.operator', label: 'Platform Operator', workspace: 'Platform Administration' },
  { username: 'demo.clinician', label: 'Multi-Role Clinician', workspace: '3 Clinical Workspaces' },
];

export function LoginForm({ api, online, onAuthenticated }: LoginFormProps) {
  const [username, setUsername] = useState('demo.pharmacist');
  const [password, setPassword] = useState('DemoOnly-Synthetic-Pass-2026!');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const response = await apiFetch(`${api}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.detail || 'Authentication denied');
      }
      setPassword('');
      onAuthenticated(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to sign in');
    } finally {
      setBusy(false);
    }
  };

  const selectQuickAccount = (userAccount: string) => {
    setUsername(userAccount);
    setPassword('DemoOnly-Synthetic-Pass-2026!');
    setError('');
  };

  return (
    <div className="app">
      <main style={{ marginLeft: 0, width: '100%', padding: '32px 16px' }}>
        <form
          className="panel"
          onSubmit={submit}
          style={{ maxWidth: 560, margin: '36px auto', display: 'grid', gap: 16 }}
        >
          <div className="brand" style={{ marginBottom: 4, borderBottom: '1px solid var(--line)', paddingBottom: 14 }}>
            <div className="brandMark">
              <ShieldCheck size={24} />
            </div>
            <div>
              <strong style={{ color: 'var(--ink)' }}>AMRGuard Rwanda</strong>
              <span style={{ color: 'var(--muted)' }}>
                Institutional Antibiotic Traceability & Stewardship Platform
              </span>
            </div>
          </div>

          <div className="notice" style={{ margin: '0' }}>
            <LockKeyhole size={16} />
            <span>
              <strong>Role-Scoped Institutional Boundary:</strong> Signing in routes you strictly into your authorized
              workspace. Sessions enforce Argon2id verification, HttpOnly cookies, CSRF tokens, and server-side RBAC
              tenancy isolation.
            </span>
          </div>

          <label style={{ display: 'grid', gap: 6, fontWeight: 600 }}>
            Institutional Username
            <input
              required
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="e.g. demo.pharmacist"
              style={{ height: 39, padding: '0 10px', border: '1px solid var(--line)', borderRadius: 6 }}
            />
          </label>

          <label style={{ display: 'grid', gap: 6, fontWeight: 600 }}>
            Password
            <input
              required
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{ height: 39, padding: '0 10px', border: '1px solid var(--line)', borderRadius: 6 }}
            />
          </label>

          {error && (
            <div className="result errorBox" style={{ marginTop: 0 }}>
              <TriangleAlert size={18} />
              <div>
                <b>Authentication denied</b>
                <span>{error}</span>
              </div>
            </div>
          )}

          <button className="primary full" type="submit" disabled={busy}>
            <LockKeyhole size={16} />
            {busy ? 'Authenticating…' : 'Sign in to Authorized Workspace'}
          </button>

          <div style={{ borderTop: '1px solid var(--line)', paddingTop: 14 }}>
            <span className="eyebrow" style={{ display: 'block', marginBottom: 8 }}>
              Synthetic Pilot Role Accounts (Select to Test Role-Scoped Workspaces)
            </span>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(155px, 1fr))', gap: 8 }}>
              {PILOT_ACCOUNTS.map((acc) => (
                <button
                  key={acc.username}
                  type="button"
                  className={`chipBtn ${username === acc.username ? 'activeChip' : ''}`}
                  onClick={() => selectQuickAccount(acc.username)}
                  style={{
                    padding: '8px 10px',
                    fontSize: '11px',
                    textAlign: 'left',
                    borderRadius: '6px',
                    border: username === acc.username ? '1px solid var(--green)' : '1px solid var(--line)',
                    background: username === acc.username ? '#e7f3ed' : '#fbfdfb',
                    color: 'var(--ink)',
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ fontWeight: 700 }}>{acc.label}</div>
                  <small style={{ color: 'var(--muted)', fontSize: '10px', display: 'block', marginTop: 2 }}>
                    {acc.workspace}
                  </small>
                </button>
              ))}
            </div>
          </div>

          <small className="fieldHint" style={{ textAlign: 'center', marginTop: 4 }}>
            Backend services:{' '}
            <b style={{ color: online ? '#10b981' : '#f59e0b' }}>{online ? 'Online' : 'Connecting…'}</b> ·
            Synthetic local pilot mode (OIDC required in production).
          </small>
        </form>
      </main>
    </div>
  );
}
