"""PostgresRepository behaviour that the shared contract suite does not cover. Requires PostgreSQL.

Test data is synthetic: identifiers and placeholder text only.
"""

import traceback
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Connection, Engine

from langpipe.domain.enums import AccessClass, EntityType, LineageKind, RunStage, RunStatus
from langpipe.domain.errors import ImmutableViolation, SourceConflict
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.run import ProcessingRun
from langpipe.storage.db.repository import PostgresRepository, StorageIntegrityError
from tests.contract.builders import (
    LATER,
    NOW,
    make_form,
    make_policy,
    make_run,
    make_segment,
    make_source,
    make_source_object,
    make_token,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]

# Synthetic markers that stand in for restricted content. They must never reach an error chain.
SENTINEL_TEXT = "SENTINEL-SEGMENT-TEXT-7f3a"
SENTINEL_TITLE = "SENTINEL-SOURCE-TITLE-7f3a"
SENTINEL_PATH = "SENTINEL-FILE-NAME-7f3a.txt"


def _chain(repo: PostgresRepository) -> tuple[ProcessingRun, list[str]]:
    """Create tokens a, b, c and return the run plus their ids in that order."""
    policy = make_policy()
    run = make_run(stage=RunStage.SOURCE_REGISTRATION)
    # The registration run must exist before the source and its objects (foreign keys).
    source = make_source(policy, registration_run_id=run.id)
    source_object = make_source_object(source, registration_run_id=run.id)
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


@pytest.fixture
def statements(migrated_engine: Engine) -> Iterator[list[str]]:
    """Collect every SQL statement executed on the engine while the test runs."""
    seen: list[str] = []

    def _record(
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        seen.append(statement)

    event.listen(migrated_engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(migrated_engine, "before_cursor_execute", _record)


def test_pg_descendants_uses_single_query(
    pg_repository: PostgresRepository, statements: list[str]
) -> None:
    run, (a, b, c) = _chain(pg_repository)
    with pg_repository.transaction():
        pg_repository.add_lineage_edge(_edge(run, b, a))
        pg_repository.add_lineage_edge(_edge(run, c, b))
        pg_repository.add_lineage_edge(_edge(run, c, a))

    statements.clear()
    found = pg_repository.descendants(a)

    assert found == [(b, 1), (c, 1)]
    assert len(statements) <= 1


def test_pg_trigger_violation_maps_to_immutable_violation(
    pg_repository: PostgresRepository,
) -> None:
    run = make_run()
    with pg_repository.transaction():
        pg_repository.add_run(run)
        pg_repository.finish_run(run.id, RunStatus.SUCCEEDED, LATER)

    # The Python pre-check in finish_run would refuse this first, so the statement goes
    # straight to the session to exercise the database trigger (langpipe_run_guard).
    with pytest.raises(ImmutableViolation), pg_repository.transaction():
        session = pg_repository._session
        assert session is not None
        session.execute(
            text("UPDATE processing_run SET error_type = 'late' WHERE id = :id"),
            {"id": run.id},
        )
    assert pg_repository.get_run(run.id).error_type is None


def test_pg_policy_round_trip_preserves_policy_fields(pg_repository: PostgresRepository) -> None:
    policy = make_policy(restrictions={"notes": ["a"]})
    with pg_repository.transaction():
        pg_repository.add_policy(policy)

    assert pg_repository.get_policy(policy.id) == policy


def test_form_insert_race_returns_winner_and_keeps_outer_writes(
    migrated_engine: Engine, pg_repository: PostgresRepository
) -> None:
    run = make_run()
    with pg_repository.transaction():
        pg_repository.add_run(run)
    # Same natural key, different identifiers: only one form can exist.
    winner = make_form(run, text="hello")
    loser = make_form(run, text="hello")
    competitor = PostgresRepository(migrated_engine)
    before, after = make_policy(), make_policy()
    fired: list[bool] = []

    def _commit_competitor(
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        # Runs on the first form INSERT of the writer: the lookup has already missed.
        if fired or not statement.lstrip().startswith("INSERT INTO form "):
            return
        fired.append(True)
        with competitor.transaction():
            competitor.get_or_create_form(winner)

    event.listen(migrated_engine, "before_cursor_execute", _commit_competitor)
    try:
        with pg_repository.transaction():
            pg_repository.add_policy(before)
            stored = pg_repository.get_or_create_form(loser)
            pg_repository.add_policy(after)
    finally:
        event.remove(migrated_engine, "before_cursor_execute", _commit_competitor)

    assert fired == [True]
    assert stored == winner
    assert pg_repository.entity_type_of(loser.id) is None
    assert pg_repository.count(EntityType.FORM) == 1
    assert pg_repository.get_policy(before.id) == before
    assert pg_repository.get_policy(after.id) == after
    with migrated_engine.connect() as conn:
        matching = conn.execute(
            text("SELECT count(*) FROM form WHERE language = :lang AND text = :value"),
            {"lang": winner.language, "value": "hello"},
        ).scalar_one()
    assert matching == 1


def _rendered(exc: BaseException) -> str:
    """Everything a log handler or traceback would print for this exception."""
    return str(exc) + "".join(traceback.format_exception(exc))


def test_translated_db_failures_do_not_expose_restricted_text(
    pg_repository: PostgresRepository,
) -> None:
    policy = make_policy(access_class=AccessClass.RESTRICTED)
    run = make_run(stage=RunStage.SOURCE_REGISTRATION)
    source = make_source(policy, run.id, key="restricted-key", title="Ordinary title")
    source_object = make_source_object(source, run.id, path=SENTINEL_PATH)
    segment = make_segment(source, source_object, run, raw_text=SENTINEL_TEXT)
    with pg_repository.transaction():
        pg_repository.add_policy(policy)
        pg_repository.add_run(run)
        pg_repository.add_source(source)
        pg_repository.add_source_object(source_object)
        pg_repository.add_segment(segment)

    # The unique-violation parameters carry the restricted values; only the mapped error may escape.
    duplicate_segment = make_segment(source, source_object, run, raw_text=SENTINEL_TEXT + " copy")
    with pytest.raises(ImmutableViolation) as segment_failure, pg_repository.transaction():
        pg_repository.add_segment(duplicate_segment)

    duplicate_source = make_source(policy, run.id, key="restricted-key", title=SENTINEL_TITLE)
    with pytest.raises(SourceConflict) as source_failure, pg_repository.transaction():
        pg_repository.add_source(duplicate_source)

    duplicate_object = make_source_object(source, run.id, path=SENTINEL_PATH)
    with pytest.raises(SourceConflict) as object_failure, pg_repository.transaction():
        pg_repository.add_source_object(duplicate_object)

    for failure in (segment_failure, source_failure, object_failure):
        rendered = _rendered(failure.value)
        for sentinel in (SENTINEL_TEXT, SENTINEL_TITLE, SENTINEL_PATH):
            assert sentinel not in rendered


def test_unmapped_integrity_failure_is_redacted(pg_repository: PostgresRepository) -> None:
    policy = make_policy(access_class=AccessClass.RESTRICTED)
    run = make_run(stage=RunStage.SOURCE_REGISTRATION)
    source = make_source(policy, run.id)
    source_object = make_source_object(source, run.id)
    with pg_repository.transaction():
        pg_repository.add_policy(policy)
        pg_repository.add_run(run)
        pg_repository.add_source(source)
        pg_repository.add_source_object(source_object)

    # The run is never stored, so the segment's run foreign key is unmapped and fails.
    unstored_run = make_run(stage=RunStage.SOURCE_REGISTRATION)
    segment = make_segment(source, source_object, unstored_run, raw_text=SENTINEL_TEXT)
    with pytest.raises(StorageIntegrityError) as failure, pg_repository.transaction():
        pg_repository.add_segment(segment)

    assert failure.value.sqlstate == "23503"
    assert failure.value.constraint == "segment_run_id_fkey"
    assert SENTINEL_TEXT not in _rendered(failure.value)
    # The registry row written before the failed insert is rolled back with the transaction.
    assert pg_repository.entity_type_of(segment.id) is None
