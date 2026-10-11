"""Make external stock movement references idempotent."""
from alembic import op
import sqlalchemy as sa

revision = '0004_rms_stock_event_idempotency'
down_revision = '0003_remove_plaintext_reminder_phone'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'uq_stock_events_source_reference',
        'stock_events',
        ['source_system', 'reference_id'],
        unique=True,
        postgresql_where=sa.text('reference_id IS NOT NULL'),
        sqlite_where=sa.text('reference_id IS NOT NULL'),
    )


def downgrade():
    op.drop_index('uq_stock_events_source_reference', table_name='stock_events')