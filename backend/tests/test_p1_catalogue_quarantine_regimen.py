from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.db.seed import DEMO_EBUZIMA_API_KEY, DEMO_RMS_API_KEY, DEMO_USER_PASSWORD, seed_demo
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.core import (
    Antibiotic,
    AntibioticRule,
    AuditEvent,
    DispensingBatchLink,
    DispensingItem,
    DispensingTransaction,
    Facility,
    Formulation,
    IntegrationInbox,
    IntegrationOutbox,
    MedicineConcept,
    MedicineMapping,
    Pharmacy,
    Prescriber,
    Prescription,
    PrescriptionCredential,
    PrescriptionItem,
    StockBatch,
    StockEvent,
)
from app.services.validation import calculate_required_quantity, validate_item

Base.metadata.create_all(engine)
with SessionLocal() as _db:
    seed_demo(_db)

EBUZIMA_HEADERS = {'x-amrguard-integration-key': DEMO_EBUZIMA_API_KEY}
RMS_HEADERS = {'x-amrguard-integration-key': DEMO_RMS_API_KEY}


def _login_as(username: str) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    resp = client.post('/api/v1/auth/login', json={'username': username, 'password': DEMO_USER_PASSWORD})
    assert resp.status_code == 200, resp.text
    csrf = resp.json()['csrf_token']
    return client, {'X-CSRF-Token': csrf}


# =========================================================================
# P1-03 Formulation-Aware Regimen & Calculation Unit Tests
# =========================================================================

def test_formulation_calculation_solid_tablets():
    # 500mg dose, 500mg tablet, 3x/day for 7 days = 21 tablets
    concept = MedicineConcept(coding_system='ATC', code='J01CA04', display_name='Amoxicillin')
    form = Formulation(
        concept=concept,
        strength_value=Decimal('500'),
        strength_unit='mg',
        dose_form='tablet',
        route='Oral',
        units_per_pack=10,
        unit_of_measure='tablet',
        is_divisible=False,
    )
    regimen = calculate_required_quantity(
        formulation=form,
        dose_mg=500.0,
        frequency_per_day=3,
        duration_days=7,
        custom_pack_size=10,
    )
    assert regimen.exact_units == Decimal('21')
    assert regimen.recommended_dispense_units == 21
    assert regimen.recommended_dispense_packs == 3
    assert regimen.unit_label == 'tablet'
    assert regimen.manual_review_required is False


def test_formulation_calculation_liquid_suspension():
    # 250mg dose, 50mg/mL concentration -> 5mL/dose
    # 3x/day for 7 days = 105 mL. Bottle size 100mL -> 2 bottles
    concept = MedicineConcept(coding_system='ATC', code='J01CA04', display_name='Amoxicillin')
    form = Formulation(
        concept=concept,
        strength_value=Decimal('250'),
        strength_unit='mg',
        dose_form='suspension',
        route='Oral',
        units_per_pack=100,
        unit_of_measure='mL',
        liquid_concentration_mg_per_ml=Decimal('50.0'),
    )
    regimen = calculate_required_quantity(
        formulation=form,
        dose_mg=250.0,
        frequency_per_day=3,
        duration_days=7,
        custom_pack_size=100,
    )
    assert regimen.exact_units == Decimal('105.00')
    assert regimen.recommended_dispense_units == 105
    assert regimen.recommended_dispense_packs == 2
    assert regimen.unit_label == 'mL'
    assert regimen.manual_review_required is False


def test_formulation_calculation_injectable_vials():
    # 1000mg dose, 500mg vial -> 2 vials/admin
    # 2x/day for 5 days = 20 vials
    concept = MedicineConcept(coding_system='ATC', code='J01DD02', display_name='Ceftriaxone')
    form = Formulation(
        concept=concept,
        strength_value=Decimal('500'),
        strength_unit='mg',
        dose_form='vial',
        route='Intravenous',
        units_per_pack=1,
        unit_of_measure='vial',
    )
    regimen = calculate_required_quantity(
        formulation=form,
        dose_mg=1000.0,
        frequency_per_day=2,
        duration_days=5,
    )
    assert regimen.exact_units == Decimal('20')
    assert regimen.recommended_dispense_units == 20
    assert regimen.recommended_dispense_packs == 20
    assert regimen.unit_label == 'vial'


def test_formulation_validation_mismatch_blocks():
    concept = MedicineConcept(coding_system='ATC', code='J01CA04', display_name='Amoxicillin')
    form = Formulation(
        concept=concept,
        strength_value=Decimal('500'),
        strength_unit='mg',
        dose_form='tablet',
        route='Oral',
        units_per_pack=10,
        unit_of_measure='tablet',
    )
    # Correct quantity is 21 or 30 (3 packs). Prescribing 15 should block.
    item = PrescriptionItem(
        dose=Decimal('500'),
        frequency_per_day=Decimal('3'),
        duration_days=7,
        quantity=15,
    )
    rule = AntibioticRule(min_dose=Decimal('250'), max_dose=Decimal('1000'), enabled=True)
    issues = validate_item(item, rule, formulation=form)
    assert any(i['code'] == 'QUANTITY_MISMATCH' and i['severity'] == 'BLOCK' for i in issues)


# =========================================================================
# P1-02 Unknown-Code Quarantine & Resolution Integration Tests
# =========================================================================

def test_unknown_facility_quarantined_when_enforced():
    original_setting = settings.quarantine_unmapped_codes
    settings.quarantine_unmapped_codes = True
    client = TestClient(app)
    ext_id = f'EBZ-QUAR-FAC-{uuid4().hex[:8]}'

    try:
        payload = {
            'external_id': ext_id,
            'patient_reference': 'PAT-QUAR-001',
            'prescriber': {
                'external_user_id': 'EBZ-USER-001',
                'name': 'Demo Prescriber',
                'facility_code': 'FAC-NONEXISTENT-999',
                'facility_name': 'Unknown Clinic',
                'district': 'Kicukiro',
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
                    'indication': 'Quarantine test',
                }
            ],
        }
        res = client.post('/api/v1/integrations/ebuzima/prescriptions', json=payload, headers=EBUZIMA_HEADERS)
        assert res.status_code == 422
        body = res.json()['detail']
        assert body['status'] == 'QUARANTINED'
        assert 'quarantine_id' in body

        with SessionLocal() as db:
            inbox = db.get(IntegrationInbox, body['quarantine_id'])
            assert inbox is not None
            assert inbox.status == 'QUARANTINED'
            assert inbox.event_type == 'PRESCRIPTION'
            assert 'FAC-NONEXISTENT-999' in inbox.quarantine_reason
            # Clean up
            db.delete(inbox)
            db.commit()
    finally:
        settings.quarantine_unmapped_codes = original_setting


def test_unknown_antibiotic_quarantined_when_enforced():
    original_setting = settings.quarantine_unmapped_codes
    settings.quarantine_unmapped_codes = True
    client = TestClient(app)
    ext_id = f'EBZ-QUAR-ABX-{uuid4().hex[:8]}'

    try:
        payload = {
            'external_id': ext_id,
            'patient_reference': 'PAT-QUAR-002',
            'prescriber': {
                'external_user_id': 'EBZ-USER-001',
                'name': 'Demo Prescriber',
                'facility_code': 'FAC-KGL-001',
                'facility_name': 'Kigali Central Hospital',
                'district': 'Nyarugenge',
            },
            'items': [
                {
                    'antibiotic_code': 'ABX-UNKNOWN-XYZ-999',
                    'generic_name': 'Mysterycillin',
                    'strength': '250 mg',
                    'formulation': 'Tablet',
                    'route': 'Oral',
                    'dose': 250,
                    'frequency_per_day': 2,
                    'duration_days': 5,
                    'quantity': 10,
                    'indication': 'Unmapped test',
                }
            ],
        }
        res = client.post('/api/v1/integrations/ebuzima/prescriptions', json=payload, headers=EBUZIMA_HEADERS)
        assert res.status_code == 422
        body = res.json()['detail']
        assert body['status'] == 'QUARANTINED'

        with SessionLocal() as db:
            inbox = db.get(IntegrationInbox, body['quarantine_id'])
            assert inbox is not None
            assert inbox.unresolved_code == 'ABX-UNKNOWN-XYZ-999'
            assert inbox.status == 'QUARANTINED'
            db.delete(inbox)
            db.commit()
    finally:
        settings.quarantine_unmapped_codes = original_setting


def test_quarantine_listing_rejection_and_resolution():
    original_setting = settings.quarantine_unmapped_codes
    settings.quarantine_unmapped_codes = True
    client = TestClient(app)
    admin_client, admin_csrf = _login_as('demo.admin')

    ext_id = f'EBZ-QUAR-RES-{uuid4().hex[:8]}'
    abx_code = f'ABX-MAP-{uuid4().hex[:6].upper()}'
    inbox_id = None

    try:
        # 1. Trigger quarantine
        payload = {
            'external_id': ext_id,
            'patient_reference': 'PAT-QUAR-003',
            'prescriber': {
                'external_user_id': 'EBZ-USER-001',
                'name': 'Demo Prescriber',
                'facility_code': 'FAC-KGL-001',
                'facility_name': 'Kigali Central Hospital',
                'district': 'Nyarugenge',
            },
            'items': [
                {
                    'antibiotic_code': abx_code,
                    'generic_name': 'Mapped Amoxicillin',
                    'strength': '500 mg',
                    'formulation': 'Capsule',
                    'route': 'Oral',
                    'dose': 500,
                    'frequency_per_day': 3,
                    'duration_days': 5,
                    'quantity': 15,
                    'indication': 'Mapping test',
                }
            ],
        }
        res = client.post('/api/v1/integrations/ebuzima/prescriptions', json=payload, headers=EBUZIMA_HEADERS)
        assert res.status_code == 422
        inbox_id = res.json()['detail']['quarantine_id']

        # 2. List quarantine inbox
        list_res = admin_client.get('/api/v1/integrations/inbox/quarantine', headers=admin_csrf)
        assert list_res.status_code == 200
        items = list_res.json()
        assert any(item['id'] == inbox_id for item in items)

        # 3. Create approved catalogue concept and mapping
        with SessionLocal() as db:
            concept = db.scalar(select(MedicineConcept).where(MedicineConcept.code == 'AMX500CAP'))
            if not concept:
                concept = MedicineConcept(
                    coding_system='ATC',
                    code='AMX500CAP',
                    display_name='Amoxicillin 500mg Capsule',
                    aware_category='ACCESS',
                )
                db.add(concept)
                db.commit()
            concept_id = concept.id

        map_res = admin_client.post(
            '/api/v1/catalogue/mappings',
            json={
                'source_system': 'e-Buzima',
                'source_code': abx_code,
                'source_description': 'Legacy e-Buzima Amox Code',
                'medicine_concept_id': concept_id,
                'approval_status': 'APPROVED',
            },
            headers=admin_csrf,
        )
        assert map_res.status_code == 200, map_res.text
        assert map_res.json()['approval_status'] == 'APPROVED'

        # 4. Replay quarantined entry
        replay_res = admin_client.post(
            f'/api/v1/integrations/inbox/quarantine/{inbox_id}/resolve',
            json={'action': 'REPLAY', 'notes': 'Mapped to canonical AMX500CAP concept'},
            headers=admin_csrf,
        )
        assert replay_res.status_code == 200, replay_res.text
        replay_data = replay_res.json()
        assert replay_data['status'] == 'PROCESSED'
        assert 'prescription_id' in replay_data
        rx_id = replay_data['prescription_id']

        # Verify prescription exists and is validated
        with SessionLocal() as db:
            rx = db.get(Prescription, rx_id)
            assert rx is not None
            assert rx.status in {'VALIDATED', 'WARNING'}
            # Clean up created prescription
            db.query(PrescriptionItem).filter(PrescriptionItem.prescription_id == rx_id).delete()
            db.delete(rx)
            db.query(MedicineMapping).filter(MedicineMapping.source_code == abx_code).delete()
            db.query(IntegrationInbox).filter(IntegrationInbox.id == inbox_id).delete()
            db.commit()

    finally:
        settings.quarantine_unmapped_codes = original_setting


# =========================================================================
# P1-04 Multi-Batch Item-Level Dispensing & Outbox Tests
# =========================================================================

def test_multi_batch_dispensing_allocation_and_outbox():
    # Setup test batches and prescription
    with SessionLocal() as db:
        fac = db.scalar(select(Facility).where(Facility.code == 'FAC-KGL-001'))
        pharm = db.scalar(select(Pharmacy).where(Pharmacy.code == 'PHA-KGL-001'))
        pr = db.scalar(select(Prescriber).where(Prescriber.facility_id == fac.id))
        ab = db.scalar(select(Antibiotic).where(Antibiotic.code == 'AMX500CAP'))

        # Create 2 distinct stock batches for the same antibiotic
        b1_num = f'BATCH-MB1-{uuid4().hex[:6].upper()}'
        b2_num = f'BATCH-MB2-{uuid4().hex[:6].upper()}'

        b1 = StockBatch(
            pharmacy_id=pharm.id,
            antibiotic_id=ab.id,
            batch_number=b1_num,
            expiry_date=date.today() + timedelta(days=180),
            quantity_available=10,
            source_reference=f'RMS-MB1-{uuid4().hex[:6]}',
        )
        b2 = StockBatch(
            pharmacy_id=pharm.id,
            antibiotic_id=ab.id,
            batch_number=b2_num,
            expiry_date=date.today() + timedelta(days=365),
            quantity_available=20,
            source_reference=f'RMS-MB2-{uuid4().hex[:6]}',
        )
        db.add(b1)
        db.add(b2)
        db.flush()

        rx_ext = f'EBZ-MB-RX-{uuid4().hex[:8]}'
        rx = Prescription(
            external_id=rx_ext,
            patient_reference='PAT-MULTI-BATCH',
            prescriber_id=pr.id,
            facility_id=fac.id,
            status='ACTIVE',
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        db.add(rx)
        db.flush()

        item = PrescriptionItem(
            prescription_id=rx.id,
            antibiotic_id=ab.id,
            dose=Decimal('500'),
            frequency_per_day=Decimal('3'),
            duration_days=8,
            quantity=24,  # Prescribed 24 capsules
            indication='Multi-batch split dispensing test',
        )
        db.add(item)
        db.flush()

        # Create credential
        cred = PrescriptionCredential(
            prescription_id=rx.id,
            otp_hash='dummy_otp_hash_mb',
            qr_token_hash='dummy_qr_hash_mb',
            token_salt='dummy_salt',
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        db.add(cred)
        db.commit()

        b1_id, b2_id = b1.id, b2.id
        rx_id, item_id = rx.id, item.id
        pharm_id = pharm.id

    pharm_client, pharm_csrf = _login_as('demo.pharmacist')
    disp_data = {}
    disp_data_2 = {}

    try:
        # Issue valid credential via API
        cred_res = pharm_client.post(f'/api/v1/prescriptions/{rx_id}/credential', headers=pharm_csrf)
        assert cred_res.status_code == 200, cred_res.text
        otp = cred_res.json()['otp']

        # Fulfill 15 capsules by splitting across batch 1 (10 capsules) and batch 2 (5 capsules)
        idemp_key = f'IDEMP-MB-DISP-{uuid4().hex[:8]}'
        disp_res = pharm_client.post(
            f'/api/v1/prescriptions/{rx_id}/dispense',
            json={
                'pharmacy_id': pharm_id,
                'item_id': item_id,
                'credential': otp,
                'idempotency_key': idemp_key,
                'allocations': [
                    {'batch_id': b1_id, 'quantity': 10},
                    {'batch_id': b2_id, 'quantity': 5},
                ],
            },
            headers=pharm_csrf,
        )
        assert disp_res.status_code == 200, disp_res.text
        disp_data = disp_res.json()
        assert disp_data['authorized'] is True
        assert disp_data['quantity_dispensed'] == 15
        assert disp_data['remaining'] == 9  # 24 - 15 = 9 remaining
        assert disp_data['prescription_status'] == 'PARTIALLY_DISPENSED'
        assert 'outbox_id' in disp_data
        outbox_id = disp_data['outbox_id']

        # Verify database entities: batch deductions, dispensing items, links, outbox
        with SessionLocal() as db:
            b1_db = db.get(StockBatch, b1_id)
            b2_db = db.get(StockBatch, b2_id)
            assert b1_db.quantity_available == 0   # 10 - 10 = 0
            assert b2_db.quantity_available == 15  # 20 - 5 = 15

            tx = db.scalar(select(DispensingTransaction).where(DispensingTransaction.transaction_id == disp_data['transaction_id']))
            assert tx is not None
            assert tx.quantity == 15
            assert tx.reconciliation_status == 'PENDING_RECONCILIATION'

            disp_item = db.scalar(select(DispensingItem).where(DispensingItem.transaction_id == tx.id))
            assert disp_item is not None
            assert disp_item.quantity_dispensed == 15
            assert disp_item.fulfillment_status == 'PARTIAL'

            links = db.scalars(select(DispensingBatchLink).where(DispensingBatchLink.dispensing_item_id == disp_item.id)).all()
            assert len(links) == 2
            link_quantities = {link.batch_id: link.quantity for link in links}
            assert link_quantities[b1_id] == 10
            assert link_quantities[b2_id] == 5

            outbox = db.get(IntegrationOutbox, outbox_id)
            assert outbox is not None
            assert outbox.destination_system == 'RMS_DISPENSE_RECONCILE'
            assert outbox.status == 'PENDING'
            payload_data = json.loads(outbox.payload)
            assert payload_data['quantity_dispensed'] == 15
            assert len(payload_data['allocations']) == 2

        # Step 2: Complete the prescription by dispensing remaining 9 units from batch 2
        idemp_key_2 = f'IDEMP-MB-DISP-2-{uuid4().hex[:8]}'
        disp_res_2 = pharm_client.post(
            f'/api/v1/prescriptions/{rx_id}/dispense',
            json={
                'pharmacy_id': pharm_id,
                'item_id': item_id,
                'credential': otp,
                'idempotency_key': idemp_key_2,
                'allocations': [
                    {'batch_id': b2_id, 'quantity': 9},
                ],
            },
            headers=pharm_csrf,
        )
        assert disp_res_2.status_code == 200, disp_res_2.text
        disp_data_2 = disp_res_2.json()
        assert disp_data_2['quantity_dispensed'] == 9
        assert disp_data_2['remaining'] == 0
        assert disp_data_2['prescription_status'] == 'COMPLETED'

        # Verify prescription is COMPLETED and credential revoked
        with SessionLocal() as db:
            rx_db = db.get(Prescription, rx_id)
            assert rx_db.status == 'COMPLETED'
            cred_db = db.scalar(select(PrescriptionCredential).where(PrescriptionCredential.prescription_id == rx_id))
            assert cred_db.revoked is True

    finally:
        # Cleanup test entities
        with SessionLocal() as db:
            tx_records = db.scalars(select(DispensingTransaction).where(DispensingTransaction.prescription_id == rx_id)).all()
            for tx_rec in tx_records:
                d_items = db.scalars(select(DispensingItem).where(DispensingItem.transaction_id == tx_rec.id)).all()
                for di in d_items:
                    db.query(DispensingBatchLink).filter(DispensingBatchLink.dispensing_item_id == di.id).delete()
                db.query(DispensingItem).filter(DispensingItem.transaction_id == tx_rec.id).delete()
                db.query(StockEvent).filter(StockEvent.reference_id.like(f'{tx_rec.transaction_id}%')).delete()

            db.query(IntegrationOutbox).filter(IntegrationOutbox.aggregate_id == disp_data.get('transaction_id', '')).delete()
            db.query(IntegrationOutbox).filter(IntegrationOutbox.aggregate_id == disp_data_2.get('transaction_id', '')).delete()
            db.query(DispensingTransaction).filter(DispensingTransaction.prescription_id == rx_id).delete()
            db.query(PrescriptionCredential).filter(PrescriptionCredential.prescription_id == rx_id).delete()
            db.query(PrescriptionItem).filter(PrescriptionItem.prescription_id == rx_id).delete()
            db.query(Prescription).filter(Prescription.id == rx_id).delete()
            db.query(StockBatch).filter(StockBatch.id.in_([b1_id, b2_id])).delete()
            db.commit()
