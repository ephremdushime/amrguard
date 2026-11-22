"""Canonical partner adapter for RMS / eLMIS supply-chain integration.

Translates RMS stock receipt and adjustment feeds into AMRGuard canonical stock events,
resolves national item codes against the medicine catalogue, and serializes outbound
dispensing stock depletion reconciliation events for the central medical store ledger.
"""

from datetime import date, datetime, timezone
import json
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import (
    AdapterDispatchResult,
    AdapterIngestResult,
    PartnerAdapter,
    PartnerContractError,
    PartnerTransportClient,
    PartnerTransportError,
    UnmappedCodeError,
    calculate_payload_hash,
)
from app.models.core import Antibiotic, MedicineConcept, MedicineMapping, Pharmacy
from app.schemas.prescriptions import RmsStockEventRequest

logger = logging.getLogger('amrguard.adapters.rms')


class RMSAdapter(PartnerAdapter):
    """Canonical adapter for RMS / eLMIS supply-chain integration."""

    @property
    def system_name(self) -> str:
        return 'RMS'

    def parse_stock_event(self, payload: dict[str, Any], db: Session) -> tuple[RmsStockEventRequest, AdapterIngestResult]:
        """Parse an inbound stock event payload from RMS / eLMIS into RmsStockEventRequest.

        Raises UnmappedCodeError if pharmacy or medicine code cannot be resolved.
        Raises PartnerContractError if payload schema is invalid.
        """
        if not isinstance(payload, dict):
            raise PartnerContractError('Payload must be a JSON object')

        payload_hash = calculate_payload_hash(payload)

        source_system = payload.get('source_system') or 'RMS'
        if source_system not in ('RMS', 'eLMIS'):
            source_system = 'RMS'

        source_ref = payload.get('source_reference') or payload.get('reference_id')
        if not source_ref or not str(source_ref).strip():
            raise PartnerContractError("Field 'source_reference' is required")

        pharmacy_code = payload.get('pharmacy_code')
        if not pharmacy_code:
            raise PartnerContractError("Field 'pharmacy_code' is required")

        # Resolve pharmacy
        pharmacy = db.scalar(select(Pharmacy).where(Pharmacy.code == pharmacy_code, Pharmacy.active.is_(True)))
        if not pharmacy:
            raise UnmappedCodeError(code=pharmacy_code, domain='PHARMACY', source_system=source_system)

        raw_med_code = payload.get('antibiotic_code') or payload.get('national_item_code') or payload.get('item_code')
        if not raw_med_code:
            raise PartnerContractError("Field 'antibiotic_code' or 'national_item_code' is required")

        resolved_med_code = self._resolve_antibiotic_code(raw_med_code, source_system, db)

        batch_number = payload.get('batch_number')
        if not batch_number or not str(batch_number).strip():
            raise PartnerContractError("Field 'batch_number' is required")

        expiry_raw = payload.get('expiry_date')
        if not expiry_raw:
            raise PartnerContractError("Field 'expiry_date' is required")

        try:
            if isinstance(expiry_raw, str):
                expiry_date = date.fromisoformat(expiry_raw[:10])
            elif isinstance(expiry_raw, (date, datetime)):
                expiry_date = expiry_raw if isinstance(expiry_raw, date) else expiry_raw.date()
            else:
                raise ValueError
        except ValueError:
            raise PartnerContractError(f"Invalid date format for 'expiry_date': {expiry_raw} (expected YYYY-MM-DD)")

        event_type = payload.get('event_type', 'RECEIPT').upper()
        if event_type not in ('RECEIPT', 'ADJUSTMENT'):
            raise PartnerContractError(f"Invalid event_type '{event_type}': expected RECEIPT or ADJUSTMENT")

        try:
            quantity_delta = int(payload.get('quantity_delta', 0))
        except (ValueError, TypeError):
            raise PartnerContractError("Field 'quantity_delta' must be an integer")

        if quantity_delta == 0:
            raise PartnerContractError("Field 'quantity_delta' cannot be zero")

        if event_type == 'RECEIPT' and quantity_delta <= 0:
            raise PartnerContractError('Receipt quantity_delta must be positive')

        ab = db.scalar(select(Antibiotic).where(Antibiotic.code == resolved_med_code))

        canonical_request = RmsStockEventRequest(
            source_system=source_system,
            source_reference=str(source_ref),
            pharmacy_code=pharmacy_code,
            pharmacy_name=pharmacy.name,
            district=pharmacy.district,
            antibiotic_code=resolved_med_code,
            generic_name=payload.get('generic_name') or (ab.generic_name if ab else 'Prescribed Antibiotic'),
            strength=payload.get('strength') or (ab.strength if ab else 'Standard'),
            formulation=payload.get('formulation') or (ab.formulation if ab else 'Unit'),
            route=payload.get('route') or (ab.route if ab else 'Oral'),
            batch_number=str(batch_number).strip(),
            expiry_date=expiry_date,
            event_type=event_type,
            quantity_delta=quantity_delta,
        )

        ingest_result = AdapterIngestResult(
            source_system=source_system,
            event_type='STOCK_EVENT',
            external_id=str(source_ref),
            payload_hash=payload_hash,
            canonical_data=canonical_request,
            raw_payload=payload,
        )
        return canonical_request, ingest_result

    def _resolve_antibiotic_code(self, raw_code: str, source_system: str, db: Session) -> str:
        """Resolve a national item or RMS product code to internal Antibiotic.code."""
        direct = db.scalar(select(Antibiotic).where(Antibiotic.code == raw_code))
        if direct:
            return direct.code

        mapping = db.scalar(
            select(MedicineMapping).where(
                MedicineMapping.source_code == raw_code,
                MedicineMapping.approval_status == 'APPROVED',
                MedicineMapping.active.is_(True),
            )
        )
        if mapping and mapping.medicine_concept_id:
            concept = db.get(MedicineConcept, mapping.medicine_concept_id)
            if concept:
                mapped_ab = db.scalar(select(Antibiotic).where(Antibiotic.code == concept.code))
                if mapped_ab:
                    return mapped_ab.code

        raise UnmappedCodeError(code=raw_code, domain='ANTIBIOTIC', source_system=source_system)

    def format_stock_consumption(self, outbox_payload: dict[str, Any]) -> dict[str, Any]:
        """Format an AMRGuard dispensing outbox reconciliation event into an RMS consumption ledger update."""
        return {
            'source_system': 'AMRGuard',
            'transaction_type': 'DISPENSE_DEPLETION',
            'reconciliation_id': outbox_payload.get('transaction_id'),
            'pharmacy_code': outbox_payload.get('pharmacy_code'),
            'facility_id': outbox_payload.get('facility_id'),
            'prescription_reference': outbox_payload.get('prescription_external_id'),
            'total_depleted': outbox_payload.get('quantity_dispensed'),
            'batch_depletions': outbox_payload.get('allocations', []),
            'actor_user_id': outbox_payload.get('actor_user_id'),
            'timestamp': outbox_payload.get('timestamp') or datetime.now(timezone.utc).isoformat(),
        }


class MockRMSTransportClient(PartnerTransportClient):
    """In-memory mock transport client for RMS/eLMIS inventory ledger contract verification."""

    def __init__(self, should_fail: bool = False, fail_count: int = 0, status_code: int = 503):
        self.should_fail = should_fail
        self.fail_count = fail_count
        self.attempts = 0
        self.status_code = status_code
        self.sent_messages: list[dict[str, Any]] = []

    def send(self, endpoint: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> AdapterDispatchResult:
        self.attempts += 1
        if self.should_fail or (self.fail_count > 0 and self.attempts <= self.fail_count):
            raise PartnerTransportError(
                f"RMS inventory ledger simulated error ({self.status_code}) on {endpoint}",
                status_code=self.status_code,
                is_retryable=self.status_code in (500, 502, 503, 504),
            )

        self.sent_messages.append({'endpoint': endpoint, 'payload': payload, 'headers': headers or {}})
        return AdapterDispatchResult(
            destination_system='RMS',
            event_type='RMS_STOCK_CONSUMPTION_ACK',
            aggregate_id=str(payload.get('reconciliation_id') or ''),
            external_reference=f"RMS-RECON-{uuid4().hex[:8]}",
            status='DISPATCHED',
            status_code=200,
            response_body={'reconciled': True, 'ledger_tx': f"TX-RMS-{uuid4().hex[:6]}"},
        )
