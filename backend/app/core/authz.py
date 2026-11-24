from dataclasses import dataclass
from typing import Iterable

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Principal, require_human_user, require_service_client
from app.core.config import settings
from app.db.session import get_db
from app.models.core import (
    Facility,
    Pharmacy,
    PharmacyNetwork,
    PharmacyNetworkFacility,
    PharmacyNetworkMedicinePermission,
    PharmacyNetworkPharmacy,
    Prescription,
)
from app.services.audit import record_audit

# Canonical human roles (PRODUCT_MASTER_BLUEPRINT.md §4)
ROLE_PRESCRIBER = 'prescriber'
ROLE_PHARMACIST = 'pharmacist'
ROLE_PHARMACY_ASSISTANT = 'pharmacy_assistant'
ROLE_STEWARDSHIP_OFFICER = 'stewardship_officer'
ROLE_FACILITY_ADMIN = 'facility_admin'
ROLE_NATIONAL_ANALYST = 'national_analyst'
ROLE_PLATFORM_OPERATOR = 'platform_operator'

ALL_CANONICAL_ROLES: dict[str, str] = {
    ROLE_PRESCRIBER: 'Authorizes/views prescriptions within assigned facility',
    ROLE_PHARMACIST: 'Verifies credentials and dispenses antibiotics within assigned pharmacy',
    ROLE_PHARMACY_ASSISTANT: 'Supports pharmacy verification and retrieval without dispensing privilege',
    ROLE_STEWARDSHIP_OFFICER: 'Reviews stewardship alerts, tasks, and facility utilization indicators',
    ROLE_FACILITY_ADMIN: 'Administers facility users, configuration, and facility audit logs',
    ROLE_NATIONAL_ANALYST: 'Reviews approved aggregate stewardship indicators without identifiable patient access',
    ROLE_PLATFORM_OPERATOR: 'Operates platform infrastructure and partner service clients without clinical data access',
}

# Canonical service-client scopes
SCOPE_EBUZIMA_RX_WRITE = 'integrations:ebuzima:prescriptions:write'
SCOPE_OPENMRS_RX_WRITE = 'integrations:openmrs:prescriptions:write'
SCOPE_EBUZIMA_RX_READ = 'integrations:ebuzima:prescriptions:read'
SCOPE_EBUZIMA_CRED_WRITE = 'integrations:ebuzima:credentials:write'
SCOPE_RMS_STOCK_WRITE = 'integrations:rms:stock:write'
SCOPE_DISPENSING_READ = 'integrations:dispensing:read'
SCOPE_STEWARDSHIP_SUPPORT_READ = 'stewardship:support:read'
SCOPE_SMS_DISPATCH = 'integrations:sms:dispatch'
SCOPE_SMS_CALLBACK = 'integrations:sms:callback'
SCOPE_SMS_INBOUND = 'integrations:sms:inbound'
SCOPE_OUTBOX_DISPATCH = 'integrations:outbox:dispatch'


@dataclass(frozen=True)
class DispenseAuthzResult:
    allowed: bool
    is_cross_facility: bool = False
    network_id: int | None = None
    reason: str = ''


def audit_authz_denied(
    db: Session,
    principal: Principal,
    *,
    action: str,
    entity_type: str,
    entity_id: str | int,
    facility_id: int | None = None,
    pharmacy_id: int | None = None,
    reason: str,
) -> None:
    record_audit(
        db,
        'AUTHZ_DENIED',
        entity_type,
        entity_id,
        'AMRGuard',
        actor_type=principal.actor_type,
        actor_id=principal.actor_id,
        facility_id=facility_id,
        pharmacy_id=pharmacy_id,
        outcome='DENIED',
        details={'action': action, 'reason': reason},
    )
    db.commit()


def require_human_roles(*allowed_roles: str):
    allowed = frozenset(allowed_roles)

    def _dependency(
        principal: Principal = Depends(require_human_user),
        db: Session = Depends(get_db),
    ) -> Principal:
        if not (principal.roles & allowed):
            audit_authz_denied(
                db,
                principal,
                action='role_check',
                entity_type='Endpoint',
                entity_id=','.join(sorted(allowed)),
                reason='missing_required_role',
            )
            raise HTTPException(status_code=403, detail='Insufficient role privileges')
        return principal

    return _dependency


def require_service_scope(*required_scopes: str):
    def _dependency(
        principal: Principal = Depends(require_service_client),
        db: Session = Depends(get_db),
    ) -> Principal:
        allowed = set(required_scopes)
        if not any(g.scope in allowed for g in principal.service_scopes):
            audit_authz_denied(
                db,
                principal,
                action='service_scope_check',
                entity_type='Endpoint',
                entity_id=','.join(required_scopes),
                reason='missing_service_scope',
            )
            raise HTTPException(status_code=403, detail=f'Service client lacks required scope: {required_scopes}')
        return principal

    return _dependency


def has_national_aggregate_scope(principal: Principal) -> bool:
    if principal.actor_type != 'HUMAN':
        return False
    return any(
        g.role_code == ROLE_NATIONAL_ANALYST and g.scope_type == 'NATIONAL_AGGREGATE'
        for g in principal.role_scopes
    )


def has_platform_operator_scope(principal: Principal) -> bool:
    if principal.actor_type != 'HUMAN':
        return False
    return any(
        g.role_code == ROLE_PLATFORM_OPERATOR and g.scope_type == 'PLATFORM'
        for g in principal.role_scopes
    )


def authorized_facility_ids_for_human(
    principal: Principal,
    db: Session,
    allowed_roles: Iterable[str],
    *,
    include_pharmacy_parent_facility: bool = True,
) -> set[int]:
    if principal.actor_type != 'HUMAN':
        return set()
    allowed = set(allowed_roles)
    facility_ids: set[int] = set()
    org_ids: set[int] = set()
    pharmacy_ids: set[int] = set()

    for grant in principal.role_scopes:
        if grant.role_code not in allowed:
            continue
        if grant.scope_type == 'FACILITY' and grant.facility_id is not None:
            facility_ids.add(grant.facility_id)
        elif grant.scope_type == 'ORGANIZATION' and grant.organization_id is not None:
            org_ids.add(grant.organization_id)
        elif grant.scope_type == 'PHARMACY' and grant.pharmacy_id is not None and include_pharmacy_parent_facility:
            pharmacy_ids.add(grant.pharmacy_id)

    if org_ids:
        facility_ids.update(
            db.scalars(select(Facility.id).where(Facility.organization_id.in_(org_ids), Facility.active.is_(True))).all()
        )
    if pharmacy_ids:
        parent_ids = db.scalars(
            select(Pharmacy.facility_id).where(
                Pharmacy.id.in_(pharmacy_ids),
                Pharmacy.active.is_(True),
                Pharmacy.facility_id.is_not(None),
            )
        ).all()
        facility_ids.update(fid for fid in parent_ids if fid is not None)

    return facility_ids


def authorized_pharmacy_ids_for_human(
    principal: Principal,
    db: Session,
    allowed_roles: Iterable[str],
) -> set[int]:
    if principal.actor_type != 'HUMAN':
        return set()
    allowed = set(allowed_roles)
    pharmacy_ids: set[int] = set()
    facility_ids: set[int] = set()
    org_ids: set[int] = set()

    for grant in principal.role_scopes:
        if grant.role_code not in allowed:
            continue
        if grant.scope_type == 'PHARMACY' and grant.pharmacy_id is not None:
            pharmacy_ids.add(grant.pharmacy_id)
        elif grant.scope_type == 'FACILITY' and grant.facility_id is not None:
            facility_ids.add(grant.facility_id)
        elif grant.scope_type == 'ORGANIZATION' and grant.organization_id is not None:
            org_ids.add(grant.organization_id)

    if facility_ids:
        pharmacy_ids.update(
            db.scalars(select(Pharmacy.id).where(Pharmacy.facility_id.in_(facility_ids), Pharmacy.active.is_(True))).all()
        )
    if org_ids:
        pharmacy_ids.update(
            db.scalars(select(Pharmacy.id).where(Pharmacy.organization_id.in_(org_ids), Pharmacy.active.is_(True))).all()
        )

    return pharmacy_ids


def service_client_allows_facility(principal: Principal, scope: str, facility_id: int) -> bool:
    if principal.actor_type != 'SERVICE_CLIENT':
        return False
    return any(g.scope == scope and g.facility_id == facility_id for g in principal.service_scopes)


def service_client_allows_pharmacy(principal: Principal, scope: str, pharmacy_id: int) -> bool:
    if principal.actor_type != 'SERVICE_CLIENT':
        return False
    return any(g.scope == scope and g.pharmacy_id == pharmacy_id for g in principal.service_scopes)


def service_client_has_scope(principal: Principal, scope: str) -> bool:
    if principal.actor_type != 'SERVICE_CLIENT':
        return False
    return any(g.scope == scope for g in principal.service_scopes)


def _find_approved_cross_facility_network(
    db: Session,
    prescribing_facility_id: int,
    pharmacy_id: int,
    antibiotic_code: str | None = None,
) -> tuple[int | None, str]:
    """Return (network_id, '') if pharmacy belongs to an approved active network for prescribing_facility_id."""
    memberships = db.execute(
        select(PharmacyNetwork.id, PharmacyNetworkPharmacy.allow_all_medicines)
        .join(PharmacyNetworkFacility, PharmacyNetworkFacility.network_id == PharmacyNetwork.id)
        .join(PharmacyNetworkPharmacy, PharmacyNetworkPharmacy.network_id == PharmacyNetwork.id)
        .where(
            PharmacyNetwork.active.is_(True),
            PharmacyNetworkFacility.facility_id == prescribing_facility_id,
            PharmacyNetworkFacility.active.is_(True),
            PharmacyNetworkPharmacy.pharmacy_id == pharmacy_id,
            PharmacyNetworkPharmacy.active.is_(True),
        )
    ).all()

    if not memberships:
        return None, 'Pharmacy is not in an approved dispensing network for this prescribing facility'

    if antibiotic_code is None:
        return memberships[0][0], ''

    for network_id, allow_all_medicines in memberships:
        if allow_all_medicines:
            return network_id, ''
        permitted = db.scalar(
            select(PharmacyNetworkMedicinePermission.id).where(
                PharmacyNetworkMedicinePermission.network_id == network_id,
                PharmacyNetworkMedicinePermission.pharmacy_id == pharmacy_id,
                PharmacyNetworkMedicinePermission.antibiotic_code == antibiotic_code,
                PharmacyNetworkMedicinePermission.active.is_(True),
            )
        )
        if permitted is not None:
            return network_id, ''

    return None, 'Pharmacy is not authorized in this network to dispense the prescribed antibiotic'


def evaluate_prescription_dispensing_authorization(
    principal: Principal,
    rx: Prescription,
    pharmacy: Pharmacy,
    antibiotic_code: str,
    db: Session,
) -> DispenseAuthzResult:
    """Enforce ADR-001 Decision 2: strict facility isolation + conditional cross-facility dispensing."""
    if principal.actor_type != 'HUMAN':
        return DispenseAuthzResult(allowed=False, reason='Authenticated pharmacist required for dispensing')

    authorized_pharmacies = authorized_pharmacy_ids_for_human(principal, db, {ROLE_PHARMACIST})
    if pharmacy.id not in authorized_pharmacies:
        return DispenseAuthzResult(allowed=False, reason='Actor is not an authorized pharmacist for this pharmacy')

    if not pharmacy.active:
        return DispenseAuthzResult(allowed=False, reason='Pharmacy is not active')

    # Same-facility dispensing (hospital/facility pharmacy linked to prescribing facility)
    if pharmacy.facility_id is not None and pharmacy.facility_id == rx.facility_id:
        return DispenseAuthzResult(allowed=True, is_cross_facility=False)

    # Cross-facility / retail community pharmacy dispensing (default disabled)
    if not settings.cross_facility_dispensing_enabled:
        return DispenseAuthzResult(allowed=False, reason='Cross-facility dispensing is disabled')

    if not rx.allow_external_dispensing:
        return DispenseAuthzResult(allowed=False, reason='Prescription does not permit external dispensing')

    network_id, err = _find_approved_cross_facility_network(db, rx.facility_id, pharmacy.id, antibiotic_code)
    if network_id is None:
        return DispenseAuthzResult(allowed=False, reason=err)

    return DispenseAuthzResult(allowed=True, is_cross_facility=True, network_id=network_id)


def evaluate_verification_authorization(
    principal: Principal,
    rx: Prescription,
    db: Session,
) -> tuple[bool, int | None, str]:
    """Verify authenticated pharmacy staff may verify a prescription credential.

    Returns (allowed, matched_pharmacy_id, reason).
    """
    if principal.actor_type != 'HUMAN':
        return False, None, 'Authenticated pharmacy staff required'

    pharmacy_ids = authorized_pharmacy_ids_for_human(
        principal, db, {ROLE_PHARMACIST, ROLE_PHARMACY_ASSISTANT}
    )
    if not pharmacy_ids:
        return False, None, 'Actor is not assigned to an active pharmacy'

    pharmacies = db.scalars(
        select(Pharmacy).where(Pharmacy.id.in_(pharmacy_ids), Pharmacy.active.is_(True))
    ).all()

    # Check same-facility match first
    for pharmacy in pharmacies:
        if pharmacy.facility_id is not None and pharmacy.facility_id == rx.facility_id:
            return True, pharmacy.id, ''

    # Conditional cross-facility verification (requires flag + prescription opt-in + active network)
    if settings.cross_facility_dispensing_enabled and rx.allow_external_dispensing:
        for pharmacy in pharmacies:
            network_id, _ = _find_approved_cross_facility_network(db, rx.facility_id, pharmacy.id, antibiotic_code=None)
            if network_id is not None:
                return True, pharmacy.id, ''

    return False, None, 'Pharmacy is not authorized to verify prescriptions for this facility'
