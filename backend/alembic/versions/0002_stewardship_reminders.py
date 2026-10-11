"""Add consent-aware stewardship SMS reminder outbox."""
from alembic import op
import sqlalchemy as sa

revision = '0002_stewardship_reminders'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'stewardship_reminders',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('prescription_id', sa.Integer(), sa.ForeignKey('prescriptions.id'), nullable=False, unique=True),
        sa.Column('phone_number', sa.String(length=20), nullable=False),
        sa.Column('consent_recorded', sa.Boolean(), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='PENDING_PROVIDER'),
        sa.Column('provider_reference', sa.String(length=150)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_stewardship_reminders_prescription_id', 'stewardship_reminders', ['prescription_id'], unique=True)


def downgrade():
    op.drop_index('ix_stewardship_reminders_prescription_id', table_name='stewardship_reminders')
    op.drop_table('stewardship_reminders')