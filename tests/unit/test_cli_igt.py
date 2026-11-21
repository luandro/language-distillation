"""CLI unit tests for `langpipe igt extract` (WP5.7, Gate 36)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from langpipe.app_context import AppContext
from langpipe.cli.app import app
from langpipe.cli.context import reset_context_factory, set_context_factory
from langpipe.domain.ids import new_id
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.storage.memory import InMemoryRepository
from langpipe.storage.objects.local import LocalContentStore
from tests.service.manifests import manifest_data, write_manifest, write_origin_file

REPO = Path(__file__).resolve().parents[2]
GOLDEN_SOURCES = REPO / "tests" / "golden" / "fixture" / "sources"
SAMPLE_TOOLBOX = REPO / "tests" / "fixtures" / "igt" / "toolbox_sample.txt"
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


def _setup_igt_source(ctx: AppContext, tmp_path: Path, key: str = "src-igt") -> str:
    relative = f"texts/{key}.txt"
    write_origin_file(tmp_path, relative, SAMPLE_TOOLBOX.read_bytes())
    data = manifest_data(
        key=key,
        access_class="public",
        objects=[{"path": relative, "media_type": "text/plain"}],
    )
    data["source_type"] = "igt"
    data["languages"] = ["qaa", "por"]
    data["policy"]["mode"] = "direct"
    registered = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))
    ingest_source(ctx, registered.source.id)
    return registered.source.id


def test_cli_igt_extract_happy_path(cli_ctx: AppContext, runner: CliRunner, tmp_path: Path) -> None:
    source_id = _setup_igt_source(cli_ctx, tmp_path)
    res = runner.invoke(app, ["igt", "extract", source_id])
    assert res.exit_code == 0, res.output
    fields = _fields(res.stdout.strip())
    assert fields["source_id"] == source_id
    assert fields["run_id"].startswith("run_")
    assert fields["records"] == "4"
    assert fields["segments"] == "4"
    assert fields["words"] == "6"
    assert fields["morphs"] == "11"
    assert fields["report_id"].startswith("artifact_")
    assert fields["reused"] == "false"


def test_cli_igt_extract_idempotent_reuse(
    cli_ctx: AppContext, runner: CliRunner, tmp_path: Path
) -> None:
    source_id = _setup_igt_source(cli_ctx, tmp_path)
    first = runner.invoke(app, ["igt", "extract", source_id])
    assert first.exit_code == 0, first.output
    first_fields = _fields(first.stdout.strip())

    second = runner.invoke(app, ["igt", "extract", source_id])
    assert second.exit_code == 0, second.output
    second_fields = _fields(second.stdout.strip())

    assert second_fields["run_id"] == first_fields["run_id"]
    assert second_fields["records"] == first_fields["records"]
    assert second_fields["segments"] == first_fields["segments"]
    assert second_fields["reused"] == "true"


def test_cli_igt_extract_with_explicit_options(
    cli_ctx: AppContext, runner: CliRunner, tmp_path: Path
) -> None:
    source_id = _setup_igt_source(cli_ctx, tmp_path)
    res = runner.invoke(
        app,
        [
            "igt",
            "extract",
            source_id,
            "--reader",
            "toolbox_igt@0.1.0",
            "--language",
            "qaa",
            "--contact-language",
            "por",
        ],
    )
    assert res.exit_code == 0, res.output
    fields = _fields(res.stdout.strip())
    assert fields["source_id"] == source_id
    assert fields["reused"] == "false"


def test_cli_igt_extract_unknown_source_exits_nonzero(
    cli_ctx: AppContext, runner: CliRunner
) -> None:
    res = runner.invoke(app, ["igt", "extract", "non-existent-source"])
    assert res.exit_code != 0
