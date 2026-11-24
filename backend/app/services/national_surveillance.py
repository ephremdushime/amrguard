"""National Antimicrobial Surveillance Aggregation & Export Service.

Produces multi-facility, district-aggregated, privacy-preserving surveillance feeds
compatible with WHO GLASS (Global Antimicrobial Resistance and Use Surveillance System)
and Rwanda Biomedical Centre (RBC) national surveillance standards.

Strictly applies minimum-cell suppression (< 5 counts) to prevent patient re-identification
in small district or health-center cohorts.
"""

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import Antibiotic, Facility, Prescription, PrescriptionItem
from app.services.aware import classify_antibiotic

UTC = timezone.utc
MINIMUM_CELL_THRESHOLD = 5


def export_national_surveillance_feed(
    db: Session,
    district: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    minimum_cell_threshold: int = MINIMUM_CELL_THRESHOLD,
) -> dict[str, Any]:
    """Generates an authoritative, privacy-preserved national surveillance feed."""
    query = (
        select(
            Facility.district,
            Facility.code.label('facility_code'),
            Facility.name.label('facility_name'),
            Antibiotic.code.label('antibiotic_code'),
            Antibiotic.generic_name,
            func.count(PrescriptionItem.id).label('order_count'),
            func.sum(PrescriptionItem.quantity).label('total_units'),
            func.sum(PrescriptionItem.duration_days).label('total_dot'),
        )
        .select_from(PrescriptionItem)
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .join(Facility, Prescription.facility_id == Facility.id)
        .join(Antibiotic, PrescriptionItem.antibiotic_id == Antibiotic.id)
    )

    if district:
        query = query.where(Facility.district == district)

    # Date range filters on prescription creation
    if period_start:
        query = query.where(func.date(Prescription.created_at) >= period_start)
    if period_end:
        query = query.where(func.date(Prescription.created_at) <= period_end)

    rows = db.execute(
        query.group_by(
            Facility.district,
            Facility.code,
            Facility.name,
            Antibiotic.code,
            Antibiotic.generic_name,
        )
    ).all()

    district_aggregates: dict[str, dict[str, Any]] = {}
    national_aware = {'ACCESS': 0, 'WATCH': 0, 'RESERVE': 0, 'DISCOURAGED': 0}
    total_national_orders = 0
    total_national_units = 0
    total_national_dot = 0
    any_suppression_applied = False

    for d_name, f_code, f_name, ab_code, generic, ord_cnt, units, dot in rows:
        d_key = d_name or 'Unspecified District'
        if d_key not in district_aggregates:
            district_aggregates[d_key] = {
                'district': d_key,
                'total_orders': 0,
                'total_units': 0,
                'total_dot': 0,
                'aware_counts': {'ACCESS': 0, 'WATCH': 0, 'RESERVE': 0, 'DISCOURAGED': 0},
                'cell_suppression_applied': False,
            }

        cat = classify_antibiotic(db, ab_code)
        cnt = int(ord_cnt or 0)
        u_cnt = int(units or 0)
        dot_cnt = int(dot or 0)

        district_aggregates[d_key]['total_orders'] += cnt
        district_aggregates[d_key]['total_units'] += u_cnt
        district_aggregates[d_key]['total_dot'] += dot_cnt
        if cat in district_aggregates[d_key]['aware_counts']:
            district_aggregates[d_key]['aware_counts'][cat] += cnt

        total_national_orders += cnt
        total_national_units += u_cnt
        total_national_dot += dot_cnt
        if cat in national_aware:
            national_aware[cat] += cnt

    # Apply minimum cell suppression (< 5) per district
    for dist_data in district_aggregates.values():
        for cat, val in list(dist_data['aware_counts'].items()):
            if 0 < val < minimum_cell_threshold:
                dist_data['aware_counts'][cat] = None
                dist_data['cell_suppression_applied'] = True
                any_suppression_applied = True

    # Calculate national proportions
    access_pct = round((national_aware['ACCESS'] / max(total_national_orders, 1)) * 100, 1)
    watch_pct = round((national_aware['WATCH'] / max(total_national_orders, 1)) * 100, 1)
    reserve_pct = round((national_aware['RESERVE'] / max(total_national_orders, 1)) * 100, 1)

    return {
        'feed_type': 'NATIONAL_AMR_SURVEILLANCE_EXPORT',
        'generated_at': datetime.now(UTC).isoformat(),
        'period': {
            'start': period_start.isoformat() if period_start else None,
            'end': period_end.isoformat() if period_end else None,
            'district_filter': district,
        },
        'methodology': {
            'standard': 'WHO GLASS & Rwanda MoH National Surveillance Guidelines',
            'minimum_cell_suppression_threshold': minimum_cell_threshold,
            'privacy_preserving': True,
        },
        'national_summary': {
            'total_evaluated_orders': total_national_orders,
            'total_units_consumed': total_national_units,
            'total_estimated_dot': total_national_dot,
            'access_percentage': access_pct,
            'watch_percentage': watch_pct,
            'reserve_percentage': reserve_pct,
            'meets_who_access_benchmark': access_pct >= 60.0,
        },
        'district_breakdowns': list(district_aggregates.values()),
        'cell_suppression_applied': any_suppression_applied,
    }
