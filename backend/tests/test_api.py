import os

os.environ['DATABASE_URL'] = 'sqlite:///./test_amrguard.db'
os.environ['APP_ENV'] = 'test'
os.environ['INTEGRATION_API_KEY'] = ''

from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.db.seed import (
    DEMO_EBUZIMA_API_KEY,
    DEMO_RMS_API_KEY,
    DEMO_USER_PASSWORD,
    seed_demo,
)
from app.db.session import Base, SessionLocal, engine
from app.main import app

Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)
with SessionLocal() as _db:
    seed_demo(_db)


def login_client(username: str = 'demo.clinician', password: str = DEMO_USER_PASSWORD) -> tuple[TestClient, dict[str, str]]:
    c = TestClient(app)
    resp = c.post('/api/v1/auth/login', json={'username': username, 'password': password})
    assert resp.status_code == 200, resp.text
    csrf = resp.json()['csrf_token']
    return c, {'X-CSRF-Token': csrf}


EBUZIMA_HEADERS = {'x-amrguard-integration-key': DEMO_EBUZIMA_API_KEY}
RMS_HEADERS = {'x-amrguard-integration-key': DEMO_RMS_API_KEY}

PAYLOAD = {
    'external_id': 'EBZ-RX-TEST-001',
    'patient_reference': 'PAT-DEMO-001',
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
            'indication': 'Bacterial infection',
        }
    ],
}


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limiter.reset()


def test_health():
    anon = TestClient(app)
    r = anon.get('/health')
    assert r.status_code == 200
    assert r.json()['version'] == '0.7.0'


def test_end_to_end_and_replay_protection():
    svc = TestClient(app)
    r = svc.post('/api/v1/integrations/ebuzima/prescriptions', json=PAYLOAD, headers=EBUZIMA_HEADERS)
    assert r.status_code == 200, r.text
    rx = r.json()
    assert rx['status'] == 'VALIDATED'

    client, csrf = login_client('demo.clinician')
    c = client.post(f"/api/v1/prescriptions/{rx['id']}/credential", headers=csrf)
    assert c.status_code == 200
    cred = c.json()

    v = client.post('/api/v1/verification', json={'credential': cred['otp']}, headers=csrf)
    assert v.status_code == 200

    pharmacies = client.get('/api/v1/pharmacies').json()
    stock = client.get(f"/api/v1/pharmacies/{pharmacies[0]['id']}/stock").json()
    batch = stock[0]

    bad = client.post(
        f"/api/v1/prescriptions/{rx['id']}/dispense",
        json={
            'pharmacy_id': pharmacies[0]['id'],
            'batch_id': batch['id'],
            'quantity': 20,
            'credential': cred['otp'],
            'idempotency_key': 'idem-test-001',
        },
        headers=csrf,
    )
    assert bad.status_code == 409

    good = client.post(
        f"/api/v1/prescriptions/{rx['id']}/dispense",
        json={
            'pharmacy_id': pharmacies[0]['id'],
            'batch_id': batch['id'],
            'quantity': 15,
            'credential': cred['otp'],
            'idempotency_key': 'idem-test-001',
        },
        headers=csrf,
    )
    assert good.status_code == 200
    assert good.json()['prescription_status'] == 'COMPLETED'
    assert good.json()['actor_user_id'] is not None

    replay = client.post(
        f"/api/v1/prescriptions/{rx['id']}/dispense",
        json={
            'pharmacy_id': pharmacies[0]['id'],
            'batch_id': batch['id'],
            'quantity': 15,
            'credential': cred['otp'],
            'idempotency_key': 'idem-test-001',
        },
        headers=csrf,
    )
    assert replay.status_code == 200
    assert replay.json()['replayed'] is True


def test_multi_item_prescription_requires_and_dispenses_items_independently():
    svc = TestClient(app)
    multi = {
        **PAYLOAD,
        'external_id': 'EBZ-RX-MULTI-ITEM',
        'items': [
            {**PAYLOAD['items'][0], 'quantity': 15},
            {
                **PAYLOAD['items'][0],
                'dose': 250,
                'frequency_per_day': 1,
                'duration_days': 3,
                'quantity': 3,
                'indication': 'Second item',
            },
        ],
    }
    response = svc.post('/api/v1/integrations/ebuzima/prescriptions', json=multi, headers=EBUZIMA_HEADERS)
    assert response.status_code == 200
    prescription_id = response.json()['id']

    client, csrf = login_client('demo.clinician')
    detail = client.get(f'/api/v1/prescriptions/{prescription_id}').json()
    first_item, second_item = detail['items']
    credential = client.post(f'/api/v1/prescriptions/{prescription_id}/credential', headers=csrf).json()
    pharmacies = client.get('/api/v1/pharmacies').json()
    batch = client.get(f"/api/v1/pharmacies/{pharmacies[0]['id']}/stock").json()[0]

    missing_item = client.post(
        f'/api/v1/prescriptions/{prescription_id}/dispense',
        json={
            'pharmacy_id': pharmacies[0]['id'],
            'batch_id': batch['id'],
            'quantity': 1,
            'credential': credential['otp'],
            'idempotency_key': 'idem-multi-missing',
        },
        headers=csrf,
    )
    assert missing_item.status_code == 422

    first = client.post(
        f'/api/v1/prescriptions/{prescription_id}/dispense',
        json={
            'pharmacy_id': pharmacies[0]['id'],
            'batch_id': batch['id'],
            'item_id': first_item['id'],
            'quantity': 15,
            'credential': credential['otp'],
            'idempotency_key': 'idem-multi-first',
        },
        headers=csrf,
    )
    assert first.status_code == 200 and first.json()['prescription_status'] == 'PARTIALLY_DISPENSED'

    second = client.post(
        f'/api/v1/prescriptions/{prescription_id}/dispense',
        json={
            'pharmacy_id': pharmacies[0]['id'],
            'batch_id': batch['id'],
            'item_id': second_item['id'],
            'quantity': 3,
            'credential': credential['otp'],
            'idempotency_key': 'idem-multi-second',
        },
        headers=csrf,
    )
    assert second.status_code == 200 and second.json()['prescription_status'] == 'COMPLETED'

    mismatch = client.post(
        f'/api/v1/prescriptions/{prescription_id}/dispense',
        json={
            'pharmacy_id': pharmacies[0]['id'],
            'batch_id': batch['id'],
            'item_id': first_item['id'],
            'quantity': 14,
            'credential': credential['otp'],
            'idempotency_key': 'idem-multi-first',
        },
        headers=csrf,
    )
    assert mismatch.status_code == 409


def test_duplicate_external_prescription_is_idempotent():
    svc = TestClient(app)
    r1 = svc.post(
        '/api/v1/integrations/ebuzima/prescriptions',
        json={**PAYLOAD, 'external_id': 'EBZ-RX-IDEMPOTENT'},
        headers=EBUZIMA_HEADERS,
    )
    assert r1.status_code == 200
    r2 = svc.post(
        '/api/v1/integrations/ebuzima/prescriptions',
        json={**PAYLOAD, 'external_id': 'EBZ-RX-IDEMPOTENT'},
        headers=EBUZIMA_HEADERS,
    )
    assert r2.status_code == 200
    assert r2.json()['id'] == r1.json()['id']


def test_demo_prescription_accepts_order_fields_and_expiry():
    client, csrf = login_client('demo.prescriber')
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=36)).isoformat()
    response = client.post(
        '/api/v1/demo/prescriptions',
        json={
            'external_id': 'EBZ-RX-ORDER-FIELDS',
            'patient_reference': 'PATIENT-ORDER-001',
            'antibiotic_code': 'AMX500CAP',
            'dose': 250,
            'frequency_per_day': 2,
            'duration_days': 4,
            'quantity': 8,
            'indication': 'Order form regression',
            'expires_at': expires_at,
        },
        headers=csrf,
    )
    assert response.status_code == 200
    order = response.json()['prescription']
    assert order['patient_reference'] == 'PATIENT-ORDER-001'
    assert order['items'][0]['dose'] == '250.000'
    assert order['items'][0]['frequency_per_day'] == '2.00'
    assert order['items'][0]['authorized_quantity'] == 8
    stored_expiry = datetime.fromisoformat(order['expires_at']).replace(tzinfo=timezone.utc)
    assert stored_expiry == datetime.fromisoformat(expires_at)


def test_demo_prescription_rejects_expired_or_excessive_lifetime():
    client, csrf = login_client('demo.prescriber')
    base = {'external_id': 'EBZ-RX-BAD-LIFETIME', 'patient_reference': 'PATIENT-ORDER-002'}
    expired = client.post(
        '/api/v1/demo/prescriptions',
        json={**base, 'expires_at': (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()},
        headers=csrf,
    )
    assert expired.status_code == 422
    excessive = client.post(
        '/api/v1/demo/prescriptions',
        json={
            **base,
            'external_id': 'EBZ-RX-EXCESS-LIFETIME',
            'expires_at': (datetime.now(timezone.utc) + timedelta(days=31)).isoformat(),
        },
        headers=csrf,
    )
    assert excessive.status_code == 422


def test_batch_catalog_and_traceability_are_available_for_authorized_pharmacy_staff():
    client, _ = login_client('demo.pharmacist')
    batches = client.get('/api/v1/stock/batches')
    assert batches.status_code == 200 and batches.json()
    batch = batches.json()[0]
    trace = client.get(f"/api/v1/traceability/batches/{batch['id']}")
    assert trace.status_code == 200
    assert trace.json()['batch']['batch_number'] == batch['batch_number']
    assert 'events' in trace.json() and 'linked_transactions' in trace.json()


def test_rms_stock_events_are_idempotent_and_traceable():
    svc = TestClient(app)
    event = {
        'source_system': 'RMS',
        'source_reference': 'RMS-EVENT-TEST-001',
        'pharmacy_code': 'PHA-KGL-001',
        'pharmacy_name': 'AMRGuard Demo Pharmacy',
        'district': 'Gasabo',
        'antibiotic_code': 'AMX-INT-TEST',
        'generic_name': 'Amoxicillin',
        'strength': '250 mg',
        'formulation': 'Capsule',
        'route': 'Oral',
        'batch_number': 'RMS-BATCH-TEST-001',
        'expiry_date': '2028-12-31',
        'event_type': 'RECEIPT',
        'quantity_delta': 40,
    }
    url = '/api/v1/integrations/rms/stock-events'
    first = svc.post(url, json=event, headers=RMS_HEADERS)
    assert first.status_code == 200 and first.json()['quantity_available'] == 40
    replay = svc.post(url, json=event, headers=RMS_HEADERS)
    assert replay.status_code == 200 and replay.json()['replayed'] is True
    conflict = svc.post(url, json={**event, 'quantity_delta': 45}, headers=RMS_HEADERS)
    assert conflict.status_code == 409
    adjustment = svc.post(
        url,
        json={**event, 'source_reference': 'RMS-EVENT-TEST-002', 'event_type': 'ADJUSTMENT', 'quantity_delta': -5},
        headers=RMS_HEADERS,
    )
    assert adjustment.status_code == 200 and adjustment.json()['quantity_available'] == 35
    overdraw = svc.post(
        url,
        json={**event, 'source_reference': 'RMS-EVENT-TEST-003', 'event_type': 'ADJUSTMENT', 'quantity_delta': -50},
        headers=RMS_HEADERS,
    )
    assert overdraw.status_code == 409

    client, _ = login_client('demo.pharmacist')
    trace = client.get(f"/api/v1/traceability/batches/{first.json()['batch_id']}")
    assert trace.status_code == 200 and len(trace.json()['events']) == 2


def test_stewardship_reminder_requires_consent_and_is_provider_pending():
    client, csrf = login_client('demo.clinician')
    created = client.post(
        '/api/v1/demo/prescriptions',
        json={
            'external_id': 'EBZ-RX-REMINDER-001',
            'patient_reference': 'PATIENT-REMINDER-001',
            'duration_days': 5,
            'quantity': 15,
        },
        headers=csrf,
    )
    assert created.status_code == 200
    prescription_id = created.json()['prescription']['id']
    base = f'/api/v1/prescriptions/{prescription_id}/stewardship-reminder'
    denied = client.post(base, json={'consent': False, 'consent_reference': 'CONSENT-001'}, headers=csrf)
    assert denied.status_code == 422
    premature = client.post(base, json={'consent': True, 'consent_reference': 'CONSENT-001'}, headers=csrf)
    assert premature.status_code == 409
    credential = client.post(f'/api/v1/prescriptions/{prescription_id}/credential', headers=csrf)
    assert credential.status_code == 200
    pharmacies = client.get('/api/v1/pharmacies').json()
    batches = client.get(f"/api/v1/pharmacies/{pharmacies[0]['id']}/stock").json()
    dispensed = client.post(
        f'/api/v1/prescriptions/{prescription_id}/dispense',
        json={
            'pharmacy_id': pharmacies[0]['id'],
            'batch_id': batches[0]['id'],
            'quantity': 15,
            'credential': credential.json()['otp'],
            'idempotency_key': 'idem-reminder-001',
        },
        headers=csrf,
    )
    assert dispensed.status_code == 200
    scheduled = client.post(base, json={'consent': True, 'consent_reference': 'CONSENT-001'}, headers=csrf)
    assert scheduled.status_code == 200
    assert scheduled.json()['status'] == 'PENDING_PROVIDER'
    assert scheduled.json()['consent_recorded'] is True
    assert scheduled.json()['delivery_configured'] is False
    assert scheduled.json()['consent_reference'] == 'CONSENT-001'
    assert 'phone_number' not in client.get('/api/v1/stewardship/reminders').json()[0]
    duplicate = client.post(base, json={'consent': True, 'consent_reference': 'CONSENT-001'}, headers=csrf)
    assert duplicate.status_code == 409


def test_stewardship_reminder_requires_consent_reference():
    client, csrf = login_client('demo.clinician')
    response = client.post(
        '/api/v1/prescriptions/1/stewardship-reminder',
        json={'consent': True, 'consent_reference': 'x'},
        headers=csrf,
    )
    assert response.status_code == 422


def test_otp_verification_route_works():
    svc = TestClient(app)
    r = svc.post(
        '/api/v1/integrations/ebuzima/prescriptions',
        json={**PAYLOAD, 'external_id': 'EBZ-RX-OTP-ROUTE'},
        headers=EBUZIMA_HEADERS,
    )
    assert r.status_code == 200
    rx = r.json()

    client, csrf = login_client('demo.clinician')
    c = client.post(f"/api/v1/prescriptions/{rx['id']}/credential", headers=csrf)
    assert c.status_code == 200
    otp = c.json()['otp']
    v = client.post('/api/v1/verification/otp', params={'otp': otp}, headers=csrf)
    assert v.status_code == 200
    assert v.json()['verified'] is True
    assert v.headers.get('Deprecation') == 'true'


def test_reissuing_credential_replaces_previous_credential():
    svc = TestClient(app)
    r = svc.post(
        '/api/v1/integrations/ebuzima/prescriptions',
        json={**PAYLOAD, 'external_id': 'EBZ-RX-CREDENTIAL-REISSUE'},
        headers=EBUZIMA_HEADERS,
    )
    assert r.status_code == 200
    rx = r.json()

    client, csrf = login_client('demo.clinician')
    first = client.post(f"/api/v1/prescriptions/{rx['id']}/credential", headers=csrf)
    assert first.status_code == 200
    second = client.post(f"/api/v1/prescriptions/{rx['id']}/credential", headers=csrf)
    assert second.status_code == 200
    assert client.post('/api/v1/verification', json={'credential': first.json()['otp']}, headers=csrf).status_code == 401
    verified = client.post('/api/v1/verification', json={'credential': second.json()['otp']}, headers=csrf)
    assert verified.status_code == 200
    assert verified.json()['verified'] is True


def test_risk_scenario_blocks_intentional_quantity_mismatch():
    client, csrf = login_client('demo.prescriber')
    r = client.post('/api/v1/demo/risk-scenario', headers=csrf)
    assert r.status_code == 200
    data = r.json()
    assert data['scenario'] == 'intentional_block'
    assert data['prescription']['status'] == 'BLOCKED'
    assert any(x['code'] == 'QUANTITY_MISMATCH' and x['severity'] == 'BLOCK' for x in data['issues'])


def test_demo_prescription_endpoint_is_disabled_in_production(monkeypatch):
    client, csrf = login_client('demo.prescriber')
    monkeypatch.setattr(settings, 'credential_hmac_secret', settings.effective_hmac_secret)
    monkeypatch.setattr(settings, 'app_env', 'production')
    monkeypatch.setattr(settings, 'allow_local_auth', True)
    response = client.post(
        '/api/v1/demo/prescriptions',
        json={
            'external_id': 'EBZ-RX-PRODUCTION-DEMO-BLOCK',
            'patient_reference': 'PAT-PRODUCTION-DEMO-BLOCK',
            'antibiotic_code': 'AMX500CAP',
            'dose': 500,
            'frequency_per_day': 3,
            'duration_days': 5,
            'quantity': 15,
            'indication': 'Test only',
        },
        headers=csrf,
    )
    assert response.status_code == 404
