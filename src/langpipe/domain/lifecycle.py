from collections.abc import Mapping

from langpipe.domain.enums import LifecycleStatus, ValidationBasisKind
from langpipe.domain.errors import InvalidTransition
from langpipe.domain.models.base import DomainModel


class ValidationBasis(DomainModel):
    kind: ValidationBasisKind
    actor: str
    review_decision_id: str | None = None
    evidence_ids: tuple[str, ...] = ()


ALLOWED: Mapping[LifecycleStatus, frozenset[LifecycleStatus]] = {
    LifecycleStatus.CANDIDATE: frozenset(
        {LifecycleStatus.SUPPORTED, LifecycleStatus.REJECTED, LifecycleStatus.DEPRECATED}
    ),
    LifecycleStatus.SUPPORTED: frozenset(
        {LifecycleStatus.VALIDATED, LifecycleStatus.REJECTED, LifecycleStatus.DEPRECATED}
    ),
    LifecycleStatus.VALIDATED: frozenset({LifecycleStatus.DEPRECATED}),
    LifecycleStatus.REJECTED: frozenset(),
    LifecycleStatus.DEPRECATED: frozenset(),
}


def check_transition(
    current: LifecycleStatus,
    new: LifecycleStatus,
    basis: ValidationBasis | None = None,
) -> None:
    if new not in ALLOWED[current]:
        raise InvalidTransition()
    if new is LifecycleStatus.VALIDATED and basis is None:
        raise InvalidTransition()
