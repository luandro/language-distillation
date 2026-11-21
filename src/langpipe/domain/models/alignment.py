import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any, ClassVar

from pydantic import Field, field_validator, model_validator

from langpipe.domain.enums import (
    AlignmentDirection,
    AlignmentMode,
    AlignmentStatus,
    Symmetrization,
)
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.base import SHA256, VERSIONED_NAME, DomainModel, id_field

_DISPOSITIONAL_STATUSES = (AlignmentStatus.APPROVED, AlignmentStatus.REJECTED)
_SYMMETRIZING = (Symmetrization.INTERSECTION, Symmetrization.UNION)


def _finite_score(value: float) -> float:
    # bool is an int subclass and pydantic coerces it to 1.0; scores are never booleans.
    if isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("score values must be finite")
    return value


def _segment_id_items() -> Any:
    return id_field(IdPrefix.SEGMENT)


class SegmentAlignment(DomainModel):
    """Ordered binary n:m alignment group over persisted segments. Evidence, never truth."""

    SCHEMA_NAME: ClassVar[str | None] = "segment-alignment"

    id: id_field(IdPrefix.SEGMENT_ALIGNMENT)  # type: ignore[valid-type]
    source_segment_ids: tuple[_segment_id_items(), ...]  # type: ignore[valid-type]
    target_segment_ids: tuple[_segment_id_items(), ...]  # type: ignore[valid-type]
    method: VERSIONED_NAME
    mode: AlignmentMode
    status: AlignmentStatus
    score: float | None = None
    raw_scores: dict[str, float] = Field(default_factory=dict)
    group_key: SHA256
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime
    authorization_basis_id: id_field(IdPrefix.ARTIFACT) | None = None  # type: ignore[valid-type]
    supersedes_id: id_field(IdPrefix.SEGMENT_ALIGNMENT) | None = None  # type: ignore[valid-type]

    @field_validator("source_segment_ids", "target_segment_ids")
    @classmethod
    def _sides_are_nonempty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("alignment sides must be nonempty")
        return value

    @field_validator("score", mode="before")
    @classmethod
    def _score_is_not_bool(cls, value: object) -> object:
        # Before coercion: pydantic would otherwise turn True into 1.0.
        if isinstance(value, bool):
            raise ValueError("score values must be finite")
        return value

    @field_validator("score")
    @classmethod
    def _score_is_finite(cls, value: float | None) -> float | None:
        return None if value is None else _finite_score(value)

    @field_validator("raw_scores", mode="before")
    @classmethod
    def _raw_scores_are_not_bool(cls, value: object) -> object:
        # Before coercion: pydantic accepts any Mapping as dict[str, float]
        # and would otherwise turn True/False into 1.0/0.0.
        if isinstance(value, Mapping):
            for item in value.values():
                if isinstance(item, bool):
                    raise ValueError("score values must be finite")
        return value

    @field_validator("raw_scores")
    @classmethod
    def _raw_scores_are_finite(cls, value: dict[str, float]) -> dict[str, float]:
        return {name: _finite_score(score) for name, score in value.items()}

    @model_validator(mode="after")
    def _membership_and_disposition(self) -> "SegmentAlignment":
        if len(set(self.source_segment_ids)) != len(self.source_segment_ids):
            raise ValueError("source side contains duplicate segments")
        if len(set(self.target_segment_ids)) != len(self.target_segment_ids):
            raise ValueError("target side contains duplicate segments")
        if set(self.source_segment_ids) & set(self.target_segment_ids):
            raise ValueError("a segment cannot appear on both sides of one alignment")
        if self.status in _DISPOSITIONAL_STATUSES:
            if self.authorization_basis_id is None or self.supersedes_id is None:
                raise ValueError(
                    "approved/rejected alignments require both an authorization basis "
                    "and a superseded predecessor"
                )
        elif self.authorization_basis_id is not None or self.supersedes_id is not None:
            raise ValueError(
                "only approved/rejected alignments may carry an authorization basis or predecessor"
            )
        return self


class TokenAlignmentEdge(DomainModel):
    """One directional token-pair link inside a segment alignment group."""

    SCHEMA_NAME: ClassVar[str | None] = "token-alignment-edge"

    id: id_field(IdPrefix.TOKEN_ALIGNMENT)  # type: ignore[valid-type]
    segment_alignment_id: id_field(IdPrefix.SEGMENT_ALIGNMENT)  # type: ignore[valid-type]
    source_token_id: id_field(IdPrefix.TOKEN)  # type: ignore[valid-type]
    target_token_id: id_field(IdPrefix.TOKEN)  # type: ignore[valid-type]
    direction: AlignmentDirection
    algorithm: VERSIONED_NAME
    score: float | None = None
    raw_scores: dict[str, float] = Field(default_factory=dict)
    symmetrization: Symmetrization
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime

    @field_validator("score", mode="before")
    @classmethod
    def _score_is_not_bool(cls, value: object) -> object:
        # Before coercion: pydantic would otherwise turn True into 1.0.
        if isinstance(value, bool):
            raise ValueError("score values must be finite")
        return value

    @field_validator("score")
    @classmethod
    def _score_is_finite(cls, value: float | None) -> float | None:
        return None if value is None else _finite_score(value)

    @field_validator("raw_scores", mode="before")
    @classmethod
    def _raw_scores_are_not_bool(cls, value: object) -> object:
        # Before coercion: pydantic accepts any Mapping as dict[str, float]
        # and would otherwise turn True/False into 1.0/0.0.
        if isinstance(value, Mapping):
            for item in value.values():
                if isinstance(item, bool):
                    raise ValueError("score values must be finite")
        return value

    @field_validator("raw_scores")
    @classmethod
    def _raw_scores_are_finite(cls, value: dict[str, float]) -> dict[str, float]:
        return {name: _finite_score(score) for name, score in value.items()}

    @model_validator(mode="after")
    def _direction_matches_symmetrization(self) -> "TokenAlignmentEdge":
        if self.direction is AlignmentDirection.SYMMETRIZED:
            if self.symmetrization not in _SYMMETRIZING:
                raise ValueError("symmetrized direction requires intersection or union")
        elif self.symmetrization is not Symmetrization.NONE:
            raise ValueError("forward/reverse direction requires symmetrization none")
        return self
