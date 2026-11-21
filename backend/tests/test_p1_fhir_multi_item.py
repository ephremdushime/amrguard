from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.seed import DEMO_USER_PASSWORD, seed_demo
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.core import (
    Antibiotic,
    DispensingTransaction,
    Facility,
    Pharmacy,
    Prescriber,
    Prescription,
    PrescriptionItem,
    StockBatch,
    User,
)
from app.services.fhir import (
    dispensing_to_medication_dispense,
    prescription_item_to_medication_request,
    prescription_to_fhir_bundle,
    prescription_to_medication_request,
)
from app.services.security import hash_password


def _setup_test_db():
    test_engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    return test_engine, TestingSessionLocal


def test_fhir_multi_item_bundle_and_empty_resilience():
    test_engine, TestingSession = _setup_test_db()
    db: Session = TestingSession()

    facility = Facility(code='FAC-KGL-01', name='Kigali Central Hospital', district='Nyarugenge')
    db.add(facility)
    db.flush()

    prescriber = Prescriber(external_user_id='RW-MD-9901', name='Dr. Jean Paul', facility_id=facility.id)
    db.add(prescriber)
    db.flush()

    abx1 = Antibiotic(code='AMX500', generic_name='Amoxicillin', strength='500mg', formulation='capsule', route='oral')
    abx2 = Antibiotic(code='CLA500', generic_name='Clarithromycin', strength='500mg', formulation='tablet', route='oral')
    db.add_all([abx1, abx2])
    db.commit()

    # 1. Multi-item prescription
    rx_multi = Prescription(
        external_id='RX-MULTI-001',
        patient_reference='PAT-SYN-8812',
        prescriber_id=prescriber.id,
        facility_id=facility.id,
        status='ACTIVE',
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(rx_multi)
    db.commit()

    item1 = PrescriptionItem(
        prescription_id=rx_multi.id,
        antibiotic_id=abx1.id,
        dose=Decimal('500'),
        frequency_per_day=Decimal('3'),
        duration_days=7,
        quantity=21,
        indication='H. Pylori Eradication - Amoxicillin Component',
    )
    item2 = PrescriptionItem(
        prescription_id=rx_multi.id,
        antibiotic_id=abx2.id,
        dose=Decimal('500'),
        frequency_per_day=Decimal('2'),
        duration_days=7,
        quantity=14,
        indication='H. Pylori Eradication - Clarithromycin Component',
    )
    db.add_all([item1, item2])
    db.commit()
    db.refresh(rx_multi)

    # Export via bundle function
    bundle = prescription_to_fhir_bundle(rx_multi, db)
    assert bundle['resourceType'] == 'Bundle'
    assert bundle['type'] == 'collection'
    assert bundle['total'] == 2
    assert len(bundle['entry']) == 2

    # Validate Item 1 in bundle
    entry1 = bundle['entry'][0]['resource']
    assert entry1['resourceType'] == 'MedicationRequest'
    assert entry1['groupIdentifier']['value'] == str(rx_multi.id)
    assert entry1['subject']['reference'] == f'Patient/{rx_multi.patient_reference}'
    assert entry1['requester']['reference'] == f'Practitioner/{prescriber.id}'
    assert entry1['dispenseRequest']['quantity']['value'] == 21
    assert entry1['medicationCodeableConcept']['coding'][0]['code'] == 'AMX500'
    assert entry1['reasonCode'][0]['text'] == item1.indication

    # Validate Item 2 in bundle
    entry2 = bundle['entry'][1]['resource']
    assert entry2['resourceType'] == 'MedicationRequest'
    assert entry2['dispenseRequest']['quantity']['value'] == 14
    assert entry2['medicationCodeableConcept']['coding'][0]['code'] == 'CLA500'

    # Calling prescription_to_medication_request on multi-item returns bundle
    default_export = prescription_to_medication_request(rx_multi, db)
    assert default_export['resourceType'] == 'Bundle'
    assert default_export['total'] == 2

    # 2. Empty prescription resilience (no items)
    rx_empty = Prescription(
        external_id='RX-EMPTY-001',
        patient_reference='PAT-SYN-EMPTY',
        prescriber_id=prescriber.id,
        facility_id=facility.id,
        status='DRAFT',
    )
    db.add(rx_empty)
    db.commit()
    db.refresh(rx_empty)

    # Must NOT crash with IndexError
    empty_export = prescription_to_medication_request(rx_empty, db)
    assert empty_export['resourceType'] == 'Bundle'
    assert empty_export['total'] == 0
    assert empty_export['entry'] == []

    # 3. Single-item prescription export modes
    rx_single = Prescription(
        external_id='RX-SINGLE-001',
        patient_reference='PAT-SYN-SINGLE',
        prescriber_id=prescriber.id,
        facility_id=facility.id,
        status='ACTIVE',
    )
    db.add(rx_single)
    db.commit()
    item_single = PrescriptionItem(
        prescription_id=rx_single.id,
        antibiotic_id=abx1.id,
        dose=Decimal('500'),
        frequency_per_day=Decimal('3'),
        duration_days=5,
        quantity=15,
        indication='Uncomplicated lower UTI',
    )
    db.add(item_single)
    db.commit()
    db.refresh(rx_single)

    single_req = prescription_to_medication_request(rx_single, db, prefer_bundle=False)
    assert single_req['resourceType'] == 'MedicationRequest'
    assert single_req['id'] == f'amrguard-rx-{rx_single.id}-item-{item_single.id}'
    assert single_req['dispenseRequest']['quantity']['value'] == 15

    single_bundle = prescription_to_medication_request(rx_single, db, prefer_bundle=True)
    assert single_bundle['resourceType'] == 'Bundle'
    assert single_bundle['total'] == 1
    assert single_bundle['entry'][0]['resource']['id'] == f'amrguard-rx-{rx_single.id}-item-{item_single.id}'


def test_fhir_medication_dispense_batch_linkage():
    test_engine, TestingSession = _setup_test_db()
    db: Session = TestingSession()

    facility = Facility(code='FAC-DISP-01', name='Remera Health Center', district='Gasabo')
    pharmacy = Pharmacy(code='PH-KGL-04', name='Gasabo Retail Pharmacy', district='Gasabo', pharmacy_type='RETAIL')
    db.add_all([facility, pharmacy])
    db.flush()

    prescriber = Prescriber(external_user_id='RW-MD-7711', name='Dr. Marie', facility_id=facility.id)
    abx = Antibiotic(code='CIP500', generic_name='Ciprofloxacin', strength='500mg', formulation='tablet', route='oral')
    user = User(
        identity_issuer='https://auth.amrguard.local',
        identity_subject='pharma_marie',
        username='pharma_marie',
        display_name='Marie Claire RPh',
        email='marie@gasabo-pharma.rw',
        password_hash=hash_password('PharmSecure2026!'),
    )
    db.add_all([prescriber, abx, user])
    db.commit()

    batch = StockBatch(
        pharmacy_id=pharmacy.id,
        antibiotic_id=abx.id,
        batch_number='CIP-LOT-2026A',
        expiry_date=date(2027, 6, 30),
        quantity_available=100,
    )
    db.add(batch)
    db.commit()

    rx = Prescription(
        external_id='RX-DISP-001',
        patient_reference='PAT-SYN-DISP',
        prescriber_id=prescriber.id,
        facility_id=facility.id,
        status='PARTIALLY_DISPENSED',
    )
    db.add(rx)
    db.commit()

    item = PrescriptionItem(
        prescription_id=rx.id,
        antibiotic_id=abx.id,
        dose=Decimal('500'),
        frequency_per_day=Decimal('2'),
        duration_days=5,
        quantity=10,
        indication='Pyelonephritis',
    )
    db.add(item)
    db.commit()

    tx = DispensingTransaction(
        transaction_id='TX-DISP-9901',
        prescription_id=rx.id,
        item_id=item.id,
        pharmacy_id=pharmacy.id,
        batch_id=batch.id,
        actor_user_id=user.id,
        prescribing_facility_id=facility.id,
        dispensing_facility_id=facility.id,
        is_cross_facility=False,
        quantity=10,
        status='COMPLETED',
        created_at=datetime.now(timezone.utc),
    )
    db.add(tx)
    db.commit()

    dispense_res = dispensing_to_medication_dispense(tx, db)
    assert dispense_res['resourceType'] == 'MedicationDispense'
    assert dispense_res['id'] == 'TX-DISP-9901'
    assert dispense_res['status'] == 'completed'
    assert dispense_res['quantity']['value'] == 10

    # Verification of item-level prescription link
    assert dispense_res['authorizingPrescription'][0]['reference'] == f'MedicationRequest/amrguard-rx-{rx.id}-item-{item.id}'

    # Verification of performer
    performer_refs = [p['actor']['reference'] for p in dispense_res['performer']]
    assert f'Organization/Pharmacy-{pharmacy.id}' in performer_refs
    assert f'Practitioner/{user.id}' in performer_refs

    # Verification of batch details in contained Medication resource
    assert 'contained' in dispense_res
    contained_med = dispense_res['contained'][0]
    assert contained_med['resourceType'] == 'Medication'
    assert contained_med['batch']['lotNumber'] == 'CIP-LOT-2026A'
    assert contained_med['batch']['expirationDate'] == '2027-06-30'
    assert contained_med['code']['coding'][0]['code'] == 'CIP500'


def test_fhir_http_endpoints_with_authorization():
    # Use standard shared SessionLocal populated with demo data
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_demo(db)
        fac = db.scalar(select(Facility).where(Facility.code == 'FAC-KGL-001'))
        pharm = db.scalar(select(Pharmacy).where(Pharmacy.code == 'PHA-KGL-001'))
        prescriber = db.scalar(select(Prescriber).where(Prescriber.external_user_id == 'EBZ-USER-001'))
        abx = db.scalar(select(Antibiotic).where(Antibiotic.code == 'AMX500CAP'))
        user_doc = db.scalar(select(User).where(User.username == 'demo.prescriber'))

        rx = db.scalar(select(Prescription).where(Prescription.external_id == 'RX-E2E-TEST-001'))
        if not rx:
            batch = StockBatch(
                pharmacy_id=pharm.id,
                antibiotic_id=abx.id,
                batch_number='AMX-BATCH-001',
                expiry_date=date(2027, 12, 31),
                quantity_available=250,
            )
            db.add(batch)
            db.flush()

            rx = Prescription(
                external_id='RX-E2E-TEST-001',
                patient_reference='PAT-SYN-E2E',
                prescriber_id=prescriber.id,
                facility_id=fac.id,
                status='ACTIVE',
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
            db.add(rx)
            db.flush()

            item = PrescriptionItem(
                prescription_id=rx.id,
                antibiotic_id=abx.id,
                dose=Decimal('500'),
                frequency_per_day=Decimal('3'),
                duration_days=5,
                quantity=15,
                indication='Bacterial pharyngitis',
            )
            db.add(item)
            db.flush()

            tx = DispensingTransaction(
                transaction_id='TX-E2E-TEST-001',
                prescription_id=rx.id,
                item_id=item.id,
                pharmacy_id=pharm.id,
                batch_id=batch.id,
                actor_user_id=user_doc.id,
                prescribing_facility_id=fac.id,
                dispensing_facility_id=fac.id,
                is_cross_facility=False,
                quantity=15,
                status='COMPLETED',
                created_at=datetime.now(timezone.utc),
            )
            db.add(tx)
            db.commit()

        rx_id = rx.id
        item_id = rx.items[0].id
        tx = db.scalar(select(DispensingTransaction).where(DispensingTransaction.transaction_id == 'TX-E2E-TEST-001'))
        tx_id = tx.transaction_id

    client = TestClient(app)
    resp = client.post('/api/v1/auth/login', json={'username': 'demo.prescriber', 'password': DEMO_USER_PASSWORD})
    assert resp.status_code == 200, resp.text
    csrf_token = resp.json()['csrf_token']
    headers = {'X-CSRF-Token': csrf_token}

    try:
        # 1. Fetch prescription FHIR as default bundle
        res = client.get(f'/api/v1/integrations/ebuzima/prescriptions/{rx_id}/fhir', headers=headers)
        assert res.status_code == 200, res.text
        bundle_data = res.json()
        assert bundle_data['resourceType'] == 'Bundle'
        assert bundle_data['type'] == 'collection'
        assert bundle_data['total'] >= 1
        assert bundle_data['entry'][0]['resource']['resourceType'] == 'MedicationRequest'

        # 2. Fetch single item if bundle=false
        res_single = client.get(f'/api/v1/integrations/ebuzima/prescriptions/{rx_id}/fhir?bundle=false', headers=headers)
        assert res_single.status_code == 200, res_single.text
        single_data = res_single.json()
        assert single_data['resourceType'] == 'MedicationRequest'
        assert single_data['id'] == f'amrguard-rx-{rx_id}-item-{item_id}'

        # 3. Dispensing FHIR endpoint (login as demo.pharmacist)
        pharm_client = TestClient(app)
        p_login = pharm_client.post('/api/v1/auth/login', json={'username': 'demo.pharmacist', 'password': DEMO_USER_PASSWORD})
        assert p_login.status_code == 200, p_login.text
        p_csrf = p_login.json()['csrf_token']
        p_headers = {'X-CSRF-Token': p_csrf}

        res_disp = pharm_client.get(f'/api/v1/integrations/dispensing/{tx_id}/fhir', headers=p_headers)
        assert res_disp.status_code == 200, res_disp.text
        disp_data = res_disp.json()
        assert disp_data['resourceType'] == 'MedicationDispense'
        assert disp_data['id'] == tx_id
        assert disp_data['contained'][0]['batch']['lotNumber'] == 'AMX-BATCH-001'
    finally:
        with SessionLocal() as db:
            db.query(DispensingTransaction).filter(DispensingTransaction.transaction_id == tx_id).delete()
            db.query(PrescriptionItem).filter(PrescriptionItem.prescription_id == rx_id).delete()
            db.query(Prescription).filter(Prescription.id == rx_id).delete()
            db.query(StockBatch).filter(StockBatch.batch_number == 'AMX-BATCH-001').delete()
            db.commit()
