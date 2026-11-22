"""Canonical partner adapter for e-Buzima EMR integration.

Translates e-Buzima FHIR R4 bundles and proprietary prescription orders into AMRGuard
canonical domain models, performs partner code resolution against the medicine catalogue,
and serializes outbound dispensing updates for e-Buzima synchronization.
"""

from datetime import datetime, timezone
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
from app.models.core import Antibiotic, Facility, MedicineConcept, MedicineMapping
from app.schemas.prescriptions import (
    PrescriberIn,
    PrescriptionIn,
    PrescriptionItemIn,
)

logger = logging.getLogger('amrguard.adapters.ebuzima')


class EBuzimaAdapter(PartnerAdapter):
    """Canonical adapter for e-Buzima clinical EMR integration."""

    @property
    def system_name(self) -> str:
        return 'e-Buzima'

    def parse_prescription(self, payload: dict[str, Any], db: Session) -> tuple[PrescriptionIn, AdapterIngestResult]:
        """Parse an inbound prescription payload (FHIR R4 Bundle or e-Buzima JSON) into PrescriptionIn.

        Raises UnmappedCodeError if any facility, prescriber, or medication code cannot be resolved.
        Raises PartnerContractError if payload structure is invalid.
        """
        if not isinstance(payload, dict):
            raise PartnerContractError('Payload must be a JSON object')

        payload_hash = calculate_payload_hash(payload)

        # Detect FHIR R4 Bundle vs Proprietary JSON
        if payload.get('resourceType') == 'Bundle':
            rx_in = self._parse_fhir_bundle(payload, db)
        elif 'items' in payload and 'prescriber' in payload:
            rx_in = self._parse_proprietary_json(payload, db)
        else:
            raise PartnerContractError("Unsupported payload format: missing required 'resourceType' or 'items' structure")

        ingest_result = AdapterIngestResult(
            source_system=self.system_name,
            event_type='PRESCRIPTION',
            external_id=rx_in.external_id,
            payload_hash=payload_hash,
            canonical_data=rx_in,
            raw_payload=payload,
        )
        return rx_in, ingest_result

    def _parse_proprietary_json(self, payload: dict[str, Any], db: Session) -> PrescriptionIn:
        external_id = payload.get('external_id')
        if not external_id or not str(external_id).strip():
            raise PartnerContractError("Field 'external_id' is required")

        patient_ref = payload.get('patient_reference')
        if not patient_ref or not str(patient_ref).strip():
            raise PartnerContractError("Field 'patient_reference' is required")

        prescriber_data = payload.get('prescriber')
        if not isinstance(prescriber_data, dict):
            raise PartnerContractError("Field 'prescriber' must be an object")

        fac_code = prescriber_data.get('facility_code')
        if not fac_code:
            raise PartnerContractError("Field 'prescriber.facility_code' is required")

        # Resolve facility
        fac = db.scalar(select(Facility).where(Facility.code == fac_code, Facility.active.is_(True)))
        if not fac:
            raise UnmappedCodeError(code=fac_code, domain='FACILITY', source_system=self.system_name)

        prescriber = PrescriberIn(
            external_user_id=prescriber_data.get('external_user_id', 'EBUZIMA-UNKNOWN'),
            name=prescriber_data.get('name', 'e-Buzima Prescriber'),
            facility_code=fac_code,
            facility_name=prescriber_data.get('facility_name', fac.name),
            district=prescriber_data.get('district', fac.district),
        )

        items_raw = payload.get('items')
        if not items_raw or not isinstance(items_raw, list):
            raise PartnerContractError("Field 'items' must be a non-empty list")

        canonical_items: list[PrescriptionItemIn] = []
        for idx, item in enumerate(items_raw):
            if not isinstance(item, dict):
                raise PartnerContractError(f'Item at index {idx} must be an object')

            raw_code = item.get('antibiotic_code') or item.get('code')
            if not raw_code:
                raise PartnerContractError(f"Item at index {idx} missing 'antibiotic_code'")

            resolved_code, form_id = self._resolve_antibiotic_code(raw_code, db)

            expires_at = payload.get('expires_at')
            parsed_expires = None
            if expires_at:
                try:
                    parsed_expires = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                except ValueError:
                    raise PartnerContractError(f"Invalid ISO timestamp format for 'expires_at': {expires_at}")

            canonical_items.append(
                PrescriptionItemIn(
                    antibiotic_code=resolved_code,
                    generic_name=item.get('generic_name', 'Prescribed Antibiotic'),
                    strength=item.get('strength', 'Standard'),
                    formulation=item.get('formulation', 'Tablet'),
                    formulation_id=form_id or item.get('formulation_id'),
                    route=item.get('route', 'Oral'),
                    dose=float(item.get('dose', 500)),
                    frequency_per_day=int(item.get('frequency_per_day', 3)),
                    duration_days=int(item.get('duration_days', 5)),
                    quantity=int(item.get('quantity', 15)),
                    indication=item.get('indication', 'Prescribed indication'),
                    dose_unit=item.get('dose_unit', 'mg'),
                    pack_size=item.get('pack_size'),
                    units_per_administration=item.get('units_per_administration', 1.0),
                    is_prn=bool(item.get('is_prn', False)),
                    timing_instructions=item.get('timing_instructions'),
                    timezone=item.get('timezone', 'Africa/Kigali'),
                )
            )

        return PrescriptionIn(
            external_id=external_id,
            patient_reference=patient_ref,
            prescriber=prescriber,
            items=canonical_items,
            expires_at=parsed_expires,
            allow_external_dispensing=bool(payload.get('allow_external_dispensing', False)),
        )

    def _parse_fhir_bundle(self, bundle: dict[str, Any], db: Session) -> PrescriptionIn:
        """Parse a FHIR R4 Bundle containing MedicationRequest resources."""
        entries = bundle.get('entry') or []
        if not entries:
            raise PartnerContractError('FHIR Bundle has no entries')

        external_id = bundle.get('id') or f"EBZ-FHIR-{uuid4().hex[:8]}"
        patient_ref = None
        facility_code = None
        prescriber_id = None
        prescriber_name = None
        canonical_items: list[PrescriptionItemIn] = []

        for entry in entries:
            res = entry.get('resource') or {}
            if res.get('resourceType') == 'MedicationRequest':
                # Patient
                if not patient_ref:
                    subj = res.get('subject') or {}
                    patient_ref = subj.get('reference') or subj.get('display')

                # Prescriber & Facility
                if not prescriber_id:
                    req = res.get('requester') or {}
                    prescriber_id = req.get('reference', 'P-UNKNOWN')
                    prescriber_name = req.get('display', 'e-Buzima Physician')

                # Facility identifier
                if not facility_code:
                    for ext in res.get('extension') or []:
                        if 'facility' in ext.get('url', '').lower():
                            facility_code = ext.get('valueString') or ext.get('valueCode')
                    if not facility_code and res.get('recorder', {}).get('reference'):
                        facility_code = res['recorder']['reference'].split('/')[-1]

                # Medication coding
                med_cc = res.get('medicationCodeableConcept') or {}
                codings = med_cc.get('coding') or []
                raw_code = None
                display_name = med_cc.get('text', 'Antibiotic')
                for c in codings:
                    raw_code = c.get('code')
                    if c.get('display'):
                        display_name = c.get('display')
                    if raw_code:
                        break

                if not raw_code:
                    raise PartnerContractError("MedicationRequest missing medication code in 'medicationCodeableConcept'")

                resolved_code, form_id = self._resolve_antibiotic_code(raw_code, db)

                # Dosage & Regimen
                dosage = (res.get('dosageInstruction') or [{}])[0]
                freq = 3
                timing = dosage.get('timing', {}).get('repeat', {})
                if 'frequency' in timing:
                    freq = timing['frequency']

                dose_val = 500.0
                dose_unit = 'mg'
                d_and_r = (dosage.get('doseAndRate') or [{}])[0]
                dq = d_and_r.get('doseQuantity') or {}
                if 'value' in dq:
                    dose_val = float(dq['value'])
                if 'unit' in dq:
                    dose_unit = dq['unit']

                # Dispense request
                disp = res.get('dispenseRequest') or {}
                duration_days = 5
                if 'expectedSupplyDuration' in disp:
                    duration_days = int(disp['expectedSupplyDuration'].get('value', 5))
                quantity = int(disp.get('quantity', {}).get('value', freq * duration_days))

                route_text = 'Oral'
                route_cc = dosage.get('route', {}).get('coding', [{}])[0]
                if route_cc.get('display'):
                    route_text = route_cc['display']

                canonical_items.append(
                    PrescriptionItemIn(
                        antibiotic_code=resolved_code,
                        generic_name=display_name,
                        strength=f"{dose_val} {dose_unit}",
                        formulation='Tablet',
                        formulation_id=form_id,
                        route=route_text,
                        dose=dose_val,
                        dose_unit=dose_unit,
                        frequency_per_day=freq,
                        duration_days=duration_days,
                        quantity=quantity,
                        indication=res.get('reasonCode', [{}])[0].get('text', 'Bacterial Infection'),
                        is_prn=bool(dosage.get('asNeededBoolean', False)),
                    )
                )

        if not patient_ref:
            patient_ref = 'FHIR-UNKNOWN-PATIENT'

        # Default facility to first active facility if not passed in FHIR extension
        if not facility_code:
            fac = db.scalar(select(Facility).where(Facility.active.is_(True)).order_by(Facility.id))
            if not fac:
                raise UnmappedCodeError(code='MISSING', domain='FACILITY', source_system=self.system_name)
            facility_code = fac.code
        else:
            fac = db.scalar(select(Facility).where(Facility.code == facility_code, Facility.active.is_(True)))
            if not fac:
                raise UnmappedCodeError(code=facility_code, domain='FACILITY', source_system=self.system_name)

        return PrescriptionIn(
            external_id=external_id,
            patient_reference=patient_ref,
            prescriber=PrescriberIn(
                external_user_id=prescriber_id or 'P-UNKNOWN',
                name=prescriber_name or 'Prescriber',
                facility_code=facility_code,
                facility_name=fac.name,
                district=fac.district,
            ),
            items=canonical_items,
        )

    def _resolve_antibiotic_code(self, raw_code: str, db: Session) -> tuple[str, int | None]:
        """Resolve a partner antibiotic code to AMRGuard internal Antibiotic.code and optional formulation_id."""
        # 1. Direct catalogue lookup
        direct = db.scalar(select(Antibiotic).where(Antibiotic.code == raw_code))
        if direct:
            return direct.code, None

        # 2. MedicineMapping lookup
        mapping = db.scalar(
            select(MedicineMapping).where(
                MedicineMapping.source_code == raw_code,
                MedicineMapping.approval_status == 'APPROVED',
                MedicineMapping.active.is_(True),
            )
        )
        if mapping:
            concept = db.get(MedicineConcept, mapping.medicine_concept_id) if mapping.medicine_concept_id else None
            if concept:
                mapped_ab = db.scalar(select(Antibiotic).where(Antibiotic.code == concept.code))
                if mapped_ab:
                    return mapped_ab.code, mapping.formulation_id

        # 3. Unresolved
        raise UnmappedCodeError(code=raw_code, domain='ANTIBIOTIC', source_system=self.system_name)

    def format_dispense_notification(self, outbox_payload: dict[str, Any]) -> dict[str, Any]:
        """Format an AMRGuard dispensing outbox event into an e-Buzima MedicationDispense notification."""
        return {
            'resourceType': 'MedicationDispense',
            'id': f"MD-{outbox_payload.get('transaction_id')}",
            'status': 'completed',
            'authorizingPrescription': [{'reference': f"Prescription/{outbox_payload.get('prescription_external_id')}"}],
            'quantity': {
                'value': outbox_payload.get('quantity_dispensed'),
                'unit': 'units',
            },
            'whenHandedOver': outbox_payload.get('timestamp') or datetime.now(timezone.utc).isoformat(),
            'performer': [{
                'actor': {
                    'reference': f"Location/{outbox_payload.get('pharmacy_code')}",
                    'display': f"Pharmacy {outbox_payload.get('pharmacy_code')}",
                }
            }],
            'extension': [{
                'url': 'https://amrguard.rw/fhir/StructureDefinition/dispense-allocations',
                'valueString': json.dumps(outbox_payload.get('allocations', [])),
            }],
        }


class MockEBuzimaTransportClient(PartnerTransportClient):
    """In-memory mock transport client for e-Buzima sandbox testing and contract verification."""

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
                f"e-Buzima gateway simulated error ({self.status_code}) on {endpoint}",
                status_code=self.status_code,
                is_retryable=self.status_code in (500, 502, 503, 504),
            )

        self.sent_messages.append({'endpoint': endpoint, 'payload': payload, 'headers': headers or {}})
        return AdapterDispatchResult(
            destination_system='e-Buzima',
            event_type='MEDICATION_DISPENSE_CALLBACK',
            aggregate_id=str(payload.get('id') or ''),
            external_reference=f"EBZ-ACK-{uuid4().hex[:8]}",
            status='DISPATCHED',
            status_code=200,
            response_body={'ack': True, 'received_at': datetime.now(timezone.utc).isoformat()},
        )
