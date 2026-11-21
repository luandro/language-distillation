"""WP5.2 unit tests: `SourceUseApproval` (ADR-0018 §1).

Contracts under test:
- an approval is an append-only record `(source_id, operation, action, approver_id,
  approver_role, basis, run_id, created_at)` with an `sua_`-prefixed id;
- `action` is only `grant` or `withdraw` — the effective state per
  `(source, operation)` is computed from the latest action, never stored;
- approver identity, role and basis are nonempty; identity is unauthenticated (C-4),
  so no password/secret field exists;
- frozen, `extra="forbid"`, UTC datetimes, JSON roundtrip.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from langpipe.domain.enums import ApprovalAction, Operation
from langpipe.domain.ids import ID_PATTERN, IdPrefix, new_id
from langpipe.domain.models.approval import SourceUseApproval

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _approval(**overrides: object) -> SourceUseApproval:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.SOURCE_USE_APPROVAL),
        "source_id": new_id(IdPrefix.SOURCE),
        "operation": Operation.EXTRACT,
        "action": ApprovalAction.GRANT,
        "approver_id": "steward-ana",
        "approver_role": "governance_steward",
        "basis": "owner consent recorded 2026-01-01",
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    values.update(overrides)
    return SourceUseApproval(**values)  # type: ignore[arg-type]


def test_approval_shape_and_defaults() -> None:
    approval = _approval()

    assert approval.SCHEMA_NAME == "source-use-approval"
    assert approval.SCHEMA_VERSION == 1
    assert ID_PATTERN.fullmatch(approval.id) is not None
    assert approval.id.startswith("sua_")
    assert approval.operation is Operation.EXTRACT
    assert approval.action is ApprovalAction.GRANT


def test_approval_action_values_only_grant_or_withdraw() -> None:
    assert [action.value for action in ApprovalAction] == ["grant", "withdraw"]
    assert _approval(action=ApprovalAction.WITHDRAW).action is ApprovalAction.WITHDRAW


def test_approver_and_basis_must_be_nonempty() -> None:
    for field in ("approver_id", "approver_role", "basis"):
        with pytest.raises(ValidationError):
            _approval(**{field: ""})


def test_approval_foreign_keys_are_prefix_validated() -> None:
    # M4 convention: cross-references carry their own `id_field` prefix.
    with pytest.raises(ValidationError):
        _approval(source_id=new_id(IdPrefix.RUN))
    with pytest.raises(ValidationError):
        _approval(run_id=new_id(IdPrefix.SOURCE))
    assert _approval(source_id=new_id(IdPrefix.SOURCE)).source_id.startswith("src_")


def test_approval_is_append_only_record() -> None:
    approval = _approval()

    with pytest.raises(ValidationError):
        approval.action = ApprovalAction.WITHDRAW
    with pytest.raises(ValidationError):
        _approval(unexpected="extra")

    restored = SourceUseApproval.model_validate_json(approval.model_dump_json())
    assert restored == approval


def test_approval_rejects_non_utc_datetime() -> None:
    with pytest.raises(ValidationError):
        _approval(created_at=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=-3))))


def test_approval_operation_is_the_pipeline_operation_vocabulary() -> None:
    # ADR-0018 §3: approvable operations are a policy concern; the model accepts
    # the shared `Operation` vocabulary (refusals live in effective_policy, WP5.5).
    approval = _approval(operation=Operation.DISTILL_MORPHOLOGY)
    assert approval.operation is Operation.DISTILL_MORPHOLOGY
    with pytest.raises(ValidationError):
        _approval(operation="not-an-operation")
