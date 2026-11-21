from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from langpipe.alignment.base import AlignmentConfig, AlignmentSide
from langpipe.alignment.segment_service import SegmentAlignmentService
from langpipe.alignment.token_service import TokenAlignmentService
from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AccessClass,
    ArtifactKind,
    EntityType,
    LineageKind,
    Operation,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
)
from langpipe.domain.errors import AlignmentFailed, NotFound, PolicyDenied
from langpipe.domain.hashing import canonical_json
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.run import Artifact
from langpipe.evaluation.alignment import (
    GoldAlignment,
    GoldGroup,
    GoldGroupLocatorSelector,
    GoldTokenSelector,
)
from langpipe.evaluation.service import BenchmarkService
from langpipe.extraction.service import extract_source
from langpipe.governance.lineage_policy import ancestor_source_ids, effective_decision
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.ingestion.runs import RunRecorder
from langpipe.normalization.service import normalize_extraction
from langpipe.storage.memory import InMemoryRepository
from langpipe.storage.objects.local import LocalContentStore
from langpipe.text.registry import VersionedRegistry
from langpipe.tokenization.service import tokenize_normalization
from tests.service.manifests import manifest_data, write_manifest, write_origin_file
from tests.service.test_token_alignment_service import _DisjointLinks, _Links, _Side, _side

TSV = "text/tab-separated-values"


def _side_content(
    ctx: AppContext, tmp_path: Path, key: str, language: str, content: bytes
) -> _Side:
    tmp_path.mkdir(parents=True, exist_ok=True)
    relative = f"texts/{key}.tsv"
    write_origin_file(tmp_path, relative, content)
    data = manifest_data(key=key, mode="direct", objects=[{"path": relative, "media_type": TSV}])
    data["source_type"] = "wordlist"
    data["languages"] = [language]
    source = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml")).source
    ingest_source(ctx, source.id)
    extraction = extract_source(ctx, source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    tokenization = tokenize_normalization(ctx, normalization.run.id)
    return _Side(AlignmentSide(source.id, language, normalization.run.id), tokenization.run.id)


def _side_with_mode(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    language: str,
    mode: str,
    *,
    deny_redistribute: bool = False,
    deny_operations: tuple[str, ...] = (),
    text: str = "kanu mabi.",
) -> _Side:
    relative = f"texts/{key}.tsv"
    write_origin_file(tmp_path, relative, f"ref\t{language}\nT.1\t{text}\n".encode())
    data = manifest_data(key=key, mode=mode, objects=[{"path": relative, "media_type": TSV}])
    if deny_redistribute:
        data["policy"]["deny"] = ["redistribute_derived"]
    if deny_operations:
        data["policy"]["deny"] = list(deny_operations)
    data["source_type"] = "wordlist"
    data["languages"] = [language]
    source = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml")).source
    ingest_source(ctx, source.id)
    extraction = extract_source(ctx, source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    tokenization = tokenize_normalization(ctx, normalization.run.id)
    return _Side(AlignmentSide(source.id, language, normalization.run.id), tokenization.run.id)


def _gold(
    ctx: AppContext,
    source,
    target,
    alignment,
    source_tokens,
    target_tokens,
    *,
    source_norm_ver: str | None = None,
    selector_token_id_override: str | None = None,
    schema_name: str = "alignment-gold",
    lineage_source_ids: tuple[str, ...] | None = None,
    schema_version: int = 1,
    kind: ArtifactKind = ArtifactKind.ALIGNMENT_FILE,
    group_key_binding: bool = False,
    source_tokenizer_version: str | None = None,
    target_tokenizer_version: str | None = None,
    source_selectors: tuple[GoldTokenSelector, ...] | None = None,
    selector_ids: bool = True,
    locator_selector: GoldGroupLocatorSelector | None = None,
    gold_alignment: GoldAlignment | None = None,
) -> Artifact:
    source_segments = [ctx.repo.get_segment(i) for i in alignment.source_segment_ids]
    target_segments = [ctx.repo.get_segment(i) for i in alignment.target_segment_ids]

    def selectors(tokens, segment_ids, is_source=False):
        return tuple(
            GoldTokenSelector(
                member=segment_ids.index(t.segment_id),
                ordinal=t.ordinal,
                token_id=selector_token_id_override
                if is_source and idx == 0 and selector_token_id_override is not None
                else (t.id if selector_ids else None),
            )
            for idx, t in enumerate(tokens)
        )

    group = GoldGroup(
        id="gold-1",
        group_id=None if group_key_binding or locator_selector is not None else alignment.id,
        group_key=alignment.group_key if group_key_binding else None,
        locator_selector=locator_selector,
        source_normalization_version=source_norm_ver
        if source_norm_ver is not None
        else source_segments[0].normalization_profile,
        target_normalization_version=target_segments[0].normalization_profile,
        source_tokenizer_version=source_tokenizer_version or source_tokens[0].tokenizer,
        target_tokenizer_version=target_tokenizer_version or target_tokens[0].tokenizer,
        source_tokens=source_selectors
        if source_selectors is not None
        else selectors(source_tokens, alignment.source_segment_ids, is_source=True),
        target_tokens=selectors(target_tokens, alignment.target_segment_ids),
        sure_links=((0, 0),),
        possible_links=((0, 0),),
        authority="synthetic-test",
    )
    gold_value = gold_alignment or GoldAlignment(groups=(group,))
    stored = ctx.artifact_store.put_bytes(
        canonical_json(gold_value.model_dump(mode="json")).encode()
    )
    inputs = list(
        lineage_source_ids
        if lineage_source_ids is not None
        else (source.side.source_id, target.side.source_id)
    )
    recorder = RunRecorder(ctx)
    run = recorder.start(
        RunStage.EVALUATION,
        "test.gold_registration",
        {"fixture": "alignment-gold", "sha256": stored.sha256},
        inputs,
    )
    artifact = Artifact(
        id=ctx.new_id(IdPrefix.ARTIFACT),
        run_id=run.id,
        kind=kind,
        media_type="application/json",
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        access_class=AccessClass.PUBLIC,
        schema_name=schema_name,
        schema_version=schema_version,
        created_at=ctx.clock(),
    )
    with ctx.repo.transaction():
        ctx.repo.add_artifact(artifact)
        for input_id in inputs:
            ctx.repo.add_run_io(run.id, input_id, RunIoRole.INPUT)
        ctx.repo.add_run_io(run.id, artifact.id, RunIoRole.OUTPUT)
        for source_id in inputs:
            ctx.repo.add_lineage_edge(
                LineageEdge(
                    id=ctx.new_id(IdPrefix.LINEAGE),
                    from_id=artifact.id,
                    to_id=source_id,
                    kind=LineageKind.DERIVED_FROM,
                    run_id=run.id,
                    created_at=ctx.clock(),
                )
            )
        recorder.succeed(run.id)
    return artifact


def _benchmark_setup(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    source: _Side | None = None,
    target: _Side | None = None,
):
    source = source or _side(ctx, tmp_path, f"{key}-a", "qaa", "kanu mabi.")
    target = target or _side(ctx, tmp_path, f"{key}-b", "por", "O homem vê.")
    segment = SegmentAlignmentService(ctx).align(
        source.side, target.side, config=AlignmentConfig(namespace="refs")
    )
    alignment = ctx.repo.list_segment_alignments_for_run(segment.run.id)[0]
    token_run = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
        segment.run.id,
        source_tokenization_run_id=source.tokenization_run_id,
        target_tokenization_run_id=target.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    source_tokens = [
        t
        for sid in alignment.source_segment_ids
        for t in ctx.repo.list_tokens(sid)
        if t.run_id == source.tokenization_run_id
    ]
    target_tokens = [
        t
        for sid in alignment.target_segment_ids
        for t in ctx.repo.list_tokens(sid)
        if t.run_id == target.tokenization_run_id
    ]
    return source, target, alignment, token_run, source_tokens, target_tokens


def test_benchmark_persists_metrics_and_report(ctx: AppContext, tmp_path: Path) -> None:
    source = _side(ctx, tmp_path, "benchmark-a", "qaa", "kanu mabi.")
    target = _side(ctx, tmp_path, "benchmark-b", "por", "O homem vê.")
    segment = SegmentAlignmentService(ctx).align(
        source.side, target.side, config=AlignmentConfig(namespace="refs")
    )
    alignment = ctx.repo.list_segment_alignments_for_run(segment.run.id)[0]
    token_run = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
        segment.run.id,
        source_tokenization_run_id=source.tokenization_run_id,
        target_tokenization_run_id=target.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    source_tokens = [
        t
        for sid in alignment.source_segment_ids
        for t in ctx.repo.list_tokens(sid)
        if t.run_id == source.tokenization_run_id
    ]
    target_tokens = [
        t
        for sid in alignment.target_segment_ids
        for t in ctx.repo.list_tokens(sid)
        if t.run_id == target.tokenization_run_id
    ]
    gold = _gold(ctx, source, target, alignment, source_tokens, target_tokens)
    service = BenchmarkService(ctx)
    result = service.evaluate(token_run.run.id, gold.id)
    assert (
        result.metrics.total_predicted
        == result.metrics.total_sure
        == result.metrics.total_possible
        == 1
    )
    assert result.metrics.precision == result.metrics.recall == result.metrics.f1 == 1.0
    assert result.metrics.aer == 0.0
    assert result.run.stage is RunStage.EVALUATION
    report = json.loads(ctx.artifact_store.read_bytes(result.report.sha256))
    assert report["protocol"] == "transductive_unsupervised"
    assert (result.report.id, RunIoRole.OUTPUT.value) in {
        (oid, role.value) for oid, role in ctx.repo.list_run_io(result.run.id)
    }
    lineage_inputs = {edge.to_id for edge in ctx.repo.list_lineage_edges(result.report.id, "out")}
    chosen_ids = {
        e.id
        for e in ctx.repo.list_token_alignment_edges_for_run(token_run.run.id)
        if e.direction.value == "symmetrized"
    }
    assert {token_run.run.id, gold.id, *chosen_ids} <= lineage_inputs
    assert token_run.run.id in {
        oid for oid, role in ctx.repo.list_run_io(result.run.id) if role is RunIoRole.INPUT
    }
    expected_inputs = {
        token_run.run.id,
        gold.id,
        *chosen_ids,
        *(
            object_id
            for object_id, role in ctx.repo.list_run_io(token_run.run.id)
            if role is RunIoRole.INPUT
        ),
    }
    actual_inputs = {
        object_id
        for object_id, role in ctx.repo.list_run_io(result.run.id)
        if role is RunIoRole.INPUT
    }
    assert actual_inputs == expected_inputs
    report_bytes = ctx.artifact_store.read_bytes(result.report.sha256)
    assert all(
        t.raw_surface.encode() not in report_bytes
        for t in (*source_tokens, *target_tokens)
        if len(t.raw_surface) > 1
    )
    repeated = service.evaluate(token_run.run.id, gold.id)
    assert (
        repeated.reused
        and repeated.run.id == result.run.id
        and repeated.report.id == result.report.id
    )


def test_committed_portable_gold_fixture_binds_across_fresh_installations(
    ctx: AppContext, tmp_path: Path
) -> None:
    fixture = GoldAlignment.model_validate_json(
        (Path(__file__).parents[1] / "fixtures/alignment/gold.v1.json").read_bytes()
    )
    first_ctx_root = tmp_path / "installation-a"
    first_source_side = _side_content(
        ctx, first_ctx_root, "fixture-a", "qaa", b"ref\tqaa\nT.1\tkanu mabi.\n"
    )
    first_target_side = _side_content(
        ctx, first_ctx_root, "fixture-b", "por", b"ref\tpor\nT.1\tO homem.\nT.1\tEle ve.\n"
    )
    first = _benchmark_setup(
        ctx, first_ctx_root, "fixture", source=first_source_side, target=first_target_side
    )
    first_source, first_target, first_alignment, first_run, first_src, first_tgt = first
    assert len(first_alignment.source_segment_ids) == 1
    assert len(first_alignment.target_segment_ids) == 2
    assert [
        ctx.repo.get_segment(sid).locator["row"] for sid in first_alignment.target_segment_ids
    ] == [2, 3]
    fixture_group = fixture.groups[0]
    assert fixture_group.locator_selector is not None
    reversed_group = fixture_group.model_copy(
        update={
            "locator_selector": fixture_group.locator_selector.model_copy(
                update={
                    "target_members": tuple(reversed(fixture_group.locator_selector.target_members))
                }
            )
        }
    )
    reversed_fixture = fixture.model_copy(update={"groups": (reversed_group,)})
    reversed_gold = _gold(
        ctx,
        first_source,
        first_target,
        first_alignment,
        first_src,
        first_tgt,
        selector_ids=False,
        gold_alignment=reversed_fixture,
    )
    with pytest.raises(AlignmentFailed, match="invalid_gold"):
        BenchmarkService(ctx).evaluate(first_run.run.id, reversed_gold.id)
    first_gold = _gold(
        ctx,
        first_source,
        first_target,
        first_alignment,
        first_src,
        first_tgt,
        selector_ids=False,
        gold_alignment=fixture,
    )
    first_result = BenchmarkService(ctx).evaluate(first_run.run.id, first_gold.id)

    second_ctx = AppContext(
        repo=InMemoryRepository(),
        raw_store=LocalContentStore(tmp_path / "installation-b" / "raw"),
        artifact_store=LocalContentStore(tmp_path / "installation-b" / "artifacts"),
        clock=lambda: datetime.now(UTC),
        new_id=new_id,
        actor="test-actor",
        code_revision="test-rev",
    )
    second_ctx_root = tmp_path / "installation-b"
    second_source_side = _side_content(
        second_ctx, second_ctx_root, "fixture-a", "qaa", b"ref\tqaa\nT.1\tkanu mabi.\n"
    )
    second_target_side = _side_content(
        second_ctx, second_ctx_root, "fixture-b", "por", b"ref\tpor\nT.1\tO homem.\nT.1\tEle ve.\n"
    )
    second = _benchmark_setup(
        second_ctx, second_ctx_root, "fixture", source=second_source_side, target=second_target_side
    )
    second_source, second_target, second_alignment, second_run, second_src, second_tgt = second
    assert first_alignment.id != second_alignment.id
    second_gold = _gold(
        second_ctx,
        second_source,
        second_target,
        second_alignment,
        second_src,
        second_tgt,
        selector_ids=False,
        gold_alignment=fixture,
    )
    second_result = BenchmarkService(second_ctx).evaluate(second_run.run.id, second_gold.id)
    assert second_result.metrics == first_result.metrics


def test_portable_gold_locator_fails_closed_when_selector_missing(
    ctx: AppContext, tmp_path: Path
) -> None:
    source, target, alignment, token_run, source_tokens, target_tokens = _benchmark_setup(
        ctx, tmp_path, "bench-portable-missing"
    )
    tgt_seg = ctx.repo.get_segment(alignment.target_segment_ids[0])
    tgt_obj = ctx.repo.get_source_object(tgt_seg.source_object_id)
    selector = GoldGroupLocatorSelector(
        namespace="refs",
        source_members=({"source_object_path": "missing.tsv", "locator": {"ref": "T.1"}},),
        target_members=(
            {
                "source_object_path": tgt_obj.original_path,
                "locator": dict(tgt_seg.locator),
            },
        ),
    )
    gold = _gold(
        ctx,
        source,
        target,
        alignment,
        source_tokens,
        target_tokens,
        selector_ids=False,
        locator_selector=selector,
    )
    runs_before = ctx.repo.count(EntityType.PROCESSING_RUN)
    artifacts_before = ctx.repo.count(EntityType.ARTIFACT)
    with pytest.raises(AlignmentFailed, match="invalid_gold"):
        BenchmarkService(ctx).evaluate(token_run.run.id, gold.id)
    assert ctx.repo.count(EntityType.PROCESSING_RUN) == runs_before
    assert ctx.repo.count(EntityType.ARTIFACT) == artifacts_before
    assert not ctx.repo.list_runs_with_input(token_run.run.id, RunStage.EVALUATION)


def test_portable_gold_locator_fails_closed_when_selector_ambiguous(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target, alignment, token_run, source_tokens, target_tokens = _benchmark_setup(
        ctx, tmp_path, "bench-portable-ambiguous"
    )
    src_seg = ctx.repo.get_segment(alignment.source_segment_ids[0])
    tgt_seg = ctx.repo.get_segment(alignment.target_segment_ids[0])
    src_obj = ctx.repo.get_source_object(src_seg.source_object_id)
    tgt_obj = ctx.repo.get_source_object(tgt_seg.source_object_id)
    selector = GoldGroupLocatorSelector(
        namespace="refs",
        source_members=(
            {
                "source_object_path": src_obj.original_path,
                "locator": dict(src_seg.locator),
            },
        ),
        target_members=(
            {
                "source_object_path": tgt_obj.original_path,
                "locator": dict(tgt_seg.locator),
            },
        ),
    )
    gold = _gold(
        ctx,
        source,
        target,
        alignment,
        source_tokens,
        target_tokens,
        selector_ids=False,
        locator_selector=selector,
    )
    alt_alignment = alignment.model_copy(update={"id": ctx.new_id(IdPrefix.SEGMENT_ALIGNMENT)})
    assert alt_alignment.id != alignment.id
    candidates = [alignment, alt_alignment]
    id_map = {g.id: g for g in candidates}
    assert len(id_map) == 2
    matching = [
        row
        for row in id_map.values()
        if BenchmarkService._locator_selector_matches(selector, row, ctx.repo)
    ]
    assert len(matching) == 2

    monkeypatch.setattr(ctx.repo, "list_segment_alignments_for_run", lambda run_id: candidates)
    runs_before = ctx.repo.count(EntityType.PROCESSING_RUN)
    artifacts_before = ctx.repo.count(EntityType.ARTIFACT)
    with pytest.raises(AlignmentFailed, match="invalid_gold"):
        BenchmarkService(ctx).evaluate(token_run.run.id, gold.id)
    assert ctx.repo.count(EntityType.PROCESSING_RUN) == runs_before
    assert ctx.repo.count(EntityType.ARTIFACT) == artifacts_before
    assert not ctx.repo.list_runs_with_input(token_run.run.id, RunStage.EVALUATION)


def test_empty_predictions_keep_both_prediction_sources_in_report_ancestry(
    ctx: AppContext, tmp_path: Path
) -> None:
    source = _side(ctx, tmp_path, "bench-empty-a", "qaa", "kanu mabi.")
    target = _side(ctx, tmp_path, "bench-empty-b", "por", "O homem vê.")
    gold_owner = _side(ctx, tmp_path, "bench-empty-gold", "spa", "El hombre ve.")
    segment = SegmentAlignmentService(ctx).align(
        source.side, target.side, config=AlignmentConfig(namespace="refs")
    )
    alignment = ctx.repo.list_segment_alignments_for_run(segment.run.id)[0]
    token_run = TokenAlignmentService(ctx, aligners=VersionedRegistry((_DisjointLinks(),))).align(
        segment.run.id,
        source_tokenization_run_id=source.tokenization_run_id,
        target_tokenization_run_id=target.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    source_tokens = [
        t
        for t in ctx.repo.list_tokens(alignment.source_segment_ids[0])
        if t.run_id == source.tokenization_run_id
    ]
    target_tokens = [
        t
        for t in ctx.repo.list_tokens(alignment.target_segment_ids[0])
        if t.run_id == target.tokenization_run_id
    ]
    gold = _gold(
        ctx,
        source,
        target,
        alignment,
        source_tokens,
        target_tokens,
        lineage_source_ids=(gold_owner.side.source_id,),
        group_key_binding=True,
        selector_ids=False,
    )
    source_before = ctx.repo.get_source(source.side.source_id)
    target_before = ctx.repo.get_source(target.side.source_id)
    tokens_before = tuple(source_tokens + target_tokens)

    result = BenchmarkService(ctx).evaluate(token_run.run.id, gold.id)

    assert result.metrics.total_predicted == 0
    ancestors = set(ancestor_source_ids(ctx.repo, result.report.id))
    assert ancestors == {
        source.side.source_id,
        target.side.source_id,
        gold_owner.side.source_id,
    }
    assert effective_decision(ctx.repo, result.report.id, Operation.EVALUATION).value == "allow"
    assert ctx.repo.get_source(source.side.source_id) == source_before
    assert ctx.repo.get_source(target.side.source_id) == target_before
    assert (
        tuple(
            t
            for sid in (*alignment.source_segment_ids, *alignment.target_segment_ids)
            for t in ctx.repo.list_tokens(sid)
            if t.run_id in (source.tokenization_run_id, target.tokenization_run_id)
        )
        == tokens_before
    )


def test_partially_empty_groups_keep_prediction_restrictions(
    ctx: AppContext, tmp_path: Path
) -> None:
    source = _side_with_mode(
        ctx,
        tmp_path,
        "bench-partial-a",
        "qaa",
        "direct",
        deny_redistribute=True,
        text="kanu\nT.2\tmabi",
    )
    target = _side_with_mode(
        ctx, tmp_path, "bench-partial-b", "por", "direct", text="homem\nT.2\tve"
    )
    gold_owner = _side(ctx, tmp_path, "bench-partial-gold", "spa", "El hombre ve.")
    segment = SegmentAlignmentService(ctx).align(
        source.side, target.side, config=AlignmentConfig(namespace="refs")
    )
    alignments = ctx.repo.list_segment_alignments_for_run(segment.run.id)
    assert len(alignments) == 2

    class _EmptyForwardReverseDisagreement(_Links):
        def align(self, groups, config):
            output = super().align(groups, config)
            links = output.groups[0]
            return type(output)(
                (
                    links,
                    *(type(item)(item.alignment_id, (), ()) for item in output.groups[1:]),
                ),
                output.backend,
            )

    token_run = TokenAlignmentService(
        ctx, aligners=VersionedRegistry((_EmptyForwardReverseDisagreement(),))
    ).align(
        segment.run.id,
        source_tokenization_run_id=source.tokenization_run_id,
        target_tokenization_run_id=target.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    # One group has links and the other remains empty in this same run.
    chosen_edges = ctx.repo.list_token_alignment_edges_for_run(token_run.run.id)
    assert len(chosen_edges) == 3
    alignment = next(row for row in alignments if row.id == chosen_edges[0].segment_alignment_id)
    source_tokens = [
        t
        for t in ctx.repo.list_tokens(alignment.source_segment_ids[0])
        if t.run_id == source.tokenization_run_id
    ]
    target_tokens = [
        t
        for t in ctx.repo.list_tokens(alignment.target_segment_ids[0])
        if t.run_id == target.tokenization_run_id
    ]
    gold = _gold(
        ctx,
        source,
        target,
        alignment,
        source_tokens,
        target_tokens,
        lineage_source_ids=(gold_owner.side.source_id,),
    )
    result = BenchmarkService(ctx).evaluate(token_run.run.id, gold.id)
    assert result.metrics.total_predicted == 1
    assert set(ancestor_source_ids(ctx.repo, result.report.id)) == {
        source.side.source_id,
        target.side.source_id,
        gold_owner.side.source_id,
    }
    with ctx.repo.transaction():
        ctx.repo.set_source_status(source.side.source_id, SourceStatus.REVOKED, at=ctx.clock())
    assert (
        effective_decision(ctx.repo, result.report.id, Operation.REDISTRIBUTE_DERIVED).value
        == "deny"
    )


def test_semantic_failure_rolls_back_report_and_redacts_failed_run(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target, alignment, token_run, source_tokens, target_tokens = _benchmark_setup(
        ctx, tmp_path, "bench-atomic"
    )
    gold = _gold(ctx, source, target, alignment, source_tokens, target_tokens)
    service = BenchmarkService(ctx)
    started = []
    original_start = service.recorder.start

    def capture_start(*args, **kwargs):
        run = original_start(*args, **kwargs)
        started.append(run)
        return run

    monkeypatch.setattr(service.recorder, "start", capture_start)
    reports: list[str] = []
    original_add_artifact = ctx.repo.add_artifact

    def capture_report(artifact):
        if artifact.kind is ArtifactKind.BENCHMARK_REPORT:
            reports.append(artifact.id)
        return original_add_artifact(artifact)

    monkeypatch.setattr(ctx.repo, "add_artifact", capture_report)

    def fail_lineage(_edge):
        raise RuntimeError("private source surface")

    monkeypatch.setattr(ctx.repo, "add_lineage_edge", fail_lineage)
    with pytest.raises(RuntimeError):
        service.evaluate(token_run.run.id, gold.id)
    assert len(started) == len(reports) == 1
    failed = ctx.repo.get_run(started[0].id)
    assert failed.status is RunStatus.FAILED
    assert failed.error_type == "RuntimeError" and failed.error_message is None
    assert ctx.repo.list_run_io(failed.id) == []
    with pytest.raises(NotFound):
        ctx.repo.get_artifact(reports[0])
    assert ctx.repo.list_lineage_edges(reports[0], "out") == []
    assert all(
        source_token == ctx.repo.get_token(source_token.id) for source_token in source_tokens
    )


def test_commit_time_source_revocation_recheck_blocks_publication(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target, alignment, token_run, source_tokens, target_tokens = _benchmark_setup(
        ctx, tmp_path, "bench-commit-revoke"
    )
    gold = _gold(ctx, source, target, alignment, source_tokens, target_tokens)
    service = BenchmarkService(ctx)
    started = []
    original_start = service.recorder.start

    def capture_start(*args, **kwargs):
        run = original_start(*args, **kwargs)
        started.append(run)
        return run

    monkeypatch.setattr(service.recorder, "start", capture_start)
    original_lock = ctx.repo.lock_sources

    def lock_then_revoke(source_ids):
        original_lock(source_ids)
        if source.side.source_id in source_ids:
            ctx.repo.set_source_status(source.side.source_id, SourceStatus.REVOKED, at=ctx.clock())

    monkeypatch.setattr(ctx.repo, "lock_sources", lock_then_revoke)
    with pytest.raises(PolicyDenied):
        service.evaluate(token_run.run.id, gold.id)
    assert len(started) == 1
    failed = ctx.repo.get_run(started[0].id)
    assert failed.status is RunStatus.FAILED
    assert ctx.repo.list_run_io(failed.id) == []
    assert ctx.repo.list_lineage_edges(failed.id, "out") == []


def test_version_mismatch_fails_invalid_gold(ctx: AppContext, tmp_path: Path) -> None:
    source = _side(ctx, tmp_path, "bench-ver-a", "qaa", "kanu mabi.")
    target = _side(ctx, tmp_path, "bench-ver-b", "por", "O homem vê.")
    segment = SegmentAlignmentService(ctx).align(
        source.side, target.side, config=AlignmentConfig(namespace="refs")
    )
    alignment = ctx.repo.list_segment_alignments_for_run(segment.run.id)[0]
    token_run = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
        segment.run.id,
        source_tokenization_run_id=source.tokenization_run_id,
        target_tokenization_run_id=target.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    source_tokens = [
        t
        for sid in alignment.source_segment_ids
        for t in ctx.repo.list_tokens(sid)
        if t.run_id == source.tokenization_run_id
    ]
    target_tokens = [
        t
        for sid in alignment.target_segment_ids
        for t in ctx.repo.list_tokens(sid)
        if t.run_id == target.tokenization_run_id
    ]
    gold = _gold(
        ctx,
        source,
        target,
        alignment,
        source_tokens,
        target_tokens,
        source_norm_ver="nonexistent@9.9.9",
    )
    service = BenchmarkService(ctx)
    with pytest.raises(AlignmentFailed) as exc_info:
        service.evaluate(token_run.run.id, gold.id)
    assert exc_info.value.code == "invalid_gold"


def test_selector_mismatch_fails_invalid_gold(ctx: AppContext, tmp_path: Path) -> None:
    source = _side(ctx, tmp_path, "bench-sel-a", "qaa", "kanu mabi.")
    target = _side(ctx, tmp_path, "bench-sel-b", "por", "O homem vê.")
    segment = SegmentAlignmentService(ctx).align(
        source.side, target.side, config=AlignmentConfig(namespace="refs")
    )
    alignment = ctx.repo.list_segment_alignments_for_run(segment.run.id)[0]
    token_run = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
        segment.run.id,
        source_tokenization_run_id=source.tokenization_run_id,
        target_tokenization_run_id=target.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    source_tokens = [
        t
        for sid in alignment.source_segment_ids
        for t in ctx.repo.list_tokens(sid)
        if t.run_id == source.tokenization_run_id
    ]
    target_tokens = [
        t
        for sid in alignment.target_segment_ids
        for t in ctx.repo.list_tokens(sid)
        if t.run_id == target.tokenization_run_id
    ]
    gold = _gold(
        ctx,
        source,
        target,
        alignment,
        source_tokens,
        target_tokens,
        selector_token_id_override="tok_different",
    )
    service = BenchmarkService(ctx)
    with pytest.raises(AlignmentFailed) as exc_info:
        service.evaluate(token_run.run.id, gold.id)
    assert exc_info.value.code == "invalid_gold"


def test_gold_artifact_wrong_kind_or_schema_fails_invalid_gold(
    ctx: AppContext, tmp_path: Path
) -> None:
    source = _side(ctx, tmp_path, "bench-kind-a", "qaa", "kanu mabi.")
    target = _side(ctx, tmp_path, "bench-kind-b", "por", "O homem vê.")
    segment = SegmentAlignmentService(ctx).align(
        source.side, target.side, config=AlignmentConfig(namespace="refs")
    )
    alignment = ctx.repo.list_segment_alignments_for_run(segment.run.id)[0]
    token_run = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
        segment.run.id,
        source_tokenization_run_id=source.tokenization_run_id,
        target_tokenization_run_id=target.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    source_tokens = [
        t
        for sid in alignment.source_segment_ids
        for t in ctx.repo.list_tokens(sid)
        if t.run_id == source.tokenization_run_id
    ]
    target_tokens = [
        t
        for sid in alignment.target_segment_ids
        for t in ctx.repo.list_tokens(sid)
        if t.run_id == target.tokenization_run_id
    ]
    gold = _gold(
        ctx, source, target, alignment, source_tokens, target_tokens, schema_name="wrong-schema"
    )
    service = BenchmarkService(ctx)
    with pytest.raises(AlignmentFailed) as exc_info:
        service.evaluate(token_run.run.id, gold.id)
    assert exc_info.value.code == "invalid_gold"


@pytest.mark.parametrize(
    "gold_overrides",
    [
        {"kind": ArtifactKind.BENCHMARK_REPORT},
        {"schema_version": 2},
    ],
)
def test_wrong_artifact_kind_or_schema_version_is_rejected(
    ctx: AppContext, tmp_path: Path, gold_overrides: dict[str, object]
) -> None:
    source, target, alignment, token_run, source_tokens, target_tokens = _benchmark_setup(
        ctx, tmp_path, "bench-schema"
    )
    gold = _gold(ctx, source, target, alignment, source_tokens, target_tokens, **gold_overrides)
    with pytest.raises(AlignmentFailed, match="invalid_gold"):
        BenchmarkService(ctx).evaluate(token_run.run.id, gold.id)


@pytest.mark.parametrize("selector_error", ("ordinal", "member", "count"))
def test_tokenizer_or_selector_array_mismatch_is_rejected(
    ctx: AppContext, tmp_path: Path, selector_error: str
) -> None:
    source, target, alignment, token_run, source_tokens, target_tokens = _benchmark_setup(
        ctx, tmp_path, "bench-selector-array"
    )
    selectors = tuple(
        GoldTokenSelector(member=0, ordinal=token.ordinal, token_id=token.id)
        for token in source_tokens
    )
    if selector_error == "ordinal":
        selectors = (*selectors[:-1], GoldTokenSelector(member=0, ordinal=99))
    elif selector_error == "member":
        selectors = tuple(
            GoldTokenSelector(member=1, ordinal=selector.ordinal) for selector in selectors
        )
    else:
        selectors = selectors[:-1]
    gold = _gold(
        ctx,
        source,
        target,
        alignment,
        source_tokens,
        target_tokens,
        source_selectors=selectors,
    )
    with pytest.raises(AlignmentFailed, match="invalid_gold"):
        BenchmarkService(ctx).evaluate(token_run.run.id, gold.id)


@pytest.mark.parametrize("side", ("source", "target"))
def test_tokenizer_version_mismatch_is_rejected_independently(
    ctx: AppContext, tmp_path: Path, side: str
) -> None:
    source, target, alignment, token_run, source_tokens, target_tokens = _benchmark_setup(
        ctx, tmp_path, f"bench-tokenizer-{side}"
    )
    gold = _gold(
        ctx,
        source,
        target,
        alignment,
        source_tokens,
        target_tokens,
        source_tokenizer_version="wrong-tokenizer@9" if side == "source" else None,
        target_tokenizer_version="wrong-tokenizer@9" if side == "target" else None,
    )
    with pytest.raises(AlignmentFailed, match="invalid_gold"):
        BenchmarkService(ctx).evaluate(token_run.run.id, gold.id)


@pytest.mark.parametrize("denied_ancestry", ("source", "target", "gold"))
def test_evaluation_denial_precedes_gold_read_and_run_start(
    ctx: AppContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    denied_ancestry: str,
) -> None:
    source = (
        _side_with_mode(
            ctx, tmp_path, "bench-deny-source", "qaa", "direct", deny_operations=("evaluation",)
        )
        if denied_ancestry == "source"
        else _side(ctx, tmp_path, "bench-deny-source", "qaa", "kanu mabi.")
    )
    target = (
        _side_with_mode(
            ctx, tmp_path, "bench-deny-target", "por", "direct", deny_operations=("evaluation",)
        )
        if denied_ancestry == "target"
        else _side(ctx, tmp_path, "bench-deny-target", "por", "O homem vê.")
    )
    source, target, alignment, token_run, source_tokens, target_tokens = _benchmark_setup(
        ctx, tmp_path, "bench-deny", source, target
    )
    gold_owner = (
        _side_with_mode(
            ctx, tmp_path, "bench-deny-gold", "spa", "direct", deny_operations=("evaluation",)
        )
        if denied_ancestry == "gold"
        else None
    )
    gold = _gold(
        ctx,
        source,
        target,
        alignment,
        source_tokens,
        target_tokens,
        lineage_source_ids=(gold_owner.side.source_id,) if gold_owner else None,
    )
    service = BenchmarkService(ctx)
    started: list[object] = []
    original_start = service.recorder.start

    def record_start(*args, **kwargs):
        started.append(args[0])
        return original_start(*args, **kwargs)

    monkeypatch.setattr(service.recorder, "start", record_start)
    with (
        patch.object(ctx.artifact_store, "read_bytes", wraps=ctx.artifact_store.read_bytes) as read,
        pytest.raises(PolicyDenied),
    ):
        service.evaluate(token_run.run.id, gold.id)
    assert read.call_count == 0
    assert started == []


@pytest.mark.parametrize("revoke_before_first", (False, True))
def test_evaluation_policy_denial_and_revocation(
    ctx: AppContext, tmp_path: Path, revoke_before_first: bool
) -> None:
    source = _side(ctx, tmp_path, "bench-pol-a", "qaa", "kanu mabi.")
    target = _side(ctx, tmp_path, "bench-pol-b", "por", "O homem vê.")
    segment = SegmentAlignmentService(ctx).align(
        source.side, target.side, config=AlignmentConfig(namespace="refs")
    )
    alignment = ctx.repo.list_segment_alignments_for_run(segment.run.id)[0]
    token_run = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
        segment.run.id,
        source_tokenization_run_id=source.tokenization_run_id,
        target_tokenization_run_id=target.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    source_tokens = [
        t
        for sid in alignment.source_segment_ids
        for t in ctx.repo.list_tokens(sid)
        if t.run_id == source.tokenization_run_id
    ]
    target_tokens = [
        t
        for sid in alignment.target_segment_ids
        for t in ctx.repo.list_tokens(sid)
        if t.run_id == target.tokenization_run_id
    ]
    gold = _gold(ctx, source, target, alignment, source_tokens, target_tokens)
    service = BenchmarkService(ctx)

    if revoke_before_first:
        with ctx.repo.transaction():
            ctx.repo.set_source_status(source.side.source_id, SourceStatus.REVOKED, at=ctx.clock())
        with pytest.raises(PolicyDenied):
            service.evaluate(token_run.run.id, gold.id)
        assert not ctx.repo.list_runs_with_input(token_run.run.id, RunStage.EVALUATION)
        return

    res = service.evaluate(token_run.run.id, gold.id)
    assert not res.reused

    with ctx.repo.transaction():
        ctx.repo.set_source_status(source.side.source_id, SourceStatus.REVOKED, at=ctx.clock())
    with pytest.raises(PolicyDenied):
        service.evaluate(token_run.run.id, gold.id)

    audits = [
        e
        for e in ctx.repo.list_audit_events()
        if e.subject_id == source.side.source_id and e.event_type.value == "policy_denied"
    ]
    assert len(audits) >= 1
