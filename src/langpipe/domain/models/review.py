"""Milestone 4 human review queue domain models (ADR-0013 §4-5, REVIEW-WORKFLOW.md).

`ReviewTask` is an operational queue entry; its `status` is a workflow state
(`open`/`in_review`/`resolved`/`cancelled`), never a `LifecycleStatus` — only a
validated object carries lifecycle status. `ReviewDecision` is an immutable record:
a changed opinion records a new decision, it never edits one.
"""

import math
from datetime import datetime
from typing import ClassVar

from pydantic import Field, field_validator

from langpipe.domain.enums import ReviewDecisionKind, ReviewTaskType
from langpipe.domain.ids import IdPrefix, is_id
from langpipe.domain.models.base import DomainModel, id_field

# Operational queue states (docs/REVIEW-WORKFLOW.md lists a task "status"; lifecycle
# statuses belong to the reviewed object, not to the queue entry).
REVIEW_TASK_STATUSES = ("open", "in_review", "resolved", "cancelled")


def _strict_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not is_id(value):
        raise ValueError(f"{field} must be a valid identifier")
    return value


def _prefixed_ids(value: list[str], field: str, prefix: IdPrefix | None = None) -> list[str]:
    for item in value:
        if not is_id(item, prefix):
            raise ValueError(f"{field} entries must be valid identifiers")
    return value


def _finite_priority(value: float) -> float:
    # bool is an int subclass and pydantic coerces it to 1.0; NaN is also dropped by
    # ordering comparisons, so a NaN priority would silently reorder the queue.
    if isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("priority must be a finite number")
    return value


class ReviewTask(DomainModel):
    """One queued human review request about a candidate object."""

    SCHEMA_NAME: ClassVar[str | None] = "review-task"

    id: id_field(IdPrefix.REVIEW_TASK)  # type: ignore[valid-type]
    task_type: ReviewTaskType
    target_id: str
    target_version: str | None = Field(default=None, min_length=1)
    evidence_item_ids: list[str] = Field(default_factory=list)
    required_role: str = Field(min_length=1)
    priority: float
    reason: str = Field(min_length=1)
    creator_run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    status: str = "open"
    created_at: datetime

    @field_validator("target_id")
    @classmethod
    def _target_is_id(cls, value: str) -> str:
        return _strict_id(value, "target_id")

    @field_validator("evidence_item_ids")
    @classmethod
    def _evidence_are_evidence_ids(cls, value: list[str]) -> list[str]:
        return _prefixed_ids(value, "evidence_item_ids", IdPrefix.EVIDENCE)

    @field_validator("status")
    @classmethod
    def _status_is_operational(cls, value: str) -> str:
        if value not in REVIEW_TASK_STATUSES:
            raise ValueError("status must be an operational queue state, not a lifecycle status")
        return value

    @field_validator("priority", mode="before")
    @classmethod
    def _priority_is_not_bool(cls, value: object) -> object:
        # Before coercion: pydantic would otherwise turn True/False into 1.0/0.0.
        if isinstance(value, bool):
            raise ValueError("priority must be a finite number")
        return value

    @field_validator("priority")
    @classmethod
    def _priority_is_finite(cls, value: float) -> float:
        return _finite_priority(value)


class ReviewDecision(DomainModel):
    """An immutable reviewer disposition for one review task."""

    SCHEMA_NAME: ClassVar[str | None] = "review-decision"

    id: id_field(IdPrefix.REVIEW_DECISION)  # type: ignore[valid-type]
    task_id: id_field(IdPrefix.REVIEW_TASK)  # type: ignore[valid-type]
    target_id: str
    decision: ReviewDecisionKind
    reviewer_id: str = Field(min_length=1)
    reviewer_role: str = Field(min_length=1)
    superseding_object_id: str | None = Field(default=None, min_length=1)
    notes: str | None = Field(default=None)
    created_at: datetime

    @field_validator("target_id")
    @classmethod
    def _target_is_id(cls, value: str) -> str:
        return _strict_id(value, "target_id")

    @field_validator("superseding_object_id")
    @classmethod
    def _superseding_is_id(cls, value: str | None) -> str | None:
        return None if value is None else _strict_id(value, "superseding_object_id")
