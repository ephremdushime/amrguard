from contextvars import ContextVar
import json
from typing import Any
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.models.core import AuditEvent

correlation_id_ctx: ContextVar[str | None] = ContextVar('amrguard_correlation_id', default=None)

SENSITIVE_DETAIL_KEYS = frozenset(
    {
        'password',
        'password_hash',
        'otp',
        'qr_token',
        'token',
        'access_token',
        'refresh_token',
        'secret',
        'api_key',
        'authorization',
        'csrf_token',
        'phone_number',
    }
)


def _sanitize_details(details: dict[str, Any] | None) -> dict[str, Any]:
    if not details:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in details.items():
        if key.lower() in SENSITIVE_DETAIL_KEYS:
            sanitized[key] = '[REDACTED]'
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_details(value)
        else:
            sanitized[key] = value
    return sanitized


def record_audit(
    db: Session,
    event_type: str,
    entity_type: str,
    entity_id: Any,
    source_system: str,
    *,
    actor_type: str = 'SYSTEM',
    actor_id: str | None = None,
    facility_id: int | None = None,
    pharmacy_id: int | None = None,
    outcome: str = 'SUCCESS',
    details: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    entry = AuditEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id),
        source_system=source_system,
        actor_type=actor_type,
        actor_id=actor_id,
        facility_id=facility_id,
        pharmacy_id=pharmacy_id,
        correlation_id=correlation_id or correlation_id_ctx.get(),
        outcome=outcome,
        details=json.dumps(_sanitize_details(details), default=str),
    )
    db.add(entry)
    return entry


@event.listens_for(AuditEvent, 'before_update')
def _prevent_audit_event_update(mapper, connection, target):
    raise PermissionError('AuditEvent records are append-only and cannot be modified')


@event.listens_for(AuditEvent, 'before_delete')
def _prevent_audit_event_delete(mapper, connection, target):
    raise PermissionError('AuditEvent records are append-only and cannot be deleted')
