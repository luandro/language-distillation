from pathlib import Path

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
)
from langpipe.domain.errors import ImmutableViolation, InvalidLineage
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.run import Artifact
from langpipe.ingestion.registration import RegistrationResult, register_source
from langpipe.ingestion.runs import RunRecorder
from tests.service.manifests import (
    manifest_data,
    state_counts,
    write_manifest,
    write_origin_file,
)

SHA = "a" * 64
MISSING_OBJECT_ID = "sobj_" + "0" * 26


def _register(ctx: AppContext, tmp_path: Path, key: str = "fail-src") -> RegistrationResult:
    relative = f"texts/{key}.txt"
    write_origin_file(tmp_path, relative, b"origin bytes\n")
    data = manifest_data(key=key, objects=[{"path": relative, "media_type": "text/plain"}])
    return register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))


def _start(ctx: AppContext, input_ids: list[str]) -> str:
    return RunRecorder(ctx).start(RunStage.EXTRACTION, "langpipe.test", {}, input_ids).id


def _artifact(
    ctx: AppContext, run_id: str, kind: ArtifactKind = ArtifactKind.EXTRACTION_ERROR
) -> Artifact:
    return Artifact(
        id=ctx.new_id(IdPrefix.ARTIFACT),
        run_id=run_id,
        kind=kind,
        media_type="application/json",
        sha256=SHA,
        size_bytes=2,
        access_class=AccessClass.PUBLIC,
        created_at=ctx.clock(),
    )


def test_fail_with_artifact_records_output_and_lineage(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register(ctx, tmp_path)
    sobj = registered.objects[0]
    run_id = _start(ctx, [sobj.id])
    artifact = _artifact(ctx, run_id)

    failed = RunRecorder(ctx).fail(
        run_id, ValueError("boom"), artifact=artifact, artifact_inputs=[sobj.id]
    )

    assert failed.status is RunStatus.FAILED
    assert failed.error_type == "ValueError"
    assert failed.error_message is None
    assert ctx.repo.get_artifact(artifact.id) == artifact
    run_io = set(ctx.repo.list_run_io(run_id))
    assert (artifact.id, RunIoRole.OUTPUT) in run_io
    edges = ctx.repo.list_lineage_edges(artifact.id, "out")
    assert [(e.to_id, e.kind) for e in edges] == [(sobj.id, LineageKind.DERIVED_FROM)]


def test_fail_rejects_artifact_from_other_run(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register(ctx, tmp_path, "mismatch-src")
    sobj = registered.objects[0]
    first_run = _start(ctx, [sobj.id])
    second_run = _start(ctx, [sobj.id])
    artifact = _artifact(ctx, second_run)
    before = state_counts(ctx)

    with pytest.raises(InvalidLineage):
        RunRecorder(ctx).fail(
            first_run,
            ValueError("boom"),
            artifact=artifact,
            artifact_inputs=[sobj.id],
        )

    assert ctx.repo.get_run(first_run).status is RunStatus.RUNNING
    assert ctx.repo.get_run(second_run).status is RunStatus.RUNNING
    assert state_counts(ctx) == before
    assert ctx.repo.count(EntityType.ARTIFACT) == 0
    assert ctx.repo.list_run_io(first_run) == []
    assert ctx.repo.list_run_io(second_run) == []
    assert ctx.repo.list_lineage_edges(artifact.id, "out") == []


def test_fail_without_artifact_keeps_m1_behavior(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register(ctx, tmp_path, "m1-src")
    sobj = registered.objects[0]
    run_id = _start(ctx, [sobj.id])
    before = state_counts(ctx)

    failed = RunRecorder(ctx).fail(run_id, RuntimeError("x"))

    assert failed.status is RunStatus.FAILED
    assert failed.error_type == "RuntimeError"
    assert ctx.repo.list_run_io(run_id) == []
    assert ctx.repo.count(EntityType.ARTIFACT) == 0
    assert state_counts(ctx) == before


def test_fail_never_persists_exception_message(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register(ctx, tmp_path, "redact-src")
    sobj = registered.objects[0]
    run_id = _start(ctx, [sobj.id])
    sentinel = "RESTRICTED-SENTINEL-TEXT"

    failed = RunRecorder(ctx).fail(run_id, ValueError(sentinel))

    assert failed.error_type == "ValueError"
    assert failed.error_message is None
    assert ctx.repo.get_run(run_id).error_message is None


def test_fail_artifact_rolls_back_on_invalid_lineage(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register(ctx, tmp_path, "rollback-lineage")
    sobj = registered.objects[0]
    run_id = _start(ctx, [sobj.id])
    artifact = _artifact(ctx, run_id)
    before = state_counts(ctx)

    with pytest.raises(InvalidLineage):
        RunRecorder(ctx).fail(
            run_id,
            ValueError("boom"),
            artifact=artifact,
            artifact_inputs=[MISSING_OBJECT_ID],
        )

    assert ctx.repo.get_run(run_id).status is RunStatus.RUNNING
    assert state_counts(ctx) == before
    assert ctx.repo.list_run_io(run_id) == []


def test_fail_artifact_rolls_back_on_invalid_artifact(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register(ctx, tmp_path, "rollback-artifact")
    sobj = registered.objects[0]
    run_id = _start(ctx, [sobj.id])
    existing = _artifact(ctx, run_id, kind=ArtifactKind.OTHER)
    with ctx.repo.transaction():
        ctx.repo.add_artifact(existing)
    before = state_counts(ctx)

    with pytest.raises(ImmutableViolation):
        RunRecorder(ctx).fail(
            run_id,
            ValueError("boom"),
            artifact=existing,
            artifact_inputs=[sobj.id],
        )

    assert ctx.repo.get_run(run_id).status is RunStatus.RUNNING
    assert state_counts(ctx) == before
    assert ctx.repo.get_artifact(existing.id) == existing
    assert ctx.repo.list_run_io(run_id) == []
