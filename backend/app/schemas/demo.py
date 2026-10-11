from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator

class DemoPrescriptionCreate(BaseModel):
    external_id: str = Field(min_length=1, max_length=100)
    patient_reference: str = Field(min_length=1, max_length=150)
    antibiotic_code: str = 'AMX500CAP'
    generic_name: str = 'Amoxicillin'
    strength: str = '500 mg'
    formulation: str = 'Capsule'
    route: str = 'Oral'
    dose: Decimal = Field(default=Decimal('500'), gt=0)
    frequency_per_day: Decimal = Field(default=Decimal('3'), gt=0)
    duration_days: int = Field(default=5, gt=0)
    quantity: int = Field(default=15, gt=0)
    indication: str = 'Demo indication'
    expires_at: datetime | None = None

    @field_validator('expires_at')
    @classmethod
    def validate_expiration(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if value <= now:
            raise ValueError('Prescription expiration must be in the future')
        if value > now + timedelta(days=30):
            raise ValueError('Prescription lifetime cannot exceed 30 days')
        return value
