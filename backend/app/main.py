from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
from uuid import uuid4

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, inspect, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth_routes import router as auth_router
from app.core.auth import (
    Principal,
    require_authenticated_principal,
    require_human_user,
)
from app.core.authz import (
    ROLE_FACILITY_ADMIN,
    ROLE_NATIONAL_ANALYST,
    ROLE_PHARMACIST,
    ROLE_PHARMACY_ASSISTANT,
    ROLE_PLATFORM_OPERATOR,
    ROLE_PRESCRIBER,
    ROLE_STEWARDSHIP_OFFICER,
    SCOPE_DISPENSING_READ,
    SCOPE_EBUZIMA_CRED_WRITE,
    SCOPE_EBUZIMA_RX_READ,
    SCOPE_EBUZIMA_RX_WRITE,
    SCOPE_RMS_STOCK_WRITE,
    SCOPE_SMS_CALLBACK,
    SCOPE_SMS_DISPATCH,
    SCOPE_SMS_INBOUND,
    SCOPE_OUTBOX_DISPATCH,
    SCOPE_STEWARDSHIP_SUPPORT_READ,
    audit_authz_denied,
    authorized_facility_ids_for_human,
    authorized_pharmacy_ids_for_human,
    evaluate_prescription_dispensing_authorization,
    evaluate_verification_authorization,
    has_national_aggregate_scope,
    has_platform_operator_scope,
    require_human_roles,
    require_service_scope,
    service_client_allows_facility,
    service_client_allows_pharmacy,
    service_client_has_scope,
)
from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.db.seed import seed_demo, seed_roles
from app.db.session import Base, engine, get_db
from app.models.core import (
    Antibiotic,
    AntibioticRule,
    AuditEvent,
    ConsentRecord,
    DispensingBatchLink,
    DispensingItem,
    DispensingTransaction,
    Facility,
    Formulation,
    IntegrationInbox,
    IntegrationOutbox,
    MedicineConcept,
    MedicineMapping,
    MessageDeliveryEvent,
    MessageOutbox,
    Pharmacy,
    Prescriber,
    Prescription,
    PrescriptionCredential,
    PrescriptionItem,
    ReminderOccurrence,
    ReminderSchedule,
    StewardshipReminder,
    StewardshipReview,
    StockBatch,
    StockEvent,
    WhoAwareClassification,
    MetricDefinition,
    GovernedStewardshipRule,
    StewardshipAlert,
)
from app.schemas.demo import DemoPrescriptionCreate
from app.schemas.prescriptions import (
    BatchAllocation,
    ConsentCreateRequest,
    ConsentResponse,
    ConsentWithdrawRequest,
    CredentialResponse,
    DeliveryCallbackRequest,
    DispatchBatchRequest,
    DispenseRequest,
    InboundSmsRequest,
    MedicineMappingCreate,
    OutboxDispatchResponse,
    OutboxItemResponse,
    PrescriptionIn,
    PrescriptionResponse,
    QuarantineResolveRequest,
    ReminderOccurrenceResponse,
    ReminderScheduleCreateRequest,
    ReminderScheduleResponse,
    RmsStockEventRequest,
    StewardshipReminderRequest,
    StewardshipReviewRequest,
    StewardshipSupportRequest,
    ValidationIssue,
    VerificationRequest,
    AlertDispositionRequest,
    GovernedMetricsResponse,
    MetricDefinitionResponse,
    StewardshipAlertResponse,
    StewardshipRuleResponse,
    WhoAwareClassificationResponse,
    AIAssistanceRequest,
    AIAssistanceResponse,
)
from app.services.audit import correlation_id_ctx, record_audit
from app.services.consent import (
    capture_consent,
    handle_inbound_opt_out,
    mask_phone_number,
    verify_active_consent,
    withdraw_consent,
)
from app.services.fhir import dispensing_to_medication_dispense, prescription_to_medication_request
from app.services.reminders import (
    create_dose_reminder_schedule,
    dispatch_reminders_batch,
    record_delivery_receipt,
)
from app.adapters import (
    EBuzimaAdapter,
    RMSAdapter,
    UnmappedCodeError,
    process_integration_outbox_batch,
    retry_dead_letter,
)
from app.services.aware import (
    calculate_aware_breakdown,
    classify_antibiotic,
    seed_who_aware_classifications,
)
from app.services.metrics import (
    evaluate_governed_metrics,
    seed_metric_definitions,
)
from app.services.rules_engine import (
    evaluate_prescription_rules,
    get_active_rules,
    record_alert_disposition,
    seed_governed_rules,
)
from app.services.ai_assistance import (
    explain_prescription_validation,
    explain_stewardship_alert,
    summarize_stewardship_trends,
)
from app.services.security import keyed_digest
from app.services.validation import validate_item

API_VERSION = 'v1'
APP_VERSION = '0.7.0'

TECHNICAL_AUDIT_ENTITY_TYPES = frozenset(
    {'Authentication', 'ServiceClient', 'ServiceClientCredential', 'UserSession', 'Endpoint'}
)


@asynccontextmanager
async def lifespan(app):
    if settings.app_env == 'funder_demo':
        db = next(get_db())
        try:
            seed_demo(db)
            yield
        finally:
            db.close()
        return
    if settings.app_env in {'demo', 'development', 'test'}:
        db = next(get_db())
        try:
            if not settings.database_url.startswith('sqlite') or settings.database_url.endswith('test_amrguard.db'):
                seed_demo(db)
            else:
                seed_roles(db)
                db.commit()
            yield
        finally:
            db.close()
    else:
        db = next(get_db())
        try:
            seed_roles(db)
            db.commit()
            yield
        finally:
            db.close()


app = FastAPI(
    title='AMRGuard API',
    version=APP_VERSION,
    description='Antibiotic-specific interoperability and transaction layer. Production connectors are implemented through approved adapters.',
    docs_url='/docs' if settings.effective_enable_api_docs else None,
    redoc_url='/redoc' if settings.effective_enable_api_docs else None,
    openapi_url='/openapi.json' if settings.effective_enable_api_docs else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in settings.allowed_origins.split(',') if x.strip()],
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
    allow_headers=[
        'Authorization',
        'Content-Type',
        'X-CSRF-Token',
        'X-Request-ID',
        'x-amrguard-integration-key',
    ],
)

app.include_router(auth_router)

# Local demo databases are bootstrapped for convenience. Hosted modes are migrated by Alembic at container startup.
if settings.app_env in {'demo', 'development', 'test', 'funder_demo'}:
    inspector = inspect(engine)
    if inspector.has_table('alembic_version'):
        migration_config = AlembicConfig(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
        migration_config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'alembic'))
        alembic_command.upgrade(migration_config, 'head')
    elif inspector.has_table('facilities'):
        if settings.app_env == 'funder_demo':
            raise RuntimeError('Funder demo database is unversioned. Use a fresh dedicated funder demo database.')
    else:
        Base.metadata.create_all(bind=engine)


def utcnow():
    return datetime.now(timezone.utc)


def is_expired(value):
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= utcnow()


def audit(
    db: Session,
    event: str,
    entity: str,
    entity_id,
    source: str,
    details=None,
    *,
    principal: Principal | None = None,
    facility_id: int | None = None,
    pharmacy_id: int | None = None,
    outcome: str = 'SUCCESS',
):
    actor_type = principal.actor_type if principal else 'SYSTEM'
    actor_id = principal.actor_id if principal else None
    return record_audit(
        db,
        event,
        entity,
        entity_id,
        source,
        actor_type=actor_type,
        actor_id=actor_id,
        facility_id=facility_id,
        pharmacy_id=pharmacy_id,
        outcome=outcome,
        details=details or {},
    )


def rx_view(rx, issues):
    return PrescriptionResponse(
        id=rx.id,
        external_id=rx.external_id,
        status=rx.status,
        issues=[ValidationIssue(**i) for i in issues],
    )


def prescription_detail(rx, db):
    items = []
    for item in rx.items:
        ab = db.get(Antibiotic, item.antibiotic_id)
        items.append(
            {
                'id': item.id,
                'antibiotic': ab.generic_name,
                'code': ab.code,
                'strength': ab.strength,
                'formulation': ab.formulation,
                'route': ab.route,
                'dose': str(item.dose),
                'frequency_per_day': str(item.frequency_per_day),
                'duration_days': item.duration_days,
                'authorized_quantity': item.quantity,
                'indication': item.indication,
            }
        )
    pr = db.get(Prescriber, rx.prescriber_id)
    fac = db.get(Facility, rx.facility_id)
    return {
        'id': rx.id,
        'code': f'AMR-RX-{rx.id:06d}',
        'external_id': rx.external_id,
        'status': rx.status,
        'allow_external_dispensing': bool(rx.allow_external_dispensing),
        'prescriber': {'id': pr.external_user_id, 'name': pr.name},
        'facility': {'id': fac.id, 'code': fac.code, 'name': fac.name},
        'patient_reference': rx.patient_reference,
        'created_at': rx.created_at,
        'expires_at': rx.expires_at,
        'items': items,
    }


@app.middleware('http')
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get('X-Request-ID') or str(uuid4())
    token = correlation_id_ctx.set(request_id)
    try:
        response = await call_next(request)
        response.headers['X-Request-ID'] = request_id
        return response
    finally:
        correlation_id_ctx.reset(token)


@app.get('/health')
def health():
    payload = {'status': 'ok', 'service': 'AMRGuard', 'version': APP_VERSION}
    if settings.app_env.lower() != 'production':
        payload['environment'] = settings.app_env
    return payload


@app.get('/health/ready')
def readiness(db: Session = Depends(get_db)):
    try:
        db.execute(select(1))
    except Exception as exc:
        raise HTTPException(status_code=503, detail='Database unavailable') from exc
    return {'status': 'ready', 'service': 'AMRGuard'}


@app.get('/api/v1/meta')
def meta(_principal: Principal = Depends(require_authenticated_principal)):
    return {
        'name': 'AMRGuard',
        'version': APP_VERSION,
        'api_version': API_VERSION,
        'integration_mode': 'adapter-ready',
        'demo_data': settings.app_env in {'demo', 'funder_demo'},
        'standards': 'REST/OpenAPI; FHIR-compatible mapping layer',
        'auth_mode': settings.effective_auth_mode,
        'cross_facility_dispensing_enabled': settings.cross_facility_dispensing_enabled,
    }


@app.post('/api/v1/stewardship/support')
def stewardship_support(
    payload: StewardshipSupportRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_authenticated_principal),
):
    """Return an embeddable, non-prescriptive stewardship review for a source EMR.

    Local antibiotic rules must be governed and approved before they are treated as
    clinical guidance. This endpoint reports deterministic checks only.
    """
    if principal.actor_type == 'HUMAN':
        allowed_roles = {ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER}
        if not (principal.roles & allowed_roles):
            audit_authz_denied(
                db,
                principal,
                action='stewardship_support',
                entity_type='StewardshipSupport',
                entity_id=payload.antibiotic_code,
                reason='missing_required_role',
            )
            raise HTTPException(status_code=403, detail='Insufficient role privileges')
    elif not service_client_has_scope(principal, SCOPE_STEWARDSHIP_SUPPORT_READ):
        audit_authz_denied(
            db,
            principal,
            action='stewardship_support',
            entity_type='StewardshipSupport',
            entity_id=payload.antibiotic_code,
            reason='missing_service_scope',
        )
        raise HTTPException(status_code=403, detail='Service client lacks stewardship support scope')

    expected = payload.frequency_per_day * payload.duration_days
    issues = []
    mismatch = expected != int(expected) or payload.quantity != int(expected)
    if mismatch:
        issues.append(
            {
                'code': 'QUANTITY_MISMATCH',
                'severity': 'BLOCK',
                'message': f'Entered quantity {payload.quantity} differs from administrations/day × duration ({expected}).',
            }
        )
    antibiotic = db.scalar(select(Antibiotic).where(Antibiotic.code == payload.antibiotic_code))
    category = classify_antibiotic(db, payload.antibiotic_code)
    if antibiotic:
        demo_rule = db.scalar(
            select(AntibioticRule).where(
                AntibioticRule.antibiotic_id == antibiotic.id, AntibioticRule.enabled.is_(True)
            )
        )
        if demo_rule and demo_rule.source_reference.startswith('DEMO RULE'):
            issues.append(
                {
                    'code': 'DEMO_RULESET',
                    'severity': 'INFO',
                    'message': 'Illustrative demo rules are configured for this product; they are not approved prescribing guidance.',
                }
            )
    review_days = 3
    return {
        'decision': 'REVIEW_REQUIRED' if mismatch else 'CHECKS_PASSED',
        'issues': issues,
        'stewardship': {
            'aware_category': category,
            'review_prompt': f'Review clinical response and available results at approximately day {review_days}, according to local protocol.',
            'indication_captured': bool(payload.indication.strip()),
        },
        'display': {
            'message': 'Resolve the quantity discrepancy before continuing.'
            if mismatch
            else 'No configured transaction checks were triggered. Confirm clinical appropriateness using approved local guidance.',
            'severity': 'error' if mismatch else 'information',
        },
        'governance': {
            'clinical_recommendation': False,
            'ruleset': 'transaction checks only',
            'requires_local_guideline_review': True,
        },
    }


@app.post('/api/v1/integrations/ebuzima/prescriptions', response_model=PrescriptionResponse)
def receive_prescription(
    payload: PrescriptionIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_service_scope(SCOPE_EBUZIMA_RX_WRITE)),
):
    fac = db.scalar(select(Facility).where(Facility.code == payload.prescriber.facility_code, Facility.active.is_(True)))
    if not fac or not service_client_allows_facility(principal, SCOPE_EBUZIMA_RX_WRITE, fac.id):
        if not fac and settings.effective_quarantine_unmapped_codes:
            inbox_entry = IntegrationInbox(
                source_system=principal.service_client_code or 'e-Buzima',
                event_type='PRESCRIPTION',
                external_id=payload.external_id,
                payload=payload.model_dump_json(),
                quarantine_reason=f'Unknown facility code: {payload.prescriber.facility_code}',
                unresolved_code=payload.prescriber.facility_code,
                status='QUARANTINED',
            )
            db.add(inbox_entry)
            db.flush()
            audit(
                db,
                'INTEGRATION_EVENT_QUARANTINED',
                'IntegrationInbox',
                inbox_entry.id,
                principal.service_client_code or 'e-Buzima',
                {'external_id': payload.external_id, 'reason': inbox_entry.quarantine_reason},
                principal=principal,
            )
            db.commit()
            raise HTTPException(
                status_code=422,
                detail={
                    'message': f'Unknown facility code "{payload.prescriber.facility_code}" quarantined',
                    'quarantine_id': inbox_entry.id,
                    'status': 'QUARANTINED',
                },
            )
        audit_authz_denied(
            db,
            principal,
            action='ebuzima_prescription_ingest',
            entity_type='Facility',
            entity_id=payload.prescriber.facility_code,
            facility_id=fac.id if fac else None,
            reason='facility_not_provisioned_or_out_of_scope',
        )
        raise HTTPException(status_code=403, detail='Service client is not authorized for this facility')

    existing = db.scalar(select(Prescription).where(Prescription.external_id == payload.external_id))
    if existing:
        if existing.facility_id != fac.id:
            audit_authz_denied(
                db,
                principal,
                action='ebuzima_prescription_replay',
                entity_type='Prescription',
                entity_id=existing.id,
                facility_id=existing.facility_id,
                reason='external_id_cross_facility_conflict',
            )
            raise HTTPException(status_code=409, detail='External prescription ID belongs to another facility')
        return rx_view(existing, [])

    pr = db.scalar(select(Prescriber).where(Prescriber.external_user_id == payload.prescriber.external_user_id))
    if not pr:
        pr = Prescriber(
            external_user_id=payload.prescriber.external_user_id,
            name=payload.prescriber.name,
            facility_id=fac.id,
        )
        db.add(pr)
        db.flush()
    elif pr.facility_id != fac.id:
        if settings.effective_quarantine_unmapped_codes:
            inbox_entry = IntegrationInbox(
                source_system=principal.service_client_code or 'e-Buzima',
                event_type='PRESCRIPTION',
                external_id=payload.external_id,
                payload=payload.model_dump_json(),
                quarantine_reason=f'Prescriber {pr.external_user_id} facility mismatch',
                unresolved_code=payload.prescriber.facility_code,
                status='QUARANTINED',
                facility_id=fac.id,
            )
            db.add(inbox_entry)
            db.flush()
            audit(
                db,
                'INTEGRATION_EVENT_QUARANTINED',
                'IntegrationInbox',
                inbox_entry.id,
                principal.service_client_code or 'e-Buzima',
                {'external_id': payload.external_id, 'reason': inbox_entry.quarantine_reason},
                principal=principal,
                facility_id=fac.id,
            )
            db.commit()
            raise HTTPException(
                status_code=422,
                detail={
                    'message': f'Prescriber {pr.external_user_id} does not belong to requested facility',
                    'quarantine_id': inbox_entry.id,
                    'status': 'QUARANTINED',
                },
            )
        audit_authz_denied(
            db,
            principal,
            action='ebuzima_prescription_ingest',
            entity_type='Prescriber',
            entity_id=pr.id,
            facility_id=fac.id,
            reason='prescriber_facility_mismatch',
        )
        raise HTTPException(status_code=403, detail='Prescriber does not belong to the requested facility')

    rx = Prescription(
        external_id=payload.external_id,
        patient_reference=payload.patient_reference,
        prescriber_id=pr.id,
        facility_id=fac.id,
        allow_external_dispensing=bool(payload.allow_external_dispensing),
        expires_at=payload.expires_at,
    )
    db.add(rx)
    db.flush()

    issues = []
    for p in payload.items:
        ab = db.scalar(select(Antibiotic).where(Antibiotic.code == p.antibiotic_code))
        formulation = db.get(Formulation, p.formulation_id) if p.formulation_id else None

        if not ab:
            mapping = db.scalar(
                select(MedicineMapping).where(
                    MedicineMapping.source_code == p.antibiotic_code,
                    MedicineMapping.approval_status == 'APPROVED',
                    MedicineMapping.active.is_(True),
                )
            )
            if mapping:
                if mapping.formulation_id and not formulation:
                    formulation = db.get(Formulation, mapping.formulation_id)
                concept = db.get(MedicineConcept, mapping.medicine_concept_id) if mapping.medicine_concept_id else None
                if concept:
                    ab = db.scalar(select(Antibiotic).where(Antibiotic.code == concept.code))

            if not ab:
                if settings.effective_quarantine_unmapped_codes:
                    db.rollback()
                    inbox_entry = IntegrationInbox(
                        source_system=principal.service_client_code or 'e-Buzima',
                        event_type='PRESCRIPTION',
                        external_id=payload.external_id,
                        payload=payload.model_dump_json(),
                        quarantine_reason=f'Unknown antibiotic catalogue code: {p.antibiotic_code}',
                        unresolved_code=p.antibiotic_code,
                        status='QUARANTINED',
                        facility_id=fac.id,
                    )
                    db.add(inbox_entry)
                    db.flush()
                    audit(
                        db,
                        'INTEGRATION_EVENT_QUARANTINED',
                        'IntegrationInbox',
                        inbox_entry.id,
                        principal.service_client_code or 'e-Buzima',
                        {'external_id': payload.external_id, 'reason': inbox_entry.quarantine_reason},
                        principal=principal,
                        facility_id=fac.id,
                    )
                    db.commit()
                    raise HTTPException(
                        status_code=422,
                        detail={
                            'message': f'Unknown antibiotic catalogue code "{p.antibiotic_code}" requires approved mapping before ingestion',
                            'quarantine_id': inbox_entry.id,
                            'status': 'QUARANTINED',
                        },
                    )
                ab = Antibiotic(
                    code=p.antibiotic_code,
                    generic_name=p.generic_name,
                    strength=p.strength,
                    formulation=p.formulation,
                    route=p.route,
                )
                db.add(ab)
                db.flush()

        if not formulation and ab:
            concept = db.scalar(select(MedicineConcept).where(MedicineConcept.code == ab.code))
            if concept:
                formulation = db.scalar(
                    select(Formulation).where(
                        Formulation.medicine_concept_id == concept.id,
                        Formulation.active.is_(True),
                    )
                )

        rule = db.scalar(
            select(AntibioticRule).where(AntibioticRule.antibiotic_id == ab.id, AntibioticRule.enabled.is_(True))
        )
        item = PrescriptionItem(
            prescription_id=rx.id,
            antibiotic_id=ab.id,
            formulation_id=formulation.id if formulation else p.formulation_id,
            dose=p.dose,
            dose_unit=p.dose_unit,
            frequency_per_day=p.frequency_per_day,
            duration_days=p.duration_days,
            quantity=p.quantity,
            indication=p.indication,
            is_prn=p.is_prn,
            prn_reason=p.prn_reason,
            instructions=p.instructions,
        )
        db.add(item)
        db.flush()
        item_issues = validate_item(item, rule, formulation=formulation)
        if any(issue.get('code') == 'MANUAL_REVIEW_REQUIRED' for issue in item_issues):
            item.conversion_review_required = True
        issues += item_issues

    blocks = [i for i in issues if i['severity'] == 'BLOCK']
    rx.status = 'BLOCKED' if blocks else ('WARNING' if issues else 'VALIDATED')
    evaluate_prescription_rules(db, rx, auto_commit=False)
    audit(
        db,
        'PRESCRIPTION_RECEIVED',
        'Prescription',
        rx.id,
        principal.service_client_code or 'e-Buzima',
        {'external_id': rx.external_id, 'allow_external_dispensing': rx.allow_external_dispensing},
        principal=principal,
        facility_id=fac.id,
    )
    db.commit()
    return rx_view(rx, issues)


@app.post('/api/v1/integrations/ebuzima/fhir-bundle', response_model=PrescriptionResponse)
def receive_ebuzima_fhir_bundle(
    payload: dict,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_service_scope(SCOPE_EBUZIMA_RX_WRITE)),
):
    """Ingest a FHIR R4 Bundle containing MedicationRequest resources from e-Buzima."""
    adapter = EBuzimaAdapter()
    try:
        rx_in, _ = adapter.parse_prescription(payload, db)
    except UnmappedCodeError as exc:
        if settings.effective_quarantine_unmapped_codes:
            inbox_entry = IntegrationInbox(
                source_system=principal.service_client_code or 'e-Buzima',
                event_type='FHIR_BUNDLE',
                external_id=str(payload.get('id') or 'UNKNOWN_FHIR'),
                payload=json.dumps(payload),
                quarantine_reason=str(exc),
                unresolved_code=exc.code,
                status='QUARANTINED',
            )
            db.add(inbox_entry)
            db.flush()
            audit(
                db,
                'INTEGRATION_EVENT_QUARANTINED',
                'IntegrationInbox',
                inbox_entry.id,
                principal.service_client_code or 'e-Buzima',
                {'external_id': inbox_entry.external_id, 'reason': exc.details or str(exc)},
                principal=principal,
            )
            db.commit()
            raise HTTPException(
                status_code=422,
                detail={
                    'message': f'Unmapped code "{exc.code}" quarantined',
                    'quarantine_id': inbox_entry.id,
                    'status': 'QUARANTINED',
                },
            )
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f'FHIR bundle parsing error: {exc}')

    return receive_prescription(rx_in, db, principal)


@app.get('/api/v1/prescriptions/{prescription_id}')
def get_prescription(
    prescription_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(
        require_human_roles(
            ROLE_PRESCRIBER,
            ROLE_PHARMACIST,
            ROLE_PHARMACY_ASSISTANT,
            ROLE_STEWARDSHIP_OFFICER,
            ROLE_FACILITY_ADMIN,
        )
    ),
):
    rx = db.get(Prescription, prescription_id)
    if not rx:
        raise HTTPException(404, 'Prescription not found')
    allowed_facilities = authorized_facility_ids_for_human(
        principal,
        db,
        {ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_PHARMACY_ASSISTANT, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN},
    )
    if rx.facility_id not in allowed_facilities:
        audit_authz_denied(
            db,
            principal,
            action='read_prescription',
            entity_type='Prescription',
            entity_id=rx.id,
            facility_id=rx.facility_id,
            reason='cross_facility_read_denied',
        )
        raise HTTPException(403, 'Not authorized to access prescriptions for this facility')
    audit(
        db,
        'PRESCRIPTION_ACCESSED',
        'Prescription',
        rx.id,
        'AMRGuard',
        principal=principal,
        facility_id=rx.facility_id,
    )
    db.commit()
    return prescription_detail(rx, db)


def _generate_unique_otp(db: Session) -> tuple[str, str]:
    for _ in range(8):
        otp = f'{secrets.randbelow(1000000):06d}'
        otp_hash = keyed_digest(otp, purpose='rx_otp')
        collision = db.scalar(
            select(PrescriptionCredential.id).where(
                PrescriptionCredential.otp_hash == otp_hash,
                PrescriptionCredential.revoked.is_(False),
            )
        )
        if collision is None:
            return otp, otp_hash
    raise HTTPException(status_code=503, detail='Unable to allocate unique verification credential')


@app.post('/api/v1/prescriptions/{prescription_id}/credential', response_model=CredentialResponse)
def create_credential(
    prescription_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_authenticated_principal),
):
    rx = db.get(Prescription, prescription_id)
    if not rx:
        raise HTTPException(404, 'Prescription not found')

    if principal.actor_type == 'HUMAN':
        allowed_facilities = authorized_facility_ids_for_human(
            principal, db, {ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_FACILITY_ADMIN}
        )
        if rx.facility_id not in allowed_facilities:
            audit_authz_denied(
                db,
                principal,
                action='issue_credential',
                entity_type='Prescription',
                entity_id=rx.id,
                facility_id=rx.facility_id,
                reason='unauthorized_role_or_facility',
            )
            raise HTTPException(403, 'Not authorized to issue credentials for this prescription')
    elif not service_client_allows_facility(principal, SCOPE_EBUZIMA_CRED_WRITE, rx.facility_id):
        audit_authz_denied(
            db,
            principal,
            action='issue_credential',
            entity_type='Prescription',
            entity_id=rx.id,
            facility_id=rx.facility_id,
            reason='service_scope_or_facility_denied',
        )
        raise HTTPException(403, 'Service client not authorized to issue credentials for this facility')

    rate_key = f'cred_issue:{principal.actor_id}:{rx.id}'
    if not rate_limiter.check_and_record(
        rate_key,
        max_attempts=settings.credential_issue_rate_limit,
        window_seconds=settings.credential_issue_window_seconds,
    ):
        audit(
            db,
            'CREDENTIAL_ISSUANCE_RATE_LIMITED',
            'Prescription',
            rx.id,
            'AMRGuard',
            principal=principal,
            facility_id=rx.facility_id,
            outcome='DENIED',
        )
        db.commit()
        raise HTTPException(429, 'Credential issuance rate limit exceeded')

    if rx.status not in {'VALIDATED', 'WARNING', 'ACTIVE', 'PARTIALLY_DISPENSED'}:
        raise HTTPException(409, f'Prescription is {rx.status}')
    if rx.expires_at and is_expired(rx.expires_at):
        rx.status = 'EXPIRED'
        audit(
            db,
            'PRESCRIPTION_EXPIRED',
            'Prescription',
            rx.id,
            'AMRGuard',
            {'stage': 'CREDENTIAL_ISSUANCE'},
            principal=principal,
            facility_id=rx.facility_id,
            outcome='DENIED',
        )
        db.commit()
        raise HTTPException(409, 'Prescription has expired')

    old = db.scalar(select(PrescriptionCredential).where(PrescriptionCredential.prescription_id == rx.id))
    otp, otp_hash = _generate_unique_otp(db)
    token = secrets.token_urlsafe(32)
    qr_hash = keyed_digest(token, purpose='rx_qr')
    now = utcnow()
    expiry = now + timedelta(minutes=10)
    salt = secrets.token_hex(16)
    if old:
        old.otp_hash = otp_hash
        old.qr_token_hash = qr_hash
        old.token_salt = salt
        old.expires_at = expiry
        old.revoked = False
        old.revoked_at = None
        old.revoked_by_user_id = None
        old.used_count = 0
        old.failed_attempts = 0
        old.issued_by_user_id = principal.user_id
        old.issued_at = now
    else:
        db.add(
            PrescriptionCredential(
                prescription_id=rx.id,
                otp_hash=otp_hash,
                qr_token_hash=qr_hash,
                token_salt=salt,
                expires_at=expiry,
                issued_by_user_id=principal.user_id,
                issued_at=now,
            )
        )
    if rx.status in {'VALIDATED', 'WARNING'}:
        rx.status = 'ACTIVE'
    audit(
        db,
        'CREDENTIAL_CREATED',
        'Prescription',
        rx.id,
        'AMRGuard',
        {'expires_at': expiry.isoformat()},
        principal=principal,
        facility_id=rx.facility_id,
    )
    db.commit()
    return CredentialResponse(
        prescription_id=rx.id,
        prescription_code=f'AMR-RX-{rx.id:06d}',
        otp=otp,
        qr_token=token,
        expires_at=expiry,
    )


@app.post('/api/v1/prescriptions/{prescription_id}/credential/revoke')
def revoke_credential(
    prescription_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_FACILITY_ADMIN)),
):
    rx = db.get(Prescription, prescription_id)
    if not rx:
        raise HTTPException(404, 'Prescription not found')
    allowed_facilities = authorized_facility_ids_for_human(
        principal, db, {ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_FACILITY_ADMIN}
    )
    if rx.facility_id not in allowed_facilities:
        audit_authz_denied(
            db,
            principal,
            action='revoke_credential',
            entity_type='Prescription',
            entity_id=rx.id,
            facility_id=rx.facility_id,
            reason='cross_facility_revoke_denied',
        )
        raise HTTPException(403, 'Not authorized to revoke credentials for this prescription')
    cred = db.scalar(select(PrescriptionCredential).where(PrescriptionCredential.prescription_id == rx.id))
    if not cred:
        raise HTTPException(404, 'No active credential exists for this prescription')
    cred.revoked = True
    cred.revoked_at = utcnow()
    cred.revoked_by_user_id = principal.user_id
    audit(
        db,
        'CREDENTIAL_REVOKED',
        'Prescription',
        rx.id,
        'AMRGuard',
        {'revoked_at': cred.revoked_at.isoformat()},
        principal=principal,
        facility_id=rx.facility_id,
    )
    db.commit()
    return {'prescription_id': rx.id, 'revoked': True, 'revoked_at': cred.revoked_at}


def verify_credential(
    credential: str,
    db: Session,
    *,
    principal: Principal,
    consume: bool = False,
    expected_prescription_id: int | None = None,
    pharmacy_id: int | None = None,
):
    is_otp = credential.isdigit() and len(credential) == 6
    if is_otp:
        cred = db.scalar(
            select(PrescriptionCredential).where(
                PrescriptionCredential.otp_hash == keyed_digest(credential, purpose='rx_otp')
            )
        )
    else:
        cred = db.scalar(
            select(PrescriptionCredential).where(
                PrescriptionCredential.qr_token_hash == keyed_digest(credential, purpose='rx_qr')
            )
        )

    if not cred or cred.revoked or is_expired(cred.expires_at):
        audit(
            db,
            'CREDENTIAL_VERIFICATION_FAILED',
            'Prescription',
            expected_prescription_id or 'unknown',
            'Pharmacy',
            {'method': 'OTP' if is_otp else 'QR', 'reason': 'invalid_revoked_or_expired'},
            principal=principal,
            pharmacy_id=pharmacy_id,
            outcome='DENIED',
        )
        db.commit()
        raise HTTPException(401, 'Invalid or expired credential')

    if expected_prescription_id is not None and cred.prescription_id != expected_prescription_id:
        cred.failed_attempts += 1
        audit(
            db,
            'CREDENTIAL_PRESCRIPTION_MISMATCH',
            'Prescription',
            expected_prescription_id,
            'Pharmacy',
            {'credential_prescription_id': cred.prescription_id},
            principal=principal,
            pharmacy_id=pharmacy_id,
            outcome='DENIED',
        )
        db.commit()
        raise HTTPException(401, 'Credential does not match prescription')

    rx = db.get(Prescription, cred.prescription_id)
    if not rx:
        raise HTTPException(404, 'Prescription not found')
    if rx.status in {'CANCELLED', 'EXPIRED', 'COMPLETED', 'BLOCKED'}:
        raise HTTPException(409, f'Prescription is {rx.status}')
    if rx.expires_at and is_expired(rx.expires_at):
        rx.status = 'EXPIRED'
        audit(
            db,
            'PRESCRIPTION_EXPIRED',
            'Prescription',
            rx.id,
            'Pharmacy',
            {'stage': 'VERIFICATION'},
            principal=principal,
            facility_id=rx.facility_id,
            pharmacy_id=pharmacy_id,
            outcome='DENIED',
        )
        db.commit()
        raise HTTPException(409, 'Prescription has expired')
    if consume:
        cred.used_count += 1
    audit(
        db,
        'CREDENTIAL_VERIFIED',
        'Prescription',
        rx.id,
        'Pharmacy',
        {'method': 'OTP' if is_otp else 'QR', 'consumed': consume},
        principal=principal,
        facility_id=rx.facility_id,
        pharmacy_id=pharmacy_id,
    )
    return rx, cred


def _enforce_verify_rate_limit(principal: Principal, db: Session) -> None:
    if not rate_limiter.check_and_record(
        f'cred_verify:{principal.actor_id}',
        max_attempts=settings.credential_verify_rate_limit,
        window_seconds=settings.credential_verify_window_seconds,
    ):
        audit(
            db,
            'CREDENTIAL_VERIFICATION_RATE_LIMITED',
            'Verification',
            principal.actor_id,
            'Pharmacy',
            principal=principal,
            outcome='DENIED',
        )
        db.commit()
        raise HTTPException(429, 'Verification rate limit exceeded')


@app.post('/api/v1/verification')
def verify(
    request: VerificationRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PHARMACIST, ROLE_PHARMACY_ASSISTANT)),
):
    _enforce_verify_rate_limit(principal, db)
    rx, _ = verify_credential(request.credential, db, principal=principal)
    allowed, matched_pharmacy_id, reason = evaluate_verification_authorization(principal, rx, db)
    if not allowed:
        db.rollback()
        audit_authz_denied(
            db,
            principal,
            action='verify_credential',
            entity_type='Prescription',
            entity_id=rx.id,
            facility_id=rx.facility_id,
            reason=reason,
        )
        raise HTTPException(403, reason)
    db.commit()
    return {
        'verified': True,
        'matched_pharmacy_id': matched_pharmacy_id,
        'prescription': prescription_detail(rx, db),
    }


@app.post('/api/v1/verification/otp', deprecated=True)
def verify_otp(
    response: Response,
    otp: str = Query(min_length=6, max_length=6),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PHARMACIST, ROLE_PHARMACY_ASSISTANT)),
):
    """Deprecated query-string OTP verification. Disabled in production; use POST /api/v1/verification JSON body."""
    if settings.app_env.lower() == 'production':
        raise HTTPException(
            status_code=410,
            detail='Query-string OTP verification is disabled in production; use POST /api/v1/verification',
        )
    response.headers['Deprecation'] = 'true'
    _enforce_verify_rate_limit(principal, db)
    rx, _ = verify_credential(otp, db, principal=principal)
    allowed, _, reason = evaluate_verification_authorization(principal, rx, db)
    if not allowed:
        db.rollback()
        audit_authz_denied(
            db,
            principal,
            action='verify_otp',
            entity_type='Prescription',
            entity_id=rx.id,
            facility_id=rx.facility_id,
            reason=reason,
        )
        raise HTTPException(403, reason)
    db.commit()
    return {
        'verified': True,
        'prescription_id': rx.id,
        'prescription_code': f'AMR-RX-{rx.id:06d}',
        'status': rx.status,
    }


@app.get('/api/v1/prescriptions')
def list_prescriptions(
    limit: int = Query(default=25, ge=1, le=100),
    status: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(
        require_human_roles(
            ROLE_PRESCRIBER,
            ROLE_PHARMACIST,
            ROLE_PHARMACY_ASSISTANT,
            ROLE_STEWARDSHIP_OFFICER,
            ROLE_FACILITY_ADMIN,
        )
    ),
):
    allowed_facilities = authorized_facility_ids_for_human(
        principal,
        db,
        {ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_PHARMACY_ASSISTANT, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN},
    )
    if not allowed_facilities:
        return []
    query = (
        select(Prescription)
        .where(Prescription.facility_id.in_(allowed_facilities))
        .order_by(Prescription.created_at.desc())
        .limit(limit)
    )
    if status:
        query = query.where(Prescription.status == status.upper())
    rows = db.scalars(query).all()
    return [prescription_detail(rx, db) for rx in rows]


@app.get('/api/v1/stock/batches')
def list_stock_batches(
    pharmacy_id: int | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(
        require_human_roles(
            ROLE_PHARMACIST,
            ROLE_PHARMACY_ASSISTANT,
            ROLE_STEWARDSHIP_OFFICER,
            ROLE_FACILITY_ADMIN,
        )
    ),
):
    allowed_pharmacies = authorized_pharmacy_ids_for_human(
        principal, db, {ROLE_PHARMACIST, ROLE_PHARMACY_ASSISTANT, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
    )
    if pharmacy_id is not None and pharmacy_id not in allowed_pharmacies:
        audit_authz_denied(
            db,
            principal,
            action='list_stock_batches',
            entity_type='Pharmacy',
            entity_id=pharmacy_id,
            pharmacy_id=pharmacy_id,
            reason='cross_pharmacy_stock_read_denied',
        )
        raise HTTPException(403, 'Not authorized to view stock for this pharmacy')
    if not allowed_pharmacies:
        return []

    query = select(StockBatch).order_by(StockBatch.expiry_date, StockBatch.batch_number)
    if pharmacy_id is not None:
        query = query.where(StockBatch.pharmacy_id == pharmacy_id)
    else:
        query = query.where(StockBatch.pharmacy_id.in_(allowed_pharmacies))
    rows = db.scalars(query).all()
    result = []
    for batch in rows:
        pharmacy = db.get(Pharmacy, batch.pharmacy_id)
        antibiotic = db.get(Antibiotic, batch.antibiotic_id)
        if pharmacy and antibiotic:
            result.append(
                {
                    'id': batch.id,
                    'pharmacy_id': pharmacy.id,
                    'pharmacy_name': pharmacy.name,
                    'pharmacy_code': pharmacy.code,
                    'antibiotic_id': antibiotic.id,
                    'antibiotic': antibiotic.generic_name,
                    'antibiotic_code': antibiotic.code,
                    'strength': antibiotic.strength,
                    'formulation': antibiotic.formulation,
                    'batch_number': batch.batch_number,
                    'expiry_date': batch.expiry_date,
                    'quantity_available': batch.quantity_available,
                    'source_reference': batch.source_reference,
                }
            )
    return result


@app.post('/api/v1/integrations/rms/stock-events')
def receive_rms_stock_event(
    request: RmsStockEventRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_service_scope(SCOPE_RMS_STOCK_WRITE)),
):
    if request.event_type == 'RECEIPT' and request.quantity_delta <= 0:
        raise HTTPException(422, 'Receipt quantity_delta must be positive')
    if request.quantity_delta == 0:
        raise HTTPException(422, 'quantity_delta cannot be zero')

    pharmacy = db.scalar(select(Pharmacy).where(Pharmacy.code == request.pharmacy_code, Pharmacy.active.is_(True)))
    if not pharmacy or not service_client_allows_pharmacy(principal, SCOPE_RMS_STOCK_WRITE, pharmacy.id):
        if not pharmacy and settings.effective_quarantine_unmapped_codes:
            inbox_entry = IntegrationInbox(
                source_system=request.source_system,
                event_type='STOCK_EVENT',
                external_id=request.source_reference,
                payload=request.model_dump_json(),
                quarantine_reason=f'Unknown pharmacy code: {request.pharmacy_code}',
                unresolved_code=request.pharmacy_code,
                status='QUARANTINED',
            )
            db.add(inbox_entry)
            db.flush()
            audit(
                db,
                'INTEGRATION_EVENT_QUARANTINED',
                'IntegrationInbox',
                inbox_entry.id,
                request.source_system,
                {'source_reference': request.source_reference, 'reason': inbox_entry.quarantine_reason},
                principal=principal,
            )
            db.commit()
            raise HTTPException(
                status_code=422,
                detail={
                    'message': f'Unknown pharmacy code "{request.pharmacy_code}" quarantined',
                    'quarantine_id': inbox_entry.id,
                    'status': 'QUARANTINED',
                },
            )
        audit_authz_denied(
            db,
            principal,
            action='rms_stock_event',
            entity_type='Pharmacy',
            entity_id=request.pharmacy_code,
            pharmacy_id=pharmacy.id if pharmacy else None,
            reason='pharmacy_not_provisioned_or_out_of_scope',
        )
        raise HTTPException(403, 'Service client is not authorized for this pharmacy')

    details = {
        'pharmacy_code': request.pharmacy_code,
        'antibiotic_code': request.antibiotic_code,
        'batch_number': request.batch_number,
        'expiry_date': request.expiry_date.isoformat(),
        'event_type': request.event_type,
        'quantity_delta': request.quantity_delta,
    }
    prior = db.scalar(
        select(StockEvent).where(
            StockEvent.source_system == request.source_system,
            StockEvent.reference_id == request.source_reference,
        )
    )
    if prior:
        prior_batch = db.get(StockBatch, prior.batch_id)
        if prior_batch and prior_batch.pharmacy_id != pharmacy.id:
            raise HTTPException(409, 'Source event reference belongs to a different pharmacy')
        if json.loads(prior.details or '{}') != details:
            raise HTTPException(409, 'Source event reference was already used for a different stock movement')
        return {
            'accepted': True,
            'replayed': True,
            'event_id': prior.id,
            'batch_id': prior.batch_id,
            'quantity_available': prior_batch.quantity_available if prior_batch else None,
        }

    antibiotic = db.scalar(select(Antibiotic).where(Antibiotic.code == request.antibiotic_code))
    if not antibiotic:
        mapping = db.scalar(
            select(MedicineMapping).where(
                MedicineMapping.source_code == request.antibiotic_code,
                MedicineMapping.approval_status == 'APPROVED',
                MedicineMapping.active.is_(True),
            )
        )
        if mapping:
            concept = db.get(MedicineConcept, mapping.medicine_concept_id) if mapping.medicine_concept_id else None
            if concept:
                antibiotic = db.scalar(select(Antibiotic).where(Antibiotic.code == concept.code))

        if not antibiotic:
            if settings.effective_quarantine_unmapped_codes:
                inbox_entry = IntegrationInbox(
                    source_system=request.source_system,
                    event_type='STOCK_EVENT',
                    external_id=request.source_reference,
                    payload=request.model_dump_json(),
                    quarantine_reason=f'Unknown antibiotic catalogue code: {request.antibiotic_code}',
                    unresolved_code=request.antibiotic_code,
                    status='QUARANTINED',
                    facility_id=pharmacy.facility_id,
                )
                db.add(inbox_entry)
                db.flush()
                audit(
                    db,
                    'INTEGRATION_EVENT_QUARANTINED',
                    'IntegrationInbox',
                    inbox_entry.id,
                    request.source_system,
                    {'source_reference': request.source_reference, 'reason': inbox_entry.quarantine_reason},
                    principal=principal,
                    facility_id=pharmacy.facility_id,
                    pharmacy_id=pharmacy.id,
                )
                db.commit()
                raise HTTPException(
                    status_code=422,
                    detail={
                        'message': f'Unknown antibiotic catalogue code "{request.antibiotic_code}" requires approved mapping before stock ingestion',
                        'quarantine_id': inbox_entry.id,
                        'status': 'QUARANTINED',
                    },
                )
            antibiotic = Antibiotic(
                code=request.antibiotic_code,
                generic_name=request.generic_name,
                strength=request.strength,
                formulation=request.formulation,
                route=request.route,
                active=True,
            )
            db.add(antibiotic)
            db.flush()
    elif (antibiotic.generic_name, antibiotic.strength, antibiotic.formulation, antibiotic.route) != (
        request.generic_name,
        request.strength,
        request.formulation,
        request.route,
    ):
        raise HTTPException(409, 'Antibiotic catalog fields conflict with the existing canonical item')

    batch = db.scalar(
        select(StockBatch)
        .where(
            StockBatch.pharmacy_id == pharmacy.id,
            StockBatch.antibiotic_id == antibiotic.id,
            StockBatch.batch_number == request.batch_number,
        )
        .with_for_update()
    )
    if not batch:
        if request.event_type != 'RECEIPT':
            raise HTTPException(404, 'A stock batch must be received before it can be adjusted')
        batch = StockBatch(
            pharmacy_id=pharmacy.id,
            antibiotic_id=antibiotic.id,
            batch_number=request.batch_number,
            expiry_date=request.expiry_date,
            quantity_available=0,
            source_reference=request.source_reference,
        )
        db.add(batch)
        db.flush()
    elif batch.expiry_date != request.expiry_date:
        raise HTTPException(409, 'Batch expiry conflicts with the existing stock record')

    updated_quantity = batch.quantity_available + request.quantity_delta
    if updated_quantity < 0:
        raise HTTPException(409, 'Stock adjustment would make available quantity negative')
    batch.quantity_available = updated_quantity
    event = StockEvent(
        batch_id=batch.id,
        event_type=request.event_type,
        quantity=request.quantity_delta,
        reference_id=request.source_reference,
        source_system=request.source_system,
        details=json.dumps(details),
    )
    db.add(event)
    audit(
        db,
        'STOCK_EVENT_RECEIVED',
        'StockBatch',
        batch.id,
        request.source_system,
        details,
        principal=principal,
        facility_id=pharmacy.facility_id,
        pharmacy_id=pharmacy.id,
    )
    db.commit()
    db.refresh(event)
    return {
        'accepted': True,
        'replayed': False,
        'event_id': event.id,
        'batch_id': batch.id,
        'quantity_available': batch.quantity_available,
    }


@app.get('/api/v1/integrations/inbox/quarantine')
def list_quarantined_messages(
    source_system: str | None = None,
    status: str = 'QUARANTINED',
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_FACILITY_ADMIN, ROLE_STEWARDSHIP_OFFICER, ROLE_PLATFORM_OPERATOR)),
):
    query = select(IntegrationInbox).where(IntegrationInbox.status == status)
    if source_system:
        query = query.where(IntegrationInbox.source_system == source_system)
    query = query.order_by(IntegrationInbox.created_at.desc()).offset(offset).limit(limit)
    rows = db.scalars(query).all()
    return [
        {
            'id': row.id,
            'source_system': row.source_system,
            'event_type': row.event_type,
            'external_id': row.external_id,
            'quarantine_reason': row.quarantine_reason,
            'unresolved_code': row.unresolved_code,
            'status': row.status,
            'facility_id': row.facility_id,
            'created_at': row.created_at,
            'resolved_at': row.resolved_at,
            'resolved_by_user_id': row.resolved_by_user_id,
            'resolution_notes': row.resolution_notes,
        }
        for row in rows
    ]


@app.post('/api/v1/integrations/inbox/quarantine/{inbox_id}/resolve')
def resolve_quarantined_message(
    inbox_id: int,
    request: QuarantineResolveRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_FACILITY_ADMIN, ROLE_STEWARDSHIP_OFFICER, ROLE_PLATFORM_OPERATOR)),
):
    entry = db.get(IntegrationInbox, inbox_id)
    if not entry:
        raise HTTPException(404, 'Quarantine inbox entry not found')
    if entry.status not in {'QUARANTINED', 'PENDING'}:
        raise HTTPException(409, f'Inbox entry is already {entry.status}')

    if request.action == 'REJECT':
        entry.status = 'REJECTED'
        entry.resolved_at = utcnow()
        entry.resolved_by_user_id = principal.user_id
        entry.resolution_notes = request.notes
        audit(
            db,
            'QUARANTINE_REJECTED',
            'IntegrationInbox',
            entry.id,
            entry.source_system,
            {'notes': request.notes},
            principal=principal,
            facility_id=entry.facility_id,
        )
        db.commit()
        return {'id': entry.id, 'status': entry.status, 'action': 'REJECT'}

    elif request.action in {'APPROVE', 'REPLAY'}:
        if entry.event_type == 'PRESCRIPTION':
            data = json.loads(entry.payload)
            rx_in = PrescriptionIn(**data)
            fac = db.scalar(select(Facility).where(Facility.code == rx_in.prescriber.facility_code, Facility.active.is_(True)))
            if not fac:
                raise HTTPException(422, f'Facility {rx_in.prescriber.facility_code} is still unmapped or inactive')
            pr = db.scalar(select(Prescriber).where(Prescriber.external_user_id == rx_in.prescriber.external_user_id))
            if not pr:
                pr = Prescriber(external_user_id=rx_in.prescriber.external_user_id, name=rx_in.prescriber.name, facility_id=fac.id)
                db.add(pr)
                db.flush()
            elif pr.facility_id != fac.id:
                raise HTTPException(422, f'Prescriber {pr.external_user_id} facility mismatch')

            existing = db.scalar(select(Prescription).where(Prescription.external_id == rx_in.external_id))
            if existing:
                entry.status = 'PROCESSED'
                entry.resolved_at = utcnow()
                entry.resolved_by_user_id = principal.user_id
                entry.resolution_notes = 'Prescription already ingested'
                db.commit()
                return {'id': entry.id, 'status': entry.status, 'prescription_id': existing.id}

            rx = Prescription(
                external_id=rx_in.external_id,
                patient_reference=rx_in.patient_reference,
                prescriber_id=pr.id,
                facility_id=fac.id,
                allow_external_dispensing=bool(rx_in.allow_external_dispensing),
                expires_at=rx_in.expires_at,
            )
            db.add(rx)
            db.flush()
            issues = []
            for p in rx_in.items:
                ab = db.scalar(select(Antibiotic).where(Antibiotic.code == p.antibiotic_code))
                formulation = db.get(Formulation, p.formulation_id) if p.formulation_id else None
                if not ab:
                    mapping = db.scalar(
                        select(MedicineMapping).where(
                            MedicineMapping.source_code == p.antibiotic_code,
                            MedicineMapping.approval_status == 'APPROVED',
                            MedicineMapping.active.is_(True),
                        )
                    )
                    if mapping:
                        if mapping.formulation_id and not formulation:
                            formulation = db.get(Formulation, mapping.formulation_id)
                        concept = db.get(MedicineConcept, mapping.medicine_concept_id) if mapping.medicine_concept_id else None
                        if concept:
                            ab = db.scalar(select(Antibiotic).where(Antibiotic.code == concept.code))
                    if not ab:
                        raise HTTPException(422, f'Antibiotic code {p.antibiotic_code} remains unmapped')

                if not formulation and ab:
                    concept = db.scalar(select(MedicineConcept).where(MedicineConcept.code == ab.code))
                    if concept:
                        formulation = db.scalar(
                            select(Formulation).where(
                                Formulation.medicine_concept_id == concept.id,
                                Formulation.active.is_(True),
                            )
                        )

                rule = db.scalar(select(AntibioticRule).where(AntibioticRule.antibiotic_id == ab.id, AntibioticRule.enabled.is_(True)))
                item = PrescriptionItem(
                    prescription_id=rx.id,
                    antibiotic_id=ab.id,
                    formulation_id=formulation.id if formulation else p.formulation_id,
                    dose=p.dose,
                    dose_unit=p.dose_unit,
                    frequency_per_day=p.frequency_per_day,
                    duration_days=p.duration_days,
                    quantity=p.quantity,
                    indication=p.indication,
                    is_prn=p.is_prn,
                    prn_reason=p.prn_reason,
                    instructions=p.instructions,
                )
                db.add(item)
                db.flush()
                item_issues = validate_item(item, rule, formulation=formulation)
                if any(issue.get('code') == 'MANUAL_REVIEW_REQUIRED' for issue in item_issues):
                    item.conversion_review_required = True
                issues += item_issues

            blocks = [i for i in issues if i['severity'] == 'BLOCK']
            rx.status = 'BLOCKED' if blocks else ('WARNING' if issues else 'VALIDATED')
            entry.status = 'PROCESSED'
            entry.resolved_at = utcnow()
            entry.resolved_by_user_id = principal.user_id
            entry.resolution_notes = request.notes or 'Replayed successfully after mapping resolution'
            audit(
                db,
                'QUARANTINE_REPLAYED',
                'IntegrationInbox',
                entry.id,
                entry.source_system,
                {'prescription_id': rx.id, 'status': rx.status},
                principal=principal,
                facility_id=fac.id,
            )
            db.commit()
            return {'id': entry.id, 'status': entry.status, 'prescription_id': rx.id}

        elif entry.event_type == 'STOCK_EVENT':
            data = json.loads(entry.payload)
            stock_in = RmsStockEventRequest(**data)
            pharmacy = db.scalar(select(Pharmacy).where(Pharmacy.code == stock_in.pharmacy_code, Pharmacy.active.is_(True)))
            if not pharmacy:
                raise HTTPException(422, f'Pharmacy {stock_in.pharmacy_code} remains unmapped or inactive')
            ab = db.scalar(select(Antibiotic).where(Antibiotic.code == stock_in.antibiotic_code))
            if not ab:
                mapping = db.scalar(
                    select(MedicineMapping).where(
                        MedicineMapping.source_code == stock_in.antibiotic_code,
                        MedicineMapping.approval_status == 'APPROVED',
                        MedicineMapping.active.is_(True),
                    )
                )
                if mapping:
                    concept = db.get(MedicineConcept, mapping.medicine_concept_id) if mapping.medicine_concept_id else None
                    if concept:
                        ab = db.scalar(select(Antibiotic).where(Antibiotic.code == concept.code))
                if not ab:
                    raise HTTPException(422, f'Antibiotic code {stock_in.antibiotic_code} remains unmapped')

            batch = db.scalar(
                select(StockBatch).where(
                    StockBatch.pharmacy_id == pharmacy.id,
                    StockBatch.antibiotic_id == ab.id,
                    StockBatch.batch_number == stock_in.batch_number,
                ).with_for_update()
            )
            if not batch:
                if stock_in.event_type != 'RECEIPT':
                    raise HTTPException(404, 'A stock batch must be received before it can be adjusted')
                batch = StockBatch(
                    pharmacy_id=pharmacy.id,
                    antibiotic_id=ab.id,
                    batch_number=stock_in.batch_number,
                    expiry_date=stock_in.expiry_date,
                    quantity_available=0,
                    source_reference=stock_in.source_reference,
                )
                db.add(batch)
                db.flush()
            updated_quantity = batch.quantity_available + stock_in.quantity_delta
            if updated_quantity < 0:
                raise HTTPException(409, 'Stock adjustment would make available quantity negative')
            batch.quantity_available = updated_quantity
            event = StockEvent(
                batch_id=batch.id,
                event_type=stock_in.event_type,
                quantity=stock_in.quantity_delta,
                reference_id=stock_in.source_reference,
                source_system=stock_in.source_system,
                details=json.dumps(data),
            )
            db.add(event)
            entry.status = 'PROCESSED'
            entry.resolved_at = utcnow()
            entry.resolved_by_user_id = principal.user_id
            entry.resolution_notes = request.notes or 'Replayed successfully after mapping resolution'
            audit(
                db,
                'QUARANTINE_REPLAYED',
                'IntegrationInbox',
                entry.id,
                entry.source_system,
                {'batch_id': batch.id, 'quantity_available': batch.quantity_available},
                principal=principal,
                pharmacy_id=pharmacy.id,
            )
            db.commit()
            return {'id': entry.id, 'status': entry.status, 'batch_id': batch.id}


@app.post('/api/v1/catalogue/mappings')
def create_or_update_mapping(
    request: MedicineMappingCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_FACILITY_ADMIN, ROLE_STEWARDSHIP_OFFICER, ROLE_PLATFORM_OPERATOR)),
):
    concept = db.get(MedicineConcept, request.medicine_concept_id)
    if not concept:
        raise HTTPException(404, f'MedicineConcept {request.medicine_concept_id} not found')
    if request.formulation_id:
        form = db.get(Formulation, request.formulation_id)
        if not form:
            raise HTTPException(404, f'Formulation {request.formulation_id} not found')

    existing = db.scalar(
        select(MedicineMapping).where(
            MedicineMapping.source_system == request.source_system,
            MedicineMapping.source_code == request.source_code,
        )
    )
    now = utcnow()
    if existing:
        existing.medicine_concept_id = request.medicine_concept_id
        existing.formulation_id = request.formulation_id
        existing.source_description = request.source_description
        existing.approval_status = request.approval_status
        if request.approval_status == 'APPROVED':
            existing.approved_by_user_id = principal.user_id
            existing.approved_at = now
        mapping = existing
    else:
        mapping = MedicineMapping(
            source_system=request.source_system,
            source_code=request.source_code,
            source_description=request.source_description,
            medicine_concept_id=request.medicine_concept_id,
            formulation_id=request.formulation_id,
            approval_status=request.approval_status,
            approved_by_user_id=principal.user_id if request.approval_status == 'APPROVED' else None,
            approved_at=now if request.approval_status == 'APPROVED' else None,
            active=True,
        )
        db.add(mapping)
    db.flush()
    audit(
        db,
        'MEDICINE_MAPPING_SAVED',
        'MedicineMapping',
        mapping.id,
        'AMRGuard',
        {
            'source_system': mapping.source_system,
            'source_code': mapping.source_code,
            'concept_id': mapping.medicine_concept_id,
            'approval_status': mapping.approval_status,
        },
        principal=principal,
    )
    db.commit()
    return {
        'id': mapping.id,
        'source_system': mapping.source_system,
        'source_code': mapping.source_code,
        'medicine_concept_id': mapping.medicine_concept_id,
        'formulation_id': mapping.formulation_id,
        'approval_status': mapping.approval_status,
    }


@app.get('/api/v1/catalogue/mappings')
def list_mappings(
    source_system: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_FACILITY_ADMIN, ROLE_STEWARDSHIP_OFFICER, ROLE_PHARMACIST, ROLE_PLATFORM_OPERATOR)),
):
    query = select(MedicineMapping).where(MedicineMapping.active.is_(True))
    if source_system:
        query = query.where(MedicineMapping.source_system == source_system)
    if status:
        query = query.where(MedicineMapping.approval_status == status.upper())
    query = query.order_by(MedicineMapping.source_system, MedicineMapping.source_code).limit(limit)
    rows = db.scalars(query).all()
    return [
        {
            'id': row.id,
            'source_system': row.source_system,
            'source_code': row.source_code,
            'source_description': row.source_description,
            'medicine_concept_id': row.medicine_concept_id,
            'formulation_id': row.formulation_id,
            'approval_status': row.approval_status,
            'created_at': row.created_at,
        }
        for row in rows
    ]


@app.post('/api/v1/prescriptions/{prescription_id}/stewardship-reminder')
def schedule_stewardship_reminder(
    prescription_id: int,
    request: StewardshipReminderRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER)),
):
    rx = db.get(Prescription, prescription_id)
    if not rx:
        raise HTTPException(404, 'Prescription not found')
    allowed_facilities = authorized_facility_ids_for_human(
        principal, db, {ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER}
    )
    if rx.facility_id not in allowed_facilities:
        audit_authz_denied(
            db,
            principal,
            action='schedule_reminder',
            entity_type='Prescription',
            entity_id=rx.id,
            facility_id=rx.facility_id,
            reason='cross_facility_reminder_denied',
        )
        raise HTTPException(403, 'Not authorized to schedule reminders for this facility')

    if not request.consent:
        raise HTTPException(422, 'Patient consent is required before scheduling an SMS reminder')
    if rx.status == 'BLOCKED' or not rx.items:
        raise HTTPException(409, 'A blocked or empty prescription cannot receive a stewardship reminder')
    existing = db.scalar(select(StewardshipReminder).where(StewardshipReminder.prescription_id == rx.id))
    if existing:
        raise HTTPException(409, 'A stewardship reminder is already scheduled for this prescription')
    first_dispense = db.scalar(
        select(func.min(DispensingTransaction.created_at)).where(DispensingTransaction.prescription_id == rx.id)
    )
    if not first_dispense:
        raise HTTPException(409, 'A stewardship reminder can only be scheduled after pharmacy dispensing')
    course_end = first_dispense + timedelta(days=max(item.duration_days for item in rx.items))
    if course_end.tzinfo is None:
        course_end = course_end.replace(tzinfo=timezone.utc)
    scheduled_at = max(course_end, utcnow())
    reminder = StewardshipReminder(
        prescription_id=rx.id,
        consent_recorded=True,
        consent_reference=request.consent_reference.strip(),
        consent_recorded_at=utcnow(),
        scheduled_at=scheduled_at,
        status='PENDING_PROVIDER',
    )
    db.add(reminder)
    audit(
        db,
        'STEWARDSHIP_REMINDER_SCHEDULED',
        'Prescription',
        rx.id,
        'AMRGuard',
        {
            'scheduled_at': scheduled_at.isoformat(),
            'delivery_status': 'PENDING_PROVIDER',
            'consent_reference': request.consent_reference.strip(),
        },
        principal=principal,
        facility_id=rx.facility_id,
    )
    db.commit()
    db.refresh(reminder)
    return {
        'id': reminder.id,
        'prescription_id': rx.id,
        'prescription_code': f'AMR-RX-{rx.id:06d}',
        'scheduled_at': reminder.scheduled_at,
        'status': reminder.status,
        'consent_recorded': reminder.consent_recorded,
        'consent_reference': reminder.consent_reference,
        'delivery_configured': False,
    }


@app.get('/api/v1/stewardship/reminders')
def list_stewardship_reminders(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN)),
):
    allowed_facilities = authorized_facility_ids_for_human(
        principal, db, {ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
    )
    if not allowed_facilities:
        return []
    rows = db.scalars(
        select(StewardshipReminder)
        .join(Prescription, Prescription.id == StewardshipReminder.prescription_id)
        .where(Prescription.facility_id.in_(allowed_facilities))
        .order_by(StewardshipReminder.scheduled_at)
        .limit(limit)
    ).all()
    return [
        {
            'id': reminder.id,
            'prescription_id': reminder.prescription_id,
            'prescription_code': f'AMR-RX-{reminder.prescription_id:06d}',
            'scheduled_at': reminder.scheduled_at,
            'status': reminder.status,
            'consent_recorded': reminder.consent_recorded,
            'consent_reference': reminder.consent_reference,
        }
        for reminder in rows
    ]


# ============================================================================
# P1-06: Informed Patient Consent Architecture
# ============================================================================

@app.post('/api/v1/consent', response_model=ConsentResponse)
def record_patient_consent(
    payload: ConsentCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN)),
):
    """Capture informed patient consent for dose reminders or stewardship notifications."""
    facility_id = payload.facility_id
    if facility_id is None:
        allowed_facs = authorized_facility_ids_for_human(
            principal, db, {ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
        )
        facility_id = next(iter(allowed_facs)) if allowed_facs else None
    else:
        if not has_platform_operator_scope(principal):
            allowed_facs = authorized_facility_ids_for_human(
                principal, db, {ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
            )
            if facility_id not in allowed_facs:
                audit_authz_denied(
                    db, principal, action='capture_consent', entity_type='ConsentRecord',
                    entity_id=payload.patient_reference, facility_id=facility_id, reason='facility_not_authorized'
                )
                raise HTTPException(status_code=403, detail='Not authorized for this facility')

    try:
        consent = capture_consent(
            db,
            patient_reference=payload.patient_reference,
            phone_number=payload.phone_number,
            purpose=payload.purpose,
            channel=payload.channel,
            language=payload.language,
            captured_by_user_id=principal.user_id,
            facility_id=facility_id,
            source_reference=payload.source_reference,
            evidence_reference=payload.evidence_reference,
            policy_version=payload.policy_version,
        )
        db.commit()
        db.refresh(consent)
        return consent
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get('/api/v1/consent', response_model=list[ConsentResponse])
def list_patient_consent(
    patient_reference: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN, ROLE_PLATFORM_OPERATOR)),
):
    """List or query consent records with facility tenancy scoping."""
    query = select(ConsentRecord)
    if patient_reference:
        query = query.where(ConsentRecord.patient_reference == patient_reference.strip())
    if status:
        query = query.where(ConsentRecord.status == status.upper())

    if not (has_platform_operator_scope(principal) or has_national_aggregate_scope(principal)):
        allowed_facs = authorized_facility_ids_for_human(
            principal, db, {ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
        )
        if not allowed_facs:
            return []
        query = query.where(ConsentRecord.facility_id.in_(allowed_facs) | ConsentRecord.facility_id.is_(None))

    query = query.order_by(ConsentRecord.captured_at.desc()).limit(limit)
    return db.scalars(query).all()


@app.post('/api/v1/consent/{consent_id}/withdraw', response_model=ConsentResponse)
def withdraw_patient_consent(
    consent_id: int,
    payload: ConsentWithdrawRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN)),
):
    """Withdraw consent and cascade cancellation to active schedules, occurrences, and outbox."""
    consent = db.get(ConsentRecord, consent_id)
    if not consent:
        raise HTTPException(status_code=404, detail='Consent record not found')

    if consent.facility_id and not has_platform_operator_scope(principal):
        allowed_facs = authorized_facility_ids_for_human(
            principal, db, {ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
        )
        if consent.facility_id not in allowed_facs:
            audit_authz_denied(
                db, principal, action='withdraw_consent', entity_type='ConsentRecord',
                entity_id=consent_id, facility_id=consent.facility_id, reason='facility_not_authorized'
            )
            raise HTTPException(status_code=403, detail='Not authorized for this facility')

    withdrawn = withdraw_consent(
        db,
        consent_id,
        withdrawn_by_user_id=principal.user_id,
        reason=payload.reason,
    )
    db.commit()
    db.refresh(withdrawn)
    return withdrawn


# ============================================================================
# P1-07: Dose-Level Reminder Engine & Outbox Dispatch
# ============================================================================

@app.post('/api/v1/prescriptions/{prescription_id}/reminders/schedule', response_model=ReminderScheduleResponse)
def schedule_dose_reminders(
    prescription_id: int,
    payload: ReminderScheduleCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER)),
):
    """Generate deterministic dose-level reminder schedules and queued outbox messages from an authoritative prescription."""
    rx = db.get(Prescription, prescription_id)
    if not rx:
        raise HTTPException(status_code=404, detail='Prescription not found')

    allowed_facs = authorized_facility_ids_for_human(
        principal, db, {ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER}
    )
    if rx.facility_id not in allowed_facs:
        audit_authz_denied(
            db, principal, action='schedule_dose_reminders', entity_type='Prescription',
            entity_id=rx.id, facility_id=rx.facility_id, reason='facility_not_authorized'
        )
        raise HTTPException(status_code=403, detail='Not authorized for this facility')

    try:
        schedule = create_dose_reminder_schedule(
            db,
            prescription_id=rx.id,
            prescription_item_id=payload.prescription_item_id,
            daily_times=payload.daily_times,
            start_date=payload.start_date,
            language=payload.language,
            created_by_user_id=principal.user_id,
        )
        db.commit()
        db.refresh(schedule)

        occurrences = db.scalars(
            select(ReminderOccurrence).where(ReminderOccurrence.schedule_id == schedule.id).order_by(ReminderOccurrence.dose_number.asc())
        ).all()
        return ReminderScheduleResponse(
            id=schedule.id,
            prescription_id=schedule.prescription_id,
            prescription_item_id=schedule.prescription_item_id,
            patient_reference=schedule.patient_reference,
            consent_record_id=schedule.consent_record_id,
            timezone=schedule.timezone,
            start_date=schedule.start_date,
            end_date=schedule.end_date,
            daily_times=json.loads(schedule.daily_times),
            language=schedule.language,
            status=schedule.status,
            created_at=schedule.created_at,
            cancelled_at=schedule.cancelled_at,
            cancellation_reason=schedule.cancellation_reason,
            total_doses=len(occurrences),
            occurrences=[ReminderOccurrenceResponse.model_validate(o) for o in occurrences],
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))


@app.get('/api/v1/prescriptions/{prescription_id}/reminders', response_model=list[ReminderScheduleResponse])
def get_prescription_reminder_schedules(
    prescription_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN)),
):
    """List dose-level reminder schedules and occurrences for a prescription."""
    rx = db.get(Prescription, prescription_id)
    if not rx:
        raise HTTPException(status_code=404, detail='Prescription not found')

    allowed_facs = authorized_facility_ids_for_human(
        principal, db, {ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
    )
    if rx.facility_id not in allowed_facs:
        audit_authz_denied(
            db, principal, action='get_reminder_schedules', entity_type='Prescription',
            entity_id=rx.id, facility_id=rx.facility_id, reason='facility_not_authorized'
        )
        raise HTTPException(status_code=403, detail='Not authorized for this facility')

    schedules = db.scalars(
        select(ReminderSchedule).where(ReminderSchedule.prescription_id == prescription_id).order_by(ReminderSchedule.created_at.desc())
    ).all()

    result = []
    for s in schedules:
        occurrences = db.scalars(
            select(ReminderOccurrence).where(ReminderOccurrence.schedule_id == s.id).order_by(ReminderOccurrence.dose_number.asc())
        ).all()
        result.append(
            ReminderScheduleResponse(
                id=s.id,
                prescription_id=s.prescription_id,
                prescription_item_id=s.prescription_item_id,
                patient_reference=s.patient_reference,
                consent_record_id=s.consent_record_id,
                timezone=s.timezone,
                start_date=s.start_date,
                end_date=s.end_date,
                daily_times=json.loads(s.daily_times),
                language=s.language,
                status=s.status,
                created_at=s.created_at,
                cancelled_at=s.cancelled_at,
                cancellation_reason=s.cancellation_reason,
                total_doses=len(occurrences),
                occurrences=[ReminderOccurrenceResponse.model_validate(o) for o in occurrences],
            )
        )
    return result


@app.post('/api/v1/reminders/dispatch-tick')
def trigger_reminder_dispatch_tick(
    payload: DispatchBatchRequest = DispatchBatchRequest(),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_service_scope(SCOPE_SMS_DISPATCH)),
):
    """Worker endpoint to lease and dispatch pending outbox messages with pre-send active consent checks."""
    summary = dispatch_reminders_batch(db, batch_size=payload.batch_size)
    db.commit()
    return {
        'status': 'SUCCESS',
        'details': summary,
    }


@app.post('/api/v1/integrations/sms/delivery-callback')
def receive_sms_delivery_callback(
    payload: DeliveryCallbackRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_service_scope(SCOPE_SMS_CALLBACK)),
):
    """Record webhook delivery receipt from SMS gateway.

    CLINICAL BOUNDARY: Network delivery receipt NEVER implies or records medication ingestion.
    """
    try:
        event = record_delivery_receipt(
            db,
            provider=payload.provider,
            provider_message_id=payload.provider_message_id,
            event_type=payload.event_type,
            raw_payload=payload.details,
        )
        db.commit()
        return {
            'status': 'ACKNOWLEDGED',
            'event_id': event.id,
            'event_type': event.event_type,
            'clinical_notice': 'SMS delivery confirmation indicates network transmission only; does not record patient medication adherence.',
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post('/api/v1/integrations/sms/inbound')
def receive_inbound_sms(
    payload: InboundSmsRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_service_scope(SCOPE_SMS_INBOUND)),
):
    """Inbound webhook for SMS keywords (STOP, YEKA, etc.) to trigger automatic consent withdrawal."""
    try:
        withdrawn = handle_inbound_opt_out(db, raw_phone=payload.sender_phone, message_body=payload.message_body)
        db.commit()
        return {
            'status': 'PROCESSED',
            'opt_out_actioned': len(withdrawn) > 0,
            'consents_withdrawn': len(withdrawn),
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# P1-05: Canonical Outbox Worker Dispatch and Dead-Letter Endpoints
@app.post('/api/v1/integrations/outbox/dispatch-tick', response_model=OutboxDispatchResponse)
def dispatch_integration_outbox_tick(
    batch_size: int = Query(default=20, ge=1, le=100),
    max_retries: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_authenticated_principal),
):
    """Worker tick to lease and dispatch pending partner outbox reconciliation messages."""
    is_authorized = False
    if principal.actor_type in ('SERVICE_CLIENT', 'service_client') and service_client_has_scope(principal, SCOPE_OUTBOX_DISPATCH):
        is_authorized = True
    elif principal.actor_type in ('HUMAN', 'human') and (ROLE_PLATFORM_OPERATOR in principal.roles):
        is_authorized = True

    if not is_authorized:
        audit_authz_denied(
            db,
            principal,
            action='outbox_dispatch_tick',
            entity_type='IntegrationOutbox',
            entity_id='BATCH',
            reason='outbox_dispatch_scope_or_platform_operator_required',
        )
        raise HTTPException(status_code=403, detail='Requires outbox dispatch service scope or platform operator role')

    stats = process_integration_outbox_batch(db, batch_size=batch_size, max_retries=max_retries)
    return OutboxDispatchResponse(**stats)


@app.get('/api/v1/integrations/outbox/dead-letter', response_model=list[OutboxItemResponse])
def list_outbox_dead_letters(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN)),
):
    """Retrieve dead-letter and failed partner reconciliation events for administrative inspection."""
    stmt = (
        select(IntegrationOutbox)
        .where(IntegrationOutbox.status.in_(['DEAD_LETTER', 'FAILED']))
        .order_by(IntegrationOutbox.created_at.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


@app.post('/api/v1/integrations/outbox/{outbox_id}/retry', response_model=OutboxItemResponse)
def retry_outbox_dead_letter(
    outbox_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR)),
):
    """Manually reset a dead-letter partner reconciliation event back to PENDING."""
    try:
        retried = retry_dead_letter(db, outbox_id)
        return retried
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def create_due_stewardship_review(
    prescription_id: int,
    dispensed_at: datetime,
    db: Session,
    *,
    principal: Principal | None = None,
    facility_id: int | None = None,
):
    existing = db.scalar(
        select(StewardshipReview).where(
            StewardshipReview.prescription_id == prescription_id,
            StewardshipReview.review_type == 'POST_DISPENSE',
        )
    )
    if existing:
        return existing
    review = StewardshipReview(
        prescription_id=prescription_id,
        review_type='POST_DISPENSE',
        status='PENDING',
        due_at=dispensed_at + timedelta(days=3),
    )
    db.add(review)
    db.flush()
    audit(
        db,
        'STEWARDSHIP_REVIEW_CREATED',
        'Prescription',
        prescription_id,
        'AMRGuard',
        {'review_id': review.id, 'due_at': review.due_at.isoformat()},
        principal=principal,
        facility_id=facility_id,
    )
    return review


@app.get('/api/v1/stewardship/reviews')
def list_stewardship_reviews(
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_STEWARDSHIP_OFFICER, ROLE_PHARMACIST, ROLE_FACILITY_ADMIN)),
):
    allowed_facilities = authorized_facility_ids_for_human(
        principal, db, {ROLE_STEWARDSHIP_OFFICER, ROLE_PHARMACIST, ROLE_FACILITY_ADMIN}
    )
    if not allowed_facilities:
        return []
    query = (
        select(StewardshipReview)
        .join(Prescription, Prescription.id == StewardshipReview.prescription_id)
        .where(Prescription.facility_id.in_(allowed_facilities))
        .order_by(StewardshipReview.due_at)
        .limit(limit)
    )
    if status:
        query = query.where(StewardshipReview.status == status.upper())
    result = []
    for review in db.scalars(query).all():
        rx = db.get(Prescription, review.prescription_id)
        tx = db.scalar(
            select(DispensingTransaction)
            .where(DispensingTransaction.prescription_id == review.prescription_id)
            .order_by(DispensingTransaction.created_at.desc())
        )
        result.append(
            {
                'id': review.id,
                'prescription_id': review.prescription_id,
                'prescription_code': f'AMR-RX-{review.prescription_id:06d}',
                'patient_reference': rx.patient_reference if rx else None,
                'facility_id': rx.facility_id if rx else None,
                'review_type': review.review_type,
                'status': review.status,
                'due_at': review.due_at,
                'outcome': review.outcome,
                'reason': review.reason,
                'reviewer_reference': review.reviewer_reference,
                'reviewer_user_id': review.reviewer_user_id,
                'completed_at': review.completed_at,
                'last_transaction_id': tx.transaction_id if tx else None,
            }
        )
    return result


@app.post('/api/v1/stewardship/reviews/{review_id}/complete')
def complete_stewardship_review(
    review_id: int,
    request: StewardshipReviewRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_STEWARDSHIP_OFFICER, ROLE_PHARMACIST)),
):
    review = db.get(StewardshipReview, review_id)
    if not review:
        raise HTTPException(404, 'Stewardship review not found')
    rx = db.get(Prescription, review.prescription_id)
    if not rx:
        raise HTTPException(404, 'Linked prescription not found')
    allowed_facilities = authorized_facility_ids_for_human(
        principal, db, {ROLE_STEWARDSHIP_OFFICER, ROLE_PHARMACIST}
    )
    if rx.facility_id not in allowed_facilities:
        audit_authz_denied(
            db,
            principal,
            action='complete_stewardship_review',
            entity_type='StewardshipReview',
            entity_id=review.id,
            facility_id=rx.facility_id,
            reason='cross_facility_review_denied',
        )
        raise HTTPException(403, 'Not authorized to complete stewardship reviews for this facility')

    if review.status == 'COMPLETED':
        raise HTTPException(409, 'Stewardship review is already completed')

    review.status = 'COMPLETED'
    review.outcome = request.outcome
    review.reason = request.reason.strip()
    review.reviewer_user_id = principal.user_id
    review.reviewer_reference = (
        request.reviewer_reference.strip() if request.reviewer_reference else (principal.username or principal.actor_id)
    )
    review.completed_at = utcnow()
    audit(
        db,
        'STEWARDSHIP_REVIEW_COMPLETED',
        'Prescription',
        review.prescription_id,
        review.reviewer_reference,
        {'review_id': review.id, 'outcome': review.outcome, 'reason': review.reason},
        principal=principal,
        facility_id=rx.facility_id,
    )
    db.commit()
    return {
        'id': review.id,
        'prescription_id': review.prescription_id,
        'status': review.status,
        'outcome': review.outcome,
        'reviewer_user_id': review.reviewer_user_id,
        'completed_at': review.completed_at,
    }


@app.get('/api/v1/stewardship/metrics', response_model=GovernedMetricsResponse)
def get_governed_metrics(
    facility_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(
        require_human_roles(
            ROLE_STEWARDSHIP_OFFICER,
            ROLE_NATIONAL_ANALYST,
            ROLE_PLATFORM_OPERATOR,
            ROLE_FACILITY_ADMIN,
            ROLE_PRESCRIBER,
            ROLE_PHARMACIST,
        )
    ),
):
    """Evaluates governed stewardship KPIs and WHO AWaRe breakdown with minimum-cell suppression."""
    is_national = has_national_aggregate_scope(principal) or has_platform_operator_scope(principal)
    if is_national:
        target_facility_id = facility_id
    else:
        allowed_facilities = authorized_facility_ids_for_human(
            principal,
            db,
            {ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN, ROLE_PRESCRIBER, ROLE_PHARMACIST},
        )
        if facility_id is not None:
            if facility_id not in allowed_facilities:
                audit_authz_denied(
                    db,
                    principal,
                    action='read_governed_metrics',
                    entity_type='Facility',
                    entity_id=facility_id,
                    facility_id=facility_id,
                    reason='unauthorized_facility_metrics',
                )
                raise HTTPException(403, 'Not authorized to view metrics for this facility')
            target_facility_id = facility_id
        elif len(allowed_facilities) == 1:
            target_facility_id = next(iter(allowed_facilities))
        else:
            target_facility_id = None

    metrics_res = evaluate_governed_metrics(db, facility_id=target_facility_id)
    audit(
        db,
        'GOVERNED_METRICS_EVALUATED',
        'MetricDefinition',
        str(target_facility_id or 'ALL'),
        'AMRGuard',
        {'target_facility_id': target_facility_id},
        principal=principal,
        facility_id=target_facility_id,
    )
    db.commit()
    return metrics_res


@app.get('/api/v1/stewardship/aware-catalog', response_model=list[WhoAwareClassificationResponse])
def list_aware_catalog(
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_authenticated_principal),
):
    """Retrieves authoritative WHO AWaRe antibiotic classifications."""
    seed_who_aware_classifications(db)
    query = select(WhoAwareClassification)
    if category:
        query = query.where(WhoAwareClassification.category == category.upper())
    query = query.order_by(WhoAwareClassification.generic_name)
    rows = list(db.scalars(query).all())
    audit(
        db,
        'AWARE_CATALOG_ACCESSED',
        'WhoAwareClassification',
        'LIST',
        'AMRGuard',
        {'category_filter': category, 'count': len(rows)},
        principal=principal,
    )
    db.commit()
    return rows


@app.get('/api/v1/stewardship/rules', response_model=list[StewardshipRuleResponse])
def list_stewardship_rules(
    status: str | None = Query(default='ACTIVE'),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_authenticated_principal),
):
    """Retrieves clinically governed antimicrobial stewardship rules."""
    seed_governed_rules(db)
    query = select(GovernedStewardshipRule)
    if status:
        query = query.where(GovernedStewardshipRule.status == status.upper())
    query = query.order_by(GovernedStewardshipRule.rule_code)
    rows = list(db.scalars(query).all())
    audit(
        db,
        'STEWARDSHIP_RULES_ACCESSED',
        'GovernedStewardshipRule',
        'LIST',
        'AMRGuard',
        {'status_filter': status, 'count': len(rows)},
        principal=principal,
    )
    db.commit()
    return rows


@app.get('/api/v1/stewardship/alerts', response_model=list[StewardshipAlertResponse])
def list_stewardship_alerts(
    prescription_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    principal: Principal = Depends(
        require_human_roles(
            ROLE_STEWARDSHIP_OFFICER,
            ROLE_PRESCRIBER,
            ROLE_PHARMACIST,
            ROLE_FACILITY_ADMIN,
            ROLE_NATIONAL_ANALYST,
            ROLE_PLATFORM_OPERATOR,
        )
    ),
):
    """Retrieves generated stewardship alerts subject to tenant facility boundaries."""
    query = select(StewardshipAlert).join(Prescription, StewardshipAlert.prescription_id == Prescription.id)

    if not (has_national_aggregate_scope(principal) or has_platform_operator_scope(principal)):
        allowed_facilities = authorized_facility_ids_for_human(
            principal,
            db,
            {ROLE_STEWARDSHIP_OFFICER, ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_FACILITY_ADMIN},
        )
        if not allowed_facilities:
            return []
        query = query.where(Prescription.facility_id.in_(allowed_facilities))

    if prescription_id:
        query = query.where(StewardshipAlert.prescription_id == prescription_id)
    if status:
        query = query.where(StewardshipAlert.status == status.upper())

    query = query.order_by(StewardshipAlert.created_at.desc()).limit(limit)
    rows = list(db.scalars(query).all())

    audit(
        db,
        'STEWARDSHIP_ALERTS_ACCESSED',
        'StewardshipAlert',
        str(prescription_id or 'LIST'),
        'AMRGuard',
        {'prescription_id': prescription_id, 'status': status, 'count': len(rows)},
        principal=principal,
    )
    db.commit()
    return rows


@app.post('/api/v1/stewardship/alerts/{alert_id}/disposition', response_model=StewardshipAlertResponse)
def disposition_stewardship_alert(
    alert_id: str,
    payload: AlertDispositionRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(
        require_human_roles(
            ROLE_STEWARDSHIP_OFFICER,
            ROLE_PRESCRIBER,
            ROLE_PHARMACIST,
            ROLE_FACILITY_ADMIN,
        )
    ),
):
    """Records clinician or stewardship officer review disposition and clinical rationale for an alert."""
    alert = db.scalar(select(StewardshipAlert).where(StewardshipAlert.alert_id == alert_id))
    if not alert:
        raise HTTPException(404, 'Stewardship alert not found')

    rx = db.get(Prescription, alert.prescription_id)
    if rx:
        allowed_facilities = authorized_facility_ids_for_human(
            principal,
            db,
            {ROLE_STEWARDSHIP_OFFICER, ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_FACILITY_ADMIN},
        )
        if rx.facility_id not in allowed_facilities:
            audit_authz_denied(
                db,
                principal,
                action='disposition_stewardship_alert',
                entity_type='StewardshipAlert',
                entity_id=alert.alert_id,
                facility_id=rx.facility_id,
                reason='unauthorized_facility_alert',
            )
            raise HTTPException(403, 'Not authorized to disposition alerts for this prescription facility')

    try:
        updated_alert = record_alert_disposition(
            db,
            alert_id=alert_id,
            outcome=payload.outcome,
            reason=payload.reason,
            user_id=principal.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))

    audit(
        db,
        'STEWARDSHIP_ALERT_DISPOSITIONED',
        'StewardshipAlert',
        updated_alert.alert_id,
        principal.username or principal.actor_id,
        {
            'outcome': payload.outcome,
            'reason': payload.reason,
            'prescription_id': updated_alert.prescription_id,
            'rule_code': updated_alert.rule_code,
        },
        principal=principal,
        facility_id=rx.facility_id if rx else None,
    )
    db.commit()
    return updated_alert


@app.post('/api/v1/stewardship/ai-assist', response_model=AIAssistanceResponse)
def stewardship_ai_assist(
    payload: AIAssistanceRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(
        require_human_roles(
            ROLE_STEWARDSHIP_OFFICER,
            ROLE_PRESCRIBER,
            ROLE_PHARMACIST,
            ROLE_FACILITY_ADMIN,
            ROLE_NATIONAL_ANALYST,
        )
    ),
):
    """Provides bounded, read-only clinical rationale explanations and guideline retrieval."""
    if payload.scenario == 'PRESCRIPTION_VALIDATION_EXPLAIN':
        if not payload.prescription_id:
            raise HTTPException(400, 'prescription_id is required for PRESCRIPTION_VALIDATION_EXPLAIN')
        rx = db.get(Prescription, payload.prescription_id)
        if not rx:
            raise HTTPException(404, 'Prescription not found')

        if not has_national_aggregate_scope(principal):
            allowed_facilities = authorized_facility_ids_for_human(
                principal,
                db,
                {ROLE_STEWARDSHIP_OFFICER, ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_FACILITY_ADMIN},
            )
            if rx.facility_id not in allowed_facilities:
                audit_authz_denied(
                    db,
                    principal,
                    action='ai_assist_prescription_explain',
                    entity_type='Prescription',
                    entity_id=rx.id,
                    facility_id=rx.facility_id,
                    reason='unauthorized_facility_prescription',
                )
                raise HTTPException(403, 'Not authorized for this prescription facility')

        res = explain_prescription_validation(db, rx)

    elif payload.scenario == 'STEWARDSHIP_ALERT_EXPLAIN':
        if not payload.alert_id:
            raise HTTPException(400, 'alert_id is required for STEWARDSHIP_ALERT_EXPLAIN')
        alert = db.scalar(select(StewardshipAlert).where(StewardshipAlert.alert_id == payload.alert_id))
        if not alert:
            raise HTTPException(404, 'Stewardship alert not found')

        rx = db.get(Prescription, alert.prescription_id)
        if rx and not has_national_aggregate_scope(principal):
            allowed_facilities = authorized_facility_ids_for_human(
                principal,
                db,
                {ROLE_STEWARDSHIP_OFFICER, ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_FACILITY_ADMIN},
            )
            if rx.facility_id not in allowed_facilities:
                audit_authz_denied(
                    db,
                    principal,
                    action='ai_assist_alert_explain',
                    entity_type='StewardshipAlert',
                    entity_id=alert.alert_id,
                    facility_id=rx.facility_id,
                    reason='unauthorized_facility_alert',
                )
                raise HTTPException(403, 'Not authorized for this alert facility')

        res = explain_stewardship_alert(db, alert)

    elif payload.scenario == 'AGGREGATE_TREND_SUMMARY':
        target_facility_id = payload.facility_id
        if not has_national_aggregate_scope(principal):
            allowed_facilities = authorized_facility_ids_for_human(
                principal,
                db,
                {ROLE_STEWARDSHIP_OFFICER, ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_FACILITY_ADMIN},
            )
            if target_facility_id is not None:
                if target_facility_id not in allowed_facilities:
                    audit_authz_denied(
                        db,
                        principal,
                        action='ai_assist_trend_summary',
                        entity_type='Facility',
                        entity_id=target_facility_id,
                        facility_id=target_facility_id,
                        reason='unauthorized_facility_trend',
                    )
                    raise HTTPException(403, 'Not authorized for this facility')
            elif len(allowed_facilities) == 1:
                target_facility_id = next(iter(allowed_facilities))

        res = summarize_stewardship_trends(db, facility_id=target_facility_id)
    else:
        raise HTTPException(400, f'Unsupported scenario {payload.scenario}')

    audit(
        db,
        'AI_ASSISTANCE_REQUESTED',
        'StewardshipIntelligence',
        str(payload.prescription_id or payload.alert_id or payload.facility_id or 'GENERAL'),
        principal.username or principal.actor_id,
        {'scenario': payload.scenario, 'model_version': res['model_version']},
        principal=principal,
    )
    db.commit()
    return res


@app.post('/api/v1/demo/prescriptions')
def create_demo_prescription(
    payload: DemoPrescriptionCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PRESCRIBER, ROLE_FACILITY_ADMIN)),
):
    if settings.app_env not in {'demo', 'test', 'development', 'funder_demo'}:
        raise HTTPException(404, 'Demo prescription endpoint unavailable')
    fac = db.scalar(select(Facility).where(Facility.code == 'FAC-KGL-001'))
    pr = db.scalar(select(Prescriber).where(Prescriber.external_user_id == 'EBZ-USER-001'))
    ab = db.scalar(select(Antibiotic).where(Antibiotic.code == payload.antibiotic_code))
    if not fac or not pr or not ab:
        raise HTTPException(500, 'Demo data is not initialized')
    allowed_facilities = authorized_facility_ids_for_human(principal, db, {ROLE_PRESCRIBER, ROLE_FACILITY_ADMIN})
    if fac.id not in allowed_facilities:
        audit_authz_denied(
            db,
            principal,
            action='demo_create_prescription',
            entity_type='Facility',
            entity_id=fac.id,
            facility_id=fac.id,
            reason='demo_facility_out_of_scope',
        )
        raise HTTPException(403, 'Not authorized for demo facility')
    if db.scalar(select(Prescription).where(Prescription.external_id == payload.external_id)):
        raise HTTPException(409, 'External prescription ID already exists')

    rule = db.scalar(
        select(AntibioticRule).where(AntibioticRule.antibiotic_id == ab.id, AntibioticRule.enabled.is_(True))
    )
    rx = Prescription(
        external_id=payload.external_id,
        patient_reference=payload.patient_reference,
        prescriber_id=pr.id,
        facility_id=fac.id,
        expires_at=payload.expires_at,
    )
    db.add(rx)
    db.flush()
    item = PrescriptionItem(
        prescription_id=rx.id,
        antibiotic_id=ab.id,
        dose=payload.dose,
        frequency_per_day=payload.frequency_per_day,
        duration_days=payload.duration_days,
        quantity=payload.quantity,
        indication=payload.indication,
    )
    db.add(item)
    db.flush()
    issues = validate_item(item, rule)
    blocks = [i for i in issues if i['severity'] == 'BLOCK']
    rx.status = 'BLOCKED' if blocks else ('WARNING' if issues else 'VALIDATED')
    evaluate_prescription_rules(db, rx, auto_commit=False)
    audit(
        db,
        'DEMO_PRESCRIPTION_CREATED',
        'Prescription',
        rx.id,
        'e-Buzima Simulator',
        {'external_id': rx.external_id},
        principal=principal,
        facility_id=fac.id,
    )
    db.commit()
    return {'prescription': prescription_detail(rx, db), 'issues': issues}


@app.post('/api/v1/demo/risk-scenario')
def demo_risk_scenario(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PRESCRIBER, ROLE_FACILITY_ADMIN)),
):
    """Create a deliberately invalid demo prescription to demonstrate a dispensing-control block."""
    if settings.app_env not in {'demo', 'test', 'development', 'funder_demo'}:
        raise HTTPException(404, 'Demo scenario unavailable')
    fac = db.scalar(select(Facility).where(Facility.code == 'FAC-KGL-001'))
    pr = db.scalar(select(Prescriber).where(Prescriber.external_user_id == 'EBZ-USER-001'))
    ab = db.scalar(select(Antibiotic).where(Antibiotic.code == 'AMX500CAP'))
    if not fac or not pr or not ab:
        raise HTTPException(500, 'Demo data is not initialized')
    allowed_facilities = authorized_facility_ids_for_human(principal, db, {ROLE_PRESCRIBER, ROLE_FACILITY_ADMIN})
    if fac.id not in allowed_facilities:
        audit_authz_denied(
            db,
            principal,
            action='demo_risk_scenario',
            entity_type='Facility',
            entity_id=fac.id,
            facility_id=fac.id,
            reason='demo_facility_out_of_scope',
        )
        raise HTTPException(403, 'Not authorized for demo facility')

    external = f'EBZ-RISK-{uuid4().hex[:10].upper()}'
    rx = Prescription(
        external_id=external,
        patient_reference='PATIENT-DEMO-RISK',
        prescriber_id=pr.id,
        facility_id=fac.id,
    )
    db.add(rx)
    db.flush()
    item = PrescriptionItem(
        prescription_id=rx.id,
        antibiotic_id=ab.id,
        dose=500,
        frequency_per_day=3,
        duration_days=5,
        quantity=20,
        indication='Demo risk scenario',
    )
    db.add(item)
    db.flush()
    rule = db.scalar(
        select(AntibioticRule).where(AntibioticRule.antibiotic_id == ab.id, AntibioticRule.enabled.is_(True))
    )
    issues = validate_item(item, rule)
    rx.status = 'BLOCKED'
    evaluate_prescription_rules(db, rx, auto_commit=False)
    audit(
        db,
        'DEMO_RISK_SCENARIO',
        'Prescription',
        rx.id,
        'AMRGuard Demo',
        {'reason': 'Intentional quantity mismatch', 'issues': issues},
        principal=principal,
        facility_id=fac.id,
    )
    db.commit()
    return {'prescription': prescription_detail(rx, db), 'issues': issues, 'scenario': 'intentional_block'}


@app.post('/api/v1/prescriptions/{prescription_id}/activate')
def activate_prescription(
    prescription_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_authenticated_principal),
):
    rx = db.get(Prescription, prescription_id)
    if not rx:
        raise HTTPException(404, 'Prescription not found')

    if principal.actor_type == 'HUMAN':
        allowed_facilities = authorized_facility_ids_for_human(
            principal, db, {ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_FACILITY_ADMIN}
        )
        if rx.facility_id not in allowed_facilities:
            audit_authz_denied(
                db,
                principal,
                action='activate_prescription',
                entity_type='Prescription',
                entity_id=rx.id,
                facility_id=rx.facility_id,
                reason='unauthorized_role_or_facility',
            )
            raise HTTPException(403, 'Not authorized to activate this prescription')
    elif not service_client_allows_facility(principal, SCOPE_EBUZIMA_RX_WRITE, rx.facility_id):
        audit_authz_denied(
            db,
            principal,
            action='activate_prescription',
            entity_type='Prescription',
            entity_id=rx.id,
            facility_id=rx.facility_id,
            reason='service_scope_or_facility_denied',
        )
        raise HTTPException(403, 'Service client not authorized to activate prescriptions for this facility')

    if rx.status not in {'VALIDATED', 'WARNING'}:
        raise HTTPException(409, f'Prescription is {rx.status}')
    if rx.expires_at and is_expired(rx.expires_at):
        rx.status = 'EXPIRED'
        audit(
            db,
            'PRESCRIPTION_EXPIRED',
            'Prescription',
            rx.id,
            'AMRGuard',
            {'stage': 'ACTIVATION'},
            principal=principal,
            facility_id=rx.facility_id,
            outcome='DENIED',
        )
        db.commit()
        raise HTTPException(409, 'Prescription has expired')
    rx.status = 'ACTIVE'
    audit(
        db,
        'PRESCRIPTION_ACTIVATED',
        'Prescription',
        rx.id,
        'AMRGuard',
        principal=principal,
        facility_id=rx.facility_id,
    )
    db.commit()
    return prescription_detail(rx, db)


@app.get('/api/v1/transactions')
def transactions(
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN)),
):
    allowed_pharmacies = authorized_pharmacy_ids_for_human(
        principal, db, {ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
    )
    allowed_facilities = authorized_facility_ids_for_human(
        principal, db, {ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
    )
    if not allowed_pharmacies and not allowed_facilities:
        return []

    conditions = []
    if allowed_pharmacies:
        conditions.append(DispensingTransaction.pharmacy_id.in_(allowed_pharmacies))
    if allowed_facilities:
        conditions.append(DispensingTransaction.prescribing_facility_id.in_(allowed_facilities))
        conditions.append(Prescription.facility_id.in_(allowed_facilities))

    rows = db.scalars(
        select(DispensingTransaction)
        .join(Prescription, Prescription.id == DispensingTransaction.prescription_id)
        .where(or_(*conditions))
        .order_by(DispensingTransaction.created_at.desc())
        .limit(limit)
    ).all()
    result = []
    for transaction in rows:
        prescription = db.get(Prescription, transaction.prescription_id)
        result.append(
            {
                'transaction_id': transaction.transaction_id,
                'prescription_id': transaction.prescription_id,
                'prescription_code': f'AMR-RX-{transaction.prescription_id:06d}',
                'external_id': prescription.external_id if prescription else None,
                'pharmacy_id': transaction.pharmacy_id,
                'batch_id': transaction.batch_id,
                'actor_user_id': transaction.actor_user_id,
                'prescribing_facility_id': transaction.prescribing_facility_id,
                'dispensing_facility_id': transaction.dispensing_facility_id,
                'is_cross_facility': transaction.is_cross_facility,
                'quantity': transaction.quantity,
                'status': transaction.status,
                'payment_reference': transaction.payment_reference,
                'created_at': transaction.created_at,
            }
        )
    return result


@app.get('/api/v1/pharmacies')
def pharmacies(
    db: Session = Depends(get_db),
    principal: Principal = Depends(
        require_human_roles(
            ROLE_PHARMACIST,
            ROLE_PHARMACY_ASSISTANT,
            ROLE_PRESCRIBER,
            ROLE_STEWARDSHIP_OFFICER,
            ROLE_FACILITY_ADMIN,
            ROLE_PLATFORM_OPERATOR,
        )
    ),
):
    if has_platform_operator_scope(principal):
        rows = db.scalars(select(Pharmacy).order_by(Pharmacy.id)).all()
    else:
        allowed_pharmacies = authorized_pharmacy_ids_for_human(
            principal,
            db,
            {ROLE_PHARMACIST, ROLE_PHARMACY_ASSISTANT, ROLE_PRESCRIBER, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN},
        )
        if not allowed_pharmacies:
            return []
        rows = db.scalars(select(Pharmacy).where(Pharmacy.id.in_(allowed_pharmacies)).order_by(Pharmacy.id)).all()
    return [
        {
            'id': p.id,
            'code': p.code,
            'name': p.name,
            'district': p.district,
            'facility_id': p.facility_id,
            'pharmacy_type': p.pharmacy_type,
            'active': p.active,
        }
        for p in rows
    ]


@app.get('/api/v1/pharmacies/{pharmacy_id}/stock')
def pharmacy_stock(
    pharmacy_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(
        require_human_roles(ROLE_PHARMACIST, ROLE_PHARMACY_ASSISTANT, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN)
    ),
):
    if not db.get(Pharmacy, pharmacy_id):
        raise HTTPException(404, 'Pharmacy not found')
    allowed_pharmacies = authorized_pharmacy_ids_for_human(
        principal, db, {ROLE_PHARMACIST, ROLE_PHARMACY_ASSISTANT, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
    )
    if pharmacy_id not in allowed_pharmacies:
        audit_authz_denied(
            db,
            principal,
            action='read_pharmacy_stock',
            entity_type='Pharmacy',
            entity_id=pharmacy_id,
            pharmacy_id=pharmacy_id,
            reason='cross_pharmacy_stock_read_denied',
        )
        raise HTTPException(403, 'Not authorized to view stock for this pharmacy')
    return [
        {
            'id': b.id,
            'antibiotic_id': b.antibiotic_id,
            'batch_number': b.batch_number,
            'expiry_date': b.expiry_date,
            'quantity_available': b.quantity_available,
        }
        for b in db.scalars(
            select(StockBatch).where(StockBatch.pharmacy_id == pharmacy_id).order_by(StockBatch.expiry_date)
        ).all()
    ]


def _build_dispense_replay_response(
    prior: DispensingTransaction, prescription_id: int, request: DispenseRequest, db: Session
):
    replay_item_id = request.item_id
    replay_prescription = db.get(Prescription, prescription_id)
    if replay_item_id is None and replay_prescription and len(replay_prescription.items) == 1:
        replay_item_id = replay_prescription.items[0].id
    if (prior.prescription_id, prior.pharmacy_id, prior.batch_id, prior.item_id, prior.quantity) != (
        prescription_id,
        request.pharmacy_id,
        request.batch_id,
        replay_item_id,
        request.quantity,
    ):
        raise HTTPException(409, 'Idempotency key was already used for a different dispensing request')
    return {
        'authorized': True,
        'replayed': True,
        'transaction_id': prior.transaction_id,
        'actor_user_id': prior.actor_user_id,
        'prescribing_facility_id': prior.prescribing_facility_id,
        'dispensing_facility_id': prior.dispensing_facility_id,
        'is_cross_facility': prior.is_cross_facility,
        'quantity_dispensed': prior.quantity,
        'remaining': None,
        'prescription_status': replay_prescription.status if replay_prescription else prior.status,
    }


@app.post('/api/v1/prescriptions/{prescription_id}/dispense')
def dispense(
    prescription_id: int,
    request: DispenseRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PHARMACIST)),
):
    # Enforce pharmacist membership on the target pharmacy BEFORE any idempotency replay lookup
    allowed_pharmacies = authorized_pharmacy_ids_for_human(principal, db, {ROLE_PHARMACIST})
    if request.pharmacy_id not in allowed_pharmacies:
        audit_authz_denied(
            db,
            principal,
            action='dispense_prescription',
            entity_type='Pharmacy',
            entity_id=request.pharmacy_id,
            pharmacy_id=request.pharmacy_id,
            reason='actor_not_authorized_pharmacist_for_pharmacy',
        )
        raise HTTPException(403, 'Authenticated pharmacist is not authorized for this pharmacy')

    prior = db.scalar(
        select(DispensingTransaction).where(DispensingTransaction.idempotency_key == request.idempotency_key)
    )
    if prior:
        if prior.pharmacy_id != request.pharmacy_id:
            audit_authz_denied(
                db,
                principal,
                action='dispense_replay',
                entity_type='DispensingTransaction',
                entity_id=prior.transaction_id,
                pharmacy_id=request.pharmacy_id,
                reason='idempotency_key_cross_pharmacy_conflict',
            )
            raise HTTPException(409, 'Idempotency key was already used for a different dispensing request')
        return _build_dispense_replay_response(prior, prescription_id, request, db)

    rx = db.scalar(select(Prescription).where(Prescription.id == prescription_id).with_for_update())
    if not rx:
        raise HTTPException(404, 'Prescription not found')

    pharmacy = db.get(Pharmacy, request.pharmacy_id)
    if not pharmacy or not pharmacy.active:
        raise HTTPException(403, 'Pharmacy is not active')

    if request.item_id is None:
        if len(rx.items) != 1:
            raise HTTPException(422, 'item_id is required when a prescription contains multiple items')
        item = rx.items[0]
    else:
        item = next((prescription_item for prescription_item in rx.items if prescription_item.id == request.item_id), None)
        if not item:
            raise HTTPException(404, 'Prescription item not found')

    antibiotic = db.get(Antibiotic, item.antibiotic_id)
    if not antibiotic or not antibiotic.active:
        raise HTTPException(409, 'Prescribed antibiotic catalogue item is not active')

    _, cred = verify_credential(
        request.credential,
        db,
        principal=principal,
        expected_prescription_id=rx.id,
        pharmacy_id=pharmacy.id,
    )

    if rx.status not in {'ACTIVE', 'PARTIALLY_DISPENSED'}:
        raise HTTPException(409, f'Prescription status is {rx.status}')
    if rx.expires_at and is_expired(rx.expires_at):
        rx.status = 'EXPIRED'
        audit(
            db,
            'PRESCRIPTION_EXPIRED',
            'Prescription',
            rx.id,
            'Pharmacy',
            {'stage': 'DISPENSE'},
            principal=principal,
            facility_id=rx.facility_id,
            pharmacy_id=pharmacy.id,
            outcome='DENIED',
        )
        db.commit()
        raise HTTPException(409, 'Prescription has expired')

    # Enforce Decision 2: same-facility or strictly authorized conditional cross-facility dispensing
    authz = evaluate_prescription_dispensing_authorization(principal, rx, pharmacy, antibiotic.code, db)
    if not authz.allowed:
        db.rollback()
        audit_authz_denied(
            db,
            principal,
            action='dispense_prescription',
            entity_type='Prescription',
            entity_id=rx.id,
            facility_id=rx.facility_id,
            pharmacy_id=pharmacy.id,
            reason=authz.reason,
        )
        raise HTTPException(403, authz.reason)

    allocations = request.allocations or [BatchAllocation(batch_id=request.batch_id, quantity=request.quantity)]
    total_quantity = sum(a.quantity for a in allocations)
    if total_quantity <= 0:
        raise HTTPException(422, 'Total quantity to dispense must be greater than zero')

    allocated_batches: list[tuple[StockBatch, int]] = []
    for a in allocations:
        b = db.scalar(select(StockBatch).where(StockBatch.id == a.batch_id).with_for_update())
        if not b:
            raise HTTPException(404, f'Stock batch {a.batch_id} not found')
        if b.pharmacy_id != request.pharmacy_id:
            audit_authz_denied(
                db,
                principal,
                action='dispense_prescription',
                entity_type='StockBatch',
                entity_id=b.id,
                facility_id=rx.facility_id,
                pharmacy_id=request.pharmacy_id,
                reason='batch_belongs_to_different_pharmacy',
            )
            raise HTTPException(403, f'Batch {b.id} does not belong to this pharmacy')
        if b.expiry_date < utcnow().date():
            raise HTTPException(409, f'Stock batch {b.batch_number} has expired')
        if b.antibiotic_id != item.antibiotic_id:
            raise HTTPException(409, f'Batch {b.batch_number} antibiotic does not match prescription')
        if a.quantity > b.quantity_available:
            raise HTTPException(409, f'Insufficient stock in batch {b.batch_number} (requested {a.quantity}, available {b.quantity_available})')
        allocated_batches.append((b, a.quantity))

    dispensed_by_item = {
        prescription_item.id: (
            db.scalar(
                select(func.coalesce(func.sum(DispensingTransaction.quantity), 0)).where(
                    DispensingTransaction.prescription_id == rx.id,
                    DispensingTransaction.item_id == prescription_item.id,
                )
            )
            or 0
        )
        for prescription_item in rx.items
    }
    remaining = item.quantity - int(dispensed_by_item[item.id])
    if total_quantity > remaining:
        raise HTTPException(409, f'Quantity exceeds authorized remaining quantity ({remaining})')

    txid = f'DT-{secrets.token_hex(6).upper()}'
    primary_batch = allocated_batches[0][0]
    tx = DispensingTransaction(
        transaction_id=txid,
        idempotency_key=request.idempotency_key,
        prescription_id=rx.id,
        item_id=item.id,
        pharmacy_id=pharmacy.id,
        batch_id=primary_batch.id,
        actor_user_id=principal.user_id,
        prescribing_facility_id=rx.facility_id,
        dispensing_facility_id=pharmacy.facility_id,
        is_cross_facility=authz.is_cross_facility,
        quantity=total_quantity,
        reconciliation_status='PENDING_RECONCILIATION',
        payment_reference=request.payment_reference,
    )
    db.add(tx)
    db.flush()

    fulfillment_status = 'FULL' if (remaining - total_quantity == 0) else 'PARTIAL'
    disp_item = DispensingItem(
        transaction_id=tx.id,
        prescription_item_id=item.id,
        quantity_requested=remaining,
        quantity_dispensed=total_quantity,
        fulfillment_status=fulfillment_status,
    )
    db.add(disp_item)
    db.flush()

    for b, qty in allocated_batches:
        b.quantity_available -= qty
        link = DispensingBatchLink(
            dispensing_item_id=disp_item.id,
            batch_id=b.id,
            quantity=qty,
        )
        db.add(link)
        ref_id = f'{txid}-B{b.id}' if len(allocated_batches) > 1 else txid
        db.add(
            StockEvent(
                batch_id=b.id,
                event_type='DISPENSING',
                quantity=-qty,
                reference_id=ref_id,
                source_system='AMRGuard',
                details=json.dumps(
                    {
                        'prescription_id': rx.id,
                        'pharmacy_id': pharmacy.id,
                        'actor_user_id': principal.user_id,
                        'is_cross_facility': authz.is_cross_facility,
                    }
                ),
            )
        )

    # Durable Outbox event
    recon_payload = {
        'event_type': 'DISPENSING_RECONCILIATION',
        'transaction_id': txid,
        'prescription_id': rx.id,
        'prescription_external_id': rx.external_id,
        'item_id': item.id,
        'pharmacy_code': pharmacy.code,
        'facility_id': pharmacy.facility_id,
        'quantity_dispensed': total_quantity,
        'allocations': [{'batch_id': b.id, 'batch_number': b.batch_number, 'quantity': qty} for b, qty in allocated_batches],
        'actor_user_id': principal.user_id,
        'timestamp': utcnow().isoformat(),
    }
    outbox_entry = IntegrationOutbox(
        destination_system='RMS_DISPENSE_RECONCILE',
        event_type='DISPENSING_RECONCILIATION',
        aggregate_type='DispensingTransaction',
        aggregate_id=txid,
        payload=json.dumps(recon_payload),
        status='PENDING',
        retry_count=0,
        next_attempt_at=utcnow(),
    )
    db.add(outbox_entry)

    ebuzima_outbox_entry = IntegrationOutbox(
        destination_system='EBUZIMA_DISPENSE_UPDATE',
        event_type='DISPENSING_RECONCILIATION',
        aggregate_type='DispensingTransaction',
        aggregate_id=txid,
        payload=json.dumps(recon_payload),
        status='PENDING',
        retry_count=0,
        next_attempt_at=utcnow(),
    )
    db.add(ebuzima_outbox_entry)

    new_item_remaining = remaining - total_quantity
    total_remaining = (
        sum(prescription_item.quantity - int(dispensed_by_item[prescription_item.id]) for prescription_item in rx.items)
        - total_quantity
    )
    rx.status = 'COMPLETED' if total_remaining == 0 else 'PARTIALLY_DISPENSED'
    cred.used_count += 1
    if rx.status == 'COMPLETED':
        cred.revoked = True
        cred.revoked_at = utcnow()
        cred.revoked_by_user_id = principal.user_id

    audit(
        db,
        'DISPENSED',
        'Prescription',
        rx.id,
        'Pharmacy',
        {
            'transaction_id': txid,
            'batch_id': primary_batch.id,
            'item_id': item.id,
            'quantity': total_quantity,
            'pharmacy_id': pharmacy.id,
            'prescribing_facility_id': rx.facility_id,
            'dispensing_facility_id': pharmacy.facility_id,
            'is_cross_facility': authz.is_cross_facility,
            'network_id': authz.network_id,
            'allocations': [{'batch_id': b.id, 'quantity': qty} for b, qty in allocated_batches],
        },
        principal=principal,
        facility_id=rx.facility_id,
        pharmacy_id=pharmacy.id,
    )
    db.flush()
    create_due_stewardship_review(rx.id, utcnow(), db, principal=principal, facility_id=rx.facility_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.scalar(
            select(DispensingTransaction).where(DispensingTransaction.idempotency_key == request.idempotency_key)
        )
        if prior:
            if prior.pharmacy_id != request.pharmacy_id:
                raise HTTPException(409, 'Idempotency key was already used for a different dispensing request')
            return _build_dispense_replay_response(prior, prescription_id, request, db)
        raise HTTPException(409, 'Conflicting dispensing transaction')
    return {
        'authorized': True,
        'replayed': False,
        'transaction_id': txid,
        'actor_user_id': principal.user_id,
        'prescribing_facility_id': rx.facility_id,
        'dispensing_facility_id': pharmacy.facility_id,
        'is_cross_facility': authz.is_cross_facility,
        'item_id': item.id,
        'quantity_dispensed': total_quantity,
        'remaining': new_item_remaining,
        'prescription_remaining': total_remaining,
        'prescription_status': rx.status,
        'allocations': [{'batch_id': b.id, 'quantity': qty} for b, qty in allocated_batches],
        'outbox_id': outbox_entry.id,
    }


@app.get('/api/v1/traceability/batches/{batch_id}')
def batch_trace(
    batch_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN)),
):
    b = db.get(StockBatch, batch_id)
    if not b:
        raise HTTPException(404, 'Batch not found')
    allowed_pharmacies = authorized_pharmacy_ids_for_human(
        principal, db, {ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
    )
    if b.pharmacy_id not in allowed_pharmacies:
        audit_authz_denied(
            db,
            principal,
            action='read_batch_traceability',
            entity_type='StockBatch',
            entity_id=b.id,
            pharmacy_id=b.pharmacy_id,
            reason='cross_pharmacy_traceability_denied',
        )
        raise HTTPException(403, 'Not authorized to view traceability for this pharmacy batch')

    p = db.get(Pharmacy, b.pharmacy_id)
    ab = db.get(Antibiotic, b.antibiotic_id)
    if not p or not ab:
        raise HTTPException(404, 'Batch references an unknown pharmacy or antibiotic')
    events = db.scalars(select(StockEvent).where(StockEvent.batch_id == batch_id).order_by(StockEvent.created_at)).all()
    tx_rows = db.scalars(
        select(DispensingTransaction)
        .where(DispensingTransaction.batch_id == batch_id)
        .order_by(DispensingTransaction.created_at.desc())
    ).all()
    linked = []
    for transaction in tx_rows:
        prescription = db.get(Prescription, transaction.prescription_id)
        if prescription:
            linked.append(
                {
                    'transaction_id': transaction.transaction_id,
                    'prescription_id': prescription.id,
                    'prescription_code': f'AMR-RX-{prescription.id:06d}',
                    'external_id': prescription.external_id,
                    'actor_user_id': transaction.actor_user_id,
                    'prescribing_facility_id': transaction.prescribing_facility_id,
                    'dispensing_facility_id': transaction.dispensing_facility_id,
                    'is_cross_facility': transaction.is_cross_facility,
                    'quantity': transaction.quantity,
                    'status': transaction.status,
                    'created_at': transaction.created_at,
                }
            )
    return {
        'batch': {
            'id': b.id,
            'batch_number': b.batch_number,
            'antibiotic': ab.generic_name,
            'antibiotic_code': ab.code,
            'strength': ab.strength,
            'expiry_date': b.expiry_date,
            'current_quantity': b.quantity_available,
            'pharmacy': p.name,
            'pharmacy_id': p.id,
            'source_reference': b.source_reference,
        },
        'events': [
            {
                'type': e.event_type,
                'quantity': e.quantity,
                'reference': e.reference_id,
                'source': e.source_system,
                'details': json.loads(e.details or '{}'),
                'created_at': e.created_at,
            }
            for e in events
        ],
        'linked_transactions': linked,
    }


@app.get('/api/v1/integrations/ebuzima/prescriptions/{prescription_id}/fhir')
def prescription_fhir(
    prescription_id: int,
    bundle: bool = Query(default=True, description='Return full FHIR R4 Bundle'),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_authenticated_principal),
):
    rx = db.get(Prescription, prescription_id)
    if not rx:
        raise HTTPException(404, 'Prescription not found')

    if principal.actor_type == 'HUMAN':
        allowed_facilities = authorized_facility_ids_for_human(
            principal, db, {ROLE_PRESCRIBER, ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
        )
        if rx.facility_id not in allowed_facilities:
            audit_authz_denied(
                db,
                principal,
                action='read_prescription_fhir',
                entity_type='Prescription',
                entity_id=rx.id,
                facility_id=rx.facility_id,
                reason='cross_facility_fhir_export_denied',
            )
            raise HTTPException(403, 'Not authorized to export FHIR prescription for this facility')
    elif not service_client_allows_facility(principal, SCOPE_EBUZIMA_RX_READ, rx.facility_id):
        audit_authz_denied(
            db,
            principal,
            action='read_prescription_fhir',
            entity_type='Prescription',
            entity_id=rx.id,
            facility_id=rx.facility_id,
            reason='service_scope_or_facility_denied',
        )
        raise HTTPException(403, 'Service client not authorized to read prescriptions for this facility')

    audit(
        db,
        'PRESCRIPTION_FHIR_ACCESSED',
        'Prescription',
        rx.id,
        'AMRGuard',
        principal=principal,
        facility_id=rx.facility_id,
    )
    db.commit()
    return prescription_to_medication_request(rx, db, prefer_bundle=bundle)


@app.get('/api/v1/integrations/dispensing/{transaction_id}/fhir')
def dispensing_fhir(
    transaction_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_authenticated_principal),
):
    tx = db.scalar(select(DispensingTransaction).where(DispensingTransaction.transaction_id == transaction_id))
    if not tx:
        raise HTTPException(404, 'Transaction not found')
    rx = db.get(Prescription, tx.prescription_id)

    if principal.actor_type == 'HUMAN':
        allowed_pharmacies = authorized_pharmacy_ids_for_human(
            principal, db, {ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
        )
        allowed_facilities = authorized_facility_ids_for_human(
            principal, db, {ROLE_PHARMACIST, ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
        )
        if tx.pharmacy_id not in allowed_pharmacies and (not rx or rx.facility_id not in allowed_facilities):
            audit_authz_denied(
                db,
                principal,
                action='read_dispensing_fhir',
                entity_type='DispensingTransaction',
                entity_id=tx.transaction_id,
                facility_id=rx.facility_id if rx else None,
                pharmacy_id=tx.pharmacy_id,
                reason='cross_tenant_fhir_export_denied',
            )
            raise HTTPException(403, 'Not authorized to export FHIR dispensing transaction')
    else:
        allowed_by_pharmacy = service_client_allows_pharmacy(principal, SCOPE_DISPENSING_READ, tx.pharmacy_id)
        allowed_by_facility = bool(rx and service_client_allows_facility(principal, SCOPE_DISPENSING_READ, rx.facility_id))
        if not (allowed_by_pharmacy or allowed_by_facility):
            audit_authz_denied(
                db,
                principal,
                action='read_dispensing_fhir',
                entity_type='DispensingTransaction',
                entity_id=tx.transaction_id,
                facility_id=rx.facility_id if rx else None,
                pharmacy_id=tx.pharmacy_id,
                reason='service_scope_or_tenant_denied',
            )
            raise HTTPException(403, 'Service client not authorized to read this dispensing transaction')

    audit(
        db,
        'DISPENSING_FHIR_ACCESSED',
        'DispensingTransaction',
        tx.transaction_id,
        'AMRGuard',
        principal=principal,
        facility_id=rx.facility_id if rx else None,
        pharmacy_id=tx.pharmacy_id,
    )
    db.commit()
    return dispensing_to_medication_dispense(tx, db)


@app.get('/api/v1/audit')
def audit_events(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    principal: Principal = Depends(
        require_human_roles(ROLE_FACILITY_ADMIN, ROLE_STEWARDSHIP_OFFICER, ROLE_PLATFORM_OPERATOR)
    ),
):
    allowed_facilities = authorized_facility_ids_for_human(
        principal, db, {ROLE_FACILITY_ADMIN, ROLE_STEWARDSHIP_OFFICER}, include_pharmacy_parent_facility=False
    )
    is_platform_op = has_platform_operator_scope(principal)

    query = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if allowed_facilities and is_platform_op:
        query = query.where(
            or_(
                AuditEvent.facility_id.in_(allowed_facilities),
                AuditEvent.entity_type.in_(TECHNICAL_AUDIT_ENTITY_TYPES),
            )
        )
    elif allowed_facilities:
        query = query.where(AuditEvent.facility_id.in_(allowed_facilities))
    elif is_platform_op:
        # Platform operators have no implicit clinical access; technical/auth audit rows only
        query = query.where(AuditEvent.entity_type.in_(TECHNICAL_AUDIT_ENTITY_TYPES))
    else:
        return []

    rows = db.scalars(query).all()
    audit(
        db,
        'AUDIT_LOG_ACCESSED',
        'AuditEvent',
        'list',
        'AMRGuard',
        {'returned_count': len(rows)},
        principal=principal,
        facility_id=next(iter(allowed_facilities)) if len(allowed_facilities) == 1 else None,
    )
    db.commit()
    return [
        {
            'id': e.id,
            'event_type': e.event_type,
            'entity_type': e.entity_type,
            'entity_id': e.entity_id,
            'source_system': e.source_system,
            'actor_type': e.actor_type,
            'actor_id': e.actor_id,
            'facility_id': e.facility_id,
            'pharmacy_id': e.pharmacy_id,
            'correlation_id': e.correlation_id,
            'outcome': e.outcome,
            'details': json.loads(e.details or '{}'),
            'created_at': e.created_at,
        }
        for e in rows
    ]


@app.get('/api/v1/analytics/summary')
def analytics(
    db: Session = Depends(get_db),
    principal: Principal = Depends(
        require_human_roles(ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN, ROLE_PHARMACIST, ROLE_NATIONAL_ANALYST)
    ),
):
    if has_national_aggregate_scope(principal):
        prescriptions = db.scalar(select(func.count()).select_from(Prescription)) or 0
        validated = (
            db.scalar(
                select(func.count())
                .select_from(Prescription)
                .where(Prescription.status.in_(['VALIDATED', 'ACTIVE', 'PARTIALLY_DISPENSED', 'COMPLETED']))
            )
            or 0
        )
        blocked = db.scalar(select(func.count()).select_from(Prescription).where(Prescription.status == 'BLOCKED')) or 0
        dispensed = db.scalar(select(func.count(func.distinct(DispensingTransaction.prescription_id)))) or 0
        tx_count = db.scalar(select(func.count()).select_from(DispensingTransaction)) or 0
        units = db.scalar(select(func.coalesce(func.sum(DispensingTransaction.quantity), 0))) or 0
        active_batches = db.scalar(select(func.count()).select_from(StockBatch).where(StockBatch.quantity_available > 0)) or 0
        connected_pharmacies = db.scalar(select(func.count()).select_from(Pharmacy).where(Pharmacy.active.is_(True))) or 0
        total_reviews = db.scalar(select(func.count()).select_from(StewardshipReview)) or 0
        completed_reviews = (
            db.scalar(select(func.count()).select_from(StewardshipReview).where(StewardshipReview.status == 'COMPLETED'))
            or 0
        )
    else:
        allowed_facilities = authorized_facility_ids_for_human(
            principal, db, {ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN, ROLE_PHARMACIST}
        )
        allowed_pharmacies = authorized_pharmacy_ids_for_human(
            principal, db, {ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN, ROLE_PHARMACIST}
        )
        if not allowed_facilities and not allowed_pharmacies:
            return {
                'prescriptions': 0,
                'validated': 0,
                'blocked': 0,
                'dispensing_transactions': 0,
                'units_dispensed': 0,
                'active_batches': 0,
                'connected_pharmacies': 0,
                'prescriptions_with_dispense': 0,
                'prescription_dispense_reconciliation_rate': 0.0,
                'stewardship_reviews_total': 0,
                'stewardship_reviews_completed': 0,
                'stewardship_review_completion_rate': 0.0,
                'pending_stewardship_reviews': 0,
                'aware_breakdown': None,
            }
        rx_subq = select(Prescription.id).where(Prescription.facility_id.in_(allowed_facilities)) if allowed_facilities else None
        prescriptions = (
            db.scalar(select(func.count()).select_from(Prescription).where(Prescription.facility_id.in_(allowed_facilities)))
            or 0
            if allowed_facilities
            else 0
        )
        validated = (
            db.scalar(
                select(func.count())
                .select_from(Prescription)
                .where(
                    Prescription.facility_id.in_(allowed_facilities),
                    Prescription.status.in_(['VALIDATED', 'ACTIVE', 'PARTIALLY_DISPENSED', 'COMPLETED']),
                )
            )
            or 0
            if allowed_facilities
            else 0
        )
        blocked = (
            db.scalar(
                select(func.count())
                .select_from(Prescription)
                .where(Prescription.facility_id.in_(allowed_facilities), Prescription.status == 'BLOCKED')
            )
            or 0
            if allowed_facilities
            else 0
        )
        tx_filters = []
        if allowed_pharmacies:
            tx_filters.append(DispensingTransaction.pharmacy_id.in_(allowed_pharmacies))
        if rx_subq is not None:
            tx_filters.append(DispensingTransaction.prescription_id.in_(rx_subq))
        tx_cond = or_(*tx_filters)
        dispensed = (
            db.scalar(select(func.count(func.distinct(DispensingTransaction.prescription_id))).where(tx_cond)) or 0
        )
        tx_count = db.scalar(select(func.count()).select_from(DispensingTransaction).where(tx_cond)) or 0
        units = db.scalar(select(func.coalesce(func.sum(DispensingTransaction.quantity), 0)).where(tx_cond)) or 0
        active_batches = (
            db.scalar(
                select(func.count())
                .select_from(StockBatch)
                .where(StockBatch.pharmacy_id.in_(allowed_pharmacies), StockBatch.quantity_available > 0)
            )
            or 0
            if allowed_pharmacies
            else 0
        )
        connected_pharmacies = (
            db.scalar(
                select(func.count())
                .select_from(Pharmacy)
                .where(Pharmacy.id.in_(allowed_pharmacies), Pharmacy.active.is_(True))
            )
            or 0
            if allowed_pharmacies
            else 0
        )
        total_reviews = (
            db.scalar(
                select(func.count())
                .select_from(StewardshipReview)
                .where(StewardshipReview.prescription_id.in_(rx_subq))
            )
            or 0
            if rx_subq is not None
            else 0
        )
        completed_reviews = (
            db.scalar(
                select(func.count())
                .select_from(StewardshipReview)
                .where(StewardshipReview.prescription_id.in_(rx_subq), StewardshipReview.status == 'COMPLETED')
            )
            or 0
            if rx_subq is not None
            else 0
        )

    aware_facility_id = None if has_national_aggregate_scope(principal) else (
        next(iter(allowed_facilities)) if len(allowed_facilities) == 1 else None
    )
    aware_summary = calculate_aware_breakdown(db, facility_id=aware_facility_id)

    return {
        'prescriptions': prescriptions,
        'validated': validated,
        'blocked': blocked,
        'dispensing_transactions': tx_count,
        'units_dispensed': units,
        'active_batches': active_batches,
        'connected_pharmacies': connected_pharmacies,
        'prescriptions_with_dispense': dispensed,
        'prescription_dispense_reconciliation_rate': round(dispensed / max(prescriptions, 1) * 100, 1),
        'stewardship_reviews_total': total_reviews,
        'stewardship_reviews_completed': completed_reviews,
        'stewardship_review_completion_rate': round(completed_reviews / max(total_reviews, 1) * 100, 1),
        'pending_stewardship_reviews': total_reviews - completed_reviews,
        'aware_breakdown': aware_summary,
    }


@app.get('/api/v1/analytics/facilities')
def facility_analytics(
    db: Session = Depends(get_db),
    principal: Principal = Depends(
        require_human_roles(ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN, ROLE_NATIONAL_ANALYST)
    ),
):
    if has_national_aggregate_scope(principal):
        facilities_query = select(Facility).where(Facility.active.is_(True)).order_by(Facility.name)
    else:
        allowed_facilities = authorized_facility_ids_for_human(
            principal, db, {ROLE_STEWARDSHIP_OFFICER, ROLE_FACILITY_ADMIN}
        )
        if not allowed_facilities:
            return {'data_status': 'operational pilot data', 'facilities': []}
        facilities_query = (
            select(Facility)
            .where(Facility.active.is_(True), Facility.id.in_(allowed_facilities))
            .order_by(Facility.name)
        )

    result = []
    for facility in db.scalars(facilities_query).all():
        rx_ids = select(Prescription.id).where(Prescription.facility_id == facility.id)
        rx_count = db.scalar(select(func.count()).select_from(Prescription).where(Prescription.facility_id == facility.id)) or 0
        linked = (
            db.scalar(
                select(func.count(func.distinct(DispensingTransaction.prescription_id))).where(
                    DispensingTransaction.prescription_id.in_(rx_ids)
                )
            )
            or 0
        )
        review_ids = (
            select(StewardshipReview.id)
            .join(Prescription, Prescription.id == StewardshipReview.prescription_id)
            .where(Prescription.facility_id == facility.id)
        )
        review_total = (
            db.scalar(select(func.count()).select_from(StewardshipReview).where(StewardshipReview.id.in_(review_ids)))
            or 0
        )
        review_done = (
            db.scalar(
                select(func.count())
                .select_from(StewardshipReview)
                .where(StewardshipReview.id.in_(review_ids), StewardshipReview.status == 'COMPLETED')
            )
            or 0
        )
        result.append(
            {
                'facility_code': facility.code,
                'facility_name': facility.name,
                'district': facility.district,
                'prescriptions': rx_count,
                'prescriptions_with_dispense': linked,
                'reconciliation_rate': round(linked / max(rx_count, 1) * 100, 1),
                'stewardship_reviews': review_total,
                'reviews_completed': review_done,
                'review_completion_rate': round(review_done / max(review_total, 1) * 100, 1),
            }
        )
    return {'data_status': 'operational pilot data', 'facilities': result}
