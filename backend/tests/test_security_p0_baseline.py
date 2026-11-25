from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re
from uuid import uuid4

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.core.rate_limit import rate_limiter
from app.db.seed import (
    DEMO_EBUZIMA_API_KEY,
    DEMO_USER_PASSWORD,
    seed_demo,
)
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.core import (
    Antibiotic,
    AuditEvent,
    Facility,
    Pharmacy,
    Prescription,
    PrescriptionCredential,
    StockBatch,
)

Base.metadata.create_all(engine)
with SessionLocal() as _db:
    seed_demo(_db)

EBUZIMA_HEADERS = {'x-amrguard-integration-key': DEMO_EBUZIMA_API_KEY}


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limiter.reset()


def _login(username: str = 'demo.clinician') -> tuple[TestClient, dict[str, str]]:
    c = TestClient(app)
    resp = c.post('/api/v1/auth/login', json={'username': username, 'password': DEMO_USER_PASSWORD})
    assert resp.status_code == 200, resp.text
    return c, {'X-CSRF-Token': resp.json()['csrf_token']}


def _create_prescription(external_suffix: str, expires_at: str | None = None, quantity: int = 15, duration_days: int = 5):
    svc = TestClient(app)
    payload = {
        'external_id': f'EBZ-SEC-{external_suffix}-{uuid4().hex[:8]}',
        'patient_reference': f'PAT-SYNTH-{uuid4().hex[:8]}',
        'prescriber': {
            'external_user_id': 'EBZ-USER-001',
            'name': 'Synthetic Prescriber',
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
                'duration_days': duration_days,
                'quantity': quantity,
                'indication': 'Synthetic clinical test indication',
            }
        ],
    }
    if expires_at is not None:
        payload['expires_at'] = expires_at
    response = svc.post('/api/v1/integrations/ebuzima/prescriptions', json=payload, headers=EBUZIMA_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def _get_default_pharmacy_and_batch(client: TestClient):
    pharmacies = client.get('/api/v1/pharmacies').json()
    pharmacy = next(p for p in pharmacies if p['code'] == 'PHA-KGL-001')
    stock = client.get(f"/api/v1/pharmacies/{pharmacy['id']}/stock").json()
    batch = next(b for b in stock if b['batch_number'] == 'AMX-2026-0042')
    return pharmacy, batch


def test_cross_prescription_credential_cannot_dispense_another_prescription():
    client, csrf = _login('demo.clinician')
    rx_a = _create_prescription('CROSS-A')
    rx_b = _create_prescription('CROSS-B')
    cred_a = client.post(f"/api/v1/prescriptions/{rx_a['id']}/credential", headers=csrf).json()
    _ = client.post(f"/api/v1/prescriptions/{rx_b['id']}/credential", headers=csrf).json()
    pharmacy, batch = _get_default_pharmacy_and_batch(client)

    stock_before = batch['quantity_available']
    attempt = client.post(
        f"/api/v1/prescriptions/{rx_b['id']}/dispense",
        json={
            'pharmacy_id': pharmacy['id'],
            'batch_id': batch['id'],
            'quantity': 15,
            'credential': cred_a['otp'],
            'idempotency_key': f'idem-cross-{uuid4().hex[:10]}',
        },
        headers=csrf,
    )
    assert attempt.status_code == 401
    assert 'does not match' in attempt.json()['detail'].lower()

    with SessionLocal() as db:
        reloaded_batch = db.get(StockBatch, batch['id'])
        assert reloaded_batch.quantity_available == stock_before
        mismatch_event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == 'CREDENTIAL_PRESCRIPTION_MISMATCH',
                AuditEvent.entity_id == str(rx_b['id']),
            )
        )
        assert mismatch_event is not None
        assert mismatch_event.actor_type == 'HUMAN'
        assert mismatch_event.outcome == 'DENIED'


def test_expired_and_revoked_credentials_are_rejected():
    client, csrf = _login('demo.clinician')
    rx = _create_prescription('CRED-STATE')
    cred = client.post(f"/api/v1/prescriptions/{rx['id']}/credential", headers=csrf).json()
    pharmacy, batch = _get_default_pharmacy_and_batch(client)

    with SessionLocal() as db:
        row = db.scalar(select(PrescriptionCredential).where(PrescriptionCredential.prescription_id == rx['id']))
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    assert client.post('/api/v1/verification', json={'credential': cred['otp']}, headers=csrf).status_code == 401
    assert (
        client.post(
            f"/api/v1/prescriptions/{rx['id']}/dispense",
            json={
                'pharmacy_id': pharmacy['id'],
                'batch_id': batch['id'],
                'quantity': 15,
                'credential': cred['otp'],
                'idempotency_key': f'idem-exp-cred-{uuid4().hex[:10]}',
            },
            headers=csrf,
        ).status_code
        == 401
    )

    cred2 = client.post(f"/api/v1/prescriptions/{rx['id']}/credential", headers=csrf).json()
    revoked = client.post(f"/api/v1/prescriptions/{rx['id']}/credential/revoke", headers=csrf)
    assert revoked.status_code == 200 and revoked.json()['revoked'] is True

    assert client.post('/api/v1/verification', json={'credential': cred2['qr_token']}, headers=csrf).status_code == 401
    assert (
        client.post(
            f"/api/v1/prescriptions/{rx['id']}/dispense",
            json={
                'pharmacy_id': pharmacy['id'],
                'batch_id': batch['id'],
                'quantity': 15,
                'credential': cred2['qr_token'],
                'idempotency_key': f'idem-rev-cred-{uuid4().hex[:10]}',
            },
            headers=csrf,
        ).status_code
        == 401
    )


def test_completed_dispense_consumes_and_revokes_credential():
    client, csrf = _login('demo.clinician')
    rx = _create_prescription('CRED-CONSUME')
    cred = client.post(f"/api/v1/prescriptions/{rx['id']}/credential", headers=csrf).json()
    pharmacy, batch = _get_default_pharmacy_and_batch(client)

    dispensed = client.post(
        f"/api/v1/prescriptions/{rx['id']}/dispense",
        json={
            'pharmacy_id': pharmacy['id'],
            'batch_id': batch['id'],
            'quantity': 15,
            'credential': cred['otp'],
            'idempotency_key': f'idem-consume-{uuid4().hex[:10]}',
        },
        headers=csrf,
    )
    assert dispensed.status_code == 200
    assert dispensed.json()['prescription_status'] == 'COMPLETED'

    with SessionLocal() as db:
        row = db.scalar(select(PrescriptionCredential).where(PrescriptionCredential.prescription_id == rx['id']))
        assert row.used_count == 1
        assert row.revoked is True
        assert row.revoked_at is not None

    assert client.post('/api/v1/verification', json={'credential': cred['otp']}, headers=csrf).status_code == 401


def test_partial_dispense_preserves_status_on_reissue_and_replay():
    client, csrf = _login('demo.clinician')
    rx = _create_prescription('PARTIAL-PRESERVE')
    cred = client.post(f"/api/v1/prescriptions/{rx['id']}/credential", headers=csrf).json()
    pharmacy, batch = _get_default_pharmacy_and_batch(client)
    idem = f'idem-partial-{uuid4().hex[:10]}'

    first = client.post(
        f"/api/v1/prescriptions/{rx['id']}/dispense",
        json={
            'pharmacy_id': pharmacy['id'],
            'batch_id': batch['id'],
            'quantity': 5,
            'credential': cred['otp'],
            'idempotency_key': idem,
        },
        headers=csrf,
    )
    assert first.status_code == 200
    assert first.json()['prescription_status'] == 'PARTIALLY_DISPENSED'

    replay = client.post(
        f"/api/v1/prescriptions/{rx['id']}/dispense",
        json={
            'pharmacy_id': pharmacy['id'],
            'batch_id': batch['id'],
            'quantity': 5,
            'credential': cred['otp'],
            'idempotency_key': idem,
        },
        headers=csrf,
    )
    assert replay.status_code == 200
    assert replay.json()['replayed'] is True
    assert replay.json()['prescription_status'] == 'PARTIALLY_DISPENSED'

    reissued = client.post(f"/api/v1/prescriptions/{rx['id']}/credential", headers=csrf)
    assert reissued.status_code == 200
    detail = client.get(f"/api/v1/prescriptions/{rx['id']}").json()
    assert detail['status'] == 'PARTIALLY_DISPENSED'


def test_expired_prescription_rejected_across_lifecycle():
    client, csrf = _login('demo.clinician')
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    rx_cred = _create_prescription('RX-EXP-CRED', expires_at=past)
    assert client.post(f"/api/v1/prescriptions/{rx_cred['id']}/credential", headers=csrf).status_code == 409
    assert client.get(f"/api/v1/prescriptions/{rx_cred['id']}").json()['status'] == 'EXPIRED'

    rx_act = _create_prescription('RX-EXP-ACT', expires_at=past)
    assert client.post(f"/api/v1/prescriptions/{rx_act['id']}/activate", headers=csrf).status_code == 409
    assert client.get(f"/api/v1/prescriptions/{rx_act['id']}").json()['status'] == 'EXPIRED'

    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    rx_ver = _create_prescription('RX-EXP-VER', expires_at=future)
    cred = client.post(f"/api/v1/prescriptions/{rx_ver['id']}/credential", headers=csrf).json()
    with SessionLocal() as db:
        row = db.get(Prescription, rx_ver['id'])
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()
    assert client.post('/api/v1/verification', json={'credential': cred['otp']}, headers=csrf).status_code == 409


def test_expired_stock_batch_is_rejected_for_dispensing():
    client, csrf = _login('demo.clinician')
    rx = _create_prescription('EXP-BATCH')
    cred = client.post(f"/api/v1/prescriptions/{rx['id']}/credential", headers=csrf).json()
    pharmacy, _ = _get_default_pharmacy_and_batch(client)

    with SessionLocal() as db:
        ab = db.scalar(select(Antibiotic).where(Antibiotic.code == 'AMX500CAP'))
        expired_batch = StockBatch(
            pharmacy_id=pharmacy['id'],
            antibiotic_id=ab.id,
            batch_number=f'EXP-BATCH-{uuid4().hex[:6]}',
            expiry_date=datetime.now(timezone.utc).date() - timedelta(days=1),
            quantity_available=50,
            source_reference='SYNTHETIC EXPIRED TEST',
        )
        db.add(expired_batch)
        db.commit()
        db.refresh(expired_batch)
        expired_batch_id = expired_batch.id

    response = client.post(
        f"/api/v1/prescriptions/{rx['id']}/dispense",
        json={
            'pharmacy_id': pharmacy['id'],
            'batch_id': expired_batch_id,
            'quantity': 15,
            'credential': cred['otp'],
            'idempotency_key': f'idem-exp-batch-{uuid4().hex[:10]}',
        },
        headers=csrf,
    )
    assert response.status_code == 409
    assert 'expired' in response.json()['detail'].lower()

    with SessionLocal() as db:
        assert db.get(StockBatch, expired_batch_id).quantity_available == 50


def test_wrong_pharmacy_and_inactive_pharmacy_rejected_for_dispensing():
    client, csrf = _login('demo.clinician')
    rx = _create_prescription('WRONG-PHARM')
    cred = client.post(f"/api/v1/prescriptions/{rx['id']}/credential", headers=csrf).json()
    _, batch = _get_default_pharmacy_and_batch(client)

    with SessionLocal() as db:
        fac = db.scalar(select(Facility).where(Facility.code == 'FAC-KGL-001'))
        other_active = Pharmacy(
            code=f'PHA-OTH-{uuid4().hex[:6]}',
            name='Other Active Pharmacy',
            district='Kicukiro',
            facility_id=fac.id,
            active=True,
        )
        inactive = Pharmacy(
            code=f'PHA-INA-{uuid4().hex[:6]}',
            name='Inactive Pharmacy',
            district='Kicukiro',
            facility_id=fac.id,
            active=False,
        )
        db.add_all([other_active, inactive])
        db.commit()
        db.refresh(other_active)
        db.refresh(inactive)
        other_id = other_active.id
        inactive_id = inactive.id

    wrong_owner = client.post(
        f"/api/v1/prescriptions/{rx['id']}/dispense",
        json={
            'pharmacy_id': other_id,
            'batch_id': batch['id'],
            'quantity': 15,
            'credential': cred['otp'],
            'idempotency_key': f'idem-wrong-ph-{uuid4().hex[:10]}',
        },
        headers=csrf,
    )
    assert wrong_owner.status_code == 403

    inactive_resp = client.post(
        f"/api/v1/prescriptions/{rx['id']}/dispense",
        json={
            'pharmacy_id': inactive_id,
            'batch_id': batch['id'],
            'quantity': 15,
            'credential': cred['otp'],
            'idempotency_key': f'idem-inact-ph-{uuid4().hex[:10]}',
        },
        headers=csrf,
    )
    assert inactive_resp.status_code == 403


def test_all_registered_routes_are_documented_in_authorization_matrix():
    matrix_path = Path(__file__).resolve().parents[2] / 'docs' / 'security' / 'API_AUTHORIZATION_MATRIX.md'
    assert matrix_path.exists(), 'API_AUTHORIZATION_MATRIX.md must exist'
    matrix_text = matrix_path.read_text(encoding='utf-8')

    undocumented = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods - {'HEAD', 'OPTIONS'}):
                expected_marker = f'`{method}` | `{route.path}`'
                if expected_marker not in matrix_text:
                    undocumented.append(f'{method} {route.path}')

    assert not undocumented, f'Routes missing from API_AUTHORIZATION_MATRIX.md: {undocumented}'


def test_every_non_public_route_enforces_authentication_dependency():
    public_routes = {
        ('GET', '/health'),
        ('GET', '/health/ready'),
        ('POST', '/api/v1/auth/login'),
    }
    unprotected = []
    anon = TestClient(app)

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods - {'HEAD', 'OPTIONS'}):
            if (method, route.path) in public_routes:
                continue
            path = route.path.replace('{transaction_id}', 'DT-NONEXISTENT')
            path = re.sub(r'\{[^}]+_id\}', '1', path)
            kwargs = {'json': {}} if method in {'POST', 'PUT', 'PATCH'} else {}
            if route.path == '/api/v1/verification/otp':
                kwargs = {'params': {'otp': '000000'}}
            resp = anon.request(method, path, **kwargs)
            if resp.status_code != 401:
                unprotected.append((method, route.path, resp.status_code))

    assert not unprotected, f'Non-public routes did not return 401 anonymously: {unprotected}'
