"""Alembic environment: uses the app's tables and DATABASE_URL."""
from alembic import context
from sqlalchemy import engine_from_config, pool

from app import db
from app.config import get_settings

config = context.config
url = config.get_main_option("sqlalchemy.url") or db.normalize_url(get_settings().database_url or "")
target_metadata = db.Base.metadata


def run_offline():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online():
    connectable = config.attributes.get("connection")
    if connectable is None:
        engine = engine_from_config({"sqlalchemy.url": url}, prefix="sqlalchemy.", poolclass=pool.NullPool)
        with engine.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
