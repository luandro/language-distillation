"""Canonical, text-free Stage 5 report contracts."""

import json
from pathlib import Path

from langpipe.alignment.base import (
    AlignmentConfig,
    BackendMetadata,
    TokenBatchOutput,
    TokenLinks,
)
from langpipe.alignment.segment_service import SegmentAlignmentService
from langpipe.alignment.token_service import TokenAlignmentService
from langpipe.domain.enums import (
    AccessClass,
    ArtifactKind,
    LineageKind,
    RunIoRole,
)
from langpipe.text.registry import VersionedRegistry
from tests.service.test_token_alignment_service import _side


class _Empty:
    name = "empty"
    version = "0.1.0"

    def align(self, groups, config):
        return TokenBatchOutput(
            tuple(TokenLinks(g.alignment_id, (), ()) for g in groups),
            BackendMetadata("0.1.0", None, {}, False),
        )


class _OneLink:
    name = "linked"
    version = "0.1.0"

    def align(self, groups, config):
        from langpipe.alignment.base import IndexLink

        return TokenBatchOutput(
            tuple(
                TokenLinks(g.alignment_id, (IndexLink(0, 0),), (IndexLink(0, 0),)) for g in groups
            ),
            BackendMetadata("0.1.0", None, {}, False),
        )


def test_empty_side_report_no_forced_links(ctx, tmp_path: Path) -> None:
    a = _side(ctx, tmp_path, "report-a", "qaa", "   ")
    b = _side(ctx, tmp_path, "report-b", "por", "homem")
    segment = SegmentAlignmentService(ctx).align(
        a.side, b.side, config=AlignmentConfig(namespace="refs")
    )
    result = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Empty(),))).align(
        segment.run.id,
        source_tokenization_run_id=a.tokenization_run_id,
        target_tokenization_run_id=b.tokenization_run_id,
        method="empty@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    report = result.report
    assert report is not None and report.kind is ArtifactKind.ALIGNMENT_FILE
    raw = ctx.artifact_store.read_bytes(report.sha256)
    payload = json.loads(raw)
    assert payload["schema"] == "token-alignment-report"
    assert payload["schema_version"] == 1
    assert payload["groups"][0]["reason"] == "empty_token_side"
    selected = ctx.repo.list_segment_alignments_for_run(segment.run.id)[0]
    assert payload["groups"][0]["source_segment_ids"] == list(selected.source_segment_ids)
    assert payload["groups"][0]["target_segment_ids"] == list(selected.target_segment_ids)
    assert payload["groups"][0]["status"] == selected.status.value
    assert payload["groups"][0]["links"]["forward"] == []
    assert b"report-a.tsv" not in raw
    targets = {
        edge.to_id
        for edge in ctx.repo.list_lineage_edges(report.id, "out")
        if edge.kind is LineageKind.DERIVED_FROM
    }
    assert selected.id in targets
    assert set(selected.source_segment_ids + selected.target_segment_ids) <= targets
    assert a.side.source_id in targets and b.side.source_id in targets


def test_complete_run_io_and_lineage(ctx, tmp_path: Path) -> None:
    a = _side(ctx, tmp_path, "lineage-a", "qaa", "kanu")
    b = _side(ctx, tmp_path, "lineage-b", "por", "homem")
    segment = SegmentAlignmentService(ctx).align(
        a.side, b.side, config=AlignmentConfig(namespace="refs")
    )
    result = TokenAlignmentService(ctx, aligners=VersionedRegistry((_OneLink(),))).align(
        segment.run.id,
        source_tokenization_run_id=a.tokenization_run_id,
        target_tokenization_run_id=b.tokenization_run_id,
        method="linked@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    groups = ctx.repo.list_segment_alignments_for_run(segment.run.id)
    group = groups[0]
    tokens = [
        token
        for segment_id in (*group.source_segment_ids, *group.target_segment_ids)
        for token in ctx.repo.list_tokens(segment_id)
    ]
    edges = ctx.repo.list_token_alignment_edges_for_run(result.run.id)
    assert edges
    for edge in edges:
        parents = {
            item.to_id
            for item in ctx.repo.list_lineage_edges(edge.id, "out")
            if item.kind is LineageKind.DERIVED_FROM
        }
        assert parents == {edge.segment_alignment_id, edge.source_token_id, edge.target_token_id}
        assert (edge.id, RunIoRole.OUTPUT) in ctx.repo.list_run_io(result.run.id)
    lineage = ctx.repo.list_lineage_edges(result.report.id, "out")
    assert {edge.to_id for edge in lineage if edge.kind is LineageKind.DERIVED_FROM} == {
        group.id,
        *group.source_segment_ids,
        *group.target_segment_ids,
        *(token.id for token in tokens),
        a.side.source_id,
        b.side.source_id,
        *(edge.id for edge in edges),
    }
    io = ctx.repo.list_run_io(result.run.id)
    assert (result.report.id, RunIoRole.OUTPUT) in io
    expected_inputs = {
        group.id,
        *group.source_segment_ids,
        *group.target_segment_ids,
        *(token.id for token in tokens),
        a.side.source_id,
        b.side.source_id,
        a.side.normalization_run_id,
        b.side.normalization_run_id,
        a.tokenization_run_id,
        b.tokenization_run_id,
        segment.run.id,
    }
    assert {item for item, role in io if role is RunIoRole.INPUT} == expected_inputs


def test_report_access_class_is_most_restrictive(ctx, tmp_path: Path) -> None:
    a = _side(ctx, tmp_path, "access-a", "qaa", "kanu", access_class="public")
    b = _side(ctx, tmp_path, "access-b", "por", "homem", access_class="restricted")
    segment = SegmentAlignmentService(ctx).align(
        a.side, b.side, config=AlignmentConfig(namespace="refs")
    )
    result = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Empty(),))).align(
        segment.run.id,
        source_tokenization_run_id=a.tokenization_run_id,
        target_tokenization_run_id=b.tokenization_run_id,
        method="empty@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    assert result.report.access_class is AccessClass.RESTRICTED
