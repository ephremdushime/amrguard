from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.core.rate_limit import rate_limiter
from app.db.seed import DEMO_USER_PASSWORD, seed_demo
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.core import AuditEvent

Base.metadata.create_all(engine)
with SessionLocal() as _db:
    seed_demo(_db)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limiter.reset()


def _login(username: str, password: str = DEMO_USER_PASSWORD) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    resp = client.post('/api/v1/auth/login', json={'username': username, 'password': password})
    assert resp.status_code == 200, resp.text
    return client, {'X-CSRF-Token': resp.json()['csrf_token']}


def test_non_admin_roles_denied_across_admin_governance_endpoints():
    for role_user in ['demo.pharmacist', 'demo.assistant', 'demo.prescriber', 'demo.steward', 'demo.analyst']:
        client, csrf = _login(role_user)
        assert client.get('/api/v1/admin/organizations').status_code == 403
        assert client.get('/api/v1/admin/facilities').status_code == 403
        assert client.get('/api/v1/admin/pharmacies').status_code == 403
        assert client.get('/api/v1/admin/users').status_code == 403
        assert client.get('/api/v1/admin/service-clients').status_code == 403
        assert (
            client.post('/api/v1/admin/organizations', json={'code': 'ORG-DENY', 'name': 'Denied Org'}, headers=csrf).status_code
            == 403
        )


def test_platform_operator_provisions_org_facility_pharmacy_and_network():
    op, csrf = _login('demo.operator')
    suffix = uuid4().hex[:6].upper()

    org_resp = op.post(
        '/api/v1/admin/organizations',
        json={'code': f'ORG-{suffix}', 'name': f'Test Health Group {suffix}'},
        headers=csrf,
    )
    assert org_resp.status_code == 201, org_resp.text
    org_id = org_resp.json()['id']

    fac_resp = op.post(
        '/api/v1/admin/facilities',
        json={
            'code': f'FAC-{suffix}',
            'name': f'District Hospital {suffix}',
            'district': 'Nyarugenge',
            'organization_id': org_id,
        },
        headers=csrf,
    )
    assert fac_resp.status_code == 201, fac_resp.text
    fac_id = fac_resp.json()['id']

    ph_resp = op.post(
        '/api/v1/admin/pharmacies',
        json={
            'code': f'PHA-RET-{suffix}',
            'name': f'Retail Partner {suffix}',
            'district': 'Nyarugenge',
            'organization_id': org_id,
            'pharmacy_type': 'COMMUNITY_RETAIL',
        },
        headers=csrf,
    )
    assert ph_resp.status_code == 201, ph_resp.text
    ph_id = ph_resp.json()['id']

    net_resp = op.post(
        '/api/v1/admin/networks',
        json={'code': f'NET-{suffix}', 'name': f'Approved Network {suffix}'},
        headers=csrf,
    )
    assert net_resp.status_code == 201, net_resp.text
    net_id = net_resp.json()['id']

    member_resp = op.post(
        f'/api/v1/admin/networks/{net_id}/members',
        json={
            'facility_id': fac_id,
            'pharmacy_id': ph_id,
            'allow_all_medicines': False,
            'antibiotic_codes': ['AMX500CAP'],
            'active': True,
        },
        headers=csrf,
    )
    assert member_resp.status_code == 200, member_resp.text
    net_body = member_resp.json()
    assert any(f['facility_id'] == fac_id for f in net_body['facilities'])
    assert any(
        p['pharmacy_id'] == ph_id and 'AMX500CAP' in p['permitted_antibiotic_codes'] for p in net_body['pharmacies']
    )


def test_facility_admin_tenancy_isolation_and_anti_escalation():
    op, op_csrf = _login('demo.operator')
    suffix = uuid4().hex[:6].upper()

    # Create an isolated second facility via platform operator
    other_fac = op.post(
        '/api/v1/admin/facilities',
        json={'code': f'FAC-ISO-{suffix}', 'name': f'Other Facility {suffix}', 'district': 'Huye'},
        headers=op_csrf,
    ).json()

    admin, admin_csrf = _login('demo.admin')

    # Facility admin sees ONLY their own facility (FAC-KGL-001), never other_fac
    fac_list = admin.get('/api/v1/admin/facilities')
    assert fac_list.status_code == 200
    own_facs = fac_list.json()
    assert len(own_facs) == 1
    own_fac_id = own_facs[0]['id']
    assert own_fac_id != other_fac['id']

    # Facility admin CANNOT create organizations, facilities, networks, or service clients
    assert (
        admin.post('/api/v1/admin/organizations', json={'code': f'NO-{suffix}', 'name': 'No'}, headers=admin_csrf).status_code
        == 403
    )
    assert (
        admin.post(
            '/api/v1/admin/facilities',
            json={'code': f'NOF-{suffix}', 'name': 'No', 'district': 'Huye'},
            headers=admin_csrf,
        ).status_code
        == 403
    )
    assert admin.get('/api/v1/admin/service-clients').status_code == 403

    # Facility admin CAN create a facility pharmacy in own facility, CANNOT create in other facility or retail
    ok_ph = admin.post(
        '/api/v1/admin/pharmacies',
        json={
            'code': f'PHA-OWN-{suffix}',
            'name': f'Own Wing Pharmacy {suffix}',
            'district': 'Gasabo',
            'facility_id': own_fac_id,
            'pharmacy_type': 'FACILITY_PHARMACY',
        },
        headers=admin_csrf,
    )
    assert ok_ph.status_code == 201, ok_ph.text
    own_ph_id = ok_ph.json()['id']

    cross_ph = admin.post(
        '/api/v1/admin/pharmacies',
        json={
            'code': f'PHA-X-{suffix}',
            'name': 'Cross Facility Pharmacy',
            'district': 'Huye',
            'facility_id': other_fac['id'],
            'pharmacy_type': 'FACILITY_PHARMACY',
        },
        headers=admin_csrf,
    )
    assert cross_ph.status_code == 403

    retail_ph = admin.post(
        '/api/v1/admin/pharmacies',
        json={
            'code': f'PHA-R-{suffix}',
            'name': 'Unauthorized Retail',
            'district': 'Gasabo',
            'facility_id': own_fac_id,
            'pharmacy_type': 'COMMUNITY_RETAIL',
        },
        headers=admin_csrf,
    )
    assert retail_ph.status_code == 403

    # Facility admin CANNOT escalate privileges to platform_operator or national_analyst
    esc = admin.post(
        '/api/v1/admin/users',
        json={
            'username': f'esc.{suffix.lower()}',
            'display_name': 'Escalated Attempt',
            'auth_provider': 'local',
            'password': 'Strong-Password-2026!',
            'initial_scope': {'role_code': 'platform_operator', 'scope_type': 'PLATFORM'},
        },
        headers=admin_csrf,
    )
    assert esc.status_code == 403

    # Facility admin CAN provision a new pharmacist scoped to their own pharmacy
    new_username = f'staff.{suffix.lower()}'
    new_pw = 'Strong-Staff-Pass-2026!'
    created = admin.post(
        '/api/v1/admin/users',
        json={
            'username': new_username,
            'display_name': 'New Facility Pharmacist',
            'auth_provider': 'local',
            'password': new_pw,
            'initial_scope': {
                'role_code': 'pharmacist',
                'scope_type': 'PHARMACY',
                'pharmacy_id': own_ph_id,
            },
        },
        headers=admin_csrf,
    )
    assert created.status_code == 201, created.text
    created_user_id = created.json()['id']
    initial_scope_id = created.json()['scopes'][0]['id']

    # Newly provisioned user can log in immediately
    staff_client, _ = _login(new_username, new_pw)
    assert staff_client.get('/api/v1/auth/me').status_code == 200

    # Grant an additional facility prescriber scope, then revoke initial scope
    granted = admin.post(
        f'/api/v1/admin/users/{created_user_id}/role-scopes',
        json={'role_code': 'prescriber', 'scope_type': 'FACILITY', 'facility_id': own_fac_id},
        headers=admin_csrf,
    )
    assert granted.status_code == 201, granted.text

    revoked = admin.post(
        f'/api/v1/admin/users/{created_user_id}/role-scopes/{initial_scope_id}/revoke',
        headers=admin_csrf,
    )
    assert revoked.status_code == 200
    assert revoked.json()['active'] is False

    # Deactivating the staff user immediately revokes their live session
    deactivated = admin.patch(
        f'/api/v1/admin/users/{created_user_id}',
        json={'active': False},
        headers=admin_csrf,
    )
    assert deactivated.status_code == 200
    assert deactivated.json()['active'] is False
    assert staff_client.get('/api/v1/auth/me').status_code == 401


def test_service_client_provisioning_key_rotation_and_revocation():
    op, op_csrf = _login('demo.operator')
    suffix = uuid4().hex[:6].lower()

    created = op.post(
        '/api/v1/admin/service-clients',
        json={
            'client_code': f'openmrs-test-{suffix}',
            'name': f'OpenMRS Test Client {suffix}',
            'partner_type': 'EMR',
            'expires_in_days': 30,
            'scopes': [{'scope': 'integrations:openmrs:prescriptions:write', 'facility_id': 1}],
        },
        headers=op_csrf,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    client_id = body['client_id']
    key_v1 = body['api_key']
    assert '.' in key_v1

    # Service key v1 authenticates against /api/v1/meta
    svc = TestClient(app)
    assert svc.get('/api/v1/meta', headers={'x-amrguard-integration-key': key_v1}).status_code == 200

    # Dual-key overlap rotation: both v1 and v2 remain active
    rot_overlap = op.post(
        f'/api/v1/admin/service-clients/{client_id}/rotate-key',
        json={'revoke_previous': False, 'expires_in_days': 30},
        headers=op_csrf,
    )
    assert rot_overlap.status_code == 200
    key_v2 = rot_overlap.json()['api_key']
    assert rot_overlap.json()['revoked_previous_count'] == 0
    assert svc.get('/api/v1/meta', headers={'x-amrguard-integration-key': key_v1}).status_code == 200
    assert svc.get('/api/v1/meta', headers={'x-amrguard-integration-key': key_v2}).status_code == 200

    # Hard rotation revokes prior keys immediately
    rot_hard = op.post(
        f'/api/v1/admin/service-clients/{client_id}/rotate-key',
        json={'revoke_previous': True, 'expires_in_days': 30},
        headers=op_csrf,
    )
    assert rot_hard.status_code == 200
    key_v3 = rot_hard.json()['api_key']
    cred_v3_id = rot_hard.json()['credential_id']
    assert rot_hard.json()['revoked_previous_count'] == 2
    assert svc.get('/api/v1/meta', headers={'x-amrguard-integration-key': key_v1}).status_code == 403
    assert svc.get('/api/v1/meta', headers={'x-amrguard-integration-key': key_v2}).status_code == 403
    assert svc.get('/api/v1/meta', headers={'x-amrguard-integration-key': key_v3}).status_code == 200

    # Explicit credential revocation invalidates v3 immediately
    rev = op.post(
        f'/api/v1/admin/service-clients/{client_id}/credentials/{cred_v3_id}/revoke',
        headers=op_csrf,
    )
    assert rev.status_code == 200
    assert rev.json()['active'] is False
    assert svc.get('/api/v1/meta', headers={'x-amrguard-integration-key': key_v3}).status_code == 403

    # Verify audit event recorded without raw key leakage
    with SessionLocal() as db:
        ev = db.scalar(
            select(AuditEvent)
            .where(AuditEvent.event_type == 'ADMIN_SERVICE_KEY_ROTATED')
            .order_by(AuditEvent.id.desc())
        )
        assert ev is not None
        assert key_v3 not in (ev.details or '')
