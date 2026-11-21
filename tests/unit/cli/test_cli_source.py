"""CLI `source` and `lineage` commands against the in-memory repository (no database)."""

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.exc import ProgrammingError
from typer.testing import CliRunner

from langpipe.app_context import AppContext
from langpipe.cli.app import app, main
from langpipe.cli.context import reset_context_factory, set_context_factory
from langpipe.domain.ids import new_id
from langpipe.storage.memory import InMemoryRepository
from langpipe.storage.objects.local import LocalContentStore
from tests.service.manifests import manifest_data, write_manifest, write_origin_file

CONTENT_SENTINEL = "SENTINEL-RESTRICTED-7f3a9c"
TITLE_SENTINEL = "SENTINEL-TITLE-55"
FILENAME_SENTINEL = "sentinel-file-name-99"
REF_SENTINEL = "SENTINEL-REF-42"
SQL_SENTINEL = "SENTINEL-SQL-PARAM-31"
CLOCK_START = datetime(2026, 1, 1, tzinfo=UTC)
SAFE_FAILURE_LINE = "error=LangpipeError"


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


def _write_text_source(tmp_path: Path, key: str = "test-source") -> Path:
    write_origin_file(tmp_path, "texts/a.txt", b"alpha text\n")
    write_origin_file(tmp_path, "texts/b.txt", b"beta text\n")
    objects = [
        {"path": "texts/a.txt", "media_type": "text/plain"},
        {"path": "texts/b.txt", "media_type": "text/plain"},
    ]
    return write_manifest(tmp_path, manifest_data(key=key, objects=objects))


def test_add_ingest_verify_happy_path(
    cli_ctx: AppContext, runner: CliRunner, tmp_path: Path
) -> None:
    manifest = _write_text_source(tmp_path)

    added = runner.invoke(app, ["source", "add", str(manifest)])
    assert added.exit_code == 0, added.output
    add_fields = _fields(added.stdout.strip())
    assert add_fields["source_id"].startswith("src_")
    assert add_fields["key"] == "test-source"
    assert add_fields["objects"] == "2"
    assert add_fields["reused"] == "false"

    ingested = runner.invoke(app, ["source", "ingest", "test-source"])
    assert ingested.exit_code == 0, ingested.output
    ingest_fields = _fields(ingested.stdout.strip())
    assert ingest_fields["source_id"] == add_fields["source_id"]
    assert ingest_fields["blobs"] == "2"
    assert ingest_fields["report_id"].startswith("artifact_")
    assert ingest_fields["reused"] == "false"

    verified = runner.invoke(app, ["source", "verify", add_fields["source_id"]])
    assert verified.exit_code == 0, verified.output
    lines = verified.stdout.strip().splitlines()
    assert len(lines) == 2
    assert all(_fields(line)["status"] == "ok" for line in lines)


def test_add_twice_reports_reused(cli_ctx: AppContext, runner: CliRunner, tmp_path: Path) -> None:
    manifest = _write_text_source(tmp_path)

    first = _fields(runner.invoke(app, ["source", "add", str(manifest)]).stdout.strip())
    second = runner.invoke(app, ["source", "add", str(manifest)])

    assert second.exit_code == 0, second.output
    second_fields = _fields(second.stdout.strip())
    assert second_fields["reused"] == "true"
    assert second_fields["source_id"] == first["source_id"]
    assert second_fields["run_id"] == first["run_id"]


def test_ingest_exclude_exits_3(cli_ctx: AppContext, runner: CliRunner, tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path, manifest_data(key="excluded-source", mode="exclude", objects=[])
    )
    assert runner.invoke(app, ["source", "add", str(path)]).exit_code == 0

    result = runner.invoke(app, ["source", "ingest", "excluded-source"])

    assert result.exit_code == 3
    assert "error=PolicyDenied" in result.output


def test_invalid_manifest_exits_4_without_echoing_values(
    cli_ctx: AppContext, runner: CliRunner, tmp_path: Path
) -> None:
    bad_key = "SENTINEL-KEY-BAD!"
    path = write_manifest(tmp_path, manifest_data(key=bad_key))

    result = runner.invoke(app, ["source", "add", str(path)])

    assert result.exit_code == 4
    assert "error=SchemaViolation" in result.output
    assert bad_key not in result.output
    assert "SENTINEL" not in result.output


def test_cli_output_never_contains_raw_content(
    cli_ctx: AppContext,
    runner: CliRunner,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="langpipe")
    write_origin_file(tmp_path, f"texts/{FILENAME_SENTINEL}.txt", f"{CONTENT_SENTINEL}\n".encode())
    path = write_manifest(
        tmp_path,
        manifest_data(
            key="redaction-cli",
            title=TITLE_SENTINEL,
            mode="restricted",
            access_class="restricted",
            objects=[{"path": f"texts/{FILENAME_SENTINEL}.txt", "media_type": "text/plain"}],
        ),
    )
    outputs: list[str] = []
    for args in (
        ["source", "add", str(path)],
        ["source", "ingest", "redaction-cli"],
        ["source", "verify", "redaction-cli"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        outputs.append(result.output)
    object_id = cli_ctx.repo.list_source_objects(
        cli_ctx.repo.find_source_by_key("redaction-cli").id  # type: ignore[union-attr]
    )[0].id
    lineage = runner.invoke(app, ["lineage", "descendants", object_id])
    assert lineage.exit_code == 0, lineage.output
    outputs.append(lineage.output)

    # `source show` is the one command allowed to print title and file-name metadata.
    shown = runner.invoke(app, ["source", "show", "redaction-cli"])
    assert shown.exit_code == 0, shown.output

    for output in (*outputs, shown.output, caplog.text):
        assert CONTENT_SENTINEL not in output
    for output in (*outputs, caplog.text):
        assert TITLE_SENTINEL not in output
        assert FILENAME_SENTINEL not in output


def test_verify_corrupted_exits_5(cli_ctx: AppContext, runner: CliRunner, tmp_path: Path) -> None:
    manifest = _write_text_source(tmp_path, key="corrupt-source")
    assert runner.invoke(app, ["source", "add", str(manifest)]).exit_code == 0
    assert runner.invoke(app, ["source", "ingest", "corrupt-source"]).exit_code == 0
    source = cli_ctx.repo.find_source_by_key("corrupt-source")
    assert source is not None
    corrupted = next(
        o for o in cli_ctx.repo.list_source_objects(source.id) if "b.txt" in o.original_path
    )
    stored = cli_ctx.raw_store.path_for(corrupted.sha256)
    stored.chmod(0o644)
    with stored.open("ab") as handle:
        handle.write(b"tampered\n")

    result = runner.invoke(app, ["source", "verify", "corrupt-source"])

    assert result.exit_code == 5
    statuses = [_fields(line)["status"] for line in result.stdout.strip().splitlines()]
    assert statuses == ["ok", "mismatch"]


def test_show_prints_metadata_json(cli_ctx: AppContext, runner: CliRunner, tmp_path: Path) -> None:
    manifest = _write_text_source(tmp_path, key="show-source")
    assert runner.invoke(app, ["source", "add", str(manifest)]).exit_code == 0

    result = runner.invoke(app, ["source", "show", "show-source"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload) == {"source", "policy", "objects", "effective_approved_operations"}
    assert payload["source"]["key"] == "show-source"
    assert payload["policy"]["mode"] == "direct"
    assert len(payload["objects"]) == 2


def test_unknown_source_ref_exits_7_without_echoing_ref(
    cli_ctx: AppContext, runner: CliRunner
) -> None:
    result = runner.invoke(app, ["source", "ingest", "SENTINEL-UNKNOWN-REF"])

    assert result.exit_code == 7
    assert "error=NotFound" in result.output
    assert "SENTINEL-UNKNOWN-REF" not in result.output


def test_invalid_lineage_object_id_exits_4(cli_ctx: AppContext, runner: CliRunner) -> None:
    result = runner.invoke(app, ["lineage", "descendants", "not-an-id"])

    assert result.exit_code == 4
    assert "not-an-id" not in result.output


def test_main_console_entry_maps_error_to_exit_code(
    cli_ctx: AppContext,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["langpipe", "source", "ingest", "missing-key"])

    with pytest.raises(SystemExit) as raised:
        main()

    assert raised.value.code == 7
    assert "error=NotFound" in capsys.readouterr().err


def _programming_error() -> ProgrammingError:
    # Mirrors the real failure shape: SQL text plus bound parameters plus the driver message.
    return ProgrammingError(
        f"SELECT source.id FROM source WHERE source.key = %(key_1)s {SQL_SENTINEL}",
        {"key_1": REF_SENTINEL, "extra": SQL_SENTINEL},
        Exception(f"relation {SQL_SENTINEL} does not exist"),
    )


def _assert_safe_failure(stdout: str, stderr: str, logs: str, forbidden: tuple[str, ...]) -> None:
    assert stdout == ""
    assert stderr.strip() == SAFE_FAILURE_LINE
    for output in (stdout, stderr, logs):
        assert "Traceback" not in output
        for sentinel in forbidden:
            assert sentinel not in output


def test_unexpected_db_error_in_command_exits_1_with_fixed_diagnostic(
    cli_ctx: AppContext,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="langpipe")

    def fail(*_args: object) -> None:
        raise _programming_error()

    monkeypatch.setattr("langpipe.cli.source.ingest_source", fail)

    result = runner.invoke(app, ["source", "ingest", REF_SENTINEL])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    _assert_safe_failure(
        result.stdout,
        result.stderr,
        caplog.text,
        (REF_SENTINEL, SQL_SENTINEL, "SELECT", "UndefinedTable", "[parameters"),
    )


def test_context_construction_failure_exits_1_with_fixed_diagnostic(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="langpipe")

    def broken_build(_settings: object) -> AppContext:
        raise OSError(f"cannot open {FILENAME_SENTINEL}")

    monkeypatch.setattr("langpipe.cli.context.build_context", broken_build)

    result = runner.invoke(app, ["source", "show", "any-key"])

    assert result.exit_code == 1
    _assert_safe_failure(result.stdout, result.stderr, caplog.text, (FILENAME_SENTINEL,))


def test_filesystem_error_in_command_exits_1_without_filename(
    cli_ctx: AppContext,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="langpipe")

    def fail(*_args: object) -> None:
        raise OSError(2, "No such file or directory", f"/data/{FILENAME_SENTINEL}.txt")

    monkeypatch.setattr("langpipe.cli.source.verify_source", fail)

    result = runner.invoke(app, ["source", "verify", "any-key"])

    assert result.exit_code == 1
    _assert_safe_failure(result.stdout, result.stderr, caplog.text, (FILENAME_SENTINEL,))


def test_main_guard_catches_unexpected_error_outside_commands(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken_app() -> None:
        raise OSError(f"cannot read {FILENAME_SENTINEL}")

    monkeypatch.setattr("langpipe.cli.app.app", broken_app)
    monkeypatch.setattr("sys.argv", ["langpipe", "source", "show", "any-key"])

    with pytest.raises(SystemExit) as raised:
        main()

    assert raised.value.code == 1
    captured = capsys.readouterr()
    _assert_safe_failure(captured.out, captured.err, "", (FILENAME_SENTINEL,))


def test_usage_error_still_exits_2(runner: CliRunner) -> None:
    result = runner.invoke(app, ["source", "add"])

    assert result.exit_code == 2
    assert "Traceback" not in result.output
