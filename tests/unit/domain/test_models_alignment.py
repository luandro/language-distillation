import json
from collections import UserDict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from langpipe.domain.enums import (
    AlignmentDirection,
    AlignmentMode,
    AlignmentStatus,
    LifecycleStatus,
    Symmetrization,
)
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.alignment import SegmentAlignment, TokenAlignmentEdge

NOW = datetime(2026, 1, 1, tzinfo=UTC)
GROUP_KEY = "a" * 64


def _alignment(**overrides: object) -> SegmentAlignment:
    kwargs: dict[str, object] = {
        "id": new_id(IdPrefix.SEGMENT_ALIGNMENT),
        "source_segment_ids": (new_id(IdPrefix.SEGMENT),),
        "target_segment_ids": (new_id(IdPrefix.SEGMENT),),
        "method": "canonical_locator@0.1.0",
        "mode": AlignmentMode.CANONICAL,
        "status": AlignmentStatus.STRUCTURAL,
        "score": None,
        "raw_scores": {},
        "group_key": GROUP_KEY,
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    kwargs.update(overrides)
    return SegmentAlignment(**kwargs)  # type: ignore[arg-type]


def _edge(**overrides: object) -> TokenAlignmentEdge:
    kwargs: dict[str, object] = {
        "id": new_id(IdPrefix.TOKEN_ALIGNMENT),
        "segment_alignment_id": new_id(IdPrefix.SEGMENT_ALIGNMENT),
        "source_token_id": new_id(IdPrefix.TOKEN),
        "target_token_id": new_id(IdPrefix.TOKEN),
        "direction": AlignmentDirection.FORWARD,
        "algorithm": "eflomal@0.1.0",
        "score": None,
        "raw_scores": {},
        "symmetrization": Symmetrization.NONE,
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    kwargs.update(overrides)
    return TokenAlignmentEdge(**kwargs)  # type: ignore[arg-type]


def test_nonempty_distinct_members() -> None:
    source = (new_id(IdPrefix.SEGMENT), new_id(IdPrefix.SEGMENT))
    target = (new_id(IdPrefix.SEGMENT), new_id(IdPrefix.SEGMENT), new_id(IdPrefix.SEGMENT))
    _alignment(source_segment_ids=source[:1], target_segment_ids=target)  # 1:3
    _alignment(source_segment_ids=source, target_segment_ids=target[:2])  # 2:2
    _alignment(source_segment_ids=source, target_segment_ids=target)  # 2:3

    with pytest.raises(ValidationError):
        _alignment(source_segment_ids=())
    with pytest.raises(ValidationError):
        _alignment(target_segment_ids=())
    with pytest.raises(ValidationError):
        _alignment(source_segment_ids=(source[0], source[0]))
    with pytest.raises(ValidationError):
        _alignment(target_segment_ids=(target[0], target[0]))
    shared = new_id(IdPrefix.SEGMENT)
    with pytest.raises(ValidationError):
        _alignment(source_segment_ids=(shared,), target_segment_ids=(shared,))


def test_score_finite_nullable() -> None:
    _alignment(score=None)
    _alignment(score=0.5)
    _alignment(score=-1.5)  # raw components keep their own scale, not [0,1]
    _alignment(score=42.0)
    _alignment(raw_scores={})
    _alignment(raw_scores={"p": 0.25, "logp": -3.75})

    with pytest.raises(ValidationError):
        _alignment(score=float("nan"))
    with pytest.raises(ValidationError):
        _alignment(score=float("inf"))
    with pytest.raises(ValidationError):
        _alignment(score=float("-inf"))
    with pytest.raises(ValidationError):
        _alignment(score=True)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        _alignment(raw_scores={"p": float("nan")})
    with pytest.raises(ValidationError):
        _alignment(raw_scores={"p": float("inf")})
    with pytest.raises(ValidationError):
        _alignment(raw_scores={"p": True})  # type: ignore[dict-item]

    _edge(score=None)
    _edge(score=0.5)
    with pytest.raises(ValidationError):
        _edge(score=float("nan"))
    with pytest.raises(ValidationError):
        _edge(score=True)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        _edge(raw_scores={"p": float("inf")})


@pytest.mark.parametrize("flag", [True, False])
@pytest.mark.parametrize("factory", [_alignment, _edge])
def test_raw_scores_reject_boolean_from_any_mapping(
    factory: Callable[..., Any], flag: bool
) -> None:
    # pydantic coerces non-dict Mappings (e.g. UserDict) to dict, so booleans
    # must be rejected before coercion turns True/False into 1.0/0.0.
    with pytest.raises(ValidationError):
        factory(raw_scores=UserDict({"p": flag}))
    with pytest.raises(ValidationError):
        factory(raw_scores={"p": flag})  # plain dict boolean still fails


@pytest.mark.parametrize("factory", [_alignment, _edge])
def test_raw_scores_accept_finite_numeric_mapping(factory: Callable[..., Any]) -> None:
    model = factory(raw_scores=UserDict({"p": 0.25, "logp": -3.75}))
    assert model.raw_scores == {"p": 0.25, "logp": -3.75}


@pytest.mark.parametrize("factory", [_alignment, _edge])
def test_raw_scores_reject_boolean_from_json(factory: Callable[..., Any]) -> None:
    model = factory()
    payload = json.loads(model.model_dump_json())
    payload["raw_scores"] = {"p": True}
    with pytest.raises(ValidationError):
        type(model).model_validate_json(json.dumps(payload))


def test_direction_symmetrization_matrix() -> None:
    _edge(direction=AlignmentDirection.FORWARD, symmetrization=Symmetrization.NONE)
    _edge(direction=AlignmentDirection.REVERSE, symmetrization=Symmetrization.NONE)
    _edge(direction=AlignmentDirection.SYMMETRIZED, symmetrization=Symmetrization.INTERSECTION)
    _edge(direction=AlignmentDirection.SYMMETRIZED, symmetrization=Symmetrization.UNION)

    with pytest.raises(ValidationError):
        _edge(direction=AlignmentDirection.FORWARD, symmetrization=Symmetrization.INTERSECTION)
    with pytest.raises(ValidationError):
        _edge(direction=AlignmentDirection.FORWARD, symmetrization=Symmetrization.UNION)
    with pytest.raises(ValidationError):
        _edge(direction=AlignmentDirection.REVERSE, symmetrization=Symmetrization.UNION)
    with pytest.raises(ValidationError):
        _edge(direction=AlignmentDirection.SYMMETRIZED, symmetrization=Symmetrization.NONE)


def test_approval_requires_basis_and_predecessor() -> None:
    basis = new_id(IdPrefix.ARTIFACT)
    predecessor = new_id(IdPrefix.SEGMENT_ALIGNMENT)
    for status in (AlignmentStatus.STRUCTURAL, AlignmentStatus.INFERRED, AlignmentStatus.CANDIDATE):
        _alignment(status=status)
        with pytest.raises(ValidationError):
            _alignment(status=status, authorization_basis_id=basis)
        with pytest.raises(ValidationError):
            _alignment(status=status, supersedes_id=predecessor)
    for status in (AlignmentStatus.APPROVED, AlignmentStatus.REJECTED):
        _alignment(status=status, authorization_basis_id=basis, supersedes_id=predecessor)
        with pytest.raises(ValidationError):
            _alignment(status=status)
        with pytest.raises(ValidationError):
            _alignment(status=status, authorization_basis_id=basis)
        with pytest.raises(ValidationError):
            _alignment(status=status, supersedes_id=predecessor)


def test_alignment_status_cannot_validate_translation() -> None:
    assert [member.value for member in AlignmentStatus] == [
        "structural",
        "inferred",
        "candidate",
        "approved",
        "rejected",
    ]
    # No alignment disposition may claim linguistic validation (ADR-0011 §2).
    linguistic = {
        LifecycleStatus.VALIDATED.value,
        LifecycleStatus.SUPPORTED.value,
        LifecycleStatus.DEPRECATED.value,
    }
    assert {member.value for member in AlignmentStatus} & linguistic == set()
    assert SegmentAlignment.model_fields["status"].annotation is AlignmentStatus
    assert not hasattr(AlignmentStatus, "VALIDATED")


def test_roundtrip_and_extra_forbidden() -> None:
    basis = new_id(IdPrefix.ARTIFACT)
    alignment = _alignment(
        status=AlignmentStatus.APPROVED,
        score=0.75,
        raw_scores={"component": -2.0},
        authorization_basis_id=basis,
        supersedes_id=new_id(IdPrefix.SEGMENT_ALIGNMENT),
    )
    restored = SegmentAlignment.model_validate_json(alignment.model_dump_json())
    assert restored == alignment

    edge = _edge(
        direction=AlignmentDirection.SYMMETRIZED,
        symmetrization=Symmetrization.UNION,
        raw_scores={"component": 1.5},
    )
    assert TokenAlignmentEdge.model_validate_json(edge.model_dump_json()) == edge

    with pytest.raises(ValidationError):
        SegmentAlignment.model_validate({**alignment.model_dump(), "extra": "x"})
    with pytest.raises(ValidationError):
        TokenAlignmentEdge.model_validate({**edge.model_dump(), "extra": "x"})

    with pytest.raises(ValidationError):
        _alignment(id=new_id(IdPrefix.SEGMENT))
    with pytest.raises(ValidationError):
        _alignment(source_segment_ids=(new_id(IdPrefix.TOKEN),))
    with pytest.raises(ValidationError):
        _alignment(run_id=new_id(IdPrefix.SEGMENT))
    with pytest.raises(ValidationError):
        _alignment(authorization_basis_id=new_id(IdPrefix.SEGMENT_ALIGNMENT))
    with pytest.raises(ValidationError):
        _alignment(
            status=AlignmentStatus.APPROVED,
            authorization_basis_id=basis,
            supersedes_id=new_id(IdPrefix.RUN),
        )
    with pytest.raises(ValidationError):
        _alignment(group_key="a" * 63)

    with pytest.raises(ValidationError):
        _edge(id=new_id(IdPrefix.SEGMENT))
    with pytest.raises(ValidationError):
        _edge(segment_alignment_id=new_id(IdPrefix.TOKEN))
    with pytest.raises(ValidationError):
        _edge(source_token_id=new_id(IdPrefix.SEGMENT))
    with pytest.raises(ValidationError):
        _edge(target_token_id=new_id(IdPrefix.SEGMENT_ALIGNMENT))

    with pytest.raises(ValidationError):
        _alignment(created_at=datetime(2026, 1, 1))  # naive has no UTC offset
    with pytest.raises(ValidationError):
        _alignment(created_at=datetime(2026, 1, 1, 3, 0, tzinfo=timezone(timedelta(hours=2))))
    with pytest.raises(ValidationError):
        _edge(created_at=datetime(2026, 1, 1, 3, 0, tzinfo=timezone(timedelta(hours=2))))
    _edge(created_at=NOW.replace(tzinfo=timezone(timedelta(0))))  # explicit +00:00 is UTC
