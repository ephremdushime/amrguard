from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.db.seed import seed_demo
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.core import (
    Antibiotic,
    AuditEvent,
    Pharmacy,
    Prescription,
    PrescriptionCredential,
    StockBatch,
)

Base.metadata.create_all(engine)
_db = SessionLocal()
seed_demo(_db)
_db.close()

client = TestClient(app)


def _create_prescription(external_suffix: str, expires_at: str | None = None, quantity: int = 15, duration_days: int = 5):
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
    response = client.post('/api/v1/integrations/ebuzima/prescriptions', json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _get_default_pharmacy_and_batch():
    pharmacies = client.get('/api/v1/pharmacies').json()
    pharmacy = next(p for p in pharmacies if p['code'] == 'PHA-KGL-001')
    stock = client.get(f"/api/v1/pharmacies/{pharmacy['id']}/stock").json()
    batch = next(b for b in stock if b['batch_number'] == 'AMX-2026-0042')
    return pharmacy, batch


def test_cross_prescription_credential_cannot_dispense_another_prescription():
    rx_a = _create_prescription('CROSS-A')
    rx_b = _create_prescription('CROSS-B')
    cred_a = client.post(f"/api/v1/prescriptions/{rx_a['id']}/credential").json()
    _ = client.post(f"/api/v1/prescriptions/{rx_b['id']}/credential").json()
    pharmacy, batch = _get_default_pharmacy_and_batch()

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


def test_expired_and_revoked_credentials_are_rejected():
    rx = _create_prescription('CRED-STATE')
    cred = client.post(f"/api/v1/prescriptions/{rx['id']}/credential").json()
    pharmacy, batch = _get_default_pharmacy_and_batch()

    # Force credential expiration
    with SessionLocal() as db:
        row = db.scalar(select(PrescriptionCredential).where(PrescriptionCredential.prescription_id == rx['id']))
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    assert client.post('/api/v1/verification', json={'credential': cred['otp']}).status_code == 401
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
        ).status_code
        == 401
    )

    # Reissue and explicitly revoke
    cred2 = client.post(f"/api/v1/prescriptions/{rx['id']}/credential").json()
    with SessionLocal() as db:
        row = db.scalar(select(PrescriptionCredential).where(PrescriptionCredential.prescription_id == rx['id']))
        row.revoked = True
        db.commit()

    assert client.post('/api/v1/verification', json={'credential': cred2['qr_token']}).status_code == 401
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
        ).status_code
        == 401
    )


def test_completed_dispense_consumes_and_revokes_credential():
    rx = _create_prescription('CRED-CONSUME')
    cred = client.post(f"/api/v1/prescriptions/{rx['id']}/credential").json()
    pharmacy, batch = _get_default_pharmacy_and_batch()

    dispensed = client.post(
        f"/api/v1/prescriptions/{rx['id']}/dispense",
        json={
            'pharmacy_id': pharmacy['id'],
            'batch_id': batch['id'],
            'quantity': 15,
            'credential': cred['otp'],
            'idempotency_key': f'idem-consume-{uuid4().hex[:10]}',
        },
    )
    assert dispensed.status_code == 200
    assert dispensed.json()['prescription_status'] == 'COMPLETED'

    with SessionLocal() as db:
        row = db.scalar(select(PrescriptionCredential).where(PrescriptionCredential.prescription_id == rx['id']))
        assert row.used_count == 1
        assert row.revoked is True

    assert client.post('/api/v1/verification', json={'credential': cred['otp']}).status_code == 401


def test_partial_dispense_preserves_status_on_reissue_and_replay():
    rx = _create_prescription('PARTIAL-PRESERVE')
    cred = client.post(f"/api/v1/prescriptions/{rx['id']}/credential").json()
    pharmacy, batch = _get_default_pharmacy_and_batch()
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
    )
    assert first.status_code == 200
    assert first.json()['prescription_status'] == 'PARTIALLY_DISPENSED'

    # Replay must report actual prescription status (PARTIALLY_DISPENSED), not COMPLETED
    replay = client.post(
        f"/api/v1/prescriptions/{rx['id']}/dispense",
        json={
            'pharmacy_id': pharmacy['id'],
            'batch_id': batch['id'],
            'quantity': 5,
            'credential': cred['otp'],
            'idempotency_key': idem,
        },
    )
    assert replay.status_code == 200
    assert replay.json()['replayed'] is True
    assert replay.json()['prescription_status'] == 'PARTIALLY_DISPENSED'

    # Reissuing credential must not clobber PARTIALLY_DISPENSED back to ACTIVE
    reissued = client.post(f"/api/v1/prescriptions/{rx['id']}/credential")
    assert reissued.status_code == 200
    detail = client.get(f"/api/v1/prescriptions/{rx['id']}").json()
    assert detail['status'] == 'PARTIALLY_DISPENSED'


def test_expired_prescription_rejected_across_lifecycle():
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    rx_cred = _create_prescription('RX-EXP-CRED', expires_at=past)
    assert client.post(f"/api/v1/prescriptions/{rx_cred['id']}/credential").status_code == 409
    assert client.get(f"/api/v1/prescriptions/{rx_cred['id']}").json()['status'] == 'EXPIRED'

    rx_act = _create_prescription('RX-EXP-ACT', expires_at=past)
    assert client.post(f"/api/v1/prescriptions/{rx_act['id']}/activate").status_code == 409
    assert client.get(f"/api/v1/prescriptions/{rx_act['id']}").json()['status'] == 'EXPIRED'

    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    rx_ver = _create_prescription('RX-EXP-VER', expires_at=future)
    cred = client.post(f"/api/v1/prescriptions/{rx_ver['id']}/credential").json()
    with SessionLocal() as db:
        row = db.get(Prescription, rx_ver['id'])
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()
    assert client.post('/api/v1/verification', json={'credential': cred['otp']}).status_code == 409


def test_expired_stock_batch_is_rejected_for_dispensing():
    rx = _create_prescription('EXP-BATCH')
    cred = client.post(f"/api/v1/prescriptions/{rx['id']}/credential").json()
    pharmacy, _ = _get_default_pharmacy_and_batch()

    with SessionLocal() as db:
        ab = db.scalar(select(Antibiotic).where(Antibiotic.code == 'AMX500CAP'))
        expired_batch = StockBatch(
            pharmacy_id=pharmacy['id'],
            antibiotic_id=ab.id,
            batch_number=f'EXP-BATCH-{uuid4().hex[:6]}',
            expiry_date=date.today() - timedelta(days=1),
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
    )
    assert response.status_code == 409
    assert 'expired' in response.json()['detail'].lower()

    with SessionLocal() as db:
        assert db.get(StockBatch, expired_batch_id).quantity_available == 50


def test_wrong_pharmacy_and_inactive_pharmacy_rejected_for_dispensing():
    rx = _create_prescription('WRONG-PHARM')
    cred = client.post(f"/api/v1/prescriptions/{rx['id']}/credential").json()
    _, batch = _get_default_pharmacy_and_batch()

    with SessionLocal() as db:
        other_active = Pharmacy(
            code=f'PHA-OTH-{uuid4().hex[:6]}',
            name='Other Active Pharmacy',
            district='Kicukiro',
            active=True,
        )
        inactive = Pharmacy(
            code=f'PHA-INA-{uuid4().hex[:6]}',
            name='Inactive Pharmacy',
            district='Kicukiro',
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
    )
    assert inactive_resp.status_code == 403


def test_integration_key_gate_enforces_401_403_and_503(monkeypatch):
    sample = {
        'external_id': f'EBZ-KEY-TEST-{uuid4().hex[:8]}',
        'patient_reference': 'PAT-KEY-TEST',
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
                'duration_days': 5,
                'quantity': 15,
                'indication': 'Key test',
            }
        ],
    }

    monkeypatch.setattr(settings, 'app_env', 'production')
    monkeypatch.setattr(settings, 'integration_api_key', '')
    assert client.post('/api/v1/integrations/ebuzima/prescriptions', json=sample).status_code == 503

    secret = 's' * 40
    monkeypatch.setattr(settings, 'integration_api_key', secret)
    assert client.post('/api/v1/integrations/ebuzima/prescriptions', json=sample).status_code == 401
    assert (
        client.post(
            '/api/v1/integrations/ebuzima/prescriptions',
            json=sample,
            headers={'x-amrguard-integration-key': 'wrong-key'},
        ).status_code
        == 403
    )
    assert (
        client.post(
            '/api/v1/integrations/ebuzima/prescriptions',
            json=sample,
            headers={'x-amrguard-integration-key': secret},
        ).status_code
        == 200
    )


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
