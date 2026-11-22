"""P0 + P1 End-to-End Synthetic Pilot Smoke Verification Suite.

Exercises the full digital thread across:
1. e-Buzima partner FHIR R4 Bundle intake & prescription validation.
2. Secure QR token & OTP credential issuance.
3. RMS supply chain stock event ingestion (batch registration & inventory).
4. Pharmacy credential verification via short-lived OTP.
5. Multi-batch split dispensing transaction execution.
6. Leased outbox worker dispatch (RMS reconciliation + e-Buzima callback).
7. Verified patient SMS consent recording with cryptographic phone hashing.
8. Authoritative dose-level reminder schedule generation.
9. Clinical stewardship review completion with structured outcome.
10. End-to-end audit trail and analytics reconciliation.
"""

from datetime import date, datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.seed import (
    DEMO_EBUZIMA_API_KEY,
    DEMO_OUTBOX_WORKER_API_KEY,
    DEMO_RMS_API_KEY,
    DEMO_USER_PASSWORD,
    seed_demo,
)
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.core import (
    AuditEvent,
    ConsentRecord,
    DispensingItem,
    DispensingTransaction,
    IntegrationOutbox,
    Prescription,
    ReminderOccurrence,
    ReminderSchedule,
    StockBatch,
    StewardshipReview,
)

Base.metadata.create_all(engine)
with SessionLocal() as _db:
    seed_demo(_db)

UTC = timezone.utc


@pytest.fixture
def db_session():
    with SessionLocal() as session:
        yield session


def _login(username: str) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    resp = client.post('/api/v1/auth/login', json={'username': username, 'password': DEMO_USER_PASSWORD})
    assert resp.status_code == 200, f'Login failed for {username}: {resp.text}'
    csrf = resp.json().get('csrf_token', '')
    return client, {'x-csrf-token': csrf}


def test_full_synthetic_pilot_e2e_digital_thread(db_session: Session):
    """Executes the complete end-to-end digital thread with synthetic data."""
    client = TestClient(app)
    test_run_id = datetime.now(UTC).strftime('%Y%m%d%H%M%S')
    external_rx_id = f'EBZ-SMOKE-{test_run_id}'
    patient_ref = f'SYNTH-PAT-{test_run_id}'

    # -------------------------------------------------------------------------
    # 1. Ingest e-Buzima FHIR R4 Bundle
    # -------------------------------------------------------------------------
    fhir_bundle = {
        'resourceType': 'Bundle',
        'type': 'collection',
        'id': f'BUNDLE-{test_run_id}',
        'entry': [
            {
                'resource': {
                    'resourceType': 'MedicationRequest',
                    'id': f'MR-{test_run_id}',
                    'status': 'active',
                    'intent': 'order',
                    'subject': {'reference': f'Patient/{patient_ref}', 'display': 'Synthetic Patient'},
                    'recorder': {'reference': 'Organization/FAC-KGL-001'},
                    'medicationCodeableConcept': {
                        'coding': [
                            {
                                'system': 'http://moh.gov.rw/drugs',
                                'code': 'AMX500CAP',
                                'display': 'Amoxicillin 500 mg Capsule',
                            }
                        ],
                        'text': 'Amoxicillin 500 mg',
                    },
                    'dosageInstruction': [
                        {
                            'timing': {'repeat': {'frequency': 3, 'period': 1, 'periodUnit': 'd'}},
                            'doseAndRate': [{'doseQuantity': {'value': 500, 'unit': 'mg'}}],
                            'route': {'coding': [{'display': 'Oral'}]},
                        }
                    ],
                    'dispenseRequest': {
                        'expectedSupplyDuration': {'value': 5, 'unit': 'days'},
                        'quantity': {'value': 15, 'unit': 'capsules'},
                    },
                    'reasonCode': [{'text': 'Community Acquired Pneumonia'}],
                }
            }
        ],
    }

    resp = client.post(
        '/api/v1/integrations/ebuzima/fhir-bundle',
        headers={'x-amrguard-integration-key': DEMO_EBUZIMA_API_KEY},
        json=fhir_bundle,
    )
    assert resp.status_code == 200, f'FHIR bundle intake failed: {resp.text}'
    rx_data = resp.json()
    rx_id = rx_data['id']
    assert rx_data['status'] in ('VALIDATED', 'ACTIVE')

    # Query prescription from database
    rx = db_session.get(Prescription, rx_id)
    assert rx is not None
    assert len(rx.items) == 1
    rx_item = rx.items[0]
    assert rx_item.quantity == 15

    # -------------------------------------------------------------------------
    # 2. Issue Secure Credential (QR / OTP)
    # -------------------------------------------------------------------------
    prescriber_client, pres_headers = _login('demo.prescriber')
    cred_resp = prescriber_client.post(
        f'/api/v1/prescriptions/{rx_id}/credential',
        headers=pres_headers,
    )
    assert cred_resp.status_code == 200, f'Credential generation failed: {cred_resp.text}'
    cred_data = cred_resp.json()
    otp = cred_data['otp']
    qr_token = cred_data['qr_token']
    assert len(otp) == 6
    assert len(qr_token) >= 32

    # -------------------------------------------------------------------------
    # 3. Ingest RMS Stock Batches (Supply Chain Receipts)
    # -------------------------------------------------------------------------
    batch_num_1 = f'BAT-SMOKE-1-{test_run_id}'
    batch_num_2 = f'BAT-SMOKE-2-{test_run_id}'
    future_expiry = (datetime.now(UTC).date() + timedelta(days=180)).isoformat()

    # Receipt 1: 10 units
    receipt_1 = {
        'source_system': 'RMS',
        'source_reference': f'RMS-RCV-1-{test_run_id}',
        'pharmacy_code': 'PHA-KGL-001',
        'pharmacy_name': 'AMRGuard Demo Pharmacy',
        'district': 'Gasabo',
        'antibiotic_code': 'AMX500CAP',
        'generic_name': 'Amoxicillin',
        'strength': '500 mg',
        'formulation': 'Capsule',
        'route': 'Oral',
        'batch_number': batch_num_1,
        'expiry_date': future_expiry,
        'event_type': 'RECEIPT',
        'quantity_delta': 10,
    }
    resp1 = client.post(
        '/api/v1/integrations/rms/stock-events',
        headers={'x-amrguard-integration-key': DEMO_RMS_API_KEY},
        json=receipt_1,
    )
    assert resp1.status_code == 200, f'RMS Receipt 1 failed: {resp1.text}'
    batch1_id = resp1.json()['batch_id']

    # Receipt 2: 10 units
    receipt_2 = {
        'source_system': 'RMS',
        'source_reference': f'RMS-RCV-2-{test_run_id}',
        'pharmacy_code': 'PHA-KGL-001',
        'pharmacy_name': 'AMRGuard Demo Pharmacy',
        'district': 'Gasabo',
        'antibiotic_code': 'AMX500CAP',
        'generic_name': 'Amoxicillin',
        'strength': '500 mg',
        'formulation': 'Capsule',
        'route': 'Oral',
        'batch_number': batch_num_2,
        'expiry_date': future_expiry,
        'event_type': 'RECEIPT',
        'quantity_delta': 10,
    }
    resp2 = client.post(
        '/api/v1/integrations/rms/stock-events',
        headers={'x-amrguard-integration-key': DEMO_RMS_API_KEY},
        json=receipt_2,
    )
    assert resp2.status_code == 200, f'RMS Receipt 2 failed: {resp2.text}'
    batch2_id = resp2.json()['batch_id']

    # -------------------------------------------------------------------------
    # 4. Verify Credential at Pharmacy
    # -------------------------------------------------------------------------
    pharm_client, pharm_headers = _login('demo.pharmacist')
    verify_resp = pharm_client.post(
        '/api/v1/verification',
        headers=pharm_headers,
        json={'credential': otp},
    )
    assert verify_resp.status_code == 200, f'Verification failed: {verify_resp.text}'
    v_data = verify_resp.json()
    assert v_data['prescription']['id'] == rx_id

    # -------------------------------------------------------------------------
    # 5. Multi-Batch Split Dispensing (10 from Batch 1, 5 from Batch 2)
    # -------------------------------------------------------------------------
    dispense_payload = {
        'pharmacy_id': 1,
        'item_id': rx_item.id,
        'allocations': [
            {'batch_id': batch1_id, 'quantity': 10},
            {'batch_id': batch2_id, 'quantity': 5},
        ],
        'credential': otp,
        'idempotency_key': f'IDEM-SMOKE-{test_run_id}',
    }
    disp_resp = pharm_client.post(
        f'/api/v1/prescriptions/{rx_id}/dispense',
        headers=pharm_headers,
        json=dispense_payload,
    )
    assert disp_resp.status_code == 200, f'Dispense failed: {disp_resp.text}'
    disp_data = disp_resp.json()
    assert disp_data['prescription_status'] == 'COMPLETED'
    assert disp_data['quantity_dispensed'] == 15
    tx_id = disp_data['transaction_id']

    # Verify inventory was decremented correctly
    db_session.expire_all()
    b1 = db_session.get(StockBatch, batch1_id)
    b2 = db_session.get(StockBatch, batch2_id)
    assert b1.quantity_available == 0
    assert b2.quantity_available == 5

    # -------------------------------------------------------------------------
    # 6. Verify Outbox Entries & Dispatch via Worker
    # -------------------------------------------------------------------------
    outbox_entries = db_session.scalars(
        select(IntegrationOutbox).where(IntegrationOutbox.aggregate_id == tx_id)
    ).all()
    assert len(outbox_entries) >= 2
    systems = {e.destination_system for e in outbox_entries}
    assert 'RMS_DISPENSE_RECONCILE' in systems
    assert 'EBUZIMA_DISPENSE_UPDATE' in systems

    # Worker dispatch tick
    worker_client = TestClient(app)
    tick_resp = worker_client.post(
        '/api/v1/integrations/outbox/dispatch-tick',
        headers={'x-amrguard-integration-key': DEMO_OUTBOX_WORKER_API_KEY},
    )
    assert tick_resp.status_code == 200
    tick_data = tick_resp.json()
    assert tick_data['dispatched'] >= 2

    # -------------------------------------------------------------------------
    # 7. Capture Patient SMS Consent
    # -------------------------------------------------------------------------
    consent_payload = {
        'patient_reference': rx.patient_reference,
        'phone_number': '+250788123456',
        'purpose': 'DOSE_REMINDER',
        'channel': 'SMS',
        'language': 'rw',
        'evidence_reference': f'CLIN-CONSENT-FORM-{test_run_id}',
    }
    consent_resp = prescriber_client.post(
        '/api/v1/consent',
        headers=pres_headers,
        json=consent_payload,
    )
    assert consent_resp.status_code == 200, f'Consent capture failed: {consent_resp.text}'
    consent_data = consent_resp.json()
    assert consent_data['status'] == 'ACTIVE'
    assert consent_data['recipient_phone_masked'] == '+250 78 *** **56'

    # -------------------------------------------------------------------------
    # 8. Schedule Authoritative Dose-Level Reminders
    # -------------------------------------------------------------------------
    sched_resp = prescriber_client.post(
        f'/api/v1/prescriptions/{rx_id}/reminders/schedule',
        headers=pres_headers,
        json={'prescription_item_id': rx_item.id},
    )
    assert sched_resp.status_code == 200, f'Reminder scheduling failed: {sched_resp.text}'
    sched_data = sched_resp.json()
    assert sched_data['total_doses'] == 15
    assert len(sched_data['occurrences']) == 15  # 3 doses/day * 5 days

    # -------------------------------------------------------------------------
    # 9. Complete Clinical Stewardship Review
    # -------------------------------------------------------------------------
    steward_client, steward_headers = _login('demo.steward')
    reviews_resp = steward_client.get(
        '/api/v1/stewardship/reviews?limit=100',
        headers=steward_headers,
    )
    assert reviews_resp.status_code == 200
    reviews = reviews_resp.json()
    target_review = next((r for r in reviews if r['prescription_id'] == rx_id), None)
    assert target_review is not None

    review_completion = {
        'outcome': 'CONTINUE',
        'reason': 'Patient clinical symptoms resolved on Day 3 check. Completing full 5-day regimen.',
    }
    complete_resp = steward_client.post(
        f"/api/v1/stewardship/reviews/{target_review['id']}/complete",
        headers=steward_headers,
        json=review_completion,
    )
    assert complete_resp.status_code == 200, f'Review completion failed: {complete_resp.text}'
    c_data = complete_resp.json()
    assert c_data['status'] == 'COMPLETED'
    assert c_data['outcome'] == 'CONTINUE'

    # -------------------------------------------------------------------------
    # 10. Audit Trail & Analytics Reconciliation
    # -------------------------------------------------------------------------
    summary_resp = steward_client.get('/api/v1/analytics/summary', headers=steward_headers)
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary['prescriptions'] >= 1
    assert summary['units_dispensed'] >= 15
    assert summary['dispensing_transactions'] >= 1

    # Verify audit events logged for prescription, credential, and dispensing
    audit_events = db_session.scalars(
        select(AuditEvent).where(AuditEvent.entity_id == str(rx_id)).order_by(AuditEvent.id.asc())
    ).all()
    event_types = {e.event_type for e in audit_events}
    assert 'CREDENTIAL_CREATED' in event_types
    assert 'DISPENSED' in event_types
