from dataclasses import dataclass

from hypothesis import given
from hypothesis import strategies as st

from langpipe.domain.enums import Operation, PolicyDecision, PolicyMode
from langpipe.governance.policy import resolve, resolve_many

_RANK = {
    PolicyDecision.DENY: 0,
    PolicyDecision.REVIEW_REQUIRED: 1,
    PolicyDecision.ALLOW: 2,
}


@dataclass(frozen=True)
class _P:
    mode: PolicyMode
    allow: tuple[Operation, ...]
    deny: tuple[Operation, ...]


_ops = st.sampled_from(list(Operation))
_policies = st.builds(
    _P,
    mode=st.sampled_from(list(PolicyMode)),
    allow=st.lists(_ops, max_size=6).map(tuple),
    deny=st.lists(_ops, max_size=6).map(tuple),
)


@given(policy=_policies, op=_ops, extra=_ops)
def test_adding_deny_never_increases_permission(
    policy: _P, op: Operation, extra: Operation
) -> None:
    tighter = _P(policy.mode, policy.allow, (*policy.deny, extra))
    assert _RANK[resolve(tighter, op)] <= _RANK[resolve(policy, op)]


@given(policies=st.lists(_policies, min_size=1, max_size=5), extra=_policies, op=_ops)
def test_resolve_many_is_monotonic(policies: list[_P], extra: _P, op: Operation) -> None:
    before = resolve_many(policies, op)
    after = resolve_many([*policies, extra], op)
    assert _RANK[after] <= _RANK[before]


@given(op=_ops)
def test_resolve_many_empty_is_deny(op: Operation) -> None:
    assert resolve_many([], op) is PolicyDecision.DENY
