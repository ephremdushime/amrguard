from datetime import datetime, timezone, date
from decimal import Decimal
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


def now_utc():
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = 'organizations'

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Facility(Base):
    __tablename__ = 'facilities'

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    district: Mapped[str] = mapped_column(String(100))
    organization_id: Mapped[int | None] = mapped_column(ForeignKey('organizations.id'), index=True, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Pharmacy(Base):
    __tablename__ = 'pharmacies'

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    district: Mapped[str] = mapped_column(String(100))
    organization_id: Mapped[int | None] = mapped_column(ForeignKey('organizations.id'), index=True, nullable=True)
    facility_id: Mapped[int | None] = mapped_column(ForeignKey('facilities.id'), index=True, nullable=True)
    pharmacy_type: Mapped[str] = mapped_column(String(30), default='FACILITY_PHARMACY')
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PharmacyNetwork(Base):
    __tablename__ = 'pharmacy_networks'

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PharmacyNetworkFacility(Base):
    __tablename__ = 'pharmacy_network_facilities'
    __table_args__ = (UniqueConstraint('network_id', 'facility_id', name='uq_pharmacy_network_facility'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    network_id: Mapped[int] = mapped_column(ForeignKey('pharmacy_networks.id'), index=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey('facilities.id'), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PharmacyNetworkPharmacy(Base):
    __tablename__ = 'pharmacy_network_pharmacies'
    __table_args__ = (UniqueConstraint('network_id', 'pharmacy_id', name='uq_pharmacy_network_pharmacy'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    network_id: Mapped[int] = mapped_column(ForeignKey('pharmacy_networks.id'), index=True)
    pharmacy_id: Mapped[int] = mapped_column(ForeignKey('pharmacies.id'), index=True)
    allow_all_medicines: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PharmacyNetworkMedicinePermission(Base):
    __tablename__ = 'pharmacy_network_medicine_permissions'
    __table_args__ = (
        UniqueConstraint('network_id', 'pharmacy_id', 'antibiotic_code', name='uq_pharmacy_network_medicine_perm'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    network_id: Mapped[int] = mapped_column(ForeignKey('pharmacy_networks.id'), index=True)
    pharmacy_id: Mapped[int] = mapped_column(ForeignKey('pharmacies.id'), index=True)
    antibiotic_code: Mapped[str] = mapped_column(String(50), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class User(Base):
    __tablename__ = 'users'
    __table_args__ = (UniqueConstraint('identity_issuer', 'identity_subject', name='uq_users_issuer_subject'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    identity_issuer: Mapped[str] = mapped_column(String(255))
    identity_subject: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Role(Base):
    __tablename__ = 'roles'

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(300))


class UserRoleScope(Base):
    __tablename__ = 'user_role_scopes'
    __table_args__ = (
        CheckConstraint(
            "(scope_type = 'PHARMACY' AND pharmacy_id IS NOT NULL AND facility_id IS NULL AND organization_id IS NULL) OR "
            "(scope_type = 'FACILITY' AND facility_id IS NOT NULL AND pharmacy_id IS NULL AND organization_id IS NULL) OR "
            "(scope_type = 'ORGANIZATION' AND organization_id IS NOT NULL AND facility_id IS NULL AND pharmacy_id IS NULL) OR "
            "(scope_type IN ('NATIONAL_AGGREGATE', 'PLATFORM') AND organization_id IS NULL AND facility_id IS NULL AND pharmacy_id IS NULL)",
            name='ck_user_role_scopes_explicit_scope',
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey('roles.id'), index=True)
    scope_type: Mapped[str] = mapped_column(String(30), index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey('organizations.id'), index=True, nullable=True)
    facility_id: Mapped[int | None] = mapped_column(ForeignKey('facilities.id'), index=True, nullable=True)
    pharmacy_id: Mapped[int | None] = mapped_column(ForeignKey('pharmacies.id'), index=True, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    granted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSession(Base):
    __tablename__ = 'user_sessions'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address_truncated: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ServiceClient(Base):
    __tablename__ = 'service_clients'

    id: Mapped[int] = mapped_column(primary_key=True)
    client_code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    partner_type: Mapped[str] = mapped_column(String(50))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ServiceClientScope(Base):
    __tablename__ = 'service_client_scopes'

    id: Mapped[int] = mapped_column(primary_key=True)
    service_client_id: Mapped[int] = mapped_column(ForeignKey('service_clients.id'), index=True)
    scope: Mapped[str] = mapped_column(String(100), index=True)
    facility_id: Mapped[int | None] = mapped_column(ForeignKey('facilities.id'), index=True, nullable=True)
    pharmacy_id: Mapped[int | None] = mapped_column(ForeignKey('pharmacies.id'), index=True, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ServiceClientCredential(Base):
    __tablename__ = 'service_client_credentials'

    id: Mapped[int] = mapped_column(primary_key=True)
    service_client_id: Mapped[int] = mapped_column(ForeignKey('service_clients.id'), index=True)
    key_prefix: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Prescriber(Base):
    __tablename__ = 'prescribers'

    id: Mapped[int] = mapped_column(primary_key=True)
    external_user_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    facility_id: Mapped[int] = mapped_column(ForeignKey('facilities.id'))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Antibiotic(Base):
    __tablename__ = 'antibiotics'

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    generic_name: Mapped[str] = mapped_column(String(200))
    strength: Mapped[str] = mapped_column(String(100))
    formulation: Mapped[str] = mapped_column(String(100))
    route: Mapped[str] = mapped_column(String(50))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AntibioticRule(Base):
    __tablename__ = 'antibiotic_rules'

    id: Mapped[int] = mapped_column(primary_key=True)
    antibiotic_id: Mapped[int] = mapped_column(ForeignKey('antibiotics.id'), index=True)
    min_dose: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    max_dose: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    min_duration_days: Mapped[int | None] = mapped_column(Integer)
    max_duration_days: Mapped[int | None] = mapped_column(Integer)
    frequency_per_day_min: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    frequency_per_day_max: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source_reference: Mapped[str] = mapped_column(Text, default='Configured clinical guidance')


class Prescription(Base):
    __tablename__ = 'prescriptions'

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    patient_reference: Mapped[str] = mapped_column(String(150), index=True)
    prescriber_id: Mapped[int] = mapped_column(ForeignKey('prescribers.id'))
    facility_id: Mapped[int] = mapped_column(ForeignKey('facilities.id'))
    status: Mapped[str] = mapped_column(String(30), default='CREATED', index=True)
    allow_external_dispensing: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items: Mapped[list['PrescriptionItem']] = relationship(back_populates='prescription', cascade='all, delete-orphan')


class PrescriptionItem(Base):
    __tablename__ = 'prescription_items'

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey('prescriptions.id'), index=True)
    antibiotic_id: Mapped[int] = mapped_column(ForeignKey('antibiotics.id'))
    dose: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    frequency_per_day: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    duration_days: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    indication: Mapped[str] = mapped_column(String(300))
    prescription: Mapped[Prescription] = relationship(back_populates='items')


class PrescriptionCredential(Base):
    __tablename__ = 'prescription_credentials'

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey('prescriptions.id'), unique=True)
    otp_hash: Mapped[str] = mapped_column(String(128), index=True)
    qr_token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    token_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    issued_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    intended_pharmacy_id: Mapped[int | None] = mapped_column(ForeignKey('pharmacies.id'), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)


class StewardshipReminder(Base):
    __tablename__ = 'stewardship_reminders'

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey('prescriptions.id'), unique=True, index=True)
    consent_recorded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    consent_reference: Mapped[str | None] = mapped_column(String(150))
    consent_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default='PENDING_PROVIDER')
    provider_reference: Mapped[str | None] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class StewardshipReview(Base):
    __tablename__ = 'stewardship_reviews'
    __table_args__ = (UniqueConstraint('prescription_id', 'review_type'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey('prescriptions.id'), index=True)
    review_type: Mapped[str] = mapped_column(String(40), default='POST_DISPENSE')
    status: Mapped[str] = mapped_column(String(30), default='PENDING', index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(String(500))
    reviewer_reference: Mapped[str | None] = mapped_column(String(150))
    reviewer_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), index=True, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class StockBatch(Base):
    __tablename__ = 'stock_batches'
    __table_args__ = (UniqueConstraint('pharmacy_id', 'antibiotic_id', 'batch_number'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pharmacy_id: Mapped[int] = mapped_column(ForeignKey('pharmacies.id'), index=True)
    antibiotic_id: Mapped[int] = mapped_column(ForeignKey('antibiotics.id'))
    batch_number: Mapped[str] = mapped_column(String(100), index=True)
    expiry_date: Mapped[date] = mapped_column(Date)
    quantity_available: Mapped[int] = mapped_column(Integer)
    source_reference: Mapped[str | None] = mapped_column(String(150))


class StockEvent(Base):
    __tablename__ = 'stock_events'
    __table_args__ = (
        Index(
            'uq_stock_events_source_reference',
            'source_system',
            'reference_id',
            unique=True,
            sqlite_where=text('reference_id IS NOT NULL'),
            postgresql_where=text('reference_id IS NOT NULL'),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey('stock_batches.id'), index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    quantity: Mapped[int] = mapped_column(Integer)
    reference_id: Mapped[str | None] = mapped_column(String(150))
    source_system: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    details: Mapped[str] = mapped_column(Text, default='{}')


class DispensingTransaction(Base):
    __tablename__ = 'dispensing_transactions'

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(150), unique=True, index=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey('prescriptions.id'), index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey('prescription_items.id'))
    pharmacy_id: Mapped[int] = mapped_column(ForeignKey('pharmacies.id'))
    batch_id: Mapped[int] = mapped_column(ForeignKey('stock_batches.id'))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), index=True, nullable=True)
    prescribing_facility_id: Mapped[int | None] = mapped_column(ForeignKey('facilities.id'), index=True, nullable=True)
    dispensing_facility_id: Mapped[int | None] = mapped_column(ForeignKey('facilities.id'), index=True, nullable=True)
    is_cross_facility: Mapped[bool] = mapped_column(Boolean, default=False)
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default='COMPLETED')
    payment_reference: Mapped[str | None] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AuditEvent(Base):
    __tablename__ = 'audit_events'

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(100))
    source_system: Mapped[str] = mapped_column(String(100))
    actor_type: Mapped[str] = mapped_column(String(30), default='SYSTEM', index=True)
    actor_id: Mapped[str | None] = mapped_column(String(150), index=True, nullable=True)
    facility_id: Mapped[int | None] = mapped_column(ForeignKey('facilities.id'), index=True, nullable=True)
    pharmacy_id: Mapped[int | None] = mapped_column(ForeignKey('pharmacies.id'), index=True, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    outcome: Mapped[str] = mapped_column(String(30), default='SUCCESS', index=True)
    details: Mapped[str] = mapped_column(Text, default='{}')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
