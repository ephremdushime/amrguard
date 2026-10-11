import os
os.environ['DATABASE_URL']='sqlite:///./test_amrguard.db'
os.environ['APP_ENV']='test'
os.environ['INTEGRATION_API_KEY']=''
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.db.session import Base,engine

Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
from app.db.session import SessionLocal
from app.db.seed import seed_demo
_db=SessionLocal(); seed_demo(_db); _db.close()
client=TestClient(app)

PAYLOAD={'external_id':'EBZ-RX-TEST-001','patient_reference':'PAT-DEMO-001','prescriber':{'external_user_id':'EBZ-TEST-001','name':'Test Prescriber','facility_code':'FAC-TEST','facility_name':'Test Facility','district':'Gasabo'},'items':[{'antibiotic_code':'AMX500CAP','generic_name':'Amoxicillin','strength':'500 mg','formulation':'Capsule','route':'Oral','dose':500,'frequency_per_day':3,'duration_days':5,'quantity':15,'indication':'Bacterial infection'}]}

def test_health():
    r=client.get('/health'); assert r.status_code==200; assert r.json()['version']=='0.7.0'

def test_end_to_end_and_replay_protection():
    r=client.post('/api/v1/integrations/ebuzima/prescriptions',json=PAYLOAD); assert r.status_code==200; rx=r.json(); assert rx['status']=='VALIDATED'
    c=client.post(f"/api/v1/prescriptions/{rx['id']}/credential"); assert c.status_code==200; cred=c.json()
    v=client.post('/api/v1/verification',json={'credential':cred['otp']}); assert v.status_code==200
    pharmacies=client.get('/api/v1/pharmacies').json(); stock=client.get(f"/api/v1/pharmacies/{pharmacies[0]['id']}/stock").json(); batch=stock[0]
    bad=client.post(f"/api/v1/prescriptions/{rx['id']}/dispense",json={'pharmacy_id':pharmacies[0]['id'],'batch_id':batch['id'],'quantity':20,'credential':cred['otp'],'idempotency_key':'idem-test-001'}); assert bad.status_code==409
    good=client.post(f"/api/v1/prescriptions/{rx['id']}/dispense",json={'pharmacy_id':pharmacies[0]['id'],'batch_id':batch['id'],'quantity':15,'credential':cred['otp'],'idempotency_key':'idem-test-001'}); assert good.status_code==200; assert good.json()['prescription_status']=='COMPLETED'
    replay=client.post(f"/api/v1/prescriptions/{rx['id']}/dispense",json={'pharmacy_id':pharmacies[0]['id'],'batch_id':batch['id'],'quantity':15,'credential':cred['otp'],'idempotency_key':'idem-test-001'}); assert replay.status_code==200; assert replay.json()['replayed'] is True


def test_multi_item_prescription_requires_and_dispenses_items_independently():
    multi={**PAYLOAD,'external_id':'EBZ-RX-MULTI-ITEM','items':[
        {**PAYLOAD['items'][0],'quantity':15},
        {**PAYLOAD['items'][0],'dose':250,'frequency_per_day':1,'duration_days':3,'quantity':3,'indication':'Second item'}
    ]}
    response=client.post('/api/v1/integrations/ebuzima/prescriptions',json=multi)
    assert response.status_code==200
    prescription_id=response.json()['id']
    detail=client.get(f'/api/v1/prescriptions/{prescription_id}').json()
    first_item,second_item=detail['items']
    credential=client.post(f'/api/v1/prescriptions/{prescription_id}/credential').json()
    pharmacies=client.get('/api/v1/pharmacies').json(); batch=client.get(f"/api/v1/pharmacies/{pharmacies[0]['id']}/stock").json()[0]
    missing_item=client.post(f'/api/v1/prescriptions/{prescription_id}/dispense',json={
        'pharmacy_id':pharmacies[0]['id'],'batch_id':batch['id'],'quantity':1,'credential':credential['otp'],'idempotency_key':'idem-multi-missing'
    })
    assert missing_item.status_code==422
    first=client.post(f'/api/v1/prescriptions/{prescription_id}/dispense',json={
        'pharmacy_id':pharmacies[0]['id'],'batch_id':batch['id'],'item_id':first_item['id'],'quantity':15,'credential':credential['otp'],'idempotency_key':'idem-multi-first'
    })
    assert first.status_code==200 and first.json()['prescription_status']=='PARTIALLY_DISPENSED'
    second=client.post(f'/api/v1/prescriptions/{prescription_id}/dispense',json={
        'pharmacy_id':pharmacies[0]['id'],'batch_id':batch['id'],'item_id':second_item['id'],'quantity':3,'credential':credential['otp'],'idempotency_key':'idem-multi-second'
    })
    assert second.status_code==200 and second.json()['prescription_status']=='COMPLETED'
    mismatch=client.post(f'/api/v1/prescriptions/{prescription_id}/dispense',json={
        'pharmacy_id':pharmacies[0]['id'],'batch_id':batch['id'],'item_id':first_item['id'],'quantity':14,'credential':credential['otp'],'idempotency_key':'idem-multi-first'
    })
    assert mismatch.status_code==409

def test_duplicate_external_prescription_is_idempotent():
    r1=client.post('/api/v1/integrations/ebuzima/prescriptions',json={**PAYLOAD,'external_id':'EBZ-RX-IDEMPOTENT'}); assert r1.status_code==200
    r2=client.post('/api/v1/integrations/ebuzima/prescriptions',json={**PAYLOAD,'external_id':'EBZ-RX-IDEMPOTENT'}); assert r2.status_code==200; assert r2.json()['id']==r1.json()['id']


def test_demo_prescription_accepts_order_fields_and_expiry():
    from datetime import datetime, timedelta, timezone
    expires_at=(datetime.now(timezone.utc)+timedelta(hours=36)).isoformat()
    response=client.post('/api/v1/demo/prescriptions',json={
        'external_id':'EBZ-RX-ORDER-FIELDS',
        'patient_reference':'PATIENT-ORDER-001',
        'antibiotic_code':'AMX500CAP',
        'dose':250,
        'frequency_per_day':2,
        'duration_days':4,
        'quantity':8,
        'indication':'Order form regression',
        'expires_at':expires_at
    })
    assert response.status_code==200
    order=response.json()['prescription']
    assert order['patient_reference']=='PATIENT-ORDER-001'
    assert order['items'][0]['dose']=='250.000'
    assert order['items'][0]['frequency_per_day']=='2.00'
    assert order['items'][0]['authorized_quantity']==8
    stored_expiry=datetime.fromisoformat(order['expires_at']).replace(tzinfo=timezone.utc)
    assert stored_expiry==datetime.fromisoformat(expires_at)


def test_demo_prescription_rejects_expired_or_excessive_lifetime():
    from datetime import datetime, timedelta, timezone
    base={'external_id':'EBZ-RX-BAD-LIFETIME','patient_reference':'PATIENT-ORDER-002'}
    expired=client.post('/api/v1/demo/prescriptions',json={**base,'expires_at':(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()})
    assert expired.status_code==422
    excessive=client.post('/api/v1/demo/prescriptions',json={**base,'external_id':'EBZ-RX-EXCESS-LIFETIME','expires_at':(datetime.now(timezone.utc)+timedelta(days=31)).isoformat()})
    assert excessive.status_code==422


def test_batch_catalog_and_traceability_are_available_without_ui_state():
    batches=client.get('/api/v1/stock/batches')
    assert batches.status_code==200 and batches.json()
    batch=batches.json()[0]
    trace=client.get(f"/api/v1/traceability/batches/{batch['id']}")
    assert trace.status_code==200
    assert trace.json()['batch']['batch_number']==batch['batch_number']
    assert 'events' in trace.json() and 'linked_transactions' in trace.json()


def test_rms_stock_events_are_idempotent_and_traceable():
    event={
        'source_system':'RMS','source_reference':'RMS-EVENT-TEST-001',
        'pharmacy_code':'PHA-INT-TEST','pharmacy_name':'Integration Test Pharmacy','district':'Gasabo',
        'antibiotic_code':'AMX-INT-TEST','generic_name':'Amoxicillin','strength':'250 mg',
        'formulation':'Capsule','route':'Oral','batch_number':'RMS-BATCH-TEST-001',
        'expiry_date':'2028-12-31','event_type':'RECEIPT','quantity_delta':40
    }
    url='/api/v1/integrations/rms/stock-events'
    first=client.post(url,json=event)
    assert first.status_code==200 and first.json()['quantity_available']==40
    replay=client.post(url,json=event)
    assert replay.status_code==200 and replay.json()['replayed'] is True
    conflict=client.post(url,json={**event,'quantity_delta':45})
    assert conflict.status_code==409
    adjustment=client.post(url,json={**event,'source_reference':'RMS-EVENT-TEST-002','event_type':'ADJUSTMENT','quantity_delta':-5})
    assert adjustment.status_code==200 and adjustment.json()['quantity_available']==35
    overdraw=client.post(url,json={**event,'source_reference':'RMS-EVENT-TEST-003','event_type':'ADJUSTMENT','quantity_delta':-50})
    assert overdraw.status_code==409
    trace=client.get(f"/api/v1/traceability/batches/{first.json()['batch_id']}")
    assert trace.status_code==200 and len(trace.json()['events'])==2


def test_stewardship_reminder_requires_consent_and_is_provider_pending():
    created=client.post('/api/v1/demo/prescriptions',json={
        'external_id':'EBZ-RX-REMINDER-001','patient_reference':'PATIENT-REMINDER-001',
        'duration_days':5,'quantity':15
    })
    assert created.status_code==200
    prescription_id=created.json()['prescription']['id']
    base=f'/api/v1/prescriptions/{prescription_id}/stewardship-reminder'
    denied=client.post(base,json={'consent':False,'consent_reference':'CONSENT-001'})
    assert denied.status_code==422
    premature=client.post(base,json={'consent':True,'consent_reference':'CONSENT-001'})
    assert premature.status_code==409
    credential=client.post(f'/api/v1/prescriptions/{prescription_id}/credential')
    assert credential.status_code==200
    pharmacies=client.get('/api/v1/pharmacies').json()
    batches=client.get(f"/api/v1/pharmacies/{pharmacies[0]['id']}/stock").json()
    dispensed=client.post(f'/api/v1/prescriptions/{prescription_id}/dispense',json={
        'pharmacy_id':pharmacies[0]['id'],'batch_id':batches[0]['id'],'quantity':15,
        'credential':credential.json()['otp'],'idempotency_key':'idem-reminder-001'
    })
    assert dispensed.status_code==200
    scheduled=client.post(base,json={'consent':True,'consent_reference':'CONSENT-001'})
    assert scheduled.status_code==200
    assert scheduled.json()['status']=='PENDING_PROVIDER'
    assert scheduled.json()['consent_recorded'] is True
    assert scheduled.json()['delivery_configured'] is False
    assert scheduled.json()['consent_reference']=='CONSENT-001'
    assert 'phone_number' not in client.get('/api/v1/stewardship/reminders').json()[0]
    duplicate=client.post(base,json={'consent':True,'consent_reference':'CONSENT-001'})
    assert duplicate.status_code==409


def test_stewardship_reminder_requires_consent_reference():
    response=client.post('/api/v1/prescriptions/1/stewardship-reminder',json={'consent':True,'consent_reference':'x'})
    assert response.status_code==422


def test_otp_verification_route_works():
    r=client.post('/api/v1/integrations/ebuzima/prescriptions',json={**PAYLOAD,'external_id':'EBZ-RX-OTP-ROUTE'}); assert r.status_code==200; rx=r.json()
    c=client.post(f"/api/v1/prescriptions/{rx['id']}/credential"); assert c.status_code==200; otp=c.json()['otp']
    v=client.post('/api/v1/verification/otp',params={'otp':otp}); assert v.status_code==200; assert v.json()['verified'] is True


def test_reissuing_credential_replaces_previous_credential():
    r=client.post('/api/v1/integrations/ebuzima/prescriptions',json={**PAYLOAD,'external_id':'EBZ-RX-CREDENTIAL-REISSUE'}); assert r.status_code==200; rx=r.json()
    first=client.post(f"/api/v1/prescriptions/{rx['id']}/credential"); assert first.status_code==200
    second=client.post(f"/api/v1/prescriptions/{rx['id']}/credential"); assert second.status_code==200
    assert client.post('/api/v1/verification/otp',params={'otp':first.json()['otp']}).status_code==401
    verified=client.post('/api/v1/verification/otp',params={'otp':second.json()['otp']})
    assert verified.status_code==200; assert verified.json()['verified'] is True


def test_risk_scenario_blocks_intentional_quantity_mismatch():
    r=client.post('/api/v1/demo/risk-scenario'); assert r.status_code==200
    data=r.json(); assert data['scenario']=='intentional_block'; assert data['prescription']['status']=='BLOCKED'
    assert any(x['code']=='QUANTITY_MISMATCH' and x['severity']=='BLOCK' for x in data['issues'])


def test_demo_prescription_endpoint_is_disabled_in_production(monkeypatch):
    monkeypatch.setattr(settings,'app_env','production')
    response=client.post('/api/v1/demo/prescriptions',json={
        'external_id':'EBZ-RX-PRODUCTION-DEMO-BLOCK',
        'patient_reference':'PAT-PRODUCTION-DEMO-BLOCK',
        'antibiotic_code':'AMX500CAP',
        'dose':500,
        'frequency_per_day':3,
        'duration_days':5,
        'quantity':15,
        'indication':'Test only'
    })
    assert response.status_code==404
