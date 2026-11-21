"""Real interleavings of the M3 alignment lock primitives (WP3.3, M3-PLAN §5.3).

Independent PostgreSQL connections plus thread barriers prove serialization: the same
request key serializes preflight/reuse/start/compute/commit scopes, a failed scope still
releases its advisory lock, and source row locks held until commit keep concurrent
revocation from racing an alignment commit. Test data is synthetic: identifiers only.
"""

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine

from langpipe.alignment.base import AlignmentConfig
from langpipe.alignment.token_service import TokenAlignmentService
from langpipe.app_context import AppContext
from langpipe.domain.enums import AuditEventType, RunStage, RunStatus, SourceStatus
from langpipe.domain.errors import AlignmentFailed, PolicyDenied
from langpipe.domain.ids import new_id
from langpipe.storage.db.repository import PostgresRepository
from langpipe.storage.objects.local import LocalContentStore
from langpipe.text.registry import VersionedRegistry
from tests.contract.builders import (
    LATER,
    make_evidence,
    make_policy,
    make_run,
    make_source,
)
from tests.service.test_token_alignment_service import _Links, _ready

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]

REQUEST_KEY = "wp33-concurrency-request"
JOIN_TIMEOUT = 10.0
ACQUISITION_TIMEOUT = 0.3


def test_same_request_lock_serializes(migrated_engine: Engine) -> None:
    holder = PostgresRepository(migrated_engine)
    waiter = PostgresRepository(migrated_engine)
    held = threading.Event()
    attempting = threading.Event()
    acquired = threading.Event()
    observed = threading.Event()
    timings: dict[str, float] = {}

    def hold() -> None:
        with holder.alignment_lock(REQUEST_KEY, timeout_seconds=JOIN_TIMEOUT):
            held.set()
            attempting.wait(timeout=JOIN_TIMEOUT)
            # Keep owning the lock until the blocked window has been observed.
            observed.wait(timeout=JOIN_TIMEOUT)
            timings["released"] = time.monotonic()

    def wait_for_it() -> None:
        assert held.wait(timeout=JOIN_TIMEOUT)
        attempting.set()
        timings["attempt"] = time.monotonic()
        with waiter.alignment_lock(REQUEST_KEY, timeout_seconds=JOIN_TIMEOUT):
            timings["acquired"] = time.monotonic()
            acquired.set()

    holder_thread = threading.Thread(target=hold)
    holder_thread.start()
    assert held.wait(timeout=JOIN_TIMEOUT)
    waiter_thread = threading.Thread(target=wait_for_it)
    waiter_thread.start()
    assert attempting.wait(timeout=JOIN_TIMEOUT)
    # The waiter is mid-acquisition while the holder still owns the lock.
    assert not acquired.wait(timeout=0.5)
    observed.set()
    holder_thread.join(timeout=JOIN_TIMEOUT)
    waiter_thread.join(timeout=JOIN_TIMEOUT)
    assert not holder_thread.is_alive()
    assert not waiter_thread.is_alive()
    assert acquired.is_set()
    assert timings["attempt"] < timings["released"]
    assert timings["acquired"] >= timings["released"]

    # Bounded acquisition fails closed with backend_timeout while the key is held.
    blocking = threading.Event()
    release = threading.Event()

    def own() -> None:
        with holder.alignment_lock(REQUEST_KEY, timeout_seconds=JOIN_TIMEOUT):
            blocking.set()
            release.wait(timeout=JOIN_TIMEOUT)

    owner_thread = threading.Thread(target=own)
    owner_thread.start()
    try:
        assert blocking.wait(timeout=JOIN_TIMEOUT)
        with (
            pytest.raises(AlignmentFailed) as excinfo,
            waiter.alignment_lock(REQUEST_KEY, timeout_seconds=0.3),
        ):
            pass
        assert excinfo.value.code == "backend_timeout"
    finally:
        release.set()
        owner_thread.join(timeout=JOIN_TIMEOUT)
        assert not owner_thread.is_alive()


def test_lock_released_after_failure(migrated_engine: Engine) -> None:
    repo = PostgresRepository(migrated_engine)
    other = PostgresRepository(migrated_engine)

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom), repo.alignment_lock(REQUEST_KEY, timeout_seconds=JOIN_TIMEOUT):
        raise _Boom

    # The failed scope released the lock: a different owner acquires promptly, and while
    # it holds the key the first repository's bounded attempt times out (so the success
    # below cannot be vacuous).
    with other.alignment_lock(REQUEST_KEY, timeout_seconds=2.0):
        with (
            pytest.raises(AlignmentFailed) as excinfo,
            repo.alignment_lock(REQUEST_KEY, timeout_seconds=0.3),
        ):
            pass
        assert excinfo.value.code == "backend_timeout"
    with repo.alignment_lock(REQUEST_KEY, timeout_seconds=2.0):
        pass


def test_source_lock_acquisition_is_bounded(migrated_engine: Engine) -> None:
    holder = PostgresRepository(migrated_engine)
    acquirer = PostgresRepository(migrated_engine)
    verifier = PostgresRepository(migrated_engine)
    policy = make_policy()
    registration = make_run(stage=RunStage.SOURCE_REGISTRATION)
    source = make_source(policy, registration.id)
    with holder.transaction():
        holder.add_policy(policy)
        holder.add_run(registration)
        holder.add_source(source)

    row_locked = threading.Event()
    release = threading.Event()
    outcome: dict[str, object] = {}

    def hold() -> None:
        with holder.transaction():
            holder.lock_sources([source.id])
            row_locked.set()
            # Held well beyond the acquiring side's configured limit.
            release.wait(timeout=JOIN_TIMEOUT)
            holder.set_source_status(source.id, SourceStatus.REVOKED, LATER)

    def attempt() -> None:
        assert row_locked.wait(timeout=JOIN_TIMEOUT)
        started = time.monotonic()
        try:
            with (
                acquirer.alignment_lock(REQUEST_KEY, timeout_seconds=JOIN_TIMEOUT),
                acquirer.transaction(),
            ):
                # Partial work precedes the blocked acquisition; none may survive.
                acquirer.add_evidence(make_evidence(source.id, registration))
                acquirer.lock_sources([source.id], timeout_seconds=ACQUISITION_TIMEOUT)
        except AlignmentFailed as exc:
            outcome["code"] = exc.code
            outcome["elapsed"] = time.monotonic() - started

    holder_thread = threading.Thread(target=hold)
    holder_thread.start()
    assert row_locked.wait(timeout=JOIN_TIMEOUT)
    acquirer_thread = threading.Thread(target=attempt)
    acquirer_thread.start()
    try:
        acquirer_thread.join(timeout=JOIN_TIMEOUT)
        # Bounded: the attempt failed on its own instead of blocking until released.
        assert not acquirer_thread.is_alive()
        assert outcome["code"] == "backend_timeout"
        # The configured limit is honored (>= it) and the wait is bounded (< join timeout).
        assert ACQUISITION_TIMEOUT <= outcome["elapsed"] < JOIN_TIMEOUT
        # The aborted transaction rolled back: no partial evidence was published.
        assert verifier.list_evidence_for_target(source.id) == []
        # The enclosing request lock was released normally after the inner failure.
        with verifier.alignment_lock(REQUEST_KEY, timeout_seconds=JOIN_TIMEOUT):
            pass
    finally:
        release.set()
        holder_thread.join(timeout=JOIN_TIMEOUT)
        acquirer_thread.join(timeout=JOIN_TIMEOUT)
        assert not holder_thread.is_alive()
        assert not acquirer_thread.is_alive()

    # After the holder's transaction ended, acquisition succeeds and the committed
    # revocation is already visible inside the acquiring transaction.
    with acquirer.transaction():
        acquirer.lock_sources([source.id], timeout_seconds=JOIN_TIMEOUT)
        assert acquirer.get_source(source.id).status is SourceStatus.REVOKED
    assert acquirer.get_source(source.id).status is SourceStatus.REVOKED


def test_revocation_and_commit_serialized(migrated_engine: Engine) -> None:
    revoker = PostgresRepository(migrated_engine)
    committer = PostgresRepository(migrated_engine)
    policy = make_policy()
    registration = make_run(stage=RunStage.SOURCE_REGISTRATION)
    source = make_source(policy, registration.id)
    with revoker.transaction():
        revoker.add_policy(policy)
        revoker.add_run(registration)
        revoker.add_source(source)

    row_locked = threading.Event()
    proceed = threading.Event()
    committed = threading.Event()
    second_locked = threading.Event()

    def revoke() -> None:
        with revoker.transaction():
            # Row locks survive until this transaction commits.
            revoker.lock_sources([source.id])
            row_locked.set()
            assert proceed.wait(timeout=JOIN_TIMEOUT)
            revoker.set_source_status(source.id, SourceStatus.REVOKED, LATER)
        committed.set()

    def commit_alignment() -> None:
        assert row_locked.wait(timeout=JOIN_TIMEOUT)
        with committer.transaction():
            committer.lock_sources([source.id])  # blocks until the revoker commits
            # The completed revocation is visible inside the acquiring transaction,
            # not only in a fresh read made after it has ended.
            assert committer.get_source(source.id).status is SourceStatus.REVOKED
            second_locked.set()

    revoker_thread = threading.Thread(target=revoke)
    revoker_thread.start()
    assert row_locked.wait(timeout=JOIN_TIMEOUT)
    committer_thread = threading.Thread(target=commit_alignment)
    committer_thread.start()
    committer_thread.join(timeout=0.5)
    # The committer is genuinely blocked on the same source rows, not merely slow to start.
    assert not second_locked.is_set()
    assert not committed.is_set()
    proceed.set()
    revoker_thread.join(timeout=JOIN_TIMEOUT)
    committer_thread.join(timeout=JOIN_TIMEOUT)
    assert not revoker_thread.is_alive()
    assert not committer_thread.is_alive()
    assert committed.is_set()
    assert second_locked.is_set()
    # The committer observed the completed revocation, not a pre-commit state.
    assert committer.get_source(source.id).status is SourceStatus.REVOKED


def test_two_requests_one_success(pg_repository: PostgresRepository, tmp_path: Path) -> None:
    """Concurrent identical Stage 5 requests publish and compute only once."""
    ctx = AppContext(
        repo=pg_repository,
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=lambda: datetime.now(UTC),
        new_id=new_id,
        actor="integration-test",
        code_revision="test",
    )
    source, target, segment = _ready(ctx, tmp_path)

    class _CountedLinks(_Links):
        def __init__(self):
            self.calls = 0
            self.lock = threading.Lock()
            self.both_requests_started = threading.Event()

        def align(self, groups, config):
            with self.lock:
                self.calls += 1
            assert self.both_requests_started.wait(timeout=JOIN_TIMEOUT)
            return super().align(groups, config)

    adapter = _CountedLinks()
    registry = VersionedRegistry((adapter,))
    requests_started = threading.Barrier(2)
    results = []
    failures = []

    def request() -> None:
        try:
            requests_started.wait(timeout=JOIN_TIMEOUT)
            adapter.both_requests_started.set()
            request_ctx = AppContext(
                repo=PostgresRepository(pg_repository._engine),
                raw_store=ctx.raw_store,
                artifact_store=ctx.artifact_store,
                clock=ctx.clock,
                new_id=ctx.new_id,
                actor=ctx.actor,
                code_revision=ctx.code_revision,
            )
            results.append(
                TokenAlignmentService(request_ctx, aligners=registry).align(
                    segment.run.id,
                    source_tokenization_run_id=source.tokenization_run_id,
                    target_tokenization_run_id=target.tokenization_run_id,
                    method="fixture@0.1.0",
                    config=AlignmentConfig(namespace="refs"),
                )
            )
        except BaseException as error:
            failures.append(error)

    first = threading.Thread(target=request)
    second = threading.Thread(target=request)
    first.start()
    second.start()
    first.join(timeout=JOIN_TIMEOUT)
    second.join(timeout=JOIN_TIMEOUT)
    assert not first.is_alive() and not second.is_alive()
    assert not failures
    assert len(results) == 2
    assert sorted(result.reused for result in results) == [False, True]
    assert len({result.run.id for result in results}) == 1
    assert adapter.calls == 1
    succeeded = pg_repository.list_runs_with_input(
        segment.run.id, RunStage.TOKEN_ALIGNMENT, RunStatus.SUCCEEDED
    )
    assert len(succeeded) == 1 and succeeded[0].id == results[0].run.id
    edge_sets = [
        {
            (edge.segment_alignment_id, edge.source_token_id, edge.target_token_id, edge.direction)
            for edge in pg_repository.list_token_alignment_edges_for_run(result.run.id)
        }
        for result in results
    ]
    assert edge_sets[0] == edge_sets[1]


def test_revocation_during_native_compute_blocks_commit(
    pg_repository: PostgresRepository, tmp_path: Path
) -> None:
    ctx = AppContext(
        repo=pg_repository,
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=lambda: datetime.now(UTC),
        new_id=new_id,
        actor="integration-test",
        code_revision="test",
    )
    source, target, segment = _ready(ctx, tmp_path)
    entered = threading.Event()
    release = threading.Event()

    class _BlockedLinks(_Links):
        def align(self, groups, config):
            entered.set()
            assert release.wait(timeout=JOIN_TIMEOUT)
            return super().align(groups, config)

    worker_repo = PostgresRepository(pg_repository._engine)
    worker_ctx = AppContext(
        repo=worker_repo,
        raw_store=ctx.raw_store,
        artifact_store=ctx.artifact_store,
        clock=ctx.clock,
        new_id=ctx.new_id,
        actor=ctx.actor,
        code_revision=ctx.code_revision,
    )
    service = TokenAlignmentService(worker_ctx, aligners=VersionedRegistry((_BlockedLinks(),)))
    audit_count = len(worker_repo.list_audit_events())
    started_runs = []
    original_start = service.recorder.start

    def capture_start(*args, **kwargs):
        run = original_start(*args, **kwargs)
        started_runs.append(run.id)
        return run

    service.recorder.start = capture_start
    failures = []

    def align() -> None:
        try:
            service.align(
                segment.run.id,
                source_tokenization_run_id=source.tokenization_run_id,
                target_tokenization_run_id=target.tokenization_run_id,
                method="fixture@0.1.0",
                config=AlignmentConfig(namespace="refs"),
            )
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=align)
    thread.start()
    assert entered.wait(timeout=JOIN_TIMEOUT)
    revoker = PostgresRepository(pg_repository._engine)
    with revoker.transaction():
        revoker.set_source_status(source.side.source_id, SourceStatus.REVOKED, datetime.now(UTC))
    release.set()
    thread.join(timeout=JOIN_TIMEOUT)
    assert not thread.is_alive()
    assert len(failures) == 1 and isinstance(failures[0], PolicyDenied)
    failed = worker_repo.get_run(started_runs[0])
    assert failed.status is RunStatus.FAILED and failed.error_type == "PolicyDenied"
    assert failed.error_message is None
    assert worker_repo.list_token_alignment_edges_for_run(failed.id) == []
    assert worker_repo.list_run_io(failed.id) == []
    assert (
        len(
            [
                event
                for event in worker_repo.list_audit_events()[audit_count:]
                if event.event_type is AuditEventType.POLICY_DENIED
            ]
        )
        == 1
    )
