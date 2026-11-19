"""PostgreSQL 16 integration, transaction, concurrency, locking, and append-only audit tests.

Runs ONLY against an isolated, disposable synthetic PostgreSQL database specified via
POSTGRES_TEST_DATABASE_URL (never an operational or production database).
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import os
from pathlib import Path
from uuid import uuid4

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import sessionmaker

POSTGRES_TEST_URL = os.environ.get('POSTGRES_TEST_DATABASE_URL', '').strip()

pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason='Set POSTGRES_TEST_DATABASE_URL to an isolated disposable PostgreSQL test DB to run PostgreSQL integration tests',
)


def _assert_safe_disposable_test_url(url: str) -> None:
    lowered = url.lower()
    if not lowered.startswith('postgresql'):
        raise RuntimeError('POSTGRES_TEST_DATABASE_URL must be a PostgreSQL URL')
    if 'prod' in lowered:
        raise RuntimeError('Refusing to run PostgreSQL integration tests against any URL containing "prod"')
    if 'test' not in lowered:
        raise RuntimeError('POSTGRES_TEST_DATABASE_URL must explicitly target a disposable "*test*" database')


@pytest.fixture(scope='module')
def pg_engine():
    _assert_safe_disposable_test_url(POSTGRES_TEST_URL)
    eng = create_engine(POSTGRES_TEST_URL, pool_pre_ping=True, pool_size=12, max_overflow=8)

    # Reset disposable synthetic test schema cleanly
    with eng.begin() as conn:
        conn.execute(text('DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;'))

    backend_dir = Path(__file__).resolve().parents[1]
    alembic_cfg = AlembicConfig(str(backend_dir / 'alembic.ini'))
    alembic_cfg.set_main_option('script_location', str(backend_dir / 'alembic'))
    alembic_cfg.set_main_option('sqlalchemy.url', POSTGRES_TEST_URL)

    # Override env.py settings URL cleanly for migration verification
    from app.core.config import settings

    original_url = settings.database_url
    settings.database_url = POSTGRES_TEST_URL
    try:
        alembic_command.upgrade(alembic_cfg, 'head')
        # Verify reversibility of migration 0006 on PostgreSQL 16
        alembic_command.downgrade(alembic_cfg, '0005_stewardship_reviews')
        alembic_command.upgrade(alembic_cfg, 'head')
    finally:
        settings.database_url = original_url

    yield eng
    eng.dispose()


@pytest.fixture()
def pg_session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)


def _seed_pg_dispense_scenario(SessionFactory, *, rx_quantity: int = 15, initial_stock: int = 120):
    from app.core.authz import ROLE_PHARMACIST
    from app.db.seed import DEMO_USER_PASSWORD, ensure_local_user, ensure_role_scope, seed_roles
    from app.models.core import (
        Antibiotic,
        Facility,
        Organization,
        Pharmacy,
        Prescriber,
        Prescription,
        PrescriptionCredential,
        PrescriptionItem,
        StockBatch,
    )
    from app.services.security import keyed_digest
    from datetime import datetime, timezone

    suffix = uuid4().hex[:8].upper()
    otp = f'{int(uuid4().hex[:6], 16) % 1000000:06d}'
    qr = f'qr-pg-{suffix}-{uuid4().hex}'

    with SessionFactory() as db:
        roles = seed_roles(db)
        org = Organization(code=f'PG-ORG-{suffix}', name=f'PG Org {suffix}')
        db.add(org)
        db.flush()
        fac = Facility(code=f'PG-FAC-{suffix}', name=f'PG Facility {suffix}', district='Gasabo', organization_id=org.id)
        db.add(fac)
        db.flush()
        pharm = Pharmacy(
            code=f'PG-PHA-{suffix}',
            name=f'PG Pharmacy {suffix}',
            district='Gasabo',
            organization_id=org.id,
            facility_id=fac.id,
            pharmacy_type='FACILITY_PHARMACY',
        )
        db.add(pharm)
        db.flush()
        ab = db.scalar(select(Antibiotic).where(Antibiotic.code == 'AMX500CAP'))
        if not ab:
            ab = Antibiotic(
                code='AMX500CAP',
                generic_name='Amoxicillin',
                strength='500 mg',
                formulation='Capsule',
                route='Oral',
            )
            db.add(ab)
            db.flush()
        batch = StockBatch(
            pharmacy_id=pharm.id,
            antibiotic_id=ab.id,
            batch_number=f'PG-BATCH-{suffix}',
            expiry_date=date.today() + timedelta(days=365),
            quantity_available=initial_stock,
            source_reference='PG-SYNTHETIC',
        )
        db.add(batch)
        presc = Prescriber(external_user_id=f'PG-PR-{suffix}', name='PG Prescriber', facility_id=fac.id)
        db.add(presc)
        db.flush()
        rx = Prescription(
            external_id=f'PG-RX-{suffix}',
            patient_reference=f'PG-PAT-{suffix}',
            prescriber_id=presc.id,
            facility_id=fac.id,
            status='ACTIVE',
        )
        db.add(rx)
        db.flush()
        item = PrescriptionItem(
            prescription_id=rx.id,
            antibiotic_id=ab.id,
            dose=500,
            frequency_per_day=3,
            duration_days=max(1, rx_quantity // 3),
            quantity=rx_quantity,
            indication='PG concurrency test',
        )
        db.add(item)
        db.flush()
        cred = PrescriptionCredential(
            prescription_id=rx.id,
            otp_hash=keyed_digest(otp, purpose='rx_otp'),
            qr_token_hash=keyed_digest(qr, purpose='rx_qr'),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        db.add(cred)
        user = ensure_local_user(
            db, username=f'pg.pharm.{suffix.lower()}', display_name='PG Pharmacist', password=DEMO_USER_PASSWORD
        )
        ensure_role_scope(db, user=user, role=roles[ROLE_PHARMACIST], scope_type='PHARMACY', pharmacy_id=pharm.id)
        db.commit()
        return {
            'facility_id': fac.id,
            'pharmacy_id': pharm.id,
            'batch_id': batch.id,
            'rx_id': rx.id,
            'item_id': item.id,
            'user_id': user.id,
            'otp': otp,
        }


def test_postgres_append_only_audit_trigger_blocks_raw_sql_update_and_delete(pg_engine, pg_session_factory):
    from app.services.audit import record_audit

    with pg_session_factory() as db:
        ev = record_audit(
            db,
            'PG_IMMUTABILITY_TEST',
            'Prescription',
            'pg-1',
            'AMRGuard',
            actor_type='SYSTEM',
            outcome='SUCCESS',
            details={'synthetic': True},
        )
        db.commit()
        ev_id = ev.id

    # Raw SQL UPDATE bypassing SQLAlchemy ORM must be rejected by PostgreSQL trigger
    with pytest.raises(DatabaseError) as upd_exc:
        with pg_engine.begin() as conn:
            conn.execute(text("UPDATE audit_events SET outcome = 'TAMPERED' WHERE id = :id"), {'id': ev_id})
    assert 'append-only' in str(upd_exc.value).lower()

    # Raw SQL DELETE bypassing SQLAlchemy ORM must be rejected by PostgreSQL trigger
    with pytest.raises(DatabaseError) as del_exc:
        with pg_engine.begin() as conn:
            conn.execute(text('DELETE FROM audit_events WHERE id = :id'), {'id': ev_id})
    assert 'append-only' in str(del_exc.value).lower()


def test_postgres_check_constraint_rejects_nullable_scope(pg_session_factory):
    from app.core.authz import ROLE_FACILITY_ADMIN
    from app.db.seed import DEMO_USER_PASSWORD, ensure_local_user, seed_roles
    from app.models.core import UserRoleScope

    with pg_session_factory() as db:
        roles = seed_roles(db)
        u = ensure_local_user(
            db, username=f'pg.badscope.{uuid4().hex[:6]}', display_name='Bad Scope', password=DEMO_USER_PASSWORD
        )
        db.commit()
        user_id = u.id
        role_id = roles[ROLE_FACILITY_ADMIN].id

    with pg_session_factory() as db:
        db.add(UserRoleScope(user_id=user_id, role_id=role_id, scope_type='FACILITY', facility_id=None, active=True))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_postgres_concurrent_duplicate_dispensing_idempotency(pg_session_factory):
    from app.core.auth import _load_human_principal
    from app.main import dispense
    from app.models.core import DispensingTransaction, StockBatch, User
    from app.schemas.prescriptions import DispenseRequest

    fx = _seed_pg_dispense_scenario(pg_session_factory, rx_quantity=15, initial_stock=120)
    shared_idem_key = f'pg-dup-idem-{uuid4().hex}'

    def _worker(_idx: int):
        with pg_session_factory() as db:
            user = db.get(User, fx['user_id'])
            principal = _load_human_principal(db, user, auth_method='local_session')
            req = DispenseRequest(
                pharmacy_id=fx['pharmacy_id'],
                batch_id=fx['batch_id'],
                item_id=fx['item_id'],
                quantity=15,
                credential=fx['otp'],
                idempotency_key=shared_idem_key,
            )
            return dispense(fx['rx_id'], req, db=db, principal=principal)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_worker, range(6)))

    tx_ids = {r['transaction_id'] for r in results}
    assert len(tx_ids) == 1
    assert sum(1 for r in results if not r['replayed']) == 1
    assert sum(1 for r in results if r['replayed']) == 5

    with pg_session_factory() as db:
        tx_rows = db.scalars(
            select(DispensingTransaction).where(DispensingTransaction.prescription_id == fx['rx_id'])
        ).all()
        assert len(tx_rows) == 1
        assert tx_rows[0].actor_user_id == fx['user_id']
        batch = db.get(StockBatch, fx['batch_id'])
        assert batch.quantity_available == 105


def test_postgres_concurrent_competing_dispenses_prevent_overdispense_and_negative_stock(pg_session_factory):
    from fastapi import HTTPException
    from app.core.auth import _load_human_principal
    from app.main import dispense
    from app.models.core import DispensingTransaction, StockBatch, User
    from app.schemas.prescriptions import DispenseRequest

    # Prescription authorizes 15 units, batch has 12 units -> at most two 5-unit dispenses (10 total) can succeed!
    fx = _seed_pg_dispense_scenario(pg_session_factory, rx_quantity=15, initial_stock=12)

    def _worker(idx: int):
        with pg_session_factory() as db:
            user = db.get(User, fx['user_id'])
            principal = _load_human_principal(db, user, auth_method='local_session')
            req = DispenseRequest(
                pharmacy_id=fx['pharmacy_id'],
                batch_id=fx['batch_id'],
                item_id=fx['item_id'],
                quantity=5,
                credential=fx['otp'],
                idempotency_key=f'pg-race-{idx}-{uuid4().hex[:8]}',
            )
            try:
                return ('OK', dispense(fx['rx_id'], req, db=db, principal=principal))
            except HTTPException as exc:
                return ('HTTP', exc.status_code)

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(_worker, range(6)))

    succeeded = [o for o in outcomes if o[0] == 'OK']
    rejected = [o for o in outcomes if o[0] == 'HTTP']
    assert len(succeeded) == 2
    assert len(rejected) == 4
    assert all(code in {401, 409} for _, code in rejected)

    with pg_session_factory() as db:
        tx_rows = db.scalars(
            select(DispensingTransaction).where(DispensingTransaction.prescription_id == fx['rx_id'])
        ).all()
        total_dispensed = sum(t.quantity for t in tx_rows)
        batch = db.get(StockBatch, fx['batch_id'])
        assert total_dispensed == 10
        assert batch.quantity_available == 2
        assert batch.quantity_available >= 0


def test_postgres_dispense_rollback_preserves_atomic_stock_consistency(pg_session_factory, monkeypatch):
    import app.main as main_mod
    from app.core.auth import _load_human_principal
    from app.models.core import DispensingTransaction, StockBatch, StockEvent, User
    from app.schemas.prescriptions import DispenseRequest

    fx = _seed_pg_dispense_scenario(pg_session_factory, rx_quantity=15, initial_stock=50)

    def _boom(*args, **kwargs):
        raise RuntimeError('Simulated mid-transaction failure')

    monkeypatch.setattr(main_mod, 'create_due_stewardship_review', _boom)

    with pg_session_factory() as db:
        user = db.get(User, fx['user_id'])
        principal = _load_human_principal(db, user, auth_method='local_session')
        req = DispenseRequest(
            pharmacy_id=fx['pharmacy_id'],
            batch_id=fx['batch_id'],
            item_id=fx['item_id'],
            quantity=15,
            credential=fx['otp'],
            idempotency_key=f'pg-rollback-{uuid4().hex[:8]}',
        )
        with pytest.raises(RuntimeError):
            main_mod.dispense(fx['rx_id'], req, db=db, principal=principal)
        db.rollback()

    with pg_session_factory() as db:
        assert db.get(StockBatch, fx['batch_id']).quantity_available == 50
        assert db.scalars(select(DispensingTransaction).where(DispensingTransaction.prescription_id == fx['rx_id'])).all() == []
        assert db.scalars(select(StockEvent).where(StockEvent.batch_id == fx['batch_id'])).all() == []
