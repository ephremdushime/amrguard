"""Stewardship Metric Dictionary & Governed Analytics Service.

Defines authoritative metric dictionary, evaluates clinical KPIs against source data,
applies minimum-cell privacy suppression (<5 counts), and attaches data quality caveats.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import (
    DispensingTransaction,
    MetricDefinition,
    Prescription,
    PrescriptionItem,
    StewardshipReview,
)
from app.services.aware import calculate_aware_breakdown

UTC = timezone.utc

DEFAULT_METRIC_DEFINITIONS: list[dict] = [
    {
        'metric_code': 'AWARE_ACCESS_PCT',
        'name': 'WHO Access Group Utilization Percentage',
        'category': 'AWARE_UTILIZATION',
        'description': 'Proportion of antibiotic orders belonging to the WHO Access group.',
        'numerator_definition': 'Count of prescribed items classified under WHO Access group.',
        'denominator_definition': 'Total count of prescribed antibiotic items with valid classification.',
        'calculation_formula': '(Access Items / Total Evaluated Items) * 100',
        'target_benchmark': '>= 60%',
        'minimum_cell_threshold': 5,
        'effective_from': date(2023, 1, 1),
        'version': '1.0',
    },
    {
        'metric_code': 'RX_DISPENSE_RECON_RATE',
        'name': 'Prescription-to-Dispense Reconciliation Rate',
        'category': 'DISPENSING_FIDELITY',
        'description': 'Percentage of active prescriptions reconciled to at least one verified pharmacy dispense event.',
        'numerator_definition': 'Count of distinct prescriptions linked to at least one valid DispensingTransaction.',
        'denominator_definition': 'Total count of active, completed, or validated prescriptions.',
        'calculation_formula': '(Reconciled Prescriptions / Total Prescriptions) * 100',
        'target_benchmark': '>= 85%',
        'minimum_cell_threshold': 5,
        'effective_from': date(2024, 1, 1),
        'version': '1.0',
    },
    {
        'metric_code': 'STEWARDSHIP_REVIEW_RATE',
        'name': 'Post-Dispense Stewardship Review Completion Rate',
        'category': 'STEWARDSHIP_TIMELINESS',
        'description': 'Proportion of scheduled clinical stewardship reviews completed with documented rationale.',
        'numerator_definition': 'Count of stewardship reviews with status=COMPLETED.',
        'denominator_definition': 'Total count of scheduled stewardship reviews.',
        'calculation_formula': '(Completed Reviews / Total Reviews) * 100',
        'target_benchmark': '>= 90%',
        'minimum_cell_threshold': 5,
        'effective_from': date(2024, 1, 1),
        'version': '1.0',
    },
    {
        'metric_code': 'QUANTITY_DISCREPANCY_RATE',
        'name': 'Regimen Quantity Discrepancy Rate',
        'category': 'PRESCRIBING_SAFETY',
        'description': 'Percentage of submitted prescription orders blocked or flagged for quantity-versus-regimen mismatches.',
        'numerator_definition': 'Count of prescriptions with status=BLOCKED or review-required issues.',
        'denominator_definition': 'Total submitted prescriptions.',
        'calculation_formula': '(Flagged Orders / Total Submitted Orders) * 100',
        'target_benchmark': '< 5%',
        'minimum_cell_threshold': 5,
        'effective_from': date(2024, 1, 1),
        'version': '1.0',
    },
    {
        'metric_code': 'TOTAL_ESTIMATED_DOT',
        'name': 'Estimated Total Days of Therapy (DOT)',
        'category': 'AWARE_UTILIZATION',
        'description': 'Aggregate estimated days of antibiotic therapy across authorized prescriptions.',
        'numerator_definition': 'Sum of duration_days across authorized prescription items.',
        'denominator_definition': 'N/A (Aggregate Count)',
        'calculation_formula': 'Sum(duration_days)',
        'target_benchmark': 'Baseline Surveillance',
        'minimum_cell_threshold': 5,
        'effective_from': date(2024, 1, 1),
        'version': '1.0',
    },
]

DATA_QUALITY_CAVEATS: list[str] = [
    'Operational surveillance data: not certified national epidemiology statistics.',
    'Minimum-cell suppression (< 5 counts) is applied to prevent patient re-identification in small cohorts.',
    'Data coverage reflects participating pilot facilities with active partner adapters.',
    'Days of Therapy (DOT) is estimated from authorized prescription duration; actual patient adherence is not tracked.',
]


def seed_metric_definitions(db: Session) -> int:
    """Populates baseline metric dictionary definitions if absent."""
    seeded = 0
    for m in DEFAULT_METRIC_DEFINITIONS:
        existing = db.scalar(select(MetricDefinition).where(MetricDefinition.metric_code == m['metric_code']))
        if not existing:
            db.add(
                MetricDefinition(
                    metric_code=m['metric_code'],
                    name=m['name'],
                    category=m['category'],
                    description=m['description'],
                    numerator_definition=m['numerator_definition'],
                    denominator_definition=m['denominator_definition'],
                    calculation_formula=m['calculation_formula'],
                    target_benchmark=m.get('target_benchmark'),
                    minimum_cell_threshold=m.get('minimum_cell_threshold', 5),
                    effective_from=m['effective_from'],
                    version=m.get('version', '1.0'),
                )
            )
            seeded += 1
    if seeded > 0:
        db.commit()
    return seeded


def get_all_metric_definitions(db: Session) -> list[MetricDefinition]:
    """Retrieves all registered metric definitions."""
    return list(db.scalars(select(MetricDefinition).order_by(MetricDefinition.id.asc())).all())


def evaluate_governed_metrics(
    db: Session,
    facility_id: int | None = None,
    minimum_cell_threshold: int = 5,
) -> dict[str, Any]:
    """Evaluates all registered stewardship metrics against operational database records."""
    # Ensure definitions are seeded
    seed_metric_definitions(db)

    # 1. Base counts
    rx_query = select(Prescription)
    if facility_id:
        rx_query = rx_query.where(Prescription.facility_id == facility_id)
    all_rx = list(db.scalars(rx_query).all())
    total_rx = len(all_rx)
    active_or_validated_rx = [r for r in all_rx if r.status in ('VALIDATED', 'ACTIVE', 'PARTIALLY_DISPENSED', 'COMPLETED')]
    blocked_rx = [r for r in all_rx if r.status == 'BLOCKED']

    # 2. Reconciled dispenses
    tx_query = select(func.count(func.distinct(DispensingTransaction.prescription_id)))
    if facility_id:
        tx_query = tx_query.where(DispensingTransaction.prescribing_facility_id == facility_id)
    reconciled_rx_count = db.scalar(tx_query) or 0

    # 3. Stewardship reviews
    rev_query = select(StewardshipReview)
    if facility_id:
        rev_query = rev_query.join(Prescription, StewardshipReview.prescription_id == Prescription.id).where(
            Prescription.facility_id == facility_id
        )
    all_reviews = list(db.scalars(rev_query).all())
    total_reviews = len(all_reviews)
    completed_reviews = len([r for r in all_reviews if r.status == 'COMPLETED'])
    pending_reviews = len([r for r in all_reviews if r.status == 'PENDING'])

    # 4. Total Days of Therapy (DOT)
    dot_query = select(func.coalesce(func.sum(PrescriptionItem.duration_days), 0))
    if facility_id:
        dot_query = dot_query.join(Prescription, PrescriptionItem.prescription_id == Prescription.id).where(
            Prescription.facility_id == facility_id
        )
    total_dot = int(db.scalar(dot_query) or 0)

    # 5. AWaRe breakdown
    aware_data = calculate_aware_breakdown(db, facility_id=facility_id, minimum_cell_threshold=minimum_cell_threshold)

    # Rates
    recon_rate = round((reconciled_rx_count / max(len(active_or_validated_rx), 1)) * 100, 1)
    review_rate = round((completed_reviews / max(total_reviews, 1)) * 100, 1)
    discrepancy_rate = round((len(blocked_rx) / max(total_rx, 1)) * 100, 1)

    # Apply cell suppression to small numbers
    def suppress_if_small(val: int) -> dict:
        if 0 < val < minimum_cell_threshold:
            return {'value': None, 'display': f'<{minimum_cell_threshold}', 'suppressed': True}
        return {'value': val, 'display': str(val), 'suppressed': False}

    evaluated_metrics = [
        {
            'metric_code': 'AWARE_ACCESS_PCT',
            'name': 'WHO Access Group Utilization Percentage',
            'category': 'AWARE_UTILIZATION',
            'value': aware_data['access_percentage'],
            'unit': '%',
            'target_benchmark': '>= 60%',
            'benchmark_met': aware_data['meets_who_access_target'],
            'numerator': aware_data['access_count'],
            'denominator': aware_data['total_orders'],
        },
        {
            'metric_code': 'RX_DISPENSE_RECON_RATE',
            'name': 'Prescription-to-Dispense Reconciliation Rate',
            'category': 'DISPENSING_FIDELITY',
            'value': recon_rate,
            'unit': '%',
            'target_benchmark': '>= 85%',
            'benchmark_met': recon_rate >= 85.0,
            'numerator': reconciled_rx_count,
            'denominator': len(active_or_validated_rx),
        },
        {
            'metric_code': 'STEWARDSHIP_REVIEW_RATE',
            'name': 'Post-Dispense Stewardship Review Completion Rate',
            'category': 'STEWARDSHIP_TIMELINESS',
            'value': review_rate,
            'unit': '%',
            'target_benchmark': '>= 90%',
            'benchmark_met': review_rate >= 90.0,
            'numerator': completed_reviews,
            'denominator': total_reviews,
        },
        {
            'metric_code': 'QUANTITY_DISCREPANCY_RATE',
            'name': 'Regimen Quantity Discrepancy Rate',
            'category': 'PRESCRIBING_SAFETY',
            'value': discrepancy_rate,
            'unit': '%',
            'target_benchmark': '< 5%',
            'benchmark_met': discrepancy_rate < 5.0,
            'numerator': len(blocked_rx),
            'denominator': total_rx,
        },
        {
            'metric_code': 'TOTAL_ESTIMATED_DOT',
            'name': 'Estimated Total Days of Therapy (DOT)',
            'category': 'AWARE_UTILIZATION',
            'value': total_dot,
            'unit': 'days',
            'target_benchmark': 'Surveillance Baseline',
            'benchmark_met': True,
            'numerator': total_dot,
            'denominator': None,
        },
    ]

    return {
        'facility_id': facility_id,
        'evaluated_at': datetime.now(UTC).isoformat(),
        'metrics': evaluated_metrics,
        'counts': {
            'total_prescriptions': total_rx,
            'active_or_validated': len(active_or_validated_rx),
            'reconciled_dispenses': suppress_if_small(reconciled_rx_count),
            'pending_reviews': suppress_if_small(pending_reviews),
            'completed_reviews': suppress_if_small(completed_reviews),
            'blocked_orders': suppress_if_small(len(blocked_rx)),
        },
        'aware_breakdown': aware_data,
        'data_quality_caveats': DATA_QUALITY_CAVEATS,
    }
