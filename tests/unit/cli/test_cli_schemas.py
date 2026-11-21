"""CLI `schemas` commands: the committed schema directory must match the generated models."""

import logging
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from langpipe.cli.app import app
from langpipe.domain.models.source import Source
from langpipe.schemas.generate import DEFAULT_SCHEMA_DIR, schema_filename
from tests.unit.cli import diagnostic_lines, run_console

FILENAME_SENTINEL = "SENTINEL-FILENAME-88"
SAFE_FAILURE_LINE = "error=LangpipeError"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_schemas_check_passes_on_repo(runner: CliRunner) -> None:
    result = runner.invoke(app, ["schemas", "check"])

    assert result.exit_code == 0, result.output
    assert "drift=" not in result.output


def test_schemas_check_fails_on_drift(runner: CliRunner, tmp_path: Path) -> None:
    schema_dir = tmp_path / "schemas"
    shutil.copytree(DEFAULT_SCHEMA_DIR, schema_dir)
    drifted = schema_dir / schema_filename(Source)
    drifted.write_text(drifted.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")

    result = runner.invoke(app, ["schemas", "check", "--dir", str(schema_dir)])

    assert result.exit_code == 1
    assert f"drift={schema_filename(Source)}" in result.output


def test_schemas_generate_then_check_passes(runner: CliRunner, tmp_path: Path) -> None:
    schema_dir = tmp_path / "schemas"

    generated = runner.invoke(app, ["schemas", "generate", "--dir", str(schema_dir)])
    checked = runner.invoke(app, ["schemas", "check", "--dir", str(schema_dir)])

    assert generated.exit_code == 0, generated.output
    assert "written=29" in generated.output
    assert checked.exit_code == 0, checked.output


def test_schemas_unexpected_os_error_exits_1_without_filename(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="langpipe")

    def fail(_schema_dir: Path) -> list[str]:
        raise OSError(20, "Not a directory", f"/{FILENAME_SENTINEL}")

    monkeypatch.setattr("langpipe.cli.schemas.generate", fail)

    result = runner.invoke(app, ["schemas", "generate", "--dir", str(tmp_path)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.strip() == SAFE_FAILURE_LINE
    for output in (result.output, caplog.text):
        assert FILENAME_SENTINEL not in output
        assert "Traceback" not in output


def test_console_script_os_error_exits_1_without_leaks() -> None:
    # /dev/null is a file, so the directory cannot be created: a real OSError escapes the command.
    blocked = f"/dev/null/{FILENAME_SENTINEL}"

    completed = run_console(["schemas", "generate", "--dir", blocked], env={})

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert diagnostic_lines(completed.stderr) == [SAFE_FAILURE_LINE]
    for output in (completed.stdout, completed.stderr):
        assert FILENAME_SENTINEL not in output
        assert "Traceback" not in output
