"""P2 Antimicrobial Stewardship Intelligence, WHO AWaRe & Governed Rules Test Suite.

Verifies:
1. WHO AWaRe classification service, antibiotic resolution, and target benchmark tracking.
2. Governed metrics dictionary evaluation, minimum-cell privacy suppression (< 5), and caveats.
3. Clinically governed stewardship rules engine, structured alert generation on prescription intake.
4. Clinician & stewardship officer alert disposition workflow (Accepted, Overridden, False Positive) and auditing.
5. REST API routes authorization, multi-tenant scoping, and analytics enrichment.
"""

from datetime import date, datetime, timedelta, timezone
import secrets

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.seed import (
    DEMO_USER_PASSWORD,
    seed_demo,
)
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.core import (
    Antibiotic,
    AuditEvent,
    Facility,
    GovernedStewardshipRule,
    Prescriber,
    Prescription,
    PrescriptionItem,
    StewardshipAlert,
    WhoAwareClassification,
)
from app.services.aware import (
    calculate_aware_breakdown,
    classify_antibiotic,
    seed_who_aware_classifications,
)
from app.services.metrics import (
    DATA_QUALITY_CAVEATS,
    evaluate_governed_metrics,
    seed_metric_definitions,
)
from app.services.rules_engine import (
    evaluate_prescription_rules,
    get_active_rules,
    record_alert_disposition,
    seed_governed_rules,
)

Base.metadata.create_all(engine)
with SessionLocal() as _db:
    seed_demo(_db)

UTC = timezone.utc


@pytest.fixture
def db_session():
    with SessionLocal() as session:
        yield session


def _login(username: str) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    resp = client.post('/api/v1/auth/login', json={'username': username, 'password': DEMO_USER_PASSWORD})
    assert resp.status_code == 200, f'Login failed for {username}: {resp.text}'
    csrf = resp.json().get('csrf_token', '')
    return client, {'x-csrf-token': csrf}


# =============================================================================
# 1. WHO AWaRe Classification Service Tests
# =============================================================================

def test_who_aware_classification_service(db_session: Session):
    """Verifies authoritative WHO AWaRe classifications and breakdown calculation."""
    seed_who_aware_classifications(db_session)

    # Core formulary classifications
    assert classify_antibiotic(db_session, 'AMX500CAP') == 'ACCESS'
    assert classify_antibiotic(db_session, 'AMP500CAP') == 'ACCESS'
    assert classify_antibiotic(db_session, 'DOX100TAB') == 'ACCESS'
    assert classify_antibiotic(db_session, 'CIP500TAB') == 'WATCH'
    assert classify_antibiotic(db_session, 'CRO1GINJ') == 'WATCH'
    assert classify_antibiotic(db_session, 'COL1MINJ') == 'RESERVE'

    # Fallback heuristic for unclassified code
    cat = classify_antibiotic(db_session, 'UNKNOWN_CODE')
    assert cat in {'ACCESS', 'WATCH', 'RESERVE'}

    # Breakdown calculation
    breakdown = calculate_aware_breakdown(db_session)
    assert 'total_orders' in breakdown
    assert 'access_percentage' in breakdown
    assert 'watch_percentage' in breakdown
    assert 'reserve_percentage' in breakdown
    assert 'meets_who_access_target' in breakdown
    assert breakdown['who_benchmark'] == '>= 60% of total consumption from Access group'
    assert 'cell_suppression_applied' in breakdown


# =============================================================================
# 2. Governed Metrics Dictionary & Privacy Suppression Tests
# =============================================================================

def test_governed_metrics_service_and_suppression(db_session: Session):
    """Verifies KPI evaluation, minimum-cell privacy suppression, and data caveats."""
    seed_metric_definitions(db_session)
    metrics_result = evaluate_governed_metrics(db_session)

    assert 'metrics' in metrics_result
    assert 'counts' in metrics_result
    assert 'data_quality_caveats' in metrics_result
    assert metrics_result['data_quality_caveats'] == DATA_QUALITY_CAVEATS

    # Check that all 5 standard governed metrics exist
    metric_codes = {m['metric_code'] for m in metrics_result['metrics']}
    expected_codes = {
        'AWARE_ACCESS_PCT',
        'RX_DISPENSE_RECON_RATE',
        'STEWARDSHIP_REVIEW_RATE',
        'QUANTITY_DISCREPANCY_RATE',
        'TOTAL_ESTIMATED_DOT',
    }
    assert expected_codes.issubset(metric_codes)

    # Verify minimum-cell suppression format in counts
    for key, count_info in metrics_result['counts'].items():
        if isinstance(count_info, dict):
            assert 'suppressed' in count_info
            assert 'display' in count_info
            if count_info['suppressed']:
                assert count_info['value'] is None
                assert count_info['display'] == '<5'


# =============================================================================
# 3. Governed Rules Engine & Alert Generation Tests
# =============================================================================

def test_rules_engine_evaluation_and_alerts(db_session: Session):
    """Verifies that active rules trigger structured alerts on prescription intake."""
    seed_who_aware_classifications(db_session)
    seed_governed_rules(db_session)
    active_rules = get_active_rules(db_session)
    assert len(active_rules) >= 3

    fac = db_session.scalar(select(Facility).where(Facility.code == 'FAC-KGL-001'))
    pr = db_session.scalar(select(Prescriber).where(Prescriber.external_user_id == 'EBZ-USER-001'))
    cipro = db_session.scalar(select(Antibiotic).where(Antibiotic.code == 'CIP500TAB'))
    assert fac and pr and cipro

    # Create a synthetic prescription with Watch-group antibiotic + prolonged duration (10 days > 7 ceiling)
    rx_code = f'EBZ-P2-TEST-{secrets.token_hex(4).upper()}'
    rx = Prescription(
        external_id=rx_code,
        patient_reference='PATIENT-P2-SYNTH',
        prescriber_id=pr.id,
        facility_id=fac.id,
        status='VALIDATED',
    )
    db_session.add(rx)
    db_session.flush()

    item = PrescriptionItem(
        prescription_id=rx.id,
        antibiotic_id=cipro.id,
        dose=500,
        frequency_per_day=2,
        duration_days=10,  # Exceeds 7-day ceiling
        quantity=20,
        indication='Complicated urinary tract infection',
    )
    db_session.add(item)
    db_session.flush()

    alerts = evaluate_prescription_rules(db_session, rx, auto_commit=True)
    assert len(alerts) >= 2  # Expect Watch-group restriction + Duration > 7 days

    rule_codes = {a.rule_code for a in alerts}
    assert 'RULE-ACCESS-FIRSTLINE' in rule_codes
    assert 'RULE-MAX-DURATION-7D' in rule_codes

    for alert in alerts:
        assert alert.status == 'OPEN'
        assert alert.alert_id.startswith('ALT-')
        assert alert.message
        assert alert.clinical_evidence


# =============================================================================
# 4. Alert Disposition & Auditing Tests
# =============================================================================

def test_alert_disposition_service(db_session: Session):
    """Verifies clinician disposition transitions and rationale recording."""
    seed_who_aware_classifications(db_session)
    seed_governed_rules(db_session)
    fac = db_session.scalar(select(Facility).where(Facility.code == 'FAC-KGL-001'))
    pr = db_session.scalar(select(Prescriber).where(Prescriber.external_user_id == 'EBZ-USER-001'))
    cipro = db_session.scalar(select(Antibiotic).where(Antibiotic.code == 'CIP500TAB'))

    rx = Prescription(
        external_id=f'EBZ-DISP-{secrets.token_hex(4).upper()}',
        patient_reference='PATIENT-DISP-TEST',
        prescriber_id=pr.id,
        facility_id=fac.id,
        status='VALIDATED',
    )
    db_session.add(rx)
    db_session.flush()

    item = PrescriptionItem(
        prescription_id=rx.id,
        antibiotic_id=cipro.id,
        dose=500,
        frequency_per_day=2,
        duration_days=10,
        quantity=20,
        indication='Severe pyelonephritis',
    )
    db_session.add(item)
    db_session.flush()

    alerts = evaluate_prescription_rules(db_session, rx, auto_commit=True)
    assert alerts

    # Test disposition with OVERRIDDEN_WITH_REASON
    target_alert = alerts[0]
    updated = record_alert_disposition(
        db_session,
        alert_id=target_alert.alert_id,
        outcome='OVERRIDDEN_WITH_REASON',
        reason='Patient has documented resistance to amoxicillin; ciprofloxacin indicated based on urine culture.',
        user_id=1,
    )
    assert updated.status == 'OVERRIDDEN'
    assert updated.disposition_outcome == 'OVERRIDDEN_WITH_REASON'
    assert 'culture' in updated.disposition_reason
    assert updated.disposition_at is not None

    # Test disposition with FALSE_POSITIVE_FLAGGED
    if len(alerts) > 1:
        fp_alert = alerts[1]
        fp_updated = record_alert_disposition(
            db_session,
            alert_id=fp_alert.alert_id,
            outcome='FALSE_POSITIVE_FLAGGED',
            reason='Flagged rule threshold does not apply to this specialty inpatient protocol.',
            user_id=1,
        )
        assert fp_updated.status == 'FALSE_POSITIVE'
        assert fp_updated.disposition_outcome == 'FALSE_POSITIVE_FLAGGED'


# =============================================================================
# 5. REST API Endpoints & RBAC Authorization Tests
# =============================================================================

def test_api_stewardship_metrics_rbac_and_tenant_scope():
    """Verifies RBAC enforcement and tenant facility scoping on GET /api/v1/stewardship/metrics."""
    client = TestClient(app)

    # 1. Anonymous access is rejected
    anon_resp = client.get('/api/v1/stewardship/metrics')
    assert anon_resp.status_code == 401

    # 2. Stewardship officer can retrieve metrics
    steward_client, steward_headers = _login('demo.steward')
    steward_resp = steward_client.get('/api/v1/stewardship/metrics', headers=steward_headers)
    assert steward_resp.status_code == 200
    steward_data = steward_resp.json()
    assert 'metrics' in steward_data
    assert 'aware_breakdown' in steward_data
    assert len(steward_data['metrics']) >= 5

    # 3. National analyst can retrieve national metrics
    analyst_client, analyst_headers = _login('demo.analyst')
    analyst_resp = analyst_client.get('/api/v1/stewardship/metrics', headers=analyst_headers)
    assert analyst_resp.status_code == 200

    # 4. Cross-facility access denied: facility admin cannot request metrics for unauthorized facility
    fac_client, fac_headers = _login('demo.admin')
    cross_resp = fac_client.get('/api/v1/stewardship/metrics?facility_id=999999', headers=fac_headers)
    assert cross_resp.status_code == 403


def test_api_aware_catalog_and_stewardship_rules():
    """Verifies catalog lookups and rule dictionary discovery endpoints."""
    client = TestClient(app)

    # 1. Anonymous rejected
    assert client.get('/api/v1/stewardship/aware-catalog').status_code == 401
    assert client.get('/api/v1/stewardship/rules').status_code == 401

    # 2. Authenticated access to AWaRe catalog
    steward_client, steward_headers = _login('demo.steward')
    cat_resp = steward_client.get('/api/v1/stewardship/aware-catalog', headers=steward_headers)
    assert cat_resp.status_code == 200
    catalog = cat_resp.json()
    assert len(catalog) >= 10
    assert any(item['antibiotic_code'] == 'AMX500CAP' and item['category'] == 'ACCESS' for item in catalog)

    # Filter by category
    watch_resp = steward_client.get('/api/v1/stewardship/aware-catalog?category=WATCH', headers=steward_headers)
    assert watch_resp.status_code == 200
    for item in watch_resp.json():
        assert item['category'] == 'WATCH'

    # 3. Authenticated access to Stewardship Rules
    rules_resp = steward_client.get('/api/v1/stewardship/rules', headers=steward_headers)
    assert rules_resp.status_code == 200
    rules = rules_resp.json()
    assert len(rules) >= 3
    rule_codes = {r['rule_code'] for r in rules}
    assert 'RULE-ACCESS-FIRSTLINE' in rule_codes
    assert 'RULE-MAX-DURATION-7D' in rule_codes


def test_api_alerts_and_disposition_lifecycle(db_session: Session):
    """Verifies full lifecycle: rx creation generates alert, listing alerts, and recording disposition via API."""
    prescriber_client, prescriber_headers = _login('demo.prescriber')

    # 1. Create a synthetic prescription that triggers a Watch-group alert
    rx_resp = prescriber_client.post(
        '/api/v1/demo/prescriptions',
        json={
            'external_id': f'EBZ-API-ALERT-{secrets.token_hex(4).upper()}',
            'patient_reference': 'PATIENT-API-ALERT',
            'antibiotic_code': 'CIP500TAB',
            'dose': 500,
            'frequency_per_day': 2,
            'duration_days': 10,
            'quantity': 20,
            'indication': 'Uncomplicated UTI (Watch firstline test)',
        },
        headers=prescriber_headers,
    )
    assert rx_resp.status_code == 200
    rx_id = rx_resp.json()['prescription']['id']

    # 2. List alerts for this prescription
    steward_client, steward_headers = _login('demo.steward')
    alerts_resp = steward_client.get(f'/api/v1/stewardship/alerts?prescription_id={rx_id}', headers=steward_headers)
    assert alerts_resp.status_code == 200
    alerts = alerts_resp.json()
    assert len(alerts) >= 1
    target_alert = alerts[0]
    assert target_alert['status'] == 'OPEN'

    # 3. Disposition the alert via API
    disp_resp = steward_client.post(
        f'/api/v1/stewardship/alerts/{target_alert["alert_id"]}/disposition',
        json={
            'outcome': 'ACCEPTED',
            'reason': 'Clinician agreed to switch from ciprofloxacin to amoxicillin-clavulanate based on local antibiogram.',
        },
        headers=steward_headers,
    )
    assert disp_resp.status_code == 200
    updated_alert = disp_resp.json()
    assert updated_alert['status'] == 'RESOLVED'
    assert updated_alert['disposition_outcome'] == 'ACCEPTED'

    # 4. Verify audit event was logged
    audit_event = db_session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.event_type == 'STEWARDSHIP_ALERT_DISPOSITIONED',
            AuditEvent.entity_id == target_alert['alert_id'],
        )
        .order_by(AuditEvent.created_at.desc())
    )
    assert audit_event is not None


def test_api_analytics_summary_includes_aware():
    """Verifies GET /api/v1/analytics/summary includes the WHO AWaRe breakdown."""
    analyst_client, analyst_headers = _login('demo.analyst')
    resp = analyst_client.get('/api/v1/analytics/summary', headers=analyst_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert 'aware_breakdown' in data
    assert data['aware_breakdown'] is not None
    assert 'access_percentage' in data['aware_breakdown']
    assert 'meets_who_access_target' in data['aware_breakdown']
