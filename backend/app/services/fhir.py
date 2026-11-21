"""FHIR R4 compatible mapping helpers.

These mappings are internal normalization helpers; they do not claim to be the external
FHIR contract of any national system. Final profiles, terminologies, and extensions
must be agreed with target integration owners (e.g., e-Buzima / MoH Rwanda).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.models.core import Antibiotic, DispensingTransaction, Prescription, PrescriptionItem, StockBatch

FHIR_NAMESPACE = uuid.UUID("4ca76218-8ba0-45c7-99cf-797ed41d834e")


def _format_datetime(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _format_date(dt: Any) -> str | None:
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def _map_prescription_status(status: str) -> str:
    status_upper = (status or "").upper()
    if status_upper in {"ACTIVE", "PARTIALLY_DISPENSED", "CREATED"}:
        return "active"
    if status_upper in {"DISPENSED", "COMPLETED"}:
        return "completed"
    if status_upper in {"CANCELLED", "REVOKED"}:
        return "cancelled"
    return "draft"


def prescription_item_to_medication_request(
    rx: Prescription, item: PrescriptionItem, db: Any, index: int = 1
) -> dict[str, Any]:
    """Map a single PrescriptionItem to a FHIR R4 MedicationRequest."""
    antibiotic = (
        db.get(Antibiotic, item.antibiotic_id) if item.antibiotic_id is not None else None
    )

    item_id = item.id if item.id is not None else index
    coding: list[dict[str, str]] = []
    display_name = "Unknown Antibiotic"

    if antibiotic:
        display_name = antibiotic.generic_name
        coding.append({
            "system": "urn:amrguard:antibiotic",
            "code": antibiotic.code,
            "display": antibiotic.generic_name,
        })
        if getattr(antibiotic, "atc_code", None):
            coding.append({
                "system": "http://www.whocc.no/atc",
                "code": antibiotic.atc_code,
                "display": antibiotic.generic_name,
            })

    dosage_text = f"{item.dose} dose, {item.frequency_per_day} times/day for {item.duration_days} days"
    if item.indication:
        dosage_text = f"{dosage_text} (Indication: {item.indication})"

    med_req: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": f"amrguard-rx-{rx.id}-item-{item_id}",
        "identifier": [
            {
                "system": "urn:amrguard:prescription:external-id",
                "value": rx.external_id,
            },
            {
                "system": "urn:amrguard:prescription-item:id",
                "value": str(item_id),
            },
        ],
        "groupIdentifier": {
            "system": "urn:amrguard:prescription:id",
            "value": str(rx.id),
        },
        "status": _map_prescription_status(rx.status),
        "intent": "order",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/medicationrequest-category",
                        "code": "outpatient",
                        "display": "Outpatient",
                    }
                ]
            }
        ],
        "subject": {"reference": f"Patient/{rx.patient_reference}"},
        "encounter": {"reference": f"Encounter/facility-{rx.facility_id}"},
        "requester": {"reference": f"Practitioner/{rx.prescriber_id}"},
        "authoredOn": _format_datetime(rx.created_at),
        "medicationCodeableConcept": {
            "coding": coding,
            "text": display_name,
        },
        "dosageInstruction": [
            {
                "text": dosage_text,
                "timing": {
                    "repeat": {
                        "frequency": float(item.frequency_per_day),
                        "period": 1,
                        "periodUnit": "d",
                    }
                },
                "route": {"text": getattr(antibiotic, "route", "oral") if antibiotic else "oral"},
                "doseAndRate": [
                    {
                        "doseQuantity": {
                            "value": float(item.dose),
                            "unit": "dose-unit",
                        }
                    }
                ],
            }
        ],
        "dispenseRequest": {
            "quantity": {"value": item.quantity},
            "expectedSupplyDuration": {"value": item.duration_days, "unit": "days"},
            "validityPeriod": {
                "start": _format_datetime(rx.created_at),
                "end": _format_datetime(rx.expires_at),
            },
        },
    }

    if item.indication:
        med_req["reasonCode"] = [{"text": item.indication}]

    return med_req


def prescription_to_fhir_bundle(rx: Prescription, db: Any) -> dict[str, Any]:
    """Map a complete Prescription (including all line items) to a FHIR R4 Bundle (type: collection)."""
    items = list(rx.items or [])
    entries: list[dict[str, Any]] = []

    for idx, item in enumerate(items, start=1):
        resource = prescription_item_to_medication_request(rx, item, db, index=idx)
        item_id = item.id if item.id is not None else idx
        item_uuid = uuid.uuid5(FHIR_NAMESPACE, f"prescription-{rx.id}-item-{item_id}")
        entries.append({
            "fullUrl": f"urn:uuid:{item_uuid}",
            "resource": resource,
        })

    return {
        "resourceType": "Bundle",
        "id": f"amrguard-rx-bundle-{rx.id}",
        "type": "collection",
        "timestamp": _format_datetime(rx.created_at) or _format_datetime(datetime.now(timezone.utc)),
        "identifier": {
            "system": "urn:amrguard:prescription:external-id",
            "value": rx.external_id,
        },
        "total": len(entries),
        "entry": entries,
    }


def prescription_to_medication_request(
    rx: Prescription, db: Any, prefer_bundle: bool = False
) -> dict[str, Any]:
    """FHIR exporter entry point.

    - If prefer_bundle is True, returns a FHIR R4 Bundle.
    - If rx has multiple items (>1) or zero items, returns a FHIR R4 Bundle
      to guarantee no items are silently dropped and no IndexError occurs.
    - If rx has exactly 1 item and prefer_bundle is False, returns a single
      MedicationRequest for backward compatibility.
    """
    items = list(rx.items or [])
    if prefer_bundle or len(items) != 1:
        return prescription_to_fhir_bundle(rx, db)
    return prescription_item_to_medication_request(rx, items[0], db, index=1)


def dispensing_to_medication_dispense(tx: DispensingTransaction, db: Any) -> dict[str, Any]:
    """Map a DispensingTransaction to a FHIR R4 MedicationDispense resource.

    Includes item and batch linkage, pharmacy/practitioner performer, and timing.
    """
    batch = db.get(StockBatch, tx.batch_id) if tx.batch_id is not None else None
    antibiotic = (
        db.get(Antibiotic, batch.antibiotic_id)
        if (batch and batch.antibiotic_id is not None)
        else None
    )

    auth_prescription_ref = (
        f"MedicationRequest/amrguard-rx-{tx.prescription_id}-item-{tx.item_id}"
        if tx.item_id
        else f"MedicationRequest/amrguard-rx-{tx.prescription_id}"
    )

    performers: list[dict[str, Any]] = [
        {"actor": {"reference": f"Organization/Pharmacy-{tx.pharmacy_id}"}}
    ]
    if tx.actor_user_id:
        performers.append({"actor": {"reference": f"Practitioner/{tx.actor_user_id}"}})

    dispense_resource: dict[str, Any] = {
        "resourceType": "MedicationDispense",
        "id": tx.transaction_id,
        "identifier": [
            {"system": "urn:amrguard:transaction", "value": tx.transaction_id}
        ],
        "status": "completed" if tx.status == "COMPLETED" else tx.status.lower(),
        "type": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "FF",
                    "display": "First Fill",
                }
            ]
        },
        "authorizingPrescription": [{"reference": auth_prescription_ref}],
        "quantity": {"value": tx.quantity, "unit": "unit"},
        "whenHandedOver": _format_datetime(tx.created_at),
        "performer": performers,
    }

    if batch:
        med_id = f"med-batch-{batch.id}"
        coding: list[dict[str, str]] = []
        display_name = "Dispensed Antibiotic"
        if antibiotic:
            display_name = antibiotic.generic_name
            coding.append({
                "system": "urn:amrguard:antibiotic",
                "code": antibiotic.code,
                "display": antibiotic.generic_name,
            })
            if getattr(antibiotic, "atc_code", None):
                coding.append({
                    "system": "http://www.whocc.no/atc",
                    "code": antibiotic.atc_code,
                    "display": antibiotic.generic_name,
                })

        dispense_resource["contained"] = [
            {
                "resourceType": "Medication",
                "id": med_id,
                "code": {
                    "coding": coding,
                    "text": display_name,
                },
                "batch": {
                    "lotNumber": batch.batch_number,
                    "expirationDate": _format_date(batch.expiry_date),
                },
            }
        ]
        dispense_resource["medicationReference"] = {"reference": f"#{med_id}"}
    else:
        dispense_resource["medicationCodeableConcept"] = {
            "text": "Dispensed Antibiotic"
        }

    return dispense_resource
