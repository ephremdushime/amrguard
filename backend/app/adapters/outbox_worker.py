"""Background outbox processor for partner integration reconciliation.

Dispatches queued events from integration_outbox to partner systems (RMS / e-Buzima)
with exponential backoff, transaction durability, and dead-letter queue escalation.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import PartnerTransportClient, PartnerTransportError
from app.adapters.ebuzima import EBuzimaAdapter, MockEBuzimaTransportClient
from app.adapters.rms import MockRMSTransportClient, RMSAdapter
from app.models.core import IntegrationOutbox
from app.services.audit import record_audit

logger = logging.getLogger('amrguard.adapters.outbox_worker')

# Default mock clients for synthetic and staging environments
_default_ebuzima_client = MockEBuzimaTransportClient()
_default_rms_client = MockRMSTransportClient()


def process_integration_outbox_batch(
    db: Session,
    *,
    batch_size: int = 20,
    max_retries: int = 5,
    backoff_factor: float = 2.0,
    ebuzima_client: PartnerTransportClient | None = None,
    rms_client: PartnerTransportClient | None = None,
) -> dict[str, int]:
    """Lease and process a batch of pending partner reconciliation outbox records.

    Handles RMS stock consumption depletions and e-Buzima dispense notifications.
    Applies exponential backoff on transient errors and escalates to DEAD_LETTER on exhaustion.
    """
    now = datetime.now(timezone.utc)
    eb_client = ebuzima_client or _default_ebuzima_client
    r_client = rms_client or _default_rms_client

    # Query eligible rows
    stmt = (
        select(IntegrationOutbox)
        .where(
            IntegrationOutbox.status.in_(['PENDING', 'RETRYING']),
            IntegrationOutbox.next_attempt_at <= now,
        )
        .order_by(IntegrationOutbox.next_attempt_at.asc())
        .limit(batch_size)
    )
    entries = list(db.scalars(stmt).all())

    dispatched = 0
    retrying = 0
    dead_letter = 0

    ebuzima_adapter = EBuzimaAdapter()
    rms_adapter = RMSAdapter()

    for item in entries:
        item.last_attempt_at = now
        try:
            payload_dict = json.loads(item.payload)
        except Exception as exc:
            item.status = 'DEAD_LETTER'
            item.error_message = f'Corrupt JSON payload: {exc}'
            dead_letter += 1
            record_audit(
                db,
                'INTEGRATION_OUTBOX_DEAD_LETTER',
                'IntegrationOutbox',
                item.id,
                'AMRGuard',
                outcome='DEAD_LETTER',
                details={'reason': item.error_message, 'destination_system': item.destination_system},
            )
            continue

        try:
            if item.destination_system == 'RMS_DISPENSE_RECONCILE':
                formatted = rms_adapter.format_stock_consumption(payload_dict)
                result = r_client.send('/api/v1/stock/consumption', formatted)
            elif item.destination_system == 'EBUZIMA_DISPENSE_UPDATE':
                formatted = ebuzima_adapter.format_dispense_notification(payload_dict)
                result = eb_client.send('/api/v1/dispense/notifications', formatted)
            else:
                raise PartnerTransportError(f'Unknown destination system: {item.destination_system}', is_retryable=False)

            item.status = 'DISPATCHED'
            item.dispatched_at = datetime.now(timezone.utc)
            item.error_message = None
            dispatched += 1

            record_audit(
                db,
                'INTEGRATION_OUTBOX_DISPATCHED',
                'IntegrationOutbox',
                item.id,
                'AMRGuard',
                outcome='SUCCESS',
                details={
                    'destination_system': item.destination_system,
                    'event_type': item.event_type,
                    'aggregate_id': item.aggregate_id,
                    'external_reference': result.external_reference,
                },
            )
        except Exception as exc:
            is_retryable = getattr(exc, 'is_retryable', True)
            item.retry_count += 1
            item.error_message = str(exc)

            if item.retry_count >= max_retries or not is_retryable:
                item.status = 'DEAD_LETTER'
                dead_letter += 1
                record_audit(
                    db,
                    'INTEGRATION_OUTBOX_DEAD_LETTER',
                    'IntegrationOutbox',
                    item.id,
                    'AMRGuard',
                    outcome='DEAD_LETTER',
                    details={
                        'destination_system': item.destination_system,
                        'aggregate_id': item.aggregate_id,
                        'retries': item.retry_count,
                        'error': str(exc),
                    },
                )
            else:
                item.status = 'RETRYING'
                delay = min(3600, (2 ** item.retry_count) * backoff_factor)
                item.next_attempt_at = now + timedelta(seconds=delay)
                retrying += 1
                record_audit(
                    db,
                    'INTEGRATION_OUTBOX_RETRY_SCHEDULED',
                    'IntegrationOutbox',
                    item.id,
                    'AMRGuard',
                    outcome='WARNING',
                    details={
                        'destination_system': item.destination_system,
                        'aggregate_id': item.aggregate_id,
                        'retry_count': item.retry_count,
                        'next_attempt_seconds': delay,
                        'error': str(exc),
                    },
                )

    db.commit()
    return {
        'processed': len(entries),
        'dispatched': dispatched,
        'retrying': retrying,
        'dead_letter': dead_letter,
    }


def retry_dead_letter(db: Session, outbox_id: int) -> IntegrationOutbox:
    """Manually reset a DEAD_LETTER or FAILED outbox message to PENDING."""
    item = db.get(IntegrationOutbox, outbox_id)
    if not item:
        raise ValueError(f'Outbox entry {outbox_id} not found')
    if item.status not in ('DEAD_LETTER', 'FAILED', 'RETRYING'):
        raise ValueError(f'Outbox entry {outbox_id} is in status {item.status}, not eligible for manual retry')

    now = datetime.now(timezone.utc)
    item.status = 'PENDING'
    item.retry_count = 0
    item.next_attempt_at = now
    item.error_message = None

    record_audit(
        db,
        'INTEGRATION_OUTBOX_RETRY_REQUESTED',
        'IntegrationOutbox',
        item.id,
        'AMRGuard',
        outcome='SUCCESS',
        details={'previous_status': 'DEAD_LETTER', 'destination_system': item.destination_system},
    )
    db.commit()
    db.refresh(item)
    return item
