import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.extractor import FixtureExtractor  # noqa: E402

SAMPLES = ROOT / "samples"
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def _samples():
    if not (SAMPLES / "misty_hills_munnar_2026-27.pdf").exists():
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_samples.py")], check=True)
    if not (FIXTURES / "misty_hills_munnar_2026-27.json").exists():
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "tests" / "make_fixtures.py")], check=True)


# PostgreSQL only. Default = the database from docker-compose.yml; override with TEST_DATABASE_URL, e.g.
#   TEST_DATABASE_URL=postgresql://postgres@/rates_test?host=/var/tmp/pg&port=5433
TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/rates_test")
_ready = {"url": None}


def admin_url(dbname: str) -> str:
    """The same server as TEST_DB, another database (for tests that need a database of their own)."""
    from sqlalchemy.engine import make_url
    return make_url(db.normalize_url(TEST_DB)).set(database=dbname).render_as_string(hide_password=False)


def fresh_database(name: str) -> str:
    """Create an empty database `name` on the test server and return its URL."""
    from sqlalchemy import create_engine
    eng = create_engine(admin_url("postgres"), isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.exec_driver_sql(f'drop database if exists "{name}" with (force)')
        c.exec_driver_sql(f'create database "{name}"')
    eng.dispose()
    return admin_url(name)


def _truncate_all():
    names = ", ".join(f'"{t.name}"' for t in db.Base.metadata.sorted_tables)
    with db._engine.begin() as c:
        c.exec_driver_sql(f"truncate {names} restart identity cascade")


@pytest.fixture
def session():
    settings = get_settings()
    settings.auto_approve = False
    settings.process_mode = "inline"
    settings.api_key = None
    settings.secret_key = "test-secret-key-for-encryption-123"
    settings.fixtures_dir = None           # demo mode off unless a test turns it on
    settings.cron_secret = None
    settings.google_client_id = settings.google_client_secret = None
    from app import runtime
    runtime.reset_cache()
    # schema built once per run (migrations); each test starts from empty tables
    if db._engine is None or db._engine.url.database != db.make_url_db(TEST_DB):
        db.init_db(TEST_DB, drop=_ready["url"] is None)
        _ready["url"] = TEST_DB
    _truncate_all()
    s = db.SessionLocal()
    yield s
    s.close()


@pytest.fixture
def extractor():
    return FixtureExtractor(FIXTURES)


def sample(name):
    p = SAMPLES / name
    return p.name, p.read_bytes()


ADMIN = {"email": "admin@travelepisodes.test", "name": "Test Admin", "password": "long-test-password-42"}


def signed_in_client(session):
    """A TestClient signed in as an admin, sending the CSRF header like the web app does."""
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app import api, auth
    if not session.scalar(select(db.User).where(db.User.email == ADMIN["email"])):
        auth.create_user(session, **ADMIN)
    c = TestClient(api.app, headers={"X-Requested-With": "test"})
    r = c.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert r.status_code == 200, r.text
    return c
