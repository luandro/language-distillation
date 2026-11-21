"""Shared Repository contract for M5 source-use approvals (WP5.4, ADR-0018).

Runs once per backend via `repo_backend` (in-memory and PostgreSQL). An approval is an
append-only governance record: it is written once, listed by source, and never edited or
deleted — a changed decision appends a new row whose latest action wins at read time (the
`effective_policy` resolution itself is WP5.5 scope, not storage). Data is synthetic.
"""

import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from langpipe.domain.enums import ApprovalAction, EntityType, Operation, RunStage, RunStatus
from langpipe.domain.errors import ImmutableViolation, InvalidLineage
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.approval import SourceUseApproval
from langpipe.domain.models.run import ProcessingRun
from langpipe.domain.models.source import Source, SourcePolicy
from langpipe.storage.repository import Repository
from tests.contract.builders import (
    NOW,
    make_policy,
    make_run,
    make_source,
    unique_run_key,
)

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
class ApprovalWorld:
    """Committed substrate: one governed source plus the runs approvals attribute to."""

    reg_run: ProcessingRun
    app_run: ProcessingRun
    policy: SourcePolicy
    source: Source


def _approval_world(repo: Repository) -> ApprovalWorld:
    reg_run = make_run(
        stage=RunStage.SOURCE_REGISTRATION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"approval-reg-{next(_KEYS)}"),
    )
    policy = make_policy()
    source = make_source(policy, reg_run.id, key=f"approval-src-{next(_KEYS)}")
    app_run = make_run(
        stage=RunStage.MANUAL_ANNOTATION,
        status=RunStatus.RUNNING,
        run_key=unique_run_key(f"approval-run-{next(_KEYS)}"),
    )
    with repo.transaction():
        repo.add_run(reg_run)
        repo.add_policy(policy)
        repo.add_source(source)
        repo.add_run(app_run)
    return ApprovalWorld(reg_run=reg_run, app_run=app_run, policy=policy, source=source)


def _approval(
    source_id: str,
    run_id: str,
    index: int,
    operation: Operation = Operation.DISTILL_MORPHOLOGY,
    action: ApprovalAction = ApprovalAction.GRANT,
    **overrides: object,
) -> SourceUseApproval:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.SOURCE_USE_APPROVAL),
        "source_id": source_id,
        "operation": operation,
        "action": action,
        "approver_id": "steward-1",
        "approver_role": "governance_steward",
        "basis": "synthetic delegated authority",
        "run_id": run_id,
        "created_at": _at(index),
    }
    values.update(overrides)
    return SourceUseApproval.model_validate(values)


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def repo_backend(request: pytest.FixtureRequest) -> Iterator[Repository]:
    if request.param == "memory":
        from langpipe.storage.memory import InMemoryRepository

        yield InMemoryRepository()
        return
    yield request.getfixturevalue("pg_repository")


@pytest.fixture
def approval_world(repo_backend: Repository) -> ApprovalWorld:
    return _approval_world(repo_backend)


# --- transaction guard ------------------------------------------------------------------------


def test_approval_write_requires_transaction(repo_backend: Repository) -> None:
    world = _approval_world(repo_backend)
    approval = _approval(world.source.id, world.app_run.id, 1)
    with pytest.raises(RuntimeError, match="write outside transaction"):
        repo_backend.add_source_use_approval(approval)


# --- append-only round trip ---------------------------------------------------------------------


def test_approval_round_trip_and_listing(repo_backend: Repository) -> None:
    world = _approval_world(repo_backend)
    grant = _approval(world.source.id, world.app_run.id, 1)
    withdraw = _approval(
        world.source.id,
        world.app_run.id,
        2,
        operation=Operation.READ_RAW,
        action=ApprovalAction.WITHDRAW,
    )
    with repo_backend.transaction():
        repo_backend.add_source_use_approval(grant)
        repo_backend.add_source_use_approval(withdraw)

    assert repo_backend.list_source_use_approvals(world.source.id) == [grant, withdraw]
    assert repo_backend.entity_type_of(grant.id) is EntityType.SOURCE_USE_APPROVAL
    assert repo_backend.count(EntityType.SOURCE_USE_APPROVAL) == 2
    # Approvals for other sources do not exist yet; an unknown source lists empty.
    assert repo_backend.list_source_use_approvals(new_id(IdPrefix.SOURCE)) == []


def test_approval_listing_breaks_created_at_tie_by_id(repo_backend: Repository) -> None:
    world = _approval_world(repo_backend)
    second = _approval(
        world.source.id, world.app_run.id, 1, id=_fixed_id(IdPrefix.SOURCE_USE_APPROVAL.value, "9")
    )
    first = _approval(
        world.source.id, world.app_run.id, 1, id=_fixed_id(IdPrefix.SOURCE_USE_APPROVAL.value, "5")
    )
    with repo_backend.transaction():
        repo_backend.add_source_use_approval(second)
        repo_backend.add_source_use_approval(first)

    # Insertion order decides nothing: (created_at, id) governs.
    assert repo_backend.list_source_use_approvals(world.source.id) == [first, second]


def test_approvals_have_no_update_or_delete_path(repo_backend: Repository) -> None:
    world = _approval_world(repo_backend)
    grant = _approval(world.source.id, world.app_run.id, 1)
    with repo_backend.transaction():
        repo_backend.add_source_use_approval(grant)

    # Append-only by construction: no repository carries a mutation path for approvals.
    assert not hasattr(repo_backend, "set_source_use_approval")
    assert not hasattr(repo_backend, "update_source_use_approval")
    assert not hasattr(repo_backend, "delete_source_use_approval")
    # Re-writing the same identifier is refused, so the stored row can never change.
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_source_use_approval(
            _approval(world.source.id, world.app_run.id, 2, id=grant.id)
        )
    assert repo_backend.list_source_use_approvals(world.source.id) == [grant]


def test_approval_rollback_discards_the_write(repo_backend: Repository) -> None:
    world = _approval_world(repo_backend)
    approval = _approval(world.source.id, world.app_run.id, 1)

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom), repo_backend.transaction():
        repo_backend.add_source_use_approval(approval)
        assert repo_backend.list_source_use_approvals(world.source.id) == [approval]
        raise _Boom

    assert repo_backend.entity_type_of(approval.id) is None
    assert repo_backend.count(EntityType.SOURCE_USE_APPROVAL) == 0
    assert repo_backend.list_source_use_approvals(world.source.id) == []


# --- lineage -------------------------------------------------------------------------------------


def test_approval_lineage_parents_must_exist(repo_backend: Repository) -> None:
    world = _approval_world(repo_backend)
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_source_use_approval(
            _approval(new_id(IdPrefix.SOURCE), world.app_run.id, 1)
        )
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_source_use_approval(_approval(world.source.id, new_id(IdPrefix.RUN), 2))
    assert repo_backend.count(EntityType.SOURCE_USE_APPROVAL) == 0
