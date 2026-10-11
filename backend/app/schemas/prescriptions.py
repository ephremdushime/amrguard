from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
class PrescriberIn(BaseModel):
    external_user_id:str; name:str; facility_code:str; facility_name:str; district:str
class PrescriptionItemIn(BaseModel):
    antibiotic_code:str; generic_name:str; strength:str; formulation:str; route:str
    dose:Decimal=Field(gt=0); frequency_per_day:Decimal=Field(gt=0); duration_days:int=Field(gt=0); quantity:int=Field(gt=0); indication:str=Field(min_length=1)
class PrescriptionIn(BaseModel):
    external_id:str=Field(min_length=1,max_length=100); patient_reference:str=Field(min_length=1,max_length=150); prescriber:PrescriberIn; items:list[PrescriptionItemIn]=Field(min_length=1); expires_at:datetime|None=None
class StewardshipSupportRequest(BaseModel):
    antibiotic_code:str=Field(min_length=1,max_length=50)
    generic_name:str=Field(min_length=1,max_length=200)
    dose:Decimal=Field(gt=0)
    frequency_per_day:Decimal=Field(gt=0)
    duration_days:int=Field(gt=0)
    quantity:int=Field(gt=0)
    indication:str=Field(min_length=1,max_length=300)
class StewardshipReviewRequest(BaseModel):
    outcome:Literal['CONTINUE','CHANGE','STOP','REFER']
    reason:str=Field(min_length=3,max_length=500)
    reviewer_reference:str=Field(min_length=2,max_length=150)
class ValidationIssue(BaseModel): code:str; severity:str; message:str
class PrescriptionResponse(BaseModel): model_config=ConfigDict(from_attributes=True); id:int; external_id:str; status:str; issues:list[ValidationIssue]=[]
class CredentialResponse(BaseModel): prescription_id:int; prescription_code:str; otp:str; qr_token:str; expires_at:datetime
class VerificationRequest(BaseModel): credential:str=Field(min_length=6)
class DispenseRequest(BaseModel):
    pharmacy_id:int
    batch_id:int
    item_id:int|None=None
    quantity:int=Field(gt=0)
    credential:str=Field(min_length=6)
    idempotency_key:str|None=Field(default=None,min_length=8,max_length=150)
    payment_reference:str|None=Field(default=None,max_length=150)

class StewardshipReminderRequest(BaseModel):
    consent:bool
    consent_reference:str=Field(min_length=3,max_length=150)

class RmsStockEventRequest(BaseModel):
    source_system:Literal['RMS','eLMIS']
    source_reference:str=Field(min_length=1,max_length=150)
    pharmacy_code:str=Field(min_length=1,max_length=50)
    pharmacy_name:str=Field(min_length=1,max_length=200)
    district:str=Field(min_length=1,max_length=100)
    antibiotic_code:str=Field(min_length=1,max_length=50)
    generic_name:str=Field(min_length=1,max_length=200)
    strength:str=Field(min_length=1,max_length=100)
    formulation:str=Field(min_length=1,max_length=100)
    route:str=Field(min_length=1,max_length=50)
    batch_number:str=Field(min_length=1,max_length=100)
    expiry_date:date
    event_type:Literal['RECEIPT','ADJUSTMENT']
    quantity_delta:int=Field()
