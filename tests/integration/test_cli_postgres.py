"""CLI happy path with the real `build_context` against PostgreSQL. Requires PostgreSQL."""

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy.engine import make_url
from typer.testing import CliRunner

from langpipe.cli.app import app
from langpipe.cli.context import reset_context_factory
from tests.service.manifests import manifest_data, write_manifest, write_origin_file
from tests.unit.cli import diagnostic_lines, run_console

pytestmark = pytest.mark.integration

REF_SENTINEL = "SENTINEL-REF-DB-17"


def _fields(line: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in line.split())


def test_cli_happy_path_against_postgres(
    clean_db: None,
    pg_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_context_factory()
    monkeypatch.setenv("LANGPIPE_DATABASE_URL", pg_url)
    monkeypatch.setenv("LANGPIPE_DATA_DIR", str(tmp_path / "data"))
    write_origin_file(tmp_path, "texts/a.txt", b"alpha text\n")
    manifest = write_manifest(
        tmp_path,
        manifest_data(
            key="pg-cli-source",
            objects=[{"path": "texts/a.txt", "media_type": "text/plain"}],
        ),
    )
    runner = CliRunner()

    added = runner.invoke(app, ["source", "add", str(manifest)])
    assert added.exit_code == 0, added.output
    source_id = _fields(added.stdout.strip())["source_id"]

    ingested = runner.invoke(app, ["source", "ingest", source_id])
    assert ingested.exit_code == 0, ingested.output
    assert _fields(ingested.stdout.strip())["blobs"] == "1"

    verified = runner.invoke(app, ["source", "verify", source_id])
    assert verified.exit_code == 0, verified.output
    assert _fields(verified.stdout.strip())["status"] == "ok"

    shown = runner.invoke(app, ["source", "show", source_id])
    assert shown.exit_code == 0, shown.output
    assert '"key": "pg-cli-source"' in shown.stdout

    checked = runner.invoke(app, ["schemas", "check"])
    assert checked.exit_code == 0, checked.output


@pytest.fixture
def unmigrated_db_url(pg_url: str) -> Iterator[str]:
    """A fresh *_test database without M1 tables, so queries fail with a real ProgrammingError."""
    name = f"langpipe_unmigrated_{uuid4().hex[:8]}_test"
    admin_dsn = (
        make_url(pg_url)
        .set(drivername="postgresql", database="postgres")
        .render_as_string(hide_password=False)
    )
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield make_url(pg_url).set(database=name).render_as_string(hide_password=False)
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_cli_unexpected_db_error_console_exits_1_without_leaks(
    unmigrated_db_url: str, tmp_path: Path
) -> None:
    completed = run_console(
        ["source", "ingest", REF_SENTINEL],
        env={
            "LANGPIPE_DATABASE_URL": unmigrated_db_url,
            "LANGPIPE_DATA_DIR": str(tmp_path / "data"),
        },
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert diagnostic_lines(completed.stderr) == ["error=LangpipeError"]
    for output in (completed.stdout, completed.stderr):
        for leak in (REF_SENTINEL, "Traceback", "UndefinedTable", "SELECT", "[parameters"):
            assert leak not in output
