"""Clinically Governed Antimicrobial Stewardship Rules Engine.

Implements versioned rule evaluation, structured alert generation, clinical rationale
tracking, and auditable override/disposition recording (including false-positive feedback).
"""

from datetime import date, datetime, timezone
from decimal import Decimal
import secrets
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
from app.services.aware import classify_antibiotic

UTC = timezone.utc

DEFAULT_STEWARDSHIP_RULES: list[dict] = [
    {
        'rule_code': 'RULE-ACCESS-FIRSTLINE',
        'title': 'Prioritize Access-Group Antibiotics as First-Line',
        'description': 'Encourages the use of narrow-spectrum Access-group antimicrobials for community-acquired infections before Watch-group agents.',
        'category': 'AWARE_RESTRICTION',
        'severity': 'WARNING',
        'aware_category': 'WATCH',
        'requires_specialist_approval': False,
        'effective_start_date': date(2023, 1, 1),
        'clinical_rationale': 'WHO AWaRe and national treatment guidelines recommend Access group as empiric first-line to limit selection for resistant pathogens.',
    },
    {
        'rule_code': 'RULE-MAX-DURATION-7D',
        'title': 'Standard Regimen Duration Ceiling (<= 7 Days)',
        'description': 'Flags empiric community antibiotic regimens exceeding 7 days of treatment without specialist micro culture confirmation.',
        'category': 'DURATION',
        'severity': 'REVIEW_REQUIRED',
        'max_duration_days': 7,
        'requires_specialist_approval': False,
        'effective_start_date': date(2023, 1, 1),
        'clinical_rationale': 'Shorter durations (5-7 days) are clinically equivalent to prolonged courses for most community infections with fewer adverse events and less resistance.',
    },
    {
        'rule_code': 'RULE-RESERVE-SPECIALIST-RESTRICTION',
        'title': 'Reserve-Group Antibiotic Specialist Pre-Authorization',
        'description': 'Restricts Reserve-group antimicrobials (e.g. Colistin, Linezolid, Meropenem) to confirmed multidrug-resistant infections with stewardship review.',
        'category': 'AWARE_RESTRICTION',
        'severity': 'BLOCK',
        'aware_category': 'RESERVE',
        'requires_specialist_approval': True,
        'effective_start_date': date(2023, 1, 1),
        'clinical_rationale': 'Reserve agents are the last line of defense against pandrug-resistant pathogens and must be strictly safeguarded.',
    },
]


def seed_governed_rules(db: Session) -> int:
    """Populates baseline governed stewardship rules if absent."""
    seeded = 0
    for r in DEFAULT_STEWARDSHIP_RULES:
        existing = db.scalar(select(GovernedStewardshipRule).where(GovernedStewardshipRule.rule_code == r['rule_code']))
        if not existing:
            db.add(
                GovernedStewardshipRule(
                    rule_code=r['rule_code'],
                    title=r['title'],
                    description=r['description'],
                    category=r['category'],
                    severity=r['severity'],
                    aware_category=r.get('aware_category'),
                    max_duration_days=r.get('max_duration_days'),
                    requires_specialist_approval=r.get('requires_specialist_approval', False),
                    version=1,
                    status='ACTIVE',
                    effective_start_date=r['effective_start_date'],
                    clinical_rationale=r['clinical_rationale'],
                )
            )
            seeded += 1
    if seeded > 0:
        db.commit()
    return seeded


def get_active_rules(db: Session) -> list[GovernedStewardshipRule]:
    """Retrieves currently active, non-superseded stewardship rules."""
    today = date.today()
    return list(
        db.scalars(
            select(GovernedStewardshipRule).where(
                GovernedStewardshipRule.status == 'ACTIVE',
                GovernedStewardshipRule.effective_start_date <= today,
                (GovernedStewardshipRule.effective_end_date.is_(None)) | (GovernedStewardshipRule.effective_end_date >= today),
            )
        ).all()
    )


def evaluate_prescription_rules(
    db: Session,
    prescription: Prescription,
    auto_commit: bool = True,
) -> list[StewardshipAlert]:
    """Evaluates active rules against all items of a prescription and records structured alerts."""
    seed_governed_rules(db)
    active_rules = get_active_rules(db)
    generated_alerts: list[StewardshipAlert] = []

    for item in prescription.items:
        antibiotic = db.get(Antibiotic, item.antibiotic_id)
        if not antibiotic:
            continue

        item_aware_cat = classify_antibiotic(db, antibiotic.code)

        for rule in active_rules:
            # 1. AWaRe Category Check
            if rule.aware_category and rule.aware_category == item_aware_cat:
                alert_id = f'ALT-{secrets.token_hex(6).upper()}'
                msg = f'[{rule.aware_category}] {antibiotic.generic_name} is classified in the WHO {rule.aware_category} category. {rule.title}.'
                alert = StewardshipAlert(
                    alert_id=alert_id,
                    prescription_id=prescription.id,
                    prescription_item_id=item.id,
                    rule_id=rule.id,
                    rule_code=rule.rule_code,
                    severity=rule.severity,
                    message=msg,
                    clinical_evidence=f'Regimen: {item.dose}{item.dose_unit or "mg"} x {item.frequency_per_day}/day x {item.duration_days} days. Indication: {item.indication}',
                    status='OPEN',
                )
                db.add(alert)
                generated_alerts.append(alert)

            # 2. Duration Check
            if rule.max_duration_days and item.duration_days > rule.max_duration_days:
                alert_id = f'ALT-{secrets.token_hex(6).upper()}'
                msg = f'Prescribed duration of {item.duration_days} days exceeds the recommended ceiling of {rule.max_duration_days} days for {antibiotic.generic_name}.'
                alert = StewardshipAlert(
                    alert_id=alert_id,
                    prescription_id=prescription.id,
                    prescription_item_id=item.id,
                    rule_id=rule.id,
                    rule_code=rule.rule_code,
                    severity=rule.severity,
                    message=msg,
                    clinical_evidence=f'Indication: {item.indication}. Rationale: {rule.clinical_rationale}',
                    status='OPEN',
                )
                db.add(alert)
                generated_alerts.append(alert)

    if auto_commit and generated_alerts:
        db.commit()
    return generated_alerts


def record_alert_disposition(
    db: Session,
    alert_id: str,
    outcome: str,  # ACCEPTED, MODIFIED, OVERRIDDEN_WITH_REASON, FALSE_POSITIVE_FLAGGED
    reason: str,
    user_id: int | None = None,
) -> StewardshipAlert:
    """Records clinician or stewardship officer review disposition on an active alert."""
    alert = db.scalar(select(StewardshipAlert).where(StewardshipAlert.alert_id == alert_id))
    if not alert:
        raise ValueError(f'Alert {alert_id} not found')

    alert.disposition_outcome = outcome
    alert.disposition_reason = reason.strip()
    alert.disposition_user_id = user_id
    alert.disposition_at = datetime.now(UTC)

    if outcome == 'ACCEPTED':
        alert.status = 'RESOLVED'
    elif outcome == 'OVERRIDDEN_WITH_REASON':
        alert.status = 'OVERRIDDEN'
    elif outcome == 'FALSE_POSITIVE_FLAGGED':
        alert.status = 'FALSE_POSITIVE'
    else:
        alert.status = 'ACKNOWLEDGED'

    db.commit()
    return alert
