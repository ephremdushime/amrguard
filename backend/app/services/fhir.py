"""FHIR-compatible mapping helpers.
These mappings are internal normalization helpers; they do not claim to be the external
FHIR contract of any national system. Final profiles/terminologies must be agreed with
integration owners.
"""
def prescription_to_medication_request(rx, db):
    item = rx.items[0]
    antibiotic = db.get(__import__('app.models.core', fromlist=['Antibiotic']).Antibiotic, item.antibiotic_id)
    return {
        "resourceType": "MedicationRequest",
        "id": f"amrguard-rx-{rx.id}",
        "status": "active" if rx.status in {"ACTIVE","PARTIALLY_DISPENSED"} else "draft",
        "intent": "order",
        "subject": {"reference": f"Patient/{rx.patient_reference}"},
        "requester": {"reference": f"Practitioner/{rx.prescriber_id}"},
        "medicationCodeableConcept": {"coding": [{"system": "urn:amrguard:antibiotic", "code": antibiotic.code, "display": antibiotic.generic_name}]},
        "dosageInstruction": [{
            "doseAndRate": [{"doseQuantity": {"value": float(item.dose)}}],
            "timing": {"repeat": {"frequency": float(item.frequency_per_day), "period": 1, "periodUnit": "d"}},
            "route": {"text": antibiotic.route},
            "text": f"{item.dose} dose, {item.frequency_per_day} times/day for {item.duration_days} days"
        }],
        "dispenseRequest": {"quantity": {"value": item.quantity}, "expectedSupplyDuration": {"value": item.duration_days, "unit": "days"}}
    }

def dispensing_to_medication_dispense(tx, db):
    return {
        "resourceType": "MedicationDispense",
        "id": tx.transaction_id,
        "status": "completed" if tx.status == "COMPLETED" else tx.status.lower(),
        "authorizingPrescription": [{"reference": f"MedicationRequest/amrguard-rx-{tx.prescription_id}"}],
        "quantity": {"value": tx.quantity},
        "performer": [{"actor": {"reference": f"Organization/Pharmacy-{tx.pharmacy_id}"}}],
        "identifier": [{"system": "urn:amrguard:transaction", "value": tx.transaction_id}]
    }
