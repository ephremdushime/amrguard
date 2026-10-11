from decimal import Decimal

def validate_item(item, rule):
    """Validate an antibiotic regimen using configurable rules.

    Quantity is calculated as administrations/day × duration × units per administration.
    The current MVP assumes one dispensed unit per administration for solid unit-dose
    forms (e.g. tablets/capsules). Liquid/pack-size conversion belongs in the product
    catalog before production deployment.
    """
    issues=[]
    expected_units=Decimal(item.frequency_per_day)*Decimal(item.duration_days)
    if expected_units != int(expected_units) or item.quantity != int(expected_units):
        issues.append({'code':'QUANTITY_MISMATCH','severity':'BLOCK','message':f'Quantity {item.quantity} does not match frequency × duration for unit-dose dispensing ({expected_units}).'})
    if rule and rule.enabled:
        checks=[
            ('DOSE_BELOW_RULE',item.dose,rule.min_dose,'Dose is below the configured clinical rule.','BLOCK'),
            ('DOSE_ABOVE_RULE',item.dose,rule.max_dose,'Dose is above the configured clinical rule.','BLOCK'),
            ('DURATION_BELOW_RULE',item.duration_days,rule.min_duration_days,'Duration is below the configured clinical rule.','WARNING'),
            ('DURATION_ABOVE_RULE',item.duration_days,rule.max_duration_days,'Duration is above the configured clinical rule.','WARNING'),
            ('FREQUENCY_BELOW_RULE',item.frequency_per_day,rule.frequency_per_day_min,'Frequency is below the configured clinical rule.','WARNING'),
            ('FREQUENCY_ABOVE_RULE',item.frequency_per_day,rule.frequency_per_day_max,'Frequency is above the configured clinical rule.','WARNING')]
        for code,value,bound,msg,severity in checks:
            if bound is not None and ((code.endswith('BELOW_RULE') and value<bound) or (code.endswith('ABOVE_RULE') and value>bound)):
                issues.append({'code':code,'severity':severity,'message':msg})
    return issues
