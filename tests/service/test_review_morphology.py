"""Service integration tests for human review over morphology targets (WP5.13, Gate 42).

Contracts under test (M5-PLAN §7.11):
- Task type ↔ target type pairing:
    morphology_segmentation ↔ morph_analysis
    morpheme_function ↔ morpheme
- Analysis accept: validated; refused if linking rejected/deprecated morpheme.
- Competing analyses: accepting or rejecting one analysis leaves competitors untouched.
- Morpheme decisions: accept/reject/modify flag every analysis linking the morpheme stale_dependent.
  Analysis decisions flag nothing.
- Modify:
    analysis successor must target the same token and differ in signature;
    morpheme successor must share language (role may differ).
- Priority computation for morphology tasks.
- Authority and governance enforcement for morphology tasks.
"""

from pathlib import Path

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    LifecycleStatus,
    LineageKind,
    ReviewDecisionKind,
    ReviewTaskType,
    SourceStatus,
)
from langpipe.domain.errors import (
    InvalidTransition,
    PolicyDenied,
)
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.morphology import Morpheme
from langpipe.igt.service import extract_igt
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.morphology.service import assert_igt, induce_morphology
from langpipe.normalization.service import normalize_extraction
from langpipe.review.authority import ReviewAuthorityRegistry
from langpipe.review.base import UnauthorizedReviewer
from langpipe.review.service import ReviewService
from langpipe.storage.db.repository import PostgresRepository
from langpipe.tokenization.service import tokenize_normalization
from tests.service.manifests import (
    manifest_data,
    write_manifest,
    write_origin_file,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "igt"
SAMPLE_TOOLBOX = FIXTURES / "toolbox_sample.txt"
LANGUAGE = "qaa"


@pytest.fixture
def authority() -> ReviewAuthorityRegistry:
    registry = ReviewAuthorityRegistry()
    registry.register("morph_linguist", "community_linguist", [LANGUAGE])
    registry.register("por_linguist", "community_linguist", ["por"])
    registry.register("elder", "native_speaker_elder", [LANGUAGE])
    return registry


@pytest.fixture
def service(ctx: AppContext, authority: ReviewAuthorityRegistry) -> ReviewService:
    return ReviewService(
        ctx.repo,
        authority,
        clock=ctx.clock,
        new_id=ctx.new_id,
        code_revision=ctx.code_revision,
    )


def _setup_igt_pipeline(
    ctx: AppContext,
    tmp_path: Path,
    key: str = "review-morph-src",
) -> tuple[str, str, str]:
    relative = f"texts/{key}.dat"
    write_origin_file(tmp_path, relative, SAMPLE_TOOLBOX.read_bytes())
    data = manifest_data(
        key=key,
        mode="direct",
        access_class="public",
        objects=[{"path": relative, "media_type": "text/plain"}],
    )
    data["source_type"] = "igt"
    data["languages"] = [LANGUAGE, "por"]
    reg = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))
    ingest_source(ctx, reg.source.id)

    igt_res = extract_igt(ctx, reg.source.id)
    norm_res = normalize_extraction(ctx, igt_res.run.id)
    tok_res = tokenize_normalization(ctx, norm_res.run.id)
    return reg.source.id, igt_res.run.id, tok_res.run.id


def test_review_morphology_task_creation_pairing_enforcement(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    source_id, igt_run, tok_run = _setup_igt_pipeline(ctx, tmp_path, "pair-src")
    res = assert_igt(ctx, tokenization_run_id=tok_run, igt_extract_run_id=igt_run)

    morphemes = ctx.repo.list_morphemes_for_run(res.run.id)
    analyses = ctx.repo.list_morph_analyses_for_run(res.run.id)
    assert len(morphemes) > 0
    assert len(analyses) > 0

    morpheme = morphemes[0]
    analysis = analyses[0]

    # 1. Legal pairings succeed
    t_morph = service.create_task(
        target_id=morpheme.id,
        task_type=ReviewTaskType.MORPHEME_FUNCTION,
        required_role="community_linguist",
    )
    assert t_morph.target_id == morpheme.id
    assert t_morph.task_type is ReviewTaskType.MORPHEME_FUNCTION

    t_ana = service.create_task(
        target_id=analysis.id,
        task_type=ReviewTaskType.MORPHOLOGY_SEGMENTATION,
        required_role="community_linguist",
    )
    assert t_ana.target_id == analysis.id
    assert t_ana.task_type is ReviewTaskType.MORPHOLOGY_SEGMENTATION

    # 2. Illegal task type on morpheme raises ValueError
    with pytest.raises(ValueError, match="not allowed for morpheme"):
        service.create_task(
            target_id=morpheme.id,
            task_type=ReviewTaskType.MORPHOLOGY_SEGMENTATION,
            required_role="community_linguist",
        )

    with pytest.raises(ValueError, match="not allowed for morpheme"):
        service.create_task(
            target_id=morpheme.id,
            task_type=ReviewTaskType.LEMMA,
            required_role="community_linguist",
        )

    # 3. Illegal task type on morph_analysis raises ValueError
    with pytest.raises(ValueError, match="not allowed for morph_analysis"):
        service.create_task(
            target_id=analysis.id,
            task_type=ReviewTaskType.MORPHEME_FUNCTION,
            required_role="community_linguist",
        )

    with pytest.raises(ValueError, match="not allowed for morph_analysis"):
        service.create_task(
            target_id=analysis.id,
            task_type=ReviewTaskType.LEXICAL_SENSE,
            required_role="community_linguist",
        )


def test_review_morphology_analysis_accept_and_competitors_untouched(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    source_id, igt_run, tok_run = _setup_igt_pipeline(ctx, tmp_path, "comp-src")
    res_assert = assert_igt(ctx, tokenization_run_id=tok_run, igt_extract_run_id=igt_run)
    induce_morphology(
        ctx, tokenization_run_id=tok_run, method="unsegmented@0.1.0", language=LANGUAGE
    )

    analyses = ctx.repo.list_morph_analyses_for_run(res_assert.run.id)
    target_analysis = analyses[0]
    token_id = target_analysis.target_token_id

    # The token now has competing analyses from assert_igt and unsegmented
    token_analyses = ctx.repo.list_morph_analyses_for_token(token_id)
    competitors = [a for a in token_analyses if a.id != target_analysis.id]
    assert len(competitors) >= 1
    competitor = competitors[0]
    assert competitor.status is LifecycleStatus.CANDIDATE

    task = service.create_task(
        target_id=target_analysis.id,
        task_type=ReviewTaskType.MORPHOLOGY_SEGMENTATION,
        required_role="community_linguist",
    )

    decision_res = service.record_decision(
        task_id=task.id,
        decision=ReviewDecisionKind.ACCEPT,
        reviewer_id="morph_linguist",
        reviewer_role="community_linguist",
        notes="Accepted segmentation",
    )

    assert decision_res.target_status is LifecycleStatus.VALIDATED
    assert decision_res.task_status == "resolved"

    # Reload target: validated, score recomputed with morph-v1
    updated_target = ctx.repo.get_morph_analysis(target_analysis.id)
    assert updated_target.status is LifecycleStatus.VALIDATED
    assert updated_target.score_breakdown is not None
    assert updated_target.score_breakdown.policy_version == "morph-v1"

    # Assert invariant: competing analysis on the same token is untouched!
    updated_competitor = ctx.repo.get_morph_analysis(competitor.id)
    assert updated_competitor.status is LifecycleStatus.CANDIDATE

    # Analysis decisions flag nothing stale
    stale_edges = [
        edge
        for edge in ctx.repo.list_lineage_edges(target_analysis.id, direction="out")
        if edge.kind is LineageKind.STALE_DEPENDENT
    ]
    assert len(stale_edges) == 0


def test_review_morphology_analysis_accept_refuses_rejected_or_deprecated_morpheme(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    source_id, igt_run, tok_run = _setup_igt_pipeline(ctx, tmp_path, "refuse-morpheme-src")
    res = assert_igt(ctx, tokenization_run_id=tok_run, igt_extract_run_id=igt_run)

    # Find an analysis that links at least one morpheme
    target_analysis = None
    linked_morpheme = None
    for a in ctx.repo.list_morph_analyses_for_run(res.run.id):
        segs = ctx.repo.list_morph_segments(a.id)
        m_segs = [s for s in segs if s.morpheme_id is not None]
        if m_segs:
            target_analysis = a
            morph_id = m_segs[0].morpheme_id
            assert morph_id is not None
            linked_morpheme = ctx.repo.get_morpheme(morph_id)
            break
    assert target_analysis is not None
    assert linked_morpheme is not None

    # Demote the morpheme to REJECTED
    with ctx.repo.transaction():
        ctx.repo.set_morpheme_status(linked_morpheme.id, LifecycleStatus.REJECTED)

    task = service.create_task(
        target_id=target_analysis.id,
        task_type=ReviewTaskType.MORPHOLOGY_SEGMENTATION,
        required_role="community_linguist",
    )

    # Attempting to accept must raise InvalidTransition
    with pytest.raises(InvalidTransition):
        service.record_decision(
            task_id=task.id,
            decision=ReviewDecisionKind.ACCEPT,
            reviewer_id="morph_linguist",
            reviewer_role="community_linguist",
        )

    # Analysis status is unchanged
    assert ctx.repo.get_morph_analysis(target_analysis.id).status is LifecycleStatus.CANDIDATE

    # Demote the morpheme to DEPRECATED -> accept still raises InvalidTransition
    with ctx.repo.transaction():
        ctx.repo.set_morpheme_status(linked_morpheme.id, LifecycleStatus.DEPRECATED)

    with pytest.raises(InvalidTransition):
        service.record_decision(
            task_id=task.id,
            decision=ReviewDecisionKind.ACCEPT,
            reviewer_id="morph_linguist",
            reviewer_role="community_linguist",
        )


def test_review_morphology_analysis_reject(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    source_id, igt_run, tok_run = _setup_igt_pipeline(ctx, tmp_path, "rej-src")
    res_assert = assert_igt(ctx, tokenization_run_id=tok_run, igt_extract_run_id=igt_run)
    induce_morphology(
        ctx, tokenization_run_id=tok_run, method="unsegmented@0.1.0", language=LANGUAGE
    )

    analyses = ctx.repo.list_morph_analyses_for_run(res_assert.run.id)
    target_analysis = analyses[0]
    token_id = target_analysis.target_token_id

    competitor = [
        a for a in ctx.repo.list_morph_analyses_for_token(token_id) if a.id != target_analysis.id
    ][0]

    task = service.create_task(
        target_id=target_analysis.id,
        task_type=ReviewTaskType.MORPHOLOGY_SEGMENTATION,
        required_role="community_linguist",
    )

    decision_res = service.record_decision(
        task_id=task.id,
        decision=ReviewDecisionKind.REJECT,
        reviewer_id="morph_linguist",
        reviewer_role="community_linguist",
    )
    assert decision_res.target_status is LifecycleStatus.REJECTED

    # Invariant: competitor remains candidate
    assert ctx.repo.get_morph_analysis(competitor.id).status is LifecycleStatus.CANDIDATE


def test_review_morphology_analysis_modify(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    source_id, igt_run, tok_run = _setup_igt_pipeline(ctx, tmp_path, "mod-src")
    res_assert = assert_igt(ctx, tokenization_run_id=tok_run, igt_extract_run_id=igt_run)
    induce_morphology(
        ctx, tokenization_run_id=tok_run, method="unsegmented@0.1.0", language=LANGUAGE
    )

    analyses = ctx.repo.list_morph_analyses_for_run(res_assert.run.id)
    target_analysis = analyses[0]
    token_id = target_analysis.target_token_id

    # Competitor on the same token has a different signature
    successor_analysis = [
        a for a in ctx.repo.list_morph_analyses_for_token(token_id) if a.id != target_analysis.id
    ][0]
    assert successor_analysis.signature != target_analysis.signature

    task = service.create_task(
        target_id=target_analysis.id,
        task_type=ReviewTaskType.MORPHOLOGY_SEGMENTATION,
        required_role="community_linguist",
    )

    # Modify original with successor
    decision_res = service.record_decision(
        task_id=task.id,
        decision=ReviewDecisionKind.MODIFY,
        reviewer_id="morph_linguist",
        reviewer_role="community_linguist",
        superseding_object_id=successor_analysis.id,
    )

    assert decision_res.target_status is LifecycleStatus.DEPRECATED
    assert ctx.repo.get_morph_analysis(target_analysis.id).status is LifecycleStatus.DEPRECATED
    assert ctx.repo.get_morph_analysis(successor_analysis.id).status is LifecycleStatus.VALIDATED

    # Verify SUPERSEDES lineage edge
    edges = ctx.repo.list_lineage_edges(successor_analysis.id, direction="out")
    sup_edges = [
        e for e in edges if e.kind is LineageKind.SUPERSEDES and e.to_id == target_analysis.id
    ]
    assert len(sup_edges) == 1


def test_review_morphology_morpheme_accept_flags_analyses_stale(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    source_id, igt_run, tok_run = _setup_igt_pipeline(ctx, tmp_path, "morph-accept-src")
    res = assert_igt(ctx, tokenization_run_id=tok_run, igt_extract_run_id=igt_run)

    morphemes = ctx.repo.list_morphemes_for_run(res.run.id)
    # Find a morpheme that has linking analyses
    target_morpheme = None
    for m in morphemes:
        if ctx.repo.list_analyses_linking_morpheme(m.id):
            target_morpheme = m
            break
    assert target_morpheme is not None

    linking_analyses = ctx.repo.list_analyses_linking_morpheme(target_morpheme.id)
    assert len(linking_analyses) > 0

    task = service.create_task(
        target_id=target_morpheme.id,
        task_type=ReviewTaskType.MORPHEME_FUNCTION,
        required_role="community_linguist",
    )

    decision_res = service.record_decision(
        task_id=task.id,
        decision=ReviewDecisionKind.ACCEPT,
        reviewer_id="morph_linguist",
        reviewer_role="community_linguist",
    )

    assert decision_res.target_status is LifecycleStatus.VALIDATED
    updated_morpheme = ctx.repo.get_morpheme(target_morpheme.id)
    assert updated_morpheme.status is LifecycleStatus.VALIDATED
    assert updated_morpheme.score_breakdown is not None
    assert updated_morpheme.score_breakdown.policy_version == "morph-v1"

    # Allomorphs promoted to validated
    allomorphs = ctx.repo.list_allomorphs_for_morpheme(target_morpheme.id)
    for a in allomorphs:
        assert a.status is LifecycleStatus.VALIDATED

    # Every analysis linking the morpheme must now have a STALE_DEPENDENT edge to the morpheme
    for analysis in linking_analyses:
        edges = ctx.repo.list_lineage_edges(analysis.id, direction="out")
        stale_edges = [
            e
            for e in edges
            if e.kind is LineageKind.STALE_DEPENDENT and e.to_id == target_morpheme.id
        ]
        assert len(stale_edges) == 1


def test_review_morphology_morpheme_reject_flags_analyses_stale(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    source_id, igt_run, tok_run = _setup_igt_pipeline(ctx, tmp_path, "morph-rej-src")
    res = assert_igt(ctx, tokenization_run_id=tok_run, igt_extract_run_id=igt_run)

    morphemes = ctx.repo.list_morphemes_for_run(res.run.id)
    target_morpheme = [m for m in morphemes if ctx.repo.list_analyses_linking_morpheme(m.id)][0]
    linking_analyses = ctx.repo.list_analyses_linking_morpheme(target_morpheme.id)

    task = service.create_task(
        target_id=target_morpheme.id,
        task_type=ReviewTaskType.MORPHEME_FUNCTION,
        required_role="community_linguist",
    )

    decision_res = service.record_decision(
        task_id=task.id,
        decision=ReviewDecisionKind.REJECT,
        reviewer_id="morph_linguist",
        reviewer_role="community_linguist",
    )

    assert decision_res.target_status is LifecycleStatus.REJECTED
    assert ctx.repo.get_morpheme(target_morpheme.id).status is LifecycleStatus.REJECTED

    for analysis in linking_analyses:
        edges = ctx.repo.list_lineage_edges(analysis.id, direction="out")
        stale_edges = [
            e
            for e in edges
            if e.kind is LineageKind.STALE_DEPENDENT and e.to_id == target_morpheme.id
        ]
        assert len(stale_edges) == 1


def test_review_morphology_morpheme_modify(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    source_id, igt_run, tok_run = _setup_igt_pipeline(ctx, tmp_path, "morph-mod-src")
    res = assert_igt(ctx, tokenization_run_id=tok_run, igt_extract_run_id=igt_run)

    morphemes = ctx.repo.list_morphemes_for_run(res.run.id)
    target_morpheme = [m for m in morphemes if ctx.repo.list_analyses_linking_morpheme(m.id)][0]

    # Create a successor morpheme with corrected role (e.g. root instead of unknown_bound)
    # in the same language, sharing lineage to the source
    succ_morpheme = Morpheme(
        id=new_id(IdPrefix.MORPHEME),
        language=target_morpheme.language,
        role="root",
        canonical_form=target_morpheme.canonical_form,
        form_basis=target_morpheme.form_basis,
        identity_key="f" * 64,
        run_id=res.run.id,
        created_at=ctx.clock(),
    )
    with ctx.repo.transaction():
        ctx.repo.add_morpheme(succ_morpheme)
        # Lineage to source so human review is allowed
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=new_id(IdPrefix.LINEAGE),
                from_id=succ_morpheme.id,
                to_id=source_id,
                kind=LineageKind.DERIVED_FROM,
                run_id=res.run.id,
                created_at=ctx.clock(),
            )
        )

    task = service.create_task(
        target_id=target_morpheme.id,
        task_type=ReviewTaskType.MORPHEME_FUNCTION,
        required_role="community_linguist",
    )

    decision_res = service.record_decision(
        task_id=task.id,
        decision=ReviewDecisionKind.MODIFY,
        reviewer_id="morph_linguist",
        reviewer_role="community_linguist",
        superseding_object_id=succ_morpheme.id,
    )

    assert decision_res.target_status is LifecycleStatus.DEPRECATED
    assert ctx.repo.get_morpheme(target_morpheme.id).status is LifecycleStatus.DEPRECATED
    assert ctx.repo.get_morpheme(succ_morpheme.id).status is LifecycleStatus.VALIDATED

    # Lineage supersedes edge
    edges = ctx.repo.list_lineage_edges(succ_morpheme.id, direction="out")
    sup = [e for e in edges if e.kind is LineageKind.SUPERSEDES and e.to_id == target_morpheme.id]
    assert len(sup) == 1


def test_review_morphology_uncertain_and_defer(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    source_id, igt_run, tok_run = _setup_igt_pipeline(ctx, tmp_path, "unc-src")
    res = assert_igt(ctx, tokenization_run_id=tok_run, igt_extract_run_id=igt_run)

    analysis = ctx.repo.list_morph_analyses_for_run(res.run.id)[0]

    # In M5-PLAN §7.11, defer resolves morphology tasks and leaves target status untouched
    task_defer = service.create_task(
        target_id=analysis.id,
        task_type=ReviewTaskType.MORPHOLOGY_SEGMENTATION,
        required_role="community_linguist",
    )
    res_defer = service.record_decision(
        task_id=task_defer.id,
        decision=ReviewDecisionKind.DEFER,
        reviewer_id="morph_linguist",
        reviewer_role="community_linguist",
    )
    assert res_defer.target_status is None
    assert res_defer.task_status == "resolved"
    assert ctx.repo.get_review_task(task_defer.id).status == "resolved"

    # Uncertain also resolves task and leaves target status untouched
    task_unc = service.create_task(
        target_id=analysis.id,
        task_type=ReviewTaskType.MORPHOLOGY_SEGMENTATION,
        required_role="community_linguist",
    )
    res_unc = service.record_decision(
        task_id=task_unc.id,
        decision=ReviewDecisionKind.UNCERTAIN,
        reviewer_id="morph_linguist",
        reviewer_role="community_linguist",
    )
    assert res_unc.target_status is None
    assert res_unc.task_status == "resolved"
    assert ctx.repo.get_review_task(task_unc.id).status == "resolved"


def test_review_morphology_unauthorized_refusal_changes_nothing(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    source_id, igt_run, tok_run = _setup_igt_pipeline(ctx, tmp_path, "unauth-src")
    res = assert_igt(ctx, tokenization_run_id=tok_run, igt_extract_run_id=igt_run)

    analysis = ctx.repo.list_morph_analyses_for_run(res.run.id)[0]
    task = service.create_task(
        target_id=analysis.id,
        task_type=ReviewTaskType.MORPHOLOGY_SEGMENTATION,
        required_role="community_linguist",
    )

    # 1. Reviewer with wrong role raises UnauthorizedReviewer
    with pytest.raises(UnauthorizedReviewer):
        service.record_decision(
            task_id=task.id,
            decision=ReviewDecisionKind.ACCEPT,
            reviewer_id="elder",
            reviewer_role="native_speaker_elder",
        )

    # 2. Reviewer authorized for wrong language raises UnauthorizedReviewer
    with pytest.raises(UnauthorizedReviewer):
        service.record_decision(
            task_id=task.id,
            decision=ReviewDecisionKind.ACCEPT,
            reviewer_id="por_linguist",
            reviewer_role="community_linguist",
        )

    # Invariant: task is still open, analysis status is still candidate
    assert ctx.repo.get_review_task(task.id).status == "open"
    assert ctx.repo.get_morph_analysis(analysis.id).status is LifecycleStatus.CANDIDATE


def test_review_morphology_revoked_source_denies(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    source_id, igt_run, tok_run = _setup_igt_pipeline(ctx, tmp_path, "rev-src")
    res = assert_igt(ctx, tokenization_run_id=tok_run, igt_extract_run_id=igt_run)

    analysis = ctx.repo.list_morph_analyses_for_run(res.run.id)[0]

    # Revoke the source
    with ctx.repo.transaction():
        ctx.repo.set_source_status(source_id, SourceStatus.REVOKED, at=ctx.clock())

    # create_task is blocked
    with pytest.raises(PolicyDenied):
        service.create_task(
            target_id=analysis.id,
            task_type=ReviewTaskType.MORPHOLOGY_SEGMENTATION,
            required_role="community_linguist",
        )


def test_review_morphology_task_creation_enforces_community_linguist_role(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    source_id, igt_run, tok_run = _setup_igt_pipeline(ctx, tmp_path, "role-src")
    res = assert_igt(ctx, tokenization_run_id=tok_run, igt_extract_run_id=igt_run)

    analysis = ctx.repo.list_morph_analyses_for_run(res.run.id)[0]
    morpheme = ctx.repo.list_morphemes_for_run(res.run.id)[0]

    with pytest.raises(
        ValueError,
        match="required role for morphology_segmentation must be community_linguist",
    ):
        service.create_task(
            target_id=analysis.id,
            task_type=ReviewTaskType.MORPHOLOGY_SEGMENTATION,
            required_role="native_speaker_elder",
        )

    with pytest.raises(
        ValueError,
        match="required role for morpheme_function must be community_linguist",
    ):
        service.create_task(
            target_id=morpheme.id,
            task_type=ReviewTaskType.MORPHEME_FUNCTION,
            required_role="native_speaker_elder",
        )


def test_concurrent_analysis_accept_and_morpheme_rejection_serialize_on_postgres(
    pg_repository: PostgresRepository, tmp_path: Path
) -> None:
    """Gate 42: Concurrent morpheme rejection while analysis accept is attempted."""
    import threading
    import time

    from sqlalchemy import text

    from langpipe.domain.models.base import UTC_NOW
    from langpipe.storage.objects.local import LocalContentStore

    clock = UTC_NOW
    ctx = AppContext(
        repo=pg_repository,
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=clock,
        new_id=new_id,
        actor="test-actor",
        code_revision="test-rev",
    )
    source_id, igt_run, tok_run = _setup_igt_pipeline(ctx, tmp_path, "race-src")
    res = assert_igt(ctx, tokenization_run_id=tok_run, igt_extract_run_id=igt_run)

    target_analysis = None
    linked_morpheme_id = None
    for a in ctx.repo.list_morph_analyses_for_run(res.run.id):
        segs = ctx.repo.list_morph_segments(a.id)
        m_segs = [s for s in segs if s.morpheme_id is not None]
        if m_segs:
            target_analysis = a
            linked_morpheme_id = m_segs[0].morpheme_id
            break
    assert target_analysis is not None
    assert linked_morpheme_id is not None

    authority = ReviewAuthorityRegistry()
    authority.register("morph_linguist", "community_linguist", [LANGUAGE])
    authority.register("ana_linguist", "community_linguist", [LANGUAGE])

    service_main = ReviewService(pg_repository, authority, clock=clock, new_id=new_id)

    task_morph = service_main.create_task(
        target_id=linked_morpheme_id,
        task_type=ReviewTaskType.MORPHEME_FUNCTION,
        required_role="community_linguist",
    )
    task_ana = service_main.create_task(
        target_id=target_analysis.id,
        task_type=ReviewTaskType.MORPHOLOGY_SEGMENTATION,
        required_role="community_linguist",
    )

    repo_holder = PostgresRepository(pg_repository._engine)
    service_holder = ReviewService(repo_holder, authority, clock=clock, new_id=new_id)

    repo_contender = PostgresRepository(pg_repository._engine)
    service_contender = ReviewService(repo_contender, authority, clock=clock, new_id=new_id)

    inside = threading.Event()
    release = threading.Event()
    outcome: dict[str, object] = {}
    holder_pid: dict[str, int] = {}
    contender_pid: dict[str, int] = {}

    orig_set_morpheme_status = repo_holder.set_morpheme_status

    def synced_set_morpheme_status(*args, **kwargs):
        if repo_holder._session is not None:
            pid = repo_holder._session.execute(text("SELECT pg_backend_pid()")).scalar()
            if pid is not None:
                holder_pid["pid"] = pid
        res = orig_set_morpheme_status(*args, **kwargs)
        inside.set()
        assert release.wait(timeout=10.0)
        return res

    repo_holder.set_morpheme_status = synced_set_morpheme_status  # type: ignore[method-assign]

    orig_get_morph_analysis_for_update = repo_contender.get_morph_analysis_for_update

    def synced_get_morph_analysis_for_update(object_id: str):
        if repo_contender._session is not None:
            pid = repo_contender._session.execute(text("SELECT pg_backend_pid()")).scalar()
            if pid is not None:
                contender_pid["pid"] = pid
        return orig_get_morph_analysis_for_update(object_id)

    repo_contender.get_morph_analysis_for_update = (  # type: ignore[method-assign]
        synced_get_morph_analysis_for_update
    )

    def reject_morpheme_decision() -> None:
        try:
            service_holder.record_decision(
                task_morph.id, ReviewDecisionKind.REJECT, "morph_linguist", "community_linguist"
            )
            outcome["holder"] = "committed"
        except BaseException as exc:  # noqa: BLE001
            outcome["holder"] = exc

    def contend_accept_analysis() -> None:
        try:
            service_contender.record_decision(
                task_ana.id, ReviewDecisionKind.ACCEPT, "ana_linguist", "community_linguist"
            )
            outcome["contender"] = "committed"
        except InvalidTransition:
            outcome["contender"] = "refused"
        except BaseException as exc:  # noqa: BLE001
            outcome["contender"] = exc

    holder_thread = threading.Thread(target=reject_morpheme_decision)
    holder_thread.start()
    contender_thread = threading.Thread(target=contend_accept_analysis)
    try:
        assert inside.wait(timeout=10.0)
        contender_thread.start()

        # Poll PostgreSQL pg_stat_activity to verify that contender is blocked by holder
        blocked = False
        for _ in range(50):
            with pg_repository._engine.connect() as conn:
                res = (
                    conn.execute(
                        text(
                            "SELECT pid FROM pg_stat_activity "
                            "WHERE :hpid = ANY(pg_blocking_pids(pid))"
                        ),
                        {"hpid": holder_pid["pid"]},
                    )
                    .scalars()
                    .all()
                )
                if "pid" in contender_pid and contender_pid["pid"] in res:
                    blocked = True
                    break
            time.sleep(0.05)
        assert blocked, (
            f"Contender session {contender_pid.get('pid')} must be blocked by holder session "
            f"{holder_pid.get('pid')}"
        )
        release.set()
    finally:
        release.set()
        holder_thread.join(timeout=10.0)
        if contender_thread.ident is not None:
            contender_thread.join(timeout=10.0)

    assert not holder_thread.is_alive()
    assert not contender_thread.is_alive()
    assert outcome["holder"] == "committed"
    assert outcome["contender"] == "refused"
    assert pg_repository.get_morph_analysis(target_analysis.id).status is LifecycleStatus.CANDIDATE
    assert pg_repository.get_morpheme(linked_morpheme_id).status is LifecycleStatus.REJECTED
    assert pg_repository.get_review_task(task_morph.id).status == "resolved"
    assert pg_repository.get_review_task(task_ana.id).status == "open"


def test_concurrent_opposing_modify_decisions_serialize_without_deadlock_on_postgres(
    pg_repository: PostgresRepository, tmp_path: Path
) -> None:
    """Gate 42: Opposing modify decisions serialize in sorted lock order without deadlock."""
    import threading
    import time

    from sqlalchemy import text

    from langpipe.domain.models.base import UTC_NOW
    from langpipe.storage.objects.local import LocalContentStore

    clock = UTC_NOW
    ctx = AppContext(
        repo=pg_repository,
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=clock,
        new_id=new_id,
        actor="test-actor",
        code_revision="test-rev",
    )
    source_id, igt_run, tok_run = _setup_igt_pipeline(ctx, tmp_path, "opposing-src")
    res = assert_igt(ctx, tokenization_run_id=tok_run, igt_extract_run_id=igt_run)

    authority = ReviewAuthorityRegistry()
    authority.register("linguist_1", "community_linguist", [LANGUAGE])
    authority.register("linguist_2", "community_linguist", [LANGUAGE])

    service_main = ReviewService(pg_repository, authority, clock=clock, new_id=new_id)

    morphemes = ctx.repo.list_morphemes_for_run(res.run.id)
    m1 = morphemes[0]
    m2 = Morpheme(
        id=new_id(IdPrefix.MORPHEME),
        language=m1.language,
        role="root" if m1.role != "root" else "unknown_bound",
        canonical_form=m1.canonical_form,
        form_basis=m1.form_basis,
        identity_key="e" * 64,
        status=LifecycleStatus.CANDIDATE,
        run_id=res.run.id,
        created_at=clock(),
    )
    with ctx.repo.transaction():
        ctx.repo.add_morpheme(m2)
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=new_id(IdPrefix.LINEAGE),
                from_id=m2.id,
                to_id=source_id,
                kind=LineageKind.DERIVED_FROM,
                run_id=res.run.id,
                created_at=clock(),
            )
        )

    if m1.id < m2.id:
        m_low, m_high = m1, m2
    else:
        m_low, m_high = m2, m1

    task_low = service_main.create_task(
        target_id=m_low.id,
        task_type=ReviewTaskType.MORPHEME_FUNCTION,
        required_role="community_linguist",
    )
    task_high = service_main.create_task(
        target_id=m_high.id,
        task_type=ReviewTaskType.MORPHEME_FUNCTION,
        required_role="community_linguist",
    )

    repo1 = PostgresRepository(pg_repository._engine)
    service1 = ReviewService(repo1, authority, clock=clock, new_id=new_id)

    repo2 = PostgresRepository(pg_repository._engine)
    service2 = ReviewService(repo2, authority, clock=clock, new_id=new_id)

    outcome: dict[str, object] = {}
    holder_pid: dict[str, int] = {}
    contender_pid: dict[str, int] = {}
    first_lock_repo1: list[str] = []
    first_lock_repo2: list[str] = []
    lock_count = 0
    first_lock_acquired = threading.Event()
    release_first_lock = threading.Event()

    orig_get_morpheme_for_update1 = repo1.get_morpheme_for_update

    def synced_get_morpheme_for_update1(object_id: str):
        nonlocal lock_count
        first_lock_repo1.append(object_id)
        res = orig_get_morpheme_for_update1(object_id)
        lock_count += 1
        if lock_count == 1:
            if repo1._session is not None:
                pid = repo1._session.execute(text("SELECT pg_backend_pid()")).scalar()
                if pid is not None:
                    holder_pid["pid"] = pid
            first_lock_acquired.set()
            assert release_first_lock.wait(timeout=10.0)
        return res

    repo1.get_morpheme_for_update = synced_get_morpheme_for_update1  # type: ignore[method-assign]

    orig_get_morpheme_for_update2 = repo2.get_morpheme_for_update

    def synced_get_morpheme_for_update2(object_id: str):
        first_lock_repo2.append(object_id)
        if repo2._session is not None:
            pid = repo2._session.execute(text("SELECT pg_backend_pid()")).scalar()
            if pid is not None:
                contender_pid["pid"] = pid
        return orig_get_morpheme_for_update2(object_id)

    repo2.get_morpheme_for_update = synced_get_morpheme_for_update2  # type: ignore[method-assign]

    # Thread 1 modifies low -> high (locks min(low, high) = low, then max = high)
    def run_thread1() -> None:
        try:
            service1.record_decision(
                task_low.id,
                ReviewDecisionKind.MODIFY,
                "linguist_1",
                "community_linguist",
                superseding_object_id=m_high.id,
            )
            outcome["t1"] = "committed"
        except BaseException as exc:  # noqa: BLE001
            outcome["t1"] = exc

    # Thread 2 modifies high -> low (opposing order; sorted lock still acquires low then high)
    def run_thread2() -> None:
        try:
            service2.record_decision(
                task_high.id,
                ReviewDecisionKind.MODIFY,
                "linguist_2",
                "community_linguist",
                superseding_object_id=m_low.id,
            )
            outcome["t2"] = "committed"
        except InvalidTransition:
            outcome["t2"] = "invalid_transition"
        except BaseException as exc:  # noqa: BLE001
            outcome["t2"] = exc

    t1 = threading.Thread(target=run_thread1)
    t2 = threading.Thread(target=run_thread2)
    t1.start()
    try:
        # Wait until Thread 1 acquires ONLY the first row lock (m_low)
        assert first_lock_acquired.wait(timeout=10.0)
        t2.start()

        # Thread 2 (modifying m_high -> m_low) also sorts [m_high, m_low] and attempts to
        # lock m_low first. It must be blocked by Thread 1 via pg_blocking_pids BEFORE
        # acquiring any lock, proving that sorted locking prevents the deadlocking interleaving.
        blocked = False
        for _ in range(50):
            with pg_repository._engine.connect() as conn:
                res = (
                    conn.execute(
                        text(
                            "SELECT pid FROM pg_stat_activity "
                            "WHERE :hpid = ANY(pg_blocking_pids(pid))"
                        ),
                        {"hpid": holder_pid["pid"]},
                    )
                    .scalars()
                    .all()
                )
                if "pid" in contender_pid and contender_pid["pid"] in res:
                    blocked = True
                    break
            time.sleep(0.05)
        assert blocked, (
            f"Thread 2 (PID {contender_pid.get('pid')}) must be blocked by Thread 1 "
            f"(PID {holder_pid.get('pid')}) on the first lock"
        )
        release_first_lock.set()
    finally:
        release_first_lock.set()
        t1.join(timeout=10.0)
        if t2.ident is not None:
            t2.join(timeout=10.0)

    assert not t1.is_alive()
    assert not t2.is_alive()
    assert outcome["t1"] == "committed"
    assert outcome["t2"] in ("invalid_transition", "committed")
    assert first_lock_repo1[0] == m_low.id
    assert first_lock_repo2[0] == m_low.id
