from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, inspect, pool, text
from app.core.config import settings
from app.db.session import Base
from app.models import core  # noqa: F401

config = context.config
config.set_main_option('sqlalchemy.url', settings.database_url.replace('%', '%%'))
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def _ensure_wide_alembic_version_column(connection) -> None:
    """Ensure alembic_version.version_num supports revision IDs longer than 32 chars on PostgreSQL.

    Historical migration `0003_remove_plaintext_reminder_phone` is 36 characters, which exceeds
    Alembic's default VARCHAR(32) on PostgreSQL. Creating/widening the column to VARCHAR(128)
    preserves existing revision IDs without modifying historical migrations.
    """
    if connection.dialect.name != 'postgresql':
        return
    inspector = inspect(connection)
    if not inspector.has_table('alembic_version'):
        connection.execute(
            text(
                'CREATE TABLE alembic_version ('
                'version_num VARCHAR(128) NOT NULL, '
                'CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)'
                ')'
            )
        )
    else:
        connection.execute(text('ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)'))


def run_migrations_offline():
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _ensure_wide_alembic_version_column(connection)
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
