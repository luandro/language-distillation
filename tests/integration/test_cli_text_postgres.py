"""CLI text pipeline (`extract`/`normalize`/`tokenize`) against PostgreSQL. Requires a database."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from langpipe.cli.app import app
from langpipe.cli.context import reset_context_factory

pytestmark = pytest.mark.integration

GOLDEN_SOURCES = Path(__file__).resolve().parents[1] / "golden" / "fixture" / "sources"


def _fields(line: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in line.split())


def test_cli_text_pipeline_against_postgres(
    clean_db: None,
    pg_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_context_factory()
    monkeypatch.setenv("LANGPIPE_DATABASE_URL", pg_url)
    monkeypatch.setenv("LANGPIPE_DATA_DIR", str(tmp_path / "data"))
    runner = CliRunner()
    manifest = GOLDEN_SOURCES / "01-parallel-distill" / "manifest.yaml"

    added = runner.invoke(app, ["source", "add", str(manifest)])
    assert added.exit_code == 0, added.output
    source_id = _fields(added.stdout.strip())["source_id"]

    ingested = runner.invoke(app, ["source", "ingest", source_id])
    assert ingested.exit_code == 0, ingested.output

    extracted = runner.invoke(app, ["extract", source_id])
    assert extracted.exit_code == 0, extracted.output
    extract_fields = _fields(extracted.stdout.strip())
    assert extract_fields["segments"] == "8"
    assert extract_fields["reused"] == "false"

    normalized = runner.invoke(app, ["normalize", source_id])
    assert normalized.exit_code == 0, normalized.output
    normalize_fields = _fields(normalized.stdout.strip())
    assert normalize_fields["extraction_run_id"] == extract_fields["run_id"]
    assert normalize_fields["segments"] == "8"
    assert normalize_fields["failed"] == "0"

    tokenized = runner.invoke(app, ["tokenize", source_id])
    assert tokenized.exit_code == 0, tokenized.output
    token_fields = _fields(tokenized.stdout.strip())
    assert token_fields["extraction_run_id"] == extract_fields["run_id"]
    assert token_fields["normalization_run_id"] == normalize_fields["run_id"]
    assert int(token_fields["tokens"]) > 0
    assert int(token_fields["forms"]) > 0
    assert token_fields["skipped_segments"] == "0"

    rerun = runner.invoke(app, ["tokenize", source_id])
    assert rerun.exit_code == 0, rerun.output
    assert _fields(rerun.stdout.strip())["reused"] == "true"
