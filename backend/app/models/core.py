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


class MedicineConcept(Base):
    __tablename__ = 'medicine_concepts'
    __table_args__ = (
        UniqueConstraint('coding_system', 'code', name='uq_medicine_concepts_system_code'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    coding_system: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(100), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    aware_category: Mapped[str] = mapped_column(String(50), default='ACCESS')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    formulations: Mapped[list['Formulation']] = relationship(back_populates='concept', cascade='all, delete-orphan')


class Formulation(Base):
    __tablename__ = 'formulations'

    id: Mapped[int] = mapped_column(primary_key=True)
    medicine_concept_id: Mapped[int] = mapped_column(ForeignKey('medicine_concepts.id'), index=True)
    strength_value: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    strength_unit: Mapped[str] = mapped_column(String(50))
    dose_form: Mapped[str] = mapped_column(String(100))
    route: Mapped[str] = mapped_column(String(50))
    units_per_pack: Mapped[int] = mapped_column(Integer, default=1)
    unit_of_measure: Mapped[str] = mapped_column(String(50), default='unit')
    liquid_concentration_mg_per_ml: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    is_divisible: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    concept: Mapped[MedicineConcept] = relationship(back_populates='formulations')


class MedicineMapping(Base):
    __tablename__ = 'medicine_mappings'
    __table_args__ = (
        UniqueConstraint('source_system', 'source_code', name='uq_medicine_mappings_source_code'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_system: Mapped[str] = mapped_column(String(100))
    source_code: Mapped[str] = mapped_column(String(100))
    source_description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    medicine_concept_id: Mapped[int] = mapped_column(ForeignKey('medicine_concepts.id'), index=True)
    formulation_id: Mapped[int | None] = mapped_column(ForeignKey('formulations.id'), nullable=True)
    approval_status: Mapped[str] = mapped_column(String(50), default='PENDING')
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    concept: Mapped[MedicineConcept] = relationship()
    formulation: Mapped[Formulation | None] = relationship()


class IntegrationInbox(Base):
    __tablename__ = 'integration_inbox'

    id: Mapped[int] = mapped_column(primary_key=True)
    source_system: Mapped[str] = mapped_column(String(100), index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    external_id: Mapped[str] = mapped_column(String(150), index=True)
    payload: Mapped[str] = mapped_column(Text)
    quarantine_reason: Mapped[str] = mapped_column(String(150))
    unresolved_code: Mapped[str | None] = mapped_column(String(150), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default='QUARANTINED', index=True)
    facility_id: Mapped[int | None] = mapped_column(ForeignKey('facilities.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


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
    reminder_schedules: Mapped[list['ReminderSchedule']] = relationship(back_populates='prescription', cascade='all, delete-orphan')


class PrescriptionItem(Base):
    __tablename__ = 'prescription_items'

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey('prescriptions.id'), index=True)
    antibiotic_id: Mapped[int] = mapped_column(ForeignKey('antibiotics.id'))
    formulation_id: Mapped[int | None] = mapped_column(ForeignKey('formulations.id'), nullable=True)
    dose: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    dose_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    frequency_per_day: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    duration_days: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    indication: Mapped[str] = mapped_column(String(300))
    is_prn: Mapped[bool] = mapped_column(Boolean, default=False)
    prn_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversion_review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    prescription: Mapped[Prescription] = relationship(back_populates='items')
    formulation: Mapped['Formulation | None'] = relationship()
    reminder_schedules: Mapped[list['ReminderSchedule']] = relationship(back_populates='prescription_item')


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
    reconciliation_status: Mapped[str] = mapped_column(String(50), default='PENDING_RECONCILIATION', index=True)
    payment_reference: Mapped[str | None] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    dispensing_items: Mapped[list['DispensingItem']] = relationship(back_populates='transaction', cascade='all, delete-orphan')


class DispensingItem(Base):
    __tablename__ = 'dispensing_items'

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey('dispensing_transactions.id'), index=True)
    prescription_item_id: Mapped[int] = mapped_column(ForeignKey('prescription_items.id'), index=True)
    quantity_requested: Mapped[int] = mapped_column(Integer)
    quantity_dispensed: Mapped[int] = mapped_column(Integer)
    fulfillment_status: Mapped[str] = mapped_column(String(50), default='FULL')
    refusal_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    transaction: Mapped[DispensingTransaction] = relationship(back_populates='dispensing_items')
    batch_links: Mapped[list['DispensingBatchLink']] = relationship(back_populates='dispensing_item', cascade='all, delete-orphan')


class DispensingBatchLink(Base):
    __tablename__ = 'dispensing_batch_links'

    id: Mapped[int] = mapped_column(primary_key=True)
    dispensing_item_id: Mapped[int] = mapped_column(ForeignKey('dispensing_items.id'), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey('stock_batches.id'), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    dispensing_item: Mapped[DispensingItem] = relationship(back_populates='batch_links')
    batch: Mapped[StockBatch] = relationship()


class IntegrationOutbox(Base):
    __tablename__ = 'integration_outbox'

    id: Mapped[int] = mapped_column(primary_key=True)
    destination_system: Mapped[str] = mapped_column(String(100), index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    aggregate_type: Mapped[str] = mapped_column(String(100))
    aggregate_id: Mapped[str] = mapped_column(String(150))
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default='PENDING', index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


class ConsentRecord(Base):
    __tablename__ = 'consent_records'

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_reference: Mapped[str] = mapped_column(String(100), index=True)
    purpose: Mapped[str] = mapped_column(String(50), index=True)  # DOSE_REMINDER, STEWARDSHIP_FOLLOWUP, ALL
    channel: Mapped[str] = mapped_column(String(30), default='SMS')
    language: Mapped[str] = mapped_column(String(10), default='rw')  # rw, en, fr
    recipient_phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    recipient_phone_masked: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default='ACTIVE', index=True)  # ACTIVE, WITHDRAWN, EXPIRED
    captured_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), index=True, nullable=True)
    facility_id: Mapped[int | None] = mapped_column(ForeignKey('facilities.id'), index=True, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    source_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(50), default='v1.0')
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), index=True, nullable=True)
    withdrawal_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    schedules: Mapped[list['ReminderSchedule']] = relationship(back_populates='consent_record')
    outbox_messages: Mapped[list['MessageOutbox']] = relationship(back_populates='consent_record')


class ReminderSchedule(Base):
    __tablename__ = 'reminder_schedules'

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey('prescriptions.id'), index=True)
    prescription_item_id: Mapped[int | None] = mapped_column(ForeignKey('prescription_items.id'), index=True, nullable=True)
    patient_reference: Mapped[str] = mapped_column(String(100), index=True)
    consent_record_id: Mapped[int] = mapped_column(ForeignKey('consent_records.id'), index=True)
    timezone: Mapped[str] = mapped_column(String(50), default='Africa/Kigali')
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    daily_times: Mapped[str] = mapped_column(Text)  # JSON encoded list of "HH:MM"
    language: Mapped[str] = mapped_column(String(10), default='rw')
    status: Mapped[str] = mapped_column(String(30), default='ACTIVE', index=True)  # ACTIVE, PAUSED, CANCELLED, COMPLETED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    prescription: Mapped[Prescription] = relationship(back_populates='reminder_schedules')
    prescription_item: Mapped[PrescriptionItem | None] = relationship(back_populates='reminder_schedules')
    consent_record: Mapped[ConsentRecord] = relationship(back_populates='schedules')
    occurrences: Mapped[list['ReminderOccurrence']] = relationship(back_populates='schedule', cascade='all, delete-orphan')


class ReminderOccurrence(Base):
    __tablename__ = 'reminder_occurrences'

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey('reminder_schedules.id'), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    dose_number: Mapped[int] = mapped_column(Integer)
    total_doses: Mapped[int] = mapped_column(Integer)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default='PENDING', index=True)  # PENDING, QUEUED, SENT, CANCELLED, SUPPRESSED
    suppression_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    schedule: Mapped[ReminderSchedule] = relationship(back_populates='occurrences')
    outbox_messages: Mapped[list['MessageOutbox']] = relationship(back_populates='occurrence')


class MessageOutbox(Base):
    __tablename__ = 'message_outbox'

    id: Mapped[int] = mapped_column(primary_key=True)
    occurrence_id: Mapped[int | None] = mapped_column(ForeignKey('reminder_occurrences.id'), index=True, nullable=True)
    consent_record_id: Mapped[int] = mapped_column(ForeignKey('consent_records.id'), index=True)
    destination_hash: Mapped[str] = mapped_column(String(64), index=True)
    destination_masked: Mapped[str] = mapped_column(String(30))
    message_text: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(30), default='SMS')
    status: Mapped[str] = mapped_column(String(30), default='PENDING', index=True)  # PENDING, LEASED, SENT, FAILED, DEAD_LETTER, CANCELLED
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    lease_token: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(150), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    occurrence: Mapped[ReminderOccurrence | None] = relationship(back_populates='outbox_messages')
    consent_record: Mapped[ConsentRecord] = relationship(back_populates='outbox_messages')
    delivery_events: Mapped[list['MessageDeliveryEvent']] = relationship(back_populates='outbox', cascade='all, delete-orphan')


class MessageDeliveryEvent(Base):
    # CLINICAL SAFETY INVARIANT:
    # A message delivery event confirms network/provider transmission only.
    # It DOES NOT prove patient ingestion or medication adherence.
    __tablename__ = 'message_delivery_events'

    id: Mapped[int] = mapped_column(primary_key=True)
    outbox_id: Mapped[int] = mapped_column(ForeignKey('message_outbox.id'), index=True)
    provider: Mapped[str] = mapped_column(String(50), default='MOCK')
    provider_message_id: Mapped[str] = mapped_column(String(150), index=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)  # DELIVERED, FAILED, REJECTED, UNDELIVERED
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    outbox: Mapped[MessageOutbox] = relationship(back_populates='delivery_events')


# =============================================================================
# P2 — Stewardship Intelligence, Metrics & Governed Rules Models
# =============================================================================


class WhoAwareClassification(Base):
    """Authoritative WHO AWaRe antibiotic classification reference table."""

    __tablename__ = 'who_aware_classifications'

    id: Mapped[int] = mapped_column(primary_key=True)
    antibiotic_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    generic_name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20), index=True)  # ACCESS, WATCH, RESERVE, DISCOURAGED
    atc_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    version: Mapped[str] = mapped_column(String(30), default='WHO_2023_V1')
    effective_date: Mapped[date] = mapped_column(Date)
    clinical_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class MetricDefinition(Base):
    """Governed stewardship KPI / metric dictionary definition."""

    __tablename__ = 'metric_definitions'

    id: Mapped[int] = mapped_column(primary_key=True)
    metric_code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), index=True)  # AWARE_UTILIZATION, DISPENSING_FIDELITY, STEWARDSHIP_TIMELINESS
    numerator_definition: Mapped[str] = mapped_column(Text)
    denominator_definition: Mapped[str] = mapped_column(Text)
    calculation_formula: Mapped[str] = mapped_column(Text)
    target_benchmark: Mapped[str | None] = mapped_column(String(50), nullable=True)
    minimum_cell_threshold: Mapped[int] = mapped_column(Integer, default=5)
    effective_from: Mapped[date] = mapped_column(Date)
    version: Mapped[str] = mapped_column(String(20), default='1.0')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class GovernedStewardshipRule(Base):
    """Clinically governed antimicrobial stewardship rule with versioning and approval workflow."""

    __tablename__ = 'stewardship_rules'

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50))  # DOSAGE, DURATION, AWARE_RESTRICTION, INDICATION_MISMATCH
    severity: Mapped[str] = mapped_column(String(20), default='WARNING')  # WARNING, BLOCK, REVIEW_REQUIRED
    antibiotic_id: Mapped[int | None] = mapped_column(ForeignKey('antibiotics.id'), nullable=True)
    aware_category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    max_duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_daily_dose: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    requires_specialist_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default='ACTIVE', index=True)  # ACTIVE, DRAFT, SUPERSEDED, REVOKED
    effective_start_date: Mapped[date] = mapped_column(Date)
    effective_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clinical_rationale: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    antibiotic: Mapped[Antibiotic | None] = relationship()
    approved_by: Mapped[User | None] = relationship()


class StewardshipAlert(Base):
    """Structured alert generated by clinical rule evaluation, tracking disposition and overrides."""

    __tablename__ = 'stewardship_alerts'

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey('prescriptions.id'), index=True)
    prescription_item_id: Mapped[int | None] = mapped_column(ForeignKey('prescription_items.id'), nullable=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey('stewardship_rules.id'), index=True)
    rule_code: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(20))  # WARNING, BLOCK, REVIEW_REQUIRED
    message: Mapped[str] = mapped_column(Text)
    clinical_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default='OPEN', index=True)  # OPEN, ACKNOWLEDGED, OVERRIDDEN, RESOLVED, FALSE_POSITIVE
    disposition_outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)  # ACCEPTED, MODIFIED, OVERRIDDEN_WITH_REASON, FALSE_POSITIVE_FLAGGED
    disposition_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    disposition_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    disposition_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    prescription: Mapped[Prescription] = relationship()
    rule: Mapped[GovernedStewardshipRule] = relationship()
    disposition_user: Mapped[User | None] = relationship()

