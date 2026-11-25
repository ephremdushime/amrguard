import { useCallback, useEffect, useState } from 'react';
import type { AuthUser } from './authApi';

export type WorkspaceId =
  | 'pharmacy'
  | 'prescriber'
  | 'stewardship'
  | 'facility-admin'
  | 'national'
  | 'platform';

export interface WorkspaceSectionDef {
  id: string;
  label: string;
  path: string;
  description: string;
  requiredRoles?: string[];
  devOnly?: boolean;
}

export interface WorkspaceDefinition {
  id: WorkspaceId;
  label: string;
  shortLabel: string;
  eyebrow: string;
  basePath: string;
  allowedRoles: string[];
  sections: WorkspaceSectionDef[];
}

export const WORKSPACE_DEFINITIONS: WorkspaceDefinition[] = [
  {
    id: 'pharmacy',
    label: 'Pharmacy Workspace',
    shortLabel: 'Pharmacy',
    eyebrow: 'PHARMACY DISPENSING OPERATIONS',
    basePath: '/pharmacy',
    allowedRoles: ['pharmacist', 'pharmacy_assistant'],
    sections: [
      {
        id: 'dispensing',
        label: 'Dispensing & Verification',
        path: '/pharmacy/dispensing',
        description: 'Incoming prescription queue, QR/OTP verification, and batch dispensing',
      },
      {
        id: 'traceability',
        label: 'Batch Traceability',
        path: '/pharmacy/traceability',
        description: 'Batch ledger, RMS origin references, and linked dispensing transactions',
        requiredRoles: ['pharmacist'],
      },
      {
        id: 'offline',
        label: 'Offline Queue & Sync',
        path: '/pharmacy/offline',
        description: 'Cryptographically signed offline dispensing bundles and reconciliation',
      },
    ],
  },
  {
    id: 'prescriber',
    label: 'Prescriber Workspace',
    shortLabel: 'Prescriber',
    eyebrow: 'CLINICAL PRESCRIBING & DECISION SUPPORT',
    basePath: '/prescriber',
    allowedRoles: ['prescriber'],
    sections: [
      {
        id: 'orders',
        label: 'Orders & Stewardship Support',
        path: '/prescriber/orders',
        description: 'Facility prescription register, QR/OTP issuance, FHIR export, and order checks',
      },
      {
        id: 'alerts',
        label: 'Clinical Alerts & AI Guidance',
        path: '/prescriber/alerts',
        description: 'Governed stewardship alerts, disposition recording, and cited AI explanations',
      },
      {
        id: 'safety',
        label: 'Validation Controls (Dev)',
        path: '/prescriber/safety',
        description: 'Non-production deterministic blocking verification scenario',
        devOnly: true,
      },
    ],
  },
  {
    id: 'stewardship',
    label: 'Stewardship Workspace',
    shortLabel: 'Stewardship',
    eyebrow: 'ANTIMICROBIAL STEWARDSHIP PROGRAMME',
    basePath: '/stewardship',
    allowedRoles: ['stewardship_officer'],
    sections: [
      {
        id: 'overview',
        label: 'WHO AWaRe & Rules',
        path: '/stewardship/overview',
        description: 'Governed KPIs, WHO AWaRe targets, active clinical rules, and AI trend brief',
      },
      {
        id: 'reviews',
        label: 'Alerts & Post-Dispense Reviews',
        path: '/stewardship/reviews',
        description: 'Rule alert dispositions and Day-3 clinical reassessment queue',
      },
      {
        id: 'adherence',
        label: 'Consent & Dose Reminders',
        path: '/stewardship/adherence',
        description: 'Verified patient SMS consent ledger, withdrawal, and scheduled doses',
      },
      {
        id: 'traceability',
        label: 'Batch Trace & Facility Audit',
        path: '/stewardship/traceability',
        description: 'Facility batch traceability and clinical stewardship audit log',
      },
    ],
  },
  {
    id: 'facility-admin',
    label: 'Facility Administration',
    shortLabel: 'Facility Admin',
    eyebrow: 'INSTITUTIONAL FACILITY OPERATIONS',
    basePath: '/facility-admin',
    allowedRoles: ['facility_admin'],
    sections: [
      {
        id: 'overview',
        label: 'Facility Overview',
        path: '/facility-admin/overview',
        description: 'Facility KPIs, connected pharmacies, and operational posture',
      },
      {
        id: 'users',
        label: 'Staff, Roles & Pharmacies',
        path: '/facility-admin/users',
        description: 'Facility-scoped staff provisioning, role scopes, and dispensing locations',
      },
      {
        id: 'quarantine',
        label: 'Quarantine & Catalogue',
        path: '/facility-admin/quarantine',
        description: 'Unmapped partner payloads requiring reconciliation and medicine code mappings',
      },
      {
        id: 'exceptions',
        label: 'Exceptions & Offline Sync',
        path: '/facility-admin/exceptions',
        description: 'Blocked orders, offline dispensing reconciliation, and outbox dead letters',
      },
      {
        id: 'audit',
        label: 'Facility Audit & Trace',
        path: '/facility-admin/audit',
        description: 'Append-only facility audit trail and pharmacy batch traceability',
      },
    ],
  },
  {
    id: 'national',
    label: 'District & National Intelligence',
    shortLabel: 'National Intel',
    eyebrow: 'RBC / MOH NATIONAL AMR SURVEILLANCE',
    basePath: '/national',
    allowedRoles: ['national_analyst'],
    sections: [
      {
        id: 'surveillance',
        label: 'WHO GLASS Surveillance',
        path: '/national/surveillance',
        description: 'Privacy-preserved district surveillance export with <5 minimum-cell suppression',
      },
      {
        id: 'facilities',
        label: 'Facility Comparisons',
        path: '/national/facilities',
        description: 'Cross-facility reconciliation rates, review completion, and governed KPIs',
      },
      {
        id: 'ai-insights',
        label: 'AI Brief & AWaRe Reference',
        path: '/national/ai-insights',
        description: 'Bounded national trend summary, WHO AWaRe catalog, and system telemetry',
      },
    ],
  },
  {
    id: 'platform',
    label: 'Platform Administration',
    shortLabel: 'Platform Admin',
    eyebrow: 'INTEROPERABILITY & SECURITY OPERATIONS',
    basePath: '/platform',
    allowedRoles: ['platform_operator'],
    sections: [
      {
        id: 'health',
        label: 'System Health & Telemetry',
        path: '/platform/health',
        description: 'Prometheus / OpenMetrics telemetry, runtime posture, and pharmacy directory',
      },
      {
        id: 'identity',
        label: 'Orgs, Facilities & Identity',
        path: '/platform/identity',
        description: 'Organizations, facilities, cross-facility networks, and staff RBAC scopes',
      },
      {
        id: 'service-clients',
        label: 'Partner Service Keys',
        path: '/platform/service-clients',
        description: 'Machine-to-machine partner service clients, scopes, and key rotation',
      },
      {
        id: 'integrations',
        label: 'Connectors & Outbox DLQ',
        path: '/platform/integrations',
        description: 'Registered EMR connectors, outbox dispatch ticks, dead-letter retries, and FHIR contracts',
      },
      {
        id: 'quarantine',
        label: 'Quarantine & Catalogue',
        path: '/platform/quarantine',
        description: 'Cross-partner quarantined payloads and canonical catalogue mappings',
      },
      {
        id: 'security-audit',
        label: 'Security & Technical Audit',
        path: '/platform/security-audit',
        description: 'Authentication, session, and service-client audit log (zero clinical PHI access)',
      },
    ],
  },
];

export function hasAnyRole(user: AuthUser, roles: string[]): boolean {
  return roles.some((role) => user.roles.includes(role));
}

export function getAuthorizedWorkspaces(user: AuthUser, isDev: boolean): WorkspaceDefinition[] {
  return WORKSPACE_DEFINITIONS.filter((ws) => hasAnyRole(user, ws.allowedRoles)).map((ws) => ({
    ...ws,
    sections: ws.sections.filter((sec) => {
      if (sec.devOnly && !isDev) return false;
      if (sec.requiredRoles && !hasAnyRole(user, sec.requiredRoles)) return false;
      return true;
    }),
  }));
}

export function getDefaultPathForUser(user: AuthUser, isDev: boolean): string {
  const authorized = getAuthorizedWorkspaces(user, isDev);
  const first = authorized[0];
  if (!first || !first.sections[0]) return '/';
  return first.sections[0].path;
}

export interface ResolvedRoute {
  status: 'authorized' | 'forbidden' | 'redirect';
  workspace: WorkspaceDefinition | null;
  section: WorkspaceSectionDef | null;
  redirectTo?: string;
  requestedPath: string;
}

function normalizePathname(raw: string): string {
  const trimmed = raw.replace(/\/+$/, '');
  return trimmed || '/';
}

export function resolveWorkspaceRoute(
  pathname: string,
  user: AuthUser,
  isDev: boolean,
): ResolvedRoute {
  const cleanPath = normalizePathname(pathname);
  const authorized = getAuthorizedWorkspaces(user, isDev);
  const fallbackPath = getDefaultPathForUser(user, isDev);

  if (cleanPath === '/' || cleanPath === '/index.html') {
    return {
      status: 'redirect',
      workspace: authorized[0] || null,
      section: authorized[0]?.sections[0] || null,
      redirectTo: fallbackPath,
      requestedPath: cleanPath,
    };
  }

  // Find matching workspace in global registry first so we can tell forbidden vs unknown
  const matchedGlobalWs = WORKSPACE_DEFINITIONS.find(
    (ws) => cleanPath === ws.basePath || cleanPath.startsWith(`${ws.basePath}/`),
  );

  if (!matchedGlobalWs) {
    return {
      status: 'redirect',
      workspace: authorized[0] || null,
      section: authorized[0]?.sections[0] || null,
      redirectTo: fallbackPath,
      requestedPath: cleanPath,
    };
  }

  const authorizedWs = authorized.find((ws) => ws.id === matchedGlobalWs.id);
  if (!authorizedWs) {
    return {
      status: 'forbidden',
      workspace: matchedGlobalWs,
      section: null,
      redirectTo: fallbackPath,
      requestedPath: cleanPath,
    };
  }

  // Exact base path redirects to workspace's first permitted section
  if (cleanPath === authorizedWs.basePath) {
    const firstSection = authorizedWs.sections[0] || null;
    return {
      status: 'redirect',
      workspace: authorizedWs,
      section: firstSection,
      redirectTo: firstSection ? firstSection.path : fallbackPath,
      requestedPath: cleanPath,
    };
  }

  const matchedSection = authorizedWs.sections.find((sec) => sec.path === cleanPath);
  if (matchedSection) {
    return {
      status: 'authorized',
      workspace: authorizedWs,
      section: matchedSection,
      requestedPath: cleanPath,
    };
  }

  // Check if section exists in global definition but is role-restricted (e.g. pharmacy_assistant hitting /pharmacy/traceability)
  const restrictedSection = matchedGlobalWs.sections.find((sec) => sec.path === cleanPath);
  if (restrictedSection) {
    return {
      status: 'forbidden',
      workspace: authorizedWs,
      section: restrictedSection,
      redirectTo: authorizedWs.sections[0]?.path || fallbackPath,
      requestedPath: cleanPath,
    };
  }

  // Unknown sub-route inside authorized workspace -> redirect to first section
  const firstSection = authorizedWs.sections[0] || null;
  return {
    status: 'redirect',
    workspace: authorizedWs,
    section: firstSection,
    redirectTo: firstSection ? firstSection.path : fallbackPath,
    requestedPath: cleanPath,
  };
}

export function useBrowserPath() {
  const [pathname, setPathname] = useState<string>(() =>
    typeof window !== 'undefined' ? window.location.pathname : '/',
  );

  useEffect(() => {
    const onPopState = () => setPathname(window.location.pathname);
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const navigate = useCallback((to: string, options?: { replace?: boolean }) => {
    if (typeof window === 'undefined') return;
    if (window.location.pathname !== to) {
      if (options?.replace) {
        window.history.replaceState(null, '', to);
      } else {
        window.history.pushState(null, '', to);
      }
    }
    setPathname(to);
  }, []);

  return { pathname, navigate };
}
