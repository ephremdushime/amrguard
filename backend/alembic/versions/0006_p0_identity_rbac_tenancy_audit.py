"""Add P0 identity, RBAC, tenancy, pharmacy networks, scoped service clients, and append-only audit controls."""
from alembic import op
import sqlalchemy as sa

revision = '0006_p0_security_rbac_audit'
down_revision = '0005_stewardship_reviews'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'organizations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_organizations_code', 'organizations', ['code'], unique=True)

    with op.batch_alter_table('facilities') as batch:
        batch.add_column(sa.Column('organization_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_facilities_organization_id', 'organizations', ['organization_id'], ['id'])
        batch.create_index('ix_facilities_organization_id', ['organization_id'])

    with op.batch_alter_table('pharmacies') as batch:
        batch.add_column(sa.Column('organization_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('facility_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('pharmacy_type', sa.String(30), nullable=False, server_default='FACILITY_PHARMACY'))
        batch.create_foreign_key('fk_pharmacies_organization_id', 'organizations', ['organization_id'], ['id'])
        batch.create_foreign_key('fk_pharmacies_facility_id', 'facilities', ['facility_id'], ['id'])
        batch.create_index('ix_pharmacies_organization_id', ['organization_id'])
        batch.create_index('ix_pharmacies_facility_id', ['facility_id'])

    op.create_table(
        'pharmacy_networks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_pharmacy_networks_code', 'pharmacy_networks', ['code'], unique=True)

    op.create_table(
        'pharmacy_network_facilities',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('network_id', sa.Integer(), sa.ForeignKey('pharmacy_networks.id'), nullable=False),
        sa.Column('facility_id', sa.Integer(), sa.ForeignKey('facilities.id'), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('network_id', 'facility_id', name='uq_pharmacy_network_facility'),
    )
    op.create_index('ix_pharmacy_network_facilities_network_id', 'pharmacy_network_facilities', ['network_id'])
    op.create_index('ix_pharmacy_network_facilities_facility_id', 'pharmacy_network_facilities', ['facility_id'])

    op.create_table(
        'pharmacy_network_pharmacies',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('network_id', sa.Integer(), sa.ForeignKey('pharmacy_networks.id'), nullable=False),
        sa.Column('pharmacy_id', sa.Integer(), sa.ForeignKey('pharmacies.id'), nullable=False),
        sa.Column('allow_all_medicines', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('network_id', 'pharmacy_id', name='uq_pharmacy_network_pharmacy'),
    )
    op.create_index('ix_pharmacy_network_pharmacies_network_id', 'pharmacy_network_pharmacies', ['network_id'])
    op.create_index('ix_pharmacy_network_pharmacies_pharmacy_id', 'pharmacy_network_pharmacies', ['pharmacy_id'])

    op.create_table(
        'pharmacy_network_medicine_permissions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('network_id', sa.Integer(), sa.ForeignKey('pharmacy_networks.id'), nullable=False),
        sa.Column('pharmacy_id', sa.Integer(), sa.ForeignKey('pharmacies.id'), nullable=False),
        sa.Column('antibiotic_code', sa.String(50), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('network_id', 'pharmacy_id', 'antibiotic_code', name='uq_pharmacy_network_medicine_perm'),
    )
    op.create_index('ix_pharmacy_network_medicine_permissions_network_id', 'pharmacy_network_medicine_permissions', ['network_id'])
    op.create_index('ix_pharmacy_network_medicine_permissions_pharmacy_id', 'pharmacy_network_medicine_permissions', ['pharmacy_id'])
    op.create_index('ix_pharmacy_network_medicine_permissions_antibiotic_code', 'pharmacy_network_medicine_permissions', ['antibiotic_code'])

    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('identity_issuer', sa.String(255), nullable=False),
        sa.Column('identity_subject', sa.String(255), nullable=False),
        sa.Column('username', sa.String(150), nullable=False),
        sa.Column('display_name', sa.String(200), nullable=False),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('password_hash', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('failed_login_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('identity_issuer', 'identity_subject', name='uq_users_issuer_subject'),
    )
    op.create_index('ix_users_username', 'users', ['username'], unique=True)

    op.create_table(
        'roles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('description', sa.String(300), nullable=False),
    )
    op.create_index('ix_roles_code', 'roles', ['code'], unique=True)

    op.create_table(
        'user_role_scopes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('role_id', sa.Integer(), sa.ForeignKey('roles.id'), nullable=False),
        sa.Column('scope_type', sa.String(30), nullable=False),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=True),
        sa.Column('facility_id', sa.Integer(), sa.ForeignKey('facilities.id'), nullable=True),
        sa.Column('pharmacy_id', sa.Integer(), sa.ForeignKey('pharmacies.id'), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('granted_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(scope_type = 'PHARMACY' AND pharmacy_id IS NOT NULL AND facility_id IS NULL AND organization_id IS NULL) OR "
            "(scope_type = 'FACILITY' AND facility_id IS NOT NULL AND pharmacy_id IS NULL AND organization_id IS NULL) OR "
            "(scope_type = 'ORGANIZATION' AND organization_id IS NOT NULL AND facility_id IS NULL AND pharmacy_id IS NULL) OR "
            "(scope_type IN ('NATIONAL_AGGREGATE', 'PLATFORM') AND organization_id IS NULL AND facility_id IS NULL AND pharmacy_id IS NULL)",
            name='ck_user_role_scopes_explicit_scope',
        ),
    )
    op.create_index('ix_user_role_scopes_user_id', 'user_role_scopes', ['user_id'])
    op.create_index('ix_user_role_scopes_role_id', 'user_role_scopes', ['role_id'])
    op.create_index('ix_user_role_scopes_scope_type', 'user_role_scopes', ['scope_type'])
    op.create_index('ix_user_role_scopes_organization_id', 'user_role_scopes', ['organization_id'])
    op.create_index('ix_user_role_scopes_facility_id', 'user_role_scopes', ['facility_id'])
    op.create_index('ix_user_role_scopes_pharmacy_id', 'user_role_scopes', ['pharmacy_id'])

    op.create_table(
        'user_sessions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('token_hash', sa.String(128), nullable=False),
        sa.Column('csrf_token_hash', sa.String(128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('absolute_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ip_address_truncated', sa.String(64), nullable=True),
        sa.Column('user_agent_hash', sa.String(128), nullable=True),
    )
    op.create_index('ix_user_sessions_user_id', 'user_sessions', ['user_id'])
    op.create_index('ix_user_sessions_token_hash', 'user_sessions', ['token_hash'], unique=True)

    op.create_table(
        'service_clients',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('client_code', sa.String(100), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('partner_type', sa.String(50), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_service_clients_client_code', 'service_clients', ['client_code'], unique=True)

    op.create_table(
        'service_client_scopes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('service_client_id', sa.Integer(), sa.ForeignKey('service_clients.id'), nullable=False),
        sa.Column('scope', sa.String(100), nullable=False),
        sa.Column('facility_id', sa.Integer(), sa.ForeignKey('facilities.id'), nullable=True),
        sa.Column('pharmacy_id', sa.Integer(), sa.ForeignKey('pharmacies.id'), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index('ix_service_client_scopes_service_client_id', 'service_client_scopes', ['service_client_id'])
    op.create_index('ix_service_client_scopes_scope', 'service_client_scopes', ['scope'])
    op.create_index('ix_service_client_scopes_facility_id', 'service_client_scopes', ['facility_id'])
    op.create_index('ix_service_client_scopes_pharmacy_id', 'service_client_scopes', ['pharmacy_id'])

    op.create_table(
        'service_client_credentials',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('service_client_id', sa.Integer(), sa.ForeignKey('service_clients.id'), nullable=False),
        sa.Column('key_prefix', sa.String(32), nullable=False),
        sa.Column('secret_hash', sa.String(128), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_service_client_credentials_service_client_id', 'service_client_credentials', ['service_client_id'])
    op.create_index('ix_service_client_credentials_key_prefix', 'service_client_credentials', ['key_prefix'], unique=True)

    with op.batch_alter_table('prescriptions') as batch:
        batch.add_column(sa.Column('allow_external_dispensing', sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table('prescription_credentials') as batch:
        batch.add_column(sa.Column('token_salt', sa.String(64), nullable=True))
        batch.add_column(sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('issued_by_user_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('intended_pharmacy_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('revoked_by_user_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_prescription_credentials_issued_by_user_id', 'users', ['issued_by_user_id'], ['id'])
        batch.create_foreign_key('fk_prescription_credentials_intended_pharmacy_id', 'pharmacies', ['intended_pharmacy_id'], ['id'])
        batch.create_foreign_key('fk_prescription_credentials_revoked_by_user_id', 'users', ['revoked_by_user_id'], ['id'])
        batch.create_index('ix_prescription_credentials_otp_hash', ['otp_hash'])

    with op.batch_alter_table('dispensing_transactions') as batch:
        batch.add_column(sa.Column('actor_user_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('prescribing_facility_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('dispensing_facility_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('is_cross_facility', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key('fk_dispensing_transactions_actor_user_id', 'users', ['actor_user_id'], ['id'])
        batch.create_foreign_key('fk_dispensing_transactions_prescribing_facility_id', 'facilities', ['prescribing_facility_id'], ['id'])
        batch.create_foreign_key('fk_dispensing_transactions_dispensing_facility_id', 'facilities', ['dispensing_facility_id'], ['id'])
        batch.create_index('ix_dispensing_transactions_actor_user_id', ['actor_user_id'])
        batch.create_index('ix_dispensing_transactions_prescribing_facility_id', ['prescribing_facility_id'])
        batch.create_index('ix_dispensing_transactions_dispensing_facility_id', ['dispensing_facility_id'])

    with op.batch_alter_table('stewardship_reviews') as batch:
        batch.add_column(sa.Column('reviewer_user_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_stewardship_reviews_reviewer_user_id', 'users', ['reviewer_user_id'], ['id'])
        batch.create_index('ix_stewardship_reviews_reviewer_user_id', ['reviewer_user_id'])

    with op.batch_alter_table('audit_events') as batch:
        batch.add_column(sa.Column('actor_type', sa.String(30), nullable=False, server_default='SYSTEM'))
        batch.add_column(sa.Column('actor_id', sa.String(150), nullable=True))
        batch.add_column(sa.Column('facility_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('pharmacy_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('correlation_id', sa.String(100), nullable=True))
        batch.add_column(sa.Column('outcome', sa.String(30), nullable=False, server_default='SUCCESS'))
        batch.create_foreign_key('fk_audit_events_facility_id', 'facilities', ['facility_id'], ['id'])
        batch.create_foreign_key('fk_audit_events_pharmacy_id', 'pharmacies', ['pharmacy_id'], ['id'])
        batch.create_index('ix_audit_events_actor_type', ['actor_type'])
        batch.create_index('ix_audit_events_actor_id', ['actor_id'])
        batch.create_index('ix_audit_events_facility_id', ['facility_id'])
        batch.create_index('ix_audit_events_pharmacy_id', ['pharmacy_id'])
        batch.create_index('ix_audit_events_correlation_id', ['correlation_id'])
        batch.create_index('ix_audit_events_outcome', ['outcome'])

    if op.get_bind().dialect.name == 'postgresql':
        op.execute(
            """
            CREATE OR REPLACE FUNCTION prevent_audit_events_modification()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'audit_events records are append-only and cannot be modified or deleted';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW
            EXECUTE FUNCTION prevent_audit_events_modification();
            """
        )


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events;')
        op.execute('DROP FUNCTION IF EXISTS prevent_audit_events_modification();')

    with op.batch_alter_table('audit_events') as batch:
        batch.drop_index('ix_audit_events_outcome')
        batch.drop_index('ix_audit_events_correlation_id')
        batch.drop_index('ix_audit_events_pharmacy_id')
        batch.drop_index('ix_audit_events_facility_id')
        batch.drop_index('ix_audit_events_actor_id')
        batch.drop_index('ix_audit_events_actor_type')
        batch.drop_constraint('fk_audit_events_pharmacy_id', type_='foreignkey')
        batch.drop_constraint('fk_audit_events_facility_id', type_='foreignkey')
        batch.drop_column('outcome')
        batch.drop_column('correlation_id')
        batch.drop_column('pharmacy_id')
        batch.drop_column('facility_id')
        batch.drop_column('actor_id')
        batch.drop_column('actor_type')

    with op.batch_alter_table('stewardship_reviews') as batch:
        batch.drop_index('ix_stewardship_reviews_reviewer_user_id')
        batch.drop_constraint('fk_stewardship_reviews_reviewer_user_id', type_='foreignkey')
        batch.drop_column('reviewer_user_id')

    with op.batch_alter_table('dispensing_transactions') as batch:
        batch.drop_index('ix_dispensing_transactions_dispensing_facility_id')
        batch.drop_index('ix_dispensing_transactions_prescribing_facility_id')
        batch.drop_index('ix_dispensing_transactions_actor_user_id')
        batch.drop_constraint('fk_dispensing_transactions_dispensing_facility_id', type_='foreignkey')
        batch.drop_constraint('fk_dispensing_transactions_prescribing_facility_id', type_='foreignkey')
        batch.drop_constraint('fk_dispensing_transactions_actor_user_id', type_='foreignkey')
        batch.drop_column('is_cross_facility')
        batch.drop_column('dispensing_facility_id')
        batch.drop_column('prescribing_facility_id')
        batch.drop_column('actor_user_id')

    with op.batch_alter_table('prescription_credentials') as batch:
        batch.drop_index('ix_prescription_credentials_otp_hash')
        batch.drop_constraint('fk_prescription_credentials_revoked_by_user_id', type_='foreignkey')
        batch.drop_constraint('fk_prescription_credentials_intended_pharmacy_id', type_='foreignkey')
        batch.drop_constraint('fk_prescription_credentials_issued_by_user_id', type_='foreignkey')
        batch.drop_column('revoked_by_user_id')
        batch.drop_column('revoked_at')
        batch.drop_column('intended_pharmacy_id')
        batch.drop_column('issued_at')
        batch.drop_column('issued_by_user_id')
        batch.drop_column('failed_attempts')
        batch.drop_column('token_salt')

    with op.batch_alter_table('prescriptions') as batch:
        batch.drop_column('allow_external_dispensing')

    op.drop_index('ix_service_client_credentials_key_prefix', table_name='service_client_credentials')
    op.drop_index('ix_service_client_credentials_service_client_id', table_name='service_client_credentials')
    op.drop_table('service_client_credentials')

    op.drop_index('ix_service_client_scopes_pharmacy_id', table_name='service_client_scopes')
    op.drop_index('ix_service_client_scopes_facility_id', table_name='service_client_scopes')
    op.drop_index('ix_service_client_scopes_scope', table_name='service_client_scopes')
    op.drop_index('ix_service_client_scopes_service_client_id', table_name='service_client_scopes')
    op.drop_table('service_client_scopes')

    op.drop_index('ix_service_clients_client_code', table_name='service_clients')
    op.drop_table('service_clients')

    op.drop_index('ix_user_sessions_token_hash', table_name='user_sessions')
    op.drop_index('ix_user_sessions_user_id', table_name='user_sessions')
    op.drop_table('user_sessions')

    op.drop_index('ix_user_role_scopes_pharmacy_id', table_name='user_role_scopes')
    op.drop_index('ix_user_role_scopes_facility_id', table_name='user_role_scopes')
    op.drop_index('ix_user_role_scopes_organization_id', table_name='user_role_scopes')
    op.drop_index('ix_user_role_scopes_scope_type', table_name='user_role_scopes')
    op.drop_index('ix_user_role_scopes_role_id', table_name='user_role_scopes')
    op.drop_index('ix_user_role_scopes_user_id', table_name='user_role_scopes')
    op.drop_table('user_role_scopes')

    op.drop_index('ix_roles_code', table_name='roles')
    op.drop_table('roles')

    op.drop_index('ix_users_username', table_name='users')
    op.drop_table('users')

    op.drop_index('ix_pharmacy_network_medicine_permissions_antibiotic_code', table_name='pharmacy_network_medicine_permissions')
    op.drop_index('ix_pharmacy_network_medicine_permissions_pharmacy_id', table_name='pharmacy_network_medicine_permissions')
    op.drop_index('ix_pharmacy_network_medicine_permissions_network_id', table_name='pharmacy_network_medicine_permissions')
    op.drop_table('pharmacy_network_medicine_permissions')

    op.drop_index('ix_pharmacy_network_pharmacies_pharmacy_id', table_name='pharmacy_network_pharmacies')
    op.drop_index('ix_pharmacy_network_pharmacies_network_id', table_name='pharmacy_network_pharmacies')
    op.drop_table('pharmacy_network_pharmacies')

    op.drop_index('ix_pharmacy_network_facilities_facility_id', table_name='pharmacy_network_facilities')
    op.drop_index('ix_pharmacy_network_facilities_network_id', table_name='pharmacy_network_facilities')
    op.drop_table('pharmacy_network_facilities')

    op.drop_index('ix_pharmacy_networks_code', table_name='pharmacy_networks')
    op.drop_table('pharmacy_networks')

    with op.batch_alter_table('pharmacies') as batch:
        batch.drop_index('ix_pharmacies_facility_id')
        batch.drop_index('ix_pharmacies_organization_id')
        batch.drop_constraint('fk_pharmacies_facility_id', type_='foreignkey')
        batch.drop_constraint('fk_pharmacies_organization_id', type_='foreignkey')
        batch.drop_column('pharmacy_type')
        batch.drop_column('facility_id')
        batch.drop_column('organization_id')

    with op.batch_alter_table('facilities') as batch:
        batch.drop_index('ix_facilities_organization_id')
        batch.drop_constraint('fk_facilities_organization_id', type_='foreignkey')
        batch.drop_column('organization_id')

    op.drop_index('ix_organizations_code', table_name='organizations')
    op.drop_table('organizations')
