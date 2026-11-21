"""CLI unit tests for `langpipe igt assert` and `langpipe morph` commands (M5 WP5.9, Gate 38)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from langpipe.app_context import AppContext
from langpipe.cli.app import app
from langpipe.cli.context import reset_context_factory, set_context_factory
from langpipe.domain.ids import new_id
from langpipe.igt.service import extract_igt
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.normalization.service import normalize_extraction
from langpipe.storage.memory import InMemoryRepository
from langpipe.storage.objects.local import LocalContentStore
from langpipe.tokenization.service import tokenize_normalization
from tests.service.manifests import manifest_data, write_manifest, write_origin_file

REPO = Path(__file__).resolve().parents[2]
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


def _setup_pipeline(
    ctx: AppContext, tmp_path: Path, key: str = "src-cli-morph"
) -> tuple[str, str, str]:
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

    igt_res = extract_igt(ctx, registered.source.id)
    norm_res = normalize_extraction(ctx, igt_res.run.id)
    tok_res = tokenize_normalization(ctx, norm_res.run.id)
    return registered.source.id, igt_res.run.id, tok_res.run.id


def test_cli_igt_assert_happy_path(cli_ctx: AppContext, runner: CliRunner, tmp_path: Path) -> None:
    _, igt_run_id, tok_run_id = _setup_pipeline(cli_ctx, tmp_path, "tb-cli-assert")

    res = runner.invoke(
        app,
        ["igt", "assert", "--tokenization-run", tok_run_id, "--igt-run", igt_run_id],
    )
    assert res.exit_code == 0, res.output
    fields = _fields(res.stdout.strip())
    assert fields["run_id"].startswith("run_")
    assert int(fields["analyses"]) > 0
    assert int(fields["morphemes"]) > 0
    assert int(fields["allomorphs"]) > 0
    assert fields["report_id"].startswith("artifact_")
    assert fields["reused"] == "false"


def test_cli_igt_assert_exclude_ref(cli_ctx: AppContext, runner: CliRunner, tmp_path: Path) -> None:
    _, igt_run_id, tok_run_id = _setup_pipeline(cli_ctx, tmp_path, "tb-cli-exclude")

    res = runner.invoke(
        app,
        [
            "igt",
            "assert",
            "--tokenization-run",
            tok_run_id,
            "--igt-run",
            igt_run_id,
            "--exclude-ref",
            "IGT-1",
        ],
    )
    assert res.exit_code == 0, res.output
    fields = _fields(res.stdout.strip())
    assert fields["run_id"].startswith("run_")
    assert fields["reused"] == "false"


def test_cli_igt_assert_idempotent_reuse(
    cli_ctx: AppContext, runner: CliRunner, tmp_path: Path
) -> None:
    _, igt_run_id, tok_run_id = _setup_pipeline(cli_ctx, tmp_path, "tb-cli-assert-reuse")

    first = runner.invoke(
        app,
        ["igt", "assert", "--tokenization-run", tok_run_id, "--igt-run", igt_run_id],
    )
    assert first.exit_code == 0, first.output
    first_fields = _fields(first.stdout.strip())

    second = runner.invoke(
        app,
        ["igt", "assert", "--tokenization-run", tok_run_id, "--igt-run", igt_run_id],
    )
    assert second.exit_code == 0, second.output
    second_fields = _fields(second.stdout.strip())

    assert second_fields["run_id"] == first_fields["run_id"]
    assert second_fields["reused"] == "true"


def test_cli_morph_induce_happy_path(
    cli_ctx: AppContext, runner: CliRunner, tmp_path: Path
) -> None:
    _, _, tok_run_id = _setup_pipeline(cli_ctx, tmp_path, "tb-cli-induce")

    res = runner.invoke(
        app,
        ["morph", "induce", "--tokenization-run", tok_run_id, "--method", "unsegmented@0.1.0"],
    )
    assert res.exit_code == 0, res.output
    fields = _fields(res.stdout.strip())
    assert fields["run_id"].startswith("run_")
    assert int(fields["analyses"]) > 0
    assert int(fields["segments"]) > 0
    assert fields["report_id"].startswith("artifact_")
    assert fields["reused"] == "false"


def test_cli_morph_induce_idempotent_reuse(
    cli_ctx: AppContext, runner: CliRunner, tmp_path: Path
) -> None:
    _, _, tok_run_id = _setup_pipeline(cli_ctx, tmp_path, "tb-cli-induce-reuse")

    first = runner.invoke(
        app,
        ["morph", "induce", "--tokenization-run", tok_run_id, "--method", "unsegmented@0.1.0"],
    )
    assert first.exit_code == 0, first.output
    first_fields = _fields(first.stdout.strip())

    second = runner.invoke(
        app,
        ["morph", "induce", "--tokenization-run", tok_run_id, "--method", "unsegmented@0.1.0"],
    )
    assert second.exit_code == 0, second.output
    second_fields = _fields(second.stdout.strip())

    assert second_fields["run_id"] == first_fields["run_id"]
    assert second_fields["reused"] == "true"


def test_cli_morph_analyses_no_surfaces(
    cli_ctx: AppContext, runner: CliRunner, tmp_path: Path
) -> None:
    """Invariant test: `morph analyses` lists analyses without echoing raw target text surfaces."""
    _, igt_run_id, tok_run_id = _setup_pipeline(cli_ctx, tmp_path, "tb-cli-analyses")

    # Assert morphology to produce analyses
    assert_res = runner.invoke(
        app,
        ["igt", "assert", "--tokenization-run", tok_run_id, "--igt-run", igt_run_id],
    )
    assert assert_res.exit_code == 0, assert_res.output
    assert_run_id = _fields(assert_res.stdout.strip())["run_id"]

    analyses = cli_ctx.repo.list_morph_analyses_for_run(assert_run_id)
    assert len(analyses) > 0
    target_token_id = analyses[0].target_token_id
    token = cli_ctx.repo.get_token(target_token_id)
    token_surface = token.raw_surface

    res = runner.invoke(app, ["morph", "analyses", "--token", target_token_id])
    assert res.exit_code == 0, res.output
    output = res.stdout.strip()
    assert "id=" in output
    assert "method=igt_assertion@0.1.0" in output
    assert "kind=" in output
    assert "status=" in output
    assert "signature=" in output
    assert "score_overall=" in output

    # CRITICAL: Verify that the surface text does NOT appear anywhere in the output!
    assert token_surface not in output


def test_cli_morph_benchmark_happy_path(
    cli_ctx: AppContext, runner: CliRunner, tmp_path: Path
) -> None:
    _, igt_run_id, tok_run_id = _setup_pipeline(cli_ctx, tmp_path, "tb-cli-bench")

    # Induce baseline
    ind_res = runner.invoke(
        app,
        ["morph", "induce", "--tokenization-run", tok_run_id, "--method", "unsegmented@0.1.0"],
    )
    assert ind_res.exit_code == 0, ind_res.output
    ind_run_id = _fields(ind_res.stdout.strip())["run_id"]

    res = runner.invoke(
        app,
        [
            "morph",
            "benchmark",
            "--run",
            ind_run_id,
            "--gold-from-igt",
            igt_run_id,
            "--gold-ref",
            "IGT-2",
        ],
    )
    assert res.exit_code == 0, res.output
    assert "report_id=" in res.output
    assert "method=unsegmented@0.1.0" in res.output


def test_cli_morph_benchmark_from_file_gold(
    cli_ctx: AppContext, runner: CliRunner, tmp_path: Path
) -> None:
    from langpipe.evaluation.morphology import gold_from_igt

    _, igt_run_id, tok_run_id = _setup_pipeline(cli_ctx, tmp_path, "tb-cli-bench-file")

    ind_res = runner.invoke(
        app,
        ["morph", "induce", "--tokenization-run", tok_run_id, "--method", "unsegmented@0.1.0"],
    )
    assert ind_res.exit_code == 0, ind_res.output
    ind_run_id = _fields(ind_res.stdout.strip())["run_id"]

    gold = gold_from_igt(cli_ctx.repo, igt_run_id, ["IGT-2"], "qaa")
    gold_path = tmp_path / "frozen_gold.json"
    gold_path.write_text(gold.model_dump_json())

    res = runner.invoke(
        app,
        [
            "morph",
            "benchmark",
            "--run",
            ind_run_id,
            "--gold",
            str(gold_path),
        ],
    )
    assert res.exit_code == 0, res.output
    assert "report_id=" in res.output
    assert "method=unsegmented@0.1.0" in res.output


def test_cli_error_handling(cli_ctx: AppContext, runner: CliRunner) -> None:
    res = runner.invoke(
        app,
        ["igt", "assert", "--tokenization-run", "nonexistent-tok", "--igt-run", "nonexistent-igt"],
    )
    assert res.exit_code != 0
