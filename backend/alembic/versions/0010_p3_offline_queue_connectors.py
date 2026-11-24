"""Add P3 offline dispensing queue and EMR connector configuration models.

Revision ID: 0010_p3_offline_queue_connectors
Revises: 0009_p2_stewardship_aware_rules
Create Date: 2026-11-23
"""

from alembic import op
import sqlalchemy as sa

revision = '0010_p3_offline_queue_connectors'
down_revision = '0009_p2_stewardship_aware_rules'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Offline Dispense Queue
    op.create_table(
        'offline_dispense_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bundle_id', sa.String(64), nullable=False, unique=True),
        sa.Column('pharmacy_id', sa.Integer(), sa.ForeignKey('pharmacies.id'), nullable=False),
        sa.Column('device_fingerprint', sa.String(100), nullable=False),
        sa.Column('signature', sa.String(128), nullable=False),
        sa.Column('offline_transaction_id', sa.String(64), nullable=False, unique=True),
        sa.Column('prescription_id', sa.Integer(), sa.ForeignKey('prescriptions.id'), nullable=True),
        sa.Column('prescription_code', sa.String(50), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),  # PENDING, RECONCILED, CONFLICT, REJECTED
        sa.Column('conflict_reason', sa.Text(), nullable=True),
        sa.Column('reconciled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reconciled_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_index('ix_offline_dispense_bundle_id', 'offline_dispense_records', ['bundle_id'])
    op.create_index('ix_offline_dispense_pharmacy_id', 'offline_dispense_records', ['pharmacy_id'])
    op.create_index('ix_offline_dispense_status', 'offline_dispense_records', ['status'])

    # 2. EMR Connector Configuration Registry
    op.create_table(
        'emr_connector_configs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('connector_code', sa.String(50), nullable=False, unique=True),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('emr_system_type', sa.String(50), nullable=False),  # EBUZIMA, OPENMRS, DHIS2, FHIR_R4
        sa.Column('endpoint_url', sa.String(300), nullable=True),
        sa.Column('auth_type', sa.String(50), nullable=False, server_default='HMAC_SHA256'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_index('ix_emr_connector_code', 'emr_connector_configs', ['connector_code'])


def downgrade():
    op.drop_table('emr_connector_configs')
    op.drop_table('offline_dispense_records')
