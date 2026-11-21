from __future__ import annotations

from dataclasses import dataclass
import math
from decimal import Decimal
from typing import Any


@dataclass
class RegimenCalculation:
    exact_units: Decimal
    recommended_dispense_units: int
    recommended_dispense_packs: int
    unit_label: str
    manual_review_required: bool = False
    notes: str = ''


def calculate_required_quantity(
    *,
    formulation: Any | None = None,
    dose_mg: float | Decimal | None = None,
    frequency_per_day: float | Decimal | int = 1,
    duration_days: int = 1,
    is_prn: bool = False,
    prn_max_doses_per_day: int | None = None,
    custom_pack_size: int | None = None,
) -> RegimenCalculation:
    """Calculate the required dispensing quantity based on formulation and clinical regimen parameters."""
    if formulation is None or getattr(formulation, 'active', None) is False:
        freq = Decimal(str(frequency_per_day))
        dur = Decimal(str(duration_days))
        units = freq * dur
        int_units = int(math.ceil(units))
        return RegimenCalculation(
            exact_units=units,
            recommended_dispense_units=int_units,
            recommended_dispense_packs=int_units,
            unit_label='unit',
        )

    dose_val = Decimal(str(dose_mg)) if dose_mg is not None else Decimal('1')
    freq_val = Decimal(str(prn_max_doses_per_day if is_prn and prn_max_doses_per_day else frequency_per_day))
    dur_val = Decimal(str(duration_days))
    strength_val = Decimal(str(formulation.strength_value)) if formulation.strength_value else Decimal('1')
    dose_form = (formulation.dose_form or '').lower()
    pack_size = custom_pack_size or int(getattr(formulation, 'units_per_pack', 1) or 1)

    if dose_form in {'tablet', 'capsule', 'cap', 'tab'}:
        units_per_admin = dose_val / strength_val
        total_units = units_per_admin * freq_val * dur_val
        int_units = int(math.ceil(total_units))
        packs = int(math.ceil(Decimal(int_units) / Decimal(pack_size))) if pack_size > 1 else int_units
        return RegimenCalculation(
            exact_units=total_units,
            recommended_dispense_units=int_units,
            recommended_dispense_packs=packs,
            unit_label=formulation.unit_of_measure or dose_form,
        )

    elif dose_form in {'syrup', 'suspension', 'liquid', 'oral_suspension'}:
        conc = formulation.liquid_concentration_mg_per_ml
        if conc and Decimal(str(conc)) > 0:
            dose_ml = dose_val / Decimal(str(conc))
            total_ml = dose_ml * freq_val * dur_val
            bottles = int(math.ceil(total_ml / Decimal(pack_size))) if pack_size > 1 else int(math.ceil(total_ml))
            return RegimenCalculation(
                exact_units=Decimal(f'{total_ml:.2f}'),
                recommended_dispense_units=int(math.ceil(total_ml)),
                recommended_dispense_packs=bottles,
                unit_label='mL',
            )
        else:
            return RegimenCalculation(
                exact_units=Decimal('0'),
                recommended_dispense_units=1,
                recommended_dispense_packs=1,
                unit_label='bottle',
                manual_review_required=True,
                notes='Liquid suspension regimen requires pharmacist volume conversion review (concentration unspecified).',
            )

    elif dose_form in {'injection', 'vial', 'ampoule', 'infusion'}:
        vials_per_admin = int(math.ceil(dose_val / strength_val))
        total_vials = vials_per_admin * int(freq_val) * int(dur_val)
        packs = int(math.ceil(Decimal(total_vials) / Decimal(pack_size))) if pack_size > 1 else total_vials
        return RegimenCalculation(
            exact_units=Decimal(str(total_vials)),
            recommended_dispense_units=total_vials,
            recommended_dispense_packs=packs,
            unit_label='vial',
        )

    else:
        units = freq_val * dur_val
        int_units = int(math.ceil(units))
        return RegimenCalculation(
            exact_units=units,
            recommended_dispense_units=int_units,
            recommended_dispense_packs=int_units,
            unit_label=formulation.unit_of_measure or 'unit',
        )


def validate_item(item: Any, rule: Any = None, formulation: Any = None) -> list[dict[str, str]]:
    """Validate an antibiotic regimen using formulation-aware conversion rules and clinical boundaries.

    Formulation-aware regimen model (P1-03):
    - Solid oral (tablets, capsules): handles dose / strength = units per administration,
      divisible vs non-divisible tablet checks, and unit-dose vs pack-size conversions.
    - Liquid oral / suspensions (syrups, suspensions): calculates volume from mg/mL concentration
      and rounds to bottle pack sizes where applicable.
    - Injectables / Parenteral (vials, ampoules): handles vial rounding.
    - PRN (as-needed) orders: skips rigid frequency × duration multiplication and guards against
      maximum daily dosing thresholds.
    - Complex/Ambiguous orders: flags for MANUAL_REVIEW instead of generating mathematical errors.
    """
    issues: list[dict[str, str]] = []

    # Resolve formulation if available on item or passed explicitly
    form = formulation or getattr(item, 'formulation', None)
    is_prn = bool(getattr(item, 'is_prn', False))

    if is_prn:
        # PRN orders are taken as needed: do not expect exact frequency * duration units.
        # Guard against excessive quantity if a clinical rule specifies max daily frequency.
        if rule and rule.enabled and getattr(rule, 'frequency_per_day_max', None) is not None:
            max_daily_dose = Decimal(rule.frequency_per_day_max) * Decimal(item.dose)
            duration_days = Decimal(getattr(item, 'duration_days', 1))
            # Rough safety ceiling for PRN supply
            max_recommended_quantity = int(math.ceil(Decimal(rule.frequency_per_day_max) * duration_days))
            if int(item.quantity) > max_recommended_quantity * 2:
                issues.append({
                    'code': 'PRN_QUANTITY_EXCESSIVE',
                    'severity': 'WARNING',
                    'message': f'Prescribed PRN quantity {item.quantity} exceeds twice the maximum anticipated need ({max_recommended_quantity}).',
                })
    elif form is not None and getattr(form, 'active', None) is not False:
        dose_val = Decimal(str(item.dose))
        freq_val = Decimal(str(item.frequency_per_day))
        dur_val = Decimal(str(item.duration_days))
        strength_val = Decimal(str(form.strength_value)) if form.strength_value else Decimal('1')
        dose_form = (form.dose_form or '').lower()
        pack_size = int(getattr(form, 'units_per_pack', 1) or 1)

        if dose_form in {'tablet', 'capsule', 'cap', 'tab'}:
            units_per_admin = dose_val / strength_val
            # Check divisibility
            is_divisible = bool(getattr(form, 'is_divisible', False))
            if not is_divisible and units_per_admin != int(units_per_admin):
                issues.append({
                    'code': 'INDIVISIBLE_FORMULATION',
                    'severity': 'BLOCK',
                    'message': f'Prescribed dose {item.dose} requires {units_per_admin:.2f} units of a non-divisible formulation ({form.dose_form}).',
                })

            total_units = units_per_admin * freq_val * dur_val
            int_units = int(math.ceil(total_units))
            packs = int(math.ceil(Decimal(int_units) / Decimal(pack_size))) if pack_size > 1 else int_units

            # Prescribed quantity matches either exact units or pack count
            if int(item.quantity) not in {int_units, packs}:
                expected_str = f"{int_units} units" if pack_size == 1 else f"{int_units} units ({packs} pack{'s' if packs != 1 else ''})"
                issues.append({
                    'code': 'QUANTITY_MISMATCH',
                    'severity': 'BLOCK',
                    'message': f'Quantity {item.quantity} does not match regimen expectation: {expected_str}.',
                })

        elif dose_form in {'syrup', 'suspension', 'liquid', 'oral_suspension'}:
            conc = form.liquid_concentration_mg_per_ml
            if conc and Decimal(str(conc)) > 0:
                dose_ml = dose_val / Decimal(str(conc))
                total_ml = dose_ml * freq_val * dur_val
                bottles = int(math.ceil(total_ml / Decimal(pack_size))) if pack_size > 1 else int(math.ceil(total_ml))
                if int(item.quantity) not in {int(math.ceil(total_ml)), bottles}:
                    issues.append({
                        'code': 'QUANTITY_MISMATCH',
                        'severity': 'BLOCK',
                        'message': f'Quantity {item.quantity} does not match liquid volume requirement: {total_ml:.1f} mL ({bottles} bottle(s)).',
                    })
            else:
                # Ambiguous liquid volume without concentration: route to manual review
                issues.append({
                    'code': 'MANUAL_REVIEW_REQUIRED',
                    'severity': 'WARNING',
                    'message': 'Liquid suspension regimen requires pharmacist volume conversion review (concentration unspecified).',
                })

        elif dose_form in {'injection', 'vial', 'ampoule', 'infusion'}:
            vials_per_admin = int(math.ceil(dose_val / strength_val))
            total_vials = vials_per_admin * int(freq_val) * int(dur_val)
            packs = int(math.ceil(Decimal(total_vials) / Decimal(pack_size))) if pack_size > 1 else total_vials
            if int(item.quantity) not in {total_vials, packs}:
                issues.append({
                    'code': 'QUANTITY_MISMATCH',
                    'severity': 'BLOCK',
                    'message': f'Quantity {item.quantity} does not match injectable supply requirement: {total_vials} vial(s).',
                })
        else:
            # Other forms: standard unit-dose check
            expected_units = freq_val * dur_val
            if int(item.quantity) != int(expected_units):
                issues.append({
                    'code': 'QUANTITY_MISMATCH',
                    'severity': 'BLOCK',
                    'message': f'Quantity {item.quantity} does not match frequency × duration ({expected_units}).',
                })
    else:
        # Fallback for unlinked MVP unit-dose items
        expected_units = Decimal(str(item.frequency_per_day)) * Decimal(str(item.duration_days))
        if expected_units != int(expected_units) or int(item.quantity) != int(expected_units):
            issues.append({
                'code': 'QUANTITY_MISMATCH',
                'severity': 'BLOCK',
                'message': f'Quantity {item.quantity} does not match frequency × duration for unit-dose dispensing ({expected_units}).',
            })

    # Clinical guideline boundary checks
    if rule and getattr(rule, 'enabled', True):
        checks = [
            ('DOSE_BELOW_RULE', item.dose, rule.min_dose, 'Dose is below the configured clinical rule.', 'BLOCK'),
            ('DOSE_ABOVE_RULE', item.dose, rule.max_dose, 'Dose is above the configured clinical rule.', 'BLOCK'),
            ('DURATION_BELOW_RULE', item.duration_days, rule.min_duration_days, 'Duration is below the configured clinical rule.', 'WARNING'),
            ('DURATION_ABOVE_RULE', item.duration_days, rule.max_duration_days, 'Duration is above the configured clinical rule.', 'WARNING'),
            ('FREQUENCY_BELOW_RULE', item.frequency_per_day, rule.frequency_per_day_min, 'Frequency is below the configured clinical rule.', 'WARNING'),
            ('FREQUENCY_ABOVE_RULE', item.frequency_per_day, rule.frequency_per_day_max, 'Frequency is above the configured clinical rule.', 'WARNING'),
        ]
        for code, value, bound, msg, severity in checks:
            if bound is not None and ((code.endswith('BELOW_RULE') and Decimal(str(value)) < Decimal(str(bound))) or (code.endswith('ABOVE_RULE') and Decimal(str(value)) > Decimal(str(bound)))):
                issues.append({'code': code, 'severity': severity, 'message': msg})

    return issues
