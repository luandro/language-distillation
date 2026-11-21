"""ExtractionService (M2 WP2.9): Stage 2 bytes -> raw segments, lineage, run and report."""

import json
import logging
from pathlib import Path
from typing import ClassVar

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AccessClass,
    ArtifactKind,
    EntityType,
    LineageKind,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
)
from langpipe.domain.errors import (
    ExtractionFailed,
    PolicyDenied,
    SourceNotIngested,
    UnsupportedSource,
)
from langpipe.extraction.plain_lines import PlainLinesExtractor
from langpipe.extraction.service import ExtractionResult, extract_source
from langpipe.extraction.tsv import TsvExtractor
from langpipe.extraction.usfm import UsfmExtractor
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import RegistrationResult, register_source
from langpipe.text.registry import VersionedRegistry
from tests.service.manifests import (
    manifest_data,
    record_finished_runs,
    spy_all_io,
    state_counts,
    write_manifest,
    write_origin_file,
)

GOLDEN_SOURCES = Path(__file__).resolve().parents[1] / "golden" / "fixture" / "sources"
TSV = "text/tab-separated-values"
PLAIN = "text/plain"
SENTINEL = "SENTINEL-RESTRICTED-9d2f"


def _write_source(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    objects: list[dict[str, object]],
    *,
    mode: str = "direct",
    source_type: str = "parallel_text",
    languages: tuple[str, ...] = ("qaa",),
    access_class: str = "public",
) -> RegistrationResult:
    data = manifest_data(key=key, mode=mode, access_class=access_class, objects=objects)
    data["source_type"] = source_type
    data["languages"] = list(languages)
    return register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))


def _golden_01(ctx: AppContext) -> RegistrationResult:
    return register_source(ctx, GOLDEN_SOURCES / "01-parallel-distill" / "manifest.yaml")


def test_extract_exclude_and_archive_only_denied_before_any_work(
    ctx: AppContext, tmp_path: Path
) -> None:
    write_origin_file(tmp_path, "texts/a.tsv", b"qaa\nkanu\n")
    archived = _write_source(
        ctx,
        tmp_path,
        "arch-src",
        [{"path": "texts/a.tsv", "media_type": TSV}],
        mode="archive_only",
    )
    ingest_source(ctx, archived.source.id)
    excluded = _write_source(ctx, tmp_path, "excl-src", [], mode="exclude")
    before = state_counts(ctx)

    for source_id in (archived.source.id, excluded.source.id):
        with spy_all_io(ctx) as mocks, pytest.raises(PolicyDenied):
            extract_source(ctx, source_id)
        assert all(mock.call_count == 0 for mock in mocks)

    assert state_counts(ctx) == {**before, "audit": before["audit"] + 2}


def test_extract_review_required_denied(ctx: AppContext) -> None:
    registered = register_source(ctx, GOLDEN_SOURCES / "04-igt" / "manifest.yaml")
    ingest_source(ctx, registered.source.key)
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied):
        extract_source(ctx, registered.source.id)

    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}


def test_extract_revoked_source_denied(ctx: AppContext, tmp_path: Path) -> None:
    write_origin_file(tmp_path, "texts/a.tsv", b"qaa\nkanu\n")
    registered = _write_source(
        ctx, tmp_path, "rev-src", [{"path": "texts/a.tsv", "media_type": TSV}]
    )
    ingest_source(ctx, registered.source.id)
    with ctx.repo.transaction():
        ctx.repo.set_source_status(registered.source.id, SourceStatus.REVOKED, ctx.clock())
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied):
        extract_source(ctx, registered.source.id)

    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}


def test_extract_requires_ingestion(ctx: AppContext, tmp_path: Path) -> None:
    write_origin_file(tmp_path, "texts/a.tsv", b"qaa\nkanu\n")
    registered = _write_source(
        ctx, tmp_path, "not-ing", [{"path": "texts/a.tsv", "media_type": TSV}]
    )
    before = state_counts(ctx)

    with pytest.raises(SourceNotIngested):
        extract_source(ctx, registered.source.id)

    assert state_counts(ctx) == before


def test_extract_creates_segments_lineage_run_io_and_report(ctx: AppContext) -> None:
    registered = _golden_01(ctx)
    ingest_source(ctx, registered.source.key)
    sobj = registered.objects[0]

    result = extract_source(ctx, registered.source.id)

    assert isinstance(result, ExtractionResult)
    assert result.reused is False
    assert result.segments == 8
    assert result.skipped_objects == ()
    assert result.run.stage is RunStage.EXTRACTION
    assert result.run.tool_name == "langpipe.extract"
    assert result.run.status is RunStatus.SUCCEEDED
    assert result.run.config == {"extractors": {sobj.id: "tsv@0.1.0"}, "language": None}

    segments = ctx.repo.list_segments_for_run(result.run.id)
    assert len(segments) == 8
    for segment in segments:
        edges = ctx.repo.list_lineage_edges(segment.id, "out")
        assert [(e.kind, e.to_id, e.run_id) for e in edges] == [
            (LineageKind.EXTRACTED_FROM, sobj.id, result.run.id)
        ]

    assert result.report is not None
    run_io = set(ctx.repo.list_run_io(result.run.id))
    assert (sobj.id, RunIoRole.INPUT) in run_io
    assert (result.report.id, RunIoRole.OUTPUT) in run_io
    assert {(segment.id, RunIoRole.OUTPUT) for segment in segments} <= run_io

    report = result.report
    assert report.kind is ArtifactKind.EXTRACTION_REPORT
    assert report.schema_name == "extraction-report"
    assert report.schema_version == 1
    assert report.access_class is AccessClass.COMMUNITY
    ctx.artifact_store.verify(report.sha256)
    raw_report = ctx.artifact_store.read_bytes(report.sha256)
    assert b"kanu" not in raw_report
    assert b"kanu mabi tesa." not in raw_report
    payload = json.loads(raw_report)
    assert payload["schema"] == "extraction-report"
    assert payload["source_id"] == registered.source.id
    assert payload["run_id"] == result.run.id
    assert payload["skipped"] == []
    assert len(payload["objects"]) == 1
    only = payload["objects"][0]
    assert only["source_object_id"] == sobj.id
    assert only["extractor"] == "tsv@0.1.0"
    assert only["units"] == 8
    assert only["empty_units"] == []

    artifact_edges = ctx.repo.list_lineage_edges(report.id, "out")
    assert [(e.kind, e.to_id, e.run_id) for e in artifact_edges] == [
        (LineageKind.DERIVED_FROM, sobj.id, result.run.id)
    ]


def test_extract_rerun_is_idempotent(ctx: AppContext) -> None:
    registered = _golden_01(ctx)
    ingest_source(ctx, registered.source.key)
    first = extract_source(ctx, registered.source.id)
    before = state_counts(ctx)

    second = extract_source(ctx, registered.source.id)

    assert second.reused is True
    assert second.run == first.run
    assert second.segments == first.segments == 8
    assert second.report == first.report
    assert second.skipped_objects == first.skipped_objects
    assert state_counts(ctx) == before


class _TsvV2(TsvExtractor):
    version: ClassVar[str] = "0.1.1"


def test_extract_new_extractor_version_creates_new_run_and_keeps_old_segments(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = _golden_01(ctx)
    ingest_source(ctx, registered.source.key)
    first = extract_source(ctx, registered.source.id)

    patched = VersionedRegistry((TsvExtractor(), PlainLinesExtractor(), UsfmExtractor(), _TsvV2()))
    monkeypatch.setattr("langpipe.extraction.service.EXTRACTORS", patched)

    second = extract_source(ctx, registered.source.id, extractor="tsv@0.1.1")

    assert second.reused is False
    assert second.run.id != first.run.id
    assert len(ctx.repo.list_segments_for_run(first.run.id)) == 8
    assert len(ctx.repo.list_segments_for_run(second.run.id)) == 8
    assert second.run.config["extractors"] == {registered.objects[0].id: "tsv@0.1.1"}


def test_extract_failure_leaves_no_segments_and_records_error_artifact(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_origin_file(tmp_path, "texts/a.tsv", b"qaa\nkanu\n")
    write_origin_file(tmp_path, "texts/b.tsv", b"qaa\nkanu\textra\n")
    registered = _write_source(
        ctx,
        tmp_path,
        "fail-src",
        [
            {"path": "texts/a.tsv", "media_type": TSV},
            {"path": "texts/b.tsv", "media_type": TSV},
        ],
    )
    ingest_source(ctx, registered.source.id)
    finished = record_finished_runs(ctx, monkeypatch)
    before = state_counts(ctx)

    with pytest.raises(ExtractionFailed):
        extract_source(ctx, registered.source.id)

    assert ctx.repo.count(EntityType.SEGMENT) == 0
    assert state_counts(ctx) == {
        **before,
        "artifact": before["artifact"] + 1,
        "processing_run": before["processing_run"] + 1,
        "lineage": before["lineage"] + 1,
    }
    failed = [run for run in finished if run.status is RunStatus.FAILED]
    assert len(failed) == 1
    assert failed[0].stage is RunStage.EXTRACTION
    assert failed[0].error_type == ExtractionFailed.__name__
    assert failed[0].error_message is None

    run_io = ctx.repo.list_run_io(failed[0].id)
    assert len(run_io) == 1
    artifact_id, role = run_io[0]
    assert role is RunIoRole.OUTPUT
    artifact = ctx.repo.get_artifact(artifact_id)
    assert artifact.kind is ArtifactKind.EXTRACTION_ERROR
    payload = json.loads(ctx.artifact_store.read_bytes(artifact.sha256))
    assert payload == {
        "schema": "extraction-error",
        "schema_version": 1,
        "source_object_id": registered.objects[1].id,
        "code": "tsv_ragged_row",
        "line": 2,
    }
    edges = ctx.repo.list_lineage_edges(artifact.id, "out")
    assert [(e.kind, e.to_id, e.run_id) for e in edges] == [
        (LineageKind.DERIVED_FROM, registered.objects[1].id, failed[0].id)
    ]


def test_extract_reads_only_from_raw_store(ctx: AppContext, tmp_path: Path) -> None:
    origin = write_origin_file(tmp_path, "texts/a.tsv", b"qaa\nkanu\n")
    registered = _write_source(
        ctx, tmp_path, "raw-src", [{"path": "texts/a.tsv", "media_type": TSV}]
    )
    ingest_source(ctx, registered.source.id)
    origin.unlink()

    result = extract_source(ctx, registered.source.id)

    segments = ctx.repo.list_segments_for_run(result.run.id)
    assert [segment.raw_text for segment in segments] == ["kanu"]


def test_raw_store_bytes_unchanged_by_extraction(ctx: AppContext) -> None:
    registered = _golden_01(ctx)
    ingest_source(ctx, registered.source.key)
    digests = [obj.sha256 for obj in registered.objects]
    before = {digest: ctx.raw_store.read_bytes(digest) for digest in digests}

    extract_source(ctx, registered.source.id)

    after = {digest: ctx.raw_store.read_bytes(digest) for digest in digests}
    assert after == before


def test_extract_igt_source_unsupported(ctx: AppContext, tmp_path: Path) -> None:
    write_origin_file(tmp_path, "texts/igt.txt", b"\\ref X\n\\t a b\n")
    registered = _write_source(
        ctx,
        tmp_path,
        "igt-src",
        [{"path": "texts/igt.txt", "media_type": PLAIN}],
        source_type="igt",
    )
    ingest_source(ctx, registered.source.id)
    before = state_counts(ctx)

    with pytest.raises(UnsupportedSource) as info:
        extract_source(ctx, registered.source.id)

    assert info.value.reason == "no_extractor"
    assert state_counts(ctx) == before

    with pytest.raises(UnsupportedSource) as override_info:
        extract_source(ctx, registered.source.id, extractor="plain_lines@0.1.0")

    assert override_info.value.reason == "no_extractor"
    assert state_counts(ctx) == before


def test_extract_logs_no_text(
    ctx: AppContext,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG, logger="langpipe")
    write_origin_file(tmp_path, "texts/a.tsv", f"qaa\n{SENTINEL}\n".encode())
    registered = _write_source(
        ctx, tmp_path, "log-src", [{"path": "texts/a.tsv", "media_type": TSV}]
    )
    ingest_source(ctx, registered.source.id)

    result = extract_source(ctx, registered.source.id)

    captured = capsys.readouterr()
    audit = json.dumps([event.model_dump(mode="json") for event in ctx.repo.list_audit_events()])
    assert result.report is not None
    report = ctx.artifact_store.read_bytes(result.report.sha256).decode("utf-8")
    for text in (caplog.text, captured.out, captured.err, audit, report):
        assert SENTINEL not in text
    assert "event=extraction.succeeded" in caplog.text
