from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator


class PrescriberIn(BaseModel):
    external_user_id: str
    name: str
    facility_code: str
    facility_name: str
    district: str


class PrescriptionItemIn(BaseModel):
    antibiotic_code: str
    generic_name: str
    strength: str
    formulation: str
    route: str
    dose: Decimal = Field(gt=0)
    frequency_per_day: Decimal = Field(gt=0)
    duration_days: int = Field(gt=0)
    quantity: int = Field(gt=0)
    indication: str = Field(min_length=1)
    formulation_id: int | None = None
    dose_unit: str | None = None
    is_prn: bool = False
    prn_reason: str | None = None
    instructions: str | None = None


class PrescriptionIn(BaseModel):
    external_id: str = Field(min_length=1, max_length=100)
    patient_reference: str = Field(min_length=1, max_length=150)
    prescriber: PrescriberIn
    items: list[PrescriptionItemIn] = Field(min_length=1)
    expires_at: datetime | None = None
    allow_external_dispensing: bool = False


class StewardshipSupportRequest(BaseModel):
    antibiotic_code: str = Field(min_length=1, max_length=50)
    generic_name: str = Field(min_length=1, max_length=200)
    dose: Decimal = Field(gt=0)
    frequency_per_day: Decimal = Field(gt=0)
    duration_days: int = Field(gt=0)
    quantity: int = Field(gt=0)
    indication: str = Field(min_length=1, max_length=300)


class StewardshipReviewRequest(BaseModel):
    outcome: Literal['CONTINUE', 'CHANGE', 'STOP', 'REFER']
    reason: str = Field(min_length=3, max_length=500)
    reviewer_reference: str | None = Field(default=None, min_length=2, max_length=150)


class ValidationIssue(BaseModel):
    code: str
    severity: str
    message: str


class PrescriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    external_id: str
    status: str
    issues: list[ValidationIssue] = []


class CredentialResponse(BaseModel):
    prescription_id: int
    prescription_code: str
    otp: str
    qr_token: str
    expires_at: datetime


class VerificationRequest(BaseModel):
    credential: str = Field(min_length=6)


class BatchAllocation(BaseModel):
    batch_id: int
    quantity: int = Field(gt=0)


class DispenseRequest(BaseModel):
    pharmacy_id: int
    batch_id: int | None = None
    item_id: int | None = None
    quantity: int | None = None
    allocations: list[BatchAllocation] | None = None
    credential: str = Field(min_length=6)
    idempotency_key: str = Field(min_length=8, max_length=150)
    payment_reference: str | None = Field(default=None, max_length=150)

    @model_validator(mode='after')
    def validate_allocations(self) -> 'DispenseRequest':
        if not self.allocations:
            if self.batch_id is None or self.quantity is None or self.quantity <= 0:
                raise ValueError('Either allocations or both batch_id and positive quantity must be provided')
            self.allocations = [BatchAllocation(batch_id=self.batch_id, quantity=self.quantity)]
        else:
            total_qty = sum(a.quantity for a in self.allocations)
            if self.quantity is not None and self.quantity != total_qty:
                raise ValueError('Specified quantity does not match the sum of batch allocations')
            if self.quantity is None:
                self.quantity = total_qty
            if self.batch_id is None:
                self.batch_id = self.allocations[0].batch_id
        return self


class QuarantineResolveRequest(BaseModel):
    action: Literal['APPROVE', 'REJECT', 'REPLAY']
    notes: str | None = None


class MedicineMappingCreate(BaseModel):
    source_system: str = Field(min_length=1, max_length=100)
    source_code: str = Field(min_length=1, max_length=100)
    source_description: str | None = Field(default=None, max_length=255)
    medicine_concept_id: int
    formulation_id: int | None = None
    approval_status: Literal['PENDING', 'APPROVED', 'REJECTED'] = 'APPROVED'


class StewardshipReminderRequest(BaseModel):
    consent: bool
    consent_reference: str = Field(min_length=3, max_length=150)


class RmsStockEventRequest(BaseModel):
    source_system: Literal['RMS', 'eLMIS']
    source_reference: str = Field(min_length=1, max_length=150)
    pharmacy_code: str = Field(min_length=1, max_length=50)
    pharmacy_name: str = Field(min_length=1, max_length=200)
    district: str = Field(min_length=1, max_length=100)
    antibiotic_code: str = Field(min_length=1, max_length=50)
    generic_name: str = Field(min_length=1, max_length=200)
    strength: str = Field(min_length=1, max_length=100)
    formulation: str = Field(min_length=1, max_length=100)
    route: str = Field(min_length=1, max_length=50)
    batch_number: str = Field(min_length=1, max_length=100)
    expiry_date: date
    event_type: Literal['RECEIPT', 'ADJUSTMENT']
    quantity_delta: int = Field()


# P1-06 / P1-07 Consent and Dose-Level Reminder Schemas

class ConsentCreateRequest(BaseModel):
    patient_reference: str = Field(min_length=1, max_length=150)
    phone_number: str = Field(min_length=7, max_length=30)
    purpose: Literal['DOSE_REMINDER', 'STEWARDSHIP_FOLLOWUP', 'ALL'] = 'DOSE_REMINDER'
    channel: Literal['SMS'] = 'SMS'
    language: Literal['rw', 'en', 'fr'] = 'rw'
    facility_id: int | None = None
    source_reference: str | None = Field(default=None, max_length=150)
    evidence_reference: str | None = Field(default=None, max_length=255)
    policy_version: str = Field(default='v1.0', max_length=50)


class ConsentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    patient_reference: str
    purpose: str
    channel: str
    language: str
    recipient_phone_masked: str
    status: str
    captured_at: datetime
    facility_id: int | None = None
    source_reference: str | None = None
    evidence_reference: str | None = None
    policy_version: str
    withdrawn_at: datetime | None = None
    withdrawal_reason: str | None = None


class ConsentWithdrawRequest(BaseModel):
    reason: str = Field(default='PATIENT_REQUEST', min_length=3, max_length=255)


class ReminderScheduleCreateRequest(BaseModel):
    prescription_item_id: int | None = None
    daily_times: list[str] | None = None  # e.g. ["08:00", "20:00"]
    start_date: datetime | None = None
    language: Literal['rw', 'en', 'fr'] | None = None


class ReminderOccurrenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    scheduled_at: datetime
    dose_number: int
    total_doses: int
    instructions: str | None = None
    status: str
    suppression_reason: str | None = None
    dispatched_at: datetime | None = None


class ReminderScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    prescription_id: int
    prescription_item_id: int | None = None
    patient_reference: str
    consent_record_id: int
    timezone: str
    start_date: datetime
    end_date: datetime
    daily_times: list[str]
    language: str
    status: str
    created_at: datetime
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    total_doses: int = 0
    occurrences: list[ReminderOccurrenceResponse] = []


class DispatchBatchRequest(BaseModel):
    batch_size: int = Field(default=50, ge=1, le=200)


class DeliveryCallbackRequest(BaseModel):
    provider: str = 'MOCK'
    provider_message_id: str = Field(min_length=1, max_length=150)
    event_type: Literal['DELIVERED', 'FAILED', 'REJECTED', 'UNDELIVERED'] = 'DELIVERED'
    details: dict | None = None


class InboundSmsRequest(BaseModel):
    sender_phone: str = Field(min_length=7, max_length=30)
    message_body: str = Field(min_length=1, max_length=500)
    received_at: datetime | None = None


class OutboxDispatchResponse(BaseModel):
    processed: int
    dispatched: int
    retrying: int
    dead_letter: int


class OutboxItemResponse(BaseModel):
    id: int
    destination_system: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: str
    status: str
    retry_count: int
    next_attempt_at: datetime
    last_attempt_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    dispatched_at: datetime | None = None

    class Config:
        from_attributes = True


# =============================================================================
# P2 — Stewardship Intelligence, Metrics & Governed Rules Schemas
# =============================================================================


class WhoAwareClassificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    antibiotic_code: str
    generic_name: str
    category: str
    atc_code: str | None = None
    version: str
    effective_date: date
    clinical_notes: str | None = None


class MetricDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    metric_code: str
    name: str
    category: str
    description: str
    calculation_formula: str
    target_benchmark: str | None = None
    minimum_cell_threshold: int = 5
    version: str


class EvaluatedMetricItem(BaseModel):
    metric_code: str
    name: str
    category: str
    value: float | int | None
    unit: str
    target_benchmark: str | None = None
    benchmark_met: bool
    numerator: float | int | None = None
    denominator: float | int | None = None


class GovernedMetricsResponse(BaseModel):
    facility_id: int | None = None
    evaluated_at: str
    metrics: list[EvaluatedMetricItem]
    counts: dict[str, Any]
    aware_breakdown: dict[str, Any]
    data_quality_caveats: list[str]


class StewardshipRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_code: str
    title: str
    description: str
    category: str
    severity: str
    aware_category: str | None = None
    max_duration_days: int | None = None
    requires_specialist_approval: bool = False
    version: int
    status: str
    clinical_rationale: str


class StewardshipAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    alert_id: str
    prescription_id: int
    prescription_item_id: int | None = None
    rule_code: str
    severity: str
    message: str
    clinical_evidence: str | None = None
    status: str
    disposition_outcome: str | None = None
    disposition_reason: str | None = None
    created_at: datetime


class AlertDispositionRequest(BaseModel):
    outcome: Literal['ACCEPTED', 'MODIFIED', 'OVERRIDDEN_WITH_REASON', 'FALSE_POSITIVE_FLAGGED']
    reason: str = Field(min_length=3, max_length=500)



