"""Dose-Level Reminder Engine for AMRGuard.

CLINICAL SAFETY AND TRACEABILITY INVARIANTS:
1. PRN ("as-needed") prescriptions CANNOT have automated dose reminders scheduled,
   as their dosing is symptom-contingent rather than predetermined.
2. SMS delivery confirmation indicates network transmission ONLY.
3. An SMS delivery receipt NEVER implies or records medication ingestion or adherence.
4. Medication ingestion and adherence must be verified through clinical review or
   direct patient engagement, never inferred from SMS logs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import (
    ConsentRecord,
    MessageDeliveryEvent,
    MessageOutbox,
    Prescription,
    PrescriptionItem,
    ReminderOccurrence,
    ReminderSchedule,
    now_utc,
)
from app.services.audit import record_audit
from app.services.consent import verify_active_consent

REMINDER_TEMPLATES: dict[str, str] = {
    'rw': (
        "AMRGuard: Igihe cy'umuti wawe kirageze (Urugero rwa {dose}/{total}). "
        "Nyabuneka fata umuti nk'uko muganga yabitegetse. Niba ufite ikibazo hamagara ivuriro."
    ),
    'en': (
        "AMRGuard: It is time for your prescribed medication (Dose {dose}/{total}). "
        "Please take as directed by your clinician. Contact your health facility with any questions."
    ),
    'fr': (
        "AMRGuard: Il est temps de prendre votre médicament prescrit (Dose {dose}/{total}). "
        "Veuillez suivre les instructions de votre clinicien. Contactez votre centre de santé pour toute question."
    ),
}

OPT_OUT_CONFIRMATION_TEMPLATES: dict[str, str] = {
    'rw': 'AMRGuard: Ubusabe bwawe bwo guhagarika ubutumwa bwakiriwe. Nta butumwa bundi uzongera kohererezwa.',
    'en': 'AMRGuard: You have been unsubscribed from medication reminders. You will not receive further messages.',
    'fr': 'AMRGuard: Vous avez été désabonné des rappels de médicaments. Vous ne recevrez plus de messages.',
}

DEFAULT_DAILY_TIMES_BY_FREQUENCY: dict[int, list[str]] = {
    1: ['08:00'],
    2: ['08:00', '20:00'],
    3: ['08:00', '14:00', '20:00'],
    4: ['06:00', '12:00', '18:00', '22:00'],
}


def create_dose_reminder_schedule(
    db: Session,
    prescription_id: int,
    *,
    prescription_item_id: int | None = None,
    daily_times: list[str] | None = None,
    start_date: datetime | None = None,
    language: str | None = None,
    created_by_user_id: int | None = None,
) -> ReminderSchedule:
    """Generate a dose-level schedule and queued outbox messages from an authoritative prescription."""
    rx = db.get(Prescription, prescription_id)
    if not rx:
        raise ValueError(f'Prescription {prescription_id} not found')
    if rx.status == 'BLOCKED':
        raise ValueError('Cannot schedule reminders for a BLOCKED prescription')
    if not rx.items:
        raise ValueError('Prescription has no items to schedule reminders for')

    # Select target prescription item
    item: PrescriptionItem | None = None
    if prescription_item_id:
        item = next((i for i in rx.items if i.id == prescription_item_id), None)
        if not item:
            raise ValueError(f'PrescriptionItem {prescription_item_id} does not belong to prescription {prescription_id}')
    else:
        item = rx.items[0]

    # CLINICAL SAFETY RULE: PRN orders cannot have deterministic reminder schedules
    if item.is_prn:
        raise ValueError('Cannot schedule automated dose reminders for PRN (as-needed) prescription items')

    # Informed consent check
    consent = verify_active_consent(db, patient_reference=rx.patient_reference, purpose='DOSE_REMINDER')
    if not consent:
        raise ValueError(f"No active consent found for patient reference '{rx.patient_reference}' and purpose 'DOSE_REMINDER'")

    resolved_lang = language or consent.language or 'rw'
    if resolved_lang not in REMINDER_TEMPLATES:
        resolved_lang = 'rw'

    # Resolve daily times
    times = daily_times
    if not times:
        freq = int(round(float(item.frequency_per_day)))
        times = DEFAULT_DAILY_TIMES_BY_FREQUENCY.get(freq, ['08:00'])

    for t in times:
        parts = t.split(':')
        if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
            raise ValueError(f"Invalid time format in daily_times: '{t}'. Must be HH:MM")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"Time value out of range: '{t}'")

    start = start_date or now_utc()
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    duration_days = item.duration_days
    end = start + timedelta(days=duration_days)
    total_doses = duration_days * len(times)

    schedule = ReminderSchedule(
        prescription_id=rx.id,
        prescription_item_id=item.id,
        patient_reference=rx.patient_reference,
        consent_record_id=consent.id,
        timezone='Africa/Kigali',
        start_date=start,
        end_date=end,
        daily_times=json.dumps(times),
        language=resolved_lang,
        status='ACTIVE',
        created_at=now_utc(),
    )
    db.add(schedule)
    db.flush()

    # Generate occurrences and outbox messages
    template = REMINDER_TEMPLATES[resolved_lang]
    dose_counter = 1

    for day in range(duration_days):
        base_day = start.date() + timedelta(days=day)
        for t_str in times:
            h, m = map(int, t_str.split(':'))
            scheduled_at = datetime(base_day.year, base_day.month, base_day.day, h, m, 0, tzinfo=timezone.utc)

            occ = ReminderOccurrence(
                schedule_id=schedule.id,
                scheduled_at=scheduled_at,
                dose_number=dose_counter,
                total_doses=total_doses,
                instructions=item.instructions or f'{item.dose} {item.dose_unit or "unit"}',
                status='PENDING',
                created_at=now_utc(),
            )
            db.add(occ)
            db.flush()

            msg_text = template.format(dose=dose_counter, total=total_doses)
            outbox = MessageOutbox(
                occurrence_id=occ.id,
                consent_record_id=consent.id,
                destination_hash=consent.recipient_phone_hash,
                destination_masked=consent.recipient_phone_masked,
                message_text=msg_text,
                channel='SMS',
                status='PENDING',
                next_attempt_at=scheduled_at,
                created_at=now_utc(),
            )
            db.add(outbox)
            dose_counter += 1

    db.flush()

    record_audit(
        db,
        'REMINDER_SCHEDULE_CREATED',
        'ReminderSchedule',
        schedule.id,
        'AMRGuard',
        actor_id=str(created_by_user_id) if created_by_user_id else None,
        facility_id=rx.facility_id,
        details={
            'prescription_id': rx.id,
            'prescription_item_id': item.id,
            'patient_reference': rx.patient_reference,
            'total_doses': total_doses,
            'daily_times': times,
            'language': resolved_lang,
        },
    )
    return schedule


def dispatch_reminders_batch(
    db: Session,
    *,
    batch_size: int = 50,
    now: datetime | None = None,
    lease_minutes: int = 5,
) -> dict[str, Any]:
    """Lease pending reminder outbox messages and dispatch them with pre-send active consent checks."""
    current_time = now or now_utc()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    # Lease eligible pending messages
    messages = db.scalars(
        select(MessageOutbox)
        .where(
            MessageOutbox.status == 'PENDING',
            MessageOutbox.next_attempt_at <= current_time,
        )
        .order_by(MessageOutbox.next_attempt_at.asc())
        .limit(batch_size)
    ).all()

    if not messages:
        return {'leased': 0, 'sent': 0, 'suppressed': 0, 'cancelled': 0}

    lease_token = f'LEASE-{uuid.uuid4().hex}'
    lease_expires = current_time + timedelta(minutes=lease_minutes)

    for msg in messages:
        msg.status = 'LEASED'
        msg.lease_token = lease_token
        msg.lease_expires_at = lease_expires
        msg.attempts += 1
    db.flush()

    sent_count = 0
    suppressed_count = 0
    cancelled_count = 0

    for msg in messages:
        # Pre-send Active Consent Verification: Must be active at moment of dispatch
        consent = db.get(ConsentRecord, msg.consent_record_id)
        if not consent or consent.status != 'ACTIVE':
            msg.status = 'CANCELLED'
            msg.last_error = f'Consent is no longer ACTIVE (status={getattr(consent, "status", None)})'
            cancelled_count += 1
            if msg.occurrence:
                msg.occurrence.status = 'SUPPRESSED'
                msg.occurrence.suppression_reason = 'CONSENT_WITHDRAWN_BEFORE_DISPATCH'
                suppressed_count += 1
            continue

        # Mock dispatch
        provider_id = f'MOCK-SMS-{uuid.uuid4().hex[:12].upper()}'
        msg.status = 'SENT'
        msg.sent_at = now_utc()
        msg.provider_message_id = provider_id
        msg.lease_token = None
        msg.lease_expires_at = None
        sent_count += 1

        if msg.occurrence:
            msg.occurrence.status = 'SENT'
            msg.occurrence.dispatched_at = now_utc()

    db.flush()
    return {
        'leased': len(messages),
        'sent': sent_count,
        'suppressed': suppressed_count,
        'cancelled': cancelled_count,
    }


def record_delivery_receipt(
    db: Session,
    provider: str,
    provider_message_id: str,
    event_type: str,
    raw_payload: dict[str, Any] | None = None,
) -> MessageDeliveryEvent:
    """Record webhook delivery receipt.

    CRITICAL CLINICAL BOUNDARY:
    A delivery confirmation indicates network transmission ONLY.
    Under NO circumstances does this function record medication ingestion or adherence.
    """
    outbox = db.scalar(
        select(MessageOutbox).where(MessageOutbox.provider_message_id == provider_message_id)
    )
    if not outbox:
        raise ValueError(f"MessageOutbox entry with provider_message_id '{provider_message_id}' not found")

    existing_event = db.scalar(
        select(MessageDeliveryEvent).where(
            MessageDeliveryEvent.outbox_id == outbox.id,
            MessageDeliveryEvent.event_type == event_type.upper(),
        )
    )
    if existing_event:
        return existing_event

    event = MessageDeliveryEvent(
        outbox_id=outbox.id,
        provider=provider,
        provider_message_id=provider_message_id,
        event_type=event_type.upper(),
        raw_payload=json.dumps(raw_payload or {}),
        received_at=now_utc(),
    )
    db.add(event)
    db.flush()

    record_audit(
        db,
        'MESSAGE_DELIVERY_EVENT_RECORDED',
        'MessageDeliveryEvent',
        event.id,
        provider,
        details={
            'provider_message_id': provider_message_id,
            'event_type': event_type.upper(),
            'destination_masked': outbox.destination_masked,
            'is_adherence_record': False,  # Explicitly auditable clinical invariant
        },
    )
    return event
