import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import type { AuthUser } from '../src/authApi';
import {
  getAuthorizedWorkspaces,
  getDefaultPathForUser,
  resolveWorkspaceRoute,
} from '../src/workspaceRouting';

function makeUser(roles: string[]): AuthUser {
  return {
    actor_type: 'HUMAN',
    actor_id: `user:${roles.join('+')}`,
    auth_method: 'local_session',
    user_id: 1,
    username: `test.${roles[0] || 'none'}`,
    display_name: 'Test User',
    roles,
    scopes: [],
  };
}

describe('Institutional Workspace Routing & RBAC Boundaries', () => {
  const singleRoleCases: Array<{
    role: string;
    expectedWorkspace: string;
    expectedDefault: string;
    expectedSections: string[];
    forbiddenPaths: string[];
  }> = [
    {
      role: 'pharmacist',
      expectedWorkspace: 'pharmacy',
      expectedDefault: '/pharmacy/dispensing',
      expectedSections: ['dispensing', 'traceability', 'offline'],
      forbiddenPaths: ['/prescriber/orders', '/stewardship/overview', '/facility-admin/overview', '/national/surveillance', '/platform/health'],
    },
    {
      role: 'pharmacy_assistant',
      expectedWorkspace: 'pharmacy',
      expectedDefault: '/pharmacy/dispensing',
      expectedSections: ['dispensing', 'offline'],
      forbiddenPaths: ['/pharmacy/traceability', '/facility-admin/users', '/platform/service-clients'],
    },
    {
      role: 'prescriber',
      expectedWorkspace: 'prescriber',
      expectedDefault: '/prescriber/orders',
      expectedSections: ['orders', 'alerts', 'safety'],
      forbiddenPaths: ['/pharmacy/dispensing', '/stewardship/overview', '/facility-admin/overview', '/platform/health'],
    },
    {
      role: 'stewardship_officer',
      expectedWorkspace: 'stewardship',
      expectedDefault: '/stewardship/overview',
      expectedSections: ['overview', 'reviews', 'adherence', 'traceability'],
      forbiddenPaths: ['/pharmacy/dispensing', '/facility-admin/users', '/national/surveillance', '/platform/health'],
    },
    {
      role: 'facility_admin',
      expectedWorkspace: 'facility-admin',
      expectedDefault: '/facility-admin/overview',
      expectedSections: ['overview', 'users', 'quarantine', 'exceptions', 'audit'],
      forbiddenPaths: ['/pharmacy/dispensing', '/national/surveillance', '/platform/health', '/platform/service-clients'],
    },
    {
      role: 'national_analyst',
      expectedWorkspace: 'national',
      expectedDefault: '/national/surveillance',
      expectedSections: ['surveillance', 'facilities', 'ai-insights'],
      forbiddenPaths: ['/pharmacy/dispensing', '/prescriber/orders', '/facility-admin/audit', '/platform/security-audit'],
    },
    {
      role: 'platform_operator',
      expectedWorkspace: 'platform',
      expectedDefault: '/platform/health',
      expectedSections: ['health', 'identity', 'service-clients', 'integrations', 'quarantine', 'security-audit'],
      forbiddenPaths: ['/pharmacy/dispensing', '/prescriber/orders', '/stewardship/reviews', '/national/surveillance'],
    },
  ];

  for (const tc of singleRoleCases) {
    it(`routes ${tc.role} strictly into ${tc.expectedWorkspace} and blocks unauthorized workspaces`, () => {
      const user = makeUser([tc.role]);
      const authorized = getAuthorizedWorkspaces(user, true);

      assert.equal(authorized.length, 1);
      assert.equal(authorized[0].id, tc.expectedWorkspace);
      assert.deepEqual(
        authorized[0].sections.map((s) => s.id),
        tc.expectedSections,
      );
      assert.equal(getDefaultPathForUser(user, true), tc.expectedDefault);

      // Root path redirects straight to operational route (never a pitch hero)
      const rootRoute = resolveWorkspaceRoute('/', user, true);
      assert.equal(rootRoute.status, 'redirect');
      assert.equal(rootRoute.redirectTo, tc.expectedDefault);

      // Default operational path is authorized
      const activeRoute = resolveWorkspaceRoute(tc.expectedDefault, user, true);
      assert.equal(activeRoute.status, 'authorized');
      assert.equal(activeRoute.workspace?.id, tc.expectedWorkspace);

      // Unauthorized workspaces & restricted sub-routes return explicit 403 forbidden status
      for (const forbiddenPath of tc.forbiddenPaths) {
        const res = resolveWorkspaceRoute(forbiddenPath, user, true);
        assert.equal(res.status, 'forbidden', `Expected ${tc.role} to be forbidden from ${forbiddenPath}`);
      }
    });
  }

  it('hides dev-only routes such as /prescriber/safety when isDev is false (production build)', () => {
    const prescriber = makeUser(['prescriber']);
    const prodWorkspaces = getAuthorizedWorkspaces(prescriber, false);
    assert.deepEqual(
      prodWorkspaces[0].sections.map((s) => s.id),
      ['orders', 'alerts'],
    );
    const forbiddenDevRoute = resolveWorkspaceRoute('/prescriber/safety', prescriber, false);
    assert.equal(forbiddenDevRoute.status, 'forbidden');
  });

  it('grants multi-role clinicians access to their 3 clinical workspaces only', () => {
    const clinician = makeUser(['prescriber', 'pharmacist', 'stewardship_officer']);
    const workspaces = getAuthorizedWorkspaces(clinician, true);
    assert.deepEqual(
      workspaces.map((w) => w.id),
      ['pharmacy', 'prescriber', 'stewardship'],
    );
    assert.equal(resolveWorkspaceRoute('/facility-admin/users', clinician, true).status, 'forbidden');
    assert.equal(resolveWorkspaceRoute('/national/surveillance', clinician, true).status, 'forbidden');
    assert.equal(resolveWorkspaceRoute('/platform/service-clients', clinician, true).status, 'forbidden');
  });
});
