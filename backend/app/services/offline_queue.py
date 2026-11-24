"""Policy-Bound Offline Dispensing Queue & Conflict Reconciler.

Provides resilient local dispensing continuity for health facilities experiencing
intermittent network outages. Cryptographically validates offline transaction signatures,
detects concurrent reconciliation conflicts, prevents double-dispense abuse, and
atomically updates stock ledgers and partner outboxes upon connectivity restoration.
"""

from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.core import (
    AuditEvent,
    DispensingBatchLink,
    DispensingItem,
    DispensingTransaction,
    IntegrationOutbox,
    OfflineDispenseRecord,
    Pharmacy,
    Prescription,
    PrescriptionItem,
    StockBatch,
    User,
)
from app.services.audit import record_audit

UTC = timezone.utc


def compute_offline_signature(
    pharmacy_id: int,
    device_fingerprint: str,
    offline_transaction_id: str,
    payload_str: str,
) -> str:
    """Computes HMAC-SHA256 signature for offline transaction verification."""
    secret = (settings.effective_hmac_secret or 'amrguard-offline-secret-default').encode('utf-8')
    canonical = f'{pharmacy_id}:{device_fingerprint}:{offline_transaction_id}:{payload_str}'.encode('utf-8')
    return hmac.new(secret, canonical, hashlib.sha256).hexdigest()


def verify_offline_signature(
    pharmacy_id: int,
    device_fingerprint: str,
    offline_transaction_id: str,
    payload_str: str,
    signature: str,
) -> bool:
    """Constant-time verification of offline bundle signature."""
    expected = compute_offline_signature(pharmacy_id, device_fingerprint, offline_transaction_id, payload_str)
    return hmac.compare_digest(expected, signature)


def enqueue_offline_bundle(
    db: Session,
    *,
    bundle_id: str,
    pharmacy_id: int,
    device_fingerprint: str,
    signature: str,
    offline_transaction_id: str,
    prescription_code: str,
    payload: dict[str, Any],
) -> OfflineDispenseRecord:
    """Records an incoming signed offline dispense transaction bundle into the reconciliation queue."""
    payload_str = json.dumps(payload, sort_keys=True)
    if not verify_offline_signature(pharmacy_id, device_fingerprint, offline_transaction_id, payload_str, signature):
        raise ValueError('Invalid cryptographic signature for offline dispense bundle')

    # Idempotent replay check
    existing = db.scalar(
        select(OfflineDispenseRecord).where(
            OfflineDispenseRecord.offline_transaction_id == offline_transaction_id
        )
    )
    if existing:
        return existing

    rx_id = payload.get('prescription_id')
    record = OfflineDispenseRecord(
        bundle_id=bundle_id,
        pharmacy_id=pharmacy_id,
        device_fingerprint=device_fingerprint,
        signature=signature,
        offline_transaction_id=offline_transaction_id,
        prescription_id=rx_id,
        prescription_code=prescription_code,
        payload=payload_str,
        status='PENDING',
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def reconcile_offline_bundle(
    db: Session,
    bundle_id: str,
    reconciled_by_user_id: int | None = None,
    user_id: int | None = None,
) -> tuple[OfflineDispenseRecord, DispensingTransaction | None]:
    """Reconciles an offline dispense bundle with atomic stock decrement and conflict resolution."""
    reconciled_by_user_id = reconciled_by_user_id or user_id
    record = db.scalar(
        select(OfflineDispenseRecord).where(OfflineDispenseRecord.bundle_id == bundle_id)
    )
    if not record:
        raise ValueError(f'Offline dispense bundle {bundle_id} not found')

    if record.status == 'RECONCILED':
        # Already reconciled
        tx = db.scalar(
            select(DispensingTransaction).where(
                DispensingTransaction.transaction_id == record.offline_transaction_id
            )
        )
        return record, tx

    payload = json.loads(record.payload)
    prescription_id = payload.get('prescription_id')
    pharmacy_id = record.pharmacy_id
    batch_id = payload.get('batch_id')
    quantity = int(payload.get('quantity', 0))

    rx = db.get(Prescription, prescription_id) if prescription_id else None
    if not rx:
        record.status = 'REJECTED'
        record.conflict_reason = f'Prescription #{prescription_id} does not exist in central ledger'
        db.commit()
        return record, None

    # Conflict Check 1: Was prescription already fully dispensed or cancelled elsewhere?
    if rx.status in ('COMPLETED', 'CANCELLED', 'EXPIRED'):
        record.status = 'CONFLICT'
        record.conflict_reason = f'Prescription is already in terminal state {rx.status} (concurrent dispense or cancellation)'
        record.reconciled_at = datetime.now(UTC)
        record.reconciled_by_user_id = reconciled_by_user_id
        record_audit(
            db,
            'OFFLINE_DISPENSE_CONFLICT',
            'Prescription',
            str(rx.id),
            'OfflineReconciler',
            details={'bundle_id': record.bundle_id, 'reason': record.conflict_reason},
            facility_id=rx.facility_id,
            pharmacy_id=pharmacy_id,
            outcome='DENIED',
        )
        db.commit()
        return record, None

    # Conflict Check 2: Stock Availability in designated batch
    batch = db.get(StockBatch, batch_id) if batch_id else None
    if not batch:
        record.status = 'CONFLICT'
        record.conflict_reason = f'Stock batch #{batch_id} not found at pharmacy #{pharmacy_id}'
        record.reconciled_at = datetime.now(UTC)
        record.reconciled_by_user_id = reconciled_by_user_id
        db.commit()
        return record, None

    if batch.quantity_available < quantity:
        record.status = 'CONFLICT'
        record.conflict_reason = (
            f'Insufficient stock in batch {batch.batch_number}: required {quantity}, available {batch.quantity_available}'
        )
        record.reconciled_at = datetime.now(UTC)
        record.reconciled_by_user_id = reconciled_by_user_id
        record_audit(
            db,
            'OFFLINE_DISPENSE_CONFLICT',
            'StockBatch',
            str(batch.id),
            'OfflineReconciler',
            details={'bundle_id': record.bundle_id, 'reason': record.conflict_reason},
            facility_id=rx.facility_id,
            pharmacy_id=pharmacy_id,
            outcome='DENIED',
        )
        db.commit()
        return record, None

    # Clean state: Execute atomic reconciliation
    batch.quantity_available -= quantity

    pharmacy = db.get(Pharmacy, pharmacy_id)
    dispensing_fac_id = pharmacy.facility_id if (pharmacy and pharmacy.facility_id) else rx.facility_id

    # Create canonical DispensingTransaction
    actor_id = reconciled_by_user_id or 1
    tx = DispensingTransaction(
        transaction_id=record.offline_transaction_id,
        prescription_id=rx.id,
        pharmacy_id=pharmacy_id,
        batch_id=batch.id,
        item_id=rx.items[0].id if rx.items else None,
        quantity=quantity,
        status='DISPENSED',
        actor_user_id=actor_id,
        prescribing_facility_id=rx.facility_id,
        dispensing_facility_id=dispensing_fac_id,
        is_cross_facility=False,
    )
    db.add(tx)
    db.flush()

    if rx.items:
        d_item = DispensingItem(
            transaction_id=tx.id,
            prescription_item_id=rx.items[0].id,
            quantity_requested=quantity,
            quantity_dispensed=quantity,
            fulfillment_status='FULL',
        )
        db.add(d_item)
        db.flush()

        b_link = DispensingBatchLink(
            dispensing_item_id=d_item.id,
            batch_id=batch.id,
            quantity=quantity,
        )
        db.add(b_link)

    rx.status = 'COMPLETED'

    # Enqueue partner outbox messages for downstream RMS & EMR reconciliation
    rms_outbox = IntegrationOutbox(
        destination_system='RMS',
        event_type='RMS_DISPENSE_RECONCILE',
        aggregate_type='DispensingTransaction',
        aggregate_id=tx.transaction_id,
        payload=json.dumps({
            'source_transaction_id': tx.transaction_id,
            'pharmacy_code': pharmacy.code if pharmacy else 'UNKNOWN_PHA',
            'batch_number': batch.batch_number,
            'quantity_delta': -quantity,
            'offline_reconciled': True,
        }),
        status='PENDING',
    )
    db.add(rms_outbox)

    ebuzima_outbox = IntegrationOutbox(
        destination_system='EBUZIMA',
        event_type='EBUZIMA_DISPENSE_UPDATE',
        aggregate_type='DispensingTransaction',
        aggregate_id=tx.transaction_id,
        payload=json.dumps({
            'source_transaction_id': tx.transaction_id,
            'external_id': rx.external_id,
            'status': 'DISPENSED',
            'offline_reconciled': True,
        }),
        status='PENDING',
    )
    db.add(ebuzima_outbox)

    record.status = 'RECONCILED'
    record.reconciled_at = datetime.now(UTC)
    record.reconciled_by_user_id = reconciled_by_user_id

    record_audit(
        db,
        'OFFLINE_DISPENSE_RECONCILED',
        'DispensingTransaction',
        tx.transaction_id,
        'OfflineReconciler',
        details={'bundle_id': record.bundle_id, 'quantity': quantity, 'batch_id': batch.id},
        facility_id=rx.facility_id,
        pharmacy_id=pharmacy_id,
    )

    db.commit()
    db.refresh(record)
    db.refresh(tx)
    return record, tx
