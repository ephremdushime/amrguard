from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.db.seed import (
    DEMO_EBUZIMA_API_KEY,
    DEMO_SMS_GATEWAY_API_KEY,
    DEMO_USER_PASSWORD,
    seed_demo,
)
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.core import (
    AuditEvent,
    ConsentRecord,
    Facility,
    MessageDeliveryEvent,
    MessageOutbox,
    Prescriber,
    Prescription,
    PrescriptionItem,
    ReminderOccurrence,
    ReminderSchedule,
)
from app.services.consent import (
    hash_phone_number,
    mask_phone_number,
    normalize_phone_number,
    verify_active_consent,
)

Base.metadata.create_all(engine)
with SessionLocal() as _db:
    seed_demo(_db)

SMS_HEADERS = {'x-amrguard-integration-key': DEMO_SMS_GATEWAY_API_KEY}
EBUZIMA_HEADERS = {'x-amrguard-integration-key': DEMO_EBUZIMA_API_KEY}


def _login_as(username: str) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    resp = client.post('/api/v1/auth/login', json={'username': username, 'password': DEMO_USER_PASSWORD})
    assert resp.status_code == 200, resp.text
    csrf = resp.json()['csrf_token']
    return client, {'x-csrf-token': csrf}


def _create_test_prescription(db, patient_ref: str, is_prn: bool = False) -> Prescription:
    fac = db.scalar(select(Facility).where(Facility.code == 'FAC-KGL-001'))
    prescriber = db.scalar(select(Prescriber).where(Prescriber.facility_id == fac.id))
    from app.models.core import Antibiotic
    abx = db.scalar(select(Antibiotic).where(Antibiotic.code == 'AMX500CAP'))

    rx = Prescription(
        external_id=f'TEST-RX-{datetime.now(timezone.utc).timestamp()}',
        patient_reference=patient_ref,
        prescriber_id=prescriber.id,
        facility_id=fac.id,
        status='VALIDATED',
        created_at=datetime.now(timezone.utc),
    )
    db.add(rx)
    db.flush()

    item = PrescriptionItem(
        prescription_id=rx.id,
        antibiotic_id=abx.id,
        dose=Decimal('500'),
        dose_unit='mg',
        frequency_per_day=Decimal('2'),
        duration_days=5,
        quantity=10,
        indication='Respiratory tract infection',
        is_prn=is_prn,
        prn_reason='Fever above 38.5C' if is_prn else None,
        instructions='Take 1 capsule every 12 hours with water',
    )
    db.add(item)
    db.commit()
    db.refresh(rx)
    return rx


# ----------------------------------------------------------------------------
# Test 1: Phone Normalization, HMAC Hashing & Privacy Masking
# ----------------------------------------------------------------------------
def test_phone_normalization_hashing_and_masking():
    # Various Rwandan phone number formats
    raw_variants = ['0788123456', '250788123456', '+250788123456', ' +250 788 123 456 ']
    normalized_expected = '+250788123456'

    for raw in raw_variants:
        norm = normalize_phone_number(raw)
        assert norm == normalized_expected

    # Keyed hash should be deterministic 64-char hex
    h1 = hash_phone_number(normalized_expected)
    h2 = hash_phone_number(normalized_expected)
    assert h1 == h2
    assert len(h1) == 64
    assert normalized_expected not in h1

    # Privacy mask
    mask = mask_phone_number(normalized_expected)
    assert mask == '+250 78 *** **56'
    assert '81234' not in mask


# ----------------------------------------------------------------------------
# Test 2: Consent Capture via API (No Plaintext Phone Storage)
# ----------------------------------------------------------------------------
def test_consent_capture_api():
    client, headers = _login_as('demo.prescriber')
    patient_ref = f'PAT-CONSENT-{datetime.now(timezone.utc).timestamp()}'

    resp = client.post(
        '/api/v1/consent',
        headers=headers,
        json={
            'patient_reference': patient_ref,
            'phone_number': '0788765432',
            'purpose': 'DOSE_REMINDER',
            'channel': 'SMS',
            'language': 'rw',
            'evidence_reference': 'SIGNED-FORM-2026-001',
            'policy_version': 'v1.0',
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data['patient_reference'] == patient_ref
    assert data['status'] == 'ACTIVE'
    assert data['language'] == 'rw'
    assert data['recipient_phone_masked'] == '+250 78 *** **32'
    assert '0788765432' not in json.dumps(data)

    # Verify database record: NO plaintext phone anywhere
    with SessionLocal() as db:
        record = db.scalar(select(ConsentRecord).where(ConsentRecord.id == data['id']))
        assert record is not None
        assert record.recipient_phone_masked == '+250 78 *** **32'
        assert record.recipient_phone_hash == hash_phone_number('+250788765432')

        # Check audit event
        audit = db.scalar(
            select(AuditEvent)
            .where(AuditEvent.entity_type == 'ConsentRecord', AuditEvent.entity_id == str(record.id))
            .order_by(AuditEvent.created_at.desc())
        )
        assert audit is not None
        assert '0788765432' not in audit.details
        assert '+250788765432' not in audit.details


# ----------------------------------------------------------------------------
# Test 3: Unverified Consent Blocks Reminder Scheduling
# ----------------------------------------------------------------------------
def test_unverified_consent_blocks_reminder_scheduling():
    client, headers = _login_as('demo.prescriber')
    with SessionLocal() as db:
        rx = _create_test_prescription(db, patient_ref='PAT-NO-CONSENT-999')

    resp = client.post(
        f'/api/v1/prescriptions/{rx.id}/reminders/schedule',
        headers=headers,
        json={'daily_times': ['08:00', '20:00']},
    )
    assert resp.status_code == 422
    assert 'No active consent found' in resp.json()['detail']

    with SessionLocal() as db:
        schedules = db.scalars(select(ReminderSchedule).where(ReminderSchedule.prescription_id == rx.id)).all()
        assert len(schedules) == 0


# ----------------------------------------------------------------------------
# Test 4: PRN Prescription Cannot Have Automated Schedule
# ----------------------------------------------------------------------------
def test_prn_prescription_blocks_reminder_scheduling():
    client, headers = _login_as('demo.prescriber')
    patient_ref = f'PAT-PRN-{datetime.now(timezone.utc).timestamp()}'

    # First capture valid consent
    resp_consent = client.post(
        '/api/v1/consent',
        headers=headers,
        json={'patient_reference': patient_ref, 'phone_number': '0788111222', 'purpose': 'DOSE_REMINDER'},
    )
    assert resp_consent.status_code == 200

    # Create PRN prescription
    with SessionLocal() as db:
        rx = _create_test_prescription(db, patient_ref=patient_ref, is_prn=True)

    # Attempt to schedule reminders -> MUST be rejected (422)
    resp = client.post(
        f'/api/v1/prescriptions/{rx.id}/reminders/schedule',
        headers=headers,
        json={'daily_times': ['08:00', '20:00']},
    )
    assert resp.status_code == 422
    assert 'PRN' in resp.json()['detail']


# ----------------------------------------------------------------------------
# Test 5: Dose-Level Occurrence Generation & Multi-Language Outbox Templating
# ----------------------------------------------------------------------------
def test_schedule_generation_and_outbox_templating():
    client, headers = _login_as('demo.prescriber')
    patient_ref = f'PAT-SCHED-{datetime.now(timezone.utc).timestamp()}'

    # Capture consent in Kinyarwanda
    resp_consent = client.post(
        '/api/v1/consent',
        headers=headers,
        json={'patient_reference': patient_ref, 'phone_number': '0788333444', 'language': 'rw'},
    )
    assert resp_consent.status_code == 200

    # Create prescription (5 days, BID = 10 doses)
    with SessionLocal() as db:
        rx = _create_test_prescription(db, patient_ref=patient_ref, is_prn=False)

    # Schedule reminders
    resp = client.post(
        f'/api/v1/prescriptions/{rx.id}/reminders/schedule',
        headers=headers,
        json={'daily_times': ['08:00', '20:00']},
    )
    assert resp.status_code == 200, resp.text
    sched_data = resp.json()
    assert sched_data['total_doses'] == 10
    assert len(sched_data['occurrences']) == 10
    assert sched_data['language'] == 'rw'

    with SessionLocal() as db:
        # Check outbox entries
        outbox_msgs = db.scalars(
            select(MessageOutbox)
            .join(ReminderOccurrence, ReminderOccurrence.id == MessageOutbox.occurrence_id)
            .where(ReminderOccurrence.schedule_id == sched_data['id'])
            .order_by(MessageOutbox.next_attempt_at.asc())
        ).all()
        assert len(outbox_msgs) == 10

        # Verify Kinyarwanda templating on first and last dose
        assert 'Urugero rwa 1/10' in outbox_msgs[0].message_text
        assert 'Urugero rwa 10/10' in outbox_msgs[9].message_text
        assert 'Igihe cy\'umuti wawe kirageze' in outbox_msgs[0].message_text


# ----------------------------------------------------------------------------
# Test 6: Leased Outbox Dispatch & Pre-Send Active Consent Verification
# ----------------------------------------------------------------------------
def test_outbox_leasing_dispatch_and_pre_send_consent_check():
    client_presc, headers_presc = _login_as('demo.prescriber')
    patient_ref = f'PAT-DISPATCH-{datetime.now(timezone.utc).timestamp()}'

    # Capture consent
    resp_consent = client_presc.post(
        '/api/v1/consent',
        headers=headers_presc,
        json={'patient_reference': patient_ref, 'phone_number': '0788555666', 'language': 'en'},
    )
    consent_id = resp_consent.json()['id']

    # Create and schedule prescription
    with SessionLocal() as db:
        rx = _create_test_prescription(db, patient_ref=patient_ref)

    resp_sched = client_presc.post(
        f'/api/v1/prescriptions/{rx.id}/reminders/schedule',
        headers=headers_presc,
        json={'daily_times': ['08:00', '20:00']},
    )
    assert resp_sched.status_code == 200
    sched_id = resp_sched.json()['id']

    # Backdate next_attempt_at on 2 messages so they are immediately dispatchable
    with SessionLocal() as db:
        msgs = db.scalars(
            select(MessageOutbox)
            .join(ReminderOccurrence, ReminderOccurrence.id == MessageOutbox.occurrence_id)
            .where(ReminderOccurrence.schedule_id == sched_id)
            .limit(2)
        ).all()
        for m in msgs:
            m.next_attempt_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()

    # Trigger worker dispatch tick using SMS gateway service key
    client_sms = TestClient(app)
    resp_tick = client_sms.post('/api/v1/reminders/dispatch-tick', headers=SMS_HEADERS, json={'batch_size': 50})
    assert resp_tick.status_code == 200
    details = resp_tick.json()['details']
    assert details['sent'] >= 2

    with SessionLocal() as db:
        sent_msgs = db.scalars(
            select(MessageOutbox)
            .join(ReminderOccurrence, ReminderOccurrence.id == MessageOutbox.occurrence_id)
            .where(ReminderOccurrence.schedule_id == sched_id, MessageOutbox.status == 'SENT')
        ).all()
        assert len(sent_msgs) == 2
        for sm in sent_msgs:
            assert sm.provider_message_id is not None
            assert sm.provider_message_id.startswith('MOCK-SMS-')
            assert sm.occurrence.status == 'SENT'

    # Now test Pre-Send Active Consent Re-Check:
    # Withdraw consent, backdate 2 more messages, and run dispatch tick
    resp_withdraw = client_presc.post(
        f'/api/v1/consent/{consent_id}/withdraw',
        headers=headers_presc,
        json={'reason': 'PATIENT_REQUEST'},
    )
    assert resp_withdraw.status_code == 200

    # 1. Verify consent withdrawal cascaded cancellation to pending outbox messages
    with SessionLocal() as db:
        cancelled_msgs = db.scalars(
            select(MessageOutbox)
            .join(ReminderOccurrence, ReminderOccurrence.id == MessageOutbox.occurrence_id)
            .where(ReminderOccurrence.schedule_id == sched_id, MessageOutbox.status == 'CANCELLED')
        ).all()
        assert len(cancelled_msgs) >= 8

        # 2. Simulate race condition: reset 1 message to PENDING and backdate it
        race_msg = cancelled_msgs[0]
        race_msg.status = 'PENDING'
        race_msg.next_attempt_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()

    # Worker dispatch tick runs -> pre-send active consent check must detect withdrawn consent
    resp_tick_revoked = client_sms.post('/api/v1/reminders/dispatch-tick', headers=SMS_HEADERS, json={'batch_size': 50})
    assert resp_tick_revoked.status_code == 200
    revoked_details = resp_tick_revoked.json()['details']
    assert revoked_details['sent'] == 0
    assert revoked_details['cancelled'] >= 1


# ----------------------------------------------------------------------------
# Test 7: Inbound STOP / YEKA Opt-Out Webhook
# ----------------------------------------------------------------------------
def test_inbound_sms_opt_out_keywords():
    client_presc, headers_presc = _login_as('demo.prescriber')
    patient_ref = f'PAT-INBOUND-{datetime.now(timezone.utc).timestamp()}'

    # Capture active consent
    resp_consent = client_presc.post(
        '/api/v1/consent',
        headers=headers_presc,
        json={'patient_reference': patient_ref, 'phone_number': '0788999888', 'language': 'rw'},
    )
    consent_id = resp_consent.json()['id']

    # Send inbound "YEKA" (Kinyarwanda stop keyword)
    client_sms = TestClient(app)
    resp_inbound = client_sms.post(
        '/api/v1/integrations/sms/inbound',
        headers=SMS_HEADERS,
        json={'sender_phone': '0788999888', 'message_body': 'YEKA'},
    )
    assert resp_inbound.status_code == 200
    inbound_data = resp_inbound.json()
    assert inbound_data['opt_out_actioned'] is True
    assert inbound_data['consents_withdrawn'] >= 1

    with SessionLocal() as db:
        consent = db.get(ConsentRecord, consent_id)
        assert consent.status == 'WITHDRAWN'
        assert 'YEKA' in consent.withdrawal_reason


# ----------------------------------------------------------------------------
# Test 8: SMS Delivery Receipt Webhook & Critical Clinical Invariant
# ----------------------------------------------------------------------------
def test_delivery_receipt_callback_and_clinical_invariant():
    client_presc, headers_presc = _login_as('demo.prescriber')
    patient_ref = f'PAT-DLV-{datetime.now(timezone.utc).timestamp()}'

    resp_consent = client_presc.post(
        '/api/v1/consent',
        headers=headers_presc,
        json={'patient_reference': patient_ref, 'phone_number': '0788111999', 'language': 'rw'},
    )
    consent_id = resp_consent.json()['id']

    # Create message directly
    with SessionLocal() as db:
        consent = db.get(ConsentRecord, consent_id)
        msg = MessageOutbox(
            consent_record_id=consent.id,
            destination_hash=consent.recipient_phone_hash,
            destination_masked=consent.recipient_phone_masked,
            message_text='Test delivery receipt',
            channel='SMS',
            status='SENT',
            provider_message_id='MSG-PROVIDER-TEST-001',
            created_at=datetime.now(timezone.utc),
            sent_at=datetime.now(timezone.utc),
        )
        db.add(msg)
        db.commit()

    client_sms = TestClient(app)
    resp_dlv = client_sms.post(
        '/api/v1/integrations/sms/delivery-callback',
        headers=SMS_HEADERS,
        json={
            'provider': 'MOCK',
            'provider_message_id': 'MSG-PROVIDER-TEST-001',
            'event_type': 'DELIVERED',
            'details': {'network_code': 'MTN_RW', 'delivered_at': '2026-11-22T08:00:00Z'},
        },
    )
    assert resp_dlv.status_code == 200
    data = resp_dlv.json()
    assert data['status'] == 'ACKNOWLEDGED'
    assert 'does not record patient medication adherence' in data['clinical_notice']

    # Verify CRITICAL CLINICAL SAFETY INVARIANT:
    # A delivered SMS receipt confirms network transmission only; it NEVER records ingestion
    with SessionLocal() as db:
        event = db.scalar(
            select(MessageDeliveryEvent).where(
                MessageDeliveryEvent.provider_message_id == 'MSG-PROVIDER-TEST-001'
            )
        )
        assert event is not None
        assert event.event_type == 'DELIVERED'

        audit = db.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.entity_type == 'MessageDeliveryEvent',
                AuditEvent.entity_id == str(event.id),
            )
            .order_by(AuditEvent.created_at.desc())
        )
        assert audit is not None
        details = json.loads(audit.details)
        assert details['is_adherence_record'] is False


# ----------------------------------------------------------------------------
# Test 9: Facility Tenancy Isolation on Consent & Reminders
# ----------------------------------------------------------------------------
def test_cross_facility_consent_denial():
    # User in Facility A cannot manage reminders for Facility B
    with SessionLocal() as db:
        # Create an unassigned facility
        fac_other = db.scalar(select(Facility).where(Facility.code == 'FAC-OTHER-999'))
        if not fac_other:
            fac_other = Facility(code='FAC-OTHER-999', name='Other Hospital', district='Huye', active=True)
            db.add(fac_other)
            db.flush()

        prescriber = db.scalar(select(Prescriber).where(Prescriber.facility_id == fac_other.id))
        if not prescriber:
            prescriber = Prescriber(
                external_user_id='PRESC-OTHER-001',
                name='Dr. Other',
                facility_id=fac_other.id,
                active=True,
            )
            db.add(prescriber)
            db.flush()

        from app.models.core import Antibiotic
        abx = db.scalar(select(Antibiotic).where(Antibiotic.code == 'AMX500CAP'))

        rx_other = Prescription(
            external_id=f'TEST-RX-OTHER-{datetime.now(timezone.utc).timestamp()}',
            patient_reference='PAT-OTHER-123',
            prescriber_id=prescriber.id,
            facility_id=fac_other.id,
            status='VALIDATED',
            created_at=datetime.now(timezone.utc),
        )
        db.add(rx_other)
        db.flush()

        item = PrescriptionItem(
            prescription_id=rx_other.id,
            antibiotic_id=abx.id,
            dose=Decimal('500'),
            dose_unit='mg',
            frequency_per_day=Decimal('2'),
            duration_days=5,
            quantity=10,
            indication='Respiratory tract infection',
            is_prn=False,
        )
        db.add(item)
        db.commit()
        db.refresh(rx_other)

    client, headers = _login_as('demo.prescriber')  # Prescriber is scoped only to FAC-KGL-001
    resp = client.post(
        f'/api/v1/prescriptions/{rx_other.id}/reminders/schedule',
        headers=headers,
        json={'daily_times': ['08:00', '20:00']},
    )
    assert resp.status_code == 403
    assert 'Not authorized for this facility' in resp.json()['detail']

