"""Stage 7b/8 integration tests: `MorphologyService` (M5 WP5.9, Gate 38).

Contracts under test:
- Preconditions: succeeded input runs; tokenization run descends from named IGT extract run;
  DISTILL_MORPHOLOGY allowed on every ancestor source; invalid lineage or policy denial raises.
- Assert IGT: morpheme identity per run; allomorphs; local features; segmented analyses on
  mapped tokens; morph-v1 scoring; status candidate or supported (never validated).
- Exclude refs: held-out records produce no morphemes, allomorphs, analyses, or evidence.
- Induce unsegmented baseline: whole-surface segment, insufficient_evidence abstention, candidate.
- Idempotent reuse: identical run inputs/config return reused run; changing exclude_refs creates
  a new run.
- Invariants: tokens and segments byte-identical before/after; competing analyses from two runs
  coexist on the same token.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    Abstention,
    AnalysisKind,
    ArtifactKind,
    AuditEventType,
    LifecycleStatus,
    RunStage,
    RunStatus,
    SourceStatus,
)
from langpipe.domain.errors import (
    AmbiguousInput,
    InvalidLineage,
    PolicyDenied,
)
from langpipe.igt.service import extract_igt
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.languages.base import MorphologyProfile
from langpipe.morphology.adapters.igt_assertion import IgtAssertionInducer
from langpipe.morphology.service import (
    REPORT_SCHEMA,
    REPORT_SCHEMA_VERSION,
    MorphologyInductionResult,
    MorphologyService,
    assert_igt,
    induce_morphology,
)
from langpipe.normalization.service import normalize_extraction
from langpipe.tokenization.service import tokenize_normalization
from tests.service.manifests import (
    manifest_data,
    write_manifest,
    write_origin_file,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "igt"
SAMPLE_TOOLBOX = FIXTURES / "toolbox_sample.txt"


def _setup_igt_pipeline(
    ctx: AppContext,
    tmp_path: Path,
    key: str = "morph-src",
    *,
    mode: str = "direct",
    access_class: str = "public",
) -> tuple[str, str, str]:
    """Helper to register, ingest, extract, normalize, and tokenize an IGT source."""
    relative = f"texts/{key}.dat"
    write_origin_file(tmp_path, relative, SAMPLE_TOOLBOX.read_bytes())
    data = manifest_data(
        key=key,
        mode=mode,
        access_class=access_class,
        objects=[{"path": relative, "media_type": "text/plain"}],
    )
    data["source_type"] = "igt"
    data["languages"] = ["qaa", "por"]
    reg = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))
    ingest_source(ctx, reg.source.id)

    igt_res = extract_igt(ctx, reg.source.id)
    norm_res = normalize_extraction(ctx, igt_res.run.id)
    tok_res = tokenize_normalization(ctx, norm_res.run.id)
    return reg.source.id, igt_res.run.id, tok_res.run.id


def test_assert_igt_happy_path(ctx: AppContext, tmp_path: Path) -> None:
    source_id, igt_run_id, tok_run_id = _setup_igt_pipeline(ctx, tmp_path, "tb-assert-happy")

    res = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
    )

    assert isinstance(res, MorphologyInductionResult)
    assert res.reused is False
    assert res.run.stage is RunStage.IGT_IMPORT
    assert res.run.status is RunStatus.SUCCEEDED
    assert res.totals["analyses"] > 0
    assert res.totals["segments"] > 0
    assert res.totals["morphemes"] > 0
    assert res.totals["allomorphs"] > 0
    assert res.totals["evidence_items"] > 0
    assert res.totals["lineage_edges"] > 0
    assert res.words_mapped > 0
    assert res.excluded_refs_count == 0

    # Report verification
    assert res.report is not None
    assert res.report.kind is ArtifactKind.OTHER
    assert res.report.schema_name == REPORT_SCHEMA
    assert res.report.schema_version == REPORT_SCHEMA_VERSION

    report_bytes = ctx.artifact_store.read_bytes(res.report.sha256)
    report_data = json.loads(report_bytes.decode("utf-8"))
    assert report_data["schema"] == REPORT_SCHEMA
    assert report_data["schema_version"] == REPORT_SCHEMA_VERSION
    assert report_data["run_id"] == res.run.id
    assert report_data["method"] == "igt_assertion@0.1.0"
    assert report_data["input_run_ids"] == sorted([tok_run_id, igt_run_id])
    assert report_data["words_mapped"] == res.words_mapped
    assert report_data["excluded_refs_count"] == 0

    # Invariant: VALIDATED is strictly unreachable by machine induction
    assert "validated" not in report_data["status_counts"]
    for status_str in report_data["status_counts"]:
        assert status_str != LifecycleStatus.VALIDATED.value

    analyses = ctx.repo.list_morph_analyses_for_run(res.run.id)
    assert len(analyses) == res.totals["analyses"]
    for analysis in analyses:
        assert analysis.status in (LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED)
        assert analysis.status is not LifecycleStatus.VALIDATED

    morphemes = ctx.repo.list_morphemes_for_run(res.run.id)
    assert len(morphemes) == res.totals["morphemes"]
    for m in morphemes:
        assert m.status in (LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED)
        assert m.status is not LifecycleStatus.VALIDATED


def test_assert_igt_exclude_refs(ctx: AppContext, tmp_path: Path) -> None:
    source_id, igt_run_id, tok_run_id = _setup_igt_pipeline(ctx, tmp_path, "tb-assert-exclude")

    res = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
        exclude_refs=["IGT-1"],
    )

    assert res.reused is False
    assert res.excluded_refs_count == 1

    report_bytes = ctx.artifact_store.read_bytes(res.report.sha256)
    report_data = json.loads(report_bytes.decode("utf-8"))
    assert report_data["excluded_refs_count"] == 1

    # Verify no analyses or evidence link to IGT-1 observations
    observations = ctx.repo.list_igt_observations_for_run(igt_run_id)
    igt1_obs = [obs for obs in observations if obs.record_ref == "IGT-1"]
    assert len(igt1_obs) == 1
    igt1_seg_id = igt1_obs[0].segment_id

    # The tokens belonging to igt1_seg_id must have NO analyses created by this run
    if igt1_seg_id:
        # Find normalized segment
        for edge in ctx.repo.list_lineage_edges(igt1_seg_id, direction="in"):
            for tok in ctx.repo.list_tokens(edge.from_id):
                analyses = [
                    a
                    for a in ctx.repo.list_morph_analyses_for_token(tok.id)
                    if a.run_id == res.run.id
                ]
                assert analyses == []


def test_assert_igt_invalid_lineage_raises(ctx: AppContext, tmp_path: Path) -> None:
    _, igt_run_1, _ = _setup_igt_pipeline(ctx, tmp_path, "tb-lineage-1")
    _, _, tok_run_2 = _setup_igt_pipeline(ctx, tmp_path, "tb-lineage-2")

    # tok_run_2 does NOT descend from igt_run_1
    with pytest.raises(InvalidLineage):
        assert_igt(
            ctx,
            tokenization_run_id=tok_run_2,
            igt_extract_run_id=igt_run_1,
        )


def test_assert_igt_governance_denial(ctx: AppContext, tmp_path: Path) -> None:
    source_id, igt_run_id, tok_run_id = _setup_igt_pipeline(ctx, tmp_path, "tb-gov-denial")

    # Revoke the source
    with ctx.repo.transaction():
        ctx.repo.set_source_status(source_id, SourceStatus.REVOKED, at=ctx.clock())

    with pytest.raises(PolicyDenied):
        assert_igt(
            ctx,
            tokenization_run_id=tok_run_id,
            igt_extract_run_id=igt_run_id,
        )

    # Verify POLICY_DENIED audit event written
    events = [
        e
        for e in ctx.repo.list_audit_events()
        if e.subject_id == source_id and e.event_type is AuditEventType.POLICY_DENIED
    ]
    assert len(events) >= 1


def test_assert_igt_idempotent_reuse(ctx: AppContext, tmp_path: Path) -> None:
    _, igt_run_id, tok_run_id = _setup_igt_pipeline(ctx, tmp_path, "tb-reuse")

    res1 = assert_igt(ctx, tokenization_run_id=tok_run_id, igt_extract_run_id=igt_run_id)
    assert res1.reused is False

    res2 = assert_igt(ctx, tokenization_run_id=tok_run_id, igt_extract_run_id=igt_run_id)
    assert res2.reused is True
    assert res2.run.id == res1.run.id
    assert res2.totals == res1.totals

    # Different exclude_refs creates a new run
    res3 = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
        exclude_refs=["IGT-2"],
    )
    assert res3.reused is False
    assert res3.run.id != res1.run.id


def test_induce_unsegmented_baseline(ctx: AppContext, tmp_path: Path) -> None:
    _, _, tok_run_id = _setup_igt_pipeline(ctx, tmp_path, "tb-induce-unsegmented")

    res = induce_morphology(ctx, tokenization_run_id=tok_run_id, method="unsegmented@0.1.0")

    assert res.reused is False
    assert res.run.stage is RunStage.MORPHOLOGY_INDUCTION
    assert res.run.status is RunStatus.SUCCEEDED
    assert res.totals["analyses"] > 0
    assert res.totals["segments"] == res.totals["analyses"]
    assert res.totals["morphemes"] == 0
    assert res.totals["allomorphs"] == 0
    assert res.analysis_kind_counts == {AnalysisKind.UNSEGMENTED.value: res.totals["analyses"]}
    assert res.abstention_counts == {Abstention.INSUFFICIENT_EVIDENCE.value: res.totals["analyses"]}
    assert res.status_counts == {LifecycleStatus.CANDIDATE.value: res.totals["analyses"]}

    analyses = ctx.repo.list_morph_analyses_for_run(res.run.id)
    for a in analyses:
        assert a.analysis_kind is AnalysisKind.UNSEGMENTED
        assert a.abstention is Abstention.INSUFFICIENT_EVIDENCE
        assert a.status is LifecycleStatus.CANDIDATE


def test_induce_idempotent_reuse(ctx: AppContext, tmp_path: Path) -> None:
    _, _, tok_run_id = _setup_igt_pipeline(ctx, tmp_path, "tb-induce-reuse")

    res1 = induce_morphology(ctx, tokenization_run_id=tok_run_id, method="unsegmented@0.1.0")
    assert res1.reused is False

    res2 = induce_morphology(ctx, tokenization_run_id=tok_run_id, method="unsegmented@0.1.0")
    assert res2.reused is True
    assert res2.run.id == res1.run.id
    assert res2.totals == res1.totals


def test_morphology_immutability_and_competing_analyses(ctx: AppContext, tmp_path: Path) -> None:
    source_id, igt_run_id, tok_run_id = _setup_igt_pipeline(ctx, tmp_path, "tb-competing")

    # Snapshot tokens and segments before morphology
    observations = ctx.repo.list_igt_observations_for_run(igt_run_id)
    seg_ids = [obs.segment_id for obs in observations if obs.segment_id]
    tok_objs = []
    for s_id in seg_ids:
        for edge in ctx.repo.list_lineage_edges(s_id, direction="in"):
            tok_objs.extend(ctx.repo.list_tokens(edge.from_id))
    tokens_before = [
        (t.id, t.segment_id, t.raw_surface, t.normalized_surface, t.raw_span, t.normalized_span)
        for t in tok_objs
    ]

    # Run assert_igt
    res_assert = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
    )

    # Run induce unsegmented
    induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="unsegmented@0.1.0",
    )

    # Snapshot tokens and segments after morphology
    tok_objs_after = []
    observations = ctx.repo.list_igt_observations_for_run(igt_run_id)
    seg_ids = [obs.segment_id for obs in observations if obs.segment_id]
    for s_id in seg_ids:
        for edge in ctx.repo.list_lineage_edges(s_id, direction="in"):
            tok_objs_after.extend(ctx.repo.list_tokens(edge.from_id))
    tokens_after = [
        (t.id, t.segment_id, t.raw_surface, t.normalized_surface, t.raw_span, t.normalized_span)
        for t in tok_objs_after
    ]

    # Invariant 1: tokens and segments are byte-identical
    assert tokens_before == tokens_after

    # Competing analyses: tokens have analyses from BOTH runs
    assert_analyses = ctx.repo.list_morph_analyses_for_run(res_assert.run.id)
    assert len(assert_analyses) > 0

    sample_token_id = assert_analyses[0].target_token_id
    analyses_for_token = ctx.repo.list_morph_analyses_for_token(sample_token_id)
    methods = {a.method for a in analyses_for_token}
    assert "igt_assertion@0.1.0" in methods
    assert "unsegmented@0.1.0" in methods
    assert len(analyses_for_token) >= 2


def test_assert_igt_policy_denial_under_lock(ctx: AppContext, tmp_path: Path) -> None:
    source_id, igt_run_id, tok_run_id = _setup_igt_pipeline(ctx, tmp_path, "tb-lock-deny")

    # Revoke source after predecessor runs succeeded
    with ctx.repo.transaction():
        ctx.repo.set_source_status(source_id, SourceStatus.REVOKED, at=ctx.clock())

    with pytest.raises(PolicyDenied) as exc_info:
        assert_igt(
            ctx,
            tokenization_run_id=tok_run_id,
            igt_extract_run_id=igt_run_id,
        )
    assert exc_info.value.source_id == source_id

    # Verify audit event was successfully recorded outside the rolled-back transaction
    audit_events = [e for e in ctx.repo.list_audit_events() if e.subject_id == source_id]
    denials = [e for e in audit_events if e.event_type is AuditEventType.POLICY_DENIED]
    assert len(denials) >= 1
    assert denials[-1].details.get("operation") == "distill_morphology"


def test_parameter_sensitive_reuse(ctx: AppContext, tmp_path: Path) -> None:
    source_id, igt_run_id, tok_run_id = _setup_igt_pipeline(ctx, tmp_path, "tb-param-reuse")

    res1 = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
        language="qaa",
    )
    assert res1.reused is False

    # Same parameters reuse
    res1_cached = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
        language="qaa",
    )
    assert res1_cached.reused is True
    assert res1_cached.run.id == res1.run.id

    # Changed contact_language creates a new run
    res2 = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
        language="qaa",
        contact_language="eng",
    )
    assert res2.reused is False
    assert res2.run.id != res1.run.id

    # Changed custom morphology profile creates a distinct run
    p1 = MorphologyProfile(boundary_marks=("-", "="))
    p2 = MorphologyProfile(boundary_marks=("-", "~"))
    res_p1 = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
        language="qaa",
        profile=p1,
    )
    res_p2 = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
        language="qaa",
        profile=p2,
    )
    assert res_p1.run.id != res_p2.run.id
    assert res_p1.run.config["profile"] != res_p2.run.config["profile"]


def test_preconditions_ambiguous_language_does_not_leak_running_run(
    ctx: AppContext, tmp_path: Path
) -> None:
    # Source with no text tier (only translation) -> 0 tokens; source has 2 languages
    content = b"\\ref 001\n\\ft Portuguese only\n"
    relative = "texts/ambig-src.dat"
    write_origin_file(tmp_path, relative, content)
    data = manifest_data(
        key="ambig-src",
        mode="direct",
        access_class="public",
        objects=[{"path": relative, "media_type": "text/plain"}],
    )
    data["source_type"] = "igt"
    data["languages"] = ["qaa", "por"]
    reg = register_source(ctx, write_manifest(tmp_path, data, name="ambig-src.yaml"))
    ingest_source(ctx, reg.source.id)

    igt_res = extract_igt(ctx, reg.source.id)
    norm_res = normalize_extraction(ctx, igt_res.run.id)
    tok_res = tokenize_normalization(ctx, norm_res.run.id)

    # Call induce_morphology without explicit language -> raises AmbiguousInput before run.start
    runs_before = ctx.repo.list_runs_with_input(tok_res.run.id, RunStage.MORPHOLOGY_INDUCTION)
    with pytest.raises(AmbiguousInput) as exc_info:
        induce_morphology(
            ctx,
            tokenization_run_id=tok_res.run.id,
            method="unsegmented@0.1.0",
            language=None,
        )
    assert exc_info.value.stage is RunStage.MORPHOLOGY_INDUCTION
    assert exc_info.value.count == 2

    runs_after = ctx.repo.list_runs_with_input(tok_res.run.id, RunStage.MORPHOLOGY_INDUCTION)
    # Proves no dangling RUNNING run was created
    assert len(runs_after) == len(runs_before)


def test_unrelated_tokenization_run_fails_ancestor_check(ctx: AppContext, tmp_path: Path) -> None:
    _, igt_run1, tok_run1 = _setup_igt_pipeline(ctx, tmp_path, "tb-anc-1")
    _, igt_run2, tok_run2 = _setup_igt_pipeline(ctx, tmp_path, "tb-anc-2")

    # Mismatched pair: tok_run2 does NOT descend from igt_run1
    with pytest.raises(InvalidLineage):
        assert_igt(
            ctx,
            tokenization_run_id=tok_run2,
            igt_extract_run_id=igt_run1,
        )


def test_assert_igt_policy_denial_concurrent_under_lock(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id, igt_run_id, tok_run_id = _setup_igt_pipeline(
        ctx, tmp_path, "tb-lock-deny-concurrent"
    )

    real_induce = IgtAssertionInducer.induce

    def _induce_and_revoke(self: IgtAssertionInducer, inp: Any) -> Any:
        res = real_induce(self, inp)
        # Concurrent revocation happens after initial precheck, right before locked transaction
        with ctx.repo.transaction():
            ctx.repo.set_source_status(source_id, SourceStatus.REVOKED, at=ctx.clock())
        return res

    monkeypatch.setattr(IgtAssertionInducer, "induce", _induce_and_revoke)

    failed_before = ctx.repo.count_runs(RunStatus.FAILED)
    with pytest.raises(PolicyDenied) as exc_info:
        assert_igt(
            ctx,
            tokenization_run_id=tok_run_id,
            igt_extract_run_id=igt_run_id,
        )
    assert exc_info.value.source_id == source_id

    # Verify denial audit event recorded outside the rolled-back transaction
    audit_events = [e for e in ctx.repo.list_audit_events() if e.subject_id == source_id]
    denials = [e for e in audit_events if e.event_type is AuditEventType.POLICY_DENIED]
    assert len(denials) >= 1
    assert denials[-1].details.get("operation") == "distill_morphology"

    # Verify the run was marked FAILED, not left in RUNNING
    assert ctx.repo.count_runs(RunStatus.FAILED) == failed_before + 1


def test_assert_igt_empty_lineage_end_to_end(ctx: AppContext, tmp_path: Path) -> None:
    content = b"\\ref 001\n\\ft Portuguese only\n"
    relative = "texts/empty-anc.dat"
    write_origin_file(tmp_path, relative, content)
    data = manifest_data(
        key="empty-anc",
        mode="direct",
        access_class="public",
        objects=[{"path": relative, "media_type": "text/plain"}],
    )
    data["source_type"] = "igt"
    data["languages"] = ["por"]
    reg = register_source(ctx, write_manifest(tmp_path, data, name="empty-anc.yaml"))
    ingest_source(ctx, reg.source.id)

    igt_res = extract_igt(ctx, reg.source.id)
    assert igt_res.segments == 0
    norm_res = normalize_extraction(ctx, igt_res.run.id)
    tok_res = tokenize_normalization(ctx, norm_res.run.id)

    # assert_igt must traverse empty lineage without error and succeed
    res = assert_igt(
        ctx,
        tokenization_run_id=tok_res.run.id,
        igt_extract_run_id=igt_res.run.id,
        language="por",
    )
    assert res.run.status is RunStatus.SUCCEEDED
    assert res.totals["analyses"] == 0


def test_morphology_late_failure_marks_run_failed(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, igt_run_id, tok_run_id = _setup_igt_pipeline(ctx, tmp_path, "tb-late-fail")

    def _failing_report(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected late failure during morphology report")

    monkeypatch.setattr(MorphologyService, "_create_report", _failing_report)

    failed_before = ctx.repo.count_runs(RunStatus.FAILED)
    with pytest.raises(RuntimeError, match="injected late failure"):
        assert_igt(
            ctx,
            tokenization_run_id=tok_run_id,
            igt_extract_run_id=igt_run_id,
        )

    assert ctx.repo.count_runs(RunStatus.FAILED) == failed_before + 1


def test_morphology_result_construction_failure_marks_run_failed(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, igt_run_id, tok_run_id = _setup_igt_pipeline(ctx, tmp_path, "tb-late-fail-result")

    def _failing_result(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected failure during _result_from_output")

    monkeypatch.setattr(MorphologyService, "_result_from_output", _failing_result)

    failed_before = ctx.repo.count_runs(RunStatus.FAILED)
    with pytest.raises(RuntimeError, match="injected failure during _result_from_output"):
        assert_igt(
            ctx,
            tokenization_run_id=tok_run_id,
            igt_extract_run_id=igt_run_id,
        )

    # Because result construction is inside transaction, failure rolls back and marks run FAILED
    assert ctx.repo.count_runs(RunStatus.FAILED) == failed_before + 1
