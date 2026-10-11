"""Add facility stewardship review tasks and outcomes."""
from alembic import op
import sqlalchemy as sa

revision = '0005_stewardship_reviews'
down_revision = '0004_rms_stock_event_idempotency'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'stewardship_reviews',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('prescription_id', sa.Integer(), sa.ForeignKey('prescriptions.id'), nullable=False),
        sa.Column('review_type', sa.String(40), nullable=False, server_default='POST_DISPENSE'),
        sa.Column('status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('outcome', sa.String(40), nullable=True),
        sa.Column('reason', sa.String(500), nullable=True),
        sa.Column('reviewer_reference', sa.String(150), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('prescription_id', 'review_type', name='uq_stewardship_review_prescription_type'),
    )
    op.create_index('ix_stewardship_reviews_prescription_id', 'stewardship_reviews', ['prescription_id'])
    op.create_index('ix_stewardship_reviews_status', 'stewardship_reviews', ['status'])


def downgrade():
    op.drop_index('ix_stewardship_reviews_status', table_name='stewardship_reviews')
    op.drop_index('ix_stewardship_reviews_prescription_id', table_name='stewardship_reviews')
    op.drop_table('stewardship_reviews')
