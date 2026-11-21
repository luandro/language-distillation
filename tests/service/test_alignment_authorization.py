"""WP3.7 governed approval import: trusted-basis dispositions over immutable successors.

``import_disposition`` consumes a pre-registered ``alignment-authorization.v1`` basis
artifact: registered, valid lineage, succeeded producing run, trusted importer allowlist,
explicit actor match, exact member identity, HUMAN_REVIEW allowance and no revoked
ancestor. Anything less fails ``authorization_invalid``/``PolicyDenied`` before any run
exists. Success links the successor to predecessor (supersedes) and basis (imported_from)
and never mutates the predecessor (ADR-0011 §2). A rejected successor removes its
predecessor from active selection; conflicting live successors are an ambiguity, never
resolved by picking the latest.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from langpipe.alignment.base import AlignmentConfig, AlignmentSide
from langpipe.alignment.segment_service import (
    SegmentAlignmentService,
    active_segment_alignments,
)
from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AccessClass,
    AlignmentStatus,
    ArtifactKind,
    LineageKind,
    Operation,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
)
from langpipe.domain.errors import AlignmentFailed, AmbiguousInput, PolicyDenied
from langpipe.domain.hashing import canonical_json, config_hash
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.alignment import SegmentAlignment
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.run import Artifact, ProcessingRun
from langpipe.extraction.service import extract_source
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.normalization.service import normalize_extraction
from tests.service.manifests import manifest_data, state_counts, write_manifest, write_origin_file

TSV = "text/tab-separated-values"
TRUSTED = "trusted-importer"
BASIS_TOOL_VERSION = "1.0.0"


@dataclass(frozen=True)
class _Aligned:
    service: SegmentAlignmentService
    predecessor: SegmentAlignment
    source_id: str


def _side(
    ctx: AppContext, tmp_path: Path, key: str, language: str, *, deny: list[str] | None = None
) -> AlignmentSide:
    relative = f"texts/{key}.tsv"
    content = f"ref\t{language}\nT.1\t{'kanu mabi.' if language == 'qaa' else 'O homem.'}\n"
    write_origin_file(tmp_path, relative, content.encode("utf-8"))
    overrides: dict[str, Any] = {} if deny is None else {"deny": deny}
    data = manifest_data(key=key, objects=[{"path": relative, "media_type": TSV}], **overrides)
    data["source_type"] = "wordlist"
    data["languages"] = [language]
    registered = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))
    ingest_source(ctx, registered.source.id)
    extraction = extract_source(ctx, registered.source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    return AlignmentSide(
        source_id=registered.source.id,
        language=language,
        normalization_run_id=normalization.run.id,
    )


def _aligned(
    ctx: AppContext, tmp_path: Path, key: str, *, deny: list[str] | None = None
) -> _Aligned:
    source = _side(ctx, tmp_path, f"{key}-a", "qaa", deny=deny)
    target = _side(ctx, tmp_path, f"{key}-b", "por", deny=deny)
    service = SegmentAlignmentService(ctx, trusted_importers=(TRUSTED,))
    summary = service.align(source, target, config=AlignmentConfig(namespace="refs"))
    predecessor = ctx.repo.list_segment_alignments_for_run(summary.run.id)[0]
    return _Aligned(service, predecessor, source.source_id)


def _basis_payload(
    predecessor: SegmentAlignment,
    *,
    actor: str = "test-actor",
    disposition: str = "approved",
    member_ids: list[str] | None = None,
    schema_name: str = "alignment-authorization",
    schema_version: int = 1,
    basis_kind: str = "authorized_reviewer",
) -> dict[str, Any]:
    members = (
        member_ids
        if member_ids is not None
        else sorted((*predecessor.source_segment_ids, *predecessor.target_segment_ids))
    )
    return {
        "schema": schema_name,
        "schema_version": schema_version,
        "predecessor_id": predecessor.id,
        "member_ids": members,
        "actor": actor,
        "disposition": disposition,
        "basis_kind": basis_kind,
        "issuer_authority": "test-authority",
        "occurred_at": "2026-10-13T00:00:00+00:00",
    }


def _register_basis(
    ctx: AppContext,
    payload: dict[str, Any],
    *,
    tool: str = TRUSTED,
    producing_status: RunStatus = RunStatus.SUCCEEDED,
    with_output_io: bool = True,
    with_lineage: bool = True,
) -> str:
    config: dict[str, JsonValue] = {
        "payload_kind": "alignment-authorization",
        "payload_sha256": hashlib.sha256(canonical_json(payload).encode()).hexdigest(),
    }
    run_key = ProcessingRun.compute_run_key(
        RunStage.MANUAL_ANNOTATION,
        tool,
        BASIS_TOOL_VERSION,
        config_hash(config),
        [payload["predecessor_id"]],
    )
    common: dict[str, Any] = dict(
        id=ctx.new_id(IdPrefix.RUN),
        stage=RunStage.MANUAL_ANNOTATION,
        tool_name=tool,
        tool_version=BASIS_TOOL_VERSION,
        config=config,
        config_hash=config_hash(config),
        code_revision="test-rev",
        run_key=run_key,
        status=producing_status,
        started_at=ctx.clock(),
    )
    if producing_status is RunStatus.SUCCEEDED:
        run = ProcessingRun(**common, finished_at=ctx.clock())
    else:
        run = ProcessingRun(**common, finished_at=ctx.clock(), error_type="RuntimeError")
    with ctx.repo.transaction():
        ctx.repo.add_run(run)
        stored = ctx.artifact_store.put_bytes(canonical_json(payload).encode("utf-8"))
        artifact = Artifact(
            id=ctx.new_id(IdPrefix.ARTIFACT),
            run_id=run.id,
            kind=ArtifactKind.OTHER,
            media_type="application/json",
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            access_class=AccessClass.PUBLIC,
            schema_name="alignment-authorization",
            schema_version=1,
            created_at=ctx.clock(),
        )
        ctx.repo.add_artifact(artifact)
        ctx.repo.add_run_io(run.id, payload["predecessor_id"], RunIoRole.INPUT)
        if with_output_io:
            ctx.repo.add_run_io(run.id, artifact.id, RunIoRole.OUTPUT)
        if with_lineage:
            ctx.repo.add_lineage_edge(
                LineageEdge(
                    id=ctx.new_id(IdPrefix.LINEAGE),
                    from_id=artifact.id,
                    to_id=payload["predecessor_id"],
                    kind=LineageKind.DERIVED_FROM,
                    run_id=run.id,
                    created_at=ctx.clock(),
                )
            )
    return artifact.id


def _io_ids(ctx: AppContext, run_id: str, role: RunIoRole) -> set[str]:
    return {oid for oid, r in ctx.repo.list_run_io(run_id) if r is role}


def _lineage_targets(ctx: AppContext, object_id: str, kind: LineageKind) -> set[str]:
    return {
        edge.to_id for edge in ctx.repo.list_lineage_edges(object_id, "out") if edge.kind is kind
    }


def _approved_import(ctx: AppContext, aligned: _Aligned, **kwargs: Any) -> Any:
    basis_id = _register_basis(ctx, _basis_payload(aligned.predecessor, **kwargs))
    return aligned.service.import_disposition(aligned.predecessor.id, basis_id, "approved")


def test_untrusted_producer_fails_before_run(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-untrusted")
    # Empty allowlist is the default: even a well-formed basis is untrusted.
    monkeypatch.delenv("LANGPIPE_TRUSTED_IMPORTERS", raising=False)
    service = SegmentAlignmentService(ctx)
    basis_id = _register_basis(ctx, _basis_payload(aligned.predecessor))
    before = state_counts(ctx)

    with pytest.raises(AlignmentFailed) as exc_info:
        service.import_disposition(aligned.predecessor.id, basis_id, "approved")

    assert exc_info.value.code == "authorization_invalid"
    assert state_counts(ctx) == before


def test_actor_mismatch_fails_before_run(ctx: AppContext, tmp_path: Path) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-actor")
    basis_id = _register_basis(ctx, _basis_payload(aligned.predecessor, actor="someone-else"))
    before = state_counts(ctx)

    with pytest.raises(AlignmentFailed) as exc_info:
        aligned.service.import_disposition(aligned.predecessor.id, basis_id, "approved")

    assert exc_info.value.code == "authorization_invalid"
    assert state_counts(ctx) == before


def test_denied_human_review_fails_before_run(ctx: AppContext, tmp_path: Path) -> None:
    # ALIGN stays allowed so the predecessor exists, but HUMAN_REVIEW is denied.
    aligned = _aligned(ctx, tmp_path, "auth-hr", deny=[Operation.HUMAN_REVIEW.value])
    basis_id = _register_basis(ctx, _basis_payload(aligned.predecessor))
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied) as exc_info:
        aligned.service.import_disposition(aligned.predecessor.id, basis_id, "approved")

    assert exc_info.value.operation is Operation.HUMAN_REVIEW
    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}


def test_revoked_ancestor_fails_before_run(ctx: AppContext, tmp_path: Path) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-revoked")
    with ctx.repo.transaction():
        ctx.repo.set_source_status(aligned.source_id, SourceStatus.REVOKED, ctx.clock())
    basis_id = _register_basis(ctx, _basis_payload(aligned.predecessor))
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied):
        aligned.service.import_disposition(aligned.predecessor.id, basis_id, "approved")

    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}


def test_changed_members_fail_before_run(ctx: AppContext, tmp_path: Path) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-members")
    unrelated = _side(ctx, tmp_path, "auth-members-c", "por")
    unrelated_segments = ctx.repo.list_segments_for_run(unrelated.normalization_run_id)
    changed = sorted((*aligned.predecessor.source_segment_ids, unrelated_segments[0].id))
    basis_id = _register_basis(ctx, _basis_payload(aligned.predecessor, member_ids=changed))
    before = state_counts(ctx)

    with pytest.raises(AlignmentFailed) as exc_info:
        aligned.service.import_disposition(aligned.predecessor.id, basis_id, "approved")

    assert exc_info.value.code == "authorization_invalid"
    assert state_counts(ctx) == before


def test_failed_producing_run_fails_before_run(ctx: AppContext, tmp_path: Path) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-run")
    basis_id = _register_basis(
        ctx, _basis_payload(aligned.predecessor), producing_status=RunStatus.FAILED
    )
    before = state_counts(ctx)

    with pytest.raises(AlignmentFailed) as exc_info:
        aligned.service.import_disposition(aligned.predecessor.id, basis_id, "approved")

    assert exc_info.value.code == "authorization_invalid"
    assert state_counts(ctx) == before


def test_basis_without_lineage_fails_before_run(ctx: AppContext, tmp_path: Path) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-no-lineage")
    basis_id = _register_basis(ctx, _basis_payload(aligned.predecessor), with_lineage=False)
    before = state_counts(ctx)

    with pytest.raises(AlignmentFailed) as exc_info:
        aligned.service.import_disposition(aligned.predecessor.id, basis_id, "approved")

    assert exc_info.value.code == "authorization_invalid"
    assert state_counts(ctx) == before


def test_basis_without_producer_output_io_fails_before_run(ctx: AppContext, tmp_path: Path) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-no-output")
    basis_id = _register_basis(ctx, _basis_payload(aligned.predecessor), with_output_io=False)
    before = state_counts(ctx)

    with pytest.raises(AlignmentFailed) as exc_info:
        aligned.service.import_disposition(aligned.predecessor.id, basis_id, "approved")

    assert exc_info.value.code == "authorization_invalid"
    assert state_counts(ctx) == before


def test_disposition_mismatch_fails_before_run(ctx: AppContext, tmp_path: Path) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-dispo")
    basis_id = _register_basis(ctx, _basis_payload(aligned.predecessor, disposition="approved"))

    with pytest.raises(AlignmentFailed) as exc_info:
        aligned.service.import_disposition(aligned.predecessor.id, basis_id, "rejected")

    assert exc_info.value.code == "authorization_invalid"


def test_malformed_basis_payload_fails_before_run(ctx: AppContext, tmp_path: Path) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-malformed")
    wrong_schema = _register_basis(
        ctx, _basis_payload(aligned.predecessor, schema_name="something-else")
    )
    bad_members = _register_basis(
        ctx, _basis_payload(aligned.predecessor, member_ids=["seg_not_there"])
    )
    bad_kind = _register_basis(
        ctx, _basis_payload(aligned.predecessor, basis_kind="statistical_confidence")
    )
    before = state_counts(ctx)

    for basis_id in (wrong_schema, bad_members, bad_kind):
        with pytest.raises(AlignmentFailed) as exc_info:
            aligned.service.import_disposition(aligned.predecessor.id, basis_id, "approved")
        assert exc_info.value.code == "authorization_invalid"
    assert state_counts(ctx) == before


def test_import_creates_immutable_successor_with_lineage(ctx: AppContext, tmp_path: Path) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-ok")
    predecessor_snapshot = aligned.predecessor
    before = state_counts(ctx)

    summary = _approved_import(ctx, aligned)

    assert summary.reused is False
    assert summary.run.status is RunStatus.SUCCEEDED
    assert summary.run.stage is RunStage.SEGMENT_ALIGNMENT
    assert summary.alignments == 1
    assert summary.report is not None

    successors = ctx.repo.list_segment_alignments_for_run(summary.run.id)
    assert len(successors) == 1
    successor = successors[0]
    assert successor.status is AlignmentStatus.APPROVED
    assert successor.supersedes_id == predecessor_snapshot.id
    assert successor.authorization_basis_id is not None
    assert successor.source_segment_ids == predecessor_snapshot.source_segment_ids
    assert successor.target_segment_ids == predecessor_snapshot.target_segment_ids
    assert successor.method == predecessor_snapshot.method
    assert successor.mode == predecessor_snapshot.mode

    # The predecessor row itself is untouched history.
    assert ctx.repo.get_segment_alignment(predecessor_snapshot.id) == predecessor_snapshot

    # supersedes -> predecessor, imported_from -> basis, derived_from -> members.
    assert _lineage_targets(ctx, successor.id, LineageKind.SUPERSEDES) == {predecessor_snapshot.id}
    assert _lineage_targets(ctx, successor.id, LineageKind.IMPORTED_FROM) == {
        successor.authorization_basis_id
    }
    assert _lineage_targets(ctx, successor.id, LineageKind.DERIVED_FROM) == (
        set(predecessor_snapshot.source_segment_ids) | set(predecessor_snapshot.target_segment_ids)
    )

    # Basis and predecessor are the import run's declared inputs.
    assert _io_ids(ctx, summary.run.id, RunIoRole.INPUT) == {
        predecessor_snapshot.id,
        successor.authorization_basis_id,
    }
    assert _io_ids(ctx, summary.run.id, RunIoRole.OUTPUT) == {
        successor.id,
        summary.report.id,
    }
    # One run, one successor, one report and lineage rows only.
    assert state_counts(ctx)["segment_alignment"] == before["segment_alignment"] + 1


def test_duplicate_disposition_reuses_run(ctx: AppContext, tmp_path: Path) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-dup")
    basis_id = _register_basis(ctx, _basis_payload(aligned.predecessor))

    first = aligned.service.import_disposition(aligned.predecessor.id, basis_id, "approved")
    after_first = state_counts(ctx)
    second = aligned.service.import_disposition(aligned.predecessor.id, basis_id, "approved")

    assert second.reused is True
    assert second.run.id == first.run.id
    assert second.alignments == first.alignments == 1
    assert state_counts(ctx) == after_first


def test_env_configured_allowlist_trusts_importer(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-env")
    monkeypatch.setenv("LANGPIPE_TRUSTED_IMPORTERS", f"other-tool, {TRUSTED}")
    service = SegmentAlignmentService(ctx)  # no explicit allowlist: env configures it
    basis_id = _register_basis(ctx, _basis_payload(aligned.predecessor))

    summary = service.import_disposition(aligned.predecessor.id, basis_id, "approved")

    assert summary.reused is False
    assert summary.run.status is RunStatus.SUCCEEDED


def test_rejected_successor_excludes_predecessor(ctx: AppContext, tmp_path: Path) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-reject")
    basis_id = _register_basis(ctx, _basis_payload(aligned.predecessor, disposition="rejected"))

    summary = aligned.service.import_disposition(aligned.predecessor.id, basis_id, "rejected")

    assert summary.reused is False
    successor = ctx.repo.list_segment_alignments_for_run(summary.run.id)[0]
    assert successor.status is AlignmentStatus.REJECTED
    # Active selection resolves to the successor; the predecessor is retired.
    assert active_segment_alignments(ctx.repo, [aligned.predecessor]) == [successor]


def test_conflicting_active_successors_fail_preflight(ctx: AppContext, tmp_path: Path) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-conflict")
    first = _approved_import(ctx, aligned)
    first_successor = ctx.repo.list_segment_alignments_for_run(first.run.id)[0]

    # A second live successor inserted outside the service (immutable history permits
    # the rows; selection must refuse to choose between them).
    second_basis = _register_basis(ctx, _basis_payload(aligned.predecessor, actor="other-reviewer"))
    predecessor_run = ctx.repo.get_run(aligned.predecessor.run_id)
    carrier_config: dict[str, JsonValue] = {
        "sides": list(predecessor_run.config["sides"]),
        "carrier": 2,
    }
    carrier = ProcessingRun(
        id=ctx.new_id(IdPrefix.RUN),
        stage=RunStage.SEGMENT_ALIGNMENT,
        tool_name="langpipe.align",
        tool_version="0.0.0",
        config=carrier_config,
        config_hash=config_hash(carrier_config),
        code_revision="test-rev",
        run_key=ProcessingRun.compute_run_key(
            RunStage.SEGMENT_ALIGNMENT,
            "langpipe.align",
            "0.0.0",
            config_hash(carrier_config),
            [aligned.predecessor.id],
        ),
        status=RunStatus.SUCCEEDED,
        started_at=ctx.clock(),
        finished_at=ctx.clock(),
    )
    second_successor = SegmentAlignment(
        id=ctx.new_id(IdPrefix.SEGMENT_ALIGNMENT),
        source_segment_ids=aligned.predecessor.source_segment_ids,
        target_segment_ids=aligned.predecessor.target_segment_ids,
        method=aligned.predecessor.method,
        mode=aligned.predecessor.mode,
        status=AlignmentStatus.APPROVED,
        group_key=aligned.predecessor.group_key,
        run_id=carrier.id,
        created_at=ctx.clock(),
        authorization_basis_id=second_basis,
        supersedes_id=aligned.predecessor.id,
    )
    with ctx.repo.transaction():
        ctx.repo.add_run(carrier)
        ctx.repo.add_segment_alignment(second_successor)
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=second_successor.id,
                to_id=aligned.predecessor.id,
                kind=LineageKind.SUPERSEDES,
                run_id=carrier.id,
                created_at=ctx.clock(),
            )
        )

    # Selection never picks the latest between conflicting live successors.
    with pytest.raises(AmbiguousInput) as exc_info:
        active_segment_alignments(ctx.repo, [aligned.predecessor])
    assert exc_info.value.stage is RunStage.SEGMENT_ALIGNMENT
    assert exc_info.value.count == 2

    # And a further service import over the contested predecessor fails preflight
    # instead of adding a third live successor.
    third_basis = _register_basis(ctx, _basis_payload(aligned.predecessor, disposition="rejected"))
    before = state_counts(ctx)
    with pytest.raises(AlignmentFailed) as import_error:
        aligned.service.import_disposition(aligned.predecessor.id, third_basis, "rejected")
    assert import_error.value.code == "authorization_invalid"
    assert first_successor.status is AlignmentStatus.APPROVED
    assert state_counts(ctx) == before


def test_conflict_is_rechecked_inside_locked_transaction(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aligned = _aligned(ctx, tmp_path, "auth-conflict-locked")
    basis_id = _register_basis(ctx, _basis_payload(aligned.predecessor))
    original_lock_sources = ctx.repo.lock_sources
    original_start = aligned.service.recorder.start
    started_runs: list[str] = []
    inserted = False

    def capture_start(*args: Any, **kwargs: Any) -> ProcessingRun:
        run = original_start(*args, **kwargs)
        started_runs.append(run.id)
        return run

    def add_conflicting_successor(source_ids: Any) -> None:
        nonlocal inserted
        original_lock_sources(source_ids)
        if inserted:
            return
        inserted = True
        predecessor_run = ctx.repo.get_run(aligned.predecessor.run_id)
        config: dict[str, JsonValue] = {"sides": predecessor_run.config["sides"]}
        run = ProcessingRun(
            id=ctx.new_id(IdPrefix.RUN),
            stage=RunStage.SEGMENT_ALIGNMENT,
            tool_name="test.concurrent-importer",
            tool_version="1.0.0",
            config=config,
            config_hash=config_hash(config),
            code_revision="test-rev",
            run_key=ProcessingRun.compute_run_key(
                RunStage.SEGMENT_ALIGNMENT,
                "test.concurrent-importer",
                "1.0.0",
                config_hash(config),
                [aligned.predecessor.id],
            ),
            status=RunStatus.SUCCEEDED,
            started_at=ctx.clock(),
            finished_at=ctx.clock(),
        )
        successor = SegmentAlignment(
            id=ctx.new_id(IdPrefix.SEGMENT_ALIGNMENT),
            source_segment_ids=aligned.predecessor.source_segment_ids,
            target_segment_ids=aligned.predecessor.target_segment_ids,
            method=aligned.predecessor.method,
            mode=aligned.predecessor.mode,
            status=AlignmentStatus.APPROVED,
            group_key=aligned.predecessor.group_key,
            run_id=run.id,
            created_at=ctx.clock(),
            authorization_basis_id=basis_id,
            supersedes_id=aligned.predecessor.id,
        )
        ctx.repo.add_run(run)
        ctx.repo.add_segment_alignment(successor)
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=successor.id,
                to_id=aligned.predecessor.id,
                kind=LineageKind.SUPERSEDES,
                run_id=run.id,
                created_at=ctx.clock(),
            )
        )

    monkeypatch.setattr(ctx.repo, "lock_sources", add_conflicting_successor)
    monkeypatch.setattr(aligned.service.recorder, "start", capture_start)
    before_alignments = state_counts(ctx)["segment_alignment"]

    with pytest.raises(AlignmentFailed) as exc_info:
        aligned.service.import_disposition(aligned.predecessor.id, basis_id, "approved")

    assert exc_info.value.code == "authorization_invalid"
    assert len(started_runs) == 1
    failed_run = ctx.repo.get_run(started_runs[0])
    assert failed_run.status is RunStatus.FAILED
    assert failed_run.error_message is None
    assert state_counts(ctx)["segment_alignment"] == before_alignments
