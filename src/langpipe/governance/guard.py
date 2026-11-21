from collections.abc import Mapping

from langpipe.domain.enums import Operation, PolicyDecision
from langpipe.domain.errors import PolicyDenied
from langpipe.governance.policy import PolicyLike, resolve


def require(policy: PolicyLike, op: Operation, *, source_id: str) -> None:
    decision = resolve(policy, op)
    if decision is not PolicyDecision.ALLOW:
        raise PolicyDenied(source_id, op, decision)


def require_all(policies: Mapping[str, PolicyLike], op: Operation) -> None:
    for source_id in sorted(policies):
        require(policies[source_id], op, source_id=source_id)
