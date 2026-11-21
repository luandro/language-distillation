"""PostgreSQL availability and connection fixtures for the test suite."""

import functools
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url

from langpipe.storage.db.engine import make_engine
from langpipe.storage.db.repository import PostgresRepository
from langpipe.storage.db.tables import Base

TEST_DB_URL = os.environ.get(
    "LANGPIPE_TEST_DATABASE_URL",
    "postgresql+psycopg://langpipe:langpipe@localhost:55432/langpipe_test",
)
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
REQUIRE_POSTGRES_ENV = "LANGPIPE_REQUIRE_POSTGRES"
# Query parameters that can override the database name or point libpq elsewhere.
_DATABASE_OVERRIDE_KEYS = ("dbname", "database", "service")
# Test ids of every skipped item in this process; checked once at session end.
_skipped_nodeids: list[str] = []


def _libpq_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def postgres_required() -> bool:
    """True in required CI runs: PostgreSQL must be reachable and no test may skip."""
    return os.environ.get(REQUIRE_POSTGRES_ENV) == "1"


@functools.cache
def pg_available() -> bool:
    try:
        with psycopg.connect(_libpq_url(TEST_DB_URL), connect_timeout=2):
            return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def pg_url() -> str:
    if not pg_available():
        message = "PostgreSQL unreachable; run `docker compose up -d db`"
        if postgres_required():
            pytest.fail(f"{message} (LANGPIPE_REQUIRE_POSTGRES=1)", pytrace=False)
        pytest.skip(message)
    return TEST_DB_URL


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.skipped:
        _skipped_nodeids.append(report.nodeid)


def pytest_collectreport(report: pytest.CollectReport) -> None:
    if report.skipped:
        _skipped_nodeids.append(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not postgres_required() or not _skipped_nodeids:
        return
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
    print(
        f"LANGPIPE_REQUIRE_POSTGRES=1 forbids skipped tests; {len(_skipped_nodeids)} skipped: "
        + ", ".join(_skipped_nodeids[:10]),
        file=sys.stderr,
    )


def alembic_config(url: str) -> Config:
    """Alembic config bound to `url`; env.py prefers `config.attributes["url"]`."""
    config = Config(str(ALEMBIC_INI))
    config.attributes["url"] = url
    return config


def _require_test_database(url: str) -> None:
    """Refuse to migrate or truncate anything but a parsed database named *_test."""
    try:
        parsed = make_url(url)
    except Exception:
        parsed = None
    if (
        parsed is None
        or not (parsed.database or "").endswith("_test")
        or any(key in parsed.query for key in _DATABASE_OVERRIDE_KEYS)
    ):
        raise RuntimeError("migrations and cleanup in tests only run on a database named *_test")


@pytest.fixture(scope="session")
def migrated_engine(pg_url: str) -> Iterator[Engine]:
    # Ordinary runs upgrade to head without first tearing the schema down: a populated database
    # already at head must stay usable (0002 refuses a downgrade while M2 artifact rows exist).
    # Destructive downgrade/roundtrip exercises live in tests/integration/test_migrations.py and
    # start from the isolated, empty state that `clean_db` provides.
    _require_test_database(pg_url)
    config = alembic_config(pg_url)
    command.upgrade(config, "head")
    engine = make_engine(pg_url)
    yield engine
    engine.dispose()


@pytest.fixture
def clean_db(migrated_engine: Engine) -> None:
    """Empty every registered table (M1-M3) before the test.

    `Base.metadata.sorted_tables` picks up new entity tables with their member/edge
    dependencies automatically; TRUNCATE skips row triggers (ADR-0009).
    """
    _require_test_database(migrated_engine.url.render_as_string(hide_password=False))
    names = ", ".join(table.name for table in Base.metadata.sorted_tables)
    with migrated_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def pg_repository(migrated_engine: Engine, clean_db: None) -> PostgresRepository:
    return PostgresRepository(migrated_engine)
