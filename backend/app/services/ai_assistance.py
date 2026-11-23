"""Antimicrobial Stewardship AI Assistance Service (Strictly Bounded).

Provides bounded, read-only clinical rationale explanation, guideline citation retrieval,
and aggregate trend summarization.

SAFETY & PRIVACY CONSTRAINTS (P2-03):
1. Hard Architectural Block: Cannot issue, sign, modify, or authorize prescriptions or dispensing.
2. Zero Direct PHI: Direct identifiers are scrubbed; patient references are masked.
3. Grounded Citations: Every output cites authoritative sources (WHO AWaRe Book, Rwanda STG).
4. Explicit Uncertainty: Outputs always carry uncertainty qualifiers and state they are non-prescriptive.
5. Deterministic fallback: Clinical rules knowledge base operates offline without network egress.
"""

from datetime import datetime, timezone
import hashlib
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import (
    Antibiotic,
    GovernedStewardshipRule,
    Prescription,
    PrescriptionItem,
    StewardshipAlert,
)
from app.services.aware import classify_antibiotic, get_aware_classification
from app.services.metrics import evaluate_governed_metrics

UTC = timezone.utc
MODEL_VERSION = 'AMRGuard-ClinicalKB-v1.0'

AUTHORITATIVE_GUIDELINES: dict[str, dict[str, str]] = {
    'WHO_AWARE_2023': {
        'title': 'WHO Model List of Essential Medicines & AWaRe Antibiotic Book (2023)',
        'source': 'World Health Organization (Geneva)',
        'target': 'Achieve at least 60% of total national antibiotic consumption from the Access group.',
    },
    'RWANDA_STG_2022': {
        'title': 'Rwanda National Standard Treatment Guidelines for Primary and Secondary Healthcare (7th Edition)',
        'source': 'Rwanda Ministry of Health / Rwanda Biomedical Centre',
        'target': 'Prioritize narrow-spectrum oral aminopenicillins for uncomplicated community infections.',
    },
    'SANFORD_GUIDE_2024': {
        'title': 'Antimicrobial Therapy Guidance: Short-Course Community Regimens',
        'source': 'Clinical Stewardship Guidelines Consensus',
        'target': 'Regimens exceeding 7 days require clinical re-assessment and micro-culture justification.',
    },
}

ALTERNATIVE_ACCESS_RECOMMENDATIONS: dict[str, dict[str, Any]] = {
    'CIP500TAB': {
        'preferred_access_alternatives': ['Amoxicillin-Clavulanate 625mg PO', 'Co-trimoxazole 960mg PO', 'Nitrofurantoin 100mg PO'],
        'clinical_note': 'Ciprofloxacin carries high selection pressure for fluoroquinolone resistance and tendon toxicity; reserve for pyelonephritis or culture-proven resistant organisms.',
    },
    'CRO1GINJ': {
        'preferred_access_alternatives': ['Ampicillin + Gentamicin IV', 'Amoxicillin-Clavulanate IV'],
        'clinical_note': 'Ceftriaxone select for ESBL-producing enterobacterales; de-escalate to oral Access group once clinically stabilized.',
    },
    'AZM500TAB': {
        'preferred_access_alternatives': ['Amoxicillin 500mg PO', 'Doxycycline 100mg PO'],
        'clinical_note': 'Azithromycin is frequently over-prescribed for viral upper respiratory tract infections. Confirm bacterial indication before initiation.',
    },
    'COL1MINJ': {
        'preferred_access_alternatives': ['Consult Infectious Disease Specialist', 'Meropenem-Vaborbactam (with susceptibility proof)'],
        'clinical_note': 'Colistin is a last-resort Reserve polymyxin with significant nephrotoxicity. Requires specialist stewardship committee pre-authorization.',
    },
}


def sanitize_clinical_context(patient_ref: str, text: str | None) -> str:
    """Scrubs phone numbers, email addresses, and replaces direct patient references with masked tokens."""
    if not text:
        return ''
    cleaned = text
    # Mask phone numbers (E.164 or local)
    cleaned = re.sub(r'(\+?250\s?)?\d{8,9}', '[PHONE_REDACTED]', cleaned)
    # Mask email addresses
    cleaned = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[EMAIL_REDACTED]', cleaned)
    # Mask patient reference
    if patient_ref:
        patient_token = f'PATIENT-{hashlib.sha256(patient_ref.encode()).hexdigest()[:8].upper()}'
        cleaned = cleaned.replace(patient_ref, patient_token)
    return cleaned


def explain_prescription_validation(
    db: Session,
    prescription: Prescription,
) -> dict[str, Any]:
    """Generates explainable clinical rationale for prescription validation status and issues."""
    sanitized_ref = sanitize_clinical_context(prescription.patient_reference, prescription.patient_reference)
    items_summary = []
    citations = [AUTHORITATIVE_GUIDELINES['RWANDA_STG_2022'], AUTHORITATIVE_GUIDELINES['WHO_AWARE_2023']]
    recommendations = []
    has_watch_or_reserve = False

    for item in prescription.items:
        ab = db.get(Antibiotic, item.antibiotic_id)
        generic = ab.generic_name if ab else 'Unknown Antibiotic'
        aware_cat = classify_antibiotic(db, ab.code) if ab else 'ACCESS'
        if aware_cat in ('WATCH', 'RESERVE'):
            has_watch_or_reserve = True

        items_summary.append(
            f"{generic} ({item.dose}{item.dose_unit or 'mg'} x {item.frequency_per_day}/day x {item.duration_days} days, category: {aware_cat})"
        )

        if ab and ab.code in ALTERNATIVE_ACCESS_RECOMMENDATIONS:
            rec_info = ALTERNATIVE_ACCESS_RECOMMENDATIONS[ab.code]
            recommendations.append(
                f"For {generic}: consider Access first-line alternatives ({', '.join(rec_info['preferred_access_alternatives'])}). {rec_info['clinical_note']}"
            )

        if item.duration_days > 7:
            citations.append(AUTHORITATIVE_GUIDELINES['SANFORD_GUIDE_2024'])
            recommendations.append(
                f"Prescribed duration of {item.duration_days} days for {generic} exceeds standard 5-7 day guideline. Evaluate for early de-escalation at Day 3 reassessment."
            )

    status_desc = {
        'VALIDATED': 'Regimen conforms to formulary dose and frequency rules.',
        'WARNING': 'Regimen conforms to basic limits but triggered clinical stewardship review recommendations.',
        'BLOCKED': 'Order violates safety constraints (e.g. quantity vs daily dose discrepancy or unmapped code).',
    }.get(prescription.status, f'Status is {prescription.status}.')

    summary = (
        f"Prescription {prescription.external_id} for subject {sanitized_ref} has status {prescription.status}. "
        f"{status_desc} Contains {len(prescription.items)} item(s): {'; '.join(items_summary)}."
    )

    if not recommendations:
        recommendations.append('Regimen aligns with standard first-line Access treatment guidelines. Proceed with standard patient counseling.')

    return {
        'scenario': 'PRESCRIPTION_VALIDATION_EXPLAIN',
        'summary': summary,
        'clinical_rationale': (
            'Stewardship guidelines prioritize narrow-spectrum Access agents to preserve Watch and Reserve classes for confirmed resistant infections.'
            if has_watch_or_reserve
            else 'Standard Access regimen preserves antimicrobial susceptibility while achieving clinical cure.'
        ),
        'recommendations': recommendations,
        'guideline_citations': citations,
        'uncertainty_caveats': [
            'Advisory synthesis only: does not constitute clinical prescription or dispensing authorization.',
            'Final treatment decisions remain under the sole professional authority of the licensed clinician.',
            'Patient-specific contraindications, renal clearance, and microbiological cultures must be verified independently.',
        ],
        'phi_redacted': True,
        'model_version': MODEL_VERSION,
        'evaluated_at': datetime.now(UTC).isoformat(),
    }


def explain_stewardship_alert(
    db: Session,
    alert: StewardshipAlert,
) -> dict[str, Any]:
    """Generates explainable clinical context and de-escalation guidance for an active alert."""
    rule = db.get(GovernedStewardshipRule, alert.rule_id) if alert.rule_id else None
    citations = [AUTHORITATIVE_GUIDELINES['WHO_AWARE_2023']]
    recommendations = []

    rx = db.get(Prescription, alert.prescription_id)
    sanitized_ref = sanitize_clinical_context(rx.patient_reference if rx else '', rx.patient_reference if rx else '')

    if alert.rule_code == 'RULE-ACCESS-FIRSTLINE':
        citations.append(AUTHORITATIVE_GUIDELINES['RWANDA_STG_2022'])
        recommendations.append('Reassess whether an Access-group antimicrobial (e.g. Amoxicillin, Ampicillin, Doxycycline) provides adequate empiric coverage.')
        recommendations.append('If culture data confirms resistance or clinical severity mandates Watch coverage, document rationale as OVERRIDDEN_WITH_REASON.')
    elif alert.rule_code == 'RULE-MAX-DURATION-7D':
        citations.append(AUTHORITATIVE_GUIDELINES['SANFORD_GUIDE_2024'])
        recommendations.append('Consider shortening duration to 5 or 7 days if the patient demonstrates clinical stability and defervescence.')
        recommendations.append('For deep-seated infections (e.g. osteomyelitis, endocarditis), document the specialty indication in the disposition review.')
    elif alert.rule_code == 'RULE-RESERVE-SPECIALIST-RESTRICTION':
        recommendations.append('Reserve agents require specialist infectious disease approval and documented susceptibility report.')
        recommendations.append('Verify hospital antimicrobial stewardship committee pre-authorization before pharmacy release.')

    summary = (
        f"Alert {alert.alert_id} ({alert.rule_code}) flagged with severity {alert.severity} on Prescription #{alert.prescription_id} (subject {sanitized_ref}). "
        f"{alert.message}"
    )

    return {
        'scenario': 'STEWARDSHIP_ALERT_EXPLAIN',
        'summary': summary,
        'clinical_rationale': (
            rule.clinical_rationale if rule and rule.clinical_rationale else 'Alert triggered to promote evidence-based antimicrobial use and prevent emergence of drug resistance.'
        ),
        'recommendations': recommendations,
        'guideline_citations': citations,
        'uncertainty_caveats': [
            'Advisory synthesis only: does not overrule clinician judgment or alter dispensing state.',
            'Reviewing clinicians must document clinical rationale if choosing to override this alert.',
        ],
        'phi_redacted': True,
        'model_version': MODEL_VERSION,
        'evaluated_at': datetime.now(UTC).isoformat(),
    }


def summarize_stewardship_trends(
    db: Session,
    facility_id: int | None = None,
) -> dict[str, Any]:
    """Generates an executive clinical summary of facility or national stewardship metrics."""
    metrics_data = evaluate_governed_metrics(db, facility_id=facility_id)
    aware = metrics_data['aware_breakdown']

    access_pct = aware['access_percentage']
    meets_target = aware['meets_who_access_target']
    total_orders = aware['total_orders']

    target_status = 'meets the global WHO benchmark (>= 60%)' if meets_target else 'remains below the WHO global benchmark of 60%'
    summary = (
        f"Surveillance across {total_orders} evaluated orders indicates {access_pct}% Access group consumption, "
        f"which {target_status}. Watch group accounts for {aware['watch_percentage']}%, and Reserve group accounts for {aware['reserve_percentage']}%."
    )

    recommendations = []
    if not meets_target:
        recommendations.append('Implement prospective audit and feedback on empiric Watch-group prescriptions (Ciprofloxacin, Ceftriaxone).')
        recommendations.append('Conduct targeted education for prescribers on first-line Access recommendations in Rwanda STG.')
    else:
        recommendations.append('Maintain current antimicrobial stewardship interventions to sustain Access utilization above 60%.')

    recon_metric = next((m for m in metrics_data['metrics'] if m['metric_code'] == 'RX_DISPENSE_RECON_RATE'), None)
    if recon_metric and recon_metric['value'] < 85.0:
        recommendations.append(f"Prescription-dispense reconciliation ({recon_metric['value']}%) is below the 85% target; investigate unrecorded pharmacy dispenses.")

    return {
        'scenario': 'AGGREGATE_TREND_SUMMARY',
        'summary': summary,
        'clinical_rationale': 'WHO AWaRe categorization provides an actionable metric to monitor antibiotic consumption patterns and mitigate antimicrobial resistance.',
        'recommendations': recommendations,
        'guideline_citations': [AUTHORITATIVE_GUIDELINES['WHO_AWARE_2023']],
        'uncertainty_caveats': metrics_data['data_quality_caveats'],
        'phi_redacted': True,
        'model_version': MODEL_VERSION,
        'evaluated_at': datetime.now(UTC).isoformat(),
    }
