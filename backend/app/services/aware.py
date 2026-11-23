"""WHO AWaRe (Access, Watch, Reserve) Classification & Stewardship Service.

Implements authoritative classification according to the WHO Model List of Essential Medicines
and WHO AWaRe antibiotic book guidance. Tracks national utilization against the global target:
>= 60% of total antibiotic consumption from the Access group.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import Antibiotic, AntibioticRule, DispensingTransaction, PrescriptionItem, WhoAwareClassification

AwareCategory = Literal['ACCESS', 'WATCH', 'RESERVE', 'DISCOURAGED']

# Baseline canonical WHO AWaRe classifications for core formulary items
BASELINE_AWARE_CLASSIFICATIONS: list[dict] = [
    # ACCESS Group
    {
        'antibiotic_code': 'AMX500CAP',
        'generic_name': 'Amoxicillin',
        'category': 'ACCESS',
        'atc_code': 'J01CA04',
        'clinical_notes': 'First-choice agent for community-acquired respiratory tract infections.',
    },
    {
        'antibiotic_code': 'AMP500CAP',
        'generic_name': 'Ampicillin',
        'category': 'ACCESS',
        'atc_code': 'J01CA01',
        'clinical_notes': 'Narrow-spectrum aminopenicillin for susceptible gram-positive and gram-negative infections.',
    },
    {
        'antibiotic_code': 'DOX100TAB',
        'generic_name': 'Doxycycline',
        'category': 'ACCESS',
        'atc_code': 'J01AA02',
        'clinical_notes': 'Tetracycline class; first-line oral option for atypical pathogens and vector-borne infections.',
    },
    {
        'antibiotic_code': 'GEN80INJ',
        'generic_name': 'Gentamicin',
        'category': 'ACCESS',
        'atc_code': 'J01GB03',
        'clinical_notes': 'Aminoglycoside for serious neonatal and systemic gram-negative infections.',
    },
    {
        'antibiotic_code': 'MET500TAB',
        'generic_name': 'Metronidazole',
        'category': 'ACCESS',
        'atc_code': 'J01XD01',
        'clinical_notes': 'First-line antimicrobial for anaerobic infections and protozoal conditions.',
    },
    {
        'antibiotic_code': 'CTX480TAB',
        'generic_name': 'Co-trimoxazole',
        'category': 'ACCESS',
        'atc_code': 'J01EE01',
        'clinical_notes': 'Sulfonamide/trimethoprim combination for prophylaxis and uncomplicated infections.',
    },
    # WATCH Group
    {
        'antibiotic_code': 'CIP500TAB',
        'generic_name': 'Ciprofloxacin',
        'category': 'WATCH',
        'atc_code': 'J01MA02',
        'clinical_notes': 'Fluoroquinolone; high resistance risk; restrict for severe pyelonephritis and enteric fever.',
    },
    {
        'antibiotic_code': 'CRO1GINJ',
        'generic_name': 'Ceftriaxone',
        'category': 'WATCH',
        'atc_code': 'J01DD04',
        'clinical_notes': 'Third-generation cephalosporin; high selection pressure for ESBL-producing enterobacterales.',
    },
    {
        'antibiotic_code': 'AZM500TAB',
        'generic_name': 'Azithromycin',
        'category': 'WATCH',
        'atc_code': 'J01FA10',
        'clinical_notes': 'Macrolide; monitor closely for over-prescription in mild community upper-respiratory infections.',
    },
    # RESERVE Group
    {
        'antibiotic_code': 'COL1MINJ',
        'generic_name': 'Colistin',
        'category': 'RESERVE',
        'atc_code': 'J01XB01',
        'clinical_notes': 'Last-resort polymyxin for carbapenem-resistant gram-negative pathogens.',
    },
    {
        'antibiotic_code': 'LNZ600TAB',
        'generic_name': 'Linezolid',
        'category': 'RESERVE',
        'atc_code': 'J01XX08',
        'clinical_notes': 'Oxazolidinone reserved for documented MRSA and VRE with specialist consultation.',
    },
    {
        'antibiotic_code': 'MEM1GINJ',
        'generic_name': 'Meropenem',
        'category': 'RESERVE',
        'atc_code': 'J01DH02',
        'clinical_notes': 'Carbapenem reserved for documented severe multi-drug resistant nosocomial sepsis.',
    },
]


def seed_who_aware_classifications(db: Session) -> int:
    """Populates baseline WHO AWaRe classification reference entries and formulary items if absent."""
    seeded = 0
    today = date(2023, 1, 1)
    for entry in BASELINE_AWARE_CLASSIFICATIONS:
        code = entry['antibiotic_code']
        existing = db.scalar(
            select(WhoAwareClassification).where(
                WhoAwareClassification.antibiotic_code == code
            )
        )
        if not existing:
            db.add(
                WhoAwareClassification(
                    antibiotic_code=code,
                    generic_name=entry['generic_name'],
                    category=entry['category'],
                    atc_code=entry.get('atc_code'),
                    clinical_notes=entry.get('clinical_notes'),
                    effective_date=today,
                    version='WHO_2023_V1',
                )
            )
            seeded += 1

        # Also ensure the corresponding formulary Antibiotic and clinical rule exist
        ab = db.scalar(select(Antibiotic).where(Antibiotic.code == code))
        if not ab:
            formulation = 'Tablet' if 'TAB' in code else ('Capsule' if 'CAP' in code else 'Injection')
            route = 'Oral' if formulation in ('Tablet', 'Capsule') else 'Intravenous'
            strength = '500 mg'
            if '100' in code:
                strength = '100 mg'
            elif '80' in code:
                strength = '80 mg'
            elif '1G' in code:
                strength = '1 g'
            elif '1M' in code:
                strength = '1 MIU'
            elif '600' in code:
                strength = '600 mg'
            elif '480' in code:
                strength = '480 mg'

            ab = Antibiotic(
                code=code,
                generic_name=entry['generic_name'],
                strength=strength,
                formulation=formulation,
                route=route,
            )
            db.add(ab)
            db.flush()

        rule = db.scalar(select(AntibioticRule).where(AntibioticRule.antibiotic_id == ab.id))
        if not rule:
            db.add(
                AntibioticRule(
                    antibiotic_id=ab.id,
                    min_dose=Decimal('100'),
                    max_dose=Decimal('2000'),
                    min_duration_days=1,
                    max_duration_days=21,
                    frequency_per_day_min=Decimal('1'),
                    frequency_per_day_max=Decimal('4'),
                    source_reference=f'WHO AWaRe Baseline ({entry["category"]})',
                )
            )

    if seeded > 0:
        db.commit()
    return seeded


def get_aware_classification(db: Session, antibiotic_code: str) -> WhoAwareClassification | None:
    """Retrieves the authoritative AWaRe classification for a code."""
    return db.scalar(
        select(WhoAwareClassification).where(
            WhoAwareClassification.antibiotic_code == antibiotic_code
        )
    )


def classify_antibiotic(db: Session, antibiotic_code: str) -> str:
    """Returns the AWaRe category string (ACCESS, WATCH, RESERVE, DISCOURAGED) or defaults to ACCESS."""
    rec = get_aware_classification(db, antibiotic_code)
    if rec:
        return rec.category
    # Fallback heuristic based on generic catalogue if unclassified
    ab = db.scalar(select(Antibiotic).where(Antibiotic.code == antibiotic_code))
    if ab:
        name_lower = ab.generic_name.lower()
        if any(w in name_lower for w in ('ciprofloxacin', 'ceftriaxone', 'cefotaxime', 'azithromycin', 'levofloxacin')):
            return 'WATCH'
        if any(r in name_lower for r in ('colistin', 'linezolid', 'meropenem', 'polymyxin', 'vancomycin')):
            return 'RESERVE'
    return 'ACCESS'


def calculate_aware_breakdown(
    db: Session,
    facility_id: int | None = None,
    minimum_cell_threshold: int = 5,
) -> dict:
    """Calculates prescription AWaRe category breakdown and benchmarks."""
    # Query prescription items joined with antibiotics
    query = (
        select(
            Antibiotic.code,
            func.count(PrescriptionItem.id).label('item_count'),
            func.sum(PrescriptionItem.quantity).label('total_units'),
        )
        .select_from(PrescriptionItem)
        .join(Antibiotic, PrescriptionItem.antibiotic_id == Antibiotic.id)
    )

    if facility_id:
        from app.models.core import Prescription
        query = query.join(Prescription, PrescriptionItem.prescription_id == Prescription.id).where(
            Prescription.facility_id == facility_id
        )

    rows = db.execute(query.group_by(Antibiotic.code)).all()

    counts = {'ACCESS': 0, 'WATCH': 0, 'RESERVE': 0, 'DISCOURAGED': 0}
    units = {'ACCESS': 0, 'WATCH': 0, 'RESERVE': 0, 'DISCOURAGED': 0}

    for code, item_cnt, unit_cnt in rows:
        cat = classify_antibiotic(db, code)
        if cat in counts:
            counts[cat] += int(item_cnt or 0)
            units[cat] += int(unit_cnt or 0)

    total_prescriptions = sum(counts.values())
    total_units = sum(units.values())

    access_pct = round((counts['ACCESS'] / max(total_prescriptions, 1)) * 100, 1)
    watch_pct = round((counts['WATCH'] / max(total_prescriptions, 1)) * 100, 1)
    reserve_pct = round((counts['RESERVE'] / max(total_prescriptions, 1)) * 100, 1)

    # Privacy / cell suppression check
    suppressed = False
    for cat in ('WATCH', 'RESERVE', 'DISCOURAGED'):
        if 0 < counts[cat] < minimum_cell_threshold:
            suppressed = True

    return {
        'total_orders': total_prescriptions,
        'total_units': total_units,
        'access_count': counts['ACCESS'],
        'watch_count': counts['WATCH'],
        'reserve_count': counts['RESERVE'],
        'access_percentage': access_pct,
        'watch_percentage': watch_pct,
        'reserve_percentage': reserve_pct,
        'meets_who_access_target': access_pct >= 60.0,
        'who_benchmark': '>= 60% of total consumption from Access group',
        'cell_suppression_applied': suppressed,
    }
