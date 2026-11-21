"""Integration tests for morphology benchmark harness concurrency and row-locking (Gate 40).

Proves that:
1. When a withdrawal/revocation transaction holds source locks, a concurrent benchmark
   evaluation blocks on lock_sources, unblocks upon withdrawal commit, observes REVOKED,
   and raises PolicyDenied (no leak/stale execution).
2. When a withdrawal/revocation transaction holds source locks, a concurrent benchmark
   reuse check blocks on lock_sources, unblocks upon withdrawal commit, observes REVOKED,
   and raises PolicyDenied (no stale report return on reuse).
3. When a benchmark evaluation holds source locks during computation and publication,
   a concurrent withdrawal transaction is blocked until the benchmark commits.
"""

import itertools
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from langpipe.app_context import AppContext
from langpipe.domain.enums import AuditEventType, RunStatus, SourceStatus
from langpipe.domain.errors import PolicyDenied
from langpipe.domain.ids import new_id
from langpipe.evaluation.morphology_service import (
    MorphologyBenchmarkSummary,
    evaluate_morphology_benchmark,
)
from langpipe.morphology.service import induce_morphology
from langpipe.storage.db.repository import PostgresRepository
from langpipe.storage.objects.local import LocalContentStore
from tests.service.test_morph_benchmark_service import SAMPLE_TOOLBOX, _setup_pipeline

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]
JOIN_TIMEOUT = 10.0


def _context_over(engine: Engine, tmp_path: Path) -> AppContext:
    ticks = itertools.count()
    return AppContext(
        repo=PostgresRepository(engine),
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=next(ticks)),
        new_id=new_id,
        actor="test-actor",
        code_revision="test-rev",
    )


def _wait_for_blocked_by(engine: Engine, holder_pid: int, timeout: float = 5.0) -> list[int]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            pids = (
                conn.execute(
                    text(
                        "SELECT pid FROM pg_stat_activity "
                        "WHERE :holder_pid = ANY(pg_blocking_pids(pid))"
                    ),
                    {"holder_pid": holder_pid},
                )
                .scalars()
                .all()
            )
            if pids:
                return [int(p) for p in pids]
        time.sleep(0.05)
    return []


def test_benchmark_evaluation_blocks_on_overlapping_withdrawal_and_denies(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    """Outcome 1a: Withdrawal starts first; benchmark blocks and raises PolicyDenied."""
    ctx = _context_over(migrated_engine, tmp_path)
    src_id, igt_run_id, tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-concurr-eval",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    unsegmented_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="unsegmented@0.1.0",
    )

    revoker_repo = PostgresRepository(migrated_engine)
    bench_ctx = _context_over(migrated_engine, tmp_path)

    # Instrument benchmark repo lock_sources to verify arrival at DB lock
    bench_attempting_lock = threading.Event()
    real_bench_lock = bench_ctx.repo.lock_sources

    def tracking_lock(source_ids: Any, **kwargs: Any) -> None:
        bench_attempting_lock.set()
        real_bench_lock(source_ids, **kwargs)

    bench_ctx.repo.lock_sources = tracking_lock

    row_locked = threading.Event()
    proceed = threading.Event()
    revocation_committed = threading.Event()
    bench_outcome: dict[str, BaseException | None] = {}

    def revoke_worker() -> None:
        with revoker_repo.transaction():
            revoker_repo.lock_sources([src_id])
            row_locked.set()
            assert proceed.wait(timeout=JOIN_TIMEOUT)
            revoker_repo.set_source_status(src_id, SourceStatus.REVOKED, at=ctx.clock())
        revocation_committed.set()

    def bench_worker() -> None:
        assert row_locked.wait(timeout=JOIN_TIMEOUT)
        try:
            evaluate_morphology_benchmark(
                bench_ctx,
                evaluated_run_ids=[unsegmented_res.run.id],
                gold=igt_run_id,
                refs=["IGT-2"],
            )
            bench_outcome["error"] = None
        except BaseException as exc:
            bench_outcome["error"] = exc

    revoker_thread = threading.Thread(target=revoke_worker)
    bench_thread = threading.Thread(target=bench_worker)

    revoker_thread.start()
    assert row_locked.wait(timeout=JOIN_TIMEOUT)

    bench_thread.start()
    assert bench_attempting_lock.wait(timeout=JOIN_TIMEOUT)
    bench_thread.join(timeout=0.4)
    # Benchmark must be blocked waiting on the locked source row in PostgreSQL
    assert bench_thread.is_alive()
    assert "error" not in bench_outcome

    # Unblock the revoker so it commits revocation
    proceed.set()
    revoker_thread.join(timeout=JOIN_TIMEOUT)
    bench_thread.join(timeout=JOIN_TIMEOUT)

    assert not revoker_thread.is_alive()
    assert not bench_thread.is_alive()
    assert revocation_committed.is_set()

    # Benchmark unblocked after revocation commit, observed REVOKED under lock, raised PolicyDenied
    assert isinstance(bench_outcome.get("error"), PolicyDenied)
    denials = [
        ev
        for ev in bench_ctx.repo.list_audit_events()
        if ev.event_type is AuditEventType.POLICY_DENIED
    ]
    assert len(denials) >= 1


def test_benchmark_reuse_blocks_on_overlapping_withdrawal_and_denies(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    """Outcome 1b: Withdrawal starts first during reuse; benchmark blocks and denies."""
    ctx = _context_over(migrated_engine, tmp_path)
    src_id, igt_run_id, tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-concurr-reuse",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    unsegmented_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="unsegmented@0.1.0",
    )

    # Initial evaluation succeeds
    first_summary = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[unsegmented_res.run.id],
        gold=igt_run_id,
        refs=["IGT-2"],
    )
    assert first_summary.reused is False

    revoker_repo = PostgresRepository(migrated_engine)
    bench_ctx = _context_over(migrated_engine, tmp_path)

    bench_attempting_lock = threading.Event()
    real_bench_lock = bench_ctx.repo.lock_sources

    def tracking_lock(source_ids: Any, **kwargs: Any) -> None:
        bench_attempting_lock.set()
        real_bench_lock(source_ids, **kwargs)

    bench_ctx.repo.lock_sources = tracking_lock

    row_locked = threading.Event()
    proceed = threading.Event()
    revocation_committed = threading.Event()
    bench_outcome: dict[str, BaseException | None] = {}

    def revoke_worker() -> None:
        with revoker_repo.transaction():
            revoker_repo.lock_sources([src_id])
            row_locked.set()
            assert proceed.wait(timeout=JOIN_TIMEOUT)
            revoker_repo.set_source_status(src_id, SourceStatus.REVOKED, at=ctx.clock())
        revocation_committed.set()

    def bench_worker() -> None:
        assert row_locked.wait(timeout=JOIN_TIMEOUT)
        try:
            evaluate_morphology_benchmark(
                bench_ctx,
                evaluated_run_ids=[unsegmented_res.run.id],
                gold=igt_run_id,
                refs=["IGT-2"],
            )
            bench_outcome["error"] = None
        except BaseException as exc:
            bench_outcome["error"] = exc

    revoker_thread = threading.Thread(target=revoke_worker)
    bench_thread = threading.Thread(target=bench_worker)

    revoker_thread.start()
    assert row_locked.wait(timeout=JOIN_TIMEOUT)

    bench_thread.start()
    assert bench_attempting_lock.wait(timeout=JOIN_TIMEOUT)
    bench_thread.join(timeout=0.4)
    # Benchmark reuse path must be blocked waiting on the locked source row
    assert bench_thread.is_alive()
    assert "error" not in bench_outcome

    # Unblock the revoker so it commits revocation
    proceed.set()
    revoker_thread.join(timeout=JOIN_TIMEOUT)
    bench_thread.join(timeout=JOIN_TIMEOUT)

    assert not revoker_thread.is_alive()
    assert not bench_thread.is_alive()
    assert revocation_committed.is_set()

    # Reuse path unblocked, observed REVOKED under lock, and raised PolicyDenied
    assert isinstance(bench_outcome.get("error"), PolicyDenied)


def test_benchmark_holds_source_lock_blocking_concurrent_withdrawal(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    """Outcome 2: Benchmark holds source lock; concurrent withdrawal is blocked until commit."""
    ctx = _context_over(migrated_engine, tmp_path)
    src_id, igt_run_id, tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-concurr-order-b",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    unsegmented_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="unsegmented@0.1.0",
    )

    bench_ctx = _context_over(migrated_engine, tmp_path)
    revoker_repo = PostgresRepository(migrated_engine)

    bench_in_before_commit = threading.Event()
    allow_commit = threading.Event()

    bench_holder_pid: int | None = None
    bench_xid: int | None = None
    orig_bench_tx = bench_ctx.repo.transaction

    # Controlled pause at the commit boundary: after all benchmark application code has completed,
    # right inside session.commit() before the COMMIT packet is transmitted to PostgreSQL.
    @contextmanager
    def hook_bench_tx() -> Iterator[None]:
        with orig_bench_tx():
            session = bench_ctx.repo._session
            assert session is not None
            nonlocal bench_holder_pid, bench_xid
            bench_holder_pid = int(session.execute(text("SELECT pg_backend_pid()")).scalar())
            bench_xid = int(session.execute(text("SELECT pg_current_xact_id()")).scalar())

            @event.listens_for(session, "before_commit")
            def on_before_commit(_s: Any) -> None:
                bench_in_before_commit.set()
                assert allow_commit.wait(timeout=JOIN_TIMEOUT)

            yield

    bench_ctx.repo.transaction = hook_bench_tx  # type: ignore[method-assign]

    revoker_pid: int | None = None
    orig_revoker_tx = revoker_repo.transaction

    @contextmanager
    def capturing_revoker_tx() -> Iterator[None]:
        nonlocal revoker_pid
        with orig_revoker_tx():
            assert revoker_repo._session is not None
            revoker_pid = int(
                revoker_repo._session.execute(text("SELECT pg_backend_pid()")).scalar()
            )
            yield

    revoker_repo.transaction = capturing_revoker_tx  # type: ignore[method-assign]

    revoker_attempting_lock = threading.Event()
    revoker_locked = threading.Event()
    real_revoker_lock = revoker_repo.lock_sources
    revoker_observations: dict[str, Any] = {}
    bench_summary: dict[str, MorphologyBenchmarkSummary | None] = {}

    def revoker_worker() -> None:
        assert bench_in_before_commit.wait(timeout=JOIN_TIMEOUT)
        with revoker_repo.transaction():
            revoker_attempting_lock.set()
            real_revoker_lock([src_id])
            # Database-observed transaction ordering at the instant the lock is granted:
            # 1. Synchronization proof: allow_commit MUST already have been granted by test
            assert allow_commit.is_set(), (
                "Revoker acquired lock before benchmark transaction was released to commit!"
            )
            assert revoker_repo._session is not None
            # 2. Database commit status: benchmark transaction MUST report 'committed' in PostgreSQL
            bench_status = revoker_repo._session.execute(
                text("SELECT pg_xact_status(cast(:bench_xid as text)::xid8)"),
                {"bench_xid": str(bench_xid)},
            ).scalar()
            assert bench_status == "committed", (
                f"Benchmark transaction {bench_xid} was not committed: {bench_status}"
            )
            revoker_observations["bench_status"] = bench_status

            # 3. Benchmark run MUST already be committed in PostgreSQL with SUCCEEDED status
            committed_eval_runs = (
                revoker_repo._session.execute(
                    text(
                        "SELECT id, status, finished_at FROM processing_run "
                        "WHERE stage = 'evaluation'"
                    )
                )
                .mappings()
                .all()
            )
            revoker_observations["committed_runs"] = committed_eval_runs
            if committed_eval_runs:
                run_id = committed_eval_runs[0]["id"]
                revoker_observations["committed_artifacts"] = (
                    revoker_repo._session.execute(
                        text("SELECT id FROM artifact WHERE run_id = :run_id"),
                        {"run_id": run_id},
                    )
                    .scalars()
                    .all()
                )
            revoker_observations["revoker_xid"] = int(
                revoker_repo._session.execute(text("SELECT pg_current_xact_id()")).scalar()
            )
            revoker_locked.set()
            revoker_repo.set_source_status(src_id, SourceStatus.REVOKED, at=ctx.clock())

    def bench_worker() -> None:
        summary = evaluate_morphology_benchmark(
            bench_ctx,
            evaluated_run_ids=[unsegmented_res.run.id],
            gold=igt_run_id,
            refs=["IGT-2"],
        )
        bench_summary["summary"] = summary

    bench_thread = threading.Thread(target=bench_worker)
    revoker_thread = threading.Thread(target=revoker_worker)

    bench_thread.start()
    assert bench_in_before_commit.wait(timeout=JOIN_TIMEOUT)
    assert bench_holder_pid is not None
    assert bench_xid is not None

    revoker_thread.start()
    assert revoker_attempting_lock.wait(timeout=JOIN_TIMEOUT)

    # 1. Database-observed lock blocking:
    # Assert PostgreSQL kernel has blocked revoker_pid waiting specifically on bench_holder_pid
    # while benchmark is paused in before_commit (all application work finished, commit withheld)
    blocked = _wait_for_blocked_by(migrated_engine, bench_holder_pid, timeout=JOIN_TIMEOUT)
    assert revoker_pid is not None, "Revoker PID must be captured"
    assert revoker_pid in blocked, (
        f"Revoker PID {revoker_pid} must be in PostgreSQL blocked list {blocked} "
        f"held by benchmark PID {bench_holder_pid}"
    )
    assert revoker_thread.is_alive()
    assert not revoker_locked.is_set()
    assert not allow_commit.is_set()
    assert "summary" not in bench_summary

    # 2. Release commit: session transmits COMMIT to PostgreSQL, commit finishes, lock releases
    allow_commit.set()
    bench_thread.join(timeout=JOIN_TIMEOUT)
    revoker_thread.join(timeout=JOIN_TIMEOUT)

    assert not bench_thread.is_alive()
    assert not revoker_thread.is_alive()
    assert revoker_locked.is_set()

    # 3. Database-observed transaction ordering verified:
    assert revoker_observations.get("bench_status") == "committed"

    committed_runs = revoker_observations.get("committed_runs", [])
    assert len(committed_runs) == 1, (
        "Benchmark run must be committed in PostgreSQL before revoker acquires source lock"
    )
    assert committed_runs[0]["status"] == RunStatus.SUCCEEDED.value
    assert committed_runs[0]["finished_at"] is not None

    committed_arts = revoker_observations.get("committed_artifacts", [])
    assert len(committed_arts) == 1, (
        "Benchmark report artifact must be committed in PostgreSQL before revoker acquires lock"
    )

    # PostgreSQL transaction ID ordering: benchmark xid preceded revoker xid
    revoker_xid = revoker_observations.get("revoker_xid")
    assert revoker_xid is not None and bench_xid < revoker_xid, (
        f"Benchmark xid {bench_xid} must precede revoker xid {revoker_xid}"
    )

    # Benchmark completed successfully before revocation was allowed to proceed
    summary = bench_summary["summary"]
    assert summary is not None
    assert summary.run.status is RunStatus.SUCCEEDED
    assert summary.reused is False
