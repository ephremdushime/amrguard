from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import LOCAL_ISSUER
from app.core.authz import (
    ALL_CANONICAL_ROLES,
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
    SCOPE_STEWARDSHIP_SUPPORT_READ,
)
from app.core.config import settings
from app.models.core import (
    Antibiotic,
    AntibioticRule,
    Facility,
    Organization,
    Pharmacy,
    Prescriber,
    Role,
    ServiceClient,
    ServiceClientCredential,
    ServiceClientScope,
    StockBatch,
    User,
    UserRoleScope,
)
from app.services.security import hash_password, keyed_digest

# Synthetic development/demo-only credentials (never seeded in production or sandbox)
DEMO_USER_PASSWORD = 'DemoOnly-Synthetic-Pass-2026!'
DEMO_EBUZIMA_KEY_PREFIX = 'ebz_demo_k1'
DEMO_EBUZIMA_KEY_SECRET = 'synthetic-demo-ebuzima-secret-not-for-prod-0001'
DEMO_EBUZIMA_API_KEY = f'{DEMO_EBUZIMA_KEY_PREFIX}.{DEMO_EBUZIMA_KEY_SECRET}'
DEMO_RMS_KEY_PREFIX = 'rms_demo_k1'
DEMO_RMS_KEY_SECRET = 'synthetic-demo-rms-secret-not-for-prod-0001'
DEMO_RMS_API_KEY = f'{DEMO_RMS_KEY_PREFIX}.{DEMO_RMS_KEY_SECRET}'


def seed_roles(db: Session) -> dict[str, Role]:
    roles_by_code: dict[str, Role] = {}
    for code, description in ALL_CANONICAL_ROLES.items():
        role = db.scalar(select(Role).where(Role.code == code))
        if not role:
            role = Role(code=code, description=description)
            db.add(role)
            db.flush()
        roles_by_code[code] = role
    return roles_by_code


_demo_hash_cache: dict[str, str] = {}


def ensure_local_user(
    db: Session,
    *,
    username: str,
    display_name: str,
    password: str,
    email: str | None = None,
    active: bool = True,
) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if not user:
        if password not in _demo_hash_cache:
            _demo_hash_cache[password] = hash_password(password)
        user = User(
            identity_issuer=LOCAL_ISSUER,
            identity_subject=username,
            username=username,
            display_name=display_name,
            email=email,
            password_hash=_demo_hash_cache[password],
            active=active,
        )
        db.add(user)
        db.flush()
    return user


def ensure_role_scope(
    db: Session,
    *,
    user: User,
    role: Role,
    scope_type: str,
    organization_id: int | None = None,
    facility_id: int | None = None,
    pharmacy_id: int | None = None,
) -> UserRoleScope:
    existing = db.scalar(
        select(UserRoleScope).where(
            UserRoleScope.user_id == user.id,
            UserRoleScope.role_id == role.id,
            UserRoleScope.scope_type == scope_type,
            UserRoleScope.organization_id == organization_id,
            UserRoleScope.facility_id == facility_id,
            UserRoleScope.pharmacy_id == pharmacy_id,
            UserRoleScope.active.is_(True),
            UserRoleScope.revoked_at.is_(None),
        )
    )
    if existing:
        return existing
    grant = UserRoleScope(
        user_id=user.id,
        role_id=role.id,
        scope_type=scope_type,
        organization_id=organization_id,
        facility_id=facility_id,
        pharmacy_id=pharmacy_id,
        active=True,
    )
    db.add(grant)
    db.flush()
    return grant


def ensure_service_client(
    db: Session,
    *,
    client_code: str,
    name: str,
    partner_type: str,
    key_prefix: str,
    key_secret: str,
    scopes: list[tuple[str, int | None, int | None]],
) -> ServiceClient:
    client = db.scalar(select(ServiceClient).where(ServiceClient.client_code == client_code))
    if not client:
        client = ServiceClient(client_code=client_code, name=name, partner_type=partner_type, active=True)
        db.add(client)
        db.flush()

    cred = db.scalar(select(ServiceClientCredential).where(ServiceClientCredential.key_prefix == key_prefix))
    expected_hash = keyed_digest(key_secret, purpose='service_client_key', salt=key_prefix)
    if not cred:
        db.add(
            ServiceClientCredential(
                service_client_id=client.id,
                key_prefix=key_prefix,
                secret_hash=expected_hash,
            )
        )
        db.flush()
    elif cred.secret_hash != expected_hash and cred.revoked_at is None:
        cred.secret_hash = expected_hash

    for scope_name, facility_id, pharmacy_id in scopes:
        exists = db.scalar(
            select(ServiceClientScope).where(
                ServiceClientScope.service_client_id == client.id,
                ServiceClientScope.scope == scope_name,
                ServiceClientScope.facility_id == facility_id,
                ServiceClientScope.pharmacy_id == pharmacy_id,
                ServiceClientScope.active.is_(True),
            )
        )
        if not exists:
            db.add(
                ServiceClientScope(
                    service_client_id=client.id,
                    scope=scope_name,
                    facility_id=facility_id,
                    pharmacy_id=pharmacy_id,
                    active=True,
                )
            )
    db.flush()
    return client


def seed_demo(db: Session):
    if settings.app_env.lower() in {'production', 'sandbox'}:
        raise RuntimeError('Demo seed data must never be populated in production or sandbox environments')

    roles = seed_roles(db)

    org = db.scalar(select(Organization).where(Organization.code == 'ORG-DEMO-001'))
    if not org:
        org = Organization(code='ORG-DEMO-001', name='AMRGuard Synthetic Demo Health Group', active=True)
        db.add(org)
        db.flush()

    fac = db.scalar(select(Facility).where(Facility.code == 'FAC-KGL-001'))
    if not fac:
        fac = Facility(
            code='FAC-KGL-001',
            name='AMRGuard Demo Hospital',
            district='Gasabo',
            organization_id=org.id,
        )
        db.add(fac)
        db.flush()
    elif fac.organization_id is None:
        fac.organization_id = org.id

    pharmacy = db.scalar(select(Pharmacy).where(Pharmacy.code == 'PHA-KGL-001'))
    if not pharmacy:
        pharmacy = Pharmacy(
            code='PHA-KGL-001',
            name='AMRGuard Demo Pharmacy',
            district='Gasabo',
            organization_id=org.id,
            facility_id=fac.id,
            pharmacy_type='FACILITY_PHARMACY',
        )
        db.add(pharmacy)
        db.flush()
    else:
        if pharmacy.organization_id is None:
            pharmacy.organization_id = org.id
        if pharmacy.facility_id is None:
            pharmacy.facility_id = fac.id

    prescriber = db.scalar(select(Prescriber).where(Prescriber.external_user_id == 'EBZ-USER-001'))
    if not prescriber:
        prescriber = Prescriber(external_user_id='EBZ-USER-001', name='Demo Prescriber', facility_id=fac.id)
        db.add(prescriber)
        db.flush()

    antibiotic = db.scalar(select(Antibiotic).where(Antibiotic.code == 'AMX500CAP'))
    if not antibiotic:
        antibiotic = Antibiotic(
            code='AMX500CAP',
            generic_name='Amoxicillin',
            strength='500 mg',
            formulation='Capsule',
            route='Oral',
        )
        db.add(antibiotic)
        db.flush()

    rule = db.scalar(
        select(AntibioticRule).where(
            AntibioticRule.antibiotic_id == antibiotic.id,
            AntibioticRule.source_reference.like('DEMO RULE%'),
        )
    )
    if not rule:
        db.add(
            AntibioticRule(
                antibiotic_id=antibiotic.id,
                min_dose=Decimal('250'),
                max_dose=Decimal('1000'),
                min_duration_days=3,
                max_duration_days=14,
                frequency_per_day_min=Decimal('2'),
                frequency_per_day_max=Decimal('4'),
                source_reference='DEMO RULE - illustrative only; replace with approved local clinical guidance',
            )
        )

    batch = db.scalar(
        select(StockBatch).where(
            StockBatch.pharmacy_id == pharmacy.id,
            StockBatch.antibiotic_id == antibiotic.id,
            StockBatch.batch_number == 'AMX-2026-0042',
        )
    )
    if not batch:
        db.add(
            StockBatch(
                pharmacy_id=pharmacy.id,
                antibiotic_id=antibiotic.id,
                batch_number='AMX-2026-0042',
                expiry_date=date.today() + timedelta(days=600),
                quantity_available=120,
                source_reference='SYNTHETIC FUNDER DEMO',
            )
        )

    # Synthetic demo staff accounts scoped strictly to FAC-KGL-001 / PHA-KGL-001
    demo_pharmacist = ensure_local_user(
        db, username='demo.pharmacist', display_name='Demo Pharmacist', password=DEMO_USER_PASSWORD
    )
    ensure_role_scope(db, user=demo_pharmacist, role=roles[ROLE_PHARMACIST], scope_type='PHARMACY', pharmacy_id=pharmacy.id)

    demo_prescriber = ensure_local_user(
        db, username='demo.prescriber', display_name='Demo Prescriber', password=DEMO_USER_PASSWORD
    )
    ensure_role_scope(db, user=demo_prescriber, role=roles[ROLE_PRESCRIBER], scope_type='FACILITY', facility_id=fac.id)

    demo_steward = ensure_local_user(
        db, username='demo.steward', display_name='Demo Stewardship Officer', password=DEMO_USER_PASSWORD
    )
    ensure_role_scope(db, user=demo_steward, role=roles[ROLE_STEWARDSHIP_OFFICER], scope_type='FACILITY', facility_id=fac.id)

    demo_admin = ensure_local_user(
        db, username='demo.admin', display_name='Demo Facility Admin', password=DEMO_USER_PASSWORD
    )
    ensure_role_scope(db, user=demo_admin, role=roles[ROLE_FACILITY_ADMIN], scope_type='FACILITY', facility_id=fac.id)

    demo_assistant = ensure_local_user(
        db, username='demo.assistant', display_name='Demo Pharmacy Assistant', password=DEMO_USER_PASSWORD
    )
    ensure_role_scope(
        db, user=demo_assistant, role=roles[ROLE_PHARMACY_ASSISTANT], scope_type='PHARMACY', pharmacy_id=pharmacy.id
    )

    demo_analyst = ensure_local_user(
        db, username='demo.analyst', display_name='Demo National Analyst', password=DEMO_USER_PASSWORD
    )
    ensure_role_scope(db, user=demo_analyst, role=roles[ROLE_NATIONAL_ANALYST], scope_type='NATIONAL_AGGREGATE')

    demo_operator = ensure_local_user(
        db, username='demo.operator', display_name='Demo Platform Operator', password=DEMO_USER_PASSWORD
    )
    ensure_role_scope(db, user=demo_operator, role=roles[ROLE_PLATFORM_OPERATOR], scope_type='PLATFORM')

    # Synthetic demo-only multi-role reviewer account for local walkthrough convenience (strictly scoped to FAC-KGL-001/PHA-KGL-001)
    demo_clinical = ensure_local_user(
        db, username='demo.clinician', display_name='Demo Facility Clinician', password=DEMO_USER_PASSWORD
    )
    ensure_role_scope(db, user=demo_clinical, role=roles[ROLE_PRESCRIBER], scope_type='FACILITY', facility_id=fac.id)
    ensure_role_scope(db, user=demo_clinical, role=roles[ROLE_PHARMACIST], scope_type='PHARMACY', pharmacy_id=pharmacy.id)
    ensure_role_scope(db, user=demo_clinical, role=roles[ROLE_STEWARDSHIP_OFFICER], scope_type='FACILITY', facility_id=fac.id)

    # Synthetic demo service clients strictly separated by partner and scope
    ensure_service_client(
        db,
        client_code='ebuzima-demo-client',
        name='Synthetic e-Buzima Demo Adapter',
        partner_type='EMR',
        key_prefix=DEMO_EBUZIMA_KEY_PREFIX,
        key_secret=DEMO_EBUZIMA_KEY_SECRET,
        scopes=[
            (SCOPE_EBUZIMA_RX_WRITE, fac.id, None),
            (SCOPE_EBUZIMA_RX_READ, fac.id, None),
            (SCOPE_EBUZIMA_CRED_WRITE, fac.id, None),
            (SCOPE_STEWARDSHIP_SUPPORT_READ, fac.id, None),
        ],
    )
    ensure_service_client(
        db,
        client_code='rms-demo-client',
        name='Synthetic RMS Demo Adapter',
        partner_type='SUPPLY_CHAIN',
        key_prefix=DEMO_RMS_KEY_PREFIX,
        key_secret=DEMO_RMS_KEY_SECRET,
        scopes=[
            (SCOPE_RMS_STOCK_WRITE, None, pharmacy.id),
            (SCOPE_DISPENSING_READ, None, pharmacy.id),
        ],
    )

    db.commit()
