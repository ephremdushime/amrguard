"""P3 EMR Connectors, National Surveillance, Observability & Offline Mode Test Suite.

Verifies:
1. Modular EMR Connectors framework (OpenMRS FHIR and REST Order ingestion, connector registry).
2. National Antimicrobial Surveillance Feed & WHO GLASS export with minimum-cell privacy suppression (< 5).
3. Production Observability and Prometheus OpenMetrics plaintext exposition endpoint.
4. Policy-bound offline dispensing queue: HMAC-SHA256 signatures, idempotent replay, concurrent conflict resolution, atomic stock decrement.
5. Automated Disaster Recovery Rehearsal drill script validation.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import secrets

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.connectors.base import BaseEMRConnector
from app.adapters.connectors.openmrs import OpenMRSConnector
from app.adapters.connectors.registry import get_connector, list_registered_connectors
from app.core.authz import (
    SCOPE_EBUZIMA_RX_WRITE,
)
from app.db.seed import DEMO_USER_PASSWORD, seed_demo
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.core import (
    Antibiotic,
    AuditEvent,
    Facility,
    OfflineDispenseRecord,
    Pharmacy,
    Prescription,
    PrescriptionItem,
    ServiceClient,
    ServiceClientCredential,
    ServiceClientScope,
    StockBatch,
)
from app.services.national_surveillance import (
    MINIMUM_CELL_THRESHOLD,
    export_national_surveillance_feed,
)
from app.services.observability import (
    gather_system_metrics,
    render_prometheus_metrics,
)
from app.services.offline_queue import (
    compute_offline_signature,
    enqueue_offline_bundle,
    reconcile_offline_bundle,
    verify_offline_signature,
)

import sys
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backup_restore_drill import run_backup_restore_drill

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


def _get_service_client_headers(db: Session, client_id_str: str = 'SVC-EBUZIMA-DEV') -> dict[str, str]:
    sc = db.scalar(select(ServiceClient).where(ServiceClient.client_id == client_id_str))
    assert sc is not None, f'ServiceClient {client_id_str} must be seeded'
    # Use standard dev integration header format
    return {'x-amrguard-integration-key': f'{sc.client_id}.devsecret123'}


# =============================================================================
# 1. Modular EMR Connectors Framework Tests
# =============================================================================

def test_connector_registry_and_discovery(db_session: Session):
    """Verifies connector registration, lookup, and health status reporting."""
    connectors = list_registered_connectors()
    assert len(connectors) >= 2
    codes = [c['connector_code'] for c in connectors]
    assert 'EBUZIMA_CANONICAL_V1' in codes
    assert 'OPENMRS_FHIR_V1' in codes

    openmrs = get_connector('OPENMRS_FHIR_V1')
    assert isinstance(openmrs, OpenMRSConnector)
    assert openmrs.connector_code == 'OPENMRS_FHIR_V1'

    health = openmrs.health_check()
    assert health['status'] == 'HEALTHY'
    assert 'FHIR_R4_MEDICATION_REQUEST' in health['supported_standards']


def test_openmrs_fhir_medication_request_parsing(db_session: Session):
    """Verifies transformation of OpenMRS FHIR MedicationRequest bundle into canonical Prescription."""
    connector = OpenMRSConnector()
    fhir_bundle = {
        'resourceType': 'Bundle',
        'type': 'collection',
        'entry': [
            {
                'resource': {
                    'resourceType': 'MedicationRequest',
                    'id': f'OPENMRS-MR-{secrets.token_hex(4)}',
                    'status': 'active',
                    'intent': 'order',
                    'subject': {'reference': 'Patient/OMRS-PT-9988', 'display': 'Synthetic Patient'},
                    'encounter': {'reference': 'Encounter/ENC-001'},
                    'recorder': {'reference': 'Organization/FAC-KGL-001'},
                    'requester': {'reference': 'Practitioner/DOC-OMRS-42', 'display': 'Dr. OpenMRS Provider'},
                    'medicationCodeableConcept': {
                        'coding': [
                            {
                                'system': 'http://openmrs.org/concepts',
                                'code': 'AMX500CAP',
                                'display': 'Amoxicillin 500mg Capsule',
                            }
                        ]
                    },
                    'dosageInstruction': [
                        {
                            'text': 'Take 1 capsule three times daily for 7 days',
                            'timing': {'repeat': {'frequency': 3, 'duration': 7}},
                            'doseAndRate': [{'doseQuantity': {'value': 500, 'unit': 'mg'}}],
                        }
                    ],
                    'dispenseRequest': {'quantity': {'value': 21, 'unit': 'capsules'}},
                }
            }
        ],
    }

    rx_in, warnings = connector.parse_inbound_prescription(fhir_bundle, db_session)
    assert rx_in.prescriber.facility_code == 'FAC-KGL-001'
    assert rx_in.patient_reference == 'Patient/OMRS-PT-9988'
    assert rx_in.prescriber.name == 'Dr. OpenMRS Provider'
    assert len(rx_in.items) == 1
    item = rx_in.items[0]
    assert item.antibiotic_code == 'AMX500CAP'
    assert item.quantity == 21
    assert item.duration_days == 7


def test_openmrs_rest_order_parsing(db_session: Session):
    """Verifies transformation of OpenMRS REST Order payload into canonical Prescription."""
    connector = OpenMRSConnector()
    order_payload = {
        'orderNumber': f'ORD-{secrets.token_hex(4)}',
        'uuid': f'uuid-{secrets.token_hex(6)}',
        'patient': {'uuid': 'PT-REST-1234'},
        'concept': {'uuid': 'AMX500CAP', 'display': 'Amoxicillin'},
        'orderer': {'uuid': 'DOC-REST-567', 'display': 'Dr. Rest Clinician'},
        'dose': 500,
        'frequency': 2,
        'duration': 5,
        'quantity': 10,
        'orderReasonText': 'Bacterial Sinusitis',
    }

    rx_in, warnings = connector.parse_inbound_prescription(order_payload, db_session)
    assert rx_in.patient_reference == 'PT-REST-1234'
    assert rx_in.prescriber.name == 'Dr. Rest Clinician'
    assert len(rx_in.items) == 1
    assert rx_in.items[0].antibiotic_code == 'AMX500CAP'
    assert rx_in.items[0].quantity == 10


def test_api_connectors_discovery_endpoint():
    """Verifies GET /api/v1/integrations/connectors discovery endpoint."""
    client, headers = _login('demo.operator')
    resp = client.get('/api/v1/integrations/connectors', headers=headers)
    assert resp.status_code == 200
    connectors = resp.json()
    assert any(c['connector_code'] == 'OPENMRS_FHIR_V1' for c in connectors)
    assert any(c['connector_code'] == 'EBUZIMA_CANONICAL_V1' for c in connectors)


def test_api_openmrs_medication_request_ingestion(db_session: Session):
    """Verifies POST /api/v1/integrations/openmrs/medication-request service client route."""
    # Ensure a service client with integrations:openmrs:prescriptions:write scope
    fac = db_session.scalar(select(Facility).where(Facility.code == 'FAC-KGL-001'))
    assert fac is not None, 'FAC-KGL-001 must exist'

    sc = db_session.scalar(select(ServiceClient).where(ServiceClient.client_code == 'SVC-OPENMRS-DEV'))
    if not sc:
        sc = ServiceClient(
            client_code='SVC-OPENMRS-DEV',
            name='OpenMRS Hospital Connector',
            partner_type='EMR',
            active=True,
        )
        db_session.add(sc)
        db_session.flush()

        scope = ServiceClientScope(
            service_client_id=sc.id,
            scope='integrations:openmrs:prescriptions:write',
            facility_id=fac.id,
            active=True,
        )
        db_session.add(scope)

        from app.core.auth import keyed_digest
        token_secret = 'openmrssecret123'
        secret_hash = keyed_digest(token_secret, purpose='service_client_key', salt=sc.client_code)
        cred = ServiceClientCredential(
            service_client_id=sc.id,
            key_prefix=sc.client_code,
            secret_hash=secret_hash,
        )
        db_session.add(cred)
        db_session.commit()
    else:
        scope = db_session.scalar(
            select(ServiceClientScope).where(
                ServiceClientScope.service_client_id == sc.id,
                ServiceClientScope.scope == 'integrations:openmrs:prescriptions:write',
                ServiceClientScope.facility_id == fac.id,
            )
        )
        if not scope:
            scope = ServiceClientScope(
                service_client_id=sc.id,
                scope='integrations:openmrs:prescriptions:write',
                facility_id=fac.id,
                active=True,
            )
            db_session.add(scope)
            db_session.commit()

    anon = TestClient(app)
    headers = {'x-amrguard-integration-key': 'SVC-OPENMRS-DEV.openmrssecret123'}

    order_payload = {
        'orderNumber': f'ORD-{secrets.token_hex(4)}',
        'uuid': f'uuid-{secrets.token_hex(6)}',
        'patient': {'uuid': 'PT-OPENMRS-LIVE'},
        'concept': {'uuid': 'AMX500CAP', 'display': 'Amoxicillin'},
        'orderer': {'uuid': 'DOC-LIVE-1', 'display': 'Dr. Live Hospital'},
        'dose': 500,
        'frequency': 3,
        'duration': 7,
        'quantity': 21,
        'orderReasonText': 'Upper Respiratory Tract Infection',
    }

    resp = anon.post('/api/v1/integrations/openmrs/medication-request', json=order_payload, headers=headers)
    assert resp.status_code == 200, f'OpenMRS ingestion failed: {resp.text}'
    data = resp.json()
    assert data['external_id'] == order_payload['orderNumber']
    assert data['status'] in ('VALIDATED', 'WARNING')


# =============================================================================
# 2. National Surveillance Feeds & WHO GLASS Export Tests
# =============================================================================

def test_export_national_surveillance_feed_privacy_suppression(db_session: Session):
    """Verifies district aggregation and cell suppression (< 5) in national surveillance export."""
    feed = export_national_surveillance_feed(db_session)
    assert feed['feed_type'] == 'NATIONAL_AMR_SURVEILLANCE_EXPORT'
    assert 'national_summary' in feed
    assert 'meets_who_access_benchmark' in feed['national_summary']
    assert isinstance(feed['district_breakdowns'], list)

    # Check cell suppression logic: counts between 1 and 4 must be suppressed to None
    for dist in feed['district_breakdowns']:
        for cat, val in dist['aware_counts'].items():
            if val is not None:
                assert val == 0 or val >= MINIMUM_CELL_THRESHOLD, (
                    f"District {dist['district']} category {cat} was not suppressed: {val}"
                )


def test_api_national_surveillance_export_authorization():
    """Verifies RBAC rules on GET /api/v1/national/surveillance/export."""
    # national_analyst should be allowed
    analyst_client, analyst_headers = _login('demo.analyst')
    resp = analyst_client.get('/api/v1/national/surveillance/export', headers=analyst_headers)
    assert resp.status_code == 200
    assert resp.json()['feed_type'] == 'NATIONAL_AMR_SURVEILLANCE_EXPORT'

    # prescriber should be denied (403)
    prescriber_client, prescriber_headers = _login('demo.prescriber')
    resp_p = prescriber_client.get('/api/v1/national/surveillance/export', headers=prescriber_headers)
    assert resp_p.status_code == 403


# =============================================================================
# 3. Observability & Prometheus Metrics Exposition Tests
# =============================================================================

def test_gather_system_metrics(db_session: Session):
    """Verifies system metric extraction dictionary."""
    metrics = gather_system_metrics(db_session)
    assert 'prescriptions_total' in metrics
    assert 'dispenses_total' in metrics
    assert 'active_batches' in metrics
    assert 'outbox_pending' in metrics
    assert 'outbox_dead_letter' in metrics
    assert 'auth_failures_total' in metrics


def test_render_prometheus_metrics(db_session: Session):
    """Verifies plaintext Prometheus OpenMetrics output."""
    output = render_prometheus_metrics(db_session)
    assert '# HELP amrguard_prescriptions_total' in output
    assert '# TYPE amrguard_prescriptions_total counter' in output
    assert 'amrguard_prescriptions_total' in output
    assert 'amrguard_dispenses_total' in output
    assert 'amrguard_active_stock_batches' in output


def test_api_observability_metrics_endpoint():
    """Verifies GET /api/v1/observability/metrics returns Prometheus or JSON metrics."""
    client, headers = _login('demo.operator')

    # Prometheus format
    resp_prom = client.get('/api/v1/observability/metrics?format=prometheus', headers=headers)
    assert resp_prom.status_code == 200
    assert 'text/plain' in resp_prom.headers.get('content-type', '')
    assert 'amrguard_prescriptions_total' in resp_prom.text

    # JSON format
    resp_json = client.get('/api/v1/observability/metrics?format=json', headers=headers)
    assert resp_json.status_code == 200
    assert 'application/json' in resp_json.headers.get('content-type', '')
    data = resp_json.json()
    assert 'prescriptions_total' in data


# =============================================================================
# 4. Policy-Bound Offline Queue & Atomic Reconciliation Tests
# =============================================================================

def test_offline_signature_verification_and_tamper_proofing():
    """Verifies HMAC-SHA256 signature verification and tamper detection."""
    pharmacy_id = 1
    device_fp = 'POS-TERMINAL-01'
    tx_id = f'TX-OFFLINE-{secrets.token_hex(4)}'
    payload = {'prescription_id': 1, 'quantity': 10, 'batch_id': 1}
    payload_str = json.dumps(payload, sort_keys=True)

    sig = compute_offline_signature(pharmacy_id, device_fp, tx_id, payload_str)
    assert verify_offline_signature(pharmacy_id, device_fp, tx_id, payload_str, sig) is True

    # Tampered payload fails verification
    tampered_str = json.dumps({'prescription_id': 1, 'quantity': 100, 'batch_id': 1}, sort_keys=True)
    assert verify_offline_signature(pharmacy_id, device_fp, tx_id, tampered_str, sig) is False


def test_offline_queue_enqueue_and_idempotent_replay(db_session: Session):
    """Verifies queuing offline bundles and duplicate replay prevention."""
    pharmacy = db_session.scalar(select(Pharmacy).where(Pharmacy.active.is_(True)))
    assert pharmacy is not None

    bundle_id = f'BUNDLE-{secrets.token_hex(6)}'
    device_fp = 'POS-HW-991'
    tx_id = f'TX-OFFLINE-{secrets.token_hex(4)}'
    payload = {'prescription_id': 1, 'quantity': 5, 'batch_id': 1}
    payload_str = json.dumps(payload, sort_keys=True)
    sig = compute_offline_signature(pharmacy.id, device_fp, tx_id, payload_str)

    # First enqueue
    rec = enqueue_offline_bundle(
        db_session,
        bundle_id=bundle_id,
        pharmacy_id=pharmacy.id,
        device_fingerprint=device_fp,
        signature=sig,
        offline_transaction_id=tx_id,
        prescription_code='RX-TEST-OFFLINE',
        payload=payload,
    )
    assert rec.status == 'PENDING'
    assert rec.bundle_id == bundle_id

    # Second enqueue with same transaction id is idempotent replay
    rec_replayed = enqueue_offline_bundle(
        db_session,
        bundle_id=f'BUNDLE-NEW-{secrets.token_hex(4)}',
        pharmacy_id=pharmacy.id,
        device_fingerprint=device_fp,
        signature=sig,
        offline_transaction_id=tx_id,
        prescription_code='RX-TEST-OFFLINE',
        payload=payload,
    )
    assert rec_replayed.id == rec.id
    assert rec_replayed.bundle_id == bundle_id


def test_offline_reconciliation_happy_path(db_session: Session):
    """Verifies clean offline bundle reconciliation, stock decrement, and outbox creation."""
    pharmacy = db_session.scalar(select(Pharmacy).where(Pharmacy.id == 1))
    batch = db_session.scalar(select(StockBatch).where(StockBatch.pharmacy_id == pharmacy.id, StockBatch.quantity_available >= 10))
    if not batch:
        batch = StockBatch(
            pharmacy_id=pharmacy.id,
            antibiotic_id=1,
            batch_number=f'BAT-OFFLINE-{secrets.token_hex(3)}',
            expiry_date=date.today() + timedelta(days=180),
            quantity_available=50,
        )
        db_session.add(batch)
        db_session.flush()

    # Create active prescription
    rx = Prescription(
        external_id=f'RX-OFF-{secrets.token_hex(4)}',
        patient_reference='PT-OFFLINE',
        facility_id=pharmacy.facility_id,
        prescriber_id=1,
        status='ACTIVE',
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add(rx)
    db_session.flush()

    rx_item = PrescriptionItem(
        prescription_id=rx.id,
        antibiotic_id=batch.antibiotic_id,
        dose=Decimal('500'),
        frequency_per_day=Decimal('3'),
        duration_days=5,
        quantity=15,
        indication='Bacterial infection',
    )
    db_session.add(rx_item)
    db_session.commit()

    initial_stock = batch.quantity_available
    dispense_qty = 15

    bundle_id = f'BUNDLE-RECON-{secrets.token_hex(6)}'
    device_fp = 'POS-TERMINAL-01'
    tx_id = f'TX-OFFLINE-RECON-{secrets.token_hex(4)}'
    payload = {'prescription_id': rx.id, 'quantity': dispense_qty, 'batch_id': batch.id}
    sig = compute_offline_signature(pharmacy.id, device_fp, tx_id, json.dumps(payload, sort_keys=True))

    rec = enqueue_offline_bundle(
        db_session,
        bundle_id=bundle_id,
        pharmacy_id=pharmacy.id,
        device_fingerprint=device_fp,
        signature=sig,
        offline_transaction_id=tx_id,
        prescription_code=rx.external_id,
        payload=payload,
    )

    reconciled_rec, tx = reconcile_offline_bundle(db_session, bundle_id=rec.bundle_id, reconciled_by_user_id=1)
    assert reconciled_rec.status == 'RECONCILED'
    assert tx is not None
    assert tx.quantity == dispense_qty
    assert rx.status == 'COMPLETED'
    assert batch.quantity_available == initial_stock - dispense_qty


def test_offline_reconciliation_conflict_on_terminal_prescription(db_session: Session):
    """Verifies that an already COMPLETED prescription triggers CONFLICT and preserves stock."""
    pharmacy = db_session.scalar(select(Pharmacy).where(Pharmacy.id == 1))
    batch = db_session.scalar(select(StockBatch).where(StockBatch.pharmacy_id == pharmacy.id, StockBatch.quantity_available >= 10))

    # Prescription already in terminal state
    rx = Prescription(
        external_id=f'RX-TERM-{secrets.token_hex(4)}',
        patient_reference='PT-OFFLINE',
        facility_id=pharmacy.facility_id,
        prescriber_id=1,
        status='COMPLETED',
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add(rx)
    db_session.commit()

    initial_stock = batch.quantity_available

    bundle_id = f'BUNDLE-CONFLICT-{secrets.token_hex(6)}'
    device_fp = 'POS-TERMINAL-01'
    tx_id = f'TX-CONFLICT-{secrets.token_hex(4)}'
    payload = {'prescription_id': rx.id, 'quantity': 10, 'batch_id': batch.id}
    sig = compute_offline_signature(pharmacy.id, device_fp, tx_id, json.dumps(payload, sort_keys=True))

    rec = enqueue_offline_bundle(
        db_session,
        bundle_id=bundle_id,
        pharmacy_id=pharmacy.id,
        device_fingerprint=device_fp,
        signature=sig,
        offline_transaction_id=tx_id,
        prescription_code=rx.external_id,
        payload=payload,
    )

    reconciled_rec, tx = reconcile_offline_bundle(db_session, bundle_id=rec.bundle_id, reconciled_by_user_id=1)
    assert reconciled_rec.status == 'CONFLICT'
    assert 'terminal state COMPLETED' in reconciled_rec.conflict_reason
    assert tx is None
    # Stock must remain unchanged!
    assert batch.quantity_available == initial_stock


def test_api_offline_dispense_queue_and_reconcile_routes():
    """Verifies REST endpoints POST /api/v1/dispensing/offline-queue and offline-reconcile."""
    client, headers = _login('demo.pharmacist')

    bundle_id = f'BUNDLE-API-{secrets.token_hex(6)}'
    device_fp = 'POS-TABLET-02'
    tx_id = f'TX-API-{secrets.token_hex(4)}'
    payload = {'prescription_id': 1, 'quantity': 5, 'batch_id': 1}
    sig = compute_offline_signature(1, device_fp, tx_id, json.dumps(payload, sort_keys=True))

    queue_req = {
        'bundle_id': bundle_id,
        'pharmacy_id': 1,
        'device_fingerprint': device_fp,
        'signature': sig,
        'offline_transaction_id': tx_id,
        'prescription_code': 'RX-TEST-API',
        'payload': payload,
    }

    # Queue bundle
    resp_q = client.post('/api/v1/dispensing/offline-queue', json=queue_req, headers=headers)
    assert resp_q.status_code == 200
    q_data = resp_q.json()
    assert q_data['bundle_id'] == bundle_id
    assert q_data['status'] == 'PENDING'

    # List queue
    resp_l = client.get('/api/v1/dispensing/offline-queue?pharmacy_id=1', headers=headers)
    assert resp_l.status_code == 200
    items = resp_l.json()
    assert any(i['bundle_id'] == bundle_id for i in items)

    # Reconcile bundle
    recon_req = {'bundle_id': bundle_id}
    resp_r = client.post('/api/v1/dispensing/offline-reconcile', json=recon_req, headers=headers)
    assert resp_r.status_code == 200
    r_data = resp_r.json()
    assert r_data['bundle_id'] == bundle_id
    assert r_data['status'] in ('RECONCILED', 'CONFLICT')


# =============================================================================
# 5. Automated Disaster Recovery Rehearsal Drill Validation
# =============================================================================

def test_disaster_recovery_backup_and_restore_drill():
    """Verifies automated DR drill execution, SHA-256 calculation, and RPO/RTO validation."""
    report = run_backup_restore_drill(backup_dir='backups')
    assert report['drill_status'] == 'SUCCESS'
    assert 'COMPLIANT' in report['rpo_compliance']
    assert 'COMPLIANT' in report['rto_compliance']
    assert len(report['sha256_checksum']) == 64
    assert report['validated_tables'] >= 25
