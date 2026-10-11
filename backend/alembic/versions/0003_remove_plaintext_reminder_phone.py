"""Remove plaintext reminder destinations and retain consent evidence."""
from alembic import op
import sqlalchemy as sa

revision = '0003_remove_plaintext_reminder_phone'
down_revision = '0002_stewardship_reminders'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('stewardship_reminders') as batch:
        batch.drop_column('phone_number')
        batch.add_column(sa.Column('consent_reference', sa.String(length=150), nullable=True))
        batch.add_column(sa.Column('consent_recorded_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    raise RuntimeError('Downgrade is intentionally disabled because it would reintroduce plaintext phone storage')