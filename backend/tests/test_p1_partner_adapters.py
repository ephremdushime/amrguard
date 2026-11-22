"""P1-05 Partner Adapters & Outbox Worker Verification Suite.

Tests canonical e-Buzima EMR and RMS / eLMIS supply-chain adapters:
- FHIR R4 Bundle intake & conversion
- Proprietary e-Buzima prescription parsing
- National item code mapping and unknown code quarantine
- RMS stock event transformation
- Outbox worker leased batch dispatch (RMS consumption + e-Buzima dispense callbacks)
- Exponential backoff retry scheduling
- Dead-letter escalation after max retries
- Administrative dead-letter inspection and manual retry
- Role and service-scope authorization enforcement
"""

from datetime import date, datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.ebuzima import EBuzimaAdapter, MockEBuzimaTransportClient
from app.adapters.outbox_worker import process_integration_outbox_batch
from app.adapters.rms import MockRMSTransportClient, RMSAdapter
from app.core.config import settings
from app.db.seed import (
    DEMO_EBUZIMA_API_KEY,
    DEMO_OUTBOX_WORKER_API_KEY,
    DEMO_USER_PASSWORD,
    seed_demo,
)
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.core import (
    Antibiotic,
    Facility,
    IntegrationInbox,
    IntegrationOutbox,
    MedicineConcept,
    MedicineMapping,
    Pharmacy,
    StockBatch,
)

Base.metadata.create_all(engine)
with SessionLocal() as _db:
    seed_demo(_db)

UTC = timezone.utc


@pytest.fixture
def db_session():
    with SessionLocal() as session:
        yield session


def _login_as(username: str) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    resp = client.post('/api/v1/auth/login', json={'username': username, 'password': DEMO_USER_PASSWORD})
    assert resp.status_code == 200, resp.text
    csrf = resp.json().get('csrf_token', '')
    return client, {'x-csrf-token': csrf}


def test_ebuzima_adapter_proprietary_json_parsing(db_session: Session):
    """Verifies that EBuzimaAdapter translates canonical e-Buzima JSON into PrescriptionIn."""
    adapter = EBuzimaAdapter()
    payload = {
        'external_id': 'EBZ-UNIT-001',
        'patient_reference': 'PAT-TEST-001',
        'prescriber': {
            'external_user_id': 'DOC-KGL-01',
            'name': 'Dr. Test Prescriber',
            'facility_code': 'FAC-KGL-001',
            'facility_name': 'Kigali Central Hospital',
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
                'indication': 'Community Acquired Pneumonia',
            }
        ],
    }

    rx_in, ingest_res = adapter.parse_prescription(payload, db_session)
    assert rx_in.external_id == 'EBZ-UNIT-001'
    assert rx_in.patient_reference == 'PAT-TEST-001'
    assert len(rx_in.items) == 1
    assert rx_in.items[0].antibiotic_code == 'AMX500CAP'
    assert rx_in.items[0].quantity == 15
    assert ingest_res.source_system == 'e-Buzima'
    assert ingest_res.payload_hash is not None


def test_ebuzima_adapter_fhir_bundle_parsing(db_session: Session):
    """Verifies that EBuzimaAdapter translates a FHIR R4 Bundle with MedicationRequest into PrescriptionIn."""
    adapter = EBuzimaAdapter()
    fhir_bundle = {
        'resourceType': 'Bundle',
        'id': 'EBZ-FHIR-BUNDLE-999',
        'type': 'collection',
        'entry': [
            {
                'resource': {
                    'resourceType': 'MedicationRequest',
                    'id': 'MR-001',
                    'status': 'active',
                    'intent': 'order',
                    'subject': {'reference': 'Patient/SYNTH-PAT-999', 'display': 'Synthetic Patient'},
                    'requester': {'reference': 'Practitioner/PRAC-001', 'display': 'Dr. Rwanda Clinician'},
                    'recorder': {'reference': 'Organization/FAC-KGL-001'},
                    'medicationCodeableConcept': {
                        'coding': [{'system': 'http://moh.gov.rw/drugs', 'code': 'AMX500CAP', 'display': 'Amoxicillin 500mg'}],
                        'text': 'Amoxicillin 500 mg Capsule',
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
                    'reasonCode': [{'text': 'Respiratory tract infection'}],
                }
            }
        ],
    }

    rx_in, ingest_res = adapter.parse_prescription(fhir_bundle, db_session)
    assert rx_in.external_id == 'EBZ-FHIR-BUNDLE-999'
    assert rx_in.patient_reference == 'Patient/SYNTH-PAT-999'
    assert rx_in.prescriber.facility_code == 'FAC-KGL-001'
    assert len(rx_in.items) == 1
    assert rx_in.items[0].antibiotic_code == 'AMX500CAP'
    assert rx_in.items[0].quantity == 15


def test_ebuzima_fhir_bundle_endpoint_ingestion(db_session: Session):
    """Tests the POST /api/v1/integrations/ebuzima/fhir-bundle endpoint with service-client auth."""
    client = TestClient(app)
    fhir_bundle = {
        'resourceType': 'Bundle',
        'id': f'EBZ-FHIR-EP-{datetime.now(UTC).timestamp()}',
        'type': 'collection',
        'entry': [
            {
                'resource': {
                    'resourceType': 'MedicationRequest',
                    'id': 'MR-EP-001',
                    'status': 'active',
                    'intent': 'order',
                    'subject': {'reference': 'Patient/SYNTH-EP-01'},
                    'recorder': {'reference': 'Organization/FAC-KGL-001'},
                    'medicationCodeableConcept': {
                        'coding': [{'code': 'AMX500CAP', 'display': 'Amoxicillin'}],
                    },
                    'dosageInstruction': [
                        {
                            'timing': {'repeat': {'frequency': 3}},
                            'doseAndRate': [{'doseQuantity': {'value': 500, 'unit': 'mg'}}],
                        }
                    ],
                    'dispenseRequest': {
                        'expectedSupplyDuration': {'value': 5},
                        'quantity': {'value': 15},
                    },
                }
            }
        ],
    }

    res = client.post(
        '/api/v1/integrations/ebuzima/fhir-bundle',
        json=fhir_bundle,
        headers={'x-amrguard-integration-key': DEMO_EBUZIMA_API_KEY},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['external_id'] == fhir_bundle['id']
    assert body['status'] in ('VALIDATED', 'WARNING')


def test_ebuzima_fhir_bundle_quarantines_unmapped_code(monkeypatch, db_session: Session):
    """Tests that unmapped medicine codes in a FHIR bundle route to IntegrationInbox quarantine."""
    monkeypatch.setattr(settings, 'quarantine_unmapped_codes', True)
    client = TestClient(app)
    fhir_bundle = {
        'resourceType': 'Bundle',
        'id': f'EBZ-FHIR-QUAR-{datetime.now(UTC).timestamp()}',
        'entry': [
            {
                'resource': {
                    'resourceType': 'MedicationRequest',
                    'subject': {'reference': 'Patient/SYNTH-QUAR-01'},
                    'recorder': {'reference': 'Organization/FAC-KGL-001'},
                    'medicationCodeableConcept': {
                        'coding': [{'code': 'UNMAPPED-MYCIN-999', 'display': 'Unknown Mycin'}],
                    },
                    'dosageInstruction': [{'timing': {'repeat': {'frequency': 2}}}],
                    'dispenseRequest': {'expectedSupplyDuration': {'value': 5}, 'quantity': {'value': 10}},
                }
            }
        ],
    }

    res = client.post(
        '/api/v1/integrations/ebuzima/fhir-bundle',
        json=fhir_bundle,
        headers={'x-amrguard-integration-key': DEMO_EBUZIMA_API_KEY},
    )
    assert res.status_code == 422
    body = res.json()
    assert 'quarantine_id' in body['detail']
    assert body['detail']['status'] == 'QUARANTINED'

    inbox = db_session.get(IntegrationInbox, body['detail']['quarantine_id'])
    assert inbox is not None
    assert inbox.unresolved_code == 'UNMAPPED-MYCIN-999'
    assert inbox.status == 'QUARANTINED'


def test_ebuzima_adapter_maps_via_approved_medicine_mapping(db_session: Session):
    """Tests that partner codes mapped via approved MedicineMapping resolve successfully."""
    concept = db_session.scalar(select(MedicineConcept).where(MedicineConcept.code == 'AMX500CAP'))
    assert concept is not None

    mapping = db_session.scalar(
        select(MedicineMapping).where(
            MedicineMapping.source_system == 'e-Buzima',
            MedicineMapping.source_code == 'EXT-AMOX-CUSTOM-CODE',
        )
    )
    if not mapping:
        mapping = MedicineMapping(
            source_system='e-Buzima',
            source_code='EXT-AMOX-CUSTOM-CODE',
            source_description='Custom EMR Amoxicillin Code',
            medicine_concept_id=concept.id,
            approval_status='APPROVED',
            active=True,
        )
        db_session.add(mapping)
        db_session.commit()

    adapter = EBuzimaAdapter()
    payload = {
        'external_id': f'EBZ-MAP-{datetime.now(UTC).timestamp()}',
        'patient_reference': 'PAT-MAPPED-01',
        'prescriber': {
            'external_user_id': 'DOC-01',
            'facility_code': 'FAC-KGL-001',
            'facility_name': 'Kigali Central Hospital',
        },
        'items': [
            {
                'antibiotic_code': 'EXT-AMOX-CUSTOM-CODE',
                'dose': 500,
                'frequency_per_day': 3,
                'duration_days': 5,
                'quantity': 15,
            }
        ],
    }

    rx_in, _ = adapter.parse_prescription(payload, db_session)
    assert rx_in.items[0].antibiotic_code == 'AMX500CAP'


def test_rms_adapter_stock_event_transformation(db_session: Session):
    """Tests RMSAdapter inbound stock movement parsing and validation."""
    adapter = RMSAdapter()
    payload = {
        'source_system': 'RMS',
        'source_reference': f'RMS-TX-{datetime.now(UTC).timestamp()}',
        'pharmacy_code': 'PHA-KGL-001',
        'antibiotic_code': 'AMX500CAP',
        'batch_number': 'RMS-BATCH-UNIT-01',
        'expiry_date': '2027-12-31',
        'event_type': 'RECEIPT',
        'quantity_delta': 500,
    }

    req, ingest_res = adapter.parse_stock_event(payload, db_session)
    assert req.pharmacy_code == 'PHA-KGL-001'
    assert req.antibiotic_code == 'AMX500CAP'
    assert req.batch_number == 'RMS-BATCH-UNIT-01'
    assert req.expiry_date == date(2027, 12, 31)
    assert req.quantity_delta == 500
    assert ingest_res.source_system == 'RMS'


def test_outbox_worker_successful_dispatch_and_audit(db_session: Session):
    """Tests end-to-end dispensing outbox enqueueing, worker batch leasing, and dispatch to mock partner transport."""
    presc_client, presc_headers = _login_as('demo.prescriber')
    pharm_client, pharm_headers = _login_as('demo.pharmacist')

    # 1. Create a synthetic prescription as prescriber
    rx_res = presc_client.post(
        '/api/v1/demo/prescriptions',
        json={
            'external_id': f'EBZ-OUTBOX-RX-{datetime.now(UTC).timestamp()}',
            'patient_reference': 'PAT-OUTBOX-TEST',
            'antibiotic_code': 'AMX500CAP',
            'generic_name': 'Amoxicillin',
            'strength': '500 mg',
            'formulation': 'Capsule',
            'route': 'Oral',
            'dose': 500,
            'frequency_per_day': 3,
            'duration_days': 5,
            'quantity': 15,
            'indication': 'Test Bronchitis',
            'expires_at': (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        },
        headers=presc_headers,
    )
    assert rx_res.status_code == 200, rx_res.text
    rx_data = rx_res.json()['prescription']
    rx_id = rx_data['id']
    item_id = rx_data['items'][0]['id']

    # 2. Generate credential and verify
    cred_res = pharm_client.post(f'/api/v1/prescriptions/{rx_id}/credential', headers=pharm_headers)
    assert cred_res.status_code == 200
    otp = cred_res.json()['otp']

    ver_res = pharm_client.post('/api/v1/verification', json={'credential': otp}, headers=pharm_headers)
    assert ver_res.status_code == 200

    # 3. Find stock batch
    batch = db_session.scalar(select(StockBatch).where(StockBatch.pharmacy_id == 1, StockBatch.quantity_available >= 15))
    assert batch is not None

    # 4. Dispense
    disp_res = pharm_client.post(
        f'/api/v1/prescriptions/{rx_id}/dispense',
        json={
            'pharmacy_id': 1,
            'item_id': item_id,
            'batch_id': batch.id,
            'quantity': 15,
            'credential': otp,
            'idempotency_key': f'key-{datetime.now(UTC).timestamp()}',
        },
        headers=pharm_headers,
    )
    assert disp_res.status_code == 200

    # 5. Verify pending outbox rows exist for RMS and e-Buzima
    outbox_entries = list(
        db_session.scalars(
            select(IntegrationOutbox).where(
                IntegrationOutbox.status == 'PENDING',
                IntegrationOutbox.aggregate_id == disp_res.json()['transaction_id'],
            )
        ).all()
    )
    assert len(outbox_entries) == 2
    destinations = {e.destination_system for e in outbox_entries}
    assert 'RMS_DISPENSE_RECONCILE' in destinations
    assert 'EBUZIMA_DISPENSE_UPDATE' in destinations

    # 6. Trigger worker batch dispatch via API with outbox worker API key
    mock_eb = MockEBuzimaTransportClient()
    mock_rms = MockRMSTransportClient()

    stats = process_integration_outbox_batch(
        db_session,
        batch_size=200,
        ebuzima_client=mock_eb,
        rms_client=mock_rms,
    )
    assert stats['dispatched'] >= 2
    assert len(mock_eb.sent_messages) >= 1
    assert len(mock_rms.sent_messages) >= 1

    # Check database status
    for item in outbox_entries:
        db_session.refresh(item)
        assert item.status == 'DISPATCHED'
        assert item.dispatched_at is not None
        assert item.error_message is None


def test_outbox_worker_exponential_backoff_and_dead_letter(db_session: Session):
    """Tests that outbox retry scheduling applies exponential backoff and escalates to DEAD_LETTER after max_retries."""
    now = datetime.now(UTC)
    payload_json = json.dumps({
        'transaction_id': 'TX-FAIL-TEST',
        'pharmacy_code': 'PHA-KGL-001',
        'quantity_dispensed': 10,
    })

    bad_item = IntegrationOutbox(
        destination_system='RMS_DISPENSE_RECONCILE',
        event_type='DISPENSING_RECONCILIATION',
        aggregate_type='DispensingTransaction',
        aggregate_id='TX-FAIL-TEST',
        payload=payload_json,
        status='PENDING',
        retry_count=0,
        next_attempt_at=now - timedelta(days=5),
    )
    db_session.add(bad_item)
    db_session.commit()
    db_session.refresh(bad_item)

    # 1. Attempt 1 with failing client (retryable 503)
    failing_client = MockRMSTransportClient(should_fail=True, status_code=503)
    stats1 = process_integration_outbox_batch(
        db_session,
        batch_size=100,
        max_retries=3,
        backoff_factor=2.0,
        rms_client=failing_client,
    )
    assert stats1['retrying'] >= 1
    db_session.refresh(bad_item)
    assert bad_item.status == 'RETRYING'
    assert bad_item.retry_count == 1
    next_at = bad_item.next_attempt_at
    if next_at.tzinfo is None:
        next_at = next_at.replace(tzinfo=UTC)
    assert next_at > now

    # 2. Simulate subsequent retries until exhaustion (max_retries=3)
    bad_item.retry_count = 2
    bad_item.next_attempt_at = now - timedelta(days=5)
    db_session.commit()

    stats2 = process_integration_outbox_batch(
        db_session,
        batch_size=100,
        max_retries=3,
        rms_client=failing_client,
    )
    assert stats2['dead_letter'] >= 1
    db_session.refresh(bad_item)
    assert bad_item.status == 'DEAD_LETTER'


def test_outbox_dead_letter_api_inspection_and_manual_retry(db_session: Session):
    """Tests GET /api/v1/integrations/outbox/dead-letter and POST .../{id}/retry."""
    dl_item = IntegrationOutbox(
        destination_system='RMS_DISPENSE_RECONCILE',
        event_type='DISPENSING_RECONCILIATION',
        aggregate_type='DispensingTransaction',
        aggregate_id='TX-DL-INSPECT',
        payload=json.dumps({'test': 1}),
        status='DEAD_LETTER',
        retry_count=5,
        next_attempt_at=datetime.now(UTC),
        error_message='Connection refused by RMS gateway',
    )
    db_session.add(dl_item)
    db_session.commit()
    db_session.refresh(dl_item)

    presc_client, presc_headers = _login_as('demo.prescriber')
    op_client, op_headers = _login_as('demo.operator')

    # 1. Non-admin / prescriber denied access
    denied = presc_client.get('/api/v1/integrations/outbox/dead-letter', headers=presc_headers)
    assert denied.status_code == 403

    # 2. Platform operator can inspect
    res = op_client.get('/api/v1/integrations/outbox/dead-letter', headers=op_headers)
    assert res.status_code == 200
    items = res.json()
    assert any(x['id'] == dl_item.id for x in items)

    # 3. Platform operator can manually trigger retry
    retry_res = op_client.post(f'/api/v1/integrations/outbox/{dl_item.id}/retry', headers=op_headers)
    assert retry_res.status_code == 200
    retried = retry_res.json()
    assert retried['status'] == 'PENDING'
    assert retried['retry_count'] == 0

    db_session.refresh(dl_item)
    assert dl_item.status == 'PENDING'
    assert dl_item.retry_count == 0


def test_outbox_dispatch_tick_authorization():
    """Verifies that outbox dispatch-tick strictly requires service client scope or platform operator role."""
    presc_client, presc_headers = _login_as('demo.prescriber')
    op_client, op_headers = _login_as('demo.operator')
    anon_client = TestClient(app)

    # 1. Unauthenticated -> 401/403
    assert anon_client.post('/api/v1/integrations/outbox/dispatch-tick').status_code in (401, 403)

    # 2. Prescriber role -> 403
    assert presc_client.post('/api/v1/integrations/outbox/dispatch-tick', headers=presc_headers).status_code == 403

    # 3. Platform operator -> 200
    res_op = op_client.post('/api/v1/integrations/outbox/dispatch-tick', headers=op_headers)
    assert res_op.status_code == 200
    assert 'processed' in res_op.json()

    # 4. Service client with DEMO_OUTBOX_WORKER_API_KEY -> 200
    res_svc = anon_client.post(
        '/api/v1/integrations/outbox/dispatch-tick',
        headers={'x-amrguard-integration-key': DEMO_OUTBOX_WORKER_API_KEY},
    )
    assert res_svc.status_code == 200
    assert 'processed' in res_svc.json()
