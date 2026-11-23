"""Add P2 stewardship metric dictionary, WHO AWaRe classification, and governed clinical rules engine.

Revision ID: 0009_p2_stewardship_aware_rules
Revises: 0008_p1_consent_and_dose_reminders
Create Date: 2026-11-23
"""

from alembic import op
import sqlalchemy as sa

revision = '0009_p2_stewardship_aware_rules'
down_revision = '0008_p1_consent_and_dose_reminders'
branch_labels = None
depends_on = None


def upgrade():
    # 1. WHO AWaRe Classifications
    op.create_table(
        'who_aware_classifications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('antibiotic_code', sa.String(50), nullable=False, unique=True),
        sa.Column('generic_name', sa.String(200), nullable=False),
        sa.Column('category', sa.String(20), nullable=False),  # ACCESS, WATCH, RESERVE, DISCOURAGED
        sa.Column('atc_code', sa.String(20), nullable=True),
        sa.Column('version', sa.String(30), nullable=False, server_default='WHO_2023_V1'),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('clinical_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_index('ix_who_aware_antibiotic_code', 'who_aware_classifications', ['antibiotic_code'])
    op.create_index('ix_who_aware_category', 'who_aware_classifications', ['category'])

    # 2. Metric Definitions (Stewardship KPI Dictionary)
    op.create_table(
        'metric_definitions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('metric_code', sa.String(60), nullable=False, unique=True),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('numerator_definition', sa.Text(), nullable=False),
        sa.Column('denominator_definition', sa.Text(), nullable=False),
        sa.Column('calculation_formula', sa.Text(), nullable=False),
        sa.Column('target_benchmark', sa.String(50), nullable=True),
        sa.Column('minimum_cell_threshold', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('version', sa.String(20), nullable=False, server_default='1.0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_index('ix_metric_definitions_code', 'metric_definitions', ['metric_code'])
    op.create_index('ix_metric_definitions_category', 'metric_definitions', ['category'])

    # 3. Governed Stewardship Rules
    op.create_table(
        'stewardship_rules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('rule_code', sa.String(60), nullable=False, unique=True),
        sa.Column('title', sa.String(150), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),  # DOSAGE, DURATION, AWARE_RESTRICTION, INDICATION_MISMATCH
        sa.Column('severity', sa.String(20), nullable=False, server_default='WARNING'),  # WARNING, BLOCK, REVIEW_REQUIRED
        sa.Column('antibiotic_id', sa.Integer(), sa.ForeignKey('antibiotics.id'), nullable=True),
        sa.Column('aware_category', sa.String(20), nullable=True),
        sa.Column('max_duration_days', sa.Integer(), nullable=True),
        sa.Column('max_daily_dose', sa.Numeric(12, 3), nullable=True),
        sa.Column('requires_specialist_approval', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(20), nullable=False, server_default='ACTIVE'),  # ACTIVE, DRAFT, SUPERSEDED, REVOKED
        sa.Column('effective_start_date', sa.Date(), nullable=False),
        sa.Column('effective_end_date', sa.Date(), nullable=True),
        sa.Column('approved_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('clinical_rationale', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_index('ix_stewardship_rules_code', 'stewardship_rules', ['rule_code'])
    op.create_index('ix_stewardship_rules_status', 'stewardship_rules', ['status'])

    # 4. Structured Stewardship Alerts & Dispositions
    op.create_table(
        'stewardship_alerts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('alert_id', sa.String(60), nullable=False, unique=True),
        sa.Column('prescription_id', sa.Integer(), sa.ForeignKey('prescriptions.id'), nullable=False),
        sa.Column('prescription_item_id', sa.Integer(), sa.ForeignKey('prescription_items.id'), nullable=True),
        sa.Column('rule_id', sa.Integer(), sa.ForeignKey('stewardship_rules.id'), nullable=False),
        sa.Column('rule_code', sa.String(60), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('clinical_evidence', sa.Text(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='OPEN'),  # OPEN, ACKNOWLEDGED, OVERRIDDEN, RESOLVED, FALSE_POSITIVE
        sa.Column('disposition_outcome', sa.String(40), nullable=True),  # ACCEPTED, MODIFIED, OVERRIDDEN_WITH_REASON, FALSE_POSITIVE_FLAGGED
        sa.Column('disposition_reason', sa.Text(), nullable=True),
        sa.Column('disposition_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('disposition_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_index('ix_stewardship_alerts_rx', 'stewardship_alerts', ['prescription_id'])
    op.create_index('ix_stewardship_alerts_status', 'stewardship_alerts', ['status'])


def downgrade():
    op.drop_table('stewardship_alerts')
    op.drop_table('stewardship_rules')
    op.drop_table('metric_definitions')
    op.drop_table('who_aware_classifications')
