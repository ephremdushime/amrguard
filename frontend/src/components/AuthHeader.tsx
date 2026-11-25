import React from 'react';
import { LogOut, RefreshCw, UserCheck } from 'lucide-react';
import type { AuthUser } from '../authApi';

interface AuthHeaderProps {
  user: AuthUser;
  workspaceLabel: string;
  sectionLabel: string;
  online: boolean;
  onRefresh: () => void;
  onSignOut: () => void;
}

const ROLE_LABELS: Record<string, string> = {
  pharmacist: 'Pharmacist',
  prescriber: 'Prescriber',
  pharmacy_assistant: 'Pharmacy Assistant',
  stewardship_officer: 'Stewardship Officer',
  facility_admin: 'Facility Admin',
  national_analyst: 'National Analyst',
  platform_operator: 'Platform Operator',
};

export function AuthHeader({
  user,
  workspaceLabel,
  sectionLabel,
  online,
  onRefresh,
  onSignOut,
}: AuthHeaderProps) {
  const primaryScope = user.scopes[0];
  const scopeBadge = primaryScope
    ? primaryScope.scope_type === 'PHARMACY'
      ? `Pharmacy #${primaryScope.pharmacy_id}`
      : primaryScope.scope_type === 'FACILITY'
        ? `Facility #${primaryScope.facility_id}`
        : primaryScope.scope_type.replaceAll('_', ' ')
    : 'Scoped Session';

  return (
    <header className="topbar">
      <div className="crumb">
        <span>AMRGuard</span> / <span>{workspaceLabel}</span> / <b>{sectionLabel}</b>
      </div>
      <div className="topActions">
        <div className="userContextBadge" title={`Actor ID: ${user.actor_id} · Method: ${user.auth_method}`}>
          <UserCheck size={14} />
          <b>{user.display_name || user.username}</b>
          <span className="roleTag">
            {user.roles.map((r) => ROLE_LABELS[r] || r).join(', ')}
          </span>
          <span className="scopeTag">{scopeBadge}</span>
        </div>

        <button type="button" onClick={onRefresh} title="Refresh active workspace data">
          <RefreshCw size={14} className={online ? '' : 'spin'} />
          <span>Refresh</span>
        </button>

        <button type="button" className="signOutBtn" onClick={onSignOut} title="End authenticated session">
          <LogOut size={14} />
          <span>Sign out</span>
        </button>
      </div>
    </header>
  );
}
