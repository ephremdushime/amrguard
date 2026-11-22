from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.core import (
    ConsentRecord,
    MessageOutbox,
    ReminderOccurrence,
    ReminderSchedule,
    now_utc,
)
from app.services.audit import record_audit

OPT_OUT_KEYWORDS = frozenset({'STOP', 'YEKA', 'HAGARIKA', 'UNSUBSCRIBE', 'QUIT', 'CANCEL'})


def normalize_phone_number(raw_phone: str) -> str:
    """Normalize phone number to international E.164 format.

    Supports Rwandan local (07X...), international (2507X...), and standard E.164 (+...).
    """
    cleaned = re.sub(r'[\s\-\(\)\.]', '', raw_phone.strip())
    if not cleaned:
        raise ValueError('Phone number cannot be empty')

    # Local Rwandan mobile: 07XXXXXXXX (10 digits) -> +2507XXXXXXXX
    if cleaned.startswith('07') and len(cleaned) == 10:
        cleaned = '+25' + cleaned
    # Rwandan format without plus: 2507XXXXXXXX (12 digits) -> +2507XXXXXXXX
    elif cleaned.startswith('250') and len(cleaned) == 12:
        cleaned = '+' + cleaned
    elif not cleaned.startswith('+'):
        cleaned = '+' + cleaned

    # E.164 validation: + followed by 8 to 15 digits
    if not re.match(r'^\+[1-9]\d{7,14}$', cleaned):
        raise ValueError(f'Invalid phone number format: {raw_phone}')

    return cleaned


def hash_phone_number(normalized_phone: str, secret: str | None = None) -> str:
    """Generate a keyed HMAC-SHA256 hash of the normalized phone number.

    Never store or log plaintext phone numbers in AMRGuard.
    """
    key = secret or settings.effective_hmac_secret
    return hmac.new(key.encode('utf-8'), normalized_phone.encode('utf-8'), hashlib.sha256).hexdigest()


def mask_phone_number(normalized_phone: str) -> str:
    """Generate a privacy-preserving display mask for phone numbers.

    Example: '+250788123456' -> '+250 78 *** **56'
    """
    if normalized_phone.startswith('+250') and len(normalized_phone) == 13:
        # Rwanda specific: +250 7X *** **YY
        return f'{normalized_phone[:4]} {normalized_phone[4:6]} *** **{normalized_phone[-2:]}'
    if len(normalized_phone) >= 10:
        return f'{normalized_phone[:4]} *** **{normalized_phone[-2:]}'
    return f'{normalized_phone[:2]} *** {normalized_phone[-2:]}'


def capture_consent(
    db: Session,
    patient_reference: str,
    phone_number: str,
    *,
    purpose: str = 'DOSE_REMINDER',
    channel: str = 'SMS',
    language: str = 'rw',
    captured_by_user_id: int | None = None,
    facility_id: int | None = None,
    source_reference: str | None = None,
    evidence_reference: str | None = None,
    policy_version: str = 'v1.0',
) -> ConsentRecord:
    """Capture informed patient consent with phone normalization and keyed hashing."""
    normalized = normalize_phone_number(phone_number)
    phone_hash = hash_phone_number(normalized)
    phone_mask = mask_phone_number(normalized)

    consent = ConsentRecord(
        patient_reference=patient_reference.strip(),
        purpose=purpose,
        channel=channel,
        language=language,
        recipient_phone_hash=phone_hash,
        recipient_phone_masked=phone_mask,
        status='ACTIVE',
        captured_by_user_id=captured_by_user_id,
        facility_id=facility_id,
        captured_at=now_utc(),
        source_reference=source_reference.strip() if source_reference else None,
        evidence_reference=evidence_reference.strip() if evidence_reference else None,
        policy_version=policy_version,
    )
    db.add(consent)
    db.flush()

    record_audit(
        db,
        'CONSENT_CAPTURED',
        'ConsentRecord',
        consent.id,
        'AMRGuard',
        actor_id=str(captured_by_user_id) if captured_by_user_id else None,
        facility_id=facility_id,
        details={
            'patient_reference': patient_reference,
            'purpose': purpose,
            'channel': channel,
            'language': language,
            'recipient_phone_masked': phone_mask,
            'policy_version': policy_version,
        },
    )
    return consent


def verify_active_consent(
    db: Session,
    patient_reference: str,
    purpose: str = 'DOSE_REMINDER',
    channel: str = 'SMS',
) -> ConsentRecord | None:
    """Check if an active, unwithdrawn consent record exists for the patient and purpose."""
    return db.scalar(
        select(ConsentRecord)
        .where(
            ConsentRecord.patient_reference == patient_reference.strip(),
            ConsentRecord.channel == channel,
            ConsentRecord.purpose.in_([purpose, 'ALL']),
            ConsentRecord.status == 'ACTIVE',
        )
        .order_by(ConsentRecord.captured_at.desc())
    )


def withdraw_consent(
    db: Session,
    consent_id: int,
    *,
    withdrawn_by_user_id: int | None = None,
    reason: str = 'PATIENT_REQUEST',
) -> ConsentRecord:
    """Withdraw an informed consent record and cascade cancellation to schedules and outbox."""
    consent = db.get(ConsentRecord, consent_id)
    if not consent:
        raise ValueError(f'Consent record {consent_id} not found')

    if consent.status == 'WITHDRAWN':
        return consent

    consent.status = 'WITHDRAWN'
    consent.withdrawn_at = now_utc()
    consent.withdrawn_by_user_id = withdrawn_by_user_id
    consent.withdrawal_reason = reason

    # 1. Cascade cancellation to active reminder schedules
    schedules = db.scalars(
        select(ReminderSchedule).where(
            ReminderSchedule.consent_record_id == consent_id,
            ReminderSchedule.status == 'ACTIVE',
        )
    ).all()

    cancelled_sched_count = len(schedules)
    suppressed_occ_count = 0

    for sched in schedules:
        sched.status = 'CANCELLED'
        sched.cancelled_at = now_utc()
        sched.cancellation_reason = f'CONSENT_WITHDRAWN: {reason}'

        # Suppress pending occurrences under this schedule
        occurrences = db.scalars(
            select(ReminderOccurrence).where(
                ReminderOccurrence.schedule_id == sched.id,
                ReminderOccurrence.status == 'PENDING',
            )
        ).all()
        for occ in occurrences:
            occ.status = 'SUPPRESSED'
            occ.suppression_reason = 'CONSENT_WITHDRAWN'
            suppressed_occ_count += 1

    # 2. Cancel pending/leased messages in message_outbox
    outbox_msgs = db.scalars(
        select(MessageOutbox).where(
            MessageOutbox.consent_record_id == consent_id,
            MessageOutbox.status.in_(['PENDING', 'LEASED']),
        )
    ).all()

    for msg in outbox_msgs:
        msg.status = 'CANCELLED'
        msg.last_error = f'Consent withdrawn ({reason})'

    db.flush()

    record_audit(
        db,
        'CONSENT_WITHDRAWN',
        'ConsentRecord',
        consent.id,
        'AMRGuard',
        actor_id=str(withdrawn_by_user_id) if withdrawn_by_user_id else None,
        facility_id=consent.facility_id,
        details={
            'patient_reference': consent.patient_reference,
            'reason': reason,
            'schedules_cancelled': cancelled_sched_count,
            'occurrences_suppressed': suppressed_occ_count,
            'outbox_messages_cancelled': len(outbox_msgs),
        },
    )
    return consent


def handle_inbound_opt_out(
    db: Session,
    raw_phone: str,
    message_body: str,
) -> list[ConsentRecord]:
    """Handle inbound SMS keywords (STOP, YEKA, etc.) to immediately opt-out patient consent."""
    body_clean = message_body.strip().upper()
    first_token = body_clean.split()[0] if body_clean.split() else ''
    if first_token not in OPT_OUT_KEYWORDS:
        return []

    normalized = normalize_phone_number(raw_phone)
    phone_hash = hash_phone_number(normalized)

    active_consents = db.scalars(
        select(ConsentRecord).where(
            ConsentRecord.recipient_phone_hash == phone_hash,
            ConsentRecord.status == 'ACTIVE',
        )
    ).all()

    withdrawn: list[ConsentRecord] = []
    for c in active_consents:
        withdraw_consent(db, c.id, reason=f'INBOUND_OPT_OUT ({first_token})')
        withdrawn.append(c)

    if withdrawn:
        record_audit(
            db,
            'CONSENT_OPT_OUT_INBOUND',
            'ConsentRecord',
            ','.join(str(c.id) for c in withdrawn),
            'SMS_GATEWAY',
            details={
                'opt_out_keyword': first_token,
                'consents_withdrawn': len(withdrawn),
                'recipient_phone_masked': mask_phone_number(normalized),
            },
        )

    return withdrawn
