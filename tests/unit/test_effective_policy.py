"""Unit and property tests for effective_policy (WP5.5, ADR-0018)."""

from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from langpipe.domain.enums import (
    ApprovalAction,
    Operation,
    PolicyDecision,
    PolicyMode,
    RunStage,
    RunStatus,
)
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.approval import SourceUseApproval
from langpipe.domain.models.source import Source
from langpipe.governance.approvals import (
    APPROVABLE_OPERATIONS,
    effective_policy,
)
from langpipe.governance.policy import Baseline, baseline, resolve
from langpipe.storage.memory import InMemoryRepository
from tests.contract.builders import NOW, make_policy, make_run, make_source, unique_run_key

_RANK = {
    PolicyDecision.DENY: 0,
    PolicyDecision.REVIEW_REQUIRED: 1,
    PolicyDecision.ALLOW: 2,
}

_ops = st.sampled_from(list(Operation))
_modes = st.sampled_from(list(PolicyMode))
_actions = st.sampled_from(list(ApprovalAction))


def _setup_repo(
    mode: PolicyMode,
    allow: tuple[Operation, ...] = (),
    deny: tuple[Operation, ...] = (),
    approvals: list[tuple[Operation, ApprovalAction]] | None = None,
) -> tuple[InMemoryRepository, Source]:
    repo = InMemoryRepository()
    reg_run = make_run(
        stage=RunStage.SOURCE_REGISTRATION, status=RunStatus.SUCCEEDED, finished_at=NOW
    )
    policy = make_policy(mode=mode, allow=allow, deny=deny)
    source = make_source(policy, reg_run.id)
    with repo.transaction():
        repo.add_run(reg_run)
        repo.add_policy(policy)
        repo.add_source(source)

    if approvals:
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        for idx, (op, action) in enumerate(approvals):
            run = make_run(
                stage=RunStage.HUMAN_REVIEW,
                status=RunStatus.SUCCEEDED,
                finished_at=NOW,
                run_key=unique_run_key(f"app-run-{idx}"),
            )
            app = SourceUseApproval(
                id=new_id(IdPrefix.SOURCE_USE_APPROVAL),
                source_id=source.id,
                operation=op,
                action=action,
                approver_id="steward-1",
                approver_role="governance_steward",
                basis="test approval",
                run_id=run.id,
                created_at=t0 + timedelta(seconds=idx),
            )
            with repo.transaction():
                repo.add_run(run)
                repo.add_source_use_approval(app)

    return repo, source


def test_effective_policy_without_approvals_equals_static_resolve() -> None:
    for mode in PolicyMode:
        for op in Operation:
            repo, source = _setup_repo(mode=mode)
            eff = effective_policy(repo, source)
            raw = repo.get_policy(source.policy_id)
            assert resolve(eff, op) == resolve(raw, op)


def test_grant_lifts_review_baseline_for_approvable_operation() -> None:
    repo, source = _setup_repo(
        mode=PolicyMode.REVIEW_REQUIRED,
        approvals=[(Operation.EXTRACT, ApprovalAction.GRANT)],
    )
    eff = effective_policy(repo, source)
    assert resolve(eff, Operation.EXTRACT) is PolicyDecision.ALLOW


def test_grant_never_lifts_explicit_deny() -> None:
    repo, source = _setup_repo(
        mode=PolicyMode.REVIEW_REQUIRED,
        deny=(Operation.EXTRACT,),
        approvals=[(Operation.EXTRACT, ApprovalAction.GRANT)],
    )
    eff = effective_policy(repo, source)
    assert resolve(eff, Operation.EXTRACT) is PolicyDecision.DENY


def test_grant_never_lifts_default_or_hard_deny() -> None:
    # Under RESTRICTED, Operation.EXTRACT is Baseline.DEFAULT_DENY
    repo, source = _setup_repo(
        mode=PolicyMode.RESTRICTED,
        approvals=[(Operation.EXTRACT, ApprovalAction.GRANT)],
    )
    eff = effective_policy(repo, source)
    assert resolve(eff, Operation.EXTRACT) is PolicyDecision.DENY

    # Under EXCLUDE, Operation.READ_RAW is Baseline.HARD_DENY
    repo2, source2 = _setup_repo(
        mode=PolicyMode.EXCLUDE,
        approvals=[(Operation.READ_RAW, ApprovalAction.GRANT)],
    )
    eff2 = effective_policy(repo2, source2)
    assert resolve(eff2, Operation.READ_RAW) is PolicyDecision.DENY


def test_withdrawal_tightens_permission_back_to_review_required() -> None:
    repo, source = _setup_repo(
        mode=PolicyMode.REVIEW_REQUIRED,
        approvals=[
            (Operation.EXTRACT, ApprovalAction.GRANT),
            (Operation.EXTRACT, ApprovalAction.WITHDRAW),
        ],
    )
    eff = effective_policy(repo, source)
    assert resolve(eff, Operation.EXTRACT) is PolicyDecision.REVIEW_REQUIRED


def test_non_approvable_operation_is_never_lifted() -> None:
    repo, source = _setup_repo(
        mode=PolicyMode.REVIEW_REQUIRED,
        approvals=[(Operation.DIRECT_TRAINING, ApprovalAction.GRANT)],
    )
    eff = effective_policy(repo, source)
    assert resolve(eff, Operation.DIRECT_TRAINING) is PolicyDecision.REVIEW_REQUIRED


@given(
    mode=_modes,
    op=_ops,
    action=_actions,
)
def test_hypothesis_approvals_monotonic_properties(
    mode: PolicyMode, op: Operation, action: ApprovalAction
) -> None:
    repo, source = _setup_repo(mode=mode, approvals=[(op, action)])
    eff = effective_policy(repo, source)
    raw = repo.get_policy(source.policy_id)

    raw_decision = resolve(raw, op)
    eff_decision = resolve(eff, op)

    # 1. Approvals never lower permission compared to baseline unless baseline was review
    # 2. If raw was DENY (explicit or hard or default), effective is still DENY
    if raw_decision is PolicyDecision.DENY:
        assert eff_decision is PolicyDecision.DENY

    # 3. If action is GRANT and op is approvable and baseline was REVIEW, eff is ALLOW
    if (
        action is ApprovalAction.GRANT
        and op in APPROVABLE_OPERATIONS
        and baseline(mode, op) is Baseline.REVIEW
        and op not in raw.deny
    ):
        assert eff_decision is PolicyDecision.ALLOW
    elif action is ApprovalAction.WITHDRAW and raw_decision is not PolicyDecision.ALLOW:
        assert eff_decision is not PolicyDecision.ALLOW
