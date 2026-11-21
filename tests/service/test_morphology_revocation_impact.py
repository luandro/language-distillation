"""Revocation and approval-withdrawal impact over morphology and IGT lineage (WP5.15, Gate 44).

Contracts under test:
- Revoking an IGT source reaches:
  * observations (IGTObservation)
  * segments and tokens
  * IGT-asserted morphemes, allomorphs, and morph_analyses
  * projection analyses built on that inventory
  * review tasks and review decisions
- Revocation leaves stored rows byte-identical (Invariant 1).
- lineage_eligibility returns DENY for all reachable entities.
- Withdrawing a `distill_morphology` approval makes the downstream set computed-ineligible
  for `distill_morphology` (and nothing else); re-granting restores it.
- Features are vocabulary without source lineage (ADR-0017 §6) and are never in an impact set;
  their segment assignments carry the governed link.
- Acceptance: LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest
  tests/service/test_morphology_revocation_impact.py
  tests/service/test_lexical_revocation_impact.py -q
"""

from dataclasses import dataclass
from pathlib import Path

from typer.testing import CliRunner

from langpipe.app_context import AppContext
from langpipe.cli.app import app
from langpipe.domain.enums import (
    ApprovalAction,
    LifecycleStatus,
    Operation,
    PolicyDecision,
    ReviewDecisionKind,
    ReviewTaskType,
    SourceStatus,
)
from langpipe.extraction.service import extract_source
from langpipe.governance.approvals import record_approval
from langpipe.governance.lineage_policy import lineage_eligibility
from langpipe.igt.service import extract_igt
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.lineage.knowledge_impact import RevocationImpact, revocation_impact
from langpipe.morphology.service import assert_igt, induce_morphology
from langpipe.normalization.service import normalize_extraction
from langpipe.review.authority import ReviewAuthorityRegistry
from langpipe.review.service import ReviewService
from langpipe.storage.repository import Repository
from langpipe.tokenization.service import tokenize_normalization
from tests.service.manifests import (
    manifest_data,
    state_counts,
    write_manifest,
    write_origin_file,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE_TOOLBOX = REPO_ROOT / "tests" / "fixtures" / "igt" / "toolbox_sample.txt"

LANGUAGE = "qaa"
REVIEWER = "linguist_1"
ROLE = "community_linguist"
STEWARD = "steward_1"
STEWARD_ROLE = "governance_steward"


@dataclass(frozen=True)
class _MorphWorld:
    igt_source_id: str
    bystander_source_id: str
    igt_extract_run_id: str
    igt_assert_run_id: str
    bystander_norm_run_id: str
    proj_run_id: str
    morpheme_id: str
    asserted_analysis_id: str
    projected_analysis_id: str
    review_task_ids: tuple[str, ...]
    review_decision_ids: tuple[str, ...]
    feature_ids: tuple[str, ...]


def _build_morph_world(ctx: AppContext, tmp_path: Path) -> _MorphWorld:
    """Builds an IGT source, downstream asserted morphology, projection, and reviews."""
    # 1. Register and ingest IGT source (distill_only, baseline for distill_morphology is review)
    igt_relative = "texts/toolbox_sample.txt"
    write_origin_file(tmp_path, igt_relative, SAMPLE_TOOLBOX.read_bytes())
    igt_data = manifest_data(
        key="igt-sample-src",
        mode="review_required",
        access_class="public",
        allow=["extract", "read_raw", "normalize"],
        objects=[{"path": igt_relative, "media_type": "text/plain"}],
    )
    igt_data["source_type"] = "igt"
    igt_data["languages"] = [LANGUAGE, "por"]
    igt_reg = register_source(ctx, write_manifest(tmp_path, igt_data, name="igt-sample.yaml"))
    ingest_source(ctx, igt_reg.source.id)

    # Grant distill_morphology approval for igt_reg.source.id
    auth = ReviewAuthorityRegistry()
    auth.register(STEWARD, STEWARD_ROLE, [LANGUAGE])
    auth.register(REVIEWER, ROLE, [LANGUAGE])
    record_approval(
        ctx.repo,
        igt_reg.source.id,
        Operation.DISTILL_MORPHOLOGY,
        ApprovalAction.GRANT,
        STEWARD,
        "authorized for morphological study",
        authority_registry=auth,
        approver_role=STEWARD_ROLE,
        clock=ctx.clock,
        new_id=ctx.new_id,
        code_revision=ctx.code_revision,
    )

    # 2. Extract IGT, normalize, tokenize, assert
    igt_res = extract_igt(ctx, igt_reg.source.id)
    norm_res = normalize_extraction(ctx, igt_res.run.id)
    tok_res = tokenize_normalization(ctx, norm_res.run.id)
    assert_res = assert_igt(
        ctx, tokenization_run_id=tok_res.run.id, igt_extract_run_id=igt_res.run.id
    )

    morphemes = ctx.repo.list_morphemes_for_run(assert_res.run.id)
    analyses = ctx.repo.list_morph_analyses_for_run(assert_res.run.id)
    assert len(morphemes) > 0
    assert len(analyses) > 0

    # Pick a morpheme with dependent analyses
    morpheme = next(m for m in morphemes if len(ctx.repo.list_analyses_linking_morpheme(m.id)) > 0)
    analysis = ctx.repo.list_analyses_linking_morpheme(morpheme.id)[0]

    # 3. Register and ingest bystander text source for projection
    bystander_relative = "texts/bystander.txt"
    write_origin_file(tmp_path, bystander_relative, b"mabi-ki kana rumi.\n")
    bystander_data = manifest_data(
        key="bystander-text-src",
        mode="direct",
        access_class="public",
        objects=[{"path": bystander_relative, "media_type": "text/plain"}],
    )
    bystander_data["languages"] = [LANGUAGE]
    bystander_reg = register_source(
        ctx, write_manifest(tmp_path, bystander_data, name="bystander-text.yaml")
    )
    ingest_source(ctx, bystander_reg.source.id)

    bystander_ext = extract_source(ctx, bystander_reg.source.id)
    bystander_norm = normalize_extraction(ctx, bystander_ext.run.id)
    bystander_tok = tokenize_normalization(ctx, bystander_norm.run.id)

    # 4. Induce morphology via igt_projection using IGT inventory
    proj_res = induce_morphology(
        ctx,
        tokenization_run_id=bystander_tok.run.id,
        method="igt_projection@0.1.0",
        inventory_run_id=assert_res.run.id,
        language=LANGUAGE,
    )
    proj_analyses = ctx.repo.list_morph_analyses_for_run(proj_res.run.id)
    assert len(proj_analyses) > 0

    # 5. Review and validate morpheme and analysis ACCEPT
    review = ReviewService(
        ctx.repo,
        auth,
        clock=ctx.clock,
        new_id=ctx.new_id,
        code_revision=ctx.code_revision,
    )
    task_morph = review.create_task(
        morpheme.id, task_type=ReviewTaskType.MORPHEME_FUNCTION, required_role=ROLE
    )
    decision_morph = review.record_decision(
        task_morph.id, ReviewDecisionKind.ACCEPT, REVIEWER, ROLE
    )
    assert decision_morph.target_status is LifecycleStatus.VALIDATED

    task_ana = review.create_task(
        analysis.id, task_type=ReviewTaskType.MORPHOLOGY_SEGMENTATION, required_role=ROLE
    )
    decision_ana = review.record_decision(task_ana.id, ReviewDecisionKind.ACCEPT, REVIEWER, ROLE)
    assert decision_ana.target_status is LifecycleStatus.VALIDATED

    # Get feature vocabulary created in the repository
    features = ctx.repo.list_features()
    feature_ids = tuple(f.id for f in features)

    return _MorphWorld(
        igt_source_id=igt_reg.source.id,
        bystander_source_id=bystander_reg.source.id,
        igt_extract_run_id=igt_res.run.id,
        igt_assert_run_id=assert_res.run.id,
        bystander_norm_run_id=bystander_norm.run.id,
        proj_run_id=proj_res.run.id,
        morpheme_id=morpheme.id,
        asserted_analysis_id=analysis.id,
        projected_analysis_id=proj_analyses[0].id,
        review_task_ids=(task_morph.id, task_ana.id),
        review_decision_ids=(decision_morph.decision.id, decision_ana.decision.id),
        feature_ids=feature_ids,
    )


def _snapshot_world(repo: Repository, impact: RevocationImpact) -> dict[str, object]:
    """Snapshots every single entity and assignment row in the downstream impact set."""
    return {
        "morphemes": [repo.get_morpheme(m_id) for m_id in impact.morphemes],
        "allomorphs": [
            allo for m_id in impact.morphemes for allo in repo.list_allomorphs_for_morpheme(m_id)
        ],
        "analyses": [repo.get_morph_analysis(a_id) for a_id in impact.morph_analyses],
        "observations": [repo.get_igt_observation(o_id) for o_id in impact.igt_observations],
        "segments": [repo.get_segment(s_id) for s_id in impact.segments],
        "tokens": [repo.get_token(t_id) for t_id in impact.tokens],
        "tasks": [repo.get_review_task(t_id) for t_id in impact.review_tasks],
        "decisions": [repo.get_review_decision(d_id) for d_id in impact.review_decisions],
        "morph_segs": [
            seg for a_id in impact.morph_analyses for seg in repo.list_morph_segments(a_id)
        ],
        "segment_features": [
            feat
            for a_id in impact.morph_analyses
            for seg in repo.list_morph_segments(a_id)
            for feat in repo.list_segment_features(seg.id)
        ],
    }


def test_revocation_impact_reaches_all_morphology_entities(ctx: AppContext, tmp_path: Path) -> None:
    """Revoking an IGT source reaches observations, morphemes, allomorphs,
    analyses, segments, projection, reviews; stores remain byte-identical;
    lineage_eligibility flips to DENY for all reachable entities.
    """
    world = _build_morph_world(ctx, tmp_path)
    repo = ctx.repo

    impact = revocation_impact(repo, world.igt_source_id)

    # 1. Check that all morphology buckets are populated
    assert len(impact.igt_observations) > 0
    assert len(impact.tokens) > 0
    assert len(impact.segments) > 0
    assert len(impact.morphemes) > 0
    assert len(impact.allomorphs) > 0
    assert len(impact.morph_analyses) > 0
    assert len(impact.morph_segments) > 0
    assert len(impact.review_tasks) > 0
    assert len(impact.review_decisions) > 0

    # Every MorphSegment belonging to every impacted MorphAnalysis is in impact.morph_segments
    for a_id in impact.morph_analyses:
        segs = repo.list_morph_segments(a_id)
        assert len(segs) > 0
        for seg in segs:
            assert seg.id in impact.morph_segments

    # Projection analyses built on the IGT inventory must be reached
    assert world.projected_analysis_id in impact.morph_analyses
    # Asserted morpheme and analysis must be reached
    assert world.morpheme_id in impact.morphemes
    assert world.asserted_analysis_id in impact.morph_analyses
    # Review records must be reached
    for tid in world.review_task_ids:
        assert tid in impact.review_tasks
    for did in world.review_decision_ids:
        assert did in impact.review_decisions

    # Both validated morpheme and validated analysis are in validated_affected
    assert world.morpheme_id in impact.validated_affected
    assert world.asserted_analysis_id in impact.validated_affected

    # Features are vocabulary without source lineage (ADR-0017 §6) and MUST NOT be in impact
    assert len(world.feature_ids) > 0
    for fid in world.feature_ids:
        assert fid not in {entry.object_id for entry in impact.entries}

    # Feature assignments are exposed in impact (segment_features and feature_assignments)
    assert len(impact.feature_assignments) > 0
    assert len(impact.segment_features) > 0
    for seg_id, fid in impact.segment_features:
        assert seg_id in impact.morph_segments
        assert fid in world.feature_ids
        assert fid not in {entry.object_id for entry in impact.entries}

    # Before revocation: verify explicit ALLOW for every reachable entry (including morph segments)
    for entry in impact.entries:
        assert (
            lineage_eligibility(repo, entry.object_id, Operation.DISTILL_MORPHOLOGY)
            is PolicyDecision.ALLOW
        ), f"expected pre-revocation ALLOW for {entry.entity_type.value} {entry.object_id}"

    # Snapshot rows across ALL downstream tables before revocation
    state_before = state_counts(ctx)
    snap_before = _snapshot_world(repo, impact)

    # Revoke the IGT source
    with repo.transaction():
        repo.set_source_status(world.igt_source_id, SourceStatus.REVOKED, ctx.clock())

    # Invariant 1 / ADR-0015: stored rows and table counts are byte-identical
    assert state_counts(ctx) == state_before
    snap_after = _snapshot_world(repo, impact)
    assert snap_after == snap_before

    # Operational eligibility is now DENY for every reachable entity in the impact set
    for entry in impact.entries:
        assert (
            lineage_eligibility(repo, entry.object_id, Operation.DISTILL_MORPHOLOGY)
            is PolicyDecision.DENY
        ), f"expected post-revocation DENY for {entry.entity_type.value} {entry.object_id}"


def test_approval_withdrawal_and_regrant(ctx: AppContext, tmp_path: Path) -> None:
    """Withdrawing distill_morphology approval makes downstream computed-ineligible
    for distill_morphology while leaving other operations untouched; regranting restores it.
    """
    world = _build_morph_world(ctx, tmp_path)
    repo = ctx.repo

    auth = ReviewAuthorityRegistry()
    auth.register(STEWARD, STEWARD_ROLE, [LANGUAGE])

    impact = revocation_impact(repo, world.igt_source_id)
    # Initial state: distill_morphology is ALLOW; capture all operation decisions
    # across the entire downstream set (including morph segments)
    pre_eligibility = {
        entry.object_id: {op: lineage_eligibility(repo, entry.object_id, op) for op in Operation}
        for entry in impact.entries
    }
    for entry in impact.entries:
        assert (
            pre_eligibility[entry.object_id][Operation.DISTILL_MORPHOLOGY] is PolicyDecision.ALLOW
        )

    # Snapshot full downstream state before withdrawal
    snap_before = _snapshot_world(repo, impact)

    # Withdraw distill_morphology approval
    record_approval(
        repo,
        world.igt_source_id,
        Operation.DISTILL_MORPHOLOGY,
        ApprovalAction.WITHDRAW,
        STEWARD,
        "temporary freeze on morphology distillation",
        authority_registry=auth,
        approver_role=STEWARD_ROLE,
        clock=ctx.clock,
        new_id=ctx.new_id,
        code_revision=ctx.code_revision,
    )

    # Computed eligibility for distill_morphology is now DENY or REVIEW_REQUIRED (not ALLOW)
    # across the entire downstream set, while EVERY OTHER operation in the enum remains 100%
    # untouched ("and nothing else")
    for entry in impact.entries:
        assert (
            lineage_eligibility(repo, entry.object_id, Operation.DISTILL_MORPHOLOGY)
            is not PolicyDecision.ALLOW
        )
        for op in Operation:
            if op is not Operation.DISTILL_MORPHOLOGY:
                assert (
                    lineage_eligibility(repo, entry.object_id, op)
                    is pre_eligibility[entry.object_id][op]
                ), f"operation {op.value} changed unexpectedly on {entry.object_id}"

    # Stored rows remain 100% identical across withdrawal
    assert _snapshot_world(repo, impact) == snap_before

    # Re-grant distill_morphology approval
    record_approval(
        repo,
        world.igt_source_id,
        Operation.DISTILL_MORPHOLOGY,
        ApprovalAction.GRANT,
        STEWARD,
        "restored morphological study approval",
        authority_registry=auth,
        approver_role=STEWARD_ROLE,
        clock=ctx.clock,
        new_id=ctx.new_id,
        code_revision=ctx.code_revision,
    )

    # Computed eligibility is restored to ALLOW across the full downstream set,
    # and all other operations continue to match their baseline exactly
    for entry in impact.entries:
        for op in Operation:
            assert (
                lineage_eligibility(repo, entry.object_id, op)
                is pre_eligibility[entry.object_id][op]
            )

    # Stored rows remain 100% identical after regrant
    assert _snapshot_world(repo, impact) == snap_before


def test_bystander_isolation(ctx: AppContext, tmp_path: Path) -> None:
    """Entities belonging strictly to the bystander text source are not in the IGT source impact,
    their operational eligibility is untouched by revocation, and feature vocabulary
    with governed segment assignments is isolated.
    """
    world = _build_morph_world(ctx, tmp_path)
    repo = ctx.repo

    impact = revocation_impact(repo, world.igt_source_id)
    entry_ids = {entry.object_id for entry in impact.entries}

    # 1. Bystander source and objects are isolated
    assert world.bystander_source_id not in entry_ids
    bystander_objects = repo.list_source_objects(world.bystander_source_id)
    assert len(bystander_objects) > 0
    for obj in bystander_objects:
        assert obj.id not in entry_ids

    # 2. Bystander segments and tokens before revocation
    bystander_segments = repo.list_segments_for_run(world.bystander_norm_run_id)
    assert len(bystander_segments) > 0
    bystander_tokens = []
    for seg in bystander_segments:
        assert seg.id not in entry_ids
        toks = repo.list_tokens(seg.id)
        assert len(toks) > 0
        for tok in toks:
            assert tok.id not in entry_ids
        bystander_tokens.extend(toks)

    bystander_eligibility_before = {
        tok.id: lineage_eligibility(repo, tok.id, Operation.NORMALIZE) for tok in bystander_tokens
    }
    assert all(dec is PolicyDecision.ALLOW for dec in bystander_eligibility_before.values())

    # Revoke the IGT source
    with repo.transaction():
        repo.set_source_status(world.igt_source_id, SourceStatus.REVOKED, ctx.clock())

    # Bystander token eligibility after revocation is completely untouched
    bystander_eligibility_after = {
        tok.id: lineage_eligibility(repo, tok.id, Operation.NORMALIZE) for tok in bystander_tokens
    }
    assert bystander_eligibility_after == bystander_eligibility_before

    # 3. Features exist, are not in impact, and are linked via MorphSegmentFeature
    assert len(world.feature_ids) > 0
    for fid in world.feature_ids:
        assert fid not in entry_ids

    asserted_segs = repo.list_morph_segments(world.asserted_analysis_id)
    assert len(asserted_segs) > 0
    assigned_features = []
    for seg in asserted_segs:
        assert seg.id in impact.morph_segments
        assert (
            lineage_eligibility(repo, seg.id, Operation.DISTILL_MORPHOLOGY) is PolicyDecision.DENY
        )
        assigned_features.extend(repo.list_segment_features(seg.id))

    assert len(assigned_features) > 0
    for sf in assigned_features:
        assert sf.feature_id in world.feature_ids
        assert sf.feature_id not in entry_ids


def test_cli_lineage_impact_command(ctx: AppContext, tmp_path: Path) -> None:
    """CLI lineage impact and revocation-impact print key-value summary without raw text."""
    world = _build_morph_world(ctx, tmp_path)

    runner = CliRunner()
    from langpipe.cli.context import reset_context_factory, set_context_factory

    set_context_factory(lambda: ctx)
    try:
        res1 = runner.invoke(app, ["lineage", "impact", world.igt_source_id])
        assert res1.exit_code == 0, res1.output
        assert f"source_id={world.igt_source_id}" in res1.stdout
        assert "revoked=false" in res1.stdout
        assert "total=" in res1.stdout
        assert "morpheme=" in res1.stdout
        assert "morph_analysis=" in res1.stdout
        assert "morph_segment=" in res1.stdout

        res2 = runner.invoke(app, ["lineage", "revocation-impact", world.igt_source_id])
        assert res2.exit_code == 0, res2.output
        assert res1.stdout == res2.stdout
    finally:
        reset_context_factory()
