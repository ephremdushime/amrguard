"""Prometheus and OpenTelemetry-compatible Observability Service.

Gathers real-time operational telemetry across dispensing throughput,
partner outbox queue lag, dead letters, stock levels, and security audit events.
Outputs standard OpenMetrics / Prometheus text exposition format.
"""

from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import (
    AuditEvent,
    DispensingTransaction,
    IntegrationOutbox,
    Pharmacy,
    Prescription,
    StockBatch,
)


def gather_system_metrics(db: Session) -> dict[str, Any]:
    """Retrieves operational telemetry for dashboards and monitoring aggregators."""
    prescriptions_total = db.scalar(select(func.count()).select_from(Prescription)) or 0
    dispenses_total = db.scalar(select(func.count()).select_from(DispensingTransaction)) or 0
    active_batches = db.scalar(select(func.count()).select_from(StockBatch).where(StockBatch.quantity_available > 0)) or 0

    outbox_pending = (
        db.scalar(select(func.count()).select_from(IntegrationOutbox).where(IntegrationOutbox.status == 'PENDING')) or 0
    )
    outbox_dead_letter = (
        db.scalar(select(func.count()).select_from(IntegrationOutbox).where(IntegrationOutbox.status == 'DEAD_LETTER')) or 0
    )

    auth_failures = (
        db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type.in_(['LOGIN_FAILED', 'AUTHZ_DENIED', 'CREDENTIAL_REJECTED']))
        )
        or 0
    )

    active_pharmacies = db.scalar(select(func.count()).select_from(Pharmacy).where(Pharmacy.active.is_(True))) or 0

    return {
        'prescriptions_total': prescriptions_total,
        'dispenses_total': dispenses_total,
        'active_batches': active_batches,
        'outbox_pending': outbox_pending,
        'outbox_dead_letter': outbox_dead_letter,
        'auth_failures_total': auth_failures,
        'active_pharmacies': active_pharmacies,
    }


def render_prometheus_metrics(db: Session) -> str:
    """Formats metrics in standard Prometheus / OpenMetrics text exposition format."""
    data = gather_system_metrics(db)
    lines = [
        '# HELP amrguard_prescriptions_total Total prescriptions recorded in AMRGuard',
        '# TYPE amrguard_prescriptions_total counter',
        f'amrguard_prescriptions_total {data["prescriptions_total"]}',
        '',
        '# HELP amrguard_dispenses_total Total atomic dispensing transactions completed',
        '# TYPE amrguard_dispenses_total counter',
        f'amrguard_dispenses_total {data["dispenses_total"]}',
        '',
        '# HELP amrguard_active_stock_batches Current count of stock batches with available quantity > 0',
        '# TYPE amrguard_active_stock_batches gauge',
        f'amrguard_active_stock_batches {data["active_batches"]}',
        '',
        '# HELP amrguard_outbox_queue_depth Pending partner reconciliation messages waiting for dispatch lease',
        '# TYPE amrguard_outbox_queue_depth gauge',
        f'amrguard_outbox_queue_depth {data["outbox_pending"]}',
        '',
        '# HELP amrguard_outbox_dead_letter_total Total partner outbox messages in dead-letter state',
        '# TYPE amrguard_outbox_dead_letter_total counter',
        f'amrguard_outbox_dead_letter_total {data["outbox_dead_letter"]}',
        '',
        '# HELP amrguard_security_auth_failures_total Total authentication and authorization failure audit events',
        '# TYPE amrguard_security_auth_failures_total counter',
        f'amrguard_security_auth_failures_total {data["auth_failures_total"]}',
        '',
        '# HELP amrguard_active_pharmacies_total Connected operational pharmacies',
        '# TYPE amrguard_active_pharmacies_total gauge',
        f'amrguard_active_pharmacies_total {data["active_pharmacies"]}',
        '',
    ]
    return '\n'.join(lines)
