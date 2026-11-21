from datetime import date, datetime
from decimal import Decimal
from typing import Literal
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
