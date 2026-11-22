"""Add P1 consent architecture and dose-level reminder engine.

Revision ID: 0008_p1_consent_and_dose_reminders
Revises: 0007_p1_catalogue_quarantine_multibatch
Create Date: 2026-11-22
"""

from alembic import op
import sqlalchemy as sa

revision = '0008_p1_consent_and_dose_reminders'
down_revision = '0007_p1_catalogue_quarantine_multibatch'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Explicit Consent Records
    op.create_table(
        'consent_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('patient_reference', sa.String(100), nullable=False),
        sa.Column('purpose', sa.String(50), nullable=False),
        sa.Column('channel', sa.String(30), nullable=False, server_default='SMS'),
        sa.Column('language', sa.String(10), nullable=False, server_default='rw'),
        sa.Column('recipient_phone_hash', sa.String(64), nullable=False),
        sa.Column('recipient_phone_masked', sa.String(30), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='ACTIVE'),
        sa.Column('captured_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('facility_id', sa.Integer(), sa.ForeignKey('facilities.id'), nullable=True),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source_reference', sa.String(150), nullable=True),
        sa.Column('evidence_reference', sa.String(255), nullable=True),
        sa.Column('policy_version', sa.String(50), nullable=False, server_default='v1.0'),
        sa.Column('withdrawn_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('withdrawn_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('withdrawal_reason', sa.String(255), nullable=True),
    )
    op.create_index('ix_consent_records_patient_ref', 'consent_records', ['patient_reference'])
    op.create_index('ix_consent_records_purpose', 'consent_records', ['purpose'])
    op.create_index('ix_consent_records_phone_hash', 'consent_records', ['recipient_phone_hash'])
    op.create_index('ix_consent_records_status', 'consent_records', ['status'])
    op.create_index('ix_consent_records_facility_id', 'consent_records', ['facility_id'])
    op.create_index('ix_consent_records_captured_by', 'consent_records', ['captured_by_user_id'])
    op.create_index('ix_consent_records_withdrawn_by', 'consent_records', ['withdrawn_by_user_id'])

    # 2. Reminder Schedules
    op.create_table(
        'reminder_schedules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('prescription_id', sa.Integer(), sa.ForeignKey('prescriptions.id'), nullable=False),
        sa.Column('prescription_item_id', sa.Integer(), sa.ForeignKey('prescription_items.id'), nullable=True),
        sa.Column('patient_reference', sa.String(100), nullable=False),
        sa.Column('consent_record_id', sa.Integer(), sa.ForeignKey('consent_records.id'), nullable=False),
        sa.Column('timezone', sa.String(50), nullable=False, server_default='Africa/Kigali'),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('daily_times', sa.Text(), nullable=False),
        sa.Column('language', sa.String(10), nullable=False, server_default='rw'),
        sa.Column('status', sa.String(30), nullable=False, server_default='ACTIVE'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancellation_reason', sa.String(255), nullable=True),
    )
    op.create_index('ix_reminder_schedules_prescription_id', 'reminder_schedules', ['prescription_id'])
    op.create_index('ix_reminder_schedules_item_id', 'reminder_schedules', ['prescription_item_id'])
    op.create_index('ix_reminder_schedules_patient_ref', 'reminder_schedules', ['patient_reference'])
    op.create_index('ix_reminder_schedules_consent_id', 'reminder_schedules', ['consent_record_id'])
    op.create_index('ix_reminder_schedules_status', 'reminder_schedules', ['status'])

    # 3. Reminder Occurrences
    op.create_table(
        'reminder_occurrences',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('schedule_id', sa.Integer(), sa.ForeignKey('reminder_schedules.id'), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('dose_number', sa.Integer(), nullable=False),
        sa.Column('total_doses', sa.Integer(), nullable=False),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('suppression_reason', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_reminder_occurrences_schedule_id', 'reminder_occurrences', ['schedule_id'])
    op.create_index('ix_reminder_occurrences_scheduled_at', 'reminder_occurrences', ['scheduled_at'])
    op.create_index('ix_reminder_occurrences_status', 'reminder_occurrences', ['status'])

    # 4. Message Outbox (Leased delivery pattern)
    op.create_table(
        'message_outbox',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('occurrence_id', sa.Integer(), sa.ForeignKey('reminder_occurrences.id'), nullable=True),
        sa.Column('consent_record_id', sa.Integer(), sa.ForeignKey('consent_records.id'), nullable=False),
        sa.Column('destination_hash', sa.String(64), nullable=False),
        sa.Column('destination_masked', sa.String(30), nullable=False),
        sa.Column('message_text', sa.Text(), nullable=False),
        sa.Column('channel', sa.String(30), nullable=False, server_default='SMS'),
        sa.Column('status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('lease_token', sa.String(100), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('provider_message_id', sa.String(150), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
    )
    op.create_index('ix_message_outbox_occurrence_id', 'message_outbox', ['occurrence_id'])
    op.create_index('ix_message_outbox_consent_id', 'message_outbox', ['consent_record_id'])
    op.create_index('ix_message_outbox_dest_hash', 'message_outbox', ['destination_hash'])
    op.create_index('ix_message_outbox_status', 'message_outbox', ['status'])
    op.create_index('ix_message_outbox_next_attempt', 'message_outbox', ['next_attempt_at'])
    op.create_index('ix_message_outbox_lease_token', 'message_outbox', ['lease_token'])
    op.create_index('ix_message_outbox_provider_msg_id', 'message_outbox', ['provider_message_id'])

    # 5. Message Delivery Events (Receipt verification)
    op.create_table(
        'message_delivery_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('outbox_id', sa.Integer(), sa.ForeignKey('message_outbox.id'), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False, server_default='MOCK'),
        sa.Column('provider_message_id', sa.String(150), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('raw_payload', sa.Text(), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_message_delivery_events_outbox_id', 'message_delivery_events', ['outbox_id'])
    op.create_index('ix_message_delivery_events_provider_msg_id', 'message_delivery_events', ['provider_message_id'])
    op.create_index('ix_message_delivery_events_event_type', 'message_delivery_events', ['event_type'])


def downgrade():
    op.drop_table('message_delivery_events')
    op.drop_table('message_outbox')
    op.drop_table('reminder_occurrences')
    op.drop_table('reminder_schedules')
    op.drop_table('consent_records')
