"""The migrations must build exactly the tables the code expects."""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app import db
from conftest import fresh_database


def test_migrated_schema_matches_models(session):
    engine = session.get_bind()
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": False}), db.Base.metadata)
    assert diff == [], diff
    tables = set(inspect(engine).get_table_names())
    assert {"alembic_version", "users", "user_sessions", "trips", "hotel_rates"} <= tables


def test_existing_database_without_migrations_is_stamped():
    url = fresh_database("rates_test_old")
    from sqlalchemy import create_engine
    old = create_engine(db.normalize_url(url))
    db.Base.metadata.create_all(old)                     # like a database made by an earlier version
    db.init_db(url)                                      # must not fail on "table already exists"
    with db._engine.connect() as conn:
        from pathlib import Path
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        cfg = Config()
        cfg.set_main_option("script_location", str(Path(db.__file__).parent / "migrations"))
        head = ScriptDirectory.from_config(cfg).get_current_head()
        assert conn.exec_driver_sql("select version_num from alembic_version").scalar() == head


def test_supabase_urls_are_made_safe():
    from app.db import is_transaction_pooler, normalize_url
    pooled = "postgresql://postgres.ref:pw@aws-0-ap-south-1.pooler.supabase.com:6543/postgres?pgbouncer=true"
    assert normalize_url(pooled) == ("postgresql+psycopg://postgres.ref:pw@aws-0-ap-south-1.pooler.supabase.com:6543"
                                     "/postgres?sslmode=require")
    assert is_transaction_pooler(pooled)
    direct = "postgres://postgres:pw@db.ref.supabase.co:5432/postgres"
    assert normalize_url(direct).endswith("?sslmode=require") and not is_transaction_pooler(direct)


def test_early_database_missing_new_tables_is_completed():
    """A database from before sign-in / AI usage existed gets those tables, keeping its data."""
    url = fresh_database("rates_test_early")
    from sqlalchemy import create_engine, inspect, text
    old = create_engine(db.normalize_url(url))
    early = [t for n, t in db.Base.metadata.tables.items() if n not in ("users", "user_sessions", "ai_usage")]
    db.Base.metadata.create_all(old, tables=early)
    with old.begin() as c:
        c.execute(text("insert into suppliers (name, name_key) values ('Old DMC', 'old dmc')"))
    db.init_db(url)
    names = set(inspect(db._engine).get_table_names())
    assert {"users", "user_sessions", "ai_usage"} <= names
    with db._engine.connect() as c:
        assert c.execute(text("select name from suppliers")).scalar() == "Old DMC"


def test_supabase_data_api_is_locked(session):
    """On Supabase (detected by its 'anon' role) every app table gets RLS; the app still reads and writes."""
    engine = session.get_bind()
    with engine.begin() as c:
        c.exec_driver_sql("do $$ begin if not exists (select 1 from pg_roles where rolname='anon') "
                          "then create role anon nologin; end if; end $$")
    try:
        changed = db.lock_data_api(engine)
        assert "users" in changed and "user_sessions" in changed and "hotel_rates" in changed
        assert db.lock_data_api(engine) == []                        # idempotent
        info = db.database_info(engine)
        assert info["supabase_roles"] and info["data_api_locked"]
        from app import auth
        auth.create_user(session, "rls@te.in", "RLS", "owner-still-works-1")   # owner bypasses RLS
        from sqlalchemy import select
        assert session.scalar(select(db.User).where(db.User.email == "rls@te.in"))
    finally:
        with engine.begin() as c:
            c.exec_driver_sql("drop role if exists anon")


def test_database_info_never_shows_password(session):
    info = db.database_info(session.get_bind())
    assert "password" not in str(info).lower() and info["schema_version"]


def test_sqlite_is_refused():
    import pytest
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        db.init_db("sqlite:///x.db")
