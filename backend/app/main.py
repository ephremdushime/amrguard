from datetime import datetime, timezone, timedelta
import json, secrets
from uuid import uuid4
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy import inspect
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from pathlib import Path
from app.core.config import settings
from app.core.security import require_funder_demo_ui_or_integration_key, require_integration_key
from app.db.session import Base, engine, get_db
from app.db.seed import seed_demo
from app.models.core import *
from app.schemas.prescriptions import *
from app.schemas.demo import DemoPrescriptionCreate
from app.services.validation import validate_item
from app.services.security import digest
from app.services.fhir import prescription_to_medication_request, dispensing_to_medication_dispense

API_VERSION = 'v1'
APP_VERSION = '0.7.0'
@asynccontextmanager
async def lifespan(app):
    if settings.app_env=='funder_demo':
        db=next(get_db())
        try:
            seed_demo(db)
            yield
        finally:
            db.close()
        return
    if settings.app_env in {'demo', 'development', 'test'}:
        db=next(get_db())
        try:
            if not settings.database_url.startswith('sqlite') or settings.database_url.endswith('test_amrguard.db'):
                seed_demo(db)
            yield
        finally:
            db.close()
    else:
        yield

app = FastAPI(title='AMRGuard API', version=APP_VERSION, description='Antibiotic-specific interoperability and transaction layer. Production connectors are implemented through approved adapters.', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.allowed_origins.split(',') if x.strip()], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

# Local demo databases are bootstrapped for convenience. Hosted modes are migrated by Alembic at container startup.
if settings.app_env in {'demo', 'development', 'test','funder_demo'}:
    inspector=inspect(engine)
    if inspector.has_table('alembic_version'):
        migration_config=AlembicConfig(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
        migration_config.set_main_option('script_location',str(Path(__file__).resolve().parents[1]/'alembic'))
        alembic_command.upgrade(migration_config,'head')
    elif inspector.has_table('facilities'):
        if settings.app_env=='funder_demo':
            raise RuntimeError('Funder demo database is unversioned. Use a fresh dedicated funder demo database.')
        pass  # Keep legacy local demo data untouched; upgrades are run explicitly through Alembic.
    else:
        Base.metadata.create_all(bind=engine)

def utcnow(): return datetime.now(timezone.utc)

def is_expired(value):
    if value is None: return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= utcnow()

def audit(db,event,entity,entity_id,source,details=None):
    db.add(AuditEvent(event_type=event, entity_type=entity, entity_id=str(entity_id), source_system=source, details=json.dumps(details or {})))

def rx_view(rx,issues):
    return PrescriptionResponse(id=rx.id, external_id=rx.external_id, status=rx.status, issues=[ValidationIssue(**i) for i in issues])

def prescription_detail(rx, db):
    items=[]
    for item in rx.items:
        ab=db.get(Antibiotic,item.antibiotic_id)
        items.append({'id':item.id,'antibiotic':ab.generic_name,'code':ab.code,'strength':ab.strength,'formulation':ab.formulation,'route':ab.route,'dose':str(item.dose),'frequency_per_day':str(item.frequency_per_day),'duration_days':item.duration_days,'authorized_quantity':item.quantity,'indication':item.indication})
    pr=db.get(Prescriber,rx.prescriber_id); fac=db.get(Facility,rx.facility_id)
    return {'id':rx.id,'code':f'AMR-RX-{rx.id:06d}','external_id':rx.external_id,'status':rx.status,'prescriber':{'id':pr.external_user_id,'name':pr.name},'facility':{'code':fac.code,'name':fac.name},'patient_reference':rx.patient_reference,'created_at':rx.created_at,'expires_at':rx.expires_at,'items':items}

@app.middleware('http')
async def request_id_middleware(request: Request, call_next):
    request_id=request.headers.get('X-Request-ID') or str(uuid4())
    response=await call_next(request)
    response.headers['X-Request-ID']=request_id
    return response

@app.get('/health')
def health(): return {'status':'ok','service':'AMRGuard','version':APP_VERSION,'environment':settings.app_env}

@app.get('/health/ready')
def readiness(db:Session=Depends(get_db)):
    db.execute(select(1))
    return {'status':'ready','service':'AMRGuard'}

@app.get('/api/v1/meta')
def meta():
    return {'name':'AMRGuard','version':APP_VERSION,'api_version':API_VERSION,'integration_mode':'adapter-ready','demo_data':settings.app_env=='demo','standards':'REST/OpenAPI; FHIR-compatible mapping layer','security':'integration-key gate available; replace/extend with approved service-to-service auth'}

@app.post('/api/v1/stewardship/support')
    def stewardship_support(payload:StewardshipSupportRequest,db:Session=Depends(get_db),_auth:bool=Depends(require_funder_demo_ui_or_integration_key)):
    """Return an embeddable, non-prescriptive stewardship review for a source EMR.

    Local antibiotic rules must be governed and approved before they are treated as
    clinical guidance. This endpoint reports deterministic checks only.
    """
    expected=payload.frequency_per_day*payload.duration_days
    issues=[]
    mismatch=expected != int(expected) or payload.quantity != int(expected)
    if mismatch:
        issues.append({'code':'QUANTITY_MISMATCH','severity':'BLOCK','message':f'Entered quantity {payload.quantity} differs from administrations/day × duration ({expected}).'})
    antibiotic=db.scalar(select(Antibiotic).where(Antibiotic.code==payload.antibiotic_code))
    category='UNCLASSIFIED'
    if antibiotic:
        demo_rule=db.scalar(select(AntibioticRule).where(AntibioticRule.antibiotic_id==antibiotic.id,AntibioticRule.enabled.is_(True)))
        if demo_rule and demo_rule.source_reference.startswith('DEMO RULE'):
            issues.append({'code':'DEMO_RULESET','severity':'INFO','message':'Illustrative demo rules are configured for this product; they are not approved prescribing guidance.'})
    review_days=3
    return {
        'decision':'REVIEW_REQUIRED' if mismatch else 'CHECKS_PASSED',
        'issues':issues,
        'stewardship':{
            'aware_category':category,
            'review_prompt':f'Review clinical response and available results at approximately day {review_days}, according to local protocol.',
            'indication_captured':bool(payload.indication.strip()),
        },
        'display':{
            'message':'Resolve the quantity discrepancy before continuing.' if mismatch else 'No configured transaction checks were triggered. Confirm clinical appropriateness using approved local guidance.',
            'severity':'error' if mismatch else 'information',
        },
        'governance':{'clinical_recommendation':False,'ruleset':'transaction checks only','requires_local_guideline_review':True}
    }

@app.post('/api/v1/integrations/ebuzima/prescriptions',response_model=PrescriptionResponse,dependencies=[Depends(require_integration_key)])
def receive_prescription(payload:PrescriptionIn,db:Session=Depends(get_db)):
    existing=db.scalar(select(Prescription).where(Prescription.external_id==payload.external_id))
    if existing:
        return rx_view(existing,[])
    fac=db.scalar(select(Facility).where(Facility.code==payload.prescriber.facility_code))
    if not fac:
        fac=Facility(code=payload.prescriber.facility_code,name=payload.prescriber.facility_name,district=payload.prescriber.district); db.add(fac); db.flush()
    pr=db.scalar(select(Prescriber).where(Prescriber.external_user_id==payload.prescriber.external_user_id))
    if not pr:
        pr=Prescriber(external_user_id=payload.prescriber.external_user_id,name=payload.prescriber.name,facility_id=fac.id); db.add(pr); db.flush()
    rx=Prescription(external_id=payload.external_id,patient_reference=payload.patient_reference,prescriber_id=pr.id,facility_id=fac.id,expires_at=payload.expires_at); db.add(rx); db.flush()
    issues=[]
    for p in payload.items:
        ab=db.scalar(select(Antibiotic).where(Antibiotic.code==p.antibiotic_code))
        if not ab:
            ab=Antibiotic(code=p.antibiotic_code,generic_name=p.generic_name,strength=p.strength,formulation=p.formulation,route=p.route); db.add(ab); db.flush()
        rule=db.scalar(select(AntibioticRule).where(AntibioticRule.antibiotic_id==ab.id,AntibioticRule.enabled.is_(True)))
        item=PrescriptionItem(prescription_id=rx.id,antibiotic_id=ab.id,dose=p.dose,frequency_per_day=p.frequency_per_day,duration_days=p.duration_days,quantity=p.quantity,indication=p.indication); db.add(item); db.flush(); issues += validate_item(item,rule)
    blocks=[i for i in issues if i['severity']=='BLOCK']; rx.status='BLOCKED' if blocks else ('WARNING' if issues else 'VALIDATED')
    audit(db,'PRESCRIPTION_RECEIVED','Prescription',rx.id,'e-Buzima',{'external_id':rx.external_id}); db.commit(); return rx_view(rx,issues)

@app.get('/api/v1/prescriptions/{prescription_id}')
def get_prescription(prescription_id:int,db:Session=Depends(get_db)):
    rx=db.get(Prescription,prescription_id)
    if not rx: raise HTTPException(404,'Prescription not found')
    return prescription_detail(rx,db)

@app.post('/api/v1/prescriptions/{prescription_id}/credential',response_model=CredentialResponse)
def create_credential(prescription_id:int,db:Session=Depends(get_db)):
    rx=db.get(Prescription,prescription_id)
    if not rx: raise HTTPException(404,'Prescription not found')
    if rx.status not in {'VALIDATED','WARNING','ACTIVE','PARTIALLY_DISPENSED'}: raise HTTPException(409,f'Prescription is {rx.status}')
    old=db.scalar(select(PrescriptionCredential).where(PrescriptionCredential.prescription_id==rx.id))
    otp=f'{secrets.randbelow(1000000):06d}'; token=secrets.token_urlsafe(32); expiry=utcnow()+timedelta(minutes=10)
    if old:
        old.otp_hash=digest(otp); old.qr_token_hash=digest(token); old.expires_at=expiry; old.revoked=False; old.used_count=0
    else:
        db.add(PrescriptionCredential(prescription_id=rx.id,otp_hash=digest(otp),qr_token_hash=digest(token),expires_at=expiry))
    rx.status='ACTIVE'; audit(db,'CREDENTIAL_CREATED','Prescription',rx.id,'AMRGuard'); db.commit()
    return CredentialResponse(prescription_id=rx.id,prescription_code=f'AMR-RX-{rx.id:06d}',otp=otp,qr_token=token,expires_at=expiry)

def verify_credential(credential,db,consume=False):
    cred = db.scalar(select(PrescriptionCredential).where(PrescriptionCredential.otp_hash==digest(credential))) if credential.isdigit() and len(credential)==6 else db.scalar(select(PrescriptionCredential).where(PrescriptionCredential.qr_token_hash==digest(credential)))
    if not cred or cred.revoked or is_expired(cred.expires_at): raise HTTPException(401,'Invalid or expired credential')
    rx=db.get(Prescription,cred.prescription_id)
    if not rx: raise HTTPException(404,'Prescription not found')
    if rx.status in {'CANCELLED','EXPIRED','COMPLETED','BLOCKED'}: raise HTTPException(409,f'Prescription is {rx.status}')
    if consume: cred.used_count += 1
    audit(db,'CREDENTIAL_VERIFIED','Prescription',rx.id,'Pharmacy',{'method':'OTP' if credential.isdigit() else 'QR','consumed':consume})
    return rx

@app.post('/api/v1/verification')
def verify(request:VerificationRequest,db:Session=Depends(get_db)):
    rx=verify_credential(request.credential,db); db.commit(); return {'verified':True,'prescription':prescription_detail(rx,db)}

@app.post('/api/v1/verification/otp')
def verify_otp(otp:str=Query(min_length=6,max_length=6),db:Session=Depends(get_db)):
    rx=verify_credential(otp,db); db.commit(); return {'verified':True,'prescription_id':rx.id,'prescription_code':f'AMR-RX-{rx.id:06d}','status':rx.status}

@app.get('/api/v1/prescriptions')
def list_prescriptions(limit:int=Query(default=25, ge=1, le=100), status:str|None=None, db:Session=Depends(get_db)):
    query=select(Prescription).order_by(Prescription.created_at.desc()).limit(limit)
    if status: query=query.where(Prescription.status==status.upper())
    rows=db.scalars(query).all()
    return [prescription_detail(rx,db) for rx in rows]

@app.get('/api/v1/stock/batches')
def list_stock_batches(pharmacy_id:int|None=None, db:Session=Depends(get_db)):
    query=select(StockBatch).order_by(StockBatch.expiry_date,StockBatch.batch_number)
    if pharmacy_id is not None: query=query.where(StockBatch.pharmacy_id==pharmacy_id)
    rows=db.scalars(query).all(); result=[]
    for batch in rows:
        pharmacy=db.get(Pharmacy,batch.pharmacy_id); antibiotic=db.get(Antibiotic,batch.antibiotic_id)
        if pharmacy and antibiotic:
            result.append({'id':batch.id,'pharmacy_id':pharmacy.id,'pharmacy_name':pharmacy.name,'pharmacy_code':pharmacy.code,'antibiotic_id':antibiotic.id,'antibiotic':antibiotic.generic_name,'antibiotic_code':antibiotic.code,'strength':antibiotic.strength,'formulation':antibiotic.formulation,'batch_number':batch.batch_number,'expiry_date':batch.expiry_date,'quantity_available':batch.quantity_available,'source_reference':batch.source_reference})
    return result

@app.post('/api/v1/integrations/rms/stock-events',dependencies=[Depends(require_integration_key)])
def receive_rms_stock_event(request:RmsStockEventRequest,db:Session=Depends(get_db)):
    if request.event_type=='RECEIPT' and request.quantity_delta<=0:
        raise HTTPException(422,'Receipt quantity_delta must be positive')
    if request.quantity_delta==0:
        raise HTTPException(422,'quantity_delta cannot be zero')
    details={'pharmacy_code':request.pharmacy_code,'antibiotic_code':request.antibiotic_code,'batch_number':request.batch_number,'expiry_date':request.expiry_date.isoformat(),'event_type':request.event_type,'quantity_delta':request.quantity_delta}
    prior=db.scalar(select(StockEvent).where(StockEvent.source_system==request.source_system,StockEvent.reference_id==request.source_reference))
    if prior:
        if json.loads(prior.details or '{}')!=details:
            raise HTTPException(409,'Source event reference was already used for a different stock movement')
        batch=db.get(StockBatch,prior.batch_id)
        return {'accepted':True,'replayed':True,'event_id':prior.id,'batch_id':prior.batch_id,'quantity_available':batch.quantity_available if batch else None}
    pharmacy=db.scalar(select(Pharmacy).where(Pharmacy.code==request.pharmacy_code))
    if not pharmacy:
        pharmacy=Pharmacy(code=request.pharmacy_code,name=request.pharmacy_name,district=request.district,active=True); db.add(pharmacy); db.flush()
    antibiotic=db.scalar(select(Antibiotic).where(Antibiotic.code==request.antibiotic_code))
    if not antibiotic:
        antibiotic=Antibiotic(code=request.antibiotic_code,generic_name=request.generic_name,strength=request.strength,formulation=request.formulation,route=request.route,active=True); db.add(antibiotic); db.flush()
    elif (antibiotic.generic_name,antibiotic.strength,antibiotic.formulation,antibiotic.route)!=(request.generic_name,request.strength,request.formulation,request.route):
        raise HTTPException(409,'Antibiotic catalog fields conflict with the existing canonical item')
    batch=db.scalar(select(StockBatch).where(StockBatch.pharmacy_id==pharmacy.id,StockBatch.antibiotic_id==antibiotic.id,StockBatch.batch_number==request.batch_number))
    if not batch:
        if request.event_type!='RECEIPT': raise HTTPException(404,'A stock batch must be received before it can be adjusted')
        batch=StockBatch(pharmacy_id=pharmacy.id,antibiotic_id=antibiotic.id,batch_number=request.batch_number,expiry_date=request.expiry_date,quantity_available=0,source_reference=request.source_reference); db.add(batch); db.flush()
    elif batch.expiry_date!=request.expiry_date:
        raise HTTPException(409,'Batch expiry conflicts with the existing stock record')
    updated_quantity=batch.quantity_available+request.quantity_delta
    if updated_quantity<0: raise HTTPException(409,'Stock adjustment would make available quantity negative')
    batch.quantity_available=updated_quantity
    event=StockEvent(batch_id=batch.id,event_type=request.event_type,quantity=request.quantity_delta,reference_id=request.source_reference,source_system=request.source_system,details=json.dumps(details)); db.add(event)
    audit(db,'STOCK_EVENT_RECEIVED','StockBatch',batch.id,request.source_system,details)
    db.commit(); db.refresh(event)
    return {'accepted':True,'replayed':False,'event_id':event.id,'batch_id':batch.id,'quantity_available':batch.quantity_available}

@app.post('/api/v1/prescriptions/{prescription_id}/stewardship-reminder')
def schedule_stewardship_reminder(prescription_id:int, request:StewardshipReminderRequest, db:Session=Depends(get_db)):
    rx=db.get(Prescription,prescription_id)
    if not rx: raise HTTPException(404,'Prescription not found')
    if not request.consent: raise HTTPException(422,'Patient consent is required before scheduling an SMS reminder')
    if rx.status=='BLOCKED' or not rx.items: raise HTTPException(409,'A blocked or empty prescription cannot receive a stewardship reminder')
    existing=db.scalar(select(StewardshipReminder).where(StewardshipReminder.prescription_id==rx.id))
    if existing: raise HTTPException(409,'A stewardship reminder is already scheduled for this prescription')
    first_dispense=db.scalar(select(func.min(DispensingTransaction.created_at)).where(DispensingTransaction.prescription_id==rx.id))
    if not first_dispense: raise HTTPException(409,'A stewardship reminder can only be scheduled after pharmacy dispensing')
    course_end=first_dispense+timedelta(days=max(item.duration_days for item in rx.items))
    if course_end.tzinfo is None: course_end=course_end.replace(tzinfo=timezone.utc)
    scheduled_at=max(course_end,utcnow())
    reminder=StewardshipReminder(prescription_id=rx.id,consent_recorded=True,consent_reference=request.consent_reference.strip(),consent_recorded_at=utcnow(),scheduled_at=scheduled_at,status='PENDING_PROVIDER')
    db.add(reminder); audit(db,'STEWARDSHIP_REMINDER_SCHEDULED','Prescription',rx.id,'AMRGuard',{'scheduled_at':scheduled_at.isoformat(),'delivery_status':'PENDING_PROVIDER','consent_reference':request.consent_reference.strip()}); db.commit(); db.refresh(reminder)
    return {'id':reminder.id,'prescription_id':rx.id,'prescription_code':f'AMR-RX-{rx.id:06d}','scheduled_at':reminder.scheduled_at,'status':reminder.status,'consent_recorded':reminder.consent_recorded,'consent_reference':reminder.consent_reference,'delivery_configured':False}

@app.get('/api/v1/stewardship/reminders')
def list_stewardship_reminders(limit:int=Query(default=50,ge=1,le=200), db:Session=Depends(get_db)):
    rows=db.scalars(select(StewardshipReminder).order_by(StewardshipReminder.scheduled_at).limit(limit)).all()
    return [{'id':reminder.id,'prescription_id':reminder.prescription_id,'prescription_code':f'AMR-RX-{reminder.prescription_id:06d}','scheduled_at':reminder.scheduled_at,'status':reminder.status,'consent_recorded':reminder.consent_recorded,'consent_reference':reminder.consent_reference} for reminder in rows]

def create_due_stewardship_review(prescription_id:int,dispensed_at:datetime,db:Session):
    existing=db.scalar(select(StewardshipReview).where(StewardshipReview.prescription_id==prescription_id,StewardshipReview.review_type=='POST_DISPENSE'))
    if existing: return existing
    review=StewardshipReview(prescription_id=prescription_id,review_type='POST_DISPENSE',status='PENDING',due_at=dispensed_at+timedelta(days=3))
    db.add(review); db.flush(); audit(db,'STEWARDSHIP_REVIEW_CREATED','Prescription',prescription_id,'AMRGuard',{'review_id':review.id,'due_at':review.due_at.isoformat()}); return review

@app.get('/api/v1/stewardship/reviews')
def list_stewardship_reviews(limit:int=Query(default=100,ge=1,le=500),status:str|None=None,db:Session=Depends(get_db),_auth:bool=Depends(require_funder_demo_ui_or_integration_key)):
    query=select(StewardshipReview).order_by(StewardshipReview.due_at).limit(limit)
    if status: query=query.where(StewardshipReview.status==status.upper())
    result=[]
    for review in db.scalars(query).all():
        rx=db.get(Prescription,review.prescription_id); tx=db.scalar(select(DispensingTransaction).where(DispensingTransaction.prescription_id==review.prescription_id).order_by(DispensingTransaction.created_at.desc()))
        result.append({'id':review.id,'prescription_id':review.prescription_id,'prescription_code':f'AMR-RX-{review.prescription_id:06d}','patient_reference':rx.patient_reference if rx else None,'facility_id':rx.facility_id if rx else None,'review_type':review.review_type,'status':review.status,'due_at':review.due_at,'outcome':review.outcome,'reason':review.reason,'reviewer_reference':review.reviewer_reference,'completed_at':review.completed_at,'last_transaction_id':tx.transaction_id if tx else None})
    return result

@app.post('/api/v1/stewardship/reviews/{review_id}/complete')
def complete_stewardship_review(review_id:int,request:StewardshipReviewRequest,db:Session=Depends(get_db),_auth:bool=Depends(require_funder_demo_ui_or_integration_key)):
    review=db.get(StewardshipReview,review_id)
    if not review: raise HTTPException(404,'Stewardship review not found')
    if review.status=='COMPLETED': raise HTTPException(409,'Stewardship review is already completed')
    review.status='COMPLETED'; review.outcome=request.outcome; review.reason=request.reason.strip(); review.reviewer_reference=request.reviewer_reference.strip(); review.completed_at=utcnow()
    audit(db,'STEWARDSHIP_REVIEW_COMPLETED','Prescription',review.prescription_id,request.reviewer_reference,{'review_id':review.id,'outcome':review.outcome,'reason':review.reason}); db.commit()
    return {'id':review.id,'prescription_id':review.prescription_id,'status':review.status,'outcome':review.outcome,'completed_at':review.completed_at}

@app.post('/api/v1/demo/prescriptions')
def create_demo_prescription(payload:DemoPrescriptionCreate, db:Session=Depends(get_db)):
    # Demo-only convenience endpoint. Production ingestion remains protected by the integration gate.
    if settings.app_env not in {'demo','test','development','funder_demo'}:
        raise HTTPException(404,'Demo prescription endpoint unavailable')
    if db.scalar(select(Prescription).where(Prescription.external_id==payload.external_id)):
        raise HTTPException(409,'External prescription ID already exists')
    fac=db.scalar(select(Facility).where(Facility.code=='FAC-KGL-001'))
    pr=db.scalar(select(Prescriber).where(Prescriber.external_user_id=='EBZ-USER-001'))
    ab=db.scalar(select(Antibiotic).where(Antibiotic.code==payload.antibiotic_code))
    if not fac or not pr or not ab: raise HTTPException(500,'Demo data is not initialized')
    rule=db.scalar(select(AntibioticRule).where(AntibioticRule.antibiotic_id==ab.id,AntibioticRule.enabled.is_(True)))
    rx=Prescription(external_id=payload.external_id,patient_reference=payload.patient_reference,prescriber_id=pr.id,facility_id=fac.id,expires_at=payload.expires_at)
    db.add(rx); db.flush()
    item=PrescriptionItem(prescription_id=rx.id,antibiotic_id=ab.id,dose=payload.dose,frequency_per_day=payload.frequency_per_day,duration_days=payload.duration_days,quantity=payload.quantity,indication=payload.indication)
    db.add(item); db.flush()
    issues=validate_item(item,rule)
    blocks=[i for i in issues if i['severity']=='BLOCK']
    rx.status='BLOCKED' if blocks else ('WARNING' if issues else 'VALIDATED')
    audit(db,'DEMO_PRESCRIPTION_CREATED','Prescription',rx.id,'e-Buzima Simulator',{'external_id':rx.external_id})
    db.commit()
    return {'prescription':prescription_detail(rx,db),'issues':issues}


@app.post('/api/v1/demo/risk-scenario')
def demo_risk_scenario(db:Session=Depends(get_db)):
    """Create a deliberately invalid demo prescription to demonstrate a dispensing-control block.

    This endpoint is for the pitch environment only and must not be exposed in production.
    """
    if settings.app_env not in {'demo','test','development','funder_demo'}:
        raise HTTPException(404,'Demo scenario unavailable')
    fac=db.scalar(select(Facility).where(Facility.code=='FAC-KGL-001'))
    pr=db.scalar(select(Prescriber).where(Prescriber.external_user_id=='EBZ-USER-001'))
    ab=db.scalar(select(Antibiotic).where(Antibiotic.code=='AMX500CAP'))
    if not fac or not pr or not ab:
        raise HTTPException(500,'Demo data is not initialized')
    external=f'EBZ-RISK-{uuid4().hex[:10].upper()}'
    rx=Prescription(external_id=external,patient_reference='PATIENT-DEMO-RISK',prescriber_id=pr.id,facility_id=fac.id)
    db.add(rx); db.flush()
    # Deliberately inconsistent unit quantity: 20 units for 3 administrations/day × 5 days.
    item=PrescriptionItem(prescription_id=rx.id,antibiotic_id=ab.id,dose=500,frequency_per_day=3,duration_days=5,quantity=20,indication='Demo risk scenario')
    db.add(item); db.flush()
    rule=db.scalar(select(AntibioticRule).where(AntibioticRule.antibiotic_id==ab.id,AntibioticRule.enabled.is_(True)))
    issues=validate_item(item,rule)
    rx.status='BLOCKED'
    audit(db,'DEMO_RISK_SCENARIO','Prescription',rx.id,'AMRGuard Demo',{'reason':'Intentional quantity mismatch','issues':issues})
    db.commit()
    return {'prescription':prescription_detail(rx,db),'issues':issues,'scenario':'intentional_block'}

@app.post('/api/v1/prescriptions/{prescription_id}/activate')
def activate_prescription(prescription_id:int, db:Session=Depends(get_db)):
    rx=db.get(Prescription,prescription_id)
    if not rx: raise HTTPException(404,'Prescription not found')
    if rx.status not in {'VALIDATED','WARNING'}: raise HTTPException(409,f'Prescription is {rx.status}')
    rx.status='ACTIVE'; audit(db,'PRESCRIPTION_ACTIVATED','Prescription',rx.id,'AMRGuard'); db.commit()
    return prescription_detail(rx,db)

@app.get('/api/v1/transactions')
def transactions(limit:int=Query(default=25,ge=1,le=100), db:Session=Depends(get_db)):
    rows=db.scalars(select(DispensingTransaction).order_by(DispensingTransaction.created_at.desc()).limit(limit)).all()
    result=[]
    for transaction in rows:
        prescription=db.get(Prescription,transaction.prescription_id)
        result.append({'transaction_id':transaction.transaction_id,'prescription_id':transaction.prescription_id,'prescription_code':f'AMR-RX-{transaction.prescription_id:06d}','external_id':prescription.external_id if prescription else None,'pharmacy_id':transaction.pharmacy_id,'batch_id':transaction.batch_id,'quantity':transaction.quantity,'status':transaction.status,'payment_reference':transaction.payment_reference,'created_at':transaction.created_at})
    return result

@app.get('/api/v1/pharmacies')
def pharmacies(db:Session=Depends(get_db)):
    return [{'id':p.id,'code':p.code,'name':p.name,'district':p.district,'active':p.active} for p in db.scalars(select(Pharmacy)).all()]

@app.get('/api/v1/pharmacies/{pharmacy_id}/stock')
def pharmacy_stock(pharmacy_id:int,db:Session=Depends(get_db)):
    if not db.get(Pharmacy,pharmacy_id): raise HTTPException(404,'Pharmacy not found')
    return [{'id':b.id,'antibiotic_id':b.antibiotic_id,'batch_number':b.batch_number,'expiry_date':b.expiry_date,'quantity_available':b.quantity_available} for b in db.scalars(select(StockBatch).where(StockBatch.pharmacy_id==pharmacy_id).order_by(StockBatch.expiry_date)).all()]

@app.post('/api/v1/prescriptions/{prescription_id}/dispense')
def dispense(prescription_id:int,request:DispenseRequest,db:Session=Depends(get_db)):
    if request.idempotency_key:
        prior=db.scalar(select(DispensingTransaction).where(DispensingTransaction.idempotency_key==request.idempotency_key))
        if prior:
            replay_item_id=request.item_id
            if replay_item_id is None:
                replay_prescription=db.get(Prescription,prescription_id)
                if replay_prescription and len(replay_prescription.items)==1: replay_item_id=replay_prescription.items[0].id
            if (prior.prescription_id,prior.pharmacy_id,prior.batch_id,prior.item_id,prior.quantity)!=(prescription_id,request.pharmacy_id,request.batch_id,replay_item_id,request.quantity):
                raise HTTPException(409,'Idempotency key was already used for a different dispensing request')
            return {'authorized':True,'replayed':True,'transaction_id':prior.transaction_id,'quantity_dispensed':prior.quantity,'remaining':None,'prescription_status':'COMPLETED' if prior.status=='COMPLETED' else prior.status}
    rx=db.scalar(select(Prescription).where(Prescription.id==prescription_id).with_for_update()); batch=db.scalar(select(StockBatch).where(StockBatch.id==request.batch_id).with_for_update())
    if not rx or not batch: raise HTTPException(404,'Prescription or batch not found')
    verify_credential(request.credential,db)
    pharmacy=db.get(Pharmacy,request.pharmacy_id)
    if not pharmacy or not pharmacy.active: raise HTTPException(403,'Pharmacy is not active')
    if batch.pharmacy_id!=request.pharmacy_id: raise HTTPException(403,'Batch does not belong to this pharmacy')
    if rx.status not in {'ACTIVE','PARTIALLY_DISPENSED'}: raise HTTPException(409,f'Prescription status is {rx.status}')
    if rx.expires_at and is_expired(rx.expires_at): rx.status='EXPIRED'; db.commit(); raise HTTPException(409,'Prescription has expired')
    if request.item_id is None:
        if len(rx.items)!=1: raise HTTPException(422,'item_id is required when a prescription contains multiple items')
        item=rx.items[0]
    else:
        item=next((prescription_item for prescription_item in rx.items if prescription_item.id==request.item_id),None)
        if not item: raise HTTPException(404,'Prescription item not found')
    if batch.antibiotic_id!=item.antibiotic_id: raise HTTPException(409,'Batch antibiotic does not match prescription')
    dispensed_by_item={prescription_item.id:(db.scalar(select(func.coalesce(func.sum(DispensingTransaction.quantity),0)).where(DispensingTransaction.prescription_id==rx.id,DispensingTransaction.item_id==prescription_item.id)) or 0) for prescription_item in rx.items}
    remaining=item.quantity-int(dispensed_by_item[item.id])
    if request.quantity>remaining: raise HTTPException(409,f'Quantity exceeds authorized remaining quantity ({remaining})')
    if request.quantity>batch.quantity_available: raise HTTPException(409,'Insufficient pharmacy stock')
    batch.quantity_available-=request.quantity
    txid=f'DT-{secrets.token_hex(6).upper()}'
    tx=DispensingTransaction(transaction_id=txid,idempotency_key=request.idempotency_key,prescription_id=rx.id,item_id=item.id,pharmacy_id=request.pharmacy_id,batch_id=batch.id,quantity=request.quantity,payment_reference=request.payment_reference); db.add(tx)
    db.add(StockEvent(batch_id=batch.id,event_type='DISPENSING',quantity=-request.quantity,reference_id=txid,source_system='AMRGuard',details=json.dumps({'prescription_id':rx.id,'pharmacy_id':request.pharmacy_id})))
    new_item_remaining=remaining-request.quantity; total_remaining=sum(prescription_item.quantity-int(dispensed_by_item[prescription_item.id]) for prescription_item in rx.items)-request.quantity; rx.status='COMPLETED' if total_remaining==0 else 'PARTIALLY_DISPENSED'; audit(db,'DISPENSED','Prescription',rx.id,'Pharmacy',{'transaction_id':txid,'batch_id':batch.id,'item_id':item.id,'quantity':request.quantity}); db.flush(); create_due_stewardship_review(rx.id,utcnow(),db); db.commit()
    return {'authorized':True,'replayed':False,'transaction_id':txid,'item_id':item.id,'quantity_dispensed':request.quantity,'remaining':new_item_remaining,'prescription_remaining':total_remaining,'prescription_status':rx.status}

@app.get('/api/v1/traceability/batches/{batch_id}')
def batch_trace(batch_id:int,db:Session=Depends(get_db)):
    b=db.get(StockBatch,batch_id)
    if not b: raise HTTPException(404,'Batch not found')
    p=db.get(Pharmacy,b.pharmacy_id); ab=db.get(Antibiotic,b.antibiotic_id)
    if not p or not ab: raise HTTPException(404,'Batch references an unknown pharmacy or antibiotic')
    events=db.scalars(select(StockEvent).where(StockEvent.batch_id==batch_id).order_by(StockEvent.created_at)).all()
    transactions=db.scalars(select(DispensingTransaction).where(DispensingTransaction.batch_id==batch_id).order_by(DispensingTransaction.created_at.desc())).all()
    linked=[]
    for transaction in transactions:
        prescription=db.get(Prescription,transaction.prescription_id)
        if prescription:
            linked.append({'transaction_id':transaction.transaction_id,'prescription_id':prescription.id,'prescription_code':f'AMR-RX-{prescription.id:06d}','external_id':prescription.external_id,'quantity':transaction.quantity,'status':transaction.status,'created_at':transaction.created_at})
    return {'batch':{'id':b.id,'batch_number':b.batch_number,'antibiotic':ab.generic_name,'antibiotic_code':ab.code,'strength':ab.strength,'expiry_date':b.expiry_date,'current_quantity':b.quantity_available,'pharmacy':p.name,'pharmacy_id':p.id,'source_reference':b.source_reference},'events':[{'type':e.event_type,'quantity':e.quantity,'reference':e.reference_id,'source':e.source_system,'details':json.loads(e.details or '{}'),'created_at':e.created_at} for e in events],'linked_transactions':linked}

@app.get('/api/v1/integrations/ebuzima/prescriptions/{prescription_id}/fhir')
def prescription_fhir(prescription_id:int,db:Session=Depends(get_db)):
    rx=db.get(Prescription,prescription_id)
    if not rx: raise HTTPException(404,'Prescription not found')
    return prescription_to_medication_request(rx,db)

@app.get('/api/v1/integrations/dispensing/{transaction_id}/fhir')
def dispensing_fhir(transaction_id:str,db:Session=Depends(get_db)):
    tx=db.scalar(select(DispensingTransaction).where(DispensingTransaction.transaction_id==transaction_id))
    if not tx: raise HTTPException(404,'Transaction not found')
    return dispensing_to_medication_dispense(tx,db)

@app.get('/api/v1/audit')
def audit_events(limit:int=Query(default=50,ge=1,le=200), db:Session=Depends(get_db)):
    rows=db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)).all()
    return [{'id':e.id,'event_type':e.event_type,'entity_type':e.entity_type,'entity_id':e.entity_id,'source_system':e.source_system,'details':json.loads(e.details or '{}'),'created_at':e.created_at} for e in rows]

@app.get('/api/v1/analytics/summary')
def analytics(db:Session=Depends(get_db),_auth:bool=Depends(require_funder_demo_ui_or_integration_key)):
    prescriptions=db.scalar(select(func.count()).select_from(Prescription)) or 0
    dispensed=db.scalar(select(func.count(func.distinct(DispensingTransaction.prescription_id)))) or 0
    total_reviews=db.scalar(select(func.count()).select_from(StewardshipReview)) or 0
    completed_reviews=db.scalar(select(func.count()).select_from(StewardshipReview).where(StewardshipReview.status=='COMPLETED')) or 0
    return {'prescriptions':prescriptions,'validated':db.scalar(select(func.count()).select_from(Prescription).where(Prescription.status.in_(['VALIDATED','ACTIVE','PARTIALLY_DISPENSED','COMPLETED']))) or 0,'blocked':db.scalar(select(func.count()).select_from(Prescription).where(Prescription.status=='BLOCKED')) or 0,'dispensing_transactions':db.scalar(select(func.count()).select_from(DispensingTransaction)) or 0,'units_dispensed':db.scalar(select(func.coalesce(func.sum(DispensingTransaction.quantity),0))) or 0,'active_batches':db.scalar(select(func.count()).select_from(StockBatch).where(StockBatch.quantity_available>0)) or 0,'connected_pharmacies':db.scalar(select(func.count()).select_from(Pharmacy).where(Pharmacy.active.is_(True))) or 0,'prescriptions_with_dispense':dispensed,'prescription_dispense_reconciliation_rate':round(dispensed/max(prescriptions,1)*100,1),'stewardship_reviews_total':total_reviews,'stewardship_reviews_completed':completed_reviews,'stewardship_review_completion_rate':round(completed_reviews/max(total_reviews,1)*100,1),'pending_stewardship_reviews':total_reviews-completed_reviews}

@app.get('/api/v1/analytics/facilities')
def facility_analytics(db:Session=Depends(get_db),_auth:bool=Depends(require_funder_demo_ui_or_integration_key)):
    result=[]
    for facility in db.scalars(select(Facility).where(Facility.active.is_(True)).order_by(Facility.name)).all():
        rx_ids=select(Prescription.id).where(Prescription.facility_id==facility.id)
        rx_count=db.scalar(select(func.count()).select_from(Prescription).where(Prescription.facility_id==facility.id)) or 0
        linked=db.scalar(select(func.count(func.distinct(DispensingTransaction.prescription_id))).where(DispensingTransaction.prescription_id.in_(rx_ids))) or 0
        review_ids=select(StewardshipReview.id).join(Prescription,Prescription.id==StewardshipReview.prescription_id).where(Prescription.facility_id==facility.id)
        review_total=db.scalar(select(func.count()).select_from(StewardshipReview).where(StewardshipReview.id.in_(review_ids))) or 0
        review_done=db.scalar(select(func.count()).select_from(StewardshipReview).where(StewardshipReview.id.in_(review_ids),StewardshipReview.status=='COMPLETED')) or 0
        result.append({'facility_code':facility.code,'facility_name':facility.name,'district':facility.district,'prescriptions':rx_count,'prescriptions_with_dispense':linked,'reconciliation_rate':round(linked/max(rx_count,1)*100,1),'stewardship_reviews':review_total,'reviews_completed':review_done,'review_completion_rate':round(review_done/max(review_total,1)*100,1)})
    return {'data_status':'operational pilot data','facilities':result}
