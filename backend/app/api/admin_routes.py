"""Institutional & Platform Administration Governance APIs.

Strictly enforces RBAC separation between Platform Operators and Facility Admins:
- Platform Operators manage organizations, facilities, retail/network pharmacies,
  cross-facility networks, platform/national roles, and partner service-client keys.
- Facility Admins manage only resources and staff role scopes belonging to their own
  authorized facility and its facility pharmacies, and can NEVER escalate to
  platform_operator or national_analyst roles.
"""

from datetime import timedelta
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import LOCAL_ISSUER, Principal, utcnow
from app.core.authz import (
    ROLE_FACILITY_ADMIN,
    ROLE_NATIONAL_ANALYST,
    ROLE_PHARMACIST,
    ROLE_PHARMACY_ASSISTANT,
    ROLE_PLATFORM_OPERATOR,
    ROLE_PRESCRIBER,
    ROLE_STEWARDSHIP_OFFICER,
    audit_authz_denied,
    authorized_facility_ids_for_human,
    authorized_pharmacy_ids_for_human,
    has_platform_operator_scope,
    require_human_roles,
)
from app.core.config import settings
from app.db.seed import seed_roles
from app.db.session import get_db
from app.models.core import (
    Facility,
    Organization,
    Pharmacy,
    PharmacyNetwork,
    PharmacyNetworkFacility,
    PharmacyNetworkMedicinePermission,
    PharmacyNetworkPharmacy,
    Role,
    ServiceClient,
    ServiceClientCredential,
    ServiceClientScope,
    User,
    UserRoleScope,
    UserSession,
)
from app.schemas.admin import (
    FacilityCreate,
    FacilityResponse,
    FacilityUpdate,
    OrganizationCreate,
    OrganizationResponse,
    PharmacyAdminResponse,
    PharmacyCreate,
    PharmacyNetworkCreate,
    PharmacyNetworkFacilityItem,
    PharmacyNetworkMemberUpsert,
    PharmacyNetworkPharmacyItem,
    PharmacyNetworkResponse,
    PharmacyUpdate,
    RoleResponse,
    RoleScopeCreate,
    RoleScopeResponse,
    ServiceClientCreate,
    ServiceClientCredentialResponse,
    ServiceClientKeyIssuedResponse,
    ServiceClientKeyRotateRequest,
    ServiceClientResponse,
    ServiceClientScopeResponse,
    UserAdminResponse,
    UserCreate,
    UserUpdate,
)
from app.services.audit import record_audit
from app.services.security import hash_password, keyed_digest

router = APIRouter(prefix='/api/v1/admin', tags=['administration'])

FACILITY_ADMIN_GRANTABLE_ROLES = frozenset(
    {
        ROLE_PRESCRIBER,
        ROLE_PHARMACIST,
        ROLE_PHARMACY_ASSISTANT,
        ROLE_STEWARDSHIP_OFFICER,
        ROLE_FACILITY_ADMIN,
    }
)


def _admin_audit(
    db: Session,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str | int,
    principal: Principal,
    details: dict | None = None,
    facility_id: int | None = None,
    pharmacy_id: int | None = None,
) -> None:
    record_audit(
        db,
        event_type,
        entity_type,
        entity_id,
        principal.username or principal.actor_id,
        actor_type=principal.actor_type,
        actor_id=principal.actor_id,
        facility_id=facility_id,
        pharmacy_id=pharmacy_id,
        outcome='SUCCESS',
        details=details or {},
    )


def _caller_admin_facilities(principal: Principal, db: Session) -> set[int]:
    return authorized_facility_ids_for_human(
        principal, db, {ROLE_FACILITY_ADMIN}, include_pharmacy_parent_facility=False
    )


def _caller_admin_pharmacies(principal: Principal, db: Session) -> set[int]:
    return authorized_pharmacy_ids_for_human(principal, db, {ROLE_FACILITY_ADMIN})


def _validate_scope_grant_authority(
    principal: Principal,
    db: Session,
    scope_in: RoleScopeCreate,
    *,
    action: str,
) -> tuple[int | None, int | None]:
    """Validate target references exist and caller is permitted to grant this role scope.

    Returns (audit_facility_id, audit_pharmacy_id).
    """
    is_platform_op = has_platform_operator_scope(principal)

    if scope_in.scope_type == 'ORGANIZATION':
        org = db.get(Organization, scope_in.organization_id)
        if not org:
            raise HTTPException(404, f'Organization {scope_in.organization_id} not found')
        if not is_platform_op:
            audit_authz_denied(
                db,
                principal,
                action=action,
                entity_type='UserRoleScope',
                entity_id=f'org:{scope_in.organization_id}',
                reason='facility_admin_cannot_grant_org_scope',
            )
            raise HTTPException(403, 'Only Platform Operators may grant organization-wide scopes')
        return None, None

    if scope_in.scope_type in {'NATIONAL_AGGREGATE', 'PLATFORM'}:
        if not is_platform_op:
            audit_authz_denied(
                db,
                principal,
                action=action,
                entity_type='UserRoleScope',
                entity_id=scope_in.role_code,
                reason='facility_admin_privilege_escalation_denied',
            )
            raise HTTPException(403, f'Only Platform Operators may grant {scope_in.scope_type} scopes')
        return None, None

    if scope_in.scope_type == 'FACILITY':
        fac = db.get(Facility, scope_in.facility_id)
        if not fac:
            raise HTTPException(404, f'Facility {scope_in.facility_id} not found')
        if not is_platform_op:
            if scope_in.role_code not in FACILITY_ADMIN_GRANTABLE_ROLES:
                audit_authz_denied(
                    db,
                    principal,
                    action=action,
                    entity_type='UserRoleScope',
                    entity_id=scope_in.role_code,
                    facility_id=fac.id,
                    reason='role_not_grantable_by_facility_admin',
                )
                raise HTTPException(403, f'Facility admins cannot grant role "{scope_in.role_code}"')
            allowed_facs = _caller_admin_facilities(principal, db)
            if fac.id not in allowed_facs:
                audit_authz_denied(
                    db,
                    principal,
                    action=action,
                    entity_type='Facility',
                    entity_id=fac.id,
                    facility_id=fac.id,
                    reason='cross_facility_role_grant_denied',
                )
                raise HTTPException(403, 'Not authorized to grant roles for this facility')
        return fac.id, None

    # PHARMACY scope
    pharm = db.get(Pharmacy, scope_in.pharmacy_id)
    if not pharm:
        raise HTTPException(404, f'Pharmacy {scope_in.pharmacy_id} not found')
    if not is_platform_op:
        if scope_in.role_code not in {ROLE_PHARMACIST, ROLE_PHARMACY_ASSISTANT}:
            audit_authz_denied(
                db,
                principal,
                action=action,
                entity_type='UserRoleScope',
                entity_id=scope_in.role_code,
                pharmacy_id=pharm.id,
                reason='role_invalid_for_pharmacy_scope',
            )
            raise HTTPException(403, f'Role "{scope_in.role_code}" cannot be granted on a pharmacy scope by a facility admin')
        allowed_pharmacies = _caller_admin_pharmacies(principal, db)
        if pharm.id not in allowed_pharmacies:
            audit_authz_denied(
                db,
                principal,
                action=action,
                entity_type='Pharmacy',
                entity_id=pharm.id,
                pharmacy_id=pharm.id,
                reason='cross_pharmacy_role_grant_denied',
            )
            raise HTTPException(403, 'Not authorized to grant roles for this pharmacy')
    return pharm.facility_id, pharm.id


def _serialize_user(db: Session, user: User) -> UserAdminResponse:
    rows = db.execute(
        select(UserRoleScope, Role.code)
        .join(Role, Role.id == UserRoleScope.role_id)
        .where(UserRoleScope.user_id == user.id)
        .order_by(UserRoleScope.created_at.desc())
    ).all()
    scopes = [
        RoleScopeResponse(
            id=sc.id,
            role_code=role_code,
            scope_type=sc.scope_type,
            organization_id=sc.organization_id,
            facility_id=sc.facility_id,
            pharmacy_id=sc.pharmacy_id,
            active=bool(sc.active and sc.revoked_at is None),
            granted_by_user_id=sc.granted_by_user_id,
            created_at=sc.created_at,
            revoked_at=sc.revoked_at,
        )
        for sc, role_code in rows
    ]
    return UserAdminResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        identity_issuer=user.identity_issuer,
        active=bool(user.active),
        failed_login_attempts=user.failed_login_attempts,
        locked_until=user.locked_until,
        created_at=user.created_at,
        scopes=scopes,
    )


def _serialize_network(db: Session, network: PharmacyNetwork) -> PharmacyNetworkResponse:
    fac_rows = db.execute(
        select(PharmacyNetworkFacility, Facility)
        .join(Facility, Facility.id == PharmacyNetworkFacility.facility_id)
        .where(PharmacyNetworkFacility.network_id == network.id)
    ).all()
    ph_rows = db.execute(
        select(PharmacyNetworkPharmacy, Pharmacy)
        .join(Pharmacy, Pharmacy.id == PharmacyNetworkPharmacy.pharmacy_id)
        .where(PharmacyNetworkPharmacy.network_id == network.id)
    ).all()
    med_rows = db.scalars(
        select(PharmacyNetworkMedicinePermission).where(
            PharmacyNetworkMedicinePermission.network_id == network.id,
            PharmacyNetworkMedicinePermission.active.is_(True),
        )
    ).all()
    meds_by_pharmacy: dict[int, list[str]] = {}
    for med in med_rows:
        meds_by_pharmacy.setdefault(med.pharmacy_id, []).append(med.antibiotic_code)

    return PharmacyNetworkResponse(
        id=network.id,
        code=network.code,
        name=network.name,
        active=bool(network.active),
        created_at=network.created_at,
        facilities=[
            PharmacyNetworkFacilityItem(
                facility_id=fac.id,
                facility_code=fac.code,
                facility_name=fac.name,
                active=bool(link.active),
            )
            for link, fac in fac_rows
        ],
        pharmacies=[
            PharmacyNetworkPharmacyItem(
                pharmacy_id=ph.id,
                pharmacy_code=ph.code,
                pharmacy_name=ph.name,
                allow_all_medicines=bool(link.allow_all_medicines),
                active=bool(link.active),
                permitted_antibiotic_codes=sorted(meds_by_pharmacy.get(ph.id, [])),
            )
            for link, ph in ph_rows
        ],
    )


def _serialize_service_client(db: Session, client: ServiceClient) -> ServiceClientResponse:
    now = utcnow()
    scopes = db.scalars(
        select(ServiceClientScope)
        .where(ServiceClientScope.service_client_id == client.id)
        .order_by(ServiceClientScope.scope)
    ).all()
    creds = db.scalars(
        select(ServiceClientCredential)
        .where(ServiceClientCredential.service_client_id == client.id)
        .order_by(ServiceClientCredential.created_at.desc())
    ).all()

    cred_views: list[ServiceClientCredentialResponse] = []
    for c in creds:
        exp = c.expires_at
        is_expired = False
        if exp is not None:
            if exp.tzinfo is None:
                from datetime import timezone

                exp = exp.replace(tzinfo=timezone.utc)
            is_expired = exp <= now
        cred_views.append(
            ServiceClientCredentialResponse(
                id=c.id,
                key_prefix=c.key_prefix,
                created_at=c.created_at,
                expires_at=c.expires_at,
                revoked_at=c.revoked_at,
                active=(c.revoked_at is None and not is_expired),
            )
        )

    return ServiceClientResponse(
        id=client.id,
        client_code=client.client_code,
        name=client.name,
        partner_type=client.partner_type,
        active=bool(client.active),
        created_at=client.created_at,
        scopes=[
            ServiceClientScopeResponse(
                id=s.id,
                scope=s.scope,
                facility_id=s.facility_id,
                pharmacy_id=s.pharmacy_id,
                active=bool(s.active),
            )
            for s in scopes
        ],
        credentials=cred_views,
    )


def _generate_service_key(client_code: str) -> tuple[str, str, str]:
    clean_slug = ''.join(ch for ch in client_code.lower() if ch.isalnum())[:10] or 'svc'
    key_prefix = f'{clean_slug}_{secrets.token_hex(4)}'
    key_secret = secrets.token_urlsafe(32)
    return key_prefix, key_secret, f'{key_prefix}.{key_secret}'


# =============================================================================
# Organizations & Facilities
# =============================================================================


@router.get('/organizations', response_model=list[OrganizationResponse])
def list_organizations(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN)),
):
    if has_platform_operator_scope(principal):
        return list(db.scalars(select(Organization).order_by(Organization.name)).all())

    allowed_facs = _caller_admin_facilities(principal, db)
    if not allowed_facs:
        return []
    org_ids = db.scalars(
        select(Facility.organization_id).where(
            Facility.id.in_(allowed_facs), Facility.organization_id.is_not(None)
        )
    ).all()
    if not org_ids:
        return []
    return list(db.scalars(select(Organization).where(Organization.id.in_(org_ids)).order_by(Organization.name)).all())


@router.post('/organizations', response_model=OrganizationResponse, status_code=201)
def create_organization(
    payload: OrganizationCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR)),
):
    code = payload.code.strip().upper()
    if db.scalar(select(Organization).where(Organization.code == code)):
        raise HTTPException(409, f'Organization code "{code}" already exists')
    org = Organization(code=code, name=payload.name.strip(), active=payload.active)
    db.add(org)
    db.flush()
    _admin_audit(
        db,
        event_type='ADMIN_ORGANIZATION_CREATED',
        entity_type='Organization',
        entity_id=org.id,
        principal=principal,
        details={'code': org.code, 'name': org.name},
    )
    db.commit()
    db.refresh(org)
    return org


@router.get('/facilities', response_model=list[FacilityResponse])
def list_facilities(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN)),
):
    if has_platform_operator_scope(principal):
        return list(db.scalars(select(Facility).order_by(Facility.name)).all())
    allowed_facs = _caller_admin_facilities(principal, db)
    if not allowed_facs:
        return []
    return list(db.scalars(select(Facility).where(Facility.id.in_(allowed_facs)).order_by(Facility.name)).all())


@router.post('/facilities', response_model=FacilityResponse, status_code=201)
def create_facility(
    payload: FacilityCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR)),
):
    code = payload.code.strip().upper()
    if db.scalar(select(Facility).where(Facility.code == code)):
        raise HTTPException(409, f'Facility code "{code}" already exists')
    if payload.organization_id is not None and not db.get(Organization, payload.organization_id):
        raise HTTPException(404, f'Organization {payload.organization_id} not found')

    fac = Facility(
        code=code,
        name=payload.name.strip(),
        district=payload.district.strip(),
        organization_id=payload.organization_id,
        active=payload.active,
    )
    db.add(fac)
    db.flush()
    _admin_audit(
        db,
        event_type='ADMIN_FACILITY_CREATED',
        entity_type='Facility',
        entity_id=fac.id,
        principal=principal,
        facility_id=fac.id,
        details={'code': fac.code, 'name': fac.name, 'district': fac.district},
    )
    db.commit()
    db.refresh(fac)
    return fac


@router.patch('/facilities/{facility_id}', response_model=FacilityResponse)
def update_facility(
    facility_id: int,
    payload: FacilityUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN)),
):
    fac = db.get(Facility, facility_id)
    if not fac:
        raise HTTPException(404, 'Facility not found')

    is_platform_op = has_platform_operator_scope(principal)
    if not is_platform_op:
        allowed_facs = _caller_admin_facilities(principal, db)
        if fac.id not in allowed_facs:
            audit_authz_denied(
                db,
                principal,
                action='admin_update_facility',
                entity_type='Facility',
                entity_id=fac.id,
                facility_id=fac.id,
                reason='cross_facility_admin_denied',
            )
            raise HTTPException(403, 'Not authorized to update this facility')
        if payload.organization_id is not None or payload.active is not None:
            raise HTTPException(403, 'Only Platform Operators may change facility organization or active status')

    changes: dict = {}
    if payload.name is not None:
        fac.name = payload.name.strip()
        changes['name'] = fac.name
    if payload.district is not None:
        fac.district = payload.district.strip()
        changes['district'] = fac.district
    if payload.organization_id is not None:
        if not db.get(Organization, payload.organization_id):
            raise HTTPException(404, f'Organization {payload.organization_id} not found')
        fac.organization_id = payload.organization_id
        changes['organization_id'] = fac.organization_id
    if payload.active is not None:
        fac.active = payload.active
        changes['active'] = fac.active

    _admin_audit(
        db,
        event_type='ADMIN_FACILITY_UPDATED',
        entity_type='Facility',
        entity_id=fac.id,
        principal=principal,
        facility_id=fac.id,
        details=changes,
    )
    db.commit()
    db.refresh(fac)
    return fac


# =============================================================================
# Pharmacies & Conditional Cross-Facility Networks
# =============================================================================


@router.get('/pharmacies', response_model=list[PharmacyAdminResponse])
def list_admin_pharmacies(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN)),
):
    if has_platform_operator_scope(principal):
        return list(db.scalars(select(Pharmacy).order_by(Pharmacy.name)).all())
    allowed_pharmacies = _caller_admin_pharmacies(principal, db)
    if not allowed_pharmacies:
        return []
    return list(db.scalars(select(Pharmacy).where(Pharmacy.id.in_(allowed_pharmacies)).order_by(Pharmacy.name)).all())


@router.post('/pharmacies', response_model=PharmacyAdminResponse, status_code=201)
def create_pharmacy(
    payload: PharmacyCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN)),
):
    is_platform_op = has_platform_operator_scope(principal)
    code = payload.code.strip().upper()
    if db.scalar(select(Pharmacy).where(Pharmacy.code == code)):
        raise HTTPException(409, f'Pharmacy code "{code}" already exists')

    org_id = payload.organization_id
    if payload.facility_id is not None:
        fac = db.get(Facility, payload.facility_id)
        if not fac:
            raise HTTPException(404, f'Facility {payload.facility_id} not found')
        if org_id is None:
            org_id = fac.organization_id

    if not is_platform_op:
        allowed_facs = _caller_admin_facilities(principal, db)
        if payload.facility_id is None or payload.facility_id not in allowed_facs:
            audit_authz_denied(
                db,
                principal,
                action='admin_create_pharmacy',
                entity_type='Pharmacy',
                entity_id=code,
                facility_id=payload.facility_id,
                reason='facility_admin_pharmacy_scope_denied',
            )
            raise HTTPException(403, 'Facility admins may only create pharmacies linked to their own authorized facility')
        if payload.pharmacy_type != 'FACILITY_PHARMACY':
            raise HTTPException(403, 'Only Platform Operators may register community retail or external network pharmacies')

    pharmacy = Pharmacy(
        code=code,
        name=payload.name.strip(),
        district=payload.district.strip(),
        organization_id=org_id,
        facility_id=payload.facility_id,
        pharmacy_type=payload.pharmacy_type,
        active=payload.active,
    )
    db.add(pharmacy)
    db.flush()
    _admin_audit(
        db,
        event_type='ADMIN_PHARMACY_CREATED',
        entity_type='Pharmacy',
        entity_id=pharmacy.id,
        principal=principal,
        facility_id=pharmacy.facility_id,
        pharmacy_id=pharmacy.id,
        details={'code': pharmacy.code, 'pharmacy_type': pharmacy.pharmacy_type},
    )
    db.commit()
    db.refresh(pharmacy)
    return pharmacy


@router.patch('/pharmacies/{pharmacy_id}', response_model=PharmacyAdminResponse)
def update_pharmacy(
    pharmacy_id: int,
    payload: PharmacyUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN)),
):
    pharmacy = db.get(Pharmacy, pharmacy_id)
    if not pharmacy:
        raise HTTPException(404, 'Pharmacy not found')

    is_platform_op = has_platform_operator_scope(principal)
    if not is_platform_op:
        allowed_pharmacies = _caller_admin_pharmacies(principal, db)
        if pharmacy.id not in allowed_pharmacies:
            audit_authz_denied(
                db,
                principal,
                action='admin_update_pharmacy',
                entity_type='Pharmacy',
                entity_id=pharmacy.id,
                pharmacy_id=pharmacy.id,
                reason='cross_pharmacy_admin_denied',
            )
            raise HTTPException(403, 'Not authorized to update this pharmacy')
        if payload.pharmacy_type is not None and payload.pharmacy_type != pharmacy.pharmacy_type:
            raise HTTPException(403, 'Only Platform Operators may change pharmacy_type')

    changes: dict = {}
    if payload.name is not None:
        pharmacy.name = payload.name.strip()
        changes['name'] = pharmacy.name
    if payload.district is not None:
        pharmacy.district = payload.district.strip()
        changes['district'] = pharmacy.district
    if payload.pharmacy_type is not None:
        pharmacy.pharmacy_type = payload.pharmacy_type
        changes['pharmacy_type'] = pharmacy.pharmacy_type
    if payload.active is not None:
        pharmacy.active = payload.active
        changes['active'] = pharmacy.active

    _admin_audit(
        db,
        event_type='ADMIN_PHARMACY_UPDATED',
        entity_type='Pharmacy',
        entity_id=pharmacy.id,
        principal=principal,
        facility_id=pharmacy.facility_id,
        pharmacy_id=pharmacy.id,
        details=changes,
    )
    db.commit()
    db.refresh(pharmacy)
    return pharmacy


@router.get('/networks', response_model=list[PharmacyNetworkResponse])
def list_pharmacy_networks(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN)),
):
    if has_platform_operator_scope(principal):
        networks = db.scalars(select(PharmacyNetwork).order_by(PharmacyNetwork.name)).all()
    else:
        allowed_facs = _caller_admin_facilities(principal, db)
        if not allowed_facs:
            return []
        net_ids = db.scalars(
            select(PharmacyNetworkFacility.network_id).where(
                PharmacyNetworkFacility.facility_id.in_(allowed_facs),
                PharmacyNetworkFacility.active.is_(True),
            )
        ).all()
        if not net_ids:
            return []
        networks = db.scalars(select(PharmacyNetwork).where(PharmacyNetwork.id.in_(net_ids)).order_by(PharmacyNetwork.name)).all()
    return [_serialize_network(db, n) for n in networks]


@router.post('/networks', response_model=PharmacyNetworkResponse, status_code=201)
def create_pharmacy_network(
    payload: PharmacyNetworkCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR)),
):
    code = payload.code.strip().upper()
    if db.scalar(select(PharmacyNetwork).where(PharmacyNetwork.code == code)):
        raise HTTPException(409, f'Pharmacy network code "{code}" already exists')
    net = PharmacyNetwork(code=code, name=payload.name.strip(), active=payload.active)
    db.add(net)
    db.flush()
    _admin_audit(
        db,
        event_type='ADMIN_NETWORK_CREATED',
        entity_type='PharmacyNetwork',
        entity_id=net.id,
        principal=principal,
        details={'code': net.code, 'name': net.name},
    )
    db.commit()
    return _serialize_network(db, net)


@router.post('/networks/{network_id}/members', response_model=PharmacyNetworkResponse)
def upsert_pharmacy_network_member(
    network_id: int,
    payload: PharmacyNetworkMemberUpsert,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR)),
):
    net = db.get(PharmacyNetwork, network_id)
    if not net:
        raise HTTPException(404, 'Pharmacy network not found')

    if payload.facility_id is not None:
        if not db.get(Facility, payload.facility_id):
            raise HTTPException(404, f'Facility {payload.facility_id} not found')
        existing_fac = db.scalar(
            select(PharmacyNetworkFacility).where(
                PharmacyNetworkFacility.network_id == net.id,
                PharmacyNetworkFacility.facility_id == payload.facility_id,
            )
        )
        if existing_fac:
            existing_fac.active = payload.active
        else:
            db.add(PharmacyNetworkFacility(network_id=net.id, facility_id=payload.facility_id, active=payload.active))

    if payload.pharmacy_id is not None:
        if not db.get(Pharmacy, payload.pharmacy_id):
            raise HTTPException(404, f'Pharmacy {payload.pharmacy_id} not found')
        existing_ph = db.scalar(
            select(PharmacyNetworkPharmacy).where(
                PharmacyNetworkPharmacy.network_id == net.id,
                PharmacyNetworkPharmacy.pharmacy_id == payload.pharmacy_id,
            )
        )
        if existing_ph:
            existing_ph.allow_all_medicines = payload.allow_all_medicines
            existing_ph.active = payload.active
        else:
            db.add(
                PharmacyNetworkPharmacy(
                    network_id=net.id,
                    pharmacy_id=payload.pharmacy_id,
                    allow_all_medicines=payload.allow_all_medicines,
                    active=payload.active,
                )
            )
        for ab_code in payload.antibiotic_codes:
            clean_code = ab_code.strip().upper()
            if not clean_code:
                continue
            existing_perm = db.scalar(
                select(PharmacyNetworkMedicinePermission).where(
                    PharmacyNetworkMedicinePermission.network_id == net.id,
                    PharmacyNetworkMedicinePermission.pharmacy_id == payload.pharmacy_id,
                    PharmacyNetworkMedicinePermission.antibiotic_code == clean_code,
                )
            )
            if existing_perm:
                existing_perm.active = payload.active
            else:
                db.add(
                    PharmacyNetworkMedicinePermission(
                        network_id=net.id,
                        pharmacy_id=payload.pharmacy_id,
                        antibiotic_code=clean_code,
                        active=payload.active,
                    )
                )

    db.flush()
    _admin_audit(
        db,
        event_type='ADMIN_NETWORK_MEMBER_UPDATED',
        entity_type='PharmacyNetwork',
        entity_id=net.id,
        principal=principal,
        facility_id=payload.facility_id,
        pharmacy_id=payload.pharmacy_id,
        details={
            'facility_id': payload.facility_id,
            'pharmacy_id': payload.pharmacy_id,
            'allow_all_medicines': payload.allow_all_medicines,
            'antibiotic_codes': payload.antibiotic_codes,
            'active': payload.active,
        },
    )
    db.commit()
    return _serialize_network(db, net)


# =============================================================================
# Human Users & Role-Scope Grants
# =============================================================================


@router.get('/roles', response_model=list[RoleResponse])
def list_roles(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN)),
):
    seed_roles(db)
    db.commit()
    rows = list(db.scalars(select(Role).order_by(Role.code)).all())
    if has_platform_operator_scope(principal):
        return rows
    return [r for r in rows if r.code in FACILITY_ADMIN_GRANTABLE_ROLES]


@router.get('/users', response_model=list[UserAdminResponse])
def list_users(
    include_inactive: bool = Query(default=True),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN)),
):
    if has_platform_operator_scope(principal):
        query = select(User).order_by(User.username)
        if not include_inactive:
            query = query.where(User.active.is_(True))
        users = db.scalars(query).all()
        return [_serialize_user(db, u) for u in users]

    allowed_facs = _caller_admin_facilities(principal, db)
    allowed_pharmacies = _caller_admin_pharmacies(principal, db)
    if not allowed_facs and not allowed_pharmacies:
        return []

    scoped_user_ids: set[int] = set()
    if allowed_facs:
        scoped_user_ids.update(
            db.scalars(
                select(UserRoleScope.user_id).where(
                    UserRoleScope.facility_id.in_(allowed_facs),
                    UserRoleScope.revoked_at.is_(None),
                )
            ).all()
        )
    if allowed_pharmacies:
        scoped_user_ids.update(
            db.scalars(
                select(UserRoleScope.user_id).where(
                    UserRoleScope.pharmacy_id.in_(allowed_pharmacies),
                    UserRoleScope.revoked_at.is_(None),
                )
            ).all()
        )
    if not scoped_user_ids:
        return []

    query = select(User).where(User.id.in_(scoped_user_ids)).order_by(User.username)
    if not include_inactive:
        query = query.where(User.active.is_(True))
    users = db.scalars(query).all()
    return [_serialize_user(db, u) for u in users]


@router.post('/users', response_model=UserAdminResponse, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN)),
):
    is_platform_op = has_platform_operator_scope(principal)
    username = payload.username.strip()

    if not is_platform_op and payload.initial_scope is None:
        raise HTTPException(400, 'Facility admins must assign an explicit facility or pharmacy initial_scope when creating staff')

    if payload.auth_provider == 'local' and not settings.local_auth_enabled:
        raise HTTPException(403, 'Local password accounts cannot be created when local authentication is disabled')

    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(409, f'Username "{username}" already exists')

    audit_fac_id: int | None = None
    audit_pharm_id: int | None = None
    if payload.initial_scope is not None:
        audit_fac_id, audit_pharm_id = _validate_scope_grant_authority(
            principal, db, payload.initial_scope, action='admin_create_user_with_scope'
        )

    issuer = LOCAL_ISSUER if payload.auth_provider == 'local' else payload.identity_issuer.strip()  # type: ignore[union-attr]
    subject = username if payload.auth_provider == 'local' else payload.identity_subject.strip()  # type: ignore[union-attr]

    if db.scalar(select(User).where(User.identity_issuer == issuer, User.identity_subject == subject)):
        raise HTTPException(409, 'A user with that identity issuer and subject already exists')

    user = User(
        identity_issuer=issuer,
        identity_subject=subject,
        username=username,
        display_name=payload.display_name.strip(),
        email=payload.email.strip() if payload.email else None,
        password_hash=hash_password(payload.password) if payload.auth_provider == 'local' and payload.password else None,
        active=True,
    )
    db.add(user)
    db.flush()

    if payload.initial_scope is not None:
        roles = seed_roles(db)
        role = roles[payload.initial_scope.role_code]
        db.add(
            UserRoleScope(
                user_id=user.id,
                role_id=role.id,
                scope_type=payload.initial_scope.scope_type,
                organization_id=payload.initial_scope.organization_id,
                facility_id=payload.initial_scope.facility_id,
                pharmacy_id=payload.initial_scope.pharmacy_id,
                active=True,
                granted_by_user_id=principal.user_id,
            )
        )
        db.flush()

    _admin_audit(
        db,
        event_type='ADMIN_USER_CREATED',
        entity_type='User',
        entity_id=user.id,
        principal=principal,
        facility_id=audit_fac_id,
        pharmacy_id=audit_pharm_id,
        details={
            'username': user.username,
            'auth_provider': payload.auth_provider,
            'initial_role': payload.initial_scope.role_code if payload.initial_scope else None,
            'initial_scope_type': payload.initial_scope.scope_type if payload.initial_scope else None,
        },
    )
    db.commit()
    return _serialize_user(db, user)


@router.patch('/users/{user_id}', response_model=UserAdminResponse)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN)),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, 'User not found')

    is_platform_op = has_platform_operator_scope(principal)
    if payload.active is False and principal.user_id == user.id:
        raise HTTPException(409, 'Administrators cannot deactivate their own active account')

    target_scopes = db.execute(
        select(UserRoleScope, Role.code)
        .join(Role, Role.id == UserRoleScope.role_id)
        .where(UserRoleScope.user_id == user.id, UserRoleScope.revoked_at.is_(None))
    ).all()

    audit_fac_id: int | None = None
    if not is_platform_op:
        allowed_facs = _caller_admin_facilities(principal, db)
        allowed_pharmacies = _caller_admin_pharmacies(principal, db)
        if not target_scopes:
            raise HTTPException(403, 'Not authorized to manage this user')
        for sc, role_code in target_scopes:
            if role_code in {ROLE_PLATFORM_OPERATOR, ROLE_NATIONAL_ANALYST}:
                audit_authz_denied(
                    db,
                    principal,
                    action='admin_update_user',
                    entity_type='User',
                    entity_id=user.id,
                    reason='facility_admin_cannot_modify_elevated_account',
                )
                raise HTTPException(403, 'Facility admins cannot modify national or platform accounts')
            in_scope = (sc.facility_id in allowed_facs) or (sc.pharmacy_id in allowed_pharmacies)
            if not in_scope:
                audit_authz_denied(
                    db,
                    principal,
                    action='admin_update_user',
                    entity_type='User',
                    entity_id=user.id,
                    reason='cross_facility_user_modification_denied',
                )
                raise HTTPException(403, 'User holds scopes outside your authorized facility')
            if sc.facility_id in allowed_facs and audit_fac_id is None:
                audit_fac_id = sc.facility_id

    changes: dict = {}
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
        changes['display_name'] = user.display_name
    if payload.email is not None:
        user.email = payload.email.strip() or None
        changes['email'] = user.email
    if payload.unlock:
        user.failed_login_attempts = 0
        user.locked_until = None
        changes['unlocked'] = True
    if payload.active is not None:
        user.active = payload.active
        changes['active'] = payload.active
        if not payload.active:
            now = utcnow()
            active_sessions = db.scalars(
                select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            ).all()
            for sess in active_sessions:
                sess.revoked_at = now
            changes['revoked_sessions'] = len(active_sessions)

    _admin_audit(
        db,
        event_type='ADMIN_USER_UPDATED',
        entity_type='User',
        entity_id=user.id,
        principal=principal,
        facility_id=audit_fac_id,
        details=changes,
    )
    db.commit()
    return _serialize_user(db, user)


@router.post('/users/{user_id}/role-scopes', response_model=RoleScopeResponse, status_code=201)
def grant_user_role_scope(
    user_id: int,
    payload: RoleScopeCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN)),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, 'User not found')

    audit_fac_id, audit_pharm_id = _validate_scope_grant_authority(
        principal, db, payload, action='admin_grant_role_scope'
    )
    roles = seed_roles(db)
    role = roles[payload.role_code]

    existing = db.scalar(
        select(UserRoleScope).where(
            UserRoleScope.user_id == user.id,
            UserRoleScope.role_id == role.id,
            UserRoleScope.scope_type == payload.scope_type,
            UserRoleScope.organization_id == payload.organization_id,
            UserRoleScope.facility_id == payload.facility_id,
            UserRoleScope.pharmacy_id == payload.pharmacy_id,
            UserRoleScope.active.is_(True),
            UserRoleScope.revoked_at.is_(None),
        )
    )
    if existing:
        raise HTTPException(409, 'User already holds this active role scope')

    scope = UserRoleScope(
        user_id=user.id,
        role_id=role.id,
        scope_type=payload.scope_type,
        organization_id=payload.organization_id,
        facility_id=payload.facility_id,
        pharmacy_id=payload.pharmacy_id,
        active=True,
        granted_by_user_id=principal.user_id,
    )
    db.add(scope)
    db.flush()
    _admin_audit(
        db,
        event_type='ADMIN_ROLE_SCOPE_GRANTED',
        entity_type='UserRoleScope',
        entity_id=scope.id,
        principal=principal,
        facility_id=audit_fac_id,
        pharmacy_id=audit_pharm_id,
        details={
            'target_user_id': user.id,
            'role_code': role.code,
            'scope_type': scope.scope_type,
            'organization_id': scope.organization_id,
            'facility_id': scope.facility_id,
            'pharmacy_id': scope.pharmacy_id,
        },
    )
    db.commit()
    db.refresh(scope)
    return RoleScopeResponse(
        id=scope.id,
        role_code=role.code,
        scope_type=scope.scope_type,
        organization_id=scope.organization_id,
        facility_id=scope.facility_id,
        pharmacy_id=scope.pharmacy_id,
        active=True,
        granted_by_user_id=scope.granted_by_user_id,
        created_at=scope.created_at,
        revoked_at=scope.revoked_at,
    )


@router.post('/users/{user_id}/role-scopes/{scope_id}/revoke', response_model=RoleScopeResponse)
def revoke_user_role_scope(
    user_id: int,
    scope_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN)),
):
    scope = db.get(UserRoleScope, scope_id)
    if not scope or scope.user_id != user_id:
        raise HTTPException(404, 'Role scope not found for user')
    if scope.revoked_at is not None or not scope.active:
        raise HTTPException(409, 'Role scope is already revoked')

    role = db.get(Role, scope.role_id)
    role_code = role.code if role else 'unknown'

    is_platform_op = has_platform_operator_scope(principal)
    if not is_platform_op:
        allowed_facs = _caller_admin_facilities(principal, db)
        allowed_pharmacies = _caller_admin_pharmacies(principal, db)
        in_scope = (scope.facility_id in allowed_facs) or (scope.pharmacy_id in allowed_pharmacies)
        if not in_scope or role_code in {ROLE_PLATFORM_OPERATOR, ROLE_NATIONAL_ANALYST}:
            audit_authz_denied(
                db,
                principal,
                action='admin_revoke_role_scope',
                entity_type='UserRoleScope',
                entity_id=scope.id,
                facility_id=scope.facility_id,
                pharmacy_id=scope.pharmacy_id,
                reason='cross_scope_role_revoke_denied',
            )
            raise HTTPException(403, 'Not authorized to revoke this role scope')

    if principal.user_id == user_id and role_code in {ROLE_PLATFORM_OPERATOR, ROLE_FACILITY_ADMIN}:
        raise HTTPException(409, 'Administrators cannot revoke their own administrative role scope')

    scope.active = False
    scope.revoked_at = utcnow()
    _admin_audit(
        db,
        event_type='ADMIN_ROLE_SCOPE_REVOKED',
        entity_type='UserRoleScope',
        entity_id=scope.id,
        principal=principal,
        facility_id=scope.facility_id,
        pharmacy_id=scope.pharmacy_id,
        details={'target_user_id': user_id, 'role_code': role_code, 'scope_type': scope.scope_type},
    )
    db.commit()
    db.refresh(scope)
    return RoleScopeResponse(
        id=scope.id,
        role_code=role_code,
        scope_type=scope.scope_type,
        organization_id=scope.organization_id,
        facility_id=scope.facility_id,
        pharmacy_id=scope.pharmacy_id,
        active=False,
        granted_by_user_id=scope.granted_by_user_id,
        created_at=scope.created_at,
        revoked_at=scope.revoked_at,
    )


# =============================================================================
# Partner Service Clients & Key Rotation (Platform Operator ONLY)
# =============================================================================


@router.get('/service-clients', response_model=list[ServiceClientResponse])
def list_service_clients(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR)),
):
    clients = db.scalars(select(ServiceClient).order_by(ServiceClient.client_code)).all()
    return [_serialize_service_client(db, c) for c in clients]


@router.post('/service-clients', response_model=ServiceClientKeyIssuedResponse, status_code=201)
def create_service_client(
    payload: ServiceClientCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR)),
):
    code = payload.client_code.strip().lower()
    if db.scalar(select(ServiceClient).where(ServiceClient.client_code == code)):
        raise HTTPException(409, f'Service client "{code}" already exists')

    for sc in payload.scopes:
        if sc.facility_id is not None and not db.get(Facility, sc.facility_id):
            raise HTTPException(404, f'Facility {sc.facility_id} not found')
        if sc.pharmacy_id is not None and not db.get(Pharmacy, sc.pharmacy_id):
            raise HTTPException(404, f'Pharmacy {sc.pharmacy_id} not found')

    client = ServiceClient(
        client_code=code,
        name=payload.name.strip(),
        partner_type=payload.partner_type,
        active=True,
    )
    db.add(client)
    db.flush()

    for sc in payload.scopes:
        db.add(
            ServiceClientScope(
                service_client_id=client.id,
                scope=sc.scope.strip(),
                facility_id=sc.facility_id,
                pharmacy_id=sc.pharmacy_id,
                active=True,
            )
        )

    key_prefix, key_secret, full_api_key = _generate_service_key(code)
    expires_at = utcnow() + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None
    cred = ServiceClientCredential(
        service_client_id=client.id,
        key_prefix=key_prefix,
        secret_hash=keyed_digest(key_secret, purpose='service_client_key', salt=key_prefix),
        expires_at=expires_at,
    )
    db.add(cred)
    db.flush()

    _admin_audit(
        db,
        event_type='ADMIN_SERVICE_CLIENT_CREATED',
        entity_type='ServiceClient',
        entity_id=client.id,
        principal=principal,
        details={
            'client_code': client.client_code,
            'partner_type': client.partner_type,
            'key_prefix': key_prefix,
            'scope_count': len(payload.scopes),
        },
    )
    db.commit()
    return ServiceClientKeyIssuedResponse(
        client_id=client.id,
        client_code=client.client_code,
        credential_id=cred.id,
        key_prefix=key_prefix,
        api_key=full_api_key,
        expires_at=expires_at,
        revoked_previous_count=0,
    )


@router.post('/service-clients/{client_id}/rotate-key', response_model=ServiceClientKeyIssuedResponse)
def rotate_service_client_key(
    client_id: int,
    payload: ServiceClientKeyRotateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR)),
):
    client = db.get(ServiceClient, client_id)
    if not client:
        raise HTTPException(404, 'Service client not found')

    now = utcnow()
    revoked_count = 0
    if payload.revoke_previous:
        existing_creds = db.scalars(
            select(ServiceClientCredential).where(
                ServiceClientCredential.service_client_id == client.id,
                ServiceClientCredential.revoked_at.is_(None),
            )
        ).all()
        for old in existing_creds:
            old.revoked_at = now
            revoked_count += 1

    key_prefix, key_secret, full_api_key = _generate_service_key(client.client_code)
    expires_at = now + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None
    cred = ServiceClientCredential(
        service_client_id=client.id,
        key_prefix=key_prefix,
        secret_hash=keyed_digest(key_secret, purpose='service_client_key', salt=key_prefix),
        expires_at=expires_at,
    )
    db.add(cred)
    db.flush()

    _admin_audit(
        db,
        event_type='ADMIN_SERVICE_KEY_ROTATED',
        entity_type='ServiceClientCredential',
        entity_id=cred.id,
        principal=principal,
        details={
            'client_code': client.client_code,
            'new_key_prefix': key_prefix,
            'revoke_previous': payload.revoke_previous,
            'revoked_previous_count': revoked_count,
        },
    )
    db.commit()
    return ServiceClientKeyIssuedResponse(
        client_id=client.id,
        client_code=client.client_code,
        credential_id=cred.id,
        key_prefix=key_prefix,
        api_key=full_api_key,
        expires_at=expires_at,
        revoked_previous_count=revoked_count,
    )


@router.post('/service-clients/{client_id}/credentials/{credential_id}/revoke', response_model=ServiceClientCredentialResponse)
def revoke_service_client_credential(
    client_id: int,
    credential_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_human_roles(ROLE_PLATFORM_OPERATOR)),
):
    cred = db.get(ServiceClientCredential, credential_id)
    if not cred or cred.service_client_id != client_id:
        raise HTTPException(404, 'Service client credential not found')
    if cred.revoked_at is not None:
        raise HTTPException(409, 'Credential is already revoked')

    cred.revoked_at = utcnow()
    _admin_audit(
        db,
        event_type='ADMIN_SERVICE_KEY_REVOKED',
        entity_type='ServiceClientCredential',
        entity_id=cred.id,
        principal=principal,
        details={'client_id': client_id, 'key_prefix': cred.key_prefix},
    )
    db.commit()
    db.refresh(cred)
    return ServiceClientCredentialResponse(
        id=cred.id,
        key_prefix=cred.key_prefix,
        created_at=cred.created_at,
        expires_at=cred.expires_at,
        revoked_at=cred.revoked_at,
        active=False,
    )
