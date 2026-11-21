"""Service tests for stale-dependent recalculation (M5-PLAN §7.12, WP5.14, Gate 43).

Contracts under test:
- Stale ⇔ dependent has a `stale_dependent` lineage edge with no later `recalculated`
  edge from the same dependent to the same decided object.
- `RecalcService.recalculate(object_ids | all_stale)`:
  - Recomputes each stale dependent's breakdown under its own policy
    (`lexical-v1` for senses, `morph-v1` for analyses).
  - Status unchanged: recalculation never promotes past `supported`, never demotes `validated`.
  - Writes a `recalculated` edge (dependent → decided object) under a `HUMAN_REVIEW`-stage
    maintenance run.
  - Idempotent: recalculating already fresh items skips them.
- Depth is bounded by the M5 graph (lexeme → senses; morpheme → analyses).
- CLI `langpipe review recalc [--object ID]... | --all-stale`.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from langpipe.app_context import AppContext
from langpipe.cli.app import app
from langpipe.cli.context import reset_context_factory, set_context_factory
from langpipe.domain.enums import (
    LifecycleStatus,
    LineageKind,
    ReviewDecisionKind,
    ReviewTaskType,
    RunStage,
    RunStatus,
)
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.lexical import Lexeme, Sense
from langpipe.domain.models.run import ProcessingRun, config_hash
from langpipe.igt.service import extract_igt
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.morphology.service import assert_igt
from langpipe.normalization.service import normalize_extraction
from langpipe.review.authority import ReviewAuthorityRegistry
from langpipe.review.recalc import (
    RecalcService,
    find_all_stale,
    is_stale,
    stale_decided_targets,
)
from langpipe.review.service import ReviewService
from langpipe.storage.memory import InMemoryRepository
from langpipe.storage.objects.local import LocalContentStore
from langpipe.tokenization.service import tokenize_normalization
from tests.service.manifests import manifest_data, write_manifest, write_origin_file

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_TOOLBOX = REPO_ROOT / "tests" / "fixtures" / "igt" / "toolbox_sample.txt"

REVIEWER = "linguist"
ROLE = "community_linguist"
LANGUAGE = "qaa"
runner = CliRunner()


def _seed_source(ctx: AppContext, tmp_path: Path, key: str) -> str:
    relative = f"data/{key}.txt"
    write_origin_file(tmp_path, relative, b"test content")
    data = manifest_data(
        key=key,
        mode="direct",
        access_class="public",
        objects=[{"path": relative, "media_type": "text/plain"}],
    )
    data["languages"] = [LANGUAGE]
    reg = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))
    return reg.source.id


@pytest.fixture
def cli_ctx(tmp_path: Path) -> Iterator[AppContext]:
    context = AppContext(
        repo=InMemoryRepository(),
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        new_id=new_id,
        actor="test-actor",
        code_revision="test-rev",
    )
    set_context_factory(lambda: context)
    yield context
    reset_context_factory()


def _make_review_service(ctx: AppContext) -> ReviewService:
    auth = ReviewAuthorityRegistry()
    auth.register(REVIEWER, ROLE, [LANGUAGE])
    return ReviewService(
        ctx.repo,
        auth,
        clock=ctx.clock,
        new_id=ctx.new_id,
        code_revision=ctx.code_revision,
    )


def _seed_run(ctx: AppContext) -> ProcessingRun:
    now = ctx.clock()
    digest = config_hash({})
    run_key = ProcessingRun.compute_run_key(
        RunStage.LEXICAL_INDUCTION, "test.induction", "0.1.0", digest, ()
    )
    run = ProcessingRun(
        id=ctx.new_id(IdPrefix.RUN),
        stage=RunStage.LEXICAL_INDUCTION,
        tool_name="test.induction",
        tool_version="0.1.0",
        config={},
        config_hash=digest,
        code_revision="dev",
        run_key=run_key,
        status=RunStatus.SUCCEEDED,
        started_at=now,
        finished_at=now,
    )
    with ctx.repo.transaction():
        ctx.repo.add_run(run)
    return run


# --- Staleness predicate & target discovery contracts ---------------------------------------


def test_staleness_predicate_exact_edge_semantics(ctx: AppContext) -> None:
    """Stale ⇔ stale_dependent edge with no later recalculated edge to same decided object."""
    run = _seed_run(ctx)
    repo = ctx.repo

    dep = ctx.new_id(IdPrefix.SENSE)
    parent_a = ctx.new_id(IdPrefix.LEXEME)
    parent_b = ctx.new_id(IdPrefix.LEXEME)

    lex_a = Lexeme(
        id=parent_a,
        language=LANGUAGE,
        status=LifecycleStatus.VALIDATED,
        run_id=run.id,
        created_at=ctx.clock(),
    )
    lex_b = Lexeme(
        id=parent_b,
        language=LANGUAGE,
        status=LifecycleStatus.VALIDATED,
        run_id=run.id,
        created_at=ctx.clock(),
    )
    dep_sense = Sense(
        id=dep,
        lexeme_id=parent_a,
        glosses={"por": ["teste"]},
        status=LifecycleStatus.SUPPORTED,
        run_id=run.id,
        created_at=ctx.clock(),
    )
    with repo.transaction():
        repo.add_lexeme(lex_a)
        repo.add_lexeme(lex_b)
        repo.add_sense(dep_sense)

    t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=10)
    t2 = t0 + timedelta(seconds=20)
    t3 = t0 + timedelta(seconds=30)

    # 1. No edges: not stale
    assert is_stale(repo, dep) is False
    assert stale_decided_targets(repo, dep) == []

    # 2. Add stale edge to parent_a at t0: is stale
    with repo.transaction():
        repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=dep,
                to_id=parent_a,
                kind=LineageKind.STALE_DEPENDENT,
                run_id=run.id,
                created_at=t0,
            )
        )
    assert is_stale(repo, dep) is True
    assert stale_decided_targets(repo, dep) == [parent_a]
    assert find_all_stale(repo) == [dep]

    # 3. Add recalculated edge to parent_b at t1: parent_a is still unresolved
    with repo.transaction():
        repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=dep,
                to_id=parent_b,
                kind=LineageKind.RECALCULATED,
                run_id=run.id,
                created_at=t1,
            )
        )
    assert is_stale(repo, dep) is True
    assert stale_decided_targets(repo, dep) == [parent_a]

    # 4. Add recalculated edge to parent_a at t2: resolved!
    with repo.transaction():
        repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=dep,
                to_id=parent_a,
                kind=LineageKind.RECALCULATED,
                run_id=run.id,
                created_at=t2,
            )
        )
    assert is_stale(repo, dep) is False
    assert stale_decided_targets(repo, dep) == []
    assert find_all_stale(repo) == []

    # 5. Later at t3, a decision on another parent_c flags dep stale: stale again!
    parent_c = ctx.new_id(IdPrefix.LEXEME)
    lex_c = Lexeme(
        id=parent_c,
        language=LANGUAGE,
        status=LifecycleStatus.VALIDATED,
        run_id=run.id,
        created_at=ctx.clock(),
    )
    with repo.transaction():
        repo.add_lexeme(lex_c)
        repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=dep,
                to_id=parent_c,
                kind=LineageKind.STALE_DEPENDENT,
                run_id=run.id,
                created_at=t3,
            )
        )
    assert is_stale(repo, dep) is True
    assert stale_decided_targets(repo, dep) == [parent_c]
    assert find_all_stale(repo) == [dep]


# --- Lexical sense recalculation ------------------------------------------------------------


def test_recalc_lexical_sense_recomputes_breakdown_and_preserves_status(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Recalculating a stale sense recomputes lexical-v1 breakdown and preserves status."""
    run = _seed_run(ctx)
    repo = ctx.repo

    source_id = _seed_source(ctx, tmp_path, "test-lex-src")

    lexeme = Lexeme(
        id=ctx.new_id(IdPrefix.LEXEME),
        language=LANGUAGE,
        status=LifecycleStatus.CANDIDATE,
        run_id=run.id,
        created_at=ctx.clock(),
    )
    sense_val = Sense(
        id=ctx.new_id(IdPrefix.SENSE),
        lexeme_id=lexeme.id,
        glosses={"por": ["validado"]},
        status=LifecycleStatus.VALIDATED,
        run_id=run.id,
        created_at=ctx.clock(),
    )
    sense_sup = Sense(
        id=ctx.new_id(IdPrefix.SENSE),
        lexeme_id=lexeme.id,
        glosses={"por": ["suportado"]},
        status=LifecycleStatus.SUPPORTED,
        run_id=run.id,
        created_at=ctx.clock(),
    )

    with repo.transaction():
        repo.add_lexeme(lexeme)
        repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=lexeme.id,
                to_id=source_id,
                kind=LineageKind.DERIVED_FROM,
                run_id=run.id,
                created_at=ctx.clock(),
            )
        )
        repo.add_sense(sense_val)
        repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=sense_val.id,
                to_id=lexeme.id,
                kind=LineageKind.DERIVED_FROM,
                run_id=run.id,
                created_at=ctx.clock(),
            )
        )
        repo.add_sense(sense_sup)
        repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=sense_sup.id,
                to_id=lexeme.id,
                kind=LineageKind.DERIVED_FROM,
                run_id=run.id,
                created_at=ctx.clock(),
            )
        )

    # Human review accepts the lexeme. This automatically flags both senses as stale_dependent!
    review = _make_review_service(ctx)
    task = review.create_task(lexeme.id, task_type=ReviewTaskType.LEMMA, required_role=ROLE)
    res = review.record_decision(task.id, ReviewDecisionKind.ACCEPT, REVIEWER, ROLE)
    assert res.target_status is LifecycleStatus.VALIDATED

    assert is_stale(repo, sense_val.id) is True
    assert is_stale(repo, sense_sup.id) is True

    # Recalculate sense_val explicitly
    recalc_service = RecalcService(ctx)
    result = recalc_service.recalculate([sense_val.id])
    assert result.recalculated_ids == (sense_val.id,)
    assert result.skipped_ids == ()
    assert is_stale(repo, sense_val.id) is False
    assert is_stale(repo, sense_sup.id) is True

    # Inspect sense_val after recalc: status must remain VALIDATED (Invariant 3)
    fresh_val = repo.get_sense(sense_val.id)
    assert fresh_val.status is LifecycleStatus.VALIDATED
    assert fresh_val.score_breakdown is not None
    assert fresh_val.score_breakdown.policy_version == "lexical-v1"

    # Now recalculate remaining with all_stale=True
    result_all = recalc_service.recalculate(all_stale=True)
    assert result_all.recalculated_ids == (sense_sup.id,)
    assert is_stale(repo, sense_sup.id) is False

    # Status of sense_sup must remain SUPPORTED (recalculation never auto-promotes to validated)
    fresh_sup = repo.get_sense(sense_sup.id)
    assert fresh_sup.status is LifecycleStatus.SUPPORTED
    assert fresh_sup.score_breakdown is not None
    assert fresh_sup.score_breakdown.policy_version == "lexical-v1"

    # Verify maintenance run metadata
    run_obj = repo.get_run(result_all.run.id)
    assert run_obj.stage is RunStage.HUMAN_REVIEW
    assert run_obj.tool_name == "langpipe.review.recalc"


# --- Morphology analysis recalculation -------------------------------------------------------


def test_recalc_morphology_analysis_recomputes_breakdown_and_preserves_status(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Recalculating a stale morph analysis recomputes morph-v1 breakdown and preserves status."""
    repo = ctx.repo
    relative = "texts/morph-recalc.dat"
    write_origin_file(tmp_path, relative, SAMPLE_TOOLBOX.read_bytes())
    data = manifest_data(
        key="morph-recalc",
        mode="direct",
        access_class="public",
        objects=[{"path": relative, "media_type": "text/plain"}],
    )
    data["source_type"] = "igt"
    data["languages"] = [LANGUAGE, "por"]
    reg = register_source(ctx, write_manifest(tmp_path, data, name="morph-recalc.yaml"))
    ingest_source(ctx, reg.source.id)

    igt_res = extract_igt(ctx, reg.source.id)
    norm_res = normalize_extraction(ctx, igt_res.run.id)
    tok_res = tokenize_normalization(ctx, norm_res.run.id)
    assert_res = assert_igt(
        ctx, tokenization_run_id=tok_res.run.id, igt_extract_run_id=igt_res.run.id
    )

    morphemes = ctx.repo.list_morphemes_for_run(assert_res.run.id)
    analyses = ctx.repo.list_morph_analyses_for_run(assert_res.run.id)
    assert len(morphemes) > 0
    assert len(analyses) > 0

    # Pick a morpheme that has dependent analyses
    morpheme = next(m for m in morphemes if len(ctx.repo.list_analyses_linking_morpheme(m.id)) > 0)
    analysis = ctx.repo.list_analyses_linking_morpheme(morpheme.id)[0]

    initial_status = analysis.status

    # Decide morpheme ACCEPT: flags morph analysis as stale_dependent
    review = _make_review_service(ctx)
    task = review.create_task(
        morpheme.id, task_type=ReviewTaskType.MORPHEME_FUNCTION, required_role=ROLE
    )
    review.record_decision(task.id, ReviewDecisionKind.ACCEPT, REVIEWER, ROLE)

    assert is_stale(repo, analysis.id) is True

    # Recalculate analysis
    recalc_service = RecalcService(ctx)
    result = recalc_service.recalculate([analysis.id])
    assert result.recalculated_ids == (analysis.id,)
    assert is_stale(repo, analysis.id) is False

    fresh_analysis = repo.get_morph_analysis(analysis.id)
    assert fresh_analysis.status is initial_status
    assert fresh_analysis.score_breakdown is not None
    assert fresh_analysis.score_breakdown.policy_version == "morph-v1"


# --- Idempotency contract -------------------------------------------------------------------


def test_recalc_idempotent_skips_fresh_targets(ctx: AppContext) -> None:
    """Recalculating an object that is not stale skips it without writing redundant edges."""
    run = _seed_run(ctx)
    repo = ctx.repo

    parent = ctx.new_id(IdPrefix.LEXEME)
    child = ctx.new_id(IdPrefix.SENSE)

    lexeme = Lexeme(
        id=parent,
        language=LANGUAGE,
        status=LifecycleStatus.VALIDATED,
        run_id=run.id,
        created_at=ctx.clock(),
    )
    sense = Sense(
        id=child,
        lexeme_id=parent,
        glosses={"por": ["teste"]},
        status=LifecycleStatus.SUPPORTED,
        run_id=run.id,
        created_at=ctx.clock(),
    )
    with repo.transaction():
        repo.add_lexeme(lexeme)
        repo.add_sense(sense)
        # Flag stale
        repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=child,
                to_id=parent,
                kind=LineageKind.STALE_DEPENDENT,
                run_id=run.id,
                created_at=ctx.clock(),
            )
        )

    recalc_service = RecalcService(ctx)

    # First run: recalculated
    res_1 = recalc_service.recalculate([child])
    assert res_1.recalculated_ids == (child,)
    assert res_1.skipped_ids == ()

    # Count edges
    edges_after_1 = repo.list_lineage_edges(child, direction="out")
    recalc_edges_1 = [e for e in edges_after_1 if e.kind is LineageKind.RECALCULATED]
    assert len(recalc_edges_1) == 1

    # Second run: skipped!
    res_2 = recalc_service.recalculate([child])
    assert res_2.recalculated_ids == ()
    assert res_2.skipped_ids == (child,)

    # Edge count unchanged
    edges_after_2 = repo.list_lineage_edges(child, direction="out")
    recalc_edges_2 = [e for e in edges_after_2 if e.kind is LineageKind.RECALCULATED]
    assert len(recalc_edges_2) == 1

    # Third run with --all-stale: repeated identical empty runs succeed without key collision
    res_3 = recalc_service.recalculate(all_stale=True)
    assert res_3.recalculated_ids == ()
    res_4 = recalc_service.recalculate(all_stale=True)
    assert res_4.recalculated_ids == ()
    assert res_3.run.id != res_4.run.id


# --- CLI command verification ----------------------------------------------------------------


def test_cli_review_recalc_options_and_errors(cli_ctx: AppContext) -> None:
    """CLI review recalc validates options and exits cleanly."""
    # Neither --object nor --all-stale: error
    res_none = runner.invoke(app, ["review", "recalc"])
    assert res_none.exit_code != 0

    # Both --object and --all-stale: error
    res_both = runner.invoke(app, ["review", "recalc", "--object", "sense_1", "--all-stale"])
    assert res_both.exit_code != 0

    # --all-stale runs cleanly (0 stale objects in empty db)
    res_all = runner.invoke(app, ["review", "recalc", "--all-stale"])
    assert res_all.exit_code == 0
    assert "recalculated=0 skipped=0" in res_all.stdout
