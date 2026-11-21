"""Shared Repository contract for M4 lexical evidence and the review queue (WP4.3, ADR-0013).

Runs once per backend via `repo_backend` (in-memory and PostgreSQL). Both backends agree on
the relational contract: object-registry bookkeeping, foreign-key parents, the unique
`(form_id, lexeme_id)` pair, ordered listings, atomic status updates and the transaction guard.
Data is synthetic: identifiers and placeholder labels only, never source content.
"""

import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from langpipe.domain.enums import (
    EntityType,
    LifecycleStatus,
    ReviewTaskType,
    RunStage,
    RunStatus,
)
from langpipe.domain.errors import ImmutableViolation, InvalidLineage, NotFound, SchemaViolation
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.lexical import (
    Concept,
    FormLexemeLink,
    Lexeme,
    LexicalScoreBreakdown,
    Sense,
)
from langpipe.domain.models.review import ReviewDecision, ReviewTask
from langpipe.domain.models.run import ProcessingRun
from langpipe.storage.repository import Repository
from tests.contract.builders import NOW, make_evidence, make_form, make_run, unique_run_key

BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_KEYS = itertools.count()


def _at(seconds: int) -> datetime:
    """Distinct deterministic created_at values, so ordering assertions are exact."""
    return BASE + timedelta(seconds=seconds)


def _fixed_id(prefix: str, discriminator: str) -> str:
    """A syntactically valid identifier with a caller-chosen ULID body (identical backend rows)."""
    assert len(discriminator) == 1 and discriminator.isdigit()
    return f"{prefix}_{discriminator}{('0' * 25)}"


@dataclass
class LexicalWorld:
    """Committed substrate: one lexical induction run plus the lexical and review entities."""

    run: ProcessingRun
    form_id: str
    concept: Concept
    lexeme_mzr: Lexeme
    lexeme_por: Lexeme
    primary_link: FormLexemeLink
    variant_link: FormLexemeLink
    evidence_id: str
    sense_mzr: Sense
    sense_por: Sense
    high_priority_task: ReviewTask
    low_priority_task: ReviewTask
    in_review_task: ReviewTask
    decision: ReviewDecision


def _lexeme(language: str, run_id: str, index: int, **overrides: object) -> Lexeme:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.LEXEME),
        "language": language,
        "run_id": run_id,
        "created_at": _at(index),
    }
    values.update(overrides)
    return Lexeme(**values)  # type: ignore[arg-type]


def _sense(lexeme_id: str, run_id: str, index: int, **overrides: object) -> Sense:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.SENSE),
        "lexeme_id": lexeme_id,
        "run_id": run_id,
        "created_at": _at(index),
    }
    values.update(overrides)
    return Sense(**values)  # type: ignore[arg-type]


def _link(
    form_id: str, lexeme_id: str, run_id: str, index: int, **overrides: object
) -> FormLexemeLink:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.FORM_LEXEME),
        "form_id": form_id,
        "lexeme_id": lexeme_id,
        "run_id": run_id,
        "created_at": _at(index),
    }
    values.update(overrides)
    return FormLexemeLink(**values)  # type: ignore[arg-type]


def _task(
    target_id: str,
    run_id: str,
    index: int,
    priority: float,
    required_role: str,
    task_id: str,
    **overrides: object,
) -> ReviewTask:
    values: dict[str, object] = {
        "id": task_id,
        "task_type": ReviewTaskType.LEXICAL_SENSE,
        "target_id": target_id,
        "required_role": required_role,
        "priority": priority,
        "reason": "synthetic review request",
        "creator_run_id": run_id,
        "created_at": _at(index),
    }
    values.update(overrides)
    return ReviewTask(**values)  # type: ignore[arg-type]


def _lexical_world(repo: Repository) -> LexicalWorld:
    run = make_run(
        stage=RunStage.LEXICAL_INDUCTION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"lex-{next(_KEYS)}"),
    )
    # One orthographic form backs two lexemes: ambiguity is preserved relationally (ADR-0013 §1).
    form = make_form(run, text="mabi")
    concept = Concept(
        id=new_id(IdPrefix.CONCEPT),
        canonical_label="canoa",
        concepticon_id="1642",
        run_id=run.id,
        created_at=_at(1),
    )
    lexeme_mzr = _lexeme("mzr", run.id, 2, lemma_form_id=form.id, pos="noun", domain="ritual")
    lexeme_por = _lexeme("por", run.id, 3)
    primary_link = _link(form.id, lexeme_mzr.id, run.id, 4, role="primary_lemma")
    variant_link = _link(form.id, lexeme_por.id, run.id, 5, role="variant")
    sense_mzr = _sense(
        lexeme_mzr.id, run.id, 6, glosses={"por": ["canoa", "barco"]}, concept_id=concept.id
    )
    sense_por = _sense(lexeme_por.id, run.id, 7, glosses={"spa": ["bote"]})
    evidence = make_evidence(lexeme_mzr.id, run)
    high_priority_task = _task(
        lexeme_mzr.id,
        run.id,
        8,
        5.0,
        "community_linguist",
        _fixed_id(IdPrefix.REVIEW_TASK.value, "1"),
        task_type=ReviewTaskType.REGISTER_DOMAIN,
        evidence_item_ids=[evidence.id],
        target_version="1",
    )
    low_priority_task = _task(
        sense_mzr.id,
        run.id,
        9,
        1.0,
        "native_speaker_elder",
        _fixed_id(IdPrefix.REVIEW_TASK.value, "2"),
    )
    in_review_task = _task(
        sense_por.id,
        run.id,
        10,
        3.0,
        "community_linguist",
        _fixed_id(IdPrefix.REVIEW_TASK.value, "3"),
        status="in_review",
    )
    decision = ReviewDecision(
        id=new_id(IdPrefix.REVIEW_DECISION),
        task_id=low_priority_task.id,
        target_id=sense_mzr.id,
        decision="accept",
        reviewer_id="reviewer-1",
        reviewer_role="native_speaker_elder",
        notes="synthetic decision note",
        created_at=_at(12),
    )
    with repo.transaction():
        repo.add_run(run)
        repo.get_or_create_form(form)
        repo.add_concept(concept)
        repo.add_lexeme(lexeme_mzr)
        repo.add_lexeme(lexeme_por)
        repo.add_form_lexeme_link(primary_link)
        repo.add_form_lexeme_link(variant_link)
        repo.add_sense(sense_mzr)
        repo.add_sense(sense_por)
        repo.add_evidence(evidence)
        repo.add_review_task(high_priority_task)
        repo.add_review_task(low_priority_task)
        repo.add_review_task(in_review_task)
        repo.add_review_decision(decision)
    return LexicalWorld(
        run=run,
        form_id=form.id,
        concept=concept,
        lexeme_mzr=lexeme_mzr,
        lexeme_por=lexeme_por,
        primary_link=primary_link,
        variant_link=variant_link,
        evidence_id=evidence.id,
        sense_mzr=sense_mzr,
        sense_por=sense_por,
        high_priority_task=high_priority_task,
        low_priority_task=low_priority_task,
        in_review_task=in_review_task,
        decision=decision,
    )


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def repo_backend(request: pytest.FixtureRequest) -> Iterator[Repository]:
    if request.param == "memory":
        from langpipe.storage.memory import InMemoryRepository

        yield InMemoryRepository()
        return
    yield request.getfixturevalue("pg_repository")


@pytest.fixture
def world(repo_backend: Repository) -> LexicalWorld:
    return _lexical_world(repo_backend)


# --- transaction guard ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda repo, world: repo.add_concept(world.concept),
        lambda repo, world: repo.add_lexeme(world.lexeme_mzr),
        lambda repo, world: repo.add_form_lexeme_link(world.primary_link),
        lambda repo, world: repo.add_sense(world.sense_mzr),
        lambda repo, world: repo.add_review_task(world.high_priority_task),
        lambda repo, world: repo.add_review_decision(world.decision),
        lambda repo, world: repo.set_lexeme_status(world.lexeme_mzr.id, LifecycleStatus.SUPPORTED),
        lambda repo, world: repo.set_sense_status(world.sense_mzr.id, LifecycleStatus.REJECTED),
        lambda repo, world: repo.set_review_task_status(world.high_priority_task.id, "in_review"),
    ],
)
def test_lexical_write_requires_transaction(repo_backend: Repository, call: object) -> None:
    committed = _lexical_world(repo_backend)
    with pytest.raises(RuntimeError, match="write outside transaction"):
        call(repo_backend, committed)  # type: ignore[operator]


# --- lifecycle roundtrip -----------------------------------------------------------------------


def test_lexical_round_trip(repo_backend: Repository) -> None:
    world = _lexical_world(repo_backend)

    assert repo_backend.get_concept(world.concept.id) == world.concept
    assert repo_backend.get_lexeme(world.lexeme_mzr.id) == world.lexeme_mzr
    assert repo_backend.get_sense(world.sense_mzr.id) == world.sense_mzr
    assert repo_backend.get_review_task(world.high_priority_task.id) == world.high_priority_task
    assert repo_backend.get_review_decision(world.decision.id) == world.decision
    # Links are read through their two indexes; both sides of the join round-trip.
    assert repo_backend.list_form_lexeme_links_for_form(world.form_id) == [
        world.primary_link,
        world.variant_link,
    ]
    assert repo_backend.list_form_lexeme_links_for_lexeme(world.lexeme_mzr.id) == [
        world.primary_link
    ]


def test_not_found_for_unknown_identifiers(repo_backend: Repository) -> None:
    _lexical_world(repo_backend)
    with pytest.raises(NotFound):
        repo_backend.get_concept(new_id(IdPrefix.CONCEPT))
    with pytest.raises(NotFound):
        repo_backend.get_lexeme(new_id(IdPrefix.LEXEME))
    with pytest.raises(NotFound):
        repo_backend.get_sense(new_id(IdPrefix.SENSE))
    with pytest.raises(NotFound):
        repo_backend.get_review_task(new_id(IdPrefix.REVIEW_TASK))
    with pytest.raises(NotFound):
        repo_backend.get_review_decision(new_id(IdPrefix.REVIEW_DECISION))
    assert repo_backend.list_lexemes_by_language("spa") == []
    assert repo_backend.list_lexemes_by_form(new_id(IdPrefix.FORM)) == []
    assert repo_backend.list_senses_for_lexeme(new_id(IdPrefix.LEXEME)) == []
    assert repo_backend.list_form_lexeme_links_for_form(new_id(IdPrefix.FORM)) == []
    assert repo_backend.list_form_lexeme_links_for_lexeme(new_id(IdPrefix.LEXEME)) == []
    assert repo_backend.list_review_decisions_for_target(new_id(IdPrefix.SENSE)) == []
    assert repo_backend.list_review_tasks(required_role="no_such_role") == []


# --- filtered and ordered listings --------------------------------------------------------------


def test_listings_are_ordered_and_filtered(repo_backend: Repository) -> None:
    world = _lexical_world(repo_backend)

    assert repo_backend.list_concepts() == [world.concept]
    assert repo_backend.list_lexemes_by_language("mzr") == [world.lexeme_mzr]
    assert repo_backend.list_lexemes_by_language("por") == [world.lexeme_por]
    assert repo_backend.list_senses_for_lexeme(world.lexeme_mzr.id) == [world.sense_mzr]
    assert repo_backend.list_senses_for_lexeme(world.lexeme_por.id) == [world.sense_por]
    # One form backs two lexemes, so both directions of the join are needed.
    assert [link.id for link in repo_backend.list_form_lexeme_links_for_form(world.form_id)] == [
        world.primary_link.id,
        world.variant_link.id,
    ]
    assert repo_backend.list_review_decisions_for_target(world.sense_mzr.id) == [world.decision]


def test_list_lexemes_by_form_resolves_the_relational_join(repo_backend: Repository) -> None:
    world = _lexical_world(repo_backend)

    # Ambiguity is preserved: one form resolves to every linked lexeme, not one of them.
    assert repo_backend.list_lexemes_by_form(world.form_id) == [
        world.lexeme_mzr,
        world.lexeme_por,
    ]
    # Unrelated lexemes stay excluded even though they share the language.
    assert repo_backend.list_lexemes_by_form(world.form_id) != [world.lexeme_mzr]
    assert repo_backend.list_lexemes_by_form(world.form_id) != [world.lexeme_por]


def test_list_lexemes_by_form_includes_non_lemma_links(repo_backend: Repository) -> None:
    world = _lexical_world(repo_backend)
    # The variant link carries no lemma: `lemma_form_id` alone cannot resolve it.
    assert world.lexeme_por.lemma_form_id is None
    assert repo_backend.list_form_lexeme_links_for_form(world.form_id)[1].role == "variant"
    assert world.lexeme_por in repo_backend.list_lexemes_by_form(world.form_id)


def test_list_lexemes_by_form_missing_or_unlinked_returns_empty(repo_backend: Repository) -> None:
    _lexical_world(repo_backend)

    assert repo_backend.list_lexemes_by_form(new_id(IdPrefix.FORM)) == []
    # The second form exists but links to no lexeme.
    run = make_run(
        stage=RunStage.LEXICAL_INDUCTION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"orphan-form-{next(_KEYS)}"),
    )
    orphan_form = make_form(run, text="orphan")
    with repo_backend.transaction():
        repo_backend.add_run(run)
        repo_backend.get_or_create_form(orphan_form)
    assert repo_backend.list_lexemes_by_form(orphan_form.id) == []


def test_list_lexemes_by_form_ordered_by_created_then_id(repo_backend: Repository) -> None:
    run = make_run(
        stage=RunStage.LEXICAL_INDUCTION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"form-order-{next(_KEYS)}"),
    )
    form = make_form(run, text="ambiguity")
    later = _lexeme(
        "mzr", run.id, 132, lemma_form_id=form.id, id=_fixed_id(IdPrefix.LEXEME.value, "9")
    )
    before_it = _lexeme(
        "mzr", run.id, 131, lemma_form_id=form.id, id=_fixed_id(IdPrefix.LEXEME.value, "5")
    )
    with repo_backend.transaction():
        repo_backend.add_run(run)
        repo_backend.get_or_create_form(form)
        repo_backend.add_lexeme(before_it)
        repo_backend.add_lexeme(later)
        # Only the non-lemma link makes the earlier-created lexeme reachable by this form.
        repo_backend.add_form_lexeme_link(_link(form.id, before_it.id, run.id, 133, role="variant"))
        repo_backend.add_form_lexeme_link(
            _link(form.id, later.id, run.id, 134, role="primary_lemma")
        )

    # Insertion order decides nothing: (created_at, id) governs, never insertion sequence.
    assert repo_backend.list_lexemes_by_form(form.id) == [before_it, later]


def test_list_lexemes_by_form_returns_defensive_copies(repo_backend: Repository) -> None:
    world = _lexical_world(repo_backend)
    breakdown = LexicalScoreBreakdown(
        policy_version="lexical-v1",
        overall=0.25,
        components={"alignment_support": 1.0},
        penalties={},
        independence_groups=["alignment"],
    )
    with repo_backend.transaction():
        repo_backend.set_lexeme_status(world.lexeme_mzr.id, LifecycleStatus.SUPPORTED, breakdown)

    listed = repo_backend.list_lexemes_by_form(world.form_id)
    # Mutating a nested structure of a returned copy must not reach the stored row.
    listed[0].score_breakdown.components["injected"] = 0.0

    stored = repo_backend.get_lexeme(world.lexeme_mzr.id)
    assert stored.score_breakdown is not None
    assert "injected" not in stored.score_breakdown.components
    assert (
        "injected"
        not in repo_backend.list_lexemes_by_form(world.form_id)[0].score_breakdown.components
    )


def test_active_review_tasks_priority_order_and_filters(repo_backend: Repository) -> None:
    world = _lexical_world(repo_backend)

    # Open tasks only, ordered by descending priority: 5.0 then 1.0; in_review (3.0) excluded.
    active = repo_backend.list_review_tasks()
    assert [task.id for task in active] == [
        world.high_priority_task.id,
        world.low_priority_task.id,
    ]
    assert repo_backend.list_review_tasks(required_role="community_linguist") == [
        world.high_priority_task
    ]
    assert repo_backend.list_review_tasks(task_type=ReviewTaskType.LEXICAL_SENSE) == [
        world.low_priority_task
    ]
    assert repo_backend.list_review_tasks(task_type=ReviewTaskType.LEMMA) == []
    # Combined filters intersect.
    assert repo_backend.list_review_tasks(
        task_type=ReviewTaskType.REGISTER_DOMAIN, required_role="community_linguist"
    ) == [world.high_priority_task]
    assert (
        repo_backend.list_review_tasks(
            task_type=ReviewTaskType.REGISTER_DOMAIN, required_role="native_speaker_elder"
        )
        == []
    )


def test_active_review_tasks_break_created_at_tie(repo_backend: Repository) -> None:
    run = make_run(
        stage=RunStage.HUMAN_REVIEW,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"tie-{next(_KEYS)}"),
    )
    target = new_id(IdPrefix.LEXEME)
    early = _task(
        target,
        run.id,
        20,
        2.0,
        "community_linguist",
        _fixed_id(IdPrefix.REVIEW_TASK.value, "9"),
    )
    late = _task(
        target,
        run.id,
        21,
        2.0,
        "community_linguist",
        _fixed_id(IdPrefix.REVIEW_TASK.value, "1"),
    )
    with repo_backend.transaction():
        repo_backend.add_run(run)
        repo_backend.add_lexeme(_lexeme("mzr", run.id, 19, id=target))
        repo_backend.add_review_task(late)
        repo_backend.add_review_task(early)

    # Same priority: the earlier created_at wins, so insertion order never decides.
    assert [task.id for task in repo_backend.list_review_tasks()] == [early.id, late.id]


def test_active_review_tasks_break_id_tie(repo_backend: Repository) -> None:
    run = make_run(
        stage=RunStage.HUMAN_REVIEW,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"id-tie-{next(_KEYS)}"),
    )
    target = new_id(IdPrefix.LEXEME)
    second = _task(
        target, run.id, 30, 4.0, "community_linguist", _fixed_id(IdPrefix.REVIEW_TASK.value, "2")
    )
    first = _task(
        target, run.id, 30, 4.0, "community_linguist", _fixed_id(IdPrefix.REVIEW_TASK.value, "1")
    )
    with repo_backend.transaction():
        repo_backend.add_run(run)
        repo_backend.add_lexeme(_lexeme("mzr", run.id, 29, id=target))
        repo_backend.add_review_task(second)
        repo_backend.add_review_task(first)

    assert [task.id for task in repo_backend.list_review_tasks()] == [first.id, second.id]


# --- status updates -----------------------------------------------------------------------------


def test_status_updates_are_atomic_and_returned(repo_backend: Repository) -> None:
    world = _lexical_world(repo_backend)
    breakdown = LexicalScoreBreakdown(
        policy_version="lexical-v1",
        overall=0.75,
        components={"alignment_support": 0.9, "source_diversity": 0.6},
        penalties={"formulaic_source": 0.05},
        independence_groups=["wordlist", "alignment"],
    )

    with repo_backend.transaction():
        lexeme = repo_backend.set_lexeme_status(
            world.lexeme_mzr.id, LifecycleStatus.SUPPORTED, breakdown
        )
        assert lexeme.status is LifecycleStatus.SUPPORTED
        assert lexeme.score_breakdown == breakdown
        # Visible inside the open transaction...
        assert repo_backend.get_lexeme(world.lexeme_mzr.id) == lexeme

        sense = repo_backend.set_sense_status(
            world.sense_mzr.id, LifecycleStatus.REJECTED, breakdown
        )
        assert sense.status is LifecycleStatus.REJECTED
        assert sense.score_breakdown == breakdown

        task = repo_backend.set_review_task_status(world.low_priority_task.id, "resolved")
        assert task.status == "resolved"

    # ...and committed after it.
    assert repo_backend.get_lexeme(world.lexeme_mzr.id) == lexeme
    assert repo_backend.get_sense(world.sense_mzr.id) == sense
    assert repo_backend.get_review_task(world.low_priority_task.id) == task
    # A resolved task leaves the active queue.
    assert repo_backend.list_review_tasks() == [world.high_priority_task]


def test_status_update_without_breakdown_keeps_stored_value(repo_backend: Repository) -> None:
    world = _lexical_world(repo_backend)
    with repo_backend.transaction():
        lexeme = repo_backend.set_lexeme_status(world.lexeme_mzr.id, LifecycleStatus.SUPPORTED)
        assert lexeme.status is LifecycleStatus.SUPPORTED
        assert lexeme.score_breakdown is None
        sense = repo_backend.set_sense_status(world.sense_por.id, LifecycleStatus.DEPRECATED)
        assert sense.status is LifecycleStatus.DEPRECATED
        assert sense.score_breakdown is None
    assert repo_backend.get_lexeme(world.lexeme_mzr.id).score_breakdown is None
    assert repo_backend.get_sense(world.sense_por.id).score_breakdown is None


def test_set_review_task_status_rejects_non_operational_values(repo_backend: Repository) -> None:
    world = _lexical_world(repo_backend)
    # A queue entry carries an operational state, never a LifecycleStatus.
    for status in LifecycleStatus:
        with pytest.raises(SchemaViolation):
            repo_backend.set_review_task_status(world.in_review_task.id, status)
    with pytest.raises(SchemaViolation):
        repo_backend.set_review_task_status(world.in_review_task.id, "not_a_state")
    assert repo_backend.get_review_task(world.in_review_task.id).status == "in_review"


def test_status_update_of_missing_entities_raises_not_found(repo_backend: Repository) -> None:
    _lexical_world(repo_backend)
    with pytest.raises(NotFound), repo_backend.transaction():
        repo_backend.set_lexeme_status(new_id(IdPrefix.LEXEME), LifecycleStatus.SUPPORTED)
    with pytest.raises(NotFound), repo_backend.transaction():
        repo_backend.set_sense_status(new_id(IdPrefix.SENSE), LifecycleStatus.SUPPORTED)
    with pytest.raises(NotFound), repo_backend.transaction():
        repo_backend.set_review_task_status(new_id(IdPrefix.REVIEW_TASK), "open")


# --- object registry and counts -------------------------------------------------------------------


def test_registry_and_counts_track_lexical_entities(repo_backend: Repository) -> None:
    world = _lexical_world(repo_backend)

    assert repo_backend.entity_type_of(world.concept.id) is EntityType.CONCEPT
    assert repo_backend.entity_type_of(world.lexeme_mzr.id) is EntityType.LEXEME
    assert repo_backend.entity_type_of(world.lexeme_por.id) is EntityType.LEXEME
    assert repo_backend.entity_type_of(world.primary_link.id) is EntityType.FORM_LEXEME
    assert repo_backend.entity_type_of(world.variant_link.id) is EntityType.FORM_LEXEME
    assert repo_backend.entity_type_of(world.sense_mzr.id) is EntityType.SENSE
    assert repo_backend.entity_type_of(world.high_priority_task.id) is EntityType.REVIEW_TASK
    assert repo_backend.entity_type_of(world.decision.id) is EntityType.REVIEW_DECISION

    assert repo_backend.count(EntityType.CONCEPT) == 1
    assert repo_backend.count(EntityType.LEXEME) == 2
    assert repo_backend.count(EntityType.FORM_LEXEME) == 2
    assert repo_backend.count(EntityType.SENSE) == 2
    assert repo_backend.count(EntityType.REVIEW_TASK) == 3
    assert repo_backend.count(EntityType.REVIEW_DECISION) == 1


# --- relational integrity ------------------------------------------------------------------------


def test_duplicate_form_lexeme_pair_rejected(repo_backend: Repository) -> None:
    world = _lexical_world(repo_backend)
    duplicate = _link(world.form_id, world.lexeme_mzr.id, world.run.id, 40)
    # Same (form_id, lexeme_id) under a fresh identifier: the unique pair refuses it.
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_form_lexeme_link(duplicate)
    # The same identifier under a fresh pair is an attempt to rewrite an existing object.
    relabeled = _link(
        world.form_id, world.lexeme_por.id, world.run.id, 41, id=world.primary_link.id
    )
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_form_lexeme_link(relabeled)
    assert repo_backend.list_form_lexeme_links_for_form(world.form_id) == [
        world.primary_link,
        world.variant_link,
    ]


def test_missing_lexical_parents_rejected(repo_backend: Repository) -> None:
    run = make_run(
        stage=RunStage.LEXICAL_INDUCTION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"fk-{next(_KEYS)}"),
    )
    foreign_run = new_id(IdPrefix.RUN)
    with repo_backend.transaction():
        repo_backend.add_run(run)

    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_concept(
            Concept(
                id=new_id(IdPrefix.CONCEPT),
                canonical_label="x",
                run_id=foreign_run,
                created_at=_at(50),
            )
        )
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_lexeme(_lexeme("mzr", foreign_run, 51))
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_lexeme(_lexeme("mzr", run.id, 52, lemma_form_id=new_id(IdPrefix.FORM)))
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_sense(_sense(new_id(IdPrefix.LEXEME), run.id, 53))
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_sense(
            _sense(new_id(IdPrefix.LEXEME), run.id, 53, concept_id=new_id(IdPrefix.CONCEPT))
        )
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_form_lexeme_link(
            _link(new_id(IdPrefix.FORM), new_id(IdPrefix.LEXEME), run.id, 54)
        )
    assert repo_backend.count(EntityType.CONCEPT) == 0
    assert repo_backend.count(EntityType.LEXEME) == 0
    assert repo_backend.count(EntityType.SENSE) == 0
    assert repo_backend.count(EntityType.FORM_LEXEME) == 0


def test_missing_review_parents_rejected(repo_backend: Repository) -> None:
    run = make_run(
        stage=RunStage.HUMAN_REVIEW,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"rev-fk-{next(_KEYS)}"),
    )
    target = new_id(IdPrefix.LEXEME)
    task = _task(target, run.id, 60, 1.0, "community_linguist", new_id(IdPrefix.REVIEW_TASK))
    with repo_backend.transaction():
        repo_backend.add_run(run)
        repo_backend.add_lexeme(_lexeme("mzr", run.id, 59, id=target))
        repo_backend.add_review_task(task)

    # The decision's task exists, but its target and superseding object do not.
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_review_decision(
            ReviewDecision(
                id=new_id(IdPrefix.REVIEW_DECISION),
                task_id=task.id,
                target_id=new_id(IdPrefix.SENSE),
                decision="accept",
                reviewer_id="reviewer-1",
                reviewer_role="community_linguist",
                created_at=_at(61),
            )
        )
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_review_decision(
            ReviewDecision(
                id=new_id(IdPrefix.REVIEW_DECISION),
                task_id=task.id,
                target_id=target,
                decision="modify",
                reviewer_id="reviewer-1",
                reviewer_role="community_linguist",
                superseding_object_id=new_id(IdPrefix.LEXEME),
                created_at=_at(62),
            )
        )
    assert repo_backend.count(EntityType.REVIEW_DECISION) == 0
    assert repo_backend.get_review_task(task.id) == task


def test_duplicate_identifiers_refused(repo_backend: Repository) -> None:
    world = _lexical_world(repo_backend)
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_lexeme(_lexeme("mzr", world.run.id, 70, id=world.lexeme_mzr.id))
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_review_task(
            _task(
                world.sense_por.id,
                world.run.id,
                71,
                1.0,
                "community_linguist",
                world.low_priority_task.id,
            )
        )
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_review_decision(
            ReviewDecision(
                id=world.decision.id,
                task_id=world.low_priority_task.id,
                target_id=world.sense_por.id,
                decision="defer",
                reviewer_id="reviewer-2",
                reviewer_role="editorial_steward",
                created_at=_at(72),
            )
        )
    assert repo_backend.count(EntityType.LEXEME) == 2
    assert repo_backend.count(EntityType.REVIEW_TASK) == 3
    assert repo_backend.count(EntityType.REVIEW_DECISION) == 1


def test_review_decisions_are_append_only(repo_backend: Repository) -> None:
    world = _lexical_world(repo_backend)
    superseding = ReviewDecision(
        id=new_id(IdPrefix.REVIEW_DECISION),
        task_id=world.low_priority_task.id,
        target_id=world.sense_mzr.id,
        decision="modify",
        reviewer_id="reviewer-2",
        reviewer_role="editorial_steward",
        superseding_object_id=world.lexeme_mzr.id,
        created_at=_at(80),
    )
    with repo_backend.transaction():
        repo_backend.add_review_decision(superseding)

    # A changed opinion appends a new decision; the first one is never edited in place.
    recorded = repo_backend.list_review_decisions_for_target(world.sense_mzr.id)
    assert recorded == [world.decision, superseding]
    assert repo_backend.get_review_decision(world.decision.id) == world.decision
    assert repo_backend.count(EntityType.REVIEW_DECISION) == 2


# --- transactions and copies ----------------------------------------------------------------


def test_rollback_discards_lexical_writes(repo_backend: Repository) -> None:
    run = make_run(
        stage=RunStage.LEXICAL_INDUCTION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"rollback-{next(_KEYS)}"),
    )
    lexeme = _lexeme("mzr", run.id, 80, pos="verb")
    sense = _sense(lexeme.id, run.id, 81)

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom), repo_backend.transaction():
        repo_backend.add_run(run)
        repo_backend.add_lexeme(lexeme)
        repo_backend.add_sense(sense)
        assert repo_backend.get_lexeme(lexeme.id) == lexeme
        raise _Boom

    assert repo_backend.entity_type_of(lexeme.id) is None
    assert repo_backend.entity_type_of(sense.id) is None
    assert repo_backend.count(EntityType.LEXEME) == 0
    assert repo_backend.count(EntityType.SENSE) == 0
    assert repo_backend.list_senses_for_lexeme(lexeme.id) == []


def test_defensive_copies(repo_backend: Repository) -> None:
    world = _lexical_world(repo_backend)
    breakdown = LexicalScoreBreakdown(
        policy_version="lexical-v1",
        overall=0.5,
        components={"alignment_support": 1.0},
        penalties={},
        independence_groups=["alignment"],
    )
    with repo_backend.transaction():
        stored = repo_backend.set_sense_status(
            world.sense_mzr.id, LifecycleStatus.SUPPORTED, breakdown
        )
    # `stored` is the caller's own object; only the stored and listed copies must stay clean.
    stored.glosses["injected"] = ["leak"]
    listed = repo_backend.list_senses_for_lexeme(world.lexeme_mzr.id)
    listed[0].glosses["injected"] = ["leak"]

    assert repo_backend.get_sense(world.sense_mzr.id).glosses == {"por": ["canoa", "barco"]}
    assert repo_backend.get_sense(world.sense_mzr.id).score_breakdown == breakdown
    assert repo_backend.list_senses_for_lexeme(world.lexeme_mzr.id)[0].glosses == {
        "por": ["canoa", "barco"]
    }
    assert repo_backend.get_sense(world.sense_mzr.id).status is LifecycleStatus.SUPPORTED
