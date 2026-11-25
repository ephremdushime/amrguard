import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  Building2,
  CheckCircle2,
  FileCheck2,
  Globe2,
  LockKeyhole,
  Pill,
  Server,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react';
import { apiFetch, setCsrfToken, type AuthUser } from './authApi';
import { AuthHeader } from './components/AuthHeader';
import { LoginForm } from './components/LoginForm';
import {
  getAuthorizedWorkspaces,
  getDefaultPathForUser,
  resolveWorkspaceRoute,
  useBrowserPath,
  type WorkspaceId,
} from './workspaceRouting';
import { FacilityAdminWorkspace } from './workspaces/FacilityAdminWorkspace';
import { NationalIntelligenceWorkspace } from './workspaces/NationalIntelligenceWorkspace';
import { PharmacyWorkspace } from './workspaces/PharmacyWorkspace';
import { PlatformAdminWorkspace } from './workspaces/PlatformAdminWorkspace';
import { PrescriberWorkspace } from './workspaces/PrescriberWorkspace';
import { StewardshipWorkspace } from './workspaces/StewardshipWorkspace';
import './style.css';
import './style-v2.css';

const API = import.meta.env.VITE_API_URL || (import.meta.env.PROD ? '' : 'http://localhost:8000');
const IS_DEV = Boolean(import.meta.env.DEV);

const WORKSPACE_ICONS: Record<WorkspaceId, React.ComponentType<{ size?: number }>> = {
  pharmacy: Pill,
  prescriber: FileCheck2,
  stewardship: Activity,
  'facility-admin': Building2,
  national: Globe2,
  platform: Server,
};

function App() {
  const [authChecked, setAuthChecked] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [online, setOnline] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [toast, setToast] = useState('');

  const { pathname, navigate } = useBrowserPath();

  const notify = useCallback((msg: string) => {
    setToast(msg);
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(''), 5500);
    return () => clearTimeout(timer);
  }, [toast]);

  const checkSession = useCallback(async () => {
    try {
      const health = await fetch(`${API}/health`);
      setOnline(health.ok);
      const me = await apiFetch(`${API}/api/v1/auth/me`);
      if (me.ok) {
        const currentUser: AuthUser = await me.json();
        setUser(currentUser);
      } else {
        setUser(null);
      }
    } catch {
      setOnline(false);
      setUser(null);
    } finally {
      setAuthChecked(true);
    }
  }, []);

  useEffect(() => {
    checkSession();
  }, [checkSession]);

  const authorizedWorkspaces = useMemo(
    () => (user ? getAuthorizedWorkspaces(user, IS_DEV) : []),
    [user],
  );

  const resolved = useMemo(
    () => (user ? resolveWorkspaceRoute(pathname, user, IS_DEV) : null),
    [pathname, user],
  );

  // Redirect root or workspace base path to the user's primary authorized operational route
  useEffect(() => {
    if (user && resolved && resolved.status === 'redirect' && resolved.redirectTo) {
      navigate(resolved.redirectTo, { replace: true });
    }
  }, [user, resolved, navigate]);

  const handleAuthenticated = (signedIn: AuthUser) => {
    if (signedIn.csrf_token) setCsrfToken(signedIn.csrf_token);
    setUser(signedIn);
    const defaultPath = getDefaultPathForUser(signedIn, IS_DEV);
    navigate(defaultPath, { replace: true });
  };

  const handleUnauthorized = useCallback(() => {
    setCsrfToken('');
    setUser(null);
    setToast('Session expired — please sign in again');
  }, []);

  const handleSignOut = async () => {
    try {
      await apiFetch(`${API}/api/v1/auth/logout`, { method: 'POST' });
    } finally {
      setCsrfToken('');
      setUser(null);
      navigate('/', { replace: true });
      setToast('Signed out');
    }
  };

  if (!authChecked) {
    return (
      <div className="app">
        <main style={{ marginLeft: 0, width: '100%' }}>
          <div className="panel" style={{ maxWidth: 460, margin: '80px auto', textAlign: 'center' }}>
            <span className="eyebrow">AMRGUARD SECURITY BOUNDARY</span>
            <h2>Validating institutional session…</h2>
            <p className="muted">Checking session cookie, CSRF posture, and role scopes.</p>
          </div>
        </main>
      </div>
    );
  }

  if (!user) {
    return <LoginForm api={API} online={online} onAuthenticated={handleAuthenticated} />;
  }

  // Fallback if an authenticated account has no active workspace role scopes
  if (authorizedWorkspaces.length === 0) {
    return (
      <div className="app">
        <main style={{ marginLeft: 0, width: '100%' }}>
          <div className="panel" style={{ maxWidth: 520, margin: '80px auto', display: 'grid', gap: 14 }}>
            <span className="eyebrow">RBAC PROVISIONING REQUIRED</span>
            <h2>No operational workspace assigned</h2>
            <p className="muted">
              Account <b>{user.username || user.actor_id}</b> is authenticated, but holds no active institutional role
              scope. Contact your facility administrator or institutional IdP coordinator.
            </p>
            <button type="button" className="primary" onClick={handleSignOut}>
              Sign out
            </button>
          </div>
        </main>
      </div>
    );
  }

  const activeWorkspace =
    resolved?.status === 'authorized' && resolved.workspace
      ? resolved.workspace
      : authorizedWorkspaces[0];

  const activeSection =
    resolved?.status === 'authorized' && resolved.section
      ? resolved.section
      : activeWorkspace.sections[0];

  const ActiveWorkspaceIcon = WORKSPACE_ICONS[activeWorkspace.id];

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandMark">
            <ShieldCheck size={22} />
          </div>
          <div>
            <strong>AMRGuard</strong>
            <span>Institutional Stewardship Layer</span>
          </div>
        </div>

        {/* Multi-role workspace switcher (shown ONLY when user holds >1 authorized workspace) */}
        {authorizedWorkspaces.length > 1 ? (
          <div className="workspaceSwitcher">
            <span className="demoLabel" style={{ margin: '18px 4px 6px' }}>
              AUTHORIZED WORKSPACES ({authorizedWorkspaces.length})
            </span>
            <div className="workspaceSwitcherList">
              {authorizedWorkspaces.map((ws) => {
                const Icon = WORKSPACE_ICONS[ws.id];
                const isActive = ws.id === activeWorkspace.id && resolved?.status !== 'forbidden';
                return (
                  <button
                    key={ws.id}
                    type="button"
                    className={`wsSwitchBtn ${isActive ? 'active' : ''}`}
                    onClick={() => navigate(ws.sections[0]?.path || ws.basePath)}
                  >
                    <Icon size={14} />
                    <span>{ws.shortLabel}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="workspaceBadgeBox">
            <ActiveWorkspaceIcon size={15} />
            <div>
              <small>{activeWorkspace.eyebrow}</small>
              <strong>{activeWorkspace.label}</strong>
            </div>
          </div>
        )}

        <div className="demoLabel" style={{ marginTop: 18 }}>
          {activeWorkspace.label.toUpperCase()}
        </div>

        <nav aria-label={`${activeWorkspace.label} navigation`}>
          {activeWorkspace.sections.map((sec) => {
            const isActive = resolved?.status === 'authorized' && sec.id === activeSection.id;
            return (
              <button
                type="button"
                key={sec.id}
                className={isActive ? 'active' : ''}
                onClick={() => navigate(sec.path)}
                title={sec.description}
              >
                {sec.label}
              </button>
            );
          })}
        </nav>

        <div className="sideFoot">
          <span className={online ? 'live' : 'demoDot'} />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600, color: '#e6f4ee', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {user.display_name || user.username}
            </div>
            <small style={{ display: 'block', marginLeft: 0 }}>{user.roles.join(' · ')}</small>
          </div>
        </div>
      </aside>

      <main>
        <AuthHeader
          user={user}
          workspaceLabel={
            resolved?.status === 'forbidden' ? 'Access Boundary' : activeWorkspace.label
          }
          sectionLabel={
            resolved?.status === 'forbidden' ? 'Restricted Route' : activeSection.label
          }
          online={online}
          onRefresh={() => setRefreshKey((k) => k + 1)}
          onSignOut={handleSignOut}
        />

        {resolved?.status === 'forbidden' ? (
          <section className="panel" style={{ maxWidth: 620, margin: '48px auto', display: 'grid', gap: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <ShieldAlert size={24} color="#b94f4d" />
              <div>
                <span className="eyebrow">RBAC WORKSPACE BOUNDARY · 403</span>
                <h2 style={{ margin: '2px 0 0' }}>Route restricted for your institutional role</h2>
              </div>
            </div>
            <p className="muted" style={{ margin: 0 }}>
              The requested path <code>{resolved.requestedPath}</code> belongs to{' '}
              <b>{resolved.workspace?.label || 'another institutional workspace'}</b>, which is not authorized for your
              assigned role(s): <code>{user.roles.join(', ')}</code>. All API endpoints independently enforce this
              boundary server-side.
            </p>
            <div style={{ display: 'flex', gap: 10 }}>
              <button
                type="button"
                className="primary"
                onClick={() => navigate(resolved.redirectTo || getDefaultPathForUser(user, IS_DEV), { replace: true })}
                style={{ minHeight: 36, padding: '0 14px', display: 'inline-flex', alignItems: 'center', gap: 7 }}
              >
                <LockKeyhole size={14} /> Return to {activeWorkspace.label}
              </button>
            </div>
          </section>
        ) : (
          <>
            {activeWorkspace.id === 'pharmacy' && (
              <PharmacyWorkspace
                api={API}
                user={user}
                activeSection={activeSection.id}
                refreshKey={refreshKey}
                onNotify={notify}
                onUnauthorized={handleUnauthorized}
              />
            )}

            {activeWorkspace.id === 'prescriber' && (
              <PrescriberWorkspace
                api={API}
                user={user}
                activeSection={activeSection.id}
                refreshKey={refreshKey}
                isDev={IS_DEV}
                onNotify={notify}
                onUnauthorized={handleUnauthorized}
              />
            )}

            {activeWorkspace.id === 'stewardship' && (
              <StewardshipWorkspace
                api={API}
                user={user}
                activeSection={activeSection.id}
                refreshKey={refreshKey}
                onNotify={notify}
                onUnauthorized={handleUnauthorized}
              />
            )}

            {activeWorkspace.id === 'facility-admin' && (
              <FacilityAdminWorkspace
                api={API}
                user={user}
                activeSection={activeSection.id}
                refreshKey={refreshKey}
                onNotify={notify}
                onUnauthorized={handleUnauthorized}
              />
            )}

            {activeWorkspace.id === 'national' && (
              <NationalIntelligenceWorkspace
                api={API}
                user={user}
                activeSection={activeSection.id}
                refreshKey={refreshKey}
                onNotify={notify}
                onUnauthorized={handleUnauthorized}
              />
            )}

            {activeWorkspace.id === 'platform' && (
              <PlatformAdminWorkspace
                api={API}
                user={user}
                activeSection={activeSection.id}
                refreshKey={refreshKey}
                isDev={IS_DEV}
                onNotify={notify}
                onUnauthorized={handleUnauthorized}
              />
            )}
          </>
        )}

        {toast && (
          <div className="toast" onClick={() => setToast('')} role="status">
            <CheckCircle2 size={16} />
            <span>{toast}</span>
          </div>
        )}
      </main>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
