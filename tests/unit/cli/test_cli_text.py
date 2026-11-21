"""CLI `extract`, `normalize`, `tokenize` and `profiles list` against the memory repository.

No database or network. Golden sources 01 and 05 exercise the TSV and plain-lines paths.
"""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import pytest
from typer.testing import CliRunner

from langpipe.app_context import AppContext
from langpipe.cli.app import app
from langpipe.cli.context import reset_context_factory, set_context_factory
from langpipe.domain.ids import new_id
from langpipe.extraction.plain_lines import PlainLinesExtractor
from langpipe.extraction.service import extract_source
from langpipe.extraction.tsv import TsvExtractor
from langpipe.extraction.usfm import UsfmExtractor
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.storage.memory import InMemoryRepository
from langpipe.storage.objects.local import LocalContentStore
from langpipe.text.registry import VersionedRegistry
from tests.service.manifests import manifest_data, write_manifest, write_origin_file

GOLDEN_SOURCES = Path(__file__).resolve().parents[2] / "golden" / "fixture" / "sources"
SENTINEL = "SENTINEL-RESTRICTED-4c1e"
CLOCK_START = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def cli_ctx(tmp_path: Path) -> Iterator[AppContext]:
    ticks = iter(range(10_000))
    context = AppContext(
        repo=InMemoryRepository(),
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=lambda: CLOCK_START + timedelta(seconds=next(ticks)),
        new_id=new_id,
        actor="test-actor",
        code_revision="test-rev",
    )
    set_context_factory(lambda: context)
    yield context
    reset_context_factory()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _fields(line: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in line.split())


def _ingest_golden(ctx: AppContext, dirname: str) -> None:
    registered = register_source(ctx, GOLDEN_SOURCES / dirname / "manifest.yaml")
    ingest_source(ctx, registered.source.key)


def test_extract_normalize_tokenize_happy_path(cli_ctx: AppContext, runner: CliRunner) -> None:
    _ingest_golden(cli_ctx, "01-parallel-distill")
    _ingest_golden(cli_ctx, "05-monolingual")

    extracted = runner.invoke(app, ["extract", "01-parallel-distill"])
    assert extracted.exit_code == 0, extracted.output
    fields = _fields(extracted.stdout.strip())
    assert fields["source_id"].startswith("src_")
    assert fields["run_id"].startswith("run_")
    assert fields["segments"] == "8"
    assert fields["skipped_objects"] == "0"
    assert fields["report_id"].startswith("artifact_")
    assert fields["reused"] == "false"

    normalized = runner.invoke(app, ["normalize", "01-parallel-distill"])
    assert normalized.exit_code == 0, normalized.output
    normalized_fields = _fields(normalized.stdout.strip())
    assert normalized_fields["extraction_run_id"] == fields["run_id"]
    assert normalized_fields["segments"] == "8"
    assert normalized_fields["failed"] == "0"
    assert normalized_fields["report_id"].startswith("artifact_")
    assert normalized_fields["reused"] == "false"

    tokenized = runner.invoke(app, ["tokenize", "01-parallel-distill"])
    assert tokenized.exit_code == 0, tokenized.output
    tokenized_fields = _fields(tokenized.stdout.strip())
    assert tokenized_fields["extraction_run_id"] == fields["run_id"]
    assert tokenized_fields["normalization_run_id"] == normalized_fields["run_id"]
    assert tokenized_fields["run_id"].startswith("run_")
    assert int(tokenized_fields["tokens"]) > 0
    assert int(tokenized_fields["forms"]) > 0
    assert tokenized_fields["skipped_segments"] == "0"
    assert tokenized_fields["report_id"].startswith("artifact_")
    assert tokenized_fields["reused"] == "false"

    # 05 drives normalize internally (plain-lines, 3 lines).
    extracted_05 = runner.invoke(app, ["extract", "05-monolingual"])
    assert extracted_05.exit_code == 0, extracted_05.output
    assert _fields(extracted_05.stdout.strip())["segments"] == "3"
    tokenized_05 = runner.invoke(app, ["tokenize", "05-monolingual"])
    assert tokenized_05.exit_code == 0, tokenized_05.output
    assert int(_fields(tokenized_05.stdout.strip())["tokens"]) > 0


def test_tokenize_reuses_normalization_run(cli_ctx: AppContext, runner: CliRunner) -> None:
    _ingest_golden(cli_ctx, "05-monolingual")
    assert runner.invoke(app, ["extract", "05-monolingual"]).exit_code == 0
    first_normalize = runner.invoke(app, ["normalize", "05-monolingual"])
    assert first_normalize.exit_code == 0, first_normalize.output
    normalization_run_id = _fields(first_normalize.stdout.strip())["run_id"]

    first = runner.invoke(app, ["tokenize", "05-monolingual"])
    assert first.exit_code == 0, first.output
    first_fields = _fields(first.stdout.strip())
    assert first_fields["normalization_run_id"] == normalization_run_id
    assert first_fields["reused"] == "false"

    second = runner.invoke(app, ["tokenize", "05-monolingual"])
    assert second.exit_code == 0, second.output
    second_fields = _fields(second.stdout.strip())
    assert second_fields["run_id"] == first_fields["run_id"]
    assert second_fields["normalization_run_id"] == normalization_run_id
    assert second_fields["reused"] == "true"


def test_extract_denied_exits_3(cli_ctx: AppContext, runner: CliRunner) -> None:
    register_source(cli_ctx, GOLDEN_SOURCES / "06-excluded" / "manifest.yaml")

    result = runner.invoke(app, ["extract", "06-excluded"])

    assert result.exit_code == 3
    assert "error=PolicyDenied" in result.output


def test_extract_not_ingested_exits_9(cli_ctx: AppContext, runner: CliRunner) -> None:
    register_source(cli_ctx, GOLDEN_SOURCES / "05-monolingual" / "manifest.yaml")

    result = runner.invoke(app, ["extract", "05-monolingual"])

    assert result.exit_code == 9
    assert "error=SourceNotIngested" in result.output


class _TsvV2(TsvExtractor):
    version: ClassVar[str] = "0.1.1"


def test_ambiguous_extraction_run_exits_11(
    cli_ctx: AppContext, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ingest_golden(cli_ctx, "01-parallel-distill")
    patched = VersionedRegistry((TsvExtractor(), PlainLinesExtractor(), UsfmExtractor(), _TsvV2()))
    monkeypatch.setattr("langpipe.extraction.service.EXTRACTORS", patched)
    extract_source(cli_ctx, "01-parallel-distill")
    extract_source(cli_ctx, "01-parallel-distill", extractor="tsv@0.1.1")

    result = runner.invoke(app, ["normalize", "01-parallel-distill"])

    assert result.exit_code == 11
    assert "error=AmbiguousInput" in result.output


def test_cli_text_output_never_contains_segment_text(
    cli_ctx: AppContext,
    runner: CliRunner,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="langpipe")
    write_origin_file(tmp_path, "texts/a.txt", f"{SENTINEL} kanu\n".encode())
    data = manifest_data(
        key="redaction-text", objects=[{"path": "texts/a.txt", "media_type": "text/plain"}]
    )
    data["source_type"] = "monolingual_text"
    data["languages"] = ["qaa"]
    register_source(cli_ctx, write_manifest(tmp_path, data))
    ingest_source(cli_ctx, "redaction-text")

    outputs: list[str] = []
    for args in (
        ["extract", "redaction-text"],
        ["normalize", "redaction-text"],
        ["tokenize", "redaction-text"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        outputs.append(result.output)

    for output in (*outputs, caplog.text):
        assert SENTINEL not in output


def test_profiles_list_includes_pinned_versions() -> None:
    result = CliRunner().invoke(app, ["profiles", "list"])

    assert result.exit_code == 0, result.output
    lines = result.stdout.strip().splitlines()
    assert "kind=extractor name=tsv@0.1.0" in lines
    assert "kind=extractor name=plain_lines@0.1.0" in lines
    assert "kind=extractor name=usfm@0.1.0" in lines
    assert "kind=normalization name=default_text@0.1.0" in lines
    assert "kind=normalization name=unicode_nfc@1.0.0" in lines
    assert "kind=normalization name=marubo_standard@0.1.0" in lines
    assert "kind=tokenizer name=whitespace_punct@0.1.0" in lines
    assert "kind=tokenizer name=marubo_pilot@0.1.0" in lines
    assert (
        "kind=language language=mzr profile=mzr_pilot@0.1.0 "
        "normalization=marubo_standard@0.1.0 tokenizer=marubo_pilot@0.1.0" in lines
    )
