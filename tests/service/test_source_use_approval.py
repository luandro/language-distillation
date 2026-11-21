"""Service tests for record_approval across memory and PostgreSQL backends (WP5.5)."""

import itertools
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    ApprovalAction,
    AuditEventType,
    Operation,
    PolicyDecision,
    PolicyMode,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
    SourceType,
)
from langpipe.domain.errors import PolicyConflict, PolicyDenied
from langpipe.domain.ids import new_id
from langpipe.domain.models.source import RawBlob, Source
from langpipe.extraction.plain_lines import PlainLinesExtractor
from langpipe.extraction.service import extract_source
from langpipe.governance.approvals import (
    effective_policy,
    record_approval,
)
from langpipe.ingest.wordlist import WordlistExtractor
from langpipe.ingestion.runs import RunRecorder
from langpipe.review.authority import ROLE_GOVERNANCE_STEWARD, ReviewAuthorityRegistry
from langpipe.review.base import UnauthorizedReviewer
from langpipe.segmentation.recorder import ObservationRecorder, SegmentInput
from langpipe.storage.db.repository import PostgresRepository
from langpipe.storage.objects.local import LocalContentStore
from langpipe.storage.repository import Repository
from tests.contract.builders import (
    NOW,
    make_policy,
    make_run,
    make_source,
    make_source_object,
    unique_run_key,
)

_T0 = datetime(2026, 2, 1, 10, 0, tzinfo=UTC)
_KEYS = itertools.count()


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def repo_backend(request: pytest.FixtureRequest) -> Iterator[Repository]:
    if request.param == "memory":
        from langpipe.storage.memory import InMemoryRepository

        yield InMemoryRepository()
        return
    yield request.getfixturevalue("pg_repository")


@pytest.fixture
def registry() -> ReviewAuthorityRegistry:
    reg = ReviewAuthorityRegistry()
    reg.register("steward-mzr", ROLE_GOVERNANCE_STEWARD, ["mzr"])
    reg.register("other-steward", ROLE_GOVERNANCE_STEWARD, ["por"])
    reg.register("regular-reviewer", "linguist", ["mzr"])
    return reg


def _create_source(
    repo: Repository,
    mode: PolicyMode = PolicyMode.REVIEW_REQUIRED,
    lang: str = "mzr",
    source_type: SourceType = SourceType.MONOLINGUAL_TEXT,
) -> Source:
    idx = next(_KEYS)
    reg_run = make_run(
        stage=RunStage.SOURCE_REGISTRATION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"src-reg-{idx}"),
    )
    policy = make_policy(mode=mode)
    source = make_source(
        policy,
        reg_run.id,
        languages=(lang,),
        key=f"src-key-{idx}",
        source_type=source_type,
    )
    with repo.transaction():
        repo.add_run(reg_run)
        repo.add_policy(policy)
        repo.add_source(source)
    return source


def test_record_approval_grant_succeeds_and_creates_records(
    repo_backend: Repository, registry: ReviewAuthorityRegistry
) -> None:
    source = _create_source(repo_backend, mode=PolicyMode.REVIEW_REQUIRED)
    approval = record_approval(
        repo_backend,
        source_id=source.id,
        operation=Operation.EXTRACT,
        action=ApprovalAction.GRANT,
        approver_id="steward-mzr",
        basis="Approved for M5 golden IGT extraction",
        authority_registry=registry,
        clock=lambda: _T0,
        code_revision="git-test-rev",
    )

    assert approval.source_id == source.id
    assert approval.operation is Operation.EXTRACT
    assert approval.action is ApprovalAction.GRANT
    assert approval.approver_id == "steward-mzr"
    assert approval.approver_role == ROLE_GOVERNANCE_STEWARD
    assert approval.basis == "Approved for M5 golden IGT extraction"
    assert approval.created_at == _T0

    # 1. Stored approval
    stored = repo_backend.list_source_use_approvals(source.id)
    assert len(stored) == 1
    assert stored[0].id == approval.id

    # 2. Created creator run
    run = repo_backend.get_run(approval.run_id)
    assert run.stage is RunStage.HUMAN_REVIEW
    assert run.status is RunStatus.SUCCEEDED
    assert run.started_at == _T0
    assert run.finished_at == _T0

    # 3. ProcessingRunIo linkages
    ios = repo_backend.list_run_io(run.id)
    assert (source.id, RunIoRole.INPUT) in ios
    assert (approval.id, RunIoRole.OUTPUT) in ios

    # 4. Audit event
    events = [
        e
        for e in repo_backend.list_audit_events()
        if e.subject_id == source.id and e.event_type is AuditEventType.SOURCE_USE_APPROVED
    ]
    assert len(events) == 1
    assert events[0].actor == "steward-mzr"
    assert events[0].run_id == run.id

    # 5. Effective policy now allows Operation.EXTRACT
    eff = effective_policy(repo_backend, source)
    assert Operation.EXTRACT in eff.allow


def test_record_approval_withdraw_succeeds(
    repo_backend: Repository, registry: ReviewAuthorityRegistry
) -> None:
    source = _create_source(repo_backend, mode=PolicyMode.REVIEW_REQUIRED)
    # First grant
    record_approval(
        repo_backend,
        source_id=source.id,
        operation=Operation.EXTRACT,
        action=ApprovalAction.GRANT,
        approver_id="steward-mzr",
        basis="Initial grant",
        authority_registry=registry,
        clock=lambda: _T0,
    )
    # Then withdraw
    t1 = datetime(2026, 2, 1, 11, 0, tzinfo=UTC)
    withdrawn = record_approval(
        repo_backend,
        source_id=source.id,
        operation=Operation.EXTRACT,
        action=ApprovalAction.WITHDRAW,
        approver_id="steward-mzr",
        basis="Withdrawing approval per steward decision",
        authority_registry=registry,
        clock=lambda: t1,
    )
    assert withdrawn.action is ApprovalAction.WITHDRAW

    stored = repo_backend.list_source_use_approvals(source.id)
    assert len(stored) == 2

    # Effective policy no longer allows EXTRACT
    eff = effective_policy(repo_backend, source)
    assert Operation.EXTRACT not in eff.allow

    # Audit event is SOURCE_USE_WITHDRAWN
    events = [
        e
        for e in repo_backend.list_audit_events()
        if e.subject_id == source.id and e.event_type is AuditEventType.SOURCE_USE_WITHDRAWN
    ]
    assert len(events) == 1


def test_unauthorized_approver_raises_unauthorized_reviewer(
    repo_backend: Repository, registry: ReviewAuthorityRegistry
) -> None:
    source = _create_source(repo_backend, mode=PolicyMode.REVIEW_REQUIRED, lang="mzr")

    # Wrong role
    with pytest.raises(UnauthorizedReviewer):
        record_approval(
            repo_backend,
            source_id=source.id,
            operation=Operation.EXTRACT,
            action=ApprovalAction.GRANT,
            approver_id="regular-reviewer",
            approver_role="linguist",
            basis="Unauthorized role",
            authority_registry=registry,
        )

    # Authorized for another language (por), not source language (mzr)
    with pytest.raises(UnauthorizedReviewer):
        record_approval(
            repo_backend,
            source_id=source.id,
            operation=Operation.EXTRACT,
            action=ApprovalAction.GRANT,
            approver_id="other-steward",
            basis="Wrong language scope",
            authority_registry=registry,
        )

    # Nothing written
    assert repo_backend.list_source_use_approvals(source.id) == []


def test_unapprovable_operation_raises_policy_conflict(
    repo_backend: Repository, registry: ReviewAuthorityRegistry
) -> None:
    source = _create_source(repo_backend, mode=PolicyMode.REVIEW_REQUIRED)

    # DIRECT_TRAINING is not in APPROVABLE_OPERATIONS
    with pytest.raises(PolicyConflict):
        record_approval(
            repo_backend,
            source_id=source.id,
            operation=Operation.DIRECT_TRAINING,
            action=ApprovalAction.GRANT,
            approver_id="steward-mzr",
            basis="Training not allowed in M5",
            authority_registry=registry,
        )

    assert repo_backend.list_source_use_approvals(source.id) == []


def test_operation_with_non_review_baseline_raises_policy_conflict(
    repo_backend: Repository, registry: ReviewAuthorityRegistry
) -> None:
    # Under DIRECT, EXTRACT is Baseline.ALLOW (not REVIEW)
    source = _create_source(repo_backend, mode=PolicyMode.DIRECT)

    with pytest.raises(PolicyConflict):
        record_approval(
            repo_backend,
            source_id=source.id,
            operation=Operation.EXTRACT,
            action=ApprovalAction.GRANT,
            approver_id="steward-mzr",
            basis="Already allowed under direct",
            authority_registry=registry,
        )

    assert repo_backend.list_source_use_approvals(source.id) == []


def test_empty_basis_raises_value_error(
    repo_backend: Repository, registry: ReviewAuthorityRegistry
) -> None:
    source = _create_source(repo_backend, mode=PolicyMode.REVIEW_REQUIRED)

    with pytest.raises(ValueError, match="basis must be nonempty"):
        record_approval(
            repo_backend,
            source_id=source.id,
            operation=Operation.EXTRACT,
            action=ApprovalAction.GRANT,
            approver_id="steward-mzr",
            basis="   ",
            authority_registry=registry,
        )

    assert repo_backend.list_source_use_approvals(source.id) == []


def test_record_approval_enforces_timestamp_monotonicity_on_clock_skew(
    repo_backend: Repository, registry: ReviewAuthorityRegistry
) -> None:
    source = _create_source(repo_backend, mode=PolicyMode.REVIEW_REQUIRED)
    # 1. First grant at _T0
    grant = record_approval(
        repo_backend,
        source_id=source.id,
        operation=Operation.EXTRACT,
        action=ApprovalAction.GRANT,
        approver_id="steward-mzr",
        basis="Initial grant",
        authority_registry=registry,
        clock=lambda: _T0,
    )
    assert grant.created_at == _T0

    # 2. Withdrawal with tied clock (_T0)
    withdraw_tied = record_approval(
        repo_backend,
        source_id=source.id,
        operation=Operation.EXTRACT,
        action=ApprovalAction.WITHDRAW,
        approver_id="steward-mzr",
        basis="Withdraw with tied clock",
        authority_registry=registry,
        clock=lambda: _T0,
    )
    # Strict monotonicity: advanced past latest existing
    assert withdraw_tied.created_at > grant.created_at
    eff_after_withdraw = effective_policy(repo_backend, source)
    assert Operation.EXTRACT not in eff_after_withdraw.allow

    # 3. Re-grant with backward skewed clock (_T0 - 100s)
    skewed_backwards = _T0 - timedelta(seconds=100)
    regrant = record_approval(
        repo_backend,
        source_id=source.id,
        operation=Operation.EXTRACT,
        action=ApprovalAction.GRANT,
        approver_id="steward-mzr",
        basis="Re-grant with backwards clock",
        authority_registry=registry,
        clock=lambda: skewed_backwards,
    )
    assert regrant.created_at > withdraw_tied.created_at
    eff_after_regrant = effective_policy(repo_backend, source)
    assert Operation.EXTRACT in eff_after_regrant.allow


def _wait_for_blocked_by(engine: Engine, holder_pid: int, timeout: float = 5.0) -> list[int]:
    deadline = time.time() + timeout
    while time.time() < deadline:
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


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
def test_recorder_standalone_locking_on_postgres(
    pg_repository: PostgresRepository,
    registry: ReviewAuthorityRegistry,
) -> None:
    """Proves standalone ObservationRecorder calls acquire source locks in their own scope."""
    source = _create_source(pg_repository, mode=PolicyMode.REVIEW_REQUIRED)
    record_approval(
        pg_repository,
        source_id=source.id,
        operation=Operation.EXTRACT,
        action=ApprovalAction.GRANT,
        approver_id="steward-mzr",
        basis="Grant for recorder",
        authority_registry=registry,
    )
    run = make_run(
        stage=RunStage.EXTRACTION,
        status=RunStatus.RUNNING,
        run_key=unique_run_key("rec-standalone"),
    )
    obj = make_source_object(source, source.registration_run_id)
    with pg_repository.transaction():
        pg_repository.add_run(run)
        pg_repository.add_source_object(obj)

    # Standalone call without an outer transaction or unit_of_work
    recorder = ObservationRecorder(pg_repository, lambda: NOW, new_id)
    segments = recorder.record_segments(
        run_id=run.id,
        source_object_id=obj.id,
        segments=[SegmentInput(ordinal=0, language="mzr", locator={"line": 1}, raw_text="kanu")],
    )
    assert len(segments) == 1
    assert pg_repository.get_segment(segments[0].id).raw_text == "kanu"


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
def test_withdrawal_and_governed_operation_serialize_on_postgres(
    pg_repository: PostgresRepository,
    registry: ReviewAuthorityRegistry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves withdrawal and governed operations serialize via source row locks on PostgreSQL.

    1. When a production governed operation (extract_source) holds lock_sources across extractors,
       record_approval(WITHDRAW) blocks on the lock until extraction commits.
    2. When record_approval(WITHDRAW) holds lock_sources, production extract_source blocks on
       the lock until withdrawal commits, then unblocks, rechecks authorization under the lock,
       and raises PolicyDenied without leaking segments or decoding raw content.
    """
    raw_store = LocalContentStore(tmp_path / "raw")
    artifact_store = LocalContentStore(tmp_path / "artifacts")
    content = b"Line 1\nLine 2\n"
    stored_raw = raw_store.put_bytes(content)

    source = _create_source(pg_repository, mode=PolicyMode.REVIEW_REQUIRED)
    obj = make_source_object(
        source,
        source.registration_run_id,
        sha256=stored_raw.sha256,
        size_bytes=stored_raw.size_bytes,
        media_type="text/plain",
    )
    ingest_run = make_run(
        stage=RunStage.RAW_INGESTION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key("ingest-concur"),
    )
    blob = RawBlob(
        sha256=stored_raw.sha256,
        size_bytes=stored_raw.size_bytes,
        storage_backend="local",
        stored_at=NOW,
        ingestion_run_id=ingest_run.id,
    )
    with pg_repository.transaction():
        pg_repository.add_run(ingest_run)
        pg_repository.add_raw_blob(blob)
        pg_repository.add_source_object(obj)
        pg_repository.add_run_io(ingest_run.id, obj.id, RunIoRole.OUTPUT)
        pg_repository.set_source_status(source.id, SourceStatus.INGESTED, NOW)

    # 1. Grant EXTRACT initially
    record_approval(
        pg_repository,
        source_id=source.id,
        operation=Operation.EXTRACT,
        action=ApprovalAction.GRANT,
        approver_id="steward-mzr",
        basis="Grant before concurrency test",
        authority_registry=registry,
    )
    assert Operation.EXTRACT in effective_policy(pg_repository, source).allow

    # Scenario 1: Production extract_source holds lock across extractors and writes
    # -> record_approval(WITHDRAW) blocks on lock specifically correlated via pg_blocking_pids
    # -> extract_source commits -> Withdrawer unblocks and commits
    inside = threading.Event()
    release = threading.Event()
    completed: list[str] = []
    errors: list[BaseException] = []
    holder_pid: int | None = None

    original_extract = PlainLinesExtractor.extract

    def spy_extract(*args: object, **kwargs: object) -> object:
        nonlocal holder_pid
        # The extraction unit_of_work session holds the lock
        holder_pid = ctx_extract.repo._session.execute(text("SELECT pg_backend_pid()")).scalar()
        inside.set()
        assert release.wait(timeout=10.0), "Release timed out"
        return original_extract(*args, **kwargs)

    monkeypatch.setattr(PlainLinesExtractor, "extract", spy_extract)

    ctx_extract = AppContext(
        repo=PostgresRepository(pg_repository._engine),
        raw_store=raw_store,
        artifact_store=artifact_store,
        clock=lambda: NOW,
        new_id=new_id,
        actor="extractor-actor",
        code_revision="rev-test",
    )
    withdrawer = PostgresRepository(pg_repository._engine)
    withdrawer_pid: int | None = None
    orig_tx1 = withdrawer.transaction

    @contextmanager
    def capturing_withdrawer_tx() -> Iterator[None]:
        nonlocal withdrawer_pid
        with orig_tx1():
            assert withdrawer._session is not None
            withdrawer_pid = int(
                withdrawer._session.execute(text("SELECT pg_backend_pid()")).scalar()
            )
            yield

    monkeypatch.setattr(withdrawer, "transaction", capturing_withdrawer_tx)

    def run_extraction() -> None:
        try:
            res = extract_source(ctx_extract, source.id)
            assert res.run.status is RunStatus.SUCCEEDED
            completed.append("extract_succeeded")
        except BaseException as exc:
            errors.append(exc)

    def run_withdrawer() -> None:
        assert inside.wait(timeout=10.0)
        try:
            record_approval(
                withdrawer,
                source_id=source.id,
                operation=Operation.EXTRACT,
                action=ApprovalAction.WITHDRAW,
                approver_id="steward-mzr",
                basis="Withdrawal",
                authority_registry=registry,
            )
            completed.append("withdrawn")
        except BaseException as exc:
            errors.append(exc)

    t_ext = threading.Thread(target=run_extraction)
    t_with = threading.Thread(target=run_withdrawer)
    t_ext.start()
    t_with.start()
    try:
        assert inside.wait(timeout=10.0), f"inside timed out. errors={errors}"
        assert holder_pid is not None
        # Verify withdrawer is specifically blocked by holder_pid
        blocked = _wait_for_blocked_by(pg_repository._engine, holder_pid, timeout=5.0)
        assert withdrawer_pid is not None, "Withdrawer PID must be captured"
        assert withdrawer_pid in blocked, (
            f"Withdrawer PID {withdrawer_pid} must be in blocked list {blocked} "
            f"by holder {holder_pid}"
        )
        assert completed == [], "Withdrawer ran ahead of governed lock"
    finally:
        release.set()
    t_ext.join(timeout=10.0)
    t_with.join(timeout=10.0)
    assert not t_ext.is_alive() and not t_with.is_alive()
    assert errors == []
    assert completed == ["extract_succeeded", "withdrawn"]
    assert Operation.EXTRACT not in effective_policy(pg_repository, source).allow
    # Ensure segments were stored by extract_source
    assert len(pg_repository.list_segments(obj.id)) == 2

    # Scenario 2: Withdrawer holds lock during withdrawal
    # -> extract_source blocks on lock correlated via pg_blocking_pids
    # -> Withdrawer commits
    # -> Governed operation unblocks, rechecks authorization under lock, and is denied
    monkeypatch.undo()

    record_approval(
        pg_repository,
        source_id=source.id,
        operation=Operation.EXTRACT,
        action=ApprovalAction.GRANT,
        approver_id="steward-mzr",
        basis="Re-grant",
        authority_registry=registry,
    )
    assert Operation.EXTRACT in effective_policy(pg_repository, source).allow

    withdrawer2 = PostgresRepository(pg_repository._engine)
    ctx_extract2 = AppContext(
        repo=PostgresRepository(pg_repository._engine),
        raw_store=raw_store,
        artifact_store=artifact_store,
        clock=lambda: NOW,
        new_id=new_id,
        actor="extractor-actor-2",
        code_revision="rev-test-2",
    )
    extractor2_pid: int | None = None
    orig_tx2 = ctx_extract2.repo.transaction

    @contextmanager
    def capturing_extractor_tx() -> Iterator[None]:
        nonlocal extractor2_pid
        with orig_tx2():
            assert ctx_extract2.repo._session is not None
            extractor2_pid = int(
                ctx_extract2.repo._session.execute(text("SELECT pg_backend_pid()")).scalar()
            )
            yield

    monkeypatch.setattr(ctx_extract2.repo, "transaction", capturing_extractor_tx)

    w_inside = threading.Event()
    w_release = threading.Event()
    completed2: list[str] = []
    errors2: list[BaseException] = []
    withdrawer_pid: int | None = None

    def withdraw_clock() -> datetime:
        nonlocal withdrawer_pid
        withdrawer_pid = withdrawer2._session.execute(text("SELECT pg_backend_pid()")).scalar()
        w_inside.set()
        assert w_release.wait(timeout=10.0), "Withdraw release timed out"
        return datetime.now(UTC)

    def run_withdrawer2() -> None:
        try:
            record_approval(
                withdrawer2,
                source_id=source.id,
                operation=Operation.EXTRACT,
                action=ApprovalAction.WITHDRAW,
                approver_id="steward-mzr",
                basis="Scenario 2 withdraw",
                authority_registry=registry,
                clock=withdraw_clock,
            )
            completed2.append("withdrawn2")
        except BaseException as exc:
            errors2.append(exc)

    def run_extract2() -> None:
        assert w_inside.wait(timeout=10.0)
        try:
            extract_source(ctx_extract2, source.id)
            completed2.append("extract_unexpectedly_succeeded")
        except PolicyDenied:
            completed2.append("extract_policy_denied")
        except BaseException as exc:
            errors2.append(exc)

    t_w2 = threading.Thread(target=run_withdrawer2)
    t_e2 = threading.Thread(target=run_extract2)
    t_w2.start()
    t_e2.start()
    try:
        assert w_inside.wait(timeout=10.0)
        assert withdrawer_pid is not None
        # Verify extract_source is specifically blocked by withdrawer_pid
        blocked = _wait_for_blocked_by(pg_repository._engine, withdrawer_pid, timeout=5.0)
        assert extractor2_pid is not None, "extract_source PID must be captured"
        assert extractor2_pid in blocked, (
            f"extract_source PID {extractor2_pid} must be in blocked list {blocked} "
            f"by holder {withdrawer_pid}"
        )
        assert completed2 == [], "extract_source ran before withdrawal completed"
    finally:
        w_release.set()
    t_w2.join(timeout=10.0)
    t_e2.join(timeout=10.0)
    assert not t_w2.is_alive() and not t_e2.is_alive()
    assert errors2 == []
    assert completed2 == ["withdrawn2", "extract_policy_denied"]


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
def test_withdrawal_between_initial_gate_and_execution_caught_by_second_gate_on_postgres(
    pg_repository: PostgresRepository,
    registry: ReviewAuthorityRegistry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves withdrawal between initial gate and execution is caught by the second gate."""
    raw_store = LocalContentStore(tmp_path / "raw")
    artifact_store = LocalContentStore(tmp_path / "artifacts")
    stored_raw = raw_store.put_bytes(b"Line 1\nLine 2\n")

    source = _create_source(pg_repository, mode=PolicyMode.REVIEW_REQUIRED)
    obj = make_source_object(
        source,
        source.registration_run_id,
        sha256=stored_raw.sha256,
        size_bytes=stored_raw.size_bytes,
        media_type="text/plain",
    )
    ingest_run = make_run(
        stage=RunStage.RAW_INGESTION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key("ingest-gate2"),
    )
    blob = RawBlob(
        sha256=stored_raw.sha256,
        size_bytes=stored_raw.size_bytes,
        storage_backend="local",
        stored_at=NOW,
        ingestion_run_id=ingest_run.id,
    )
    with pg_repository.transaction():
        pg_repository.add_run(ingest_run)
        pg_repository.add_raw_blob(blob)
        pg_repository.add_source_object(obj)
        pg_repository.add_run_io(ingest_run.id, obj.id, RunIoRole.OUTPUT)
        pg_repository.set_source_status(source.id, SourceStatus.INGESTED, NOW)

    # Initial grant
    record_approval(
        pg_repository,
        source_id=source.id,
        operation=Operation.EXTRACT,
        action=ApprovalAction.GRANT,
        approver_id="steward-mzr",
        basis="Grant initially",
        authority_registry=registry,
    )

    passed_gate1 = threading.Event()
    allow_gate2 = threading.Event()
    original_find_reusable = RunRecorder.find_reusable

    def spy_find_reusable(self: RunRecorder, *args: object, **kwargs: object) -> object:
        res = original_find_reusable(self, *args, **kwargs)
        passed_gate1.set()
        assert allow_gate2.wait(timeout=10.0), "Gate 2 wait timed out"
        return res

    monkeypatch.setattr(RunRecorder, "find_reusable", spy_find_reusable)

    ctx_extract = AppContext(
        repo=PostgresRepository(pg_repository._engine),
        raw_store=raw_store,
        artifact_store=artifact_store,
        clock=lambda: NOW,
        new_id=new_id,
        actor="extractor-actor",
        code_revision="rev-test",
    )

    errors: list[BaseException] = []
    denied_caught = threading.Event()

    def run_extract() -> None:
        try:
            extract_source(ctx_extract, source.id)
        except PolicyDenied:
            denied_caught.set()
        except BaseException as exc:
            errors.append(exc)

    t = threading.Thread(target=run_extract)
    t.start()
    try:
        # 1. Wait until initial gate has passed and execution paused before second gate
        assert passed_gate1.wait(timeout=10.0), "Did not reach post-initial-gate pause"
        # 2. Commit withdrawal of EXTRACT while extraction is paused between gates
        record_approval(
            pg_repository,
            source_id=source.id,
            operation=Operation.EXTRACT,
            action=ApprovalAction.WITHDRAW,
            approver_id="steward-mzr",
            basis="Withdraw between gates",
            authority_registry=registry,
        )
        assert Operation.EXTRACT not in effective_policy(pg_repository, source).allow
    finally:
        allow_gate2.set()
    t.join(timeout=10.0)
    assert not t.is_alive()
    assert errors == []
    assert denied_caught.is_set(), (
        "extract_source must be caught and raise PolicyDenied at second gate"
    )

    # Verify run was created and marked FAILED with error_type="PolicyDenied"
    with Session(pg_repository._engine) as s:
        from langpipe.storage.db import tables

        extract_runs = (
            s.query(tables.ProcessingRun)
            .filter(tables.ProcessingRun.stage == RunStage.EXTRACTION.value)
            .all()
        )
        assert len(extract_runs) == 1
        assert extract_runs[0].status == RunStatus.FAILED.value
        assert extract_runs[0].error_type == "PolicyDenied"

    # Verify audit event was recorded for denial
    events = pg_repository.list_audit_events()
    denials = [
        e
        for e in events
        if e.subject_id == source.id and e.event_type is AuditEventType.POLICY_DENIED
    ]
    assert len(denials) == 1
    assert denials[0].details["operation"] == Operation.EXTRACT.value

    # Verify no segments were stored
    assert pg_repository.list_segments(obj.id) == []


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
def test_wordlist_withdrawal_during_reuse_records_denial_audit_on_postgres(
    pg_repository: PostgresRepository,
    registry: ReviewAuthorityRegistry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves a withdrawal during wordlist reuse records a POLICY_DENIED audit event."""
    from langpipe.ingestion.registration import register_source
    from tests.service.manifests import manifest_data, write_manifest, write_origin_file

    tsv_body = b"mzr\tpor\nkanu\tcanoa\n"
    write_origin_file(tmp_path, "wl/words.tsv", tsv_body)
    data = manifest_data(
        key="src-wl",
        mode="review_required",
        access_class="public",
        objects=[{"path": "wl/words.tsv", "media_type": "text/tab-separated-values"}],
    )
    data["source_type"] = SourceType.WORDLIST.value
    data["languages"] = ["mzr", "por"]
    manifest_path = write_manifest(tmp_path, data, name="src-wl.yaml")

    ctx = AppContext(
        repo=PostgresRepository(pg_repository._engine),
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=lambda: NOW,
        new_id=new_id,
        actor="wordlist-actor",
        code_revision="rev-test",
    )
    reg = register_source(ctx, manifest_path)
    source = reg.source

    # Grant EXTRACT initially (INGEST is allowed by review_required baseline)
    record_approval(
        pg_repository,
        source_id=source.id,
        operation=Operation.EXTRACT,
        action=ApprovalAction.GRANT,
        approver_id="steward-mzr",
        basis="Initial grant for wordlist",
        authority_registry=registry,
    )

    extractor = WordlistExtractor(ctx)

    # 1. First run succeeds
    first_res = extractor.extract(source.id)
    assert not first_res.reused
    assert first_res.run.status is RunStatus.SUCCEEDED

    # 2. Hook find_reusable on the second run to pause after finding the reusable run
    found_reuse = threading.Event()
    allow_reuse_check = threading.Event()
    original_find = RunRecorder.find_reusable

    def spy_find(self: RunRecorder, *args: object, **kwargs: object) -> object:
        res = original_find(self, *args, **kwargs)
        if res is not None:
            found_reuse.set()
            assert allow_reuse_check.wait(timeout=10.0), "Reuse check wait timed out"
        return res

    monkeypatch.setattr(RunRecorder, "find_reusable", spy_find)

    ctx2 = AppContext(
        repo=PostgresRepository(pg_repository._engine),
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=lambda: NOW,
        new_id=new_id,
        actor="wordlist-actor-2",
        code_revision="rev-test-2",
    )
    extractor2 = WordlistExtractor(ctx2)
    denied = threading.Event()
    errors: list[BaseException] = []

    def run_reused() -> None:
        try:
            extractor2.extract(source.id)
        except PolicyDenied:
            denied.set()
        except BaseException as exc:
            errors.append(exc)

    t = threading.Thread(target=run_reused)
    t.start()
    try:
        assert found_reuse.wait(timeout=10.0)
        # Commit withdrawal while paused between find_reusable and the lock check
        record_approval(
            pg_repository,
            source_id=source.id,
            operation=Operation.EXTRACT,
            action=ApprovalAction.WITHDRAW,
            approver_id="steward-mzr",
            basis="Withdrawal during reuse",
            authority_registry=registry,
        )
    finally:
        allow_reuse_check.set()
    t.join(timeout=10.0)
    assert not t.is_alive()
    assert errors == []
    assert denied.is_set(), "Wordlist reuse path must raise PolicyDenied on withdrawal"

    # Verify audit event was recorded by the reuse denial handler
    events = pg_repository.list_audit_events()
    denials = [
        e
        for e in events
        if e.subject_id == source.id and e.event_type is AuditEventType.POLICY_DENIED
    ]
    assert len(denials) == 1
    assert denials[0].details["operation"] == Operation.EXTRACT.value


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
def test_extract_source_withdrawal_during_reuse_records_denial_audit_on_postgres(
    pg_repository: PostgresRepository,
    registry: ReviewAuthorityRegistry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves that withdrawing approval while extract_source finds a reusable run is caught

    by the locked recheck and records a POLICY_DENIED audit event on PostgreSQL.
    """
    raw_store = LocalContentStore(tmp_path / "raw")
    artifact_store = LocalContentStore(tmp_path / "artifacts")
    stored_raw = raw_store.put_bytes(b"Line 1\nLine 2\n")

    source = _create_source(pg_repository, mode=PolicyMode.REVIEW_REQUIRED)
    obj = make_source_object(
        source,
        source.registration_run_id,
        sha256=stored_raw.sha256,
        size_bytes=stored_raw.size_bytes,
        media_type="text/plain",
    )
    ingest_run = make_run(
        stage=RunStage.RAW_INGESTION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key("ingest-reuse"),
    )
    blob = RawBlob(
        sha256=stored_raw.sha256,
        size_bytes=stored_raw.size_bytes,
        storage_backend="local",
        stored_at=NOW,
        ingestion_run_id=ingest_run.id,
    )
    with pg_repository.transaction():
        pg_repository.add_run(ingest_run)
        pg_repository.add_raw_blob(blob)
        pg_repository.add_source_object(obj)
        pg_repository.add_run_io(ingest_run.id, obj.id, RunIoRole.OUTPUT)
        pg_repository.set_source_status(source.id, SourceStatus.INGESTED, NOW)

    record_approval(
        pg_repository,
        source_id=source.id,
        operation=Operation.EXTRACT,
        action=ApprovalAction.GRANT,
        approver_id="steward-mzr",
        basis="Grant for initial extract",
        authority_registry=registry,
    )

    ctx1 = AppContext(
        repo=PostgresRepository(pg_repository._engine),
        raw_store=raw_store,
        artifact_store=artifact_store,
        clock=lambda: NOW,
        new_id=new_id,
        actor="extractor-actor-1",
        code_revision="rev-test-1",
    )
    # 1. First run succeeds and persists segments + report
    first_res = extract_source(ctx1, source.id)
    assert not first_res.reused
    assert first_res.run.status is RunStatus.SUCCEEDED

    # 2. Hook find_reusable on the second run to pause after finding the reusable run
    found_reuse = threading.Event()
    allow_reuse_check = threading.Event()
    original_find = RunRecorder.find_reusable

    def spy_find(self: RunRecorder, *args: object, **kwargs: object) -> object:
        res = original_find(self, *args, **kwargs)
        if res is not None:
            found_reuse.set()
            assert allow_reuse_check.wait(timeout=10.0), "Reuse check wait timed out"
        return res

    monkeypatch.setattr(RunRecorder, "find_reusable", spy_find)

    ctx2 = AppContext(
        repo=PostgresRepository(pg_repository._engine),
        raw_store=raw_store,
        artifact_store=artifact_store,
        clock=lambda: NOW,
        new_id=new_id,
        actor="extractor-actor-2",
        code_revision="rev-test-2",
    )
    denied = threading.Event()
    errors: list[BaseException] = []

    def run_reused() -> None:
        try:
            extract_source(ctx2, source.id)
        except PolicyDenied:
            denied.set()
        except BaseException as exc:
            errors.append(exc)

    t = threading.Thread(target=run_reused)
    t.start()
    try:
        assert found_reuse.wait(timeout=10.0)
        # Commit withdrawal while paused between find_reusable and the reuse lock check
        record_approval(
            pg_repository,
            source_id=source.id,
            operation=Operation.EXTRACT,
            action=ApprovalAction.WITHDRAW,
            approver_id="steward-mzr",
            basis="Withdrawal during extract reuse",
            authority_registry=registry,
        )
    finally:
        allow_reuse_check.set()
    t.join(timeout=10.0)
    assert not t.is_alive()
    assert errors == []
    assert denied.is_set(), "extract_source reuse path must raise PolicyDenied on withdrawal"

    # Verify audit event was recorded by the reuse denial handler
    events = pg_repository.list_audit_events()
    denials = [
        e
        for e in events
        if e.subject_id == source.id and e.event_type is AuditEventType.POLICY_DENIED
    ]
    assert len(denials) == 1
    assert denials[0].details["operation"] == Operation.EXTRACT.value
    assert denials[0].details["decision"] == PolicyDecision.REVIEW_REQUIRED.value
