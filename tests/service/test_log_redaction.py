"""No restricted content may reach default logs, stdout/stderr, run errors or audit details.

Sentinels cover uppercase content, lowercase single words, filename-like strings, titles,
malformed YAML, custom validator failures and filesystem failures. Absence is proven only for
the paths exercised here.
"""

import json
import logging
import traceback
from contextlib import ExitStack
from pathlib import Path

import pytest
from pydantic import ValidationError

from langpipe.app_context import AppContext
from langpipe.domain.enums import EntityType, RunStage, RunStatus, SourceStatus
from langpipe.domain.errors import SchemaViolation, SourceChanged
from langpipe.domain.models.run import ProcessingRun
from langpipe.domain.models.source import SourceManifest
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.ingestion.verify import verify_source
from tests.service.manifests import (
    manifest_data,
    raise_on,
    record_finished_runs,
    state_counts,
    write_manifest,
    write_origin_file,
)

CONTENT_SENTINEL = "SENTINEL-RESTRICTED-7f3a9c"
TITLE_SENTINEL = "SENTINEL-TITLE-55"
LOWER_SENTINEL = "sentinelwordlower"
FILENAME_SENTINEL = "sentinel-file-name-99"
SENTINELS = (CONTENT_SENTINEL, TITLE_SENTINEL, LOWER_SENTINEL, FILENAME_SENTINEL)


@pytest.fixture
def recorded_finishes(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> list[ProcessingRun]:
    return record_finished_runs(ctx, monkeypatch)


def _restricted_manifest(tmp_path: Path, key: str, title: str, filename: str) -> Path:
    write_origin_file(
        tmp_path,
        f"texts/{filename}",
        f"{CONTENT_SENTINEL}\n{LOWER_SENTINEL}\n".encode(),
    )
    data = manifest_data(
        key=key,
        title=title,
        mode="restricted",
        access_class="restricted",
        objects=[{"path": f"texts/{filename}", "media_type": "text/plain"}],
    )
    return write_manifest(tmp_path, data, name=f"{key}.yaml")


def _streams(capsys: pytest.CaptureFixture[str]) -> tuple[str, str]:
    captured = capsys.readouterr()
    return captured.out, captured.err


def _assert_no_sentinel(
    ctx: AppContext, stdout: str, stderr: str, caplog: pytest.LogCaptureFixture
) -> None:
    rendered_events = json.dumps(
        [event.model_dump(mode="json") for event in ctx.repo.list_audit_events()]
    )
    for sentinel in SENTINELS:
        assert sentinel not in caplog.text
        assert sentinel not in stdout
        assert sentinel not in stderr
        assert sentinel not in rendered_events


def test_restricted_raw_content_absent_from_default_logs(
    ctx: AppContext,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    recorded_finishes: list[ProcessingRun],
) -> None:
    caplog.set_level(logging.DEBUG, logger="langpipe")
    path = _restricted_manifest(
        tmp_path, "redaction-ok", TITLE_SENTINEL, f"{FILENAME_SENTINEL}.txt"
    )

    registration = register_source(ctx, path)
    ingestion = ingest_source(ctx, registration.source.id)
    verify_source(ctx, registration.source.id)

    assert ingestion.source.status is SourceStatus.INGESTED
    _assert_no_sentinel(ctx, *_streams(capsys), caplog)
    assert all(run.error_message is None for run in recorded_finishes)
    assert "event=source.registered" in caplog.text
    assert "event=source.ingested" in caplog.text


def test_failed_ingest_leaks_no_restricted_content(
    ctx: AppContext,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    recorded_finishes: list[ProcessingRun],
) -> None:
    caplog.set_level(logging.DEBUG, logger="langpipe")
    path = _restricted_manifest(
        tmp_path, "redaction-fail", TITLE_SENTINEL, f"{FILENAME_SENTINEL}.txt"
    )
    registration = register_source(ctx, path)
    # Corrupt the origin before the first ingestion so the run cannot be reused.
    (tmp_path / "texts" / f"{FILENAME_SENTINEL}.txt").write_bytes(b"changed content\n")

    with pytest.raises(SourceChanged):
        ingest_source(ctx, registration.source.id)

    _assert_no_sentinel(ctx, *_streams(capsys), caplog)
    failed = [run for run in recorded_finishes if run.status is RunStatus.FAILED]
    assert len(failed) == 1
    assert failed[0].error_type == SourceChanged.__name__
    assert failed[0].error_message is None


@pytest.mark.parametrize(
    ("store", "method", "error_type"),
    [
        pytest.param(None, None, FileNotFoundError, id="origin-moved"),
        pytest.param("raw_store", "put_file", PermissionError, id="raw-put-permission"),
        pytest.param("raw_store", "verify", OSError, id="raw-verify-os-error"),
        pytest.param("artifact_store", "put_bytes", PermissionError, id="artifact-put-permission"),
    ],
)
def test_ingest_io_failure_is_safe_and_records_failed_run(
    ctx: AppContext,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    recorded_finishes: list[ProcessingRun],
    store: str | None,
    method: str | None,
    error_type: type[OSError],
) -> None:
    caplog.set_level(logging.DEBUG, logger="langpipe")
    path = _restricted_manifest(tmp_path, "io-fault", TITLE_SENTINEL, f"{FILENAME_SENTINEL}.txt")
    registration = register_source(ctx, path)
    origin = tmp_path / "texts" / f"{FILENAME_SENTINEL}.txt"
    before = state_counts(ctx)

    with ExitStack() as stack:
        if store is None:
            origin.rename(origin.with_name("moved.txt"))
        else:
            # One-argument form keeps the requested class: an errno argument would map
            # OSError to a subclass. The message carries sentinel content and path.
            error = error_type(f"denied {CONTENT_SENTINEL} {origin}")
            stack.enter_context(raise_on(getattr(ctx, store), method, error))
        with pytest.raises(SchemaViolation) as info:
            ingest_source(ctx, registration.source.id)

    rendered = "".join(traceback.format_exception(info.value))
    assert str(info.value) == "schema violation"
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True
    for sentinel in SENTINELS:
        assert sentinel not in rendered

    _assert_no_sentinel(ctx, *_streams(capsys), caplog)
    failed = [run for run in recorded_finishes if run.status is RunStatus.FAILED]
    assert [run.stage for run in failed] == [RunStage.RAW_INGESTION]
    assert failed[0].error_type == error_type.__name__
    assert failed[0].error_message is None
    assert ctx.repo.count_runs(RunStatus.FAILED) == 1
    assert ctx.repo.get_source(registration.source.id).status is SourceStatus.REGISTERED
    # Only the failed run row is new; no blob, artifact, I/O, lineage or raw_ingested audit.
    assert state_counts(ctx) == {**before, "processing_run": before["processing_run"] + 1}
    assert ctx.repo.count(EntityType.ARTIFACT) == 0
    assert ctx.repo.list_run_io(failed[0].id) == []
    assert [e.event_type.value for e in ctx.repo.list_audit_events()] == [
        "policy_created",
        "source_registered",
    ]


@pytest.mark.parametrize(
    "document",
    [
        # Malformed YAML that echoes the title sentinel.
        f"manifest_version: 1\ntitle: {TITLE_SENTINEL}\n  broken: [\n",
        # Field validation: the key pattern rejects uppercase and includes a sentinel.
        f"manifest_version: 1\nkey: {TITLE_SENTINEL}\n",
    ],
    ids=["malformed-yaml", "field-validation-failure"],
)
def test_manifest_failures_do_not_echo_input(
    ctx: AppContext,
    tmp_path: Path,
    document: str,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG, logger="langpipe")
    path = tmp_path / "bad.yaml"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(SchemaViolation) as info:
        register_source(ctx, path)

    assert TITLE_SENTINEL not in str(info.value)
    assert info.value.__cause__ is None
    _assert_no_sentinel(ctx, *_streams(capsys), caplog)
    assert ctx.repo.count_runs() == 0


def test_custom_validator_failure_does_not_echo_input(
    ctx: AppContext,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG, logger="langpipe")
    write_origin_file(tmp_path, f"texts/{FILENAME_SENTINEL}.txt", b"public\n")
    # A complete manifest whose object is more permissive than its restricted policy:
    # the model validator in SourceManifest rejects it, not a missing-field check.
    data = manifest_data(
        key="custom-validator",
        title=TITLE_SENTINEL,
        mode="restricted",
        access_class="restricted",
        objects=[
            {
                "path": f"texts/{FILENAME_SENTINEL}.txt",
                "media_type": "text/plain",
                "access_class": "public",
            }
        ],
    )
    with pytest.raises(ValidationError, match="must not be more permissive"):
        SourceManifest.model_validate(data)
    path = write_manifest(tmp_path, data, name="custom.yaml")

    with pytest.raises(SchemaViolation) as info:
        register_source(ctx, path)

    assert str(info.value) == "schema violation"
    assert info.value.__cause__ is None
    _assert_no_sentinel(ctx, *_streams(capsys), caplog)
    assert ctx.repo.count_runs() == 0
    assert ctx.repo.count(EntityType.SOURCE) == 0
