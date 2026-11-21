"""WP2.17: Specific invariant and internal index contract tests for InMemoryRepository."""

import pytest

from langpipe.domain.enums import (
    EntityType,
    LineageKind,
    RunStage,
)
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.evidence import LineageEdge
from langpipe.storage.memory import InMemoryRepository
from tests.contract.builders import (
    NOW,
    make_form,
    make_policy,
    make_run,
    make_segment,
    make_source,
    make_source_object,
    make_token,
)


def test_index_rollback_on_failed_transaction() -> None:
    repo = InMemoryRepository()
    policy = make_policy()
    run = make_run(stage=RunStage.SOURCE_REGISTRATION)
    source = make_source(policy, run.id)
    source_object = make_source_object(source, run.id)
    segment = make_segment(source, source_object, run, ordinal=0)
    token = make_token(segment, run, ordinal=0)
    form = make_form(run, text="indexed_form")

    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(run)
        repo.add_source(source)
        repo.add_source_object(source_object)
        repo.add_segment(segment)
        repo.add_token(token)
        repo.get_or_create_form(form)

    # In a failed transaction, add conflicting/new items then raise
    class RollbackBoom(Exception):
        pass

    with pytest.raises(RollbackBoom), repo.transaction():
        token2 = make_token(segment, run, ordinal=1)
        repo.add_token(token2)
        edge = LineageEdge(
            id=new_id(IdPrefix.LINEAGE),
            from_id=token2.id,
            to_id=segment.id,
            kind=LineageKind.DERIVED_FROM,
            run_id=run.id,
            created_at=NOW,
        )
        repo.add_lineage_edge(edge)
        raise RollbackBoom()

    # Verify state rolled back cleanly
    assert len(repo.list_tokens(segment.id)) == 1
    assert repo.count_lineage_edges() == 0
    assert repo._state.tokens_by_segment[segment.id][0].id == token.id
    assert len(repo._state.lineage_edges_out) == 0


def test_form_identity_and_index_deduplication() -> None:
    repo = InMemoryRepository()
    run = make_run()
    f1 = make_form(run, text="kanu")
    f2 = make_form(run, text="kanu")
    with repo.transaction():
        repo.add_run(run)
        saved1 = repo.get_or_create_form(f1)
        saved2 = repo.get_or_create_form(f2)

    assert saved1.id == saved2.id
    assert repo.count(EntityType.FORM) == 1
    assert len(repo._state.forms_by_key) == 1


def test_lineage_edge_idempotent_index_preservation() -> None:
    repo = InMemoryRepository()
    policy = make_policy()
    run = make_run(stage=RunStage.SOURCE_REGISTRATION)
    source = make_source(policy, run.id)
    source_object = make_source_object(source, run.id)
    segment = make_segment(source, source_object, run)
    token = make_token(segment, run)
    edge = LineageEdge(
        id=new_id(IdPrefix.LINEAGE),
        from_id=token.id,
        to_id=segment.id,
        kind=LineageKind.DERIVED_FROM,
        run_id=run.id,
        created_at=NOW,
    )
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(run)
        repo.add_source(source)
        repo.add_source_object(source_object)
        repo.add_segment(segment)
        repo.add_token(token)
        first = repo.add_lineage_edge(edge)
        second = repo.add_lineage_edge(edge)

    assert first.id == second.id
    assert repo.count_lineage_edges() == 1
    assert len(repo._state.lineage_out[token.id]) == 1
    assert len(repo._state.lineage_in[segment.id]) == 1
