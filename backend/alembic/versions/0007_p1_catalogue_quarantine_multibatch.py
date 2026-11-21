"""Add P1 approved catalogue, unknown-code quarantine, formulation models, item-level dispensing, and outbox."""

from alembic import op
import sqlalchemy as sa

revision = '0007_p1_catalogue_quarantine_multibatch'
down_revision = '0006_p0_security_rbac_audit'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Approved Catalogue & Formulations
    op.create_table(
        'medicine_concepts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('coding_system', sa.String(100), nullable=False),
        sa.Column('code', sa.String(100), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('aware_category', sa.String(50), nullable=False, server_default='ACCESS'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_medicine_concepts_system_code', 'medicine_concepts', ['coding_system', 'code'], unique=True)
    op.create_index('ix_medicine_concepts_code', 'medicine_concepts', ['code'])

    op.create_table(
        'formulations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('medicine_concept_id', sa.Integer(), sa.ForeignKey('medicine_concepts.id'), nullable=False),
        sa.Column('strength_value', sa.Numeric(12, 3), nullable=False),
        sa.Column('strength_unit', sa.String(50), nullable=False),
        sa.Column('dose_form', sa.String(100), nullable=False),
        sa.Column('route', sa.String(50), nullable=False),
        sa.Column('units_per_pack', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('unit_of_measure', sa.String(50), nullable=False, server_default='unit'),
        sa.Column('liquid_concentration_mg_per_ml', sa.Numeric(12, 3), nullable=True),
        sa.Column('is_divisible', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_formulations_concept_id', 'formulations', ['medicine_concept_id'])

    op.create_table(
        'medicine_mappings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source_system', sa.String(100), nullable=False),
        sa.Column('source_code', sa.String(100), nullable=False),
        sa.Column('source_description', sa.String(255), nullable=True),
        sa.Column('medicine_concept_id', sa.Integer(), sa.ForeignKey('medicine_concepts.id'), nullable=False),
        sa.Column('formulation_id', sa.Integer(), sa.ForeignKey('formulations.id'), nullable=True),
        sa.Column('approval_status', sa.String(50), nullable=False, server_default='PENDING'),
        sa.Column('approved_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('uq_medicine_mappings_source_code', 'medicine_mappings', ['source_system', 'source_code'], unique=True)
    op.create_index('ix_medicine_mappings_concept_id', 'medicine_mappings', ['medicine_concept_id'])

    # 2. Integration Inbox / Quarantine Queue
    op.create_table(
        'integration_inbox',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source_system', sa.String(100), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('external_id', sa.String(150), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('quarantine_reason', sa.String(150), nullable=False),
        sa.Column('unresolved_code', sa.String(150), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='QUARANTINED'),
        sa.Column('facility_id', sa.Integer(), sa.ForeignKey('facilities.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
    )
    op.create_index('ix_integration_inbox_status', 'integration_inbox', ['status'])
    op.create_index('ix_integration_inbox_source_external', 'integration_inbox', ['source_system', 'external_id'])

    # 3. Alter PrescriptionItem for formulation-aware dosage model
    with op.batch_alter_table('prescription_items') as batch:
        batch.add_column(sa.Column('formulation_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('dose_unit', sa.String(50), nullable=True))
        batch.add_column(sa.Column('is_prn', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('prn_reason', sa.String(255), nullable=True))
        batch.add_column(sa.Column('instructions', sa.Text(), nullable=True))
        batch.add_column(sa.Column('conversion_review_required', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key('fk_prescription_items_formulation_id', 'formulations', ['formulation_id'], ['id'])
        batch.create_index('ix_prescription_items_formulation_id', ['formulation_id'])

    # 4. Item-Level Dispensing & Multi-Batch Links
    op.create_table(
        'dispensing_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('transaction_id', sa.Integer(), sa.ForeignKey('dispensing_transactions.id'), nullable=False),
        sa.Column('prescription_item_id', sa.Integer(), sa.ForeignKey('prescription_items.id'), nullable=False),
        sa.Column('quantity_requested', sa.Integer(), nullable=False),
        sa.Column('quantity_dispensed', sa.Integer(), nullable=False),
        sa.Column('fulfillment_status', sa.String(50), nullable=False, server_default='FULL'),
        sa.Column('refusal_reason', sa.String(255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_dispensing_items_transaction_id', 'dispensing_items', ['transaction_id'])
    op.create_index('ix_dispensing_items_item_id', 'dispensing_items', ['prescription_item_id'])

    op.create_table(
        'dispensing_batch_links',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('dispensing_item_id', sa.Integer(), sa.ForeignKey('dispensing_items.id'), nullable=False),
        sa.Column('batch_id', sa.Integer(), sa.ForeignKey('stock_batches.id'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_dispensing_batch_links_item_id', 'dispensing_batch_links', ['dispensing_item_id'])
    op.create_index('ix_dispensing_batch_links_batch_id', 'dispensing_batch_links', ['batch_id'])

    with op.batch_alter_table('dispensing_transactions') as batch:
        batch.add_column(sa.Column('reconciliation_status', sa.String(50), nullable=False, server_default='PENDING_RECONCILIATION'))
        batch.create_index('ix_dispensing_transactions_recon_status', ['reconciliation_status'])

    # 5. Integration Outbox
    op.create_table(
        'integration_outbox',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('destination_system', sa.String(100), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('aggregate_type', sa.String(100), nullable=False),
        sa.Column('aggregate_id', sa.String(150), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='PENDING'),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_integration_outbox_status', 'integration_outbox', ['status'])
    op.create_index('ix_integration_outbox_dest_status', 'integration_outbox', ['destination_system', 'status'])


def downgrade():
    op.drop_table('integration_outbox')

    with op.batch_alter_table('dispensing_transactions') as batch:
        batch.drop_index('ix_dispensing_transactions_recon_status')
        batch.drop_column('reconciliation_status')

    op.drop_table('dispensing_batch_links')
    op.drop_table('dispensing_items')

    with op.batch_alter_table('prescription_items') as batch:
        batch.drop_index('ix_prescription_items_formulation_id')
        batch.drop_constraint('fk_prescription_items_formulation_id', type_='foreignkey')
        batch.drop_column('conversion_review_required')
        batch.drop_column('instructions')
        batch.drop_column('prn_reason')
        batch.drop_column('is_prn')
        batch.drop_column('dose_unit')
        batch.drop_column('formulation_id')

    op.drop_table('integration_inbox')
    op.drop_table('medicine_mappings')
    op.drop_table('formulations')
    op.drop_table('medicine_concepts')
