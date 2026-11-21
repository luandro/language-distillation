"""WP3.7 Stage 4 service: atomic ``SegmentAlignmentService`` runs (M3-PLAN §5.2/§5.4).

One request is one all-or-nothing ``SEGMENT_ALIGNMENT`` run: governance preflight,
locked reuse, canonical matching outside the semantic transaction, then one transaction
holding alignments, members, lineage, report and run I/O. Failures roll every semantic
row back and mark the run failed with a fixed error type only (ADR-0011 §7). Reports
carry identifiers, enum values, counts and fixed reason codes — never text, titles,
paths or locator references.
"""

import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from langpipe.alignment.base import (
    AlignmentConfig,
    AlignmentSide,
    SegmentGroup,
    SegmentMatchOutput,
)
from langpipe.alignment.segment_service import SegmentAlignmentService
from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AlignmentMode,
    AlignmentStatus,
    ArtifactKind,
    EntityType,
    LineageKind,
    RunIoRole,
    RunStage,
    RunStatus,
)
from langpipe.domain.errors import AlignmentFailed
from langpipe.domain.models.run import ProcessingRun
from langpipe.extraction.service import extract_source
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.normalization.service import normalize_extraction
from langpipe.text.registry import VersionedRegistry
from tests.service.manifests import (
    manifest_data,
    record_finished_runs,
    state_counts,
    write_manifest,
    write_origin_file,
)

TSV = "text/tab-separated-values"


@dataclass(frozen=True)
class _Side:
    side: AlignmentSide
    segments: tuple[str, ...]  # segment ids in document order


def _side(
    ctx: AppContext, tmp_path: Path, key: str, language: str, rows: list[tuple[str, str]]
) -> _Side:
    """One normalized side: a one-language TSV source extracted and normalized."""
    relative = f"texts/{key}.tsv"
    content = f"ref\t{language}\n" + "".join(f"{ref}\t{text}\n" for ref, text in rows)
    write_origin_file(tmp_path, relative, content.encode("utf-8"))
    data = manifest_data(key=key, objects=[{"path": relative, "media_type": TSV}])
    data["source_type"] = "wordlist"
    data["languages"] = [language]
    registered = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))
    ingest_source(ctx, registered.source.id)
    extraction = extract_source(ctx, registered.source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    segments = ctx.repo.list_segments_for_run(normalization.run.id)
    assert segments
    return _Side(
        side=AlignmentSide(
            source_id=registered.source.id,
            language=language,
            normalization_run_id=normalization.run.id,
        ),
        segments=tuple(segment.id for segment in segments),
    )


def _pair(ctx: AppContext, tmp_path: Path, key: str) -> tuple[_Side, _Side, AlignmentConfig]:
    source = _side(ctx, tmp_path, f"{key}-a", "qaa", [("T.1", "kanu mabi."), ("T.2", "wesa tesa.")])
    target = _side(
        ctx, tmp_path, f"{key}-b", "por", [("T.1", "O homem vê."), ("T.2", "A mulher vê.")]
    )
    return source, target, AlignmentConfig(namespace="refs")


def _io_ids(ctx: AppContext, run_id: str, role: RunIoRole) -> set[str]:
    return {oid for oid, r in ctx.repo.list_run_io(run_id) if r is role}


def _lineage_targets(ctx: AppContext, object_id: str, kind: LineageKind) -> set[str]:
    return {
        edge.to_id for edge in ctx.repo.list_lineage_edges(object_id, "out") if edge.kind is kind
    }


def test_complete_group_run_io_and_lineage(ctx: AppContext, tmp_path: Path) -> None:
    source, target, config = _pair(ctx, tmp_path, "svc-full")
    service = SegmentAlignmentService(ctx)

    summary = service.align(source.side, target.side, config=config)

    assert summary.reused is False
    assert summary.run.status is RunStatus.SUCCEEDED
    assert summary.run.stage is RunStage.SEGMENT_ALIGNMENT
    assert summary.alignments == 2
    assert summary.unmatched_source == 0
    assert summary.unmatched_target == 0

    alignments = ctx.repo.list_segment_alignments_for_run(summary.run.id)
    assert len(alignments) == 2
    for alignment in alignments:
        assert alignment.method == "canonical_locator@0.1.0"
        assert alignment.mode is AlignmentMode.CANONICAL
        assert alignment.status is AlignmentStatus.STRUCTURAL
        assert alignment.score is None
        assert alignment.authorization_basis_id is None
        assert alignment.supersedes_id is None
        assert len(alignment.source_segment_ids) == 1
        assert len(alignment.target_segment_ids) == 1
        # sal -> each member segment via derived_from, no sal->sal Cartesian edges.
        assert _lineage_targets(ctx, alignment.id, LineageKind.DERIVED_FROM) == (
            set(alignment.source_segment_ids) | set(alignment.target_segment_ids)
        )

    matched_pairs = {
        (alignment.source_segment_ids[0], alignment.target_segment_ids[0])
        for alignment in alignments
    }
    assert matched_pairs == {
        (source.segments[0], target.segments[0]),
        (source.segments[1], target.segments[1]),
    }

    expected_inputs = (
        {source.side.source_id, target.side.source_id}
        | {source.side.normalization_run_id, target.side.normalization_run_id}
        | set(source.segments)
        | set(target.segments)
    )
    assert _io_ids(ctx, summary.run.id, RunIoRole.INPUT) == expected_inputs
    assert _io_ids(ctx, summary.run.id, RunIoRole.OUTPUT) == (
        {alignment.id for alignment in alignments} | {summary.report.id}
    )

    report = summary.report
    assert report is not None
    assert report.kind is ArtifactKind.ALIGNMENT_FILE
    assert report.schema_name == "segment-alignment-report"
    assert report.schema_version == 1
    # The report points at the selected groups and segments even though all matched.
    assert _lineage_targets(ctx, report.id, LineageKind.DERIVED_FROM) == (
        {alignment.id for alignment in alignments} | set(source.segments) | set(target.segments)
    )

    payload = json.loads(ctx.artifact_store.read_bytes(report.sha256))
    assert payload["schema"] == "segment-alignment-report"
    assert payload["run_id"] == summary.run.id
    assert payload["method"] == "canonical_locator@0.1.0"
    assert payload["namespace"] == "refs"
    assert {group["alignment_id"] for group in payload["groups"]} == {
        alignment.id for alignment in alignments
    }
    assert payload["totals"] == {"groups": 2, "unmatched_source": 0, "unmatched_target": 0}
    # No text, titles, paths or locator refs ever enter the report bytes.
    raw = ctx.artifact_store.read_bytes(report.sha256)
    assert b"kanu" not in raw and b"homem" not in raw and b"T.1" not in raw


def test_zero_matches_report_has_sources(ctx: AppContext, tmp_path: Path) -> None:
    source = _side(ctx, tmp_path, "svc-zero-a", "qaa", [("A.1", "kanu mabi.")])
    target = _side(ctx, tmp_path, "svc-zero-b", "por", [("B.1", "O homem.")])
    service = SegmentAlignmentService(ctx)

    summary = service.align(source.side, target.side, config=AlignmentConfig(namespace="refs"))

    assert summary.reused is False
    assert summary.run.status is RunStatus.SUCCEEDED
    assert summary.alignments == 0
    assert summary.unmatched_source == 1
    assert summary.unmatched_target == 1
    assert ctx.repo.list_segment_alignments_for_run(summary.run.id) == []

    report = summary.report
    assert report is not None
    # Zero-link runs keep both source ancestries on the report (ADR-0011 §7).
    assert _lineage_targets(ctx, report.id, LineageKind.DERIVED_FROM) == (
        set(source.segments) | set(target.segments)
    )
    payload = json.loads(ctx.artifact_store.read_bytes(report.sha256))
    assert payload["groups"] == []
    assert [row["segment_id"] for row in payload["unmatched_source"]] == list(source.segments)
    assert [row["segment_id"] for row in payload["unmatched_target"]] == list(target.segments)
    assert payload["totals"] == {"groups": 0, "unmatched_source": 1, "unmatched_target": 1}
    assert _io_ids(ctx, summary.run.id, RunIoRole.OUTPUT) == {report.id}


def test_group_failure_rolls_back_all_outputs(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target, config = _pair(ctx, tmp_path, "svc-fail")
    service = SegmentAlignmentService(ctx)
    before = state_counts(ctx)
    finished: list[ProcessingRun] = record_finished_runs(ctx, monkeypatch)

    original = ctx.repo.add_segment_alignment
    calls = itertools.count()

    def faulty(alignment: Any) -> None:
        if next(calls) >= 1:  # first group lands, the second detonates
            raise RuntimeError("injected")
        return original(alignment)

    monkeypatch.setattr(ctx.repo, "add_segment_alignment", faulty)

    with pytest.raises(RuntimeError):
        service.align(source.side, target.side, config=config)

    failed_runs = [run for run in finished if run.status is RunStatus.FAILED]
    assert len(failed_runs) == 1
    assert failed_runs[0].error_type == "RuntimeError"
    assert failed_runs[0].error_message is None
    assert ctx.repo.list_run_io(failed_runs[0].id) == []
    assert state_counts(ctx) == {**before, "processing_run": before["processing_run"] + 1}


def test_rerun_stable_ids_and_counts(ctx: AppContext, tmp_path: Path) -> None:
    source, target, config = _pair(ctx, tmp_path, "svc-rerun")
    service = SegmentAlignmentService(ctx)

    first = service.align(source.side, target.side, config=config)
    after_first = state_counts(ctx)
    second = service.align(source.side, target.side, config=config)

    assert second.reused is True
    assert second.run.id == first.run.id
    assert second.alignments == first.alignments == 2
    assert second.unmatched_source == first.unmatched_source == 0
    assert second.unmatched_target == first.unmatched_target == 0
    assert second.report is not None and second.report.id == first.report.id
    assert {
        alignment.id for alignment in ctx.repo.list_segment_alignments_for_run(second.run.id)
    } == {alignment.id for alignment in ctx.repo.list_segment_alignments_for_run(first.run.id)}
    assert state_counts(ctx) == after_first


def test_orientation_changes_key(ctx: AppContext, tmp_path: Path) -> None:
    source, target, config = _pair(ctx, tmp_path, "svc-flip")
    service = SegmentAlignmentService(ctx)

    forward = service.align(source.side, target.side, config=config)
    reverse = service.align(target.side, source.side, config=config)

    assert reverse.reused is False
    assert reverse.run.id != forward.run.id
    forward_rows = ctx.repo.list_segment_alignments_for_run(forward.run.id)
    reverse_rows = ctx.repo.list_segment_alignments_for_run(reverse.run.id)
    assert len(forward_rows) == len(reverse_rows) == 2
    assert {row.group_key for row in forward_rows}.isdisjoint(
        {row.group_key for row in reverse_rows}
    )
    forward_pairs = {(row.source_segment_ids[0], row.target_segment_ids[0]) for row in forward_rows}
    reverse_pairs = {(row.target_segment_ids[0], row.source_segment_ids[0]) for row in reverse_rows}
    assert forward_pairs == reverse_pairs
    # Both orientations survive as independent evidence.
    assert ctx.repo.count(EntityType.SEGMENT_ALIGNMENT) == 4


def test_configuration_changes_preserve_history(ctx: AppContext, tmp_path: Path) -> None:
    source, target, _ = _pair(ctx, tmp_path, "svc-conf")
    service = SegmentAlignmentService(ctx)

    first = service.align(source.side, target.side, config=AlignmentConfig(namespace="one"))
    second = service.align(source.side, target.side, config=AlignmentConfig(namespace="two"))

    assert second.run.id != first.run.id
    first_rows = ctx.repo.list_segment_alignments_for_run(first.run.id)
    second_rows = ctx.repo.list_segment_alignments_for_run(second.run.id)
    assert len(first_rows) == len(second_rows) == 2
    assert {row.group_key for row in first_rows}.isdisjoint({row.group_key for row in second_rows})
    # The earlier generation is untouched history, not overwritten.
    assert ctx.repo.get_segment_alignment(first_rows[0].id) == first_rows[0]
    assert ctx.repo.count(EntityType.SEGMENT_ALIGNMENT) == 4


def test_unknown_method_fails_without_run(ctx: AppContext, tmp_path: Path) -> None:
    source, target, config = _pair(ctx, tmp_path, "svc-unknown")
    service = SegmentAlignmentService(ctx)
    before = state_counts(ctx)

    with pytest.raises(AlignmentFailed) as exc_info:
        service.align(source.side, target.side, method="no_such_aligner", config=config)

    assert exc_info.value.code == "unknown_method"
    assert state_counts(ctx) == before


class _ScriptedAligner:
    """Test-only aligner with a fixed output; never registered in production."""

    name = "scripted_locator"
    version = "0.1.0"

    def __init__(self, output: SegmentMatchOutput) -> None:
        self._output = output

    def align(self, source: Any, target: Any, config: AlignmentConfig) -> SegmentMatchOutput:
        return self._output


def test_malformed_adapter_output_rejects_batch(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target, config = _pair(ctx, tmp_path, "svc-malformed")
    source_segments = [ctx.repo.get_segment(sid) for sid in source.segments]
    target_segments = [ctx.repo.get_segment(sid) for sid in target.segments]
    # One segment claimed by two groups: the whole batch is rejected, never partially kept.
    duplicated = SegmentGroup(
        source_segments=(source_segments[0],),
        target_segments=(target_segments[0],),
        group_key="a" * 64,
        status=AlignmentStatus.STRUCTURAL,
    )
    overlapping = SegmentGroup(
        source_segments=(source_segments[0],),
        target_segments=(target_segments[1],),
        group_key="b" * 64,
        status=AlignmentStatus.STRUCTURAL,
    )
    output = SegmentMatchOutput(groups=(duplicated, overlapping), unmatched=())
    service = SegmentAlignmentService(ctx, aligners=VersionedRegistry((_ScriptedAligner(output),)))
    before = state_counts(ctx)
    finished: list[ProcessingRun] = record_finished_runs(ctx, monkeypatch)

    with pytest.raises(AlignmentFailed) as exc_info:
        service.align(source.side, target.side, method="scripted_locator", config=config)

    assert exc_info.value.code == "invalid_adapter_output"
    assert ctx.repo.count(EntityType.SEGMENT_ALIGNMENT) == 0
    failed = [run for run in finished if run.status is RunStatus.FAILED]
    assert len(failed) == 1 and failed[0].error_type == "AlignmentFailed"
    assert state_counts(ctx) == {**before, "processing_run": before["processing_run"] + 1}


def test_bilingual_single_source_segment_alignment(ctx: AppContext, tmp_path: Path) -> None:
    relative = "texts/bilingual.tsv"
    content = "ref\tqaa\tpor\nT.1\tkanu mabi.\tO homem vê.\nT.2\twesa tesa.\tA mulher vê.\n"
    write_origin_file(tmp_path, relative, content.encode("utf-8"))
    data = manifest_data(key="bilingual", objects=[{"path": relative, "media_type": TSV}])
    data["source_type"] = "wordlist"
    data["languages"] = ["qaa", "por"]
    registered = register_source(ctx, write_manifest(tmp_path, data, name="bilingual.yaml"))
    ingest_source(ctx, registered.source.id)
    extraction = extract_source(ctx, registered.source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    source = AlignmentSide(
        source_id=registered.source.id,
        language="qaa",
        normalization_run_id=normalization.run.id,
    )
    target = AlignmentSide(
        source_id=registered.source.id,
        language="por",
        normalization_run_id=normalization.run.id,
    )
    config = AlignmentConfig(namespace="refs")
    summary = SegmentAlignmentService(ctx).align(source, target, config=config)
    assert summary.alignments == 2
