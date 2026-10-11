"""initial AMRGuard schema

Revision ID: 0001_initial_schema
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('facilities', sa.Column('id',sa.Integer,primary_key=True), sa.Column('code',sa.String(50),nullable=False,unique=True), sa.Column('name',sa.String(200),nullable=False), sa.Column('district',sa.String(100),nullable=False), sa.Column('active',sa.Boolean,nullable=False,server_default=sa.true()))
    op.create_index('ix_facilities_code','facilities',['code'],unique=True)
    op.create_table('pharmacies', sa.Column('id',sa.Integer,primary_key=True), sa.Column('code',sa.String(50),nullable=False,unique=True), sa.Column('name',sa.String(200),nullable=False), sa.Column('district',sa.String(100),nullable=False), sa.Column('active',sa.Boolean,nullable=False,server_default=sa.true()))
    op.create_index('ix_pharmacies_code','pharmacies',['code'],unique=True)
    op.create_table('prescribers', sa.Column('id',sa.Integer,primary_key=True), sa.Column('external_user_id',sa.String(100),nullable=False,unique=True), sa.Column('name',sa.String(200),nullable=False), sa.Column('facility_id',sa.Integer,sa.ForeignKey('facilities.id'),nullable=False), sa.Column('active',sa.Boolean,nullable=False,server_default=sa.true()))
    op.create_index('ix_prescribers_external_user_id','prescribers',['external_user_id'],unique=True)
    op.create_table('antibiotics', sa.Column('id',sa.Integer,primary_key=True), sa.Column('code',sa.String(50),nullable=False,unique=True), sa.Column('generic_name',sa.String(200),nullable=False), sa.Column('strength',sa.String(100),nullable=False), sa.Column('formulation',sa.String(100),nullable=False), sa.Column('route',sa.String(50),nullable=False), sa.Column('active',sa.Boolean,nullable=False,server_default=sa.true()))
    op.create_index('ix_antibiotics_code','antibiotics',['code'],unique=True)
    op.create_table('antibiotic_rules', sa.Column('id',sa.Integer,primary_key=True), sa.Column('antibiotic_id',sa.Integer,sa.ForeignKey('antibiotics.id'),nullable=False), sa.Column('min_dose',sa.Numeric(12,3)), sa.Column('max_dose',sa.Numeric(12,3)), sa.Column('min_duration_days',sa.Integer), sa.Column('max_duration_days',sa.Integer), sa.Column('frequency_per_day_min',sa.Numeric(8,2)), sa.Column('frequency_per_day_max',sa.Numeric(8,2)), sa.Column('enabled',sa.Boolean,nullable=False,server_default=sa.true()), sa.Column('source_reference',sa.Text,nullable=False,server_default='Configured clinical guidance'))
    op.create_index('ix_antibiotic_rules_antibiotic_id','antibiotic_rules',['antibiotic_id'])
    op.create_table('prescriptions', sa.Column('id',sa.Integer,primary_key=True), sa.Column('external_id',sa.String(100),nullable=False,unique=True), sa.Column('patient_reference',sa.String(150),nullable=False), sa.Column('prescriber_id',sa.Integer,sa.ForeignKey('prescribers.id'),nullable=False), sa.Column('facility_id',sa.Integer,sa.ForeignKey('facilities.id'),nullable=False), sa.Column('status',sa.String(30),nullable=False,server_default='CREATED'), sa.Column('created_at',sa.DateTime(timezone=True),nullable=False), sa.Column('expires_at',sa.DateTime(timezone=True)))
    op.create_index('ix_prescriptions_external_id','prescriptions',['external_id'],unique=True); op.create_index('ix_prescriptions_patient_reference','prescriptions',['patient_reference']); op.create_index('ix_prescriptions_status','prescriptions',['status'])
    op.create_table('prescription_items', sa.Column('id',sa.Integer,primary_key=True), sa.Column('prescription_id',sa.Integer,sa.ForeignKey('prescriptions.id'),nullable=False), sa.Column('antibiotic_id',sa.Integer,sa.ForeignKey('antibiotics.id'),nullable=False), sa.Column('dose',sa.Numeric(12,3),nullable=False), sa.Column('frequency_per_day',sa.Numeric(8,2),nullable=False), sa.Column('duration_days',sa.Integer,nullable=False), sa.Column('quantity',sa.Integer,nullable=False), sa.Column('indication',sa.String(300),nullable=False))
    op.create_index('ix_prescription_items_prescription_id','prescription_items',['prescription_id'])
    op.create_table('prescription_credentials', sa.Column('id',sa.Integer,primary_key=True), sa.Column('prescription_id',sa.Integer,sa.ForeignKey('prescriptions.id'),nullable=False,unique=True), sa.Column('otp_hash',sa.String(128),nullable=False), sa.Column('qr_token_hash',sa.String(128),nullable=False,unique=True), sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False), sa.Column('revoked',sa.Boolean,nullable=False,server_default=sa.false()), sa.Column('used_count',sa.Integer,nullable=False,server_default='0'))
    op.create_table('stock_batches', sa.Column('id',sa.Integer,primary_key=True), sa.Column('pharmacy_id',sa.Integer,sa.ForeignKey('pharmacies.id'),nullable=False), sa.Column('antibiotic_id',sa.Integer,sa.ForeignKey('antibiotics.id'),nullable=False), sa.Column('batch_number',sa.String(100),nullable=False), sa.Column('expiry_date',sa.Date,nullable=False), sa.Column('quantity_available',sa.Integer,nullable=False), sa.Column('source_reference',sa.String(150)), sa.UniqueConstraint('pharmacy_id','antibiotic_id','batch_number'))
    op.create_index('ix_stock_batches_pharmacy_id','stock_batches',['pharmacy_id']); op.create_index('ix_stock_batches_batch_number','stock_batches',['batch_number'])
    op.create_table('stock_events', sa.Column('id',sa.Integer,primary_key=True), sa.Column('batch_id',sa.Integer,sa.ForeignKey('stock_batches.id'),nullable=False), sa.Column('event_type',sa.String(50),nullable=False), sa.Column('quantity',sa.Integer,nullable=False), sa.Column('reference_id',sa.String(150)), sa.Column('source_system',sa.String(100),nullable=False), sa.Column('created_at',sa.DateTime(timezone=True),nullable=False), sa.Column('details',sa.Text,nullable=False,server_default='{}'))
    op.create_index('ix_stock_events_batch_id','stock_events',['batch_id'])
    op.create_table('dispensing_transactions', sa.Column('id',sa.Integer,primary_key=True), sa.Column('transaction_id',sa.String(100),nullable=False,unique=True), sa.Column('idempotency_key',sa.String(150),unique=True), sa.Column('prescription_id',sa.Integer,sa.ForeignKey('prescriptions.id'),nullable=False), sa.Column('item_id',sa.Integer,sa.ForeignKey('prescription_items.id')), sa.Column('pharmacy_id',sa.Integer,sa.ForeignKey('pharmacies.id'),nullable=False), sa.Column('batch_id',sa.Integer,sa.ForeignKey('stock_batches.id'),nullable=False), sa.Column('quantity',sa.Integer,nullable=False), sa.Column('status',sa.String(30),nullable=False,server_default='COMPLETED'), sa.Column('payment_reference',sa.String(150)), sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_dispensing_transactions_transaction_id','dispensing_transactions',['transaction_id'],unique=True); op.create_index('ix_dispensing_transactions_idempotency_key','dispensing_transactions',['idempotency_key'],unique=True); op.create_index('ix_dispensing_transactions_prescription_id','dispensing_transactions',['prescription_id'])
    op.create_table('audit_events', sa.Column('id',sa.Integer,primary_key=True), sa.Column('event_type',sa.String(100),nullable=False), sa.Column('entity_type',sa.String(100),nullable=False), sa.Column('entity_id',sa.String(100),nullable=False), sa.Column('source_system',sa.String(100),nullable=False), sa.Column('details',sa.Text,nullable=False,server_default='{}'), sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_audit_events_event_type','audit_events',['event_type'])

def downgrade():
    for table in ['audit_events','dispensing_transactions','stock_events','stock_batches','prescription_credentials','prescription_items','prescriptions','antibiotic_rules','antibiotics','prescribers','pharmacies','facilities']:
        op.drop_table(table)
