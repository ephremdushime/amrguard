from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import select
from app.models.core import Facility, Pharmacy, Prescriber, Antibiotic, AntibioticRule, StockBatch


def seed_demo(db):
    fac=db.scalar(select(Facility).where(Facility.code=='FAC-KGL-001'))
    if not fac:
        fac=Facility(code='FAC-KGL-001',name='AMRGuard Demo Hospital',district='Gasabo'); db.add(fac); db.flush()
    pharmacy=db.scalar(select(Pharmacy).where(Pharmacy.code=='PHA-KGL-001'))
    if not pharmacy:
        pharmacy=Pharmacy(code='PHA-KGL-001',name='AMRGuard Demo Pharmacy',district='Gasabo'); db.add(pharmacy); db.flush()
    prescriber=db.scalar(select(Prescriber).where(Prescriber.external_user_id=='EBZ-USER-001'))
    if not prescriber:
        prescriber=Prescriber(external_user_id='EBZ-USER-001',name='Demo Prescriber',facility_id=fac.id); db.add(prescriber); db.flush()
    antibiotic=db.scalar(select(Antibiotic).where(Antibiotic.code=='AMX500CAP'))
    if not antibiotic:
        antibiotic=Antibiotic(code='AMX500CAP',generic_name='Amoxicillin',strength='500 mg',formulation='Capsule',route='Oral'); db.add(antibiotic); db.flush()
    rule=db.scalar(select(AntibioticRule).where(AntibioticRule.antibiotic_id==antibiotic.id,AntibioticRule.source_reference.like('DEMO RULE%')))
    if not rule:
        db.add(AntibioticRule(antibiotic_id=antibiotic.id,min_dose=Decimal('250'),max_dose=Decimal('1000'),min_duration_days=3,max_duration_days=14,frequency_per_day_min=Decimal('2'),frequency_per_day_max=Decimal('4'),source_reference='DEMO RULE - illustrative only; replace with approved local clinical guidance'))
    batch=db.scalar(select(StockBatch).where(StockBatch.pharmacy_id==pharmacy.id,StockBatch.antibiotic_id==antibiotic.id,StockBatch.batch_number=='AMX-2026-0042'))
    if not batch:
        db.add(StockBatch(pharmacy_id=pharmacy.id,antibiotic_id=antibiotic.id,batch_number='AMX-2026-0042',expiry_date=date.today()+timedelta(days=600),quantity_available=120,source_reference='SYNTHETIC FUNDER DEMO'))
    db.commit()
