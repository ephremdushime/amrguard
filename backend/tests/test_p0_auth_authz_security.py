from datetime import date, datetime, timedelta, timezone
import json
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import jwt
from jwt.algorithms import RSAAlgorithm
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.authz import (
    ROLE_FACILITY_ADMIN,
    ROLE_PHARMACIST,
    ROLE_PRESCRIBER,
    SCOPE_EBUZIMA_RX_WRITE,
    SCOPE_RMS_STOCK_WRITE,
)
from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.db.seed import (
    DEMO_EBUZIMA_API_KEY,
    DEMO_RMS_API_KEY,
    DEMO_USER_PASSWORD,
    ensure_local_user,
    ensure_role_scope,
    ensure_service_client,
    seed_demo,
    seed_roles,
)
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.core import (
    Antibiotic,
    AuditEvent,
    DispensingTransaction,
    Facility,
    Organization,
    Pharmacy,
    PharmacyNetwork,
    PharmacyNetworkFacility,
    PharmacyNetworkMedicinePermission,
    PharmacyNetworkPharmacy,
    Prescriber,
    Prescription,
    PrescriptionItem,
    ServiceClient,
    ServiceClientCredential,
    StockBatch,
    User,
    UserRoleScope,
    UserSession,
)
from app.services.audit import record_audit
from app.services.security import keyed_digest

Base.metadata.create_all(engine)
with SessionLocal() as _db:
    seed_demo(_db)


@pytest.fixture(autouse=True)
def _reset_limiter():
    rate_limiter.reset()


def _login(username: str, password: str = DEMO_USER_PASSWORD) -> tuple[TestClient, dict[str, str], dict]:
    c = TestClient(app)
    resp = c.post('/api/v1/auth/login', json={'username': username, 'password': password})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return c, {'X-CSRF-Token': body['csrf_token']}, body


def _create_facility_b_fixture():
    """Create an isolated second facility, pharmacy, prescriber, batch, and staff accounts."""
    suffix = uuid4().hex[:6].upper()
    with SessionLocal() as db:
        roles = seed_roles(db)
        org_b = Organization(code=f'ORG-B-{suffix}', name=f'Facility B Org {suffix}')
        db.add(org_b)
        db.flush()
        fac_b = Facility(
            code=f'FAC-B-{suffix}',
            name=f'Hospital B {suffix}',
            district='Huye',
            organization_id=org_b.id,
        )
        db.add(fac_b)
        db.flush()
        pharm_b = Pharmacy(
            code=f'PHA-B-{suffix}',
            name=f'Hospital B Pharmacy {suffix}',
            district='Huye',
            organization_id=org_b.id,
            facility_id=fac_b.id,
            pharmacy_type='FACILITY_PHARMACY',
        )
        db.add(pharm_b)
        db.flush()
        ab = db.scalar(select(Antibiotic).where(Antibiotic.code == 'AMX500CAP'))
        batch_b = StockBatch(
            pharmacy_id=pharm_b.id,
            antibiotic_id=ab.id,
            batch_number=f'AMX-B-{suffix}',
            expiry_date=date.today() + timedelta(days=365),
            quantity_available=60,
            source_reference='SYNTHETIC-B',
        )
        db.add(batch_b)
        presc_b = Prescriber(external_user_id=f'EBZ-B-{suffix}', name='Dr B', facility_id=fac_b.id)
        db.add(presc_b)
        db.flush()
        rx_b = Prescription(
            external_id=f'EBZ-RX-B-{suffix}',
            patient_reference=f'PAT-B-{suffix}',
            prescriber_id=presc_b.id,
            facility_id=fac_b.id,
            status='VALIDATED',
            allow_external_dispensing=False,
        )
        db.add(rx_b)
        db.flush()
        db.add(
            PrescriptionItem(
                prescription_id=rx_b.id,
                antibiotic_id=ab.id,
                dose=500,
                frequency_per_day=3,
                duration_days=5,
                quantity=15,
                indication='Synthetic B indication',
            )
        )
        user_b_prescriber = ensure_local_user(
            db, username=f'prescriber.b.{suffix.lower()}', display_name='Prescriber B', password=DEMO_USER_PASSWORD
        )
        ensure_role_scope(
            db, user=user_b_prescriber, role=roles[ROLE_PRESCRIBER], scope_type='FACILITY', facility_id=fac_b.id
        )
        user_b_pharmacist = ensure_local_user(
            db, username=f'pharmacist.b.{suffix.lower()}', display_name='Pharmacist B', password=DEMO_USER_PASSWORD
        )
        ensure_role_scope(
            db, user=user_b_pharmacist, role=roles[ROLE_PHARMACIST], scope_type='PHARMACY', pharmacy_id=pharm_b.id
        )
        user_b_admin = ensure_local_user(
            db, username=f'admin.b.{suffix.lower()}', display_name='Admin B', password=DEMO_USER_PASSWORD
        )
        ensure_role_scope(
            db, user=user_b_admin, role=roles[ROLE_FACILITY_ADMIN], scope_type='FACILITY', facility_id=fac_b.id
        )
        db.commit()
        return {
            'facility_id': fac_b.id,
            'facility_code': fac_b.code,
            'pharmacy_id': pharm_b.id,
            'pharmacy_code': pharm_b.code,
            'batch_id': batch_b.id,
            'prescription_id': rx_b.id,
            'prescriber_username': user_b_prescriber.username,
            'pharmacist_username': user_b_pharmacist.username,
            'admin_username': user_b_admin.username,
        }


# ---------------------------------------------------------------------------
# 1. Local Session Security: Argon2id, HttpOnly/SameSite, CSRF, Revocation, Lockout, Rate-Limit
# ---------------------------------------------------------------------------


def test_local_session_uses_argon2id_httponly_cookie_and_csrf_protection():
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.username == 'demo.pharmacist'))
        assert u is not None and u.password_hash.startswith('$argon2id$')

    c = TestClient(app)
    resp = c.post('/api/v1/auth/login', json={'username': 'demo.pharmacist', 'password': DEMO_USER_PASSWORD})
    assert resp.status_code == 200
    set_cookie_headers = resp.headers.get_list('set-cookie')
    session_cookie_hdr = next(h for h in set_cookie_headers if h.startswith(f'{settings.session_cookie_name}='))
    assert 'httponly' in session_cookie_hdr.lower()
    assert 'samesite=strict' in session_cookie_hdr.lower()

    csrf_token = resp.json()['csrf_token']
    # Read route works with session cookie alone
    assert c.get('/api/v1/auth/me').status_code == 200

    # State-changing POST without X-CSRF-Token is blocked (403)
    no_csrf = c.post('/api/v1/auth/logout')
    assert no_csrf.status_code == 403
    assert 'csrf' in no_csrf.json()['detail'].lower()

    # Mismatched X-CSRF-Token is blocked (403)
    bad_csrf = c.post('/api/v1/auth/logout', headers={'X-CSRF-Token': 'tampered-token'})
    assert bad_csrf.status_code == 403

    # Valid X-CSRF-Token succeeds and revokes session
    session_cookie_value = c.cookies.get(settings.session_cookie_name)
    ok_logout = c.post('/api/v1/auth/logout', headers={'X-CSRF-Token': csrf_token})
    assert ok_logout.status_code == 200

    # Replaying the revoked session cookie fails with 401
    replay = TestClient(app)
    replay.cookies.set(settings.session_cookie_name, session_cookie_value)
    assert replay.get('/api/v1/auth/me').status_code == 401


def test_revoke_all_sessions_and_expired_session_denied():
    c1, csrf1, _ = _login('demo.prescriber')
    c2, _, _ = _login('demo.prescriber')
    assert c2.get('/api/v1/auth/me').status_code == 200

    res = c1.post('/api/v1/auth/sessions/revoke-all', headers=csrf1)
    assert res.status_code == 200 and res.json()['revoked_sessions'] >= 2
    assert c2.get('/api/v1/auth/me').status_code == 401

    # Expired session check
    c3, _, _ = _login('demo.prescriber')
    raw_cookie = c3.cookies.get(settings.session_cookie_name)
    with SessionLocal() as db:
        sess = db.scalar(
            select(UserSession).where(UserSession.token_hash == keyed_digest(raw_cookie, purpose='user_session'))
        )
        sess.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        db.commit()
    assert c3.get('/api/v1/auth/me').status_code == 401


def test_account_lockout_disabled_user_and_production_local_auth_disabled(monkeypatch):
    suffix = uuid4().hex[:6]
    with SessionLocal() as db:
        ensure_local_user(db, username=f'locktest.{suffix}', display_name='Lock Test', password=DEMO_USER_PASSWORD)
        ensure_local_user(
            db, username=f'disabled.{suffix}', display_name='Disabled User', password=DEMO_USER_PASSWORD, active=False
        )
        db.commit()

    c = TestClient(app)
    assert c.post('/api/v1/auth/login', json={'username': f'disabled.{suffix}', 'password': DEMO_USER_PASSWORD}).status_code == 403

    monkeypatch.setattr(settings, 'login_max_attempts', 3)
    for attempt in range(2):
        r = c.post('/api/v1/auth/login', json={'username': f'locktest.{suffix}', 'password': 'WrongPassword123!'})
        assert r.status_code == 401
    third = c.post('/api/v1/auth/login', json={'username': f'locktest.{suffix}', 'password': 'WrongPassword123!'})
    assert third.status_code == 423
    # Even the correct password is blocked while locked
    while_locked = c.post('/api/v1/auth/login', json={'username': f'locktest.{suffix}', 'password': DEMO_USER_PASSWORD})
    assert while_locked.status_code == 423

    # Local login disabled in production default (allow_local_auth=False)
    monkeypatch.setattr(settings, 'allow_local_auth', False)
    blocked_prod = c.post('/api/v1/auth/login', json={'username': 'demo.pharmacist', 'password': DEMO_USER_PASSWORD})
    assert blocked_prod.status_code == 403


def test_login_rate_limiting_enforced(monkeypatch):
    monkeypatch.setattr(settings, 'login_rate_limit_attempts', 2)
    c = TestClient(app)
    user = f'ratelimit.{uuid4().hex[:6]}'
    assert c.post('/api/v1/auth/login', json={'username': user, 'password': 'WrongPassword123!'}).status_code == 401
    assert c.post('/api/v1/auth/login', json={'username': user, 'password': 'WrongPassword123!'}).status_code == 401
    assert c.post('/api/v1/auth/login', json={'username': user, 'password': 'WrongPassword123!'}).status_code == 429


# ---------------------------------------------------------------------------
# 2. Institutional OIDC / OAuth2 JWT + JWKS Validation (Decision 1)
# ---------------------------------------------------------------------------


def test_oidc_jwt_jwks_validation_and_denials(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk['kid'] = 'rw-idp-key-1'
    public_jwk['use'] = 'sig'
    public_jwk['alg'] = 'RS256'
    jwks_json = json.dumps({'keys': [public_jwk]})

    issuer = 'https://idp.rwanda-health.example.org/realms/amrguard'
    audience = 'amrguard-api'
    subject = f'oidc-sub-{uuid4().hex[:8]}'

    with SessionLocal() as db:
        roles = seed_roles(db)
        fac = db.scalar(select(Facility).where(Facility.code == 'FAC-KGL-001'))
        oidc_user = User(
            identity_issuer=issuer,
            identity_subject=subject,
            username=f'oidc.pharmacist.{uuid4().hex[:6]}',
            display_name='OIDC Pharmacist',
            active=True,
        )
        db.add(oidc_user)
        db.flush()
        pharm = db.scalar(select(Pharmacy).where(Pharmacy.code == 'PHA-KGL-001'))
        ensure_role_scope(db, user=oidc_user, role=roles[ROLE_PHARMACIST], scope_type='PHARMACY', pharmacy_id=pharm.id)
        db.commit()
        oidc_user_id = oidc_user.id

    monkeypatch.setattr(settings, 'oidc_issuer', issuer)
    monkeypatch.setattr(settings, 'oidc_audience', audience)
    monkeypatch.setattr(settings, 'oidc_jwks_json', jwks_json)

    def _mint(sub=subject, iss=issuer, aud=audience, exp_delta=timedelta(minutes=5), kid='rw-idp-key-1', key=private_key):
        now = datetime.now(timezone.utc)
        claims = {'iss': iss, 'sub': sub, 'aud': aud, 'iat': int(now.timestamp()), 'exp': int((now + exp_delta).timestamp())}
        return jwt.encode(claims, key, algorithm='RS256', headers={'kid': kid})

    c = TestClient(app)

    # Valid OIDC JWT works even when local auth is disabled (production mode!)
    monkeypatch.setattr(settings, 'allow_local_auth', False)
    ok = c.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {_mint()}'})
    assert ok.status_code == 200
    assert ok.json()['auth_method'] == 'oidc_jwt'
    assert ok.json()['user_id'] == oidc_user_id

    # Expired token denied
    assert c.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {_mint(exp_delta=timedelta(minutes=-5))}'}).status_code == 401
    # Wrong audience denied
    assert c.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {_mint(aud="wrong-aud")}'}).status_code == 401
    # Wrong issuer denied
    assert c.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {_mint(iss="https://evil.example.org")}'}).status_code == 401
    # Unknown kid denied
    assert c.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {_mint(kid="unknown-kid")}'}).status_code == 401
    # Wrong signing key denied
    rogue_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert c.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {_mint(key=rogue_key)}'}).status_code == 401
    # Unprovisioned subject denied
    assert c.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {_mint(sub="unknown-sub")}'}).status_code == 401

    # Disabled OIDC user denied immediately
    with SessionLocal() as db:
        u = db.get(User, oidc_user_id)
        u.active = False
        db.commit()
    assert c.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {_mint()}'}).status_code == 401


# ---------------------------------------------------------------------------
# 3. Strict Human vs. Service-Client Separation, Scoped Keys & Key Rotation
# ---------------------------------------------------------------------------


def test_human_and_service_client_authentication_paths_are_strictly_separated():
    # Service key rejected on human endpoints
    svc = TestClient(app)
    ebz_headers = {'x-amrguard-integration-key': DEMO_EBUZIMA_API_KEY}
    rms_headers = {'x-amrguard-integration-key': DEMO_RMS_API_KEY}

    assert svc.get('/api/v1/auth/me', headers=ebz_headers).status_code == 403
    assert svc.get('/api/v1/prescriptions', headers=ebz_headers).status_code == 403
    assert svc.get('/api/v1/audit', headers=ebz_headers).status_code == 403
    assert (
        svc.post(
            '/api/v1/prescriptions/1/dispense',
            json={
                'pharmacy_id': 1,
                'batch_id': 1,
                'quantity': 1,
                'credential': '123456',
                'idempotency_key': 'idem-svc-blocked-001',
            },
            headers=ebz_headers,
        ).status_code
        == 403
    )

    # Human session rejected on service-only integration endpoints
    human, csrf, _ = _login('demo.clinician')
    assert (
        human.post(
            '/api/v1/integrations/ebuzima/prescriptions',
            json={
                'external_id': f'EBZ-HUMAN-NO-{uuid4().hex[:6]}',
                'patient_reference': 'PAT-1',
                'prescriber': {
                    'external_user_id': 'EBZ-USER-001',
                    'name': 'Demo Prescriber',
                    'facility_code': 'FAC-KGL-001',
                    'facility_name': 'AMRGuard Demo Hospital',
                    'district': 'Gasabo',
                },
                'items': [
                    {
                        'antibiotic_code': 'AMX500CAP',
                        'generic_name': 'Amoxicillin',
                        'strength': '500 mg',
                        'formulation': 'Capsule',
                        'route': 'Oral',
                        'dose': 500,
                        'frequency_per_day': 3,
                        'duration_days': 5,
                        'quantity': 15,
                        'indication': 'Test',
                    }
                ],
            },
            headers=csrf,
        ).status_code
        == 403
    )

    # Cross-partner scope isolation: e-Buzima cannot call RMS, RMS cannot call e-Buzima
    assert (
        svc.post(
            '/api/v1/integrations/rms/stock-events',
            json={
                'source_system': 'RMS',
                'source_reference': f'RMS-SCOPE-{uuid4().hex[:6]}',
                'pharmacy_code': 'PHA-KGL-001',
                'pharmacy_name': 'AMRGuard Demo Pharmacy',
                'district': 'Gasabo',
                'antibiotic_code': 'AMX500CAP',
                'generic_name': 'Amoxicillin',
                'strength': '500 mg',
                'formulation': 'Capsule',
                'route': 'Oral',
                'batch_number': 'AMX-2026-0042',
                'expiry_date': '2028-12-31',
                'event_type': 'RECEIPT',
                'quantity_delta': 10,
            },
            headers=ebz_headers,
        ).status_code
        == 403
    )
    assert (
        svc.post(
            '/api/v1/integrations/ebuzima/prescriptions',
            json={
                'external_id': f'EBZ-RMS-NO-{uuid4().hex[:6]}',
                'patient_reference': 'PAT-1',
                'prescriber': {
                    'external_user_id': 'EBZ-USER-001',
                    'name': 'Demo Prescriber',
                    'facility_code': 'FAC-KGL-001',
                    'facility_name': 'AMRGuard Demo Hospital',
                    'district': 'Gasabo',
                },
                'items': [
                    {
                        'antibiotic_code': 'AMX500CAP',
                        'generic_name': 'Amoxicillin',
                        'strength': '500 mg',
                        'formulation': 'Capsule',
                        'route': 'Oral',
                        'dose': 500,
                        'frequency_per_day': 3,
                        'duration_days': 5,
                        'quantity': 15,
                        'indication': 'Test',
                    }
                ],
            },
            headers=rms_headers,
        ).status_code
        == 403
    )


def test_service_client_expiry_revocation_rotation_and_facility_scope():
    fac_b = _create_facility_b_fixture()
    svc = TestClient(app)
    suffix = uuid4().hex[:6]
    p1 = f'rot_p1_{suffix}'
    s1 = f'secret-one-{suffix}-00001'
    p2 = f'rot_p2_{suffix}'
    s2 = f'secret-two-{suffix}-00002'

    with SessionLocal() as db:
        fac_a = db.scalar(select(Facility).where(Facility.code == 'FAC-KGL-001'))
        sc = ensure_service_client(
            db,
            client_code=f'ebz-rot-{suffix}',
            name='Rotation Test Client',
            partner_type='EMR',
            key_prefix=p1,
            key_secret=s1,
            scopes=[(SCOPE_EBUZIMA_RX_WRITE, fac_a.id, None)],
        )
        # Add second rotated key
        db.add(
            ServiceClientCredential(
                service_client_id=sc.id,
                key_prefix=p2,
                secret_hash=keyed_digest(s2, purpose='service_client_key', salt=p2),
            )
        )
        db.commit()

    def _rx_payload(fac_code: str):
        return {
            'external_id': f'EBZ-ROT-{uuid4().hex[:8]}',
            'patient_reference': 'PAT-ROT',
            'prescriber': {
                'external_user_id': 'EBZ-USER-001',
                'name': 'Demo Prescriber',
                'facility_code': fac_code,
                'facility_name': 'Facility',
                'district': 'Gasabo',
            },
            'items': [
                {
                    'antibiotic_code': 'AMX500CAP',
                    'generic_name': 'Amoxicillin',
                    'strength': '500 mg',
                    'formulation': 'Capsule',
                    'route': 'Oral',
                    'dose': 500,
                    'frequency_per_day': 3,
                    'duration_days': 5,
                    'quantity': 15,
                    'indication': 'Rotation test',
                }
            ],
        }

    # Facility A succeeds; Facility B denied (403)
    assert svc.post('/api/v1/integrations/ebuzima/prescriptions', json=_rx_payload('FAC-KGL-001'), headers={'x-amrguard-integration-key': f'{p1}.{s1}'}).status_code == 200
    assert svc.post('/api/v1/integrations/ebuzima/prescriptions', json=_rx_payload(fac_b['facility_code']), headers={'x-amrguard-integration-key': f'{p1}.{s1}'}).status_code == 403

    # Revoke p1; p1 fails (403), p2 succeeds (200)
    with SessionLocal() as db:
        c1 = db.scalar(select(ServiceClientCredential).where(ServiceClientCredential.key_prefix == p1))
        c1.revoked_at = datetime.now(timezone.utc)
        db.commit()
    assert svc.post('/api/v1/integrations/ebuzima/prescriptions', json=_rx_payload('FAC-KGL-001'), headers={'x-amrguard-integration-key': f'{p1}.{s1}'}).status_code == 403
    assert svc.post('/api/v1/integrations/ebuzima/prescriptions', json=_rx_payload('FAC-KGL-001'), headers={'x-amrguard-integration-key': f'{p2}.{s2}'}).status_code == 200

    # Expire p2; p2 fails (401)
    with SessionLocal() as db:
        c2 = db.scalar(select(ServiceClientCredential).where(ServiceClientCredential.key_prefix == p2))
        c2.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.commit()
    assert svc.post('/api/v1/integrations/ebuzima/prescriptions', json=_rx_payload('FAC-KGL-001'), headers={'x-amrguard-integration-key': f'{p2}.{s2}'}).status_code == 401


# ---------------------------------------------------------------------------
# 4. RBAC Roles & Cross-Facility / Cross-Pharmacy Isolation
# ---------------------------------------------------------------------------


def test_rbac_role_boundaries_enforced():
    prescriber, p_csrf, _ = _login('demo.prescriber')
    assistant, a_csrf, _ = _login('demo.assistant')
    pharmacist, ph_csrf, _ = _login('demo.pharmacist')
    analyst, _, _ = _login('demo.analyst')
    operator, _, _ = _login('demo.operator')

    # Create synthetic prescription & credential as prescriber
    created = prescriber.post(
        '/api/v1/demo/prescriptions',
        json={'external_id': f'EBZ-RBAC-{uuid4().hex[:8]}', 'patient_reference': 'PAT-RBAC'},
        headers=p_csrf,
    )
    assert created.status_code == 200
    rx_id = created.json()['prescription']['id']
    cred = prescriber.post(f'/api/v1/prescriptions/{rx_id}/credential', headers=p_csrf).json()

    pharmacy = pharmacist.get('/api/v1/pharmacies').json()[0]
    batch = pharmacist.get(f"/api/v1/pharmacies/{pharmacy['id']}/stock").json()[0]

    # Pharmacy assistant can verify, CANNOT dispense
    assert assistant.post('/api/v1/verification', json={'credential': cred['otp']}, headers=a_csrf).status_code == 200
    assert (
        assistant.post(
            f'/api/v1/prescriptions/{rx_id}/dispense',
            json={
                'pharmacy_id': pharmacy['id'],
                'batch_id': batch['id'],
                'quantity': 15,
                'credential': cred['otp'],
                'idempotency_key': f'idem-asst-{uuid4().hex[:8]}',
            },
            headers=a_csrf,
        ).status_code
        == 403
    )

    # Prescriber CANNOT dispense or view audit
    assert (
        prescriber.post(
            f'/api/v1/prescriptions/{rx_id}/dispense',
            json={
                'pharmacy_id': pharmacy['id'],
                'batch_id': batch['id'],
                'quantity': 15,
                'credential': cred['otp'],
                'idempotency_key': f'idem-presc-{uuid4().hex[:8]}',
            },
            headers=p_csrf,
        ).status_code
        == 403
    )
    assert prescriber.get('/api/v1/audit').status_code == 403

    # Pharmacist CANNOT view audit or facility analytics
    assert pharmacist.get('/api/v1/audit').status_code == 403
    assert pharmacist.get('/api/v1/analytics/facilities').status_code == 403

    # National analyst CAN view aggregate analytics, CANNOT read individual prescriptions or audit
    assert analyst.get('/api/v1/analytics/summary').status_code == 200
    assert analyst.get('/api/v1/analytics/facilities').status_code == 200
    assert analyst.get(f'/api/v1/prescriptions/{rx_id}').status_code == 403
    assert analyst.get('/api/v1/prescriptions').status_code == 403
    assert analyst.get('/api/v1/audit').status_code == 403

    # Platform operator CANNOT access clinical prescriptions, and audit view excludes clinical Prescription rows
    assert operator.get(f'/api/v1/prescriptions/{rx_id}').status_code == 403
    op_audit = operator.get('/api/v1/audit')
    assert op_audit.status_code == 200
    assert all(row['entity_type'] != 'Prescription' for row in op_audit.json())


def test_cross_facility_and_cross_pharmacy_isolation():
    fac_b = _create_facility_b_fixture()

    admin_a, a_csrf, _ = _login('demo.admin')
    pharm_a, ph_a_csrf, _ = _login('demo.pharmacist')
    presc_b, b_csrf, _ = _login(fac_b['prescriber_username'])
    pharm_b, ph_b_csrf, _ = _login(fac_b['pharmacist_username'])

    # Facility A users CANNOT read, activate, credential, revoke, or FHIR-export Facility B prescriptions
    assert admin_a.get(f"/api/v1/prescriptions/{fac_b['prescription_id']}").status_code == 403
    assert all(r['id'] != fac_b['prescription_id'] for r in admin_a.get('/api/v1/prescriptions?limit=100').json())
    assert admin_a.post(f"/api/v1/prescriptions/{fac_b['prescription_id']}/activate", headers=a_csrf).status_code == 403
    assert admin_a.post(f"/api/v1/prescriptions/{fac_b['prescription_id']}/credential", headers=a_csrf).status_code == 403
    assert admin_a.get(f"/api/v1/integrations/ebuzima/prescriptions/{fac_b['prescription_id']}/fhir").status_code == 403

    # Facility A admin analytics excludes Facility B
    fac_metrics = admin_a.get('/api/v1/analytics/facilities').json()['facilities']
    assert all(f['facility_code'] != fac_b['facility_code'] for f in fac_metrics)

    # Pharmacy A pharmacist CANNOT read Pharmacy B stock or batch traceability
    assert pharm_a.get(f"/api/v1/pharmacies/{fac_b['pharmacy_id']}/stock").status_code == 403
    assert pharm_a.get(f"/api/v1/stock/batches?pharmacy_id={fac_b['pharmacy_id']}").status_code == 403
    assert pharm_a.get(f"/api/v1/traceability/batches/{fac_b['batch_id']}").status_code == 403

    # Facility B prescriber issues credential for Facility B prescription; Pharmacy A pharmacist CANNOT verify or dispense it
    cred_b = presc_b.post(f"/api/v1/prescriptions/{fac_b['prescription_id']}/credential", headers=b_csrf)
    assert cred_b.status_code == 200
    otp_b = cred_b.json()['otp']

    assert pharm_a.post('/api/v1/verification', json={'credential': otp_b}, headers=ph_a_csrf).status_code == 403
    # Pharmacy A pharmacist attempting to dispense Facility B rx at Pharmacy A -> 403
    pharmacy_a = pharm_a.get('/api/v1/pharmacies').json()[0]
    batch_a = pharm_a.get(f"/api/v1/pharmacies/{pharmacy_a['id']}/stock").json()[0]
    assert (
        pharm_a.post(
            f"/api/v1/prescriptions/{fac_b['prescription_id']}/dispense",
            json={
                'pharmacy_id': pharmacy_a['id'],
                'batch_id': batch_a['id'],
                'quantity': 15,
                'credential': otp_b,
                'idempotency_key': f'idem-xfac-deny-{uuid4().hex[:8]}',
            },
            headers=ph_a_csrf,
        ).status_code
        == 403
    )

    # Facility B pharmacist CAN verify and dispense Facility B rx at Pharmacy B
    assert pharm_b.post('/api/v1/verification', json={'credential': otp_b}, headers=ph_b_csrf).status_code == 200
    ok_disp = pharm_b.post(
        f"/api/v1/prescriptions/{fac_b['prescription_id']}/dispense",
        json={
            'pharmacy_id': fac_b['pharmacy_id'],
            'batch_id': fac_b['batch_id'],
            'quantity': 15,
            'credential': otp_b,
            'idempotency_key': f'idem-facb-ok-{uuid4().hex[:8]}',
        },
        headers=ph_b_csrf,
    )
    assert ok_disp.status_code == 200
    assert ok_disp.json()['is_cross_facility'] is False
    assert ok_disp.json()['prescribing_facility_id'] == fac_b['facility_id']
    assert ok_disp.json()['dispensing_facility_id'] == fac_b['facility_id']


# ---------------------------------------------------------------------------
# 5. Conditional Cross-Facility Dispensing Policy (ADR-001 Decision 2)
# ---------------------------------------------------------------------------


def test_conditional_cross_facility_dispensing_policy(monkeypatch):
    suffix = uuid4().hex[:6].upper()
    with SessionLocal() as db:
        roles = seed_roles(db)
        fac_a = db.scalar(select(Facility).where(Facility.code == 'FAC-KGL-001'))
        ab = db.scalar(select(Antibiotic).where(Antibiotic.code == 'AMX500CAP'))
        # Standalone community retail pharmacy (facility_id=None)
        retail_pharm = Pharmacy(
            code=f'PHA-RET-{suffix}',
            name=f'Kigali Community Pharmacy {suffix}',
            district='Nyarugenge',
            facility_id=None,
            pharmacy_type='COMMUNITY_PHARMACY',
            active=True,
        )
        db.add(retail_pharm)
        db.flush()
        retail_batch = StockBatch(
            pharmacy_id=retail_pharm.id,
            antibiotic_id=ab.id,
            batch_number=f'RET-BATCH-{suffix}',
            expiry_date=date.today() + timedelta(days=365),
            quantity_available=50,
            source_reference='SYNTHETIC-RETAIL',
        )
        db.add(retail_batch)
        retail_user = ensure_local_user(
            db, username=f'retail.pharm.{suffix.lower()}', display_name='Retail Pharmacist', password=DEMO_USER_PASSWORD
        )
        ensure_role_scope(
            db, user=retail_user, role=roles[ROLE_PHARMACIST], scope_type='PHARMACY', pharmacy_id=retail_pharm.id
        )
        db.commit()
        fac_a_id = fac_a.id
        retail_pharm_id = retail_pharm.id
        retail_batch_id = retail_batch.id
        retail_username = retail_user.username
        retail_user_id = retail_user.id

    svc = TestClient(app)
    ebz_headers = {'x-amrguard-integration-key': DEMO_EBUZIMA_API_KEY}
    presc_a, a_csrf, _ = _login('demo.prescriber')
    retail_client, r_csrf, _ = _login(retail_username)

    def _mint_rx(allow_external: bool):
        r = svc.post(
            '/api/v1/integrations/ebuzima/prescriptions',
            json={
                'external_id': f'EBZ-XFAC-{uuid4().hex[:8]}',
                'patient_reference': 'PAT-XFAC-001',
                'allow_external_dispensing': allow_external,
                'prescriber': {
                    'external_user_id': 'EBZ-USER-001',
                    'name': 'Demo Prescriber',
                    'facility_code': 'FAC-KGL-001',
                    'facility_name': 'AMRGuard Demo Hospital',
                    'district': 'Gasabo',
                },
                'items': [
                    {
                        'antibiotic_code': 'AMX500CAP',
                        'generic_name': 'Amoxicillin',
                        'strength': '500 mg',
                        'formulation': 'Capsule',
                        'route': 'Oral',
                        'dose': 500,
                        'frequency_per_day': 3,
                        'duration_days': 5,
                        'quantity': 15,
                        'indication': 'Outpatient treatment',
                    }
                ],
            },
            headers=ebz_headers,
        )
        assert r.status_code == 200, r.text
        rx_id = r.json()['id']
        cred = presc_a.post(f'/api/v1/prescriptions/{rx_id}/credential', headers=a_csrf).json()
        return rx_id, cred['otp']

    rx_ext_id, otp_ext = _mint_rx(allow_external=True)
    rx_noext_id, otp_noext = _mint_rx(allow_external=False)

    # Case 1: Global flag disabled by default -> DENIED (403)
    assert settings.cross_facility_dispensing_enabled is False
    assert retail_client.post('/api/v1/verification', json={'credential': otp_ext}, headers=r_csrf).status_code == 403
    assert (
        retail_client.post(
            f'/api/v1/prescriptions/{rx_ext_id}/dispense',
            json={
                'pharmacy_id': retail_pharm_id,
                'batch_id': retail_batch_id,
                'quantity': 15,
                'credential': otp_ext,
                'idempotency_key': f'idem-xf1-{uuid4().hex[:8]}',
            },
            headers=r_csrf,
        ).status_code
        == 403
    )

    # Enable conditional cross-facility feature flag
    monkeypatch.setattr(settings, 'cross_facility_dispensing_enabled', True)

    # Case 2: Flag enabled, but pharmacy not in approved network -> DENIED (403)
    assert (
        retail_client.post(
            f'/api/v1/prescriptions/{rx_ext_id}/dispense',
            json={
                'pharmacy_id': retail_pharm_id,
                'batch_id': retail_batch_id,
                'quantity': 15,
                'credential': otp_ext,
                'idempotency_key': f'idem-xf2-{uuid4().hex[:8]}',
            },
            headers=r_csrf,
        ).status_code
        == 403
    )

    # Provision approved network linking FAC-KGL-001 and retail_pharm, WITHOUT medicine permission yet
    with SessionLocal() as db:
        net = PharmacyNetwork(code=f'NET-{suffix}', name=f'Kigali Approved Retail Network {suffix}', active=True)
        db.add(net)
        db.flush()
        db.add(PharmacyNetworkFacility(network_id=net.id, facility_id=fac_a_id, active=True))
        db.add(
            PharmacyNetworkPharmacy(
                network_id=net.id, pharmacy_id=retail_pharm_id, allow_all_medicines=False, active=True
            )
        )
        db.commit()
        net_id = net.id

    # Case 3: Prescription does NOT permit external dispensing -> DENIED (403)
    assert (
        retail_client.post(
            f'/api/v1/prescriptions/{rx_noext_id}/dispense',
            json={
                'pharmacy_id': retail_pharm_id,
                'batch_id': retail_batch_id,
                'quantity': 15,
                'credential': otp_noext,
                'idempotency_key': f'idem-xf3-{uuid4().hex[:8]}',
            },
            headers=r_csrf,
        ).status_code
        == 403
    )

    # Case 4: In network + prescription allows external, but antibiotic NOT permitted -> DENIED (403)
    assert (
        retail_client.post(
            f'/api/v1/prescriptions/{rx_ext_id}/dispense',
            json={
                'pharmacy_id': retail_pharm_id,
                'batch_id': retail_batch_id,
                'quantity': 15,
                'credential': otp_ext,
                'idempotency_key': f'idem-xf4-{uuid4().hex[:8]}',
            },
            headers=r_csrf,
        ).status_code
        == 403
    )

    # Grant explicit medicine permission for AMX500CAP
    with SessionLocal() as db:
        db.add(
            PharmacyNetworkMedicinePermission(
                network_id=net_id, pharmacy_id=retail_pharm_id, antibiotic_code='AMX500CAP', active=True
            )
        )
        db.commit()

    # Case 5: ALL conditions satisfied -> ALLOWED (200) with complete cross-facility attribution!
    ver = retail_client.post('/api/v1/verification', json={'credential': otp_ext}, headers=r_csrf)
    assert ver.status_code == 200

    disp = retail_client.post(
        f'/api/v1/prescriptions/{rx_ext_id}/dispense',
        json={
            'pharmacy_id': retail_pharm_id,
            'batch_id': retail_batch_id,
            'quantity': 15,
            'credential': otp_ext,
            'idempotency_key': f'idem-xf5-{uuid4().hex[:8]}',
        },
        headers=r_csrf,
    )
    assert disp.status_code == 200, disp.text
    body = disp.json()
    assert body['is_cross_facility'] is True
    assert body['actor_user_id'] == retail_user_id
    assert body['prescribing_facility_id'] == fac_a_id
    assert body['dispensing_facility_id'] is None

    with SessionLocal() as db:
        tx = db.scalar(select(DispensingTransaction).where(DispensingTransaction.transaction_id == body['transaction_id']))
        assert tx is not None
        assert tx.actor_user_id == retail_user_id
        assert tx.prescribing_facility_id == fac_a_id
        assert tx.dispensing_facility_id is None
        assert tx.is_cross_facility is True

        ev = db.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == 'DISPENSED',
                AuditEvent.entity_id == str(rx_ext_id),
            )
        )
        assert ev is not None
        assert ev.actor_type == 'HUMAN'
        assert ev.actor_id == f'user:{retail_user_id}'
        assert ev.facility_id == fac_a_id
        assert ev.pharmacy_id == retail_pharm_id
        details = json.loads(ev.details)
        assert details['is_cross_facility'] is True
        assert details['network_id'] == net_id


# ---------------------------------------------------------------------------
# 6. Explicit Scope Constraint, Dispensing Guardrails & Append-Only Audit
# ---------------------------------------------------------------------------


def test_nullable_scope_abuse_rejected_by_database_check_constraint():
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == 'demo.pharmacist'))
        role = db.scalar(select(UserRoleScope.role_id).limit(1))
        bad_grant = UserRoleScope(
            user_id=user.id,
            role_id=role,
            scope_type='FACILITY',
            facility_id=None,  # violates ck_user_role_scopes_explicit_scope!
            active=True,
        )
        db.add(bad_grant)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_dispense_requires_idempotency_key_and_production_blocks_query_otp(monkeypatch):
    client, csrf, _ = _login('demo.pharmacist')
    missing_idem = client.post(
        '/api/v1/prescriptions/1/dispense',
        json={'pharmacy_id': 1, 'batch_id': 1, 'quantity': 1, 'credential': '123456'},
        headers=csrf,
    )
    assert missing_idem.status_code == 422

    monkeypatch.setattr(settings, 'credential_hmac_secret', settings.effective_hmac_secret)
    monkeypatch.setattr(settings, 'app_env', 'production')
    monkeypatch.setattr(settings, 'allow_local_auth', True)
    gone = client.post('/api/v1/verification/otp', params={'otp': '123456'}, headers=csrf)
    assert gone.status_code == 410


def test_verification_rate_limiting_enforced(monkeypatch):
    monkeypatch.setattr(settings, 'credential_verify_rate_limit', 2)
    client, csrf, _ = _login('demo.pharmacist')
    assert client.post('/api/v1/verification', json={'credential': '000001'}, headers=csrf).status_code == 401
    assert client.post('/api/v1/verification', json={'credential': '000002'}, headers=csrf).status_code == 401
    assert client.post('/api/v1/verification', json={'credential': '000003'}, headers=csrf).status_code == 429


def test_audit_attribution_redaction_correlation_and_append_only_orm_protection():
    admin, csrf, body = _login('demo.admin')
    req_id = f'corr-test-{uuid4().hex[:10]}'
    resp = admin.get('/api/v1/audit?limit=10', headers={'X-Request-ID': req_id})
    assert resp.status_code == 200
    assert resp.headers.get('X-Request-ID') == req_id

    with SessionLocal() as db:
        access_ev = db.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == 'AUDIT_LOG_ACCESSED',
                AuditEvent.correlation_id == req_id,
            )
        )
        assert access_ev is not None
        assert access_ev.actor_type == 'HUMAN'
        assert access_ev.actor_id == f"user:{body['user_id']}"
        assert access_ev.outcome == 'SUCCESS'

        # Sensitive detail redaction check
        ev = record_audit(
            db,
            'SENSITIVE_REDACTION_CHECK',
            'Test',
            '1',
            'AMRGuard',
            details={'password': 'secret-value', 'otp': '123456', 'safe': 'ok'},
        )
        db.commit()
        db.refresh(ev)
        parsed = json.loads(ev.details)
        assert parsed['password'] == '[REDACTED]'
        assert parsed['otp'] == '[REDACTED]'
        assert parsed['safe'] == 'ok'

        # ORM append-only protection: UPDATE blocked
        ev.outcome = 'TAMPERED'
        with pytest.raises(PermissionError):
            db.commit()
        db.rollback()

        # ORM append-only protection: DELETE blocked
        reloaded = db.get(AuditEvent, ev.id)
        db.delete(reloaded)
        with pytest.raises(PermissionError):
            db.commit()
        db.rollback()
