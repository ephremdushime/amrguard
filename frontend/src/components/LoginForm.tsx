import React, { useState } from 'react';
import { LockKeyhole, ShieldCheck, TriangleAlert, UserCheck } from 'lucide-react';
import { apiFetch, type AuthUser } from '../authApi';

interface LoginFormProps {
  api: string;
  online: boolean;
  onAuthenticated: (u: AuthUser) => void;
}

const PILOT_ACCOUNTS = [
  { username: 'demo.pharmacist', label: 'Pharmacist', role: 'Dispensing & Verification' },
  { username: 'demo.prescriber', label: 'Prescriber', role: 'Prescription Authoring' },
  { username: 'demo.steward', label: 'Stewardship Officer', role: 'Review & Monitoring' },
  { username: 'demo.admin', label: 'Facility Admin', role: 'Facility Administration' },
  { username: 'demo.operator', label: 'Platform Operator', role: 'Integration Operations' },
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
      <main style={{ marginLeft: 0, width: '100%', padding: '40px 16px' }}>
        <form className="panel" onSubmit={submit} style={{ maxWidth: 480, margin: '48px auto', display: 'grid', gap: 16 }}>
          <div className="brand" style={{ marginBottom: 4 }}>
            <div className="brandMark">
              <ShieldCheck size={24} />
            </div>
            <div>
              <strong>AMRGuard Rwanda</strong>
              <span>Antibiotic Traceability & Stewardship Platform</span>
            </div>
          </div>

          <div className="notice" style={{ margin: '4px 0' }}>
            <LockKeyhole size={16} />
            <span>
              <strong>Pilot Security Boundary:</strong> Operations require authenticated institutional identity.
              Sessions enforce Argon2id verification, HttpOnly cookies, and strict RBAC tenancy scoping.
            </span>
          </div>

          <label>
            Username
            <input
              required
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="e.g. demo.pharmacist"
            />
          </label>

          <label>
            Password
            <input
              required
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>

          {error && (
            <div className="result errorBox">
              <TriangleAlert size={18} />
              <div>
                <b>Authentication denied</b>
                <span>{error}</span>
              </div>
            </div>
          )}

          <button className="primary full" type="submit" disabled={busy}>
            <LockKeyhole size={16} />
            {busy ? 'Authenticating…' : 'Sign in to Workstation'}
          </button>

          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 14 }}>
            <span className="eyebrow" style={{ display: 'block', marginBottom: 8 }}>
              Pilot Walkthrough Accounts (Synthetic Staging)
            </span>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8 }}>
              {PILOT_ACCOUNTS.map((acc) => (
                <button
                  key={acc.username}
                  type="button"
                  className={`chipBtn ${username === acc.username ? 'activeChip' : ''}`}
                  onClick={() => selectQuickAccount(acc.username)}
                  style={{
                    padding: '6px 10px',
                    fontSize: '12px',
                    textAlign: 'left',
                    borderRadius: '6px',
                    border: '1px solid var(--border)',
                    background: username === acc.username ? 'var(--primary-subtle, #eef2ff)' : 'transparent',
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ fontWeight: 600 }}>{acc.label}</div>
                  <small style={{ color: 'var(--muted)', fontSize: '10px' }}>{acc.role}</small>
                </button>
              ))}
            </div>
          </div>

          <small className="fieldHint" style={{ textAlign: 'center', marginTop: 4 }}>
            Backend services: <b style={{ color: online ? '#10b981' : '#f59e0b' }}>{online ? 'Online' : 'Connecting…'}</b> ·
            Synthetic pilot mode strictly enforces privacy & safety rules.
          </small>
        </form>
      </main>
    </div>
  );
}
