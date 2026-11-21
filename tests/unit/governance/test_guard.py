from dataclasses import dataclass

import pytest

from langpipe.domain.enums import Operation, PolicyDecision, PolicyMode
from langpipe.domain.errors import PolicyDenied
from langpipe.governance.guard import require, require_all


@dataclass(frozen=True)
class _P:
    mode: PolicyMode
    allow: tuple[Operation, ...] = ()
    deny: tuple[Operation, ...] = ()


def test_require_raises_policy_denied_with_ids_only() -> None:
    policy = _P(PolicyMode.RESTRICTED)
    with pytest.raises(PolicyDenied) as excinfo:
        require(policy, Operation.READ_RAW, source_id="src-secret-7")
    err = excinfo.value
    assert err.source_id == "src-secret-7"
    assert err.operation is Operation.READ_RAW
    assert err.decision is PolicyDecision.DENY
    message = str(err)
    assert "src-secret-7" in message
    assert "read_raw" in message
    assert "restricted" not in message


def test_require_passes_on_allow() -> None:
    require(_P(PolicyMode.DIRECT), Operation.EXTRACT, source_id="src-1")


def test_require_review_required_is_not_allow() -> None:
    with pytest.raises(PolicyDenied) as excinfo:
        require(_P(PolicyMode.REVIEW_REQUIRED), Operation.EXTRACT, source_id="src-1")
    assert excinfo.value.decision is PolicyDecision.REVIEW_REQUIRED


def test_require_all_raises_first_non_allow_in_sorted_key_order() -> None:
    policies = {
        "src-b": _P(PolicyMode.DIRECT),
        "src-c": _P(PolicyMode.EXCLUDE),
        "src-a": _P(PolicyMode.EXCLUDE),
    }
    with pytest.raises(PolicyDenied) as excinfo:
        require_all(policies, Operation.EXTRACT)
    assert excinfo.value.source_id == "src-a"


def test_require_all_passes_when_all_allow() -> None:
    policies = {"s1": _P(PolicyMode.DIRECT), "s2": _P(PolicyMode.DIRECT)}
    require_all(policies, Operation.EXTRACT)
