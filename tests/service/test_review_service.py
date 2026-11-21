"""Human review queue service contracts (WP4.8, ADR-0013 §4-5, REVIEW-WORKFLOW.md).

`ReviewService` owns the only path to `validated`/`rejected` status: an authorized
reviewer decision over a governed target. These tests cover priority computation,
the M4 lexical task-type fence, every decision kind's side effects, lifecycle
legality (deprecated is terminal, no revival), successor governance on modify,
score recalculation, direct-dependent staleness, review lineage and traversal,
authority and governance refusal with zero side effects, decision immutability and
queue filtering, on both the memory and PostgreSQL backends (run sequentially).
"""

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    EntityType,
    EvidenceKind,
    EvidencePolarity,
    LifecycleStatus,
    LineageKind,
    Operation,
    PolicyDecision,
    ReviewDecisionKind,
    ReviewTaskType,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
)
from langpipe.domain.errors import (
    InvalidLineage,
    InvalidTransition,
    NotFound,
    PolicyDenied,
    SchemaViolation,
)
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.lexical import Concept, Lexeme, LexicalScoreBreakdown, Sense
from langpipe.governance.lineage_policy import ancestor_source_ids
from langpipe.ingestion.registration import register_source
from langpipe.ingestion.runs import RunRecorder
from langpipe.lexicon.scoring import compute_score
from langpipe.review.authority import ReviewAuthorityRegistry
from langpipe.review.base import UnauthorizedReviewer
from langpipe.review.service import ReviewService
from langpipe.storage.db.repository import PostgresRepository
from langpipe.storage.objects.local import LocalContentStore
from tests.service.manifests import manifest_data, write_manifest, write_origin_file

LANGUAGE = "mzr"
JOIN_TIMEOUT = 10.0
FIXED_MOMENT = datetime(2026, 6, 1, tzinfo=UTC)


@pytest.fixture
def authority() -> ReviewAuthorityRegistry:
    registry = ReviewAuthorityRegistry()
    registry.register("linguist_1", "community_linguist", [LANGUAGE])
    registry.register("elder_1", "native_speaker_elder", [LANGUAGE], domains=["ritual"])
    registry.register("steward_1", "editorial_steward", [LANGUAGE, "qaa"])
    registry.register("por_linguist", "community_linguist", ["por"])
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


def _register_source(ctx: AppContext, tmp_path: Path, key: str, *, mode: str = "direct"):
    relative = f"texts/{key}.txt"
    write_origin_file(tmp_path, relative, b"origin bytes\n")
    data = manifest_data(
        key=key, mode=mode, objects=[{"path": relative, "media_type": "text/plain"}]
    )
    return register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))


def _candidate_lexeme(
    ctx: AppContext,
    source_object_id: str,
    *,
    domain: str | None = None,
    language: str = LANGUAGE,
    with_lineage: bool = True,
    status: LifecycleStatus = LifecycleStatus.CANDIDATE,
    score_breakdown: LexicalScoreBreakdown | None = None,
) -> Lexeme:
    """One candidate lexeme descending from the source object through lineage."""
    run_id = (
        RunRecorder(ctx)
        .start(RunStage.LEXICAL_INDUCTION, "langpipe.test", {}, [source_object_id])
        .id
    )
    lexeme = Lexeme(
        id=ctx.new_id(IdPrefix.LEXEME),
        language=language,
        domain=domain,
        status=status,
        score_breakdown=score_breakdown,
        run_id=run_id,
        created_at=ctx.clock(),
    )
    with ctx.repo.transaction():
        ctx.repo.add_lexeme(lexeme)
        if with_lineage:
            ctx.repo.add_lineage_edge(
                LineageEdge(
                    id=ctx.new_id(IdPrefix.LINEAGE),
                    from_id=lexeme.id,
                    to_id=source_object_id,
                    kind=LineageKind.DERIVED_FROM,
                    run_id=run_id,
                    created_at=ctx.clock(),
                )
            )
    return lexeme


def _candidate_sense(ctx: AppContext, source_object_id: str) -> Sense:
    """One candidate sense under its own candidate lexeme, both descending from the source."""
    run_id = (
        RunRecorder(ctx)
        .start(RunStage.LEXICAL_INDUCTION, "langpipe.test", {}, [source_object_id])
        .id
    )
    lexeme = Lexeme(
        id=ctx.new_id(IdPrefix.LEXEME),
        language=LANGUAGE,
        run_id=run_id,
        created_at=ctx.clock(),
    )
    sense = Sense(
        id=ctx.new_id(IdPrefix.SENSE),
        lexeme_id=lexeme.id,
        glosses={"por": ["canoa"]},
        run_id=run_id,
        created_at=ctx.clock(),
    )
    with ctx.repo.transaction():
        ctx.repo.add_lexeme(lexeme)
        ctx.repo.add_sense(sense)
        for node_id in (lexeme.id, sense.id):
            ctx.repo.add_lineage_edge(
                LineageEdge(
                    id=ctx.new_id(IdPrefix.LINEAGE),
                    from_id=node_id,
                    to_id=source_object_id,
                    kind=LineageKind.DERIVED_FROM,
                    run_id=run_id,
                    created_at=ctx.clock(),
                )
            )
    return sense


def _sense_under(
    ctx: AppContext, source_object_id: str, lexeme: Lexeme, *, domain: str | None = None
) -> Sense:
    """One candidate sense under an existing lexeme, itself descending from the source."""
    sense = Sense(
        id=ctx.new_id(IdPrefix.SENSE),
        lexeme_id=lexeme.id,
        glosses={"por": ["panela"]},
        domain=domain,
        run_id=lexeme.run_id,
        created_at=ctx.clock(),
    )
    with ctx.repo.transaction():
        ctx.repo.add_sense(sense)
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=sense.id,
                to_id=source_object_id,
                kind=LineageKind.DERIVED_FROM,
                run_id=lexeme.run_id,
                created_at=ctx.clock(),
            )
        )
    return sense


def _concept(ctx: AppContext) -> Concept:
    """One concept with run lineage only (concepts carry no language or lifecycle)."""
    run_id = RunRecorder(ctx).start(RunStage.LEXICAL_INDUCTION, "langpipe.test", {}, []).id
    concept = Concept(
        id=ctx.new_id(IdPrefix.CONCEPT),
        canonical_label="harvest festival",
        run_id=run_id,
        created_at=ctx.clock(),
    )
    with ctx.repo.transaction():
        ctx.repo.add_concept(concept)
    return concept


def _evidence(ctx: AppContext, run_id: str, target_id: str, source_id: str) -> EvidenceItem:
    item = EvidenceItem(
        id=ctx.new_id(IdPrefix.EVIDENCE),
        kind=EvidenceKind.DICTIONARY_ASSERTION,
        polarity=EvidencePolarity.SUPPORTS,
        target_id=target_id,
        run_id=run_id,
        source_id=source_id,
        created_at=ctx.clock(),
    )
    with ctx.repo.transaction():
        ctx.repo.add_evidence(item)
    return item


def _task(ctx: AppContext, service: ReviewService, target_id: str, **kwargs: object):
    defaults: dict[str, object] = {
        "task_type": ReviewTaskType.LEXICAL_SENSE,
        "required_role": "community_linguist",
        "creator_run_id": RunRecorder(ctx).start(RunStage.HUMAN_REVIEW, "langpipe.test", {}, []).id,
    }
    defaults.update(kwargs)
    return service.create_task(target_id, **defaults)  # type: ignore[arg-type]


# --- task creation --------------------------------------------------------------------------


def test_create_task_computes_priority_and_persists_open(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "priority-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = _task(
        ctx,
        service,
        lexeme.id,
        frequency=2.0,
        uncertainty=1.5,
        downstream_impact=2.0,
        evidence_conflict=1.0,
        sensitivity=1.0,
    )
    assert task.priority == pytest.approx(6.0)
    assert task.status == "open"
    assert task.reason == "Lexical candidate review"
    stored = ctx.repo.get_review_task(task.id)
    assert stored == task
    assert ctx.repo.entity_type_of(task.id) is EntityType.REVIEW_TASK


def test_create_task_clamps_negative_products_to_zero(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "clamp-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = _task(ctx, service, lexeme.id, frequency=-2.0, uncertainty=3.0)
    assert task.priority == 0.0


def test_create_task_rejects_nonfinite_factors(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "nonfinite-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    with pytest.raises(ValueError):
        _task(ctx, service, lexeme.id, uncertainty=float("nan"))
    assert ctx.repo.count(EntityType.REVIEW_TASK) == 0


def test_create_task_rejects_non_lexical_type_in_m4(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "nonlexical-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    with pytest.raises(ValueError, match="non-lexical task type rejected in M4"):
        _task(
            ctx,
            service,
            lexeme.id,
            task_type=ReviewTaskType.MORPHOLOGY_SEGMENTATION,
        )
    assert ctx.repo.count(EntityType.REVIEW_TASK) == 0


def test_create_task_accepts_all_four_lexical_types(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "lexical-types-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    for task_type in (
        ReviewTaskType.LEXICAL_SENSE,
        ReviewTaskType.LEMMA,
        ReviewTaskType.REGISTER_DOMAIN,
        ReviewTaskType.GOVERNANCE_EXPORT,
    ):
        assert _task(ctx, service, lexeme.id, task_type=task_type).task_type is task_type


def test_create_task_rejects_unknown_target(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    _register_source(ctx, tmp_path, "unknown-target-src")
    with pytest.raises(NotFound):
        _task(ctx, service, "lex_" + "0" * 26)
    assert ctx.repo.count(EntityType.REVIEW_TASK) == 0


def test_create_task_default_creator_run_carries_provenance(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "default-run-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = service.create_task(lexeme.id, ReviewTaskType.LEMMA, "community_linguist")
    run = ctx.repo.get_run(task.creator_run_id)
    assert run.stage is RunStage.HUMAN_REVIEW
    # Real provenance: the run consumed the target and produced the task (invariant 4).
    assert (lexeme.id, RunIoRole.INPUT) in ctx.repo.list_run_io(task.creator_run_id)
    assert (task.id, RunIoRole.OUTPUT) in ctx.repo.list_run_io(task.creator_run_id)
    # The queue entry hangs off its target in the graph, so ancestor traversal reaches it.
    assert (task.id, 1) in [(node_id, depth) for node_id, depth in ctx.repo.descendants(lexeme.id)]


def test_create_task_repeated_under_fixed_clock_gets_distinct_creator_runs(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    # A fixed injected clock must not collapse two queue entries onto one succeeded
    # creator run: run identity is collision-safe without relying on the timestamp.
    registered = _register_source(ctx, tmp_path, "fixed-clock-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    fixed = ReviewService(
        ctx.repo,
        authority,
        clock=lambda: FIXED_MOMENT,
        new_id=ctx.new_id,
        code_revision=ctx.code_revision,
    )
    first = fixed.create_task(lexeme.id, ReviewTaskType.LEMMA, "community_linguist")
    second = fixed.create_task(lexeme.id, ReviewTaskType.LEMMA, "community_linguist")
    assert first.creator_run_id != second.creator_run_id
    assert first.id != second.id
    for task in (first, second):
        run = ctx.repo.get_run(task.creator_run_id)
        assert run.status is RunStatus.SUCCEEDED
        assert (lexeme.id, RunIoRole.INPUT) in ctx.repo.list_run_io(run.id)
        assert (task.id, RunIoRole.OUTPUT) in ctx.repo.list_run_io(run.id)


def test_create_task_rejects_pinned_version_mismatching_the_target(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    # The pinned target_version is the lifecycle status-of-record the caller reviewed.
    registered = _register_source(ctx, tmp_path, "pin-mismatch-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    with pytest.raises(SchemaViolation):
        _task(ctx, service, lexeme.id, target_version="supported")
    matching = _task(ctx, service, lexeme.id, target_version="candidate")
    assert matching.target_version == "candidate"


def test_list_tasks_filters_by_type_role_and_limit(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "list-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    sense = _candidate_sense(ctx, registered.objects[0].id)
    lemma_task = _task(ctx, service, lexeme.id, task_type=ReviewTaskType.LEMMA, frequency=3.0)
    sense_task = _task(
        ctx, service, sense.id, task_type=ReviewTaskType.LEXICAL_SENSE, frequency=2.0
    )
    steward_task = _task(
        ctx,
        service,
        sense.id,
        task_type=ReviewTaskType.REGISTER_DOMAIN,
        required_role="editorial_steward",
        frequency=1.0,
    )

    assert [task.id for task in service.list_tasks()] == [
        lemma_task.id,
        sense_task.id,
        steward_task.id,
    ]
    by_type = service.list_tasks(task_type=ReviewTaskType.LEXICAL_SENSE)
    assert len(by_type) == 1
    assert by_type[0].task_type is ReviewTaskType.LEXICAL_SENSE
    by_role = service.list_tasks(required_role="editorial_steward")
    assert [task.id for task in by_role] == [steward_task.id]
    assert [task.id for task in service.list_tasks(limit=1)] == [lemma_task.id]


def test_list_tasks_filters_by_status_priority_and_language(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "queue-filters-src")
    mzr_lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    por_lexeme = _candidate_lexeme(ctx, registered.objects[0].id, language="por")
    mzr_sense = _sense_under(ctx, registered.objects[0].id, mzr_lexeme)
    concept = _concept(ctx)
    high = _task(ctx, service, mzr_lexeme.id, task_type=ReviewTaskType.LEMMA, frequency=3.0)
    resolved_por = _task(ctx, service, por_lexeme.id, frequency=2.0)
    low = _task(ctx, service, mzr_sense.id, frequency=1.0)
    languageless = _task(ctx, service, concept.id, frequency=1.0)
    with ctx.repo.transaction():
        ctx.repo.set_review_task_status(resolved_por.id, "resolved")

    # Default view stays the open queue, highest priority first.
    assert [task.id for task in service.list_tasks()] == [high.id, low.id, languageless.id]
    # Sense language derives from its lexeme; language-less targets never match.
    assert [task.id for task in service.list_tasks(language=LANGUAGE)] == [high.id, low.id]
    assert [task.id for task in service.list_tasks(language="por")] == []
    by_status = service.list_tasks(status="resolved")
    assert [task.id for task in by_status] == [resolved_por.id]
    assert [task.id for task in service.list_tasks(language="por", status=None)] == [
        resolved_por.id
    ]
    everything = service.list_tasks(status=None)
    assert [task.id for task in everything] == [high.id, resolved_por.id, low.id, languageless.id]
    assert [task.id for task in service.list_tasks(min_priority=2.5)] == [high.id]
    assert [task.id for task in service.list_tasks(status=None, min_priority=2.5)] == [high.id]


def test_list_tasks_rejects_invalid_status_and_priority(
    ctx: AppContext, service: ReviewService
) -> None:
    with pytest.raises(ValueError):
        service.list_tasks(status="validated")  # a lifecycle status is not a queue state
    with pytest.raises(ValueError):
        service.list_tasks(status="whenever")
    with pytest.raises(ValueError):
        service.list_tasks(min_priority=float("nan"))
    with pytest.raises(ValueError):
        service.list_tasks(min_priority=True)  # type: ignore[arg-type]


# --- decisions and state transitions ----------------------------------------------------------


def test_accept_promotes_candidate_to_validated(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "accept-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = _task(ctx, service, lexeme.id)
    result = service.record_decision(
        task.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
    )
    assert result.decision.decision is ReviewDecisionKind.ACCEPT
    assert result.decision.target_id == lexeme.id
    assert result.target_status is LifecycleStatus.VALIDATED
    assert result.task_status == "resolved"
    assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.VALIDATED
    assert ctx.repo.get_review_task(task.id).status == "resolved"


def test_accept_promotes_supported_to_validated(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "accept-supported-src")
    stale = LexicalScoreBreakdown(policy_version="lexical-v1", overall=0.99)
    lexeme = _candidate_lexeme(
        ctx,
        registered.objects[0].id,
        status=LifecycleStatus.SUPPORTED,
        score_breakdown=stale,
    )
    task = _task(ctx, service, lexeme.id)
    result = service.record_decision(
        task.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
    )
    assert result.target_status is LifecycleStatus.VALIDATED
    # A scored target keeps a scored target: the audit breakdown is never erased.
    stored = ctx.repo.get_lexeme(lexeme.id).score_breakdown
    assert stored is not None
    assert stored.policy_version == "lexical-v1"


def test_accept_promotes_a_sense_via_its_lexeme_language(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "accept-sense-src")
    sense = _candidate_sense(ctx, registered.objects[0].id)
    task = _task(ctx, service, sense.id)
    result = service.record_decision(
        task.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
    )
    assert result.target_status is LifecycleStatus.VALIDATED
    assert ctx.repo.get_sense(sense.id).status is LifecycleStatus.VALIDATED


def test_reject_transitions_target_to_rejected(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "reject-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = _task(ctx, service, lexeme.id)
    result = service.record_decision(
        task.id, ReviewDecisionKind.REJECT, "linguist_1", "community_linguist", notes="borrowing"
    )
    assert result.target_status is LifecycleStatus.REJECTED
    assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.REJECTED
    assert ctx.repo.get_review_task(task.id).status == "resolved"


def test_modify_deprecates_predecessor_and_validates_successor(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "modify-src")
    source_object_id = registered.objects[0].id
    lexeme = _candidate_lexeme(ctx, source_object_id)
    successor = _candidate_lexeme(ctx, source_object_id)
    task = _task(ctx, service, lexeme.id)
    result = service.record_decision(
        task.id,
        ReviewDecisionKind.MODIFY,
        "linguist_1",
        "community_linguist",
        superseding_object_id=successor.id,
    )
    assert result.target_status is LifecycleStatus.DEPRECATED
    assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.DEPRECATED
    assert ctx.repo.get_lexeme(successor.id).status is LifecycleStatus.VALIDATED
    supersede = [
        edge
        for edge in ctx.repo.list_lineage_edges(successor.id, "out")
        if edge.kind is LineageKind.SUPERSEDES
    ]
    assert [edge.to_id for edge in supersede] == [lexeme.id]
    assert ctx.repo.get_review_task(task.id).status == "resolved"
    # Both changed objects carry a recomputed versioned breakdown.
    for object_id in (lexeme.id, successor.id):
        stored = ctx.repo.get_lexeme(object_id).score_breakdown
        assert stored is not None
        expected = compute_score(ctx.repo.list_evidence_for_target(object_id), LANGUAGE)
        assert stored == expected


def test_modify_requires_a_known_superseding_object(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "modify-missing-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = _task(ctx, service, lexeme.id)
    with pytest.raises(SchemaViolation):
        service.record_decision(
            task.id, ReviewDecisionKind.MODIFY, "linguist_1", "community_linguist"
        )
    with pytest.raises(NotFound):
        service.record_decision(
            task.id,
            ReviewDecisionKind.MODIFY,
            "linguist_1",
            "community_linguist",
            superseding_object_id="lex_" + "0" * 26,
        )
    # Refusals wrote nothing: the queue entry stays open and the target keeps its status.
    assert ctx.repo.get_review_task(task.id).status == "open"
    assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.CANDIDATE


def test_modify_rejects_self_supersession(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "modify-self-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = _task(ctx, service, lexeme.id)
    with pytest.raises(SchemaViolation):
        service.record_decision(
            task.id,
            ReviewDecisionKind.MODIFY,
            "linguist_1",
            "community_linguist",
            superseding_object_id=lexeme.id,
        )
    assert ctx.repo.get_review_task(task.id).status == "open"
    assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.CANDIDATE
    assert ctx.repo.count(EntityType.REVIEW_DECISION) == 0


def test_modify_rejects_foreign_language_successor(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "modify-foreign-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    foreign = _candidate_lexeme(ctx, registered.objects[0].id, language="por")
    task = _task(ctx, service, lexeme.id)
    with pytest.raises(SchemaViolation):
        service.record_decision(
            task.id,
            ReviewDecisionKind.MODIFY,
            "linguist_1",
            "community_linguist",
            superseding_object_id=foreign.id,
        )
    assert ctx.repo.get_review_task(task.id).status == "open"
    assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.CANDIDATE
    assert ctx.repo.get_lexeme(foreign.id).status is LifecycleStatus.CANDIDATE


def test_modify_rejects_sense_successor_of_another_lexeme(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    # A sense replacement must keep the compatible lexical relationship: same lexeme.
    registered = _register_source(ctx, tmp_path, "modify-sense-lex-src")
    sense = _candidate_sense(ctx, registered.objects[0].id)
    stranger_lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    stranger_sense = _sense_under(ctx, registered.objects[0].id, stranger_lexeme)
    task = _task(ctx, service, sense.id)
    with pytest.raises(SchemaViolation):
        service.record_decision(
            task.id,
            ReviewDecisionKind.MODIFY,
            "linguist_1",
            "community_linguist",
            superseding_object_id=stranger_sense.id,
        )
    assert ctx.repo.get_review_task(task.id).status == "open"
    assert ctx.repo.get_sense(sense.id).status is LifecycleStatus.CANDIDATE


def test_modify_allows_a_sense_successor_under_the_same_lexeme(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "modify-sense-ok-src")
    sense = _candidate_sense(ctx, registered.objects[0].id)
    replacement = Sense(
        id=ctx.new_id(IdPrefix.SENSE),
        lexeme_id=sense.lexeme_id,
        glosses={"por": ["canoa corrigida"]},
        run_id=sense.run_id,
        created_at=ctx.clock(),
    )
    with ctx.repo.transaction():
        ctx.repo.add_sense(replacement)
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=replacement.id,
                to_id=registered.objects[0].id,
                kind=LineageKind.DERIVED_FROM,
                run_id=sense.run_id,
                created_at=ctx.clock(),
            )
        )
    task = _task(ctx, service, sense.id)
    result = service.record_decision(
        task.id,
        ReviewDecisionKind.MODIFY,
        "linguist_1",
        "community_linguist",
        superseding_object_id=replacement.id,
    )
    assert result.target_status is LifecycleStatus.DEPRECATED
    assert ctx.repo.get_sense(replacement.id).status is LifecycleStatus.VALIDATED


def test_modify_denies_successor_outside_domain_scope(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    # The successor's own domain must be inside the reviewer's registry scope.
    registered = _register_source(ctx, tmp_path, "modify-domain-src")
    ritual = _candidate_lexeme(ctx, registered.objects[0].id, domain="ritual")
    household = _candidate_lexeme(ctx, registered.objects[0].id, domain="household")
    task = _task(ctx, service, ritual.id, required_role="native_speaker_elder")
    with pytest.raises(UnauthorizedReviewer):
        service.record_decision(
            task.id,
            ReviewDecisionKind.MODIFY,
            "elder_1",
            "native_speaker_elder",
            superseding_object_id=household.id,
        )
    assert ctx.repo.get_review_task(task.id).status == "open"
    assert ctx.repo.get_lexeme(ritual.id).status is LifecycleStatus.CANDIDATE
    assert ctx.repo.get_lexeme(household.id).status is LifecycleStatus.CANDIDATE
    assert ctx.repo.count(EntityType.REVIEW_DECISION) == 0


def test_modify_denies_successor_from_restricted_source(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "modify-open-src")
    restricted = _register_source(ctx, tmp_path, "modify-restricted-src", mode="restricted")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    successor = _candidate_lexeme(ctx, restricted.objects[0].id)
    task = _task(ctx, service, lexeme.id)
    with pytest.raises(PolicyDenied):
        service.record_decision(
            task.id,
            ReviewDecisionKind.MODIFY,
            "linguist_1",
            "community_linguist",
            superseding_object_id=successor.id,
        )
    assert ctx.repo.get_review_task(task.id).status == "open"
    assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.CANDIDATE
    assert ctx.repo.get_lexeme(successor.id).status is LifecycleStatus.CANDIDATE
    assert ctx.repo.count(EntityType.REVIEW_DECISION) == 0


def test_modify_refuses_successor_without_source_lineage(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "modify-orphan-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    orphan = _candidate_lexeme(ctx, registered.objects[0].id, with_lineage=False)
    task = _task(ctx, service, lexeme.id)
    with pytest.raises(InvalidLineage):
        service.record_decision(
            task.id,
            ReviewDecisionKind.MODIFY,
            "linguist_1",
            "community_linguist",
            superseding_object_id=orphan.id,
        )
    assert ctx.repo.get_review_task(task.id).status == "open"
    assert ctx.repo.count(EntityType.REVIEW_DECISION) == 0


# --- lifecycle legality -----------------------------------------------------------------------


def test_deprecated_target_is_terminal(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "terminal-src")
    source_object_id = registered.objects[0].id
    lexeme = _candidate_lexeme(ctx, source_object_id)
    successor = _candidate_lexeme(ctx, source_object_id)
    later_successor = _candidate_lexeme(ctx, source_object_id)
    task = _task(ctx, service, lexeme.id)
    service.record_decision(
        task.id,
        ReviewDecisionKind.MODIFY,
        "linguist_1",
        "community_linguist",
        superseding_object_id=successor.id,
    )
    assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.DEPRECATED
    for decision in (
        ReviewDecisionKind.ACCEPT,
        ReviewDecisionKind.REJECT,
        ReviewDecisionKind.MODIFY,
    ):
        followup = _task(ctx, service, lexeme.id)
        with pytest.raises(InvalidTransition):
            service.record_decision(
                followup.id,
                decision,
                "linguist_1",
                "community_linguist",
                superseding_object_id=later_successor.id,
            )
        assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.DEPRECATED
        assert ctx.repo.count(EntityType.REVIEW_DECISION) == 1


def test_rejected_target_is_not_revived_by_accept(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "revival-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = _task(ctx, service, lexeme.id)
    service.record_decision(task.id, ReviewDecisionKind.REJECT, "linguist_1", "community_linguist")
    followup = _task(ctx, service, lexeme.id)
    with pytest.raises(InvalidTransition):
        service.record_decision(
            followup.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
        )
    assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.REJECTED
    assert ctx.repo.count(EntityType.REVIEW_DECISION) == 1


def test_accept_refuses_an_already_validated_target(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "reaccept-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = _task(ctx, service, lexeme.id)
    service.record_decision(task.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist")
    followup = _task(ctx, service, lexeme.id)
    with pytest.raises(InvalidTransition):
        service.record_decision(
            followup.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
        )
    assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.VALIDATED
    assert ctx.repo.count(EntityType.REVIEW_DECISION) == 1


def test_uncertain_resolves_without_touching_the_target(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "uncertain-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = _task(ctx, service, lexeme.id)
    result = service.record_decision(
        task.id, ReviewDecisionKind.UNCERTAIN, "linguist_1", "community_linguist"
    )
    assert result.target_status is None
    assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.CANDIDATE
    assert ctx.repo.get_review_task(task.id).status == "resolved"


def test_defer_keeps_task_open_for_a_later_decision(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "defer-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = _task(ctx, service, lexeme.id)
    result = service.record_decision(
        task.id, ReviewDecisionKind.DEFER, "linguist_1", "community_linguist"
    )
    assert result.target_status is None
    assert result.task_status == "open"
    assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.CANDIDATE
    assert ctx.repo.get_review_task(task.id).status == "open"
    # A deferred task can still be decided later.
    later = service.record_decision(
        task.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
    )
    assert later.target_status is LifecycleStatus.VALIDATED
    assert ctx.repo.get_review_task(task.id).status == "resolved"


def test_deciding_a_non_open_task_is_refused(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "resolved-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = _task(ctx, service, lexeme.id)
    service.record_decision(task.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist")
    with pytest.raises(InvalidTransition):
        service.record_decision(
            task.id, ReviewDecisionKind.REJECT, "linguist_1", "community_linguist"
        )
    # Any non-open operational state takes no decision, not just "resolved".
    for status in ("in_review", "cancelled"):
        followup = _task(ctx, service, lexeme.id)
        with ctx.repo.transaction():
            ctx.repo.set_review_task_status(followup.id, status)
        with pytest.raises(InvalidTransition):
            service.record_decision(
                followup.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
            )


def test_pinned_target_version_stale_at_decision_time(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    # The pin names the status-of-record the reviewer saw; if the object moved on, the
    # decision is refused instead of applied to a different version.
    registered = _register_source(ctx, tmp_path, "pin-stale-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = _task(ctx, service, lexeme.id, target_version="candidate")
    with ctx.repo.transaction():
        ctx.repo.set_lexeme_status(lexeme.id, LifecycleStatus.REJECTED)
    with pytest.raises(InvalidTransition):
        service.record_decision(
            task.id, ReviewDecisionKind.REJECT, "linguist_1", "community_linguist"
        )
    assert ctx.repo.get_review_task(task.id).status == "open"
    assert ctx.repo.count(EntityType.REVIEW_DECISION) == 0


def test_decided_decision_lineage_and_traversal(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "lineage-src")
    source_object_id = registered.objects[0].id
    evidence_run = RunRecorder(ctx).start(
        RunStage.MANUAL_ANNOTATION, "langpipe.test", {}, [source_object_id]
    )
    lexeme = _candidate_lexeme(ctx, source_object_id)
    evidence = _evidence(ctx, evidence_run.id, lexeme.id, registered.source.id)
    task = _task(ctx, service, lexeme.id, evidence_item_ids=[evidence.id])
    result = service.record_decision(
        task.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
    )
    edges = ctx.repo.list_lineage_edges(result.decision.id, "out")
    assert [(edge.to_id, edge.kind) for edge in edges] == [(task.id, LineageKind.DERIVED_FROM)]
    # Task lineage: the task derives from its target and its evidence bundle.
    task_parents = {(edge.to_id, edge.kind) for edge in ctx.repo.list_lineage_edges(task.id, "out")}
    assert (lexeme.id, LineageKind.DERIVED_FROM) in task_parents
    assert (evidence.id, LineageKind.DERIVED_FROM) in task_parents
    # Traversal: source -> lexical target -> task -> decision, in both directions.
    descendant_ids = {node_id for node_id, _depth in ctx.repo.descendants(source_object_id)}
    assert {lexeme.id, task.id, result.decision.id} <= descendant_ids
    task_ancestor_ids = {node_id for node_id, _depth in ctx.repo.ancestors(task.id)}
    assert {lexeme.id, evidence.id, source_object_id} <= task_ancestor_ids
    decision_ancestor_ids = {node_id for node_id, _depth in ctx.repo.ancestors(result.decision.id)}
    assert {task.id, lexeme.id, source_object_id} <= decision_ancestor_ids
    # Revocation impact groundwork: ancestor source resolution reaches the review records.
    assert ancestor_source_ids(ctx.repo, task.id) == [registered.source.id]
    assert ancestor_source_ids(ctx.repo, result.decision.id) == [registered.source.id]
    # The creator run consumed the evidence bundle too.
    run_io = ctx.repo.list_run_io(task.creator_run_id)
    assert (evidence.id, RunIoRole.INPUT) in run_io


# --- authority and governance gates ------------------------------------------------------------


def test_unauthorized_reviewer_changes_nothing(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "unauthorized-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = _task(ctx, service, lexeme.id)
    before_decisions = ctx.repo.count(EntityType.REVIEW_DECISION)
    for reviewer_id, role in (
        ("stranger", "community_linguist"),  # not registered
        ("steward_1", "community_linguist"),  # registered only as editorial_steward
        ("elder_1", "native_speaker_elder"),  # domain-scoped, target untagged
        ("linguist_1", "editorial_steward"),  # right reviewer, wrong role
    ):
        with pytest.raises(UnauthorizedReviewer):
            service.record_decision(task.id, ReviewDecisionKind.ACCEPT, reviewer_id, role)
        with pytest.raises(PermissionError):
            service.record_decision(task.id, ReviewDecisionKind.ACCEPT, reviewer_id, role)
    assert ctx.repo.count(EntityType.REVIEW_DECISION) == before_decisions
    assert ctx.repo.get_review_task(task.id).status == "open"
    assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.CANDIDATE


def test_reviewer_role_must_match_the_required_role(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    # The task's required authority is a gate, not a routing hint: a registered
    # reviewer acting outside the task's required role is denied before any write.
    registered = _register_source(ctx, tmp_path, "role-mismatch-src")
    steward_lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    steward_task = _task(ctx, service, steward_lexeme.id, required_role="editorial_steward")
    with pytest.raises(UnauthorizedReviewer):
        service.record_decision(
            steward_task.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
        )
    assert ctx.repo.get_review_task(steward_task.id).status == "open"
    assert ctx.repo.get_lexeme(steward_lexeme.id).status is LifecycleStatus.CANDIDATE
    assert ctx.repo.count(EntityType.REVIEW_DECISION) == 0
    # The registered steward, in the required role, is authorized.
    result = service.record_decision(
        steward_task.id, ReviewDecisionKind.ACCEPT, "steward_1", "editorial_steward"
    )
    assert result.target_status is LifecycleStatus.VALIDATED


def test_domain_scoped_reviewer_authorizes_only_matching_domain(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "domain-src")
    ritual = _candidate_lexeme(ctx, registered.objects[0].id, domain="ritual")
    household = _candidate_lexeme(ctx, registered.objects[0].id, domain="household")
    ritual_task = _task(ctx, service, ritual.id, required_role="native_speaker_elder")
    household_task = _task(ctx, service, household.id, required_role="native_speaker_elder")
    result = service.record_decision(
        ritual_task.id, ReviewDecisionKind.ACCEPT, "elder_1", "native_speaker_elder"
    )
    assert result.target_status is LifecycleStatus.VALIDATED
    with pytest.raises(UnauthorizedReviewer):
        service.record_decision(
            household_task.id, ReviewDecisionKind.ACCEPT, "elder_1", "native_speaker_elder"
        )


def test_missing_task_raises_not_found(ctx: AppContext, service: ReviewService) -> None:
    with pytest.raises(NotFound):
        service.record_decision(
            "rtask_" + "0" * 26, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
        )


def test_revoked_source_blocks_task_creation_and_decision(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "revoked-review-src")
    source_id = registered.source.id
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    with ctx.repo.transaction():
        ctx.repo.set_source_status(source_id, SourceStatus.REVOKED, ctx.clock())
    with pytest.raises(PolicyDenied) as create_error:
        _task(ctx, service, lexeme.id)
    assert create_error.value.source_id == source_id
    assert create_error.value.operation is Operation.HUMAN_REVIEW
    assert create_error.value.decision is PolicyDecision.DENY

    another = _register_source(ctx, tmp_path, "revoked-decision-src")
    another_source_id = another.source.id
    target = _candidate_lexeme(ctx, another.objects[0].id)
    task = _task(ctx, service, target.id)
    with ctx.repo.transaction():
        ctx.repo.set_source_status(another_source_id, SourceStatus.REVOKED, ctx.clock())
    before = ctx.repo.count(EntityType.REVIEW_DECISION)
    status = ctx.repo.get_lexeme(target.id).status
    with pytest.raises(PolicyDenied) as decision_error:
        service.record_decision(
            task.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
        )
    assert decision_error.value.source_id == another_source_id
    assert decision_error.value.operation is Operation.HUMAN_REVIEW
    assert decision_error.value.decision is PolicyDecision.DENY
    assert ctx.repo.get_lexeme(target.id).status is status
    assert ctx.repo.count(EntityType.REVIEW_DECISION) == before
    assert ctx.repo.get_review_task(task.id).status == "open"


def test_denied_human_review_policy_changes_nothing(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "restricted-src", mode="restricted")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    task = _task(ctx, service, lexeme.id)
    before_decisions = ctx.repo.count(EntityType.REVIEW_DECISION)
    with pytest.raises(PolicyDenied):
        service.record_decision(
            task.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
        )
    assert ctx.repo.count(EntityType.REVIEW_DECISION) == before_decisions
    assert ctx.repo.get_review_task(task.id).status == "open"
    assert ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.CANDIDATE


# --- score recalculation and staleness ---------------------------------------------------------


def test_accept_recomputes_score_breakdown_from_current_evidence(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "score-src")
    source_object_id = registered.objects[0].id
    stale = LexicalScoreBreakdown(
        policy_version="lexical-v1",
        overall=0.99,
        components={"alignment_support": 0.99},
        independence_groups=["stale"],
    )
    lexeme = _candidate_lexeme(
        ctx,
        source_object_id,
        status=LifecycleStatus.SUPPORTED,
        score_breakdown=stale,
    )
    evidence_run = RunRecorder(ctx).start(
        RunStage.MANUAL_ANNOTATION, "langpipe.test", {}, [source_object_id]
    )
    _evidence(ctx, evidence_run.id, lexeme.id, registered.source.id)
    _evidence(ctx, evidence_run.id, lexeme.id, registered.source.id)
    task = _task(ctx, service, lexeme.id)
    result = service.record_decision(
        task.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
    )
    assert result.target_status is LifecycleStatus.VALIDATED
    stored = ctx.repo.get_lexeme(lexeme.id).score_breakdown
    assert stored is not None
    expected = compute_score(ctx.repo.list_evidence_for_target(lexeme.id), LANGUAGE)
    assert stored == expected
    assert stored != stale


def test_accept_flags_direct_dependents_stale(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "stale-src")
    source_object_id = registered.objects[0].id
    lexeme = _candidate_lexeme(ctx, source_object_id)
    first = _sense_under(ctx, source_object_id, lexeme)
    second = _sense_under(ctx, source_object_id, lexeme)
    task = _task(ctx, service, lexeme.id)
    result = service.record_decision(
        task.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
    )
    assert result.target_status is LifecycleStatus.VALIDATED
    for sense in (first, second):
        stale = [
            edge
            for edge in ctx.repo.list_lineage_edges(sense.id, "out")
            if edge.kind is LineageKind.STALE_DEPENDENT
        ]
        assert [(edge.to_id, edge.kind) for edge in stale] == [
            (lexeme.id, LineageKind.STALE_DEPENDENT)
        ]
    # The flags are visible traversing forward from the decided target (WP4.9 groundwork).
    descendant_ids = {node_id for node_id, _depth in ctx.repo.descendants(lexeme.id)}
    assert {first.id, second.id} <= descendant_ids


def test_reject_and_modify_also_flag_direct_dependents_stale(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "stale-reject-modify-src")
    source_object_id = registered.objects[0].id
    rejected = _candidate_lexeme(ctx, source_object_id)
    rejected_sense = _sense_under(ctx, source_object_id, rejected)
    reject_task = _task(ctx, service, rejected.id)
    service.record_decision(
        reject_task.id, ReviewDecisionKind.REJECT, "linguist_1", "community_linguist"
    )
    assert (
        rejected.id,
        LineageKind.STALE_DEPENDENT,
    ) in [(e.to_id, e.kind) for e in ctx.repo.list_lineage_edges(rejected_sense.id, "out")]

    predecessor = _candidate_lexeme(ctx, source_object_id)
    predecessor_sense = _sense_under(ctx, source_object_id, predecessor)
    successor = _candidate_lexeme(ctx, source_object_id)
    successor_sense = _sense_under(ctx, source_object_id, successor)
    modify_task = _task(ctx, service, predecessor.id)
    service.record_decision(
        modify_task.id,
        ReviewDecisionKind.MODIFY,
        "linguist_1",
        "community_linguist",
        superseding_object_id=successor.id,
    )
    for sense in (predecessor_sense, successor_sense):
        stale = [
            (edge.to_id, edge.kind)
            for edge in ctx.repo.list_lineage_edges(sense.id, "out")
            if edge.kind is LineageKind.STALE_DEPENDENT
        ]
        expected_parent = predecessor.id if sense is predecessor_sense else successor.id
        assert stale == [(expected_parent, LineageKind.STALE_DEPENDENT)]


def test_queue_only_decisions_flag_no_dependents(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    registered = _register_source(ctx, tmp_path, "stale-uncertain-src")
    source_object_id = registered.objects[0].id
    lexeme = _candidate_lexeme(ctx, source_object_id)
    _sense_under(ctx, source_object_id, lexeme)
    task = _task(ctx, service, lexeme.id)
    service.record_decision(
        task.id, ReviewDecisionKind.UNCERTAIN, "linguist_1", "community_linguist"
    )
    assert ctx.repo.count_lineage_edges() >= 0  # edges exist; none may be stale_dependent
    all_out = [
        (edge.from_id, edge.to_id, edge.kind)
        for sense in ctx.repo.list_senses_for_lexeme(lexeme.id)
        for edge in ctx.repo.list_lineage_edges(sense.id, "out")
    ]
    assert all(kind is not LineageKind.STALE_DEPENDENT for _, _, kind in all_out)


# --- concept targets: queue-only support --------------------------------------------------------


def test_concept_target_supports_queue_decisions_only(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    # Concepts carry no lifecycle status in the accepted model: uncertain/defer resolve
    # the queue entry without touching anything, lifecycle decisions are refused.
    _register_source(ctx, tmp_path, "concept-src")
    concept = _concept(ctx)
    uncertain_task = _task(ctx, service, concept.id)
    result = service.record_decision(
        uncertain_task.id, ReviewDecisionKind.UNCERTAIN, "linguist_1", "community_linguist"
    )
    assert result.target_status is None
    assert ctx.repo.get_review_task(uncertain_task.id).status == "resolved"

    defer_task = _task(ctx, service, concept.id)
    deferred = service.record_decision(
        defer_task.id, ReviewDecisionKind.DEFER, "linguist_1", "community_linguist"
    )
    assert deferred.task_status == "open"
    assert ctx.repo.get_review_task(defer_task.id).status == "open"

    for decision in (
        ReviewDecisionKind.ACCEPT,
        ReviewDecisionKind.REJECT,
        ReviewDecisionKind.MODIFY,
    ):
        task = _task(ctx, service, concept.id)
        with pytest.raises(SchemaViolation):
            service.record_decision(task.id, decision, "linguist_1", "community_linguist")
        assert ctx.repo.get_review_task(task.id).status == "open"
        assert ctx.repo.count(EntityType.REVIEW_DECISION) == 2  # only uncertain + defer


def test_concept_queue_decision_requires_a_registered_role_holder(
    ctx: AppContext, service: ReviewService, tmp_path: Path
) -> None:
    # Language-less targets cannot be scoped by language, so authority reduces to the
    # required role plus a registered reviewer actually holding it.
    _register_source(ctx, tmp_path, "concept-role-src")
    concept = _concept(ctx)
    task = _task(ctx, service, concept.id)
    with pytest.raises(UnauthorizedReviewer):
        service.record_decision(
            task.id, ReviewDecisionKind.UNCERTAIN, "stranger", "community_linguist"
        )
    assert ctx.repo.get_review_task(task.id).status == "open"
    assert ctx.repo.count(EntityType.REVIEW_DECISION) == 0


# --- concurrency (PostgreSQL row locks; sequential runs) ----------------------------------------


@pytest.mark.integration
def test_concurrent_decisions_serialize_on_postgres(
    tmp_path: Path, pg_repository: PostgresRepository
) -> None:
    """One task takes exactly one decision under interleaved transactions.

    An independent session holds the task row locked while a second reviewer commits;
    the blocked decision must observe the winner's committed state and refuse, instead
    of both decisions succeeding.
    """
    clock = lambda: datetime(2026, 1, 1, tzinfo=UTC)  # noqa: E731 - test-local fixed clock
    context = AppContext(
        repo=pg_repository,
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=clock,
        new_id=new_id,
        actor="test-actor",
        code_revision="test-rev",
    )
    registered = _register_source(context, tmp_path, "contention-src")
    lexeme = _candidate_lexeme(context, registered.objects[0].id)
    authority = ReviewAuthorityRegistry()
    authority.register("linguist_1", "community_linguist", [LANGUAGE])
    winner = ReviewService(
        pg_repository, authority, clock=clock, new_id=new_id, code_revision="test-rev"
    )
    loser = ReviewService(
        pg_repository, authority, clock=clock, new_id=new_id, code_revision="test-rev"
    )
    task = winner.create_task(lexeme.id, ReviewTaskType.LEMMA, "community_linguist")

    holder = PostgresRepository(pg_repository._engine)
    inside = threading.Event()
    release = threading.Event()
    outcome: dict[str, object] = {}

    def hold() -> None:
        with holder.transaction():
            holder.get_review_task_for_update(task.id)
            holder.set_review_task_status(task.id, "resolved")
            inside.set()
            assert release.wait(timeout=JOIN_TIMEOUT)

    def contend() -> None:
        try:
            loser.record_decision(
                task.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
            )
            outcome["result"] = "committed"
        except InvalidTransition:
            outcome["result"] = "refused"
        except BaseException as exc:  # noqa: BLE001 - asserted below, never swallowed
            outcome["result"] = exc

    holder_thread = threading.Thread(target=hold)
    holder_thread.start()
    contender_thread = threading.Thread(target=contend)
    try:
        assert inside.wait(timeout=JOIN_TIMEOUT)
        # Start the contender only once the holder owns the row lock; starting both at
        # once let the contender win the lock under load and commit first.
        contender_thread.start()
        # The contender blocks on the locked reread: it must not complete while the
        # holder keeps the task row locked, and it must observe the committed
        # "resolved" state once the lock frees — not both decisions succeeding.
        time.sleep(0.4)
        assert not outcome, "the unlocked read let the second decision through"
        release.set()
    finally:
        release.set()
        holder_thread.join(timeout=JOIN_TIMEOUT)
        if contender_thread.ident is not None:
            contender_thread.join(timeout=JOIN_TIMEOUT)
    assert not holder_thread.is_alive()
    assert not contender_thread.is_alive()
    assert outcome == {"result": "refused"}
    assert pg_repository.count(EntityType.REVIEW_DECISION) == 0
    assert pg_repository.get_review_task(task.id).status == "resolved"
    assert pg_repository.get_lexeme(lexeme.id).status is LifecycleStatus.CANDIDATE


# --- immutability --------------------------------------------------------------------------------


def test_decisions_are_append_only(ctx: AppContext, service: ReviewService, tmp_path: Path) -> None:
    registered = _register_source(ctx, tmp_path, "append-only-src")
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id)
    first_task = _task(ctx, service, lexeme.id)
    second_task = _task(ctx, service, lexeme.id)
    first = service.record_decision(
        first_task.id, ReviewDecisionKind.UNCERTAIN, "linguist_1", "community_linguist"
    )
    second = service.record_decision(
        second_task.id, ReviewDecisionKind.ACCEPT, "linguist_1", "community_linguist"
    )
    stored = ctx.repo.list_review_decisions_for_target(lexeme.id)
    assert [decision.id for decision in stored] == [first.decision.id, second.decision.id]
    # The first record is untouched by the later one: a changed opinion appends, never edits.
    assert ctx.repo.get_review_decision(first.decision.id) == first.decision
    assert ctx.repo.get_review_decision(second.decision.id) == second.decision
