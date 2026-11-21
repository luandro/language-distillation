"""Behaviour every Repository backend must share. Runs once per backend via the `repo` fixture."""

import re
from datetime import timedelta

import pytest

from langpipe.domain.enums import (
    EntityType,
    EvidenceKind,
    EvidencePolarity,
    LineageKind,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
)
from langpipe.domain.errors import ImmutableViolation, InvalidLineage, NotFound, SourceConflict
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.run import ProcessingRun
from langpipe.domain.models.source import RawBlob
from langpipe.storage.repository import Repository
from tests.contract.builders import (
    LATER,
    NOW,
    SHA_A,
    SHA_B,
    make_evidence,
    make_form,
    make_policy,
    make_run,
    make_segment,
    make_source,
    make_source_object,
    make_token,
)


class _Boom(Exception):
    pass


def _ids(items: list[tuple[str, int]]) -> list[tuple[str, int]]:
    return sorted(items, key=lambda item: (item[1], item[0]))


def test_write_outside_transaction_raises(repo: Repository) -> None:
    with pytest.raises(RuntimeError, match="write outside transaction"):
        repo.add_policy(make_policy())


def test_nested_transaction_raises(repo: Repository) -> None:
    with repo.transaction(), pytest.raises(RuntimeError), repo.transaction():
        pass


def test_transaction_rollback_discards_all_writes(repo: Repository) -> None:
    policy = make_policy()
    run = make_run(stage=RunStage.SOURCE_REGISTRATION)
    source = make_source(policy, run.id)
    source_object = make_source_object(source, run.id)
    segment = make_segment(source, source_object, run)
    token = make_token(segment, run)
    form = make_form(run, text="rollback_form")
    edge = LineageEdge(
        id=new_id(IdPrefix.LINEAGE),
        from_id=token.id,
        to_id=segment.id,
        kind=LineageKind.DERIVED_FROM,
        run_id=run.id,
        created_at=NOW,
    )
    with pytest.raises(_Boom), repo.transaction():
        repo.add_policy(policy)
        repo.add_run(run)
        repo.add_source(source)
        repo.add_source_object(source_object)
        repo.add_segment(segment)
        repo.add_token(token)
        repo.get_or_create_form(form)
        repo.add_lineage_edge(edge)
        raise _Boom
    with pytest.raises(NotFound):
        repo.get_policy(policy.id)
    with pytest.raises(NotFound):
        repo.get_run(run.id)
    with pytest.raises(NotFound):
        repo.get_segment(segment.id)
    with pytest.raises(NotFound):
        repo.get_token(token.id)
    assert repo.entity_type_of(run.id) is None
    assert repo.entity_type_of(segment.id) is None
    assert repo.entity_type_of(token.id) is None
    assert repo.count(EntityType.SOURCE) == 0
    assert repo.count(EntityType.PROCESSING_RUN) == 0
    assert repo.count(EntityType.SEGMENT) == 0
    assert repo.count(EntityType.TOKEN_OCCURRENCE) == 0
    assert repo.count(EntityType.FORM) == 0
    assert repo.count_lineage_edges() == 0
    assert repo.list_tokens(segment.id) == []
    assert repo.list_lineage_edges(token.id, "out") == []
    assert repo.list_lineage_edges(segment.id, "in") == []


def test_nested_model_mutation_does_not_change_repository_state(repo: Repository) -> None:
    policy = make_policy(restrictions={"notes": ["a"]})
    run = make_run(config={"nested": ["x"]})
    source = make_source(policy, run.id)
    source_object = make_source_object(source, run.id)
    segment = make_segment(source, source_object, run, locator={"line": 1})
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(run)
        repo.add_source(source)
        repo.add_source_object(source_object)
        repo.add_segment(segment)

    policy.restrictions["notes"].append("b")
    run.config["nested"].append("y")
    segment.locator["line"] = 2
    stored_policy = repo.get_policy(policy.id)
    stored_policy.restrictions["notes"].append("c")
    stored_run = repo.get_run(run.id)
    stored_run.config["nested"].append("z")
    stored_segment = repo.get_segment(segment.id)
    stored_segment.locator["line"] = 3

    assert repo.get_policy(policy.id).restrictions == {"notes": ["a"]}
    assert repo.get_run(run.id).config == {"nested": ["x"]}
    assert repo.get_segment(segment.id).locator == {"line": 1}


def test_registry_tracks_entity_types(repo: Repository) -> None:
    policy = make_policy()
    run = make_run()
    source = make_source(policy, run.id)
    source_object = make_source_object(source, run.id)
    segment = make_segment(source, source_object, run)
    token = make_token(segment, run)
    form = make_form(run)
    evidence = make_evidence(token.id, run)
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(run)
        repo.add_source(source)
        repo.add_source_object(source_object)
        repo.add_segment(segment)
        repo.add_token(token)
        repo.get_or_create_form(form)
        repo.add_evidence(evidence)

    assert repo.entity_type_of(source.id) is EntityType.SOURCE
    assert repo.entity_type_of(source_object.id) is EntityType.SOURCE_OBJECT
    assert repo.entity_type_of(run.id) is EntityType.PROCESSING_RUN
    assert repo.entity_type_of(segment.id) is EntityType.SEGMENT
    assert repo.entity_type_of(token.id) is EntityType.TOKEN_OCCURRENCE
    assert repo.entity_type_of(form.id) is EntityType.FORM
    assert repo.entity_type_of(evidence.id) is EntityType.EVIDENCE_ITEM
    assert repo.entity_type_of(policy.id) is None
    assert repo.count(EntityType.SOURCE) == 1
    assert repo.count(EntityType.PROCESSING_RUN) == 1


def test_source_object_unique_path(repo: Repository) -> None:
    policy = make_policy()
    run = make_run(stage=RunStage.SOURCE_REGISTRATION)
    source = make_source(policy, run.id)
    first = make_source_object(source, run.id, path="texts/a.txt")
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(run)
        repo.add_source(source)
        repo.add_source_object(first)
    with pytest.raises(SourceConflict), repo.transaction():
        repo.add_source_object(make_source_object(source, run.id, path="texts/a.txt"))
    with repo.transaction():
        repo.add_source_object(make_source_object(source, run.id, path="texts/b.txt"))

    assert [o.original_path for o in repo.list_source_objects(source.id)] == [
        "texts/a.txt",
        "texts/b.txt",
    ]


def test_source_key_is_unique(repo: Repository) -> None:
    policy = make_policy()
    run = make_run(stage=RunStage.SOURCE_REGISTRATION)
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(run)
        repo.add_source(make_source(policy, run.id, key="same-key"))
    with pytest.raises(SourceConflict), repo.transaction():
        repo.add_source(make_source(policy, run.id, key="same-key"))


def test_set_source_status_returns_revalidated_copy(repo: Repository) -> None:
    policy = make_policy()
    run = make_run(stage=RunStage.SOURCE_REGISTRATION)
    source = make_source(policy, run.id)
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(run)
        repo.add_source(source)
    with repo.transaction():
        updated = repo.set_source_status(source.id, SourceStatus.REVOKED, LATER)

    assert updated.status is SourceStatus.REVOKED
    assert updated.updated_at == LATER
    assert repo.get_source(source.id).status is SourceStatus.REVOKED
    assert repo.find_source_by_key(source.key) is not None


def test_raw_blob_add_is_idempotent(repo: Repository) -> None:
    ingestion_run = make_run(stage=RunStage.RAW_INGESTION)
    first = RawBlob(
        sha256=SHA_A,
        size_bytes=5,
        storage_backend="local",
        stored_at=NOW,
        ingestion_run_id=ingestion_run.id,
    )
    second = first.model_copy(update={"stored_at": LATER})
    with repo.transaction():
        repo.add_run(ingestion_run)
        stored_first = repo.add_raw_blob(first)
    with repo.transaction():
        stored_second = repo.add_raw_blob(second)

    assert stored_first == first
    assert stored_second == first
    assert repo.get_raw_blob(SHA_A) == first
    assert repo.get_raw_blob(SHA_B) is None
    assert repo.count_raw_blobs() == 1


def test_finish_run_only_once(repo: Repository) -> None:
    run = make_run()
    with repo.transaction():
        repo.add_run(run)
    with repo.transaction():
        finished = repo.finish_run(run.id, RunStatus.SUCCEEDED, LATER)
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.finished_at == LATER

    with pytest.raises(ImmutableViolation), repo.transaction():
        repo.finish_run(run.id, RunStatus.FAILED, LATER, "ValueError", "boom")
    with pytest.raises(ImmutableViolation), repo.transaction():
        repo.finish_run(run.id, RunStatus.SUCCEEDED, LATER)
    assert repo.get_run(run.id).status is RunStatus.SUCCEEDED


def test_finish_run_rejects_running_status(repo: Repository) -> None:
    run = make_run()
    with repo.transaction():
        repo.add_run(run)
    with pytest.raises(ImmutableViolation), repo.transaction():
        repo.finish_run(run.id, RunStatus.RUNNING, LATER)


def test_find_succeeded_run_ignores_failed(repo: Repository) -> None:
    run_key = "d" * 64
    failed = make_run(run_key=run_key)
    with repo.transaction():
        repo.add_run(failed)
    with repo.transaction():
        repo.finish_run(failed.id, RunStatus.FAILED, LATER, "ValueError", "boom")
    assert repo.find_succeeded_run(run_key) is None

    succeeded = make_run(run_key=run_key)
    with repo.transaction():
        repo.add_run(succeeded)
    with repo.transaction():
        repo.finish_run(succeeded.id, RunStatus.SUCCEEDED, LATER)

    found = repo.find_succeeded_run(run_key)
    assert found is not None
    assert found.id == succeeded.id


def test_run_io_requires_registered_object(repo: Repository) -> None:
    run = make_run()
    with repo.transaction():
        repo.add_run(run)
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_run_io(run.id, new_id(IdPrefix.SOURCE_OBJECT), RunIoRole.INPUT)


def test_run_io_is_sorted_and_duplicates_are_ignored(repo: Repository) -> None:
    policy = make_policy()
    run = make_run(stage=RunStage.SOURCE_REGISTRATION)
    source = make_source(policy, run.id)
    source_object = make_source_object(source, run.id)
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(run)
        repo.add_source(source)
        repo.add_source_object(source_object)
        repo.add_run_io(run.id, source_object.id, RunIoRole.OUTPUT)
        repo.add_run_io(run.id, source_object.id, RunIoRole.INPUT)
        repo.add_run_io(run.id, source_object.id, RunIoRole.INPUT)

    assert repo.list_run_io(run.id) == sorted(
        [(source_object.id, RunIoRole.INPUT), (source_object.id, RunIoRole.OUTPUT)],
        key=lambda item: (item[0], item[1].value),
    )


def test_get_or_create_form_returns_existing(repo: Repository) -> None:
    run = make_run()
    first = make_form(run, text="hello")
    second = make_form(run, text="hello")
    with repo.transaction():
        repo.add_run(run)
        assert repo.get_or_create_form(first) == first
    with repo.transaction():
        existing = repo.get_or_create_form(second)

    assert existing == first
    assert repo.count(EntityType.FORM) == 1


def test_get_form_returns_stored_form_and_raises_for_unknown(repo: Repository) -> None:
    run = make_run()
    form = make_form(run, text="hello")
    with repo.transaction():
        repo.add_run(run)
        repo.get_or_create_form(form)

    assert repo.get_form(form.id) == form
    with pytest.raises(NotFound):
        repo.get_form(new_id(IdPrefix.FORM))


def test_lineage_requires_existing_endpoints(repo: Repository) -> None:
    policy = make_policy()
    run = make_run(stage=RunStage.SOURCE_REGISTRATION)
    source = make_source(policy, run.id)
    source_object = make_source_object(source, run.id)
    segment = make_segment(source, source_object, run)
    token = make_token(segment, run)
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(run)
        repo.add_source(source)
        repo.add_source_object(source_object)
        repo.add_segment(segment)
        repo.add_token(token)
    missing = new_id(IdPrefix.TOKEN)
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_lineage_edge(
            LineageEdge(
                id=new_id(IdPrefix.LINEAGE),
                from_id=token.id,
                to_id=missing,
                kind=LineageKind.DERIVED_FROM,
                run_id=run.id,
                created_at=NOW,
            )
        )
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_lineage_edge(
            LineageEdge(
                id=new_id(IdPrefix.LINEAGE),
                from_id=missing,
                to_id=token.id,
                kind=LineageKind.DERIVED_FROM,
                run_id=run.id,
                created_at=NOW,
            )
        )


def _chain(repo: Repository) -> tuple[ProcessingRun, list[str]]:
    """Create tokens a, b, c and return the run plus their ids in that order."""
    policy = make_policy()
    run = make_run(stage=RunStage.SOURCE_REGISTRATION)
    source = make_source(policy, run.id)
    source_object = make_source_object(source, run.id)
    segment = make_segment(source, source_object, run)
    tokens = [make_token(segment, run, ordinal=i) for i in range(3)]
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(run)
        repo.add_source(source)
        repo.add_source_object(source_object)
        repo.add_segment(segment)
        for token in tokens:
            repo.add_token(token)
    return run, [token.id for token in tokens]


def _edge(run: ProcessingRun, from_id: str, to_id: str) -> LineageEdge:
    return LineageEdge(
        id=new_id(IdPrefix.LINEAGE),
        from_id=from_id,
        to_id=to_id,
        kind=LineageKind.DERIVED_FROM,
        run_id=run.id,
        created_at=NOW,
    )


def test_lineage_rejects_cycle(repo: Repository) -> None:
    run, (a, b, c) = _chain(repo)
    with repo.transaction():
        repo.add_lineage_edge(_edge(run, b, a))
        repo.add_lineage_edge(_edge(run, c, b))
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_lineage_edge(_edge(run, a, c))
    assert repo.count_lineage_edges() == 2


def test_lineage_edge_idempotent(repo: Repository) -> None:
    run, (a, b, _) = _chain(repo)
    first = _edge(run, b, a)
    with repo.transaction():
        stored = repo.add_lineage_edge(first)
    with repo.transaction():
        again = repo.add_lineage_edge(_edge(run, b, a))

    assert stored == first
    assert again == first
    assert repo.count_lineage_edges() == 1


def test_descendants_transitive_with_min_depth(repo: Repository) -> None:
    # a <- b <- c (c depends on b, b depends on a) plus a <- c: c is reachable at depth 1.
    run, (a, b, c) = _chain(repo)
    with repo.transaction():
        repo.add_lineage_edge(_edge(run, b, a))
        repo.add_lineage_edge(_edge(run, c, b))
        repo.add_lineage_edge(_edge(run, c, a))

    assert repo.descendants(a) == _ids([(b, 1), (c, 1)])
    assert repo.ancestors(c) == _ids([(a, 1), (b, 1)])


def test_repository_has_no_observation_mutators(repo: Repository) -> None:
    pattern = re.compile(
        r"^(update|delete|remove|set)_(segment|token|source_object|evidence|lineage|form|artifact)"
    )
    assert [name for name in dir(repo) if pattern.match(name)] == []


def test_observations_unchanged_when_evidence_changes(repo: Repository) -> None:
    policy = make_policy()
    run = make_run(stage=RunStage.MANUAL_ANNOTATION)
    source = make_source(policy, run.id)
    source_object = make_source_object(source, run.id)
    segment = make_segment(source, source_object, run)
    token_one = make_token(segment, run, ordinal=0, surface="hello")
    token_two = make_token(segment, run, ordinal=1, surface="world")
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(run)
        repo.add_source(source)
        repo.add_source_object(source_object)
        repo.add_segment(segment)
        repo.add_token(token_one)
        repo.add_token(token_two)

    before = (
        repo.get_segment(segment.id).model_dump(),
        repo.get_token(token_one.id).model_dump(),
        repo.get_token(token_two.id).model_dump(),
    )

    supports = make_evidence(token_one.id, run, kind=EvidenceKind.MANUAL_ANNOTATION)
    contradicts = make_evidence(
        token_one.id,
        run,
        kind=EvidenceKind.MANUAL_ANNOTATION,
        polarity=EvidencePolarity.CONTRADICTS,
        created_at=NOW + timedelta(seconds=1),
    )
    with repo.transaction():
        repo.add_evidence(supports)
        repo.add_lineage_edge(_edge(run, supports.id, token_one.id))
        repo.add_evidence(contradicts)
        repo.add_lineage_edge(
            LineageEdge(
                id=new_id(IdPrefix.LINEAGE),
                from_id=contradicts.id,
                to_id=supports.id,
                kind=LineageKind.SUPERSEDES,
                run_id=run.id,
                created_at=NOW,
            )
        )

    after = (
        repo.get_segment(segment.id).model_dump(),
        repo.get_token(token_one.id).model_dump(),
        repo.get_token(token_two.id).model_dump(),
    )
    assert after == before
    assert [e.id for e in repo.list_evidence_for_target(token_one.id)] == [
        supports.id,
        contradicts.id,
    ]
    assert isinstance(repo.get_evidence(supports.id), EvidenceItem)


def test_list_segments_for_run_orders_by_object_then_ordinal(repo: Repository) -> None:
    policy = make_policy()
    registration = make_run(stage=RunStage.SOURCE_REGISTRATION)
    run = make_run(stage=RunStage.EXTRACTION, run_key="1" * 64)
    other_run = make_run(stage=RunStage.EXTRACTION, run_key="2" * 64)
    source = make_source(policy, registration.id)
    object_a = make_source_object(source, registration.id, path="texts/a.txt")
    object_b = make_source_object(source, registration.id, path="texts/b.txt")
    segments = [
        make_segment(source, object_b, run, ordinal=0),
        make_segment(source, object_a, run, ordinal=1),
        make_segment(source, object_a, run, ordinal=0),
    ]
    foreign = make_segment(source, object_a, other_run, ordinal=0)
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(registration)
        repo.add_run(run)
        repo.add_run(other_run)
        repo.add_source(source)
        repo.add_source_object(object_a)
        repo.add_source_object(object_b)
        for segment in [*segments, foreign]:
            repo.add_segment(segment)

    listed = repo.list_segments_for_run(run.id)

    assert [segment.id for segment in listed] == [
        segment.id for segment in sorted(segments, key=lambda s: (s.source_object_id, s.ordinal))
    ]
    assert foreign.id not in {segment.id for segment in listed}
    assert repo.list_segments_for_run(new_id(IdPrefix.RUN)) == []


def test_list_runs_with_input_filters_stage_and_status(repo: Repository) -> None:
    policy = make_policy()
    registration = make_run(stage=RunStage.SOURCE_REGISTRATION)
    source = make_source(policy, registration.id)
    source_object = make_source_object(source, registration.id)
    early = make_run(stage=RunStage.EXTRACTION, run_key="1" * 64, started_at=NOW)
    late = make_run(stage=RunStage.EXTRACTION, run_key="2" * 64, started_at=LATER)
    failed = make_run(stage=RunStage.EXTRACTION, run_key="3" * 64)
    normalization = make_run(stage=RunStage.NORMALIZATION, run_key="4" * 64)
    output_only = make_run(stage=RunStage.EXTRACTION, run_key="5" * 64)
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(registration)
        repo.add_source(source)
        repo.add_source_object(source_object)
        for run in (early, late, failed, normalization, output_only):
            repo.add_run(run)
            if run is output_only:
                repo.add_run_io(run.id, source_object.id, RunIoRole.OUTPUT)
            else:
                repo.add_run_io(run.id, source_object.id, RunIoRole.INPUT)
    with repo.transaction():
        repo.finish_run(early.id, RunStatus.SUCCEEDED, LATER)
        repo.finish_run(late.id, RunStatus.SUCCEEDED, LATER)
        repo.finish_run(failed.id, RunStatus.FAILED, LATER, "ValueError", "boom")
        repo.finish_run(normalization.id, RunStatus.SUCCEEDED, LATER)
        repo.finish_run(output_only.id, RunStatus.SUCCEEDED, LATER)

    succeeded = repo.list_runs_with_input(
        source_object.id, RunStage.EXTRACTION, RunStatus.SUCCEEDED
    )
    assert [run.id for run in succeeded] == [early.id, late.id]
    any_status = repo.list_runs_with_input(source_object.id, RunStage.EXTRACTION)
    expected_any = sorted([early, late, failed], key=lambda run: (run.started_at, run.id))
    assert [run.id for run in any_status] == [run.id for run in expected_any]
    assert [
        run.id for run in repo.list_runs_with_input(source_object.id, RunStage.NORMALIZATION)
    ] == [normalization.id]


def test_add_segment_rejects_duplicate_run_object_ordinal(repo: Repository) -> None:
    policy = make_policy()
    run = make_run(stage=RunStage.EXTRACTION)
    source = make_source(policy, run.id)
    source_object = make_source_object(source, run.id)
    first = make_segment(source, source_object, run, ordinal=0)
    duplicate = make_segment(source, source_object, run, ordinal=0)
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(run)
        repo.add_source(source)
        repo.add_source_object(source_object)
        repo.add_segment(first)
    with pytest.raises(ImmutableViolation), repo.transaction():
        repo.add_segment(duplicate)


def test_add_token_rejects_duplicate_run_segment_ordinal(repo: Repository) -> None:
    policy = make_policy()
    run = make_run(stage=RunStage.TOKENIZATION)
    source = make_source(policy, run.id)
    source_object = make_source_object(source, run.id)
    segment = make_segment(source, source_object, run)
    first = make_token(segment, run, ordinal=0)
    duplicate = make_token(segment, run, ordinal=0)
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(run)
        repo.add_source(source)
        repo.add_source_object(source_object)
        repo.add_segment(segment)
        repo.add_token(first)
    with pytest.raises(ImmutableViolation), repo.transaction():
        repo.add_token(duplicate)
