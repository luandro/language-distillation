from pathlib import Path

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AccessClass,
    AuditEventType,
    EntityType,
    LineageKind,
    Operation,
    PolicyDecision,
    PolicyMode,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
)
from langpipe.domain.errors import PolicyDenied, SchemaViolation, SourceConflict
from langpipe.domain.hashing import config_hash, sha256_bytes
from langpipe.domain.models.run import ProcessingRun
from langpipe.domain.models.source import SourceManifest
from langpipe.governance.policy import resolve
from langpipe.ingestion.registration import load_manifest, register_source
from langpipe.ingestion.runs import TOOL_VERSION
from tests.service.manifests import (
    is_success_transition,
    manifest_data,
    raise_on,
    record_finished_runs,
    state_counts,
    write_manifest,
    write_origin_file,
)


def _two_object_manifest(tmp_path: Path) -> Path:
    write_origin_file(tmp_path, "texts/a.txt", b"alpha text\n")
    write_origin_file(tmp_path, "texts/b.txt", b"beta text\n")
    objects = [
        {"path": "texts/a.txt", "media_type": "text/plain"},
        {"path": "texts/b.txt", "media_type": "text/plain"},
    ]
    return write_manifest(tmp_path, manifest_data(objects=objects))


def test_register_creates_source_policy_objects_run_and_edges(
    ctx: AppContext, tmp_path: Path
) -> None:
    manifest_path = _two_object_manifest(tmp_path)
    manifest = load_manifest(manifest_path)

    result = register_source(ctx, manifest_path)

    assert result.reused is False
    assert result.source.status is SourceStatus.REGISTERED
    assert result.source.key == "test-source"
    assert result.source.manifest_sha256 == manifest.manifest_sha256()
    assert result.source.registration_run_id == result.run.id
    assert ctx.repo.get_source(result.source.id) == result.source
    assert ctx.repo.get_policy(result.policy.id) == result.policy
    assert result.policy.mode is PolicyMode.DIRECT

    by_path = {obj.original_path: obj for obj in result.objects}
    assert set(by_path) == {"texts/a.txt", "texts/b.txt"}
    assert by_path["texts/a.txt"].sha256 == sha256_bytes(b"alpha text\n")
    assert by_path["texts/a.txt"].origin_uri.startswith("file:///")
    assert by_path["texts/a.txt"].access_class is AccessClass.PUBLIC

    assert result.run.stage is RunStage.SOURCE_REGISTRATION
    assert result.run.tool_name == "langpipe.register"
    assert result.run.status is RunStatus.SUCCEEDED
    assert result.run.code_revision == "test-rev"
    assert result.run.tool_version == TOOL_VERSION
    assert result.run.config == {"manifest_sha256": manifest.manifest_sha256()}
    assert result.run.config_hash == config_hash(result.run.config)
    assert result.run.run_key == ProcessingRun.compute_run_key(
        RunStage.SOURCE_REGISTRATION,
        "langpipe.register",
        TOOL_VERSION,
        result.run.config_hash,
        [],
    )
    assert ctx.repo.get_run(result.run.id) == result.run

    for obj in result.objects:
        edges = ctx.repo.list_lineage_edges(obj.id, "out")
        assert [(e.kind, e.to_id, e.run_id) for e in edges] == [
            (LineageKind.IMPORTED_FROM, result.source.id, result.run.id)
        ]
    assert ctx.repo.count_lineage_edges() == 2

    io = set(ctx.repo.list_run_io(result.run.id))
    assert io == {
        (result.source.id, RunIoRole.OUTPUT),
        (by_path["texts/a.txt"].id, RunIoRole.OUTPUT),
        (by_path["texts/b.txt"].id, RunIoRole.OUTPUT),
    }

    events = ctx.repo.list_audit_events()
    assert [e.event_type for e in events] == [
        AuditEventType.POLICY_CREATED,
        AuditEventType.SOURCE_REGISTERED,
    ]
    assert events[1].subject_id == result.source.id
    assert events[1].details == {"mode": "direct", "objects": 2}
    assert all(e.actor == "test-actor" for e in events)


def test_register_same_manifest_twice_is_noop(ctx: AppContext, tmp_path: Path) -> None:
    manifest_path = _two_object_manifest(tmp_path)
    first = register_source(ctx, manifest_path)
    before = state_counts(ctx)

    second = register_source(ctx, manifest_path)

    assert second.reused is True
    assert second.source == first.source
    assert second.run == first.run
    assert second.objects == first.objects
    assert state_counts(ctx) == before


def test_register_changed_manifest_same_key_raises_source_conflict(
    ctx: AppContext, tmp_path: Path
) -> None:
    manifest_path = _two_object_manifest(tmp_path)
    register_source(ctx, manifest_path)
    before = state_counts(ctx)

    changed = manifest_data(
        title="A different title",
        objects=[
            {"path": "texts/a.txt", "media_type": "text/plain"},
            {"path": "texts/b.txt", "media_type": "text/plain"},
        ],
    )
    changed_path = write_manifest(tmp_path, changed, name="changed.yaml")

    with pytest.raises(SourceConflict):
        register_source(ctx, changed_path)
    assert state_counts(ctx) == before


def test_register_missing_file_rolls_back_atomically(ctx: AppContext, tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, manifest_data())  # texts/a.txt does not exist

    with pytest.raises(SchemaViolation):
        register_source(ctx, manifest_path)

    assert ctx.repo.count(EntityType.SOURCE) == 0
    assert ctx.repo.count(EntityType.SOURCE_OBJECT) == 0
    assert ctx.repo.count_runs() == 0
    assert ctx.repo.count_lineage_edges() == 0
    assert ctx.repo.list_audit_events() == []


@pytest.mark.parametrize(
    "failing", ["add_source_object", "add_lineage_edge", "add_audit_event", "finish_run"]
)
def test_late_registration_failure_rolls_back_semantic_rows_and_records_failed_run(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    manifest_path = _two_object_manifest(tmp_path)
    finished = record_finished_runs(ctx, monkeypatch)
    before = state_counts(ctx)
    when = is_success_transition if failing == "finish_run" else (lambda args: True)

    with raise_on(ctx.repo, failing, SchemaViolation(), when), pytest.raises(SchemaViolation):
        register_source(ctx, manifest_path)

    # Policy, source, objects and edges roll back; only the committed failed run remains.
    assert state_counts(ctx) == {**before, "processing_run": before["processing_run"] + 1}
    assert ctx.repo.count(EntityType.SOURCE) == 0
    failed = [run for run in finished if run.status is RunStatus.FAILED]
    assert len(failed) == 1
    assert failed[0].stage is RunStage.SOURCE_REGISTRATION
    assert failed[0].error_type == SchemaViolation.__name__
    assert failed[0].error_message is None
    assert ctx.repo.list_run_io(failed[0].id) == []


@pytest.mark.parametrize("method", ["resolve", "is_file"])
def test_register_preflight_resolution_failure_creates_nothing(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    manifest_path = _two_object_manifest(tmp_path)
    before = state_counts(ctx)

    def denied(self: Path, *args: object, **kwargs: object) -> object:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, method, denied)

    with pytest.raises(SchemaViolation) as info:
        register_source(ctx, manifest_path)

    assert str(info.value) == "schema violation"
    assert info.value.__suppress_context__ is True
    assert state_counts(ctx) == before


def test_register_rejects_path_escaping_manifest_dir(ctx: AppContext, tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifest"
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside the manifest directory\n")
    manifest_dir.mkdir()
    (manifest_dir / "link.txt").symlink_to(outside)
    manifest_path = write_manifest(
        manifest_dir,
        manifest_data(objects=[{"path": "link.txt", "media_type": "text/plain"}]),
    )

    with pytest.raises(SchemaViolation):
        register_source(ctx, manifest_path)

    assert ctx.repo.count_runs() == 0
    assert ctx.repo.count(EntityType.SOURCE_OBJECT) == 0


def test_register_exclude_records_source_without_objects(ctx: AppContext, tmp_path: Path) -> None:
    # The object path does not exist; exclude mode must not read or hash any origin file.
    manifest_path = write_manifest(
        tmp_path,
        manifest_data(
            mode=PolicyMode.EXCLUDE.value,
            objects=[{"path": "missing.txt", "media_type": "text/plain"}],
        ),
    )

    result = register_source(ctx, manifest_path)

    assert result.objects == ()
    assert ctx.repo.count(EntityType.SOURCE) == 1
    assert ctx.repo.count(EntityType.SOURCE_OBJECT) == 0
    assert ctx.repo.get_run(result.run.id).status is RunStatus.SUCCEEDED


def test_register_ingest_denied_creates_nothing(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_origin_file(tmp_path, "texts/a.txt", b"alpha text\n")
    denied = write_manifest(
        tmp_path,
        manifest_data(deny=[Operation.INGEST.value]),
    )
    opened: list[str] = []
    original_open = Path.open

    def recording_open(self: Path, *args: object, **kwargs: object) -> object:
        opened.append(self.name)
        return original_open(self, *args, **kwargs)  # type: ignore[arg-type]

    hashed: list[str] = []

    def recording_hash(path: Path) -> tuple[str, int]:
        hashed.append(path.name)
        raise AssertionError("origin must not be hashed before the policy gate")

    monkeypatch.setattr(Path, "open", recording_open)
    monkeypatch.setattr("langpipe.ingestion.registration.sha256_file", recording_hash)
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied):
        register_source(ctx, denied)

    # The manifest itself is read; the origin is neither opened nor hashed.
    assert "a.txt" not in opened
    assert hashed == []
    assert state_counts(ctx) == before


def test_load_manifest_rejects_invalid_yaml_without_echoing_input(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("title: SENTINEL-TITLE-55\n  bad: [\n", encoding="utf-8")

    with pytest.raises(SchemaViolation) as info:
        load_manifest(path)

    assert "SENTINEL" not in str(info.value)
    assert info.value.__cause__ is None


def test_load_manifest_returns_validated_model(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, manifest_data())

    manifest = load_manifest(path)

    assert isinstance(manifest, SourceManifest)
    assert manifest.key == "test-source"
    assert manifest.resolved_policy.mode is PolicyMode.DIRECT


def test_manifest_without_policy_gets_presence_based_default(
    ctx: AppContext, tmp_path: Path
) -> None:
    # ADR-0025: a source added to the repo is authorized; no policy block required.
    write_origin_file(tmp_path, "texts/a.txt", b"alpha text\n")
    data = manifest_data()
    del data["policy"]
    manifest_path = write_manifest(tmp_path, data)

    result = register_source(ctx, manifest_path)

    assert result.policy.mode is PolicyMode.DIRECT
    assert result.policy.access_class is AccessClass.PUBLIC
    assert result.policy.authority == "repo-owner"
    assert result.source.policy_id == result.policy.id
    # ADR-0025: the default is trainable, but raw redistribution stays closed.
    assert resolve(result.policy, Operation.DIRECT_TRAINING) is PolicyDecision.ALLOW
    assert resolve(result.policy, Operation.REDISTRIBUTE_RAW) is PolicyDecision.DENY

    # The same manifest is idempotent: a rerun reuses the source and its policy id.
    again = register_source(ctx, manifest_path)
    assert again.reused is True
    assert again.source.id == result.source.id
    assert again.policy.id == result.policy.id


def test_explicit_null_policy_also_gets_presence_based_default(
    ctx: AppContext, tmp_path: Path
) -> None:
    # A `policy: null` block (rather than an absent key) behaves the same way.
    write_origin_file(tmp_path, "texts/a.txt", b"alpha text\n")
    data = manifest_data()
    data["policy"] = None
    manifest_path = write_manifest(tmp_path, data)

    result = register_source(ctx, manifest_path)

    assert result.policy.mode is PolicyMode.DIRECT
    assert result.policy.authority == "repo-owner"
    assert resolve(result.policy, Operation.DIRECT_TRAINING) is PolicyDecision.ALLOW
