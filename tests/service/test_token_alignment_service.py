"""Stage 5 token alignment service contracts (WP3.9)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from langpipe.alignment.adapters import eflomal as eflomal_module
from langpipe.alignment.adapters.eflomal import EflomalAligner
from langpipe.alignment.base import (
    AlignmentConfig,
    AlignmentSide,
    BackendMetadata,
    IndexLink,
    SegmentMatchOutput,
    TokenBatchOutput,
    TokenLinks,
)
from langpipe.alignment.canonical import CanonicalLocatorAligner
from langpipe.alignment.segment_service import SegmentAlignmentService
from langpipe.alignment.token_service import TokenAlignmentService
from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AlignmentDirection,
    AlignmentStatus,
    AuditEventType,
    RunStage,
    RunStatus,
    SourceStatus,
    Symmetrization,
)
from langpipe.domain.errors import AlignmentFailed, PolicyDenied
from langpipe.extraction.service import extract_source
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.normalization.service import normalize_extraction
from langpipe.text.registry import VersionedRegistry
from langpipe.tokenization.service import tokenize_normalization
from tests.service.manifests import manifest_data, write_manifest, write_origin_file
from tests.service.test_alignment_authorization import _aligned, _basis_payload, _register_basis

TSV = "text/tab-separated-values"


@dataclass(frozen=True)
class _Side:
    side: AlignmentSide
    tokenization_run_id: str


class _Links:
    name = "fixture"
    version = "0.1.0"

    def align(self, groups, config):
        return TokenBatchOutput(
            tuple(
                TokenLinks(g.alignment_id, (IndexLink(0, 0),), (IndexLink(0, 0),)) for g in groups
            ),
            BackendMetadata("0.1.0", None, {}, False),
        )


class _DisjointLinks(_Links):
    def align(self, groups, config):
        return TokenBatchOutput(
            tuple(
                TokenLinks(g.alignment_id, (IndexLink(0, 0),), (IndexLink(1, 1),)) for g in groups
            ),
            BackendMetadata("0.1.0", None, {}, False),
        )


class _CandidateSegments:
    name = "candidate_fixture"
    version = "0.1.0"

    def align(self, source, target, config):
        output = CanonicalLocatorAligner().align(source, target, config)
        return SegmentMatchOutput(
            tuple(replace(group, status=AlignmentStatus.CANDIDATE) for group in output.groups),
            output.unmatched,
        )


class _FailsOnce(_Links):
    def __init__(self):
        self.failed = False

    def align(self, groups, config):
        if not self.failed:
            self.failed = True
            raise AlignmentFailed("backend_failed")
        return super().align(groups, config)


def _side(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    language: str,
    text: str,
    *,
    access_class: str = "public",
) -> _Side:
    relative = f"texts/{key}.tsv"
    write_origin_file(tmp_path, relative, f"ref\t{language}\nT.1\t{text}\n".encode())
    data = manifest_data(
        key=key, access_class=access_class, objects=[{"path": relative, "media_type": TSV}]
    )
    data["source_type"] = "wordlist"
    data["languages"] = [language]
    source = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml")).source
    ingest_source(ctx, source.id)
    extraction = extract_source(ctx, source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    tokenization = tokenize_normalization(ctx, normalization.run.id)
    return _Side(AlignmentSide(source.id, language, normalization.run.id), tokenization.run.id)


def _ready(ctx, tmp_path):
    a = _side(ctx, tmp_path, "token-a", "qaa", "kanu mabi.")
    b = _side(ctx, tmp_path, "token-b", "por", "O homem vê.")
    seg = SegmentAlignmentService(ctx).align(
        a.side, b.side, config=AlignmentConfig(namespace="refs")
    )
    return a, b, seg


def test_n_m_index_mapping_exact_ids(ctx: AppContext, tmp_path: Path) -> None:
    a = _side(ctx, tmp_path, "nm-a", "qaa", "kanu mabi\nT.1\twai")
    b = _side(ctx, tmp_path, "nm-b", "por", "homem vê")
    seg = SegmentAlignmentService(ctx).align(
        a.side, b.side, config=AlignmentConfig(namespace="refs")
    )

    class _CrossBoundary(_Links):
        def align(self, groups, config):
            return TokenBatchOutput(
                tuple(
                    TokenLinks(
                        group.alignment_id,
                        (IndexLink(2, 0), IndexLink(0, 1)),
                        (IndexLink(2, 0), IndexLink(0, 1)),
                    )
                    for group in groups
                ),
                BackendMetadata("0.1.0", None, {}, False),
            )

    registry = VersionedRegistry((_CrossBoundary(),))
    out = TokenAlignmentService(ctx, aligners=registry).align(
        seg.run.id,
        source_tokenization_run_id=a.tokenization_run_id,
        target_tokenization_run_id=b.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    edges = ctx.repo.list_token_alignment_edges_for_run(out.run.id)
    assert out.run.status is RunStatus.SUCCEEDED
    group = ctx.repo.list_segment_alignments_for_run(seg.run.id)[0]
    assert len(group.source_segment_ids) == 2
    assert len(group.target_segment_ids) == 1
    source_ids = [t.id for sid in group.source_segment_ids for t in ctx.repo.list_tokens(sid)]
    target_ids = [t.id for sid in group.target_segment_ids for t in ctx.repo.list_tokens(sid)]
    assert edges
    assert {(e.source_token_id, e.target_token_id) for e in edges} == {
        (source_ids[2], target_ids[0]),
        (source_ids[0], target_ids[1]),
    }
    assert all(e.score is None for e in edges)
    assert {(e.direction, e.symmetrization.value) for e in edges} == {
        (AlignmentDirection.FORWARD, "none"),
        (AlignmentDirection.REVERSE, "none"),
        (AlignmentDirection.SYMMETRIZED, "intersection"),
    }


def test_forward_reverse_symmetrized_rows(ctx: AppContext, tmp_path: Path) -> None:
    a, b, segment = _ready(ctx, tmp_path)
    result = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
        segment.run.id,
        source_tokenization_run_id=a.tokenization_run_id,
        target_tokenization_run_id=b.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    edges = ctx.repo.list_token_alignment_edges_for_run(result.run.id)
    assert {edge.direction for edge in edges} == {
        AlignmentDirection.FORWARD,
        AlignmentDirection.REVERSE,
        AlignmentDirection.SYMMETRIZED,
    }
    assert all(edge.source_token_id and edge.target_token_id for edge in edges)


def test_pinned_token_generations(ctx: AppContext, tmp_path: Path) -> None:
    a, b, seg = _ready(ctx, tmp_path)
    from langpipe.domain.errors import InvalidLineage

    with pytest.raises(InvalidLineage):
        TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
            seg.run.id,
            source_tokenization_run_id=b.tokenization_run_id,
            target_tokenization_run_id=a.tokenization_run_id,
            method="fixture@0.1.0",
            config=AlignmentConfig(namespace="refs"),
        )


def test_only_structural_or_active_approved_inputs(ctx: AppContext, tmp_path: Path) -> None:
    a = _side(ctx, tmp_path, "candidate-a", "qaa", "kanu")
    b = _side(ctx, tmp_path, "candidate-b", "por", "homem")
    segment = SegmentAlignmentService(
        ctx, aligners=VersionedRegistry((_CandidateSegments(),))
    ).align(
        a.side,
        b.side,
        method="candidate_fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    result = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
        segment.run.id,
        source_tokenization_run_id=a.tokenization_run_id,
        target_tokenization_run_id=b.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    assert result.edges == 0
    assert ctx.repo.list_token_alignment_edges_for_run(result.run.id) == []


def test_rejected_successor_excludes_predecessor(ctx: AppContext, tmp_path: Path) -> None:
    aligned = _aligned(ctx, tmp_path, "rejected-stage5")
    basis_id = _register_basis(
        ctx,
        _basis_payload(aligned.predecessor, disposition="rejected"),
    )
    source_segment = ctx.repo.get_segment(aligned.predecessor.source_segment_ids[0])
    target_segment = ctx.repo.get_segment(aligned.predecessor.target_segment_ids[0])
    source_tokens = tokenize_normalization(ctx, source_segment.run_id)
    target_tokens = tokenize_normalization(ctx, target_segment.run_id)
    kwargs = dict(
        source_tokenization_run_id=source_tokens.run.id,
        target_tokenization_run_id=target_tokens.run.id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    predecessor_positive = TokenAlignmentService(
        ctx, aligners=VersionedRegistry((_Links(),))
    ).align(aligned.predecessor.run_id, **kwargs)
    assert predecessor_positive.edges > 0
    aligned.service.import_disposition(aligned.predecessor.id, basis_id, "rejected")
    approved_setup = _aligned(ctx, tmp_path, "approved-stage5")
    approved_basis = _register_basis(
        ctx, _basis_payload(approved_setup.predecessor, disposition="approved")
    )
    approved_result = approved_setup.service.import_disposition(
        approved_setup.predecessor.id, approved_basis, "approved"
    )
    successor = [
        row
        for row in ctx.repo.list_segment_alignments_for_run(approved_result.run.id)
        if row.supersedes_id == approved_setup.predecessor.id
        and row.status is AlignmentStatus.APPROVED
    ]
    assert successor
    approved_run = ctx.repo.get_run(successor[-1].run_id)
    approved_source = ctx.repo.get_segment(successor[-1].source_segment_ids[0])
    approved_target = ctx.repo.get_segment(successor[-1].target_segment_ids[0])
    approved_source_tokens = tokenize_normalization(ctx, approved_source.run_id)
    approved_target_tokens = tokenize_normalization(ctx, approved_target.run_id)
    approved_kwargs = {
        **kwargs,
        "source_tokenization_run_id": approved_source_tokens.run.id,
        "target_tokenization_run_id": approved_target_tokens.run.id,
    }
    approved = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
        approved_run.id, **approved_kwargs
    )
    assert approved.edges > 0
    source_segment = ctx.repo.get_segment(aligned.predecessor.source_segment_ids[0])
    target_segment = ctx.repo.get_segment(aligned.predecessor.target_segment_ids[0])
    source_tokens = tokenize_normalization(ctx, source_segment.run_id)
    target_tokens = tokenize_normalization(ctx, target_segment.run_id)
    result = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
        aligned.predecessor.run_id,
        source_tokenization_run_id=source_tokens.run.id,
        target_tokenization_run_id=target_tokens.run.id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    assert result.edges == 0


def test_late_batch_failure_no_edges(ctx: AppContext, tmp_path: Path) -> None:
    a, b, segment = _ready(ctx, tmp_path)

    class _Fail(_Links):
        def align(self, groups, config):
            raise AlignmentFailed("backend_failed")

    service = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Fail(),)))
    failed_ids = []
    original_fail = service.recorder.fail

    def capture_failure(run_id, error, *args, **kwargs):
        failed_ids.append(run_id)
        return original_fail(run_id, error, *args, **kwargs)

    service.recorder.fail = capture_failure
    with pytest.raises(AlignmentFailed):
        service.align(
            segment.run.id,
            source_tokenization_run_id=a.tokenization_run_id,
            target_tokenization_run_id=b.tokenization_run_id,
            method="fixture@0.1.0",
            config=AlignmentConfig(namespace="refs"),
        )
    assert len(failed_ids) == 1
    assert ctx.repo.get_run(failed_ids[0]).status is RunStatus.FAILED
    assert ctx.repo.list_token_alignment_edges_for_run(failed_ids[0]) == []


def test_artifact_store_failure_no_rows(ctx: AppContext, tmp_path: Path, monkeypatch) -> None:
    a, b, segment = _ready(ctx, tmp_path)
    service = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),)))
    failed_ids = []
    original_fail = service.recorder.fail

    def capture_failure(run_id, error, *args, **kwargs):
        failed_ids.append(run_id)
        return original_fail(run_id, error, *args, **kwargs)

    service.recorder.fail = capture_failure

    def fail_store(_payload: bytes):
        raise OSError("restricted payload")

    monkeypatch.setattr(ctx.artifact_store, "put_bytes", fail_store)
    with pytest.raises(OSError):
        service.align(
            segment.run.id,
            source_tokenization_run_id=a.tokenization_run_id,
            target_tokenization_run_id=b.tokenization_run_id,
            method="fixture@0.1.0",
            config=AlignmentConfig(namespace="refs"),
        )
    assert len(failed_ids) == 1
    assert ctx.repo.get_run(failed_ids[0]).status is RunStatus.FAILED
    assert ctx.repo.list_token_alignment_edges_for_run(failed_ids[0]) == []


def test_retry_failed_run_new_id_successful_rerun_reused(
    ctx: AppContext, tmp_path: Path, monkeypatch
) -> None:
    a, b, segment = _ready(ctx, tmp_path)
    service = TokenAlignmentService(ctx, aligners=VersionedRegistry((_FailsOnce(),)))
    failed_ids = []
    original_fail = service.recorder.fail

    def capture_failure(run_id, error, *args, **kwargs):
        failed_ids.append(run_id)
        return original_fail(run_id, error, *args, **kwargs)

    monkeypatch.setattr(service.recorder, "fail", capture_failure)
    kwargs = dict(
        source_tokenization_run_id=a.tokenization_run_id,
        target_tokenization_run_id=b.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    with pytest.raises(AlignmentFailed):
        service.align(segment.run.id, **kwargs)
    failed = ctx.repo.get_run(failed_ids[0])
    success = service.align(segment.run.id, **kwargs)
    reused = service.align(segment.run.id, **kwargs)
    assert success.run.id != failed.id
    assert success.reused is False
    assert reused.run.id == success.run.id and reused.reused is True


def test_unaligned_complements_per_direction(ctx: AppContext, tmp_path: Path) -> None:
    a = _side(ctx, tmp_path, "unaligned-a", "qaa", "kanu mabi")
    b = _side(ctx, tmp_path, "unaligned-b", "por", "homem vê")
    segment = SegmentAlignmentService(ctx).align(
        a.side, b.side, config=AlignmentConfig(namespace="refs")
    )
    result = TokenAlignmentService(ctx, aligners=VersionedRegistry((_DisjointLinks(),))).align(
        segment.run.id,
        source_tokenization_run_id=a.tokenization_run_id,
        target_tokenization_run_id=b.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    payload = __import__("json").loads(ctx.artifact_store.read_bytes(result.report.sha256))
    group = payload["groups"][0]
    assert len(group["unaligned_by_direction"]["forward"]["source"]) == 1
    assert len(group["unaligned_by_direction"]["reverse"]["target"]) == 1
    assert len(group["unaligned_by_direction"]["symmetrized"]["source"]) == 2


@pytest.mark.parametrize("symmetrization", list(Symmetrization))
def test_summary_fresh_equals_reused(ctx, tmp_path, symmetrization):
    a = _side(ctx, tmp_path, f"summary-a-{symmetrization}", "qaa", "kanu mabi")
    b = _side(ctx, tmp_path, f"summary-b-{symmetrization}", "por", "homem vê")
    segment = SegmentAlignmentService(ctx).align(
        a.side, b.side, config=AlignmentConfig(namespace="refs")
    )
    service = TokenAlignmentService(ctx, aligners=VersionedRegistry((_DisjointLinks(),)))
    kwargs = dict(
        source_tokenization_run_id=a.tokenization_run_id,
        target_tokenization_run_id=b.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs", symmetrization=symmetrization),
    )
    fresh = service.align(segment.run.id, **kwargs)
    reused = service.align(segment.run.id, **kwargs)
    assert (fresh.edges, fresh.unaligned_source, fresh.unaligned_target, fresh.skipped_groups) == (
        reused.edges,
        reused.unaligned_source,
        reused.unaligned_target,
        reused.skipped_groups,
    )


def test_revocation_during_native_compute_blocks_commit(ctx, tmp_path):
    a, b, segment = _ready(ctx, tmp_path)
    source_id = a.side.source_id

    class _Revokes(_Links):
        def align(self, groups, config):
            from datetime import UTC, datetime

            with ctx.repo.transaction():
                ctx.repo.set_source_status(source_id, SourceStatus.REVOKED, datetime.now(UTC))
            return super().align(groups, config)

    service = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Revokes(),)))
    failed_ids = []
    original_start = service.recorder.start

    def capture_start(*args, **kwargs):
        run = original_start(*args, **kwargs)
        failed_ids.append(run.id)
        return run

    service.recorder.start = capture_start
    before = len(ctx.repo.list_audit_events())
    with pytest.raises(PolicyDenied):
        service.align(
            segment.run.id,
            source_tokenization_run_id=a.tokenization_run_id,
            target_tokenization_run_id=b.tokenization_run_id,
            method="fixture@0.1.0",
            config=AlignmentConfig(namespace="refs"),
        )
    failed = ctx.repo.get_run(failed_ids[0])
    assert failed.status is RunStatus.FAILED
    assert failed.error_type == "PolicyDenied" and failed.error_message is None
    assert ctx.repo.list_token_alignment_edges_for_run(failed.id) == []
    assert ctx.repo.list_run_io(failed.id) == []
    assert (
        len(
            [
                e
                for e in ctx.repo.list_audit_events()[before:]
                if e.event_type is AuditEventType.POLICY_DENIED
            ]
        )
        == 1
    )


def test_reuse_after_revocation_denied_without_new_run(ctx, tmp_path):
    a, b, segment = _ready(ctx, tmp_path)
    service = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),)))
    started = []
    original_start = service.recorder.start

    def capture_start(*args, **kwargs):
        run = original_start(*args, **kwargs)
        started.append(run.id)
        return run

    service.recorder.start = capture_start
    kwargs = dict(
        source_tokenization_run_id=a.tokenization_run_id,
        target_tokenization_run_id=b.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    service.align(segment.run.id, **kwargs)
    from datetime import UTC, datetime

    with ctx.repo.transaction():
        ctx.repo.set_source_status(a.side.source_id, SourceStatus.REVOKED, datetime.now(UTC))
    before_runs = ctx.repo.find_succeeded_run(
        next(
            r.run_key
            for r in ctx.repo.list_runs_with_input(segment.run.id, RunStage.TOKEN_ALIGNMENT)
        )
    )
    before_audits = len(ctx.repo.list_audit_events())
    with pytest.raises(PolicyDenied):
        service.align(segment.run.id, **kwargs)
    assert len(started) == 1
    assert ctx.repo.find_succeeded_run(before_runs.run_key).id == before_runs.id
    assert (
        len(
            [
                e
                for e in ctx.repo.list_audit_events()[before_audits:]
                if e.event_type is AuditEventType.POLICY_DENIED
            ]
        )
        == 1
    )


@pytest.mark.parametrize("payload_kind", ["exception", "option_key", "option_value", "version"])
def test_adapter_payloads_are_redacted(ctx, tmp_path, capsys, caplog, payload_kind):
    secret = "SECRET-PAYLOAD-7f3"
    a, b, segment = _ready(ctx, tmp_path)

    class _Leaks(_Links):
        def align(self, groups, config):
            if payload_kind == "exception":
                raise RuntimeError(secret)
            metadata = BackendMetadata("0.1.0", None, {}, False)
            if payload_kind == "option_key":
                metadata = BackendMetadata("0.1.0", None, {secret: "value"}, False)
            elif payload_kind == "option_value":
                metadata = BackendMetadata("0.1.0", None, {"model": secret}, False)
            elif payload_kind == "version":
                metadata = BackendMetadata(secret, None, {}, False)
            output = super().align(groups, config)
            return TokenBatchOutput(output.groups, metadata)

    service = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Leaks(),)))
    run_ids = []
    original_start = service.recorder.start

    def capture_start(*args, **kwargs):
        run = original_start(*args, **kwargs)
        run_ids.append(run.id)
        return run

    service.recorder.start = capture_start
    expected = RuntimeError if payload_kind == "exception" else AlignmentFailed
    with pytest.raises(expected) as error:
        service.align(
            segment.run.id,
            source_tokenization_run_id=a.tokenization_run_id,
            target_tokenization_run_id=b.tokenization_run_id,
            method="fixture@0.1.0",
            config=AlignmentConfig(namespace="refs"),
        )
    if payload_kind in {"option_key", "option_value", "version"}:
        assert error.value.code == "invalid_adapter_output"
    failed = ctx.repo.get_run(run_ids[0])
    persisted = repr(failed.model_dump())
    report_bytes = b"".join(
        ctx.artifact_store.read_bytes(ctx.repo.get_artifact(object_id).sha256)
        for object_id, role in ctx.repo.list_run_io(failed.id)
        if role.value == "output" and ctx.repo.entity_type_of(object_id).value == "artifact"
    )
    captured = capsys.readouterr()
    assert failed.status is RunStatus.FAILED and failed.error_message is None
    assert ctx.repo.list_token_alignment_edges_for_run(failed.id) == []
    assert secret not in persisted + report_bytes.decode(errors="ignore")
    assert secret not in captured.out + captured.err + caplog.text


def test_native_stderr_payload_is_redacted(ctx, tmp_path, capsys, caplog, monkeypatch):
    secret = "SECRET-PAYLOAD-7f3"
    a, b, segment = _ready(ctx, tmp_path)
    monkeypatch.setattr(eflomal_module, "_probe_backend", lambda: "2.0.0")
    monkeypatch.setattr(
        eflomal_module.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args[0], 7, secret.encode(), secret.encode()
        ),
    )
    service = TokenAlignmentService(ctx, aligners=VersionedRegistry((EflomalAligner(),)))
    run_ids = []
    original_start = service.recorder.start

    def capture_start(*args, **kwargs):
        run = original_start(*args, **kwargs)
        run_ids.append(run.id)
        return run

    service.recorder.start = capture_start
    with pytest.raises(AlignmentFailed) as error:
        service.align(
            segment.run.id,
            source_tokenization_run_id=a.tokenization_run_id,
            target_tokenization_run_id=b.tokenization_run_id,
            config=AlignmentConfig(namespace="refs"),
        )

    failed = ctx.repo.get_run(run_ids[0])
    persisted = repr(failed.model_dump())
    report_bytes = b"".join(
        ctx.artifact_store.read_bytes(ctx.repo.get_artifact(object_id).sha256)
        for object_id, role in ctx.repo.list_run_io(failed.id)
        if role.value == "output" and ctx.repo.entity_type_of(object_id).value == "artifact"
    )
    captured = capsys.readouterr()
    assert error.value.code == "backend_failed"
    assert secret not in (
        repr(error.value)
        + captured.out
        + captured.err
        + caplog.text
        + persisted
        + report_bytes.decode(errors="ignore")
    )
    assert failed.status is RunStatus.FAILED and failed.error_message is None
    assert ctx.repo.list_token_alignment_edges_for_run(failed.id) == []
