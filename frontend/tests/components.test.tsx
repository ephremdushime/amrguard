import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { AuthUser } from '../src/authApi';
import { AuthHeader } from '../src/components/AuthHeader';
import { DispensingWorkstation } from '../src/components/DispensingWorkstation';
import { LoginForm } from '../src/components/LoginForm';
import { ServiceClientsPanel } from '../src/components/ServiceClientsPanel';
import { StaffAndFacilityAdminPanel } from '../src/components/StaffAndFacilityAdminPanel';
import type { OperationalBatch, OperationalRx, Pharmacy } from '../src/types';

const sampleRx: OperationalRx = {
  id: 1,
  code: 'AMR-RX-000001',
  external_id: 'EBZ-001',
  status: 'ACTIVE',
  prescriber: { id: 'EBZ-USER-001', name: 'Demo Prescriber' },
  facility: { id: 1, code: 'FAC-KGL-001', name: 'AMRGuard Demo Hospital' },
  patient_reference: 'PAT-001',
  created_at: '2026-11-25T08:00:00Z',
  items: [
    {
      id: 10,
      antibiotic: 'Amoxicillin',
      code: 'AMX500CAP',
      strength: '500 mg',
      formulation: 'Capsule',
      route: 'Oral',
      dose: 500,
      frequency_per_day: 3,
      duration_days: 5,
      authorized_quantity: 15,
      indication: 'Community-acquired URTI',
    },
  ],
};

const samplePharmacies: Pharmacy[] = [
  { id: 1, code: 'PHA-KGL-001', name: 'AMRGuard Demo Pharmacy', district: 'Gasabo', active: true, facility_id: 1 },
];

const sampleBatches: OperationalBatch[] = [
  {
    id: 1,
    pharmacy_id: 1,
    pharmacy_name: 'AMRGuard Demo Pharmacy',
    pharmacy_code: 'PHA-KGL-001',
    antibiotic_id: 1,
    antibiotic: 'Amoxicillin',
    antibiotic_code: 'AMX500CAP',
    strength: '500 mg',
    formulation: 'Capsule',
    batch_number: 'AMX-2026-0042',
    expiry_date: '2028-06-01',
    quantity_available: 120,
  },
];

describe('Role-Scoped Institutional React Components', () => {
  it('LoginForm renders all 8 pilot role accounts and online posture', () => {
    const html = renderToStaticMarkup(
      React.createElement(LoginForm, {
        api: 'http://localhost:8000',
        online: true,
        onAuthenticated: () => {},
      }),
    );

    assert.match(html, /Pharmacist/);
    assert.match(html, /Pharmacy Assistant/);
    assert.match(html, /Prescriber/);
    assert.match(html, /Stewardship Officer/);
    assert.match(html, /Facility Admin/);
    assert.match(html, /National Analyst/);
    assert.match(html, /Platform Operator/);
    assert.match(html, /Multi-Role Clinician/);
    assert.match(html, /Online/);
  });

  it('AuthHeader displays workspace breadcrumb, role label, and tenancy scope badge', () => {
    const user: AuthUser = {
      actor_type: 'HUMAN',
      actor_id: 'user:1',
      auth_method: 'local_session',
      user_id: 1,
      username: 'demo.pharmacist',
      display_name: 'Demo Pharmacist',
      roles: ['pharmacist'],
      scopes: [{ role: 'pharmacist', scope_type: 'PHARMACY', organization_id: null, facility_id: null, pharmacy_id: 1 }],
    };

    const html = renderToStaticMarkup(
      React.createElement(AuthHeader, {
        user,
        workspaceLabel: 'Pharmacy Workspace',
        sectionLabel: 'Dispensing & Verification',
        online: true,
        onRefresh: () => {},
        onSignOut: () => {},
      }),
    );

    assert.match(html, /Pharmacy Workspace/);
    assert.match(html, /Dispensing &amp; Verification/);
    assert.match(html, /Demo Pharmacist/);
    assert.match(html, /Pharmacy #1/);
  });

  it('DispensingWorkstation enforces Pharmacist vs Pharmacy Assistant UI boundaries', () => {
    const baseProps = {
      rx: sampleRx,
      pharmacies: samplePharmacies,
      currentPharmacyId: 1,
      onPharmacyChange: () => {},
      batches: sampleBatches,
      dispensedByItem: {},
      credential: '',
      otp: '',
      onOtpChange: () => {},
      onCredentialChange: () => {},
      isVerified: false,
      onVerify: async () => {},
      onIssueCredential: async () => {},
      onDispense: async () => {},
      busy: false,
    };

    const pharmacistHtml = renderToStaticMarkup(
      React.createElement(DispensingWorkstation, {
        ...baseProps,
        canDispense: true,
        canIssueCredential: true,
      }),
    );
    assert.match(pharmacistHtml, /Generate QR \/ OTP/);
    assert.match(pharmacistHtml, /Authorize Dispense/);
    assert.doesNotMatch(pharmacistHtml, /Pharmacist Role Required to Dispense/);

    const assistantHtml = renderToStaticMarkup(
      React.createElement(DispensingWorkstation, {
        ...baseProps,
        canDispense: false,
        canIssueCredential: false,
      }),
    );
    assert.doesNotMatch(assistantHtml, /Generate QR \/ OTP/);
    assert.match(assistantHtml, /Pharmacy Assistant boundary/);
    assert.match(assistantHtml, /Pharmacist Role Required to Dispense/);
  });

  it('StaffAndFacilityAdminPanel hides platform-only scope options from Facility Admins', () => {
    const facilityAdminHtml = renderToStaticMarkup(
      React.createElement(StaffAndFacilityAdminPanel, {
        api: 'http://localhost:8000',
        isPlatformOperator: false,
      }),
    );
    assert.match(facilityAdminHtml, /Facility Staff Accounts, Role Scopes &amp; Pharmacies/);
    assert.doesNotMatch(facilityAdminHtml, /value="PLATFORM"/);
    assert.doesNotMatch(facilityAdminHtml, /value="NATIONAL_AGGREGATE"/);
    assert.doesNotMatch(facilityAdminHtml, /Onboard Health Facility/);

    const platformOpHtml = renderToStaticMarkup(
      React.createElement(StaffAndFacilityAdminPanel, {
        api: 'http://localhost:8000',
        isPlatformOperator: true,
      }),
    );
    assert.match(platformOpHtml, /Organizations, Facilities, Networks &amp; Staff Identity/);
    assert.match(platformOpHtml, /value="PLATFORM"/);
    assert.match(platformOpHtml, /value="NATIONAL_AGGREGATE"/);
    assert.match(platformOpHtml, /Onboard Health Facility/);
  });

  it('ServiceClientsPanel renders machine-to-machine key lifecycle controls', () => {
    const html = renderToStaticMarkup(
      React.createElement(ServiceClientsPanel, { api: 'http://localhost:8000' }),
    );
    assert.match(html, /Partner Service Clients &amp; Key Rotation/);
    assert.match(html, /Provision Scoped Service Client/);
    assert.match(html, /Create Client &amp; Issue Key/);
  });
});
