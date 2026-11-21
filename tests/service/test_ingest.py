import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AccessClass,
    ArtifactKind,
    AuditEventType,
    EntityType,
    LineageKind,
    PolicyDecision,
    PolicyMode,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
)
from langpipe.domain.errors import NotFound, PolicyDenied, SchemaViolation, SourceChanged
from langpipe.domain.hashing import config_hash, sha256_bytes
from langpipe.domain.models.run import ProcessingRun
from langpipe.ingestion.ingest import IngestResult, ingest_source
from langpipe.ingestion.registration import RegistrationResult, register_source
from langpipe.ingestion.runs import TOOL_VERSION
from tests.service.manifests import (
    is_success_transition,
    manifest_data,
    raise_on,
    record_finished_runs,
    spy_all_io,
    state_counts,
    write_manifest,
    write_origin_file,
)


@dataclass
class _Registered:
    registration: RegistrationResult
    origin: Path


def _register(ctx: AppContext, tmp_path: Path, mode: str = "direct") -> _Registered:
    origin = write_origin_file(tmp_path, "texts/a.txt", b"alpha text\n")
    write_origin_file(tmp_path, "texts/b.txt", b"beta text\n")
    objects = [
        {"path": "texts/a.txt", "media_type": "text/plain"},
        {"path": "texts/b.txt", "media_type": "text/plain"},
    ]
    if mode == "exclude":
        objects = []
    path = write_manifest(tmp_path, manifest_data(mode=mode, objects=objects))
    return _Registered(registration=register_source(ctx, path), origin=origin)


def test_exclude_policy_denies_before_any_work(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register(ctx, tmp_path, mode=PolicyMode.EXCLUDE.value)
    before = state_counts(ctx)

    with spy_all_io(ctx) as mocks, pytest.raises(PolicyDenied):
        ingest_source(ctx, registered.registration.source.id)

    assert all(mock.call_count == 0 for mock in mocks)
    # Only the single policy_denied audit row may be added by a denial.
    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}
    new_events = ctx.repo.list_audit_events()[-1:]
    assert [e.event_type for e in new_events] == [AuditEventType.POLICY_DENIED]
    assert new_events[0].details == {"operation": "ingest", "decision": "deny"}
    assert new_events[0].subject_id == registered.registration.source.id
    assert ctx.repo.get_source(registered.registration.source.id).status is SourceStatus.REGISTERED


def test_ingest_policy_gate_precedes_origin_reads(ctx: AppContext, tmp_path: Path) -> None:
    # Direct source with readable origins; only the gate decision is denied.
    registered = _register(ctx, tmp_path)
    before = state_counts(ctx)

    with (
        spy_all_io(ctx) as mocks,
        patch(
            "langpipe.ingestion.ingest.resolve",
            return_value=PolicyDecision.DENY,
        ),
        pytest.raises(PolicyDenied),
    ):
        ingest_source(ctx, registered.registration.source.id)

    assert all(mock.call_count == 0 for mock in mocks)
    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}


def test_archive_only_allows_ingest(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register(ctx, tmp_path, mode=PolicyMode.ARCHIVE_ONLY.value)

    result = ingest_source(ctx, registered.registration.source.id)

    assert result.reused is False
    assert result.source.status is SourceStatus.INGESTED
    assert ctx.repo.count_raw_blobs() == 2


def test_ingest_creates_complete_source_run_lineage_records(
    ctx: AppContext, tmp_path: Path
) -> None:
    registered = _register(ctx, tmp_path)
    source = registered.registration.source
    objects = registered.registration.objects

    result = ingest_source(ctx, source.id)

    assert isinstance(result, IngestResult)
    assert result.source.status is SourceStatus.INGESTED
    assert ctx.repo.get_source(source.id).status is SourceStatus.INGESTED

    # Two succeeded runs: registration and ingestion.
    assert ctx.repo.count_runs(RunStatus.SUCCEEDED) == 2
    reg_run = registered.registration.run
    assert reg_run.stage is RunStage.SOURCE_REGISTRATION
    assert reg_run.tool_name == "langpipe.register"
    assert reg_run.code_revision == "test-rev"
    assert reg_run.config == {"manifest_sha256": source.manifest_sha256}
    assert reg_run.config_hash == config_hash(reg_run.config)
    assert reg_run.run_key == ProcessingRun.compute_run_key(
        RunStage.SOURCE_REGISTRATION,
        "langpipe.register",
        TOOL_VERSION,
        reg_run.config_hash,
        [],
    )

    run = result.run
    assert run.stage is RunStage.RAW_INGESTION
    assert run.tool_name == "langpipe.ingest"
    assert run.status is RunStatus.SUCCEEDED
    assert run.code_revision == "test-rev"
    assert run.tool_version == TOOL_VERSION
    assert run.config == {}
    assert run.config_hash == config_hash({})
    assert run.run_key == ProcessingRun.compute_run_key(
        RunStage.RAW_INGESTION,
        "langpipe.ingest",
        TOOL_VERSION,
        config_hash({}),
        [obj.id for obj in objects],
    )

    expected_io = {(obj.id, RunIoRole.INPUT) for obj in objects}
    assert result.report is not None
    expected_io.add((result.report.id, RunIoRole.OUTPUT))
    assert set(ctx.repo.list_run_io(run.id)) == expected_io

    # One raw blob per distinct sha256, stamped with the ingestion run.
    assert ctx.repo.count_raw_blobs() == 2
    for obj in objects:
        blob = ctx.repo.get_raw_blob(obj.sha256)
        assert blob is not None
        assert blob.ingestion_run_id == run.id
        assert blob.size_bytes == obj.size_bytes

    for obj in objects:
        out = ctx.repo.list_lineage_edges(obj.id, "out")
        assert [(e.kind, e.to_id, e.run_id) for e in out] == [
            (LineageKind.IMPORTED_FROM, source.id, reg_run.id)
        ]
    artifact_out = ctx.repo.list_lineage_edges(result.report.id, "out")
    assert {(e.kind, e.to_id, e.run_id) for e in artifact_out} == {
        (LineageKind.DERIVED_FROM, obj.id, run.id) for obj in objects
    }

    descendant_ids = {node for node, _ in ctx.repo.descendants(source.id)}
    assert descendant_ids >= {obj.id for obj in objects} | {result.report.id}

    report = result.report
    assert report.kind is ArtifactKind.INGEST_REPORT
    assert report.schema_name == "ingest-report"
    assert report.schema_version == 1
    assert report.media_type == "application/json"
    assert report.run_id == run.id
    ctx.artifact_store.verify(report.sha256)
    raw_report = ctx.artifact_store.read_bytes(report.sha256)
    assert b"alpha text" not in raw_report
    expected_report = {
        "schema": "ingest-report",
        "schema_version": 1,
        "source_id": source.id,
        "run_id": run.id,
        "objects": sorted(
            (
                {"source_object_id": o.id, "sha256": o.sha256, "size_bytes": o.size_bytes}
                for o in objects
            ),
            key=lambda item: item["source_object_id"],
        ),
    }
    payload = json.loads(raw_report)
    payload["objects"] = sorted(payload["objects"], key=lambda item: item["source_object_id"])
    assert payload == expected_report

    events = ctx.repo.list_audit_events()
    assert [e.event_type for e in events] == [
        AuditEventType.POLICY_CREATED,
        AuditEventType.SOURCE_REGISTERED,
        AuditEventType.RAW_INGESTED,
    ]


def test_report_takes_most_restrictive_object_access_class(ctx: AppContext, tmp_path: Path) -> None:
    write_origin_file(tmp_path, "texts/a.txt", b"public text\n")
    write_origin_file(tmp_path, "texts/b.txt", b"restricted text\n")
    path = write_manifest(
        tmp_path,
        manifest_data(
            objects=[
                {"path": "texts/a.txt", "media_type": "text/plain"},
                {
                    "path": "texts/b.txt",
                    "media_type": "text/plain",
                    "access_class": "restricted",
                },
            ]
        ),
    )
    source = register_source(ctx, path).source

    result = ingest_source(ctx, source.id)

    assert result.report is not None
    assert result.report.access_class is AccessClass.RESTRICTED


def test_rerun_identical_registration_and_ingestion_is_idempotent(
    ctx: AppContext, tmp_path: Path
) -> None:
    registered = _register(ctx, tmp_path)
    manifest_path = tmp_path / "manifest.yaml"
    first_ingest = ingest_source(ctx, registered.registration.source.id)
    first_counts = state_counts(ctx)

    second_registration = register_source(ctx, manifest_path)
    second_ingest = ingest_source(ctx, registered.registration.source.id)

    assert second_registration.reused is True
    assert second_ingest.reused is True
    assert second_ingest.run == first_ingest.run
    assert second_ingest.report == first_ingest.report
    assert state_counts(ctx) == first_counts


def test_two_objects_with_identical_bytes_share_one_blob_but_keep_two_source_objects(
    ctx: AppContext, tmp_path: Path
) -> None:
    write_origin_file(tmp_path, "texts/a.txt", b"same bytes\n")
    write_origin_file(tmp_path, "texts/b.txt", b"same bytes\n")
    path = write_manifest(
        tmp_path,
        manifest_data(
            objects=[
                {"path": "texts/a.txt", "media_type": "text/plain"},
                {"path": "texts/b.txt", "media_type": "text/plain"},
            ]
        ),
    )
    source = register_source(ctx, path).source

    result = ingest_source(ctx, source.id)

    assert ctx.repo.count(EntityType.SOURCE_OBJECT) == 2
    assert ctx.repo.count_raw_blobs() == 1
    assert [blob.sha256 for blob in result.blobs] == [sha256_bytes(b"same bytes\n")] * 2


def test_source_changed_after_registration_fails_run(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register(ctx, tmp_path)
    registered.origin.write_bytes(b"changed after registration\n")

    with pytest.raises(SourceChanged):
        ingest_source(ctx, registered.registration.source.id)

    assert ctx.repo.count_runs(RunStatus.FAILED) == 1
    assert ctx.repo.count_raw_blobs() == 0
    assert ctx.repo.get_source(registered.registration.source.id).status is (
        SourceStatus.REGISTERED
    )
    assert ctx.repo.count(EntityType.ARTIFACT) == 0


@pytest.mark.parametrize("failing", ["add_lineage_edge", "add_audit_event", "finish_run"])
def test_late_ingest_failure_rolls_back_semantic_rows_and_records_failed_run(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    registered = _register(ctx, tmp_path)
    source_id = registered.registration.source.id
    finished = record_finished_runs(ctx, monkeypatch)
    before = state_counts(ctx)
    when = is_success_transition if failing == "finish_run" else (lambda args: True)

    with raise_on(ctx.repo, failing, SchemaViolation(), when), pytest.raises(SchemaViolation):
        ingest_source(ctx, source_id)

    # Semantic rows roll back; only the separately committed failed run remains.
    assert state_counts(ctx) == {**before, "processing_run": before["processing_run"] + 1}
    assert ctx.repo.get_source(source_id).status is SourceStatus.REGISTERED
    failed = [run for run in finished if run.status is RunStatus.FAILED]
    assert len(failed) == 1
    assert failed[0].stage is RunStage.RAW_INGESTION
    assert failed[0].error_type == SchemaViolation.__name__
    assert failed[0].error_message is None
    assert ctx.repo.list_run_io(failed[0].id) == []


def test_ingest_by_key_resolves_the_same_source(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register(ctx, tmp_path)

    result = ingest_source(ctx, "test-source")

    assert result.source.id == registered.registration.source.id
    assert result.reused is False


def test_ingest_unknown_source_is_not_found(ctx: AppContext) -> None:
    with pytest.raises(NotFound):
        ingest_source(ctx, "no-such-source")
