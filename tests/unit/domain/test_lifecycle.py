import pytest

from langpipe.domain.enums import LifecycleStatus, ValidationBasisKind
from langpipe.domain.errors import InvalidTransition
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.lifecycle import ALLOWED, ValidationBasis, check_transition

BASIS = ValidationBasis(
    kind=ValidationBasisKind.AUTHORIZED_REVIEWER,
    actor="reviewer-1",
    review_decision_id=new_id(IdPrefix.REVIEW),
)


def test_validated_requires_basis() -> None:
    with pytest.raises(InvalidTransition):
        check_transition(LifecycleStatus.SUPPORTED, LifecycleStatus.VALIDATED)
    check_transition(LifecycleStatus.SUPPORTED, LifecycleStatus.VALIDATED, BASIS)


def test_candidate_cannot_jump_to_validated() -> None:
    with pytest.raises(InvalidTransition):
        check_transition(LifecycleStatus.CANDIDATE, LifecycleStatus.VALIDATED, BASIS)


def test_deprecated_is_terminal() -> None:
    for new in LifecycleStatus:
        with pytest.raises(InvalidTransition):
            check_transition(LifecycleStatus.DEPRECATED, new, BASIS)


def test_rejected_is_terminal() -> None:
    for new in LifecycleStatus:
        with pytest.raises(InvalidTransition):
            check_transition(LifecycleStatus.REJECTED, new, BASIS)


def test_no_model_confidence_basis_kind() -> None:
    values = {kind.value for kind in ValidationBasisKind}
    assert values == {"authorized_reviewer", "authoritative_import", "editorial_decision"}
    assert not any("model" in value or "confidence" in value for value in values)


@pytest.mark.parametrize(
    ("current", "new"),
    [(current, new) for current, targets in ALLOWED.items() for new in sorted(targets)],
)
def test_allowed_transitions_pass(current: LifecycleStatus, new: LifecycleStatus) -> None:
    check_transition(current, new, BASIS)


def test_validated_only_moves_to_deprecated() -> None:
    check_transition(LifecycleStatus.VALIDATED, LifecycleStatus.DEPRECATED)
    for new in LifecycleStatus:
        if new is LifecycleStatus.DEPRECATED:
            continue
        with pytest.raises(InvalidTransition):
            check_transition(LifecycleStatus.VALIDATED, new, BASIS)
