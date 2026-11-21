"""Row-locking proof for the M4 status setters (WP4.3 Gate 19, no database writes).

Two independent kinds of evidence that a status transition is a serialized read-modify-write
and never an unlocked `session.get`:

1. A static SQL probe: a Session bound to a PostgreSQL *mock* engine intercepts the
   statement the read helper emits, which is compiled with the PostgreSQL dialect and must
   contain `FOR UPDATE`. No row is ever written.
2. Real interleavings on PostgreSQL: an independent connection holds the target row locked
   while a second transaction attempts the same transition, so a losing writer observes the
   winner's committed value instead of overwriting it (last-writer-wins is refused).
"""

import threading
import time
from typing import Any

import pytest
from sqlalchemy import create_mock_engine, event
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from langpipe.domain.enums import LifecycleStatus, RunStage, RunStatus
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.morphology import MorphAnalysis, Morpheme
from langpipe.storage.db import repository as db_repository
from langpipe.storage.db import tables
from langpipe.storage.db.repository import PostgresRepository
from tests.contract.builders import (
    NOW,
    make_policy,
    make_run,
    make_segment,
    make_source,
    make_source_object,
    make_token,
    unique_run_key,
)
from tests.storage.test_lexical_repository import _lexeme
from tests.storage.test_morphology_repository import (
    SURFACE,
    _analysis,
    _morpheme,
    _segments_for,
)

JOIN_TIMEOUT = 10.0


# --- static probe: the read helper emits a locked SELECT -------------------------------------


def test_locked_read_helper_emits_for_update() -> None:
    from langpipe.domain.errors import NotFound

    engine = create_mock_engine("postgresql+psycopg://", executor=lambda *a, **k: None)
    seen: list[object] = []

    @event.listens_for(Session, "do_orm_execute")
    def _record(orm_execute_state: object) -> None:
        assert orm_execute_state.statement is not None
        seen.append(orm_execute_state.statement)

    try:
        with Session(bind=engine) as session:
            try:
                db_repository._require_for_update(
                    session, tables.Lexeme, "lexeme", "lex_" + "0" * 26
                )
            except NotFound:
                pass
            except Exception:
                pass
    finally:
        event.remove(Session, "do_orm_execute", _record)

    locked = [
        statement
        for statement in seen
        if "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))
    ]
    assert locked, "Gate 19: the locked read helper must emit SELECT ... FOR UPDATE"


# --- real interleavings on PostgreSQL --------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
def test_locked_setter_blocks_a_second_transaction(pg_repository: PostgresRepository) -> None:
    """The row lock is held from the locked read until the transaction exits."""
    run = make_run(
        stage=RunStage.SOURCE_REGISTRATION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key("row-lock-holds"),
    )
    with pg_repository.transaction():
        pg_repository.add_run(run)
    lexeme = _lexeme("mzr", run.id, 200)
    with pg_repository.transaction():
        pg_repository.add_lexeme(lexeme)

    holder = PostgresRepository(pg_repository._engine)
    contender = PostgresRepository(pg_repository._engine)
    inside = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    completed: list[str] = []

    def hold() -> None:
        with holder.transaction():
            holder.set_lexeme_status(lexeme.id, LifecycleStatus.SUPPORTED)
            inside.set()
            assert release.wait(timeout=JOIN_TIMEOUT)

    def contend() -> None:
        assert inside.wait(timeout=JOIN_TIMEOUT)
        try:
            with contender.transaction():
                contender.set_lexeme_status(lexeme.id, LifecycleStatus.REJECTED)
            completed.append("committed")
        except BaseException as exc:  # noqa: BLE001 - asserted below, never swallowed
            errors.append(exc)

    first = threading.Thread(target=hold)
    first.start()
    second = threading.Thread(target=contend)
    second.start()
    try:
        assert inside.wait(timeout=JOIN_TIMEOUT)
        # The contender cannot finish while the holder keeps the row locked: no UPDATE and
        # no commit may appear until the holder's transaction ends.
        assert not completed, "Gate 19: the unlocked read let the second transaction through"
        time.sleep(0.4)
        assert not completed, "Gate 19: the second transaction ran free of the row lock"
    finally:
        release.set()
    first.join(timeout=JOIN_TIMEOUT)
    second.join(timeout=JOIN_TIMEOUT)
    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    # The serial order was holder-then-contender, so the contender's value is final.
    assert completed == ["committed"]
    assert pg_repository.get_lexeme(lexeme.id).status is LifecycleStatus.REJECTED


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
def test_same_value_status_assignment_still_takes_the_row_lock(
    pg_repository: PostgresRepository,
) -> None:
    """An unchanged assignment emits no UPDATE, so only the locked read serializes it."""
    run = make_run(
        stage=RunStage.SOURCE_REGISTRATION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key("row-lock-same-value"),
    )
    with pg_repository.transaction():
        pg_repository.add_run(run)
    lexeme = _lexeme("mzr", run.id, 210, status=LifecycleStatus.CANDIDATE)
    with pg_repository.transaction():
        pg_repository.add_lexeme(lexeme)

    holder = PostgresRepository(pg_repository._engine)
    contender = PostgresRepository(pg_repository._engine)
    inside = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    completed: list[str] = []

    def hold() -> None:
        with holder.transaction():
            holder.set_lexeme_status(lexeme.id, LifecycleStatus.CANDIDATE)
            inside.set()
            assert release.wait(timeout=JOIN_TIMEOUT)

    def contend() -> None:
        assert inside.wait(timeout=JOIN_TIMEOUT)
        try:
            with contender.transaction():
                contender.set_lexeme_status(lexeme.id, LifecycleStatus.CANDIDATE)
            completed.append("committed")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    first = threading.Thread(target=hold)
    first.start()
    second = threading.Thread(target=contend)
    second.start()
    try:
        assert not completed, "Gate 19: an unchanged assignment must still lock the row"
        time.sleep(0.4)
        assert not completed, "Gate 19: an unchanged assignment bypassed the row lock"
    finally:
        release.set()
    first.join(timeout=JOIN_TIMEOUT)
    second.join(timeout=JOIN_TIMEOUT)
    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert completed == ["committed"]
    assert pg_repository.get_lexeme(lexeme.id).status is LifecycleStatus.CANDIDATE


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
def test_transition_re_reads_the_row_instead_of_answering_from_the_session(
    pg_repository: PostgresRepository, migrated_engine: Engine
) -> None:
    """The transition issues its own locked SELECT, not an identity-map answer.

    Counting the statements on the connection shows the transition's read reaches the
    database: an identity-map `session.get` would emit no statement at all.
    """
    run = make_run(
        stage=RunStage.SOURCE_REGISTRATION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key("row-lock-reread"),
    )
    with pg_repository.transaction():
        pg_repository.add_run(run)
    lexeme = _lexeme("mzr", run.id, 230)
    with pg_repository.transaction():
        pg_repository.add_lexeme(lexeme)

    statements: list[str] = []

    def _record(conn: Connection, cursor: Any, statement: str, *rest: Any) -> None:
        statements.append(statement)

    event.listen(migrated_engine, "before_cursor_execute", _record)
    try:
        with pg_repository.transaction():
            # Pre-load the row so the identity map already holds it.
            loaded = pg_repository._writer().get(tables.Lexeme, lexeme.id)
            assert loaded is not None
            statements.clear()
            updated = pg_repository.set_lexeme_status(lexeme.id, LifecycleStatus.SUPPORTED, None)
    finally:
        event.remove(migrated_engine, "before_cursor_execute", _record)

    assert updated.status is LifecycleStatus.SUPPORTED
    locked_reads = [s for s in statements if "FOR UPDATE" in s and "lexeme" in s]
    assert locked_reads, "Gate 19: the transition must issue its own locked SELECT"
    assert pg_repository.get_lexeme(lexeme.id).status is LifecycleStatus.SUPPORTED


# --- M5 morphology row locks (WP5.4, Gate 33) --------------------------------------------------


@pytest.mark.parametrize(
    ("model", "entity", "prefix"),
    [
        (tables.Morpheme, "morpheme", IdPrefix.MORPHEME),
        (tables.MorphAnalysis, "morph_analysis", IdPrefix.MORPH_ANALYSIS),
    ],
)
def test_locked_morphology_reads_emit_for_update(
    model: type[tables.Base], entity: str, prefix: IdPrefix
) -> None:
    from langpipe.domain.errors import NotFound

    engine = create_mock_engine("postgresql+psycopg://", executor=lambda *a, **k: None)
    seen: list[object] = []

    @event.listens_for(Session, "do_orm_execute")
    def _record(orm_execute_state: object) -> None:
        assert orm_execute_state.statement is not None
        seen.append(orm_execute_state.statement)

    try:
        with Session(bind=engine) as session:
            try:
                db_repository._require_for_update(session, model, entity, new_id(prefix))
            except NotFound:
                pass
            except Exception:
                pass
    finally:
        event.remove(Session, "do_orm_execute", _record)

    locked = [
        statement
        for statement in seen
        if "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))
    ]
    assert locked, "Gate 33: the locked read helper must emit SELECT ... FOR UPDATE"


def _morphology_lock_world(
    repo: PostgresRepository,
) -> tuple[Morpheme, MorphAnalysis]:
    """A committed morpheme plus a committed analysis over one token (lock-order targets)."""
    reg_run = make_run(
        stage=RunStage.SOURCE_REGISTRATION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key("row-lock-morph-reg"),
    )
    policy = make_policy()
    source = make_source(policy, reg_run.id, key="row-lock-morph-src")
    source_object = make_source_object(source, reg_run.id)
    tok_run = make_run(
        stage=RunStage.TOKENIZATION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key("row-lock-morph-tok"),
    )
    segment = make_segment(source, source_object, tok_run, raw_text=SURFACE)
    token = make_token(segment, tok_run, surface=SURFACE)
    morph_run = make_run(
        stage=RunStage.MORPHOLOGY_INDUCTION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key("row-lock-morph-run"),
    )
    stem = _morpheme(morph_run.id, 10, "mabi")
    suffix = _morpheme(morph_run.id, 11, "ku")
    analysis_id = new_id(IdPrefix.MORPH_ANALYSIS)
    segments = _segments_for(analysis_id, stem, suffix, None)
    analysis = _analysis(token.id, morph_run.id, segments, 13, analysis_id=analysis_id)
    with repo.transaction():
        repo.add_run(reg_run)
        repo.add_policy(policy)
        repo.add_source(source)
        repo.add_source_object(source_object)
        repo.add_run(tok_run)
        repo.add_segment(segment)
        repo.add_token(token)
        repo.add_run(morph_run)
        repo.add_morpheme(stem)
        repo.add_morpheme(suffix)
        repo.add_morph_analysis(analysis, segments)
    return stem, analysis


def _assert_second_writer_is_blocked(
    pg_repository: PostgresRepository,
    hold_transition: Any,
    contend_transition: Any,
    final_read: Any,
    final_status: LifecycleStatus,
) -> None:
    holder = PostgresRepository(pg_repository._engine)
    contender = PostgresRepository(pg_repository._engine)
    inside = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    completed: list[str] = []

    def hold() -> None:
        with holder.transaction():
            hold_transition(holder)
            inside.set()
            assert release.wait(timeout=JOIN_TIMEOUT)

    def contend() -> None:
        assert inside.wait(timeout=JOIN_TIMEOUT)
        try:
            with contender.transaction():
                contend_transition(contender)
            completed.append("committed")
        except BaseException as exc:  # noqa: BLE001 - asserted below, never swallowed
            errors.append(exc)

    first = threading.Thread(target=hold)
    first.start()
    second = threading.Thread(target=contend)
    second.start()
    try:
        assert inside.wait(timeout=JOIN_TIMEOUT)
        # The contender cannot finish while the holder keeps the row locked.
        assert not completed, "Gate 33: the unlocked read let the second transaction through"
        time.sleep(0.4)
        assert not completed, "Gate 33: the second transaction ran free of the row lock"
    finally:
        release.set()
    first.join(timeout=JOIN_TIMEOUT)
    second.join(timeout=JOIN_TIMEOUT)
    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    # The serial order was holder-then-contender, so the contender's value is final.
    assert completed == ["committed"]
    assert final_read(pg_repository).status is final_status


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
def test_locked_morpheme_setter_blocks_a_second_transaction(
    pg_repository: PostgresRepository,
) -> None:
    stem, _analysis_row = _morphology_lock_world(pg_repository)
    _assert_second_writer_is_blocked(
        pg_repository,
        lambda repo: repo.set_morpheme_status(stem.id, LifecycleStatus.SUPPORTED),
        lambda repo: repo.set_morpheme_status(stem.id, LifecycleStatus.REJECTED),
        lambda repo: repo.get_morpheme(stem.id),
        LifecycleStatus.REJECTED,
    )


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
def test_locked_morph_analysis_setter_blocks_a_second_transaction(
    pg_repository: PostgresRepository,
) -> None:
    _stem, analysis_row = _morphology_lock_world(pg_repository)
    _assert_second_writer_is_blocked(
        pg_repository,
        lambda repo: repo.set_morph_analysis_status(analysis_row.id, LifecycleStatus.SUPPORTED),
        lambda repo: repo.set_morph_analysis_status(analysis_row.id, LifecycleStatus.REJECTED),
        lambda repo: repo.get_morph_analysis(analysis_row.id),
        LifecycleStatus.REJECTED,
    )
