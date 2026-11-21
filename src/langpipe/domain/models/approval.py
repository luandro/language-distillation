"""Milestone 5 source-use approval model (ADR-0018).

An approval is an append-only governance record: `(source_id, operation, action,
approver_id, approver_role, basis, run_id, created_at)`. The effective state per
`(source, operation)` is computed from the latest action — no stored row is ever
edited or deleted (ADR-0018 §1, §5). Approvals only lift `review` baselines;
`deny`, `default_deny` and `hard_deny` are never lifted, and that resolution
lives in `effective_policy` (single door), not here.
"""

from datetime import datetime
from typing import ClassVar

from pydantic import Field

from langpipe.domain.enums import ApprovalAction, Operation
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.base import DomainModel, id_field


class SourceUseApproval(DomainModel):
    """One grant or withdrawal of a source-use operation (append-only)."""

    SCHEMA_NAME: ClassVar[str | None] = "source-use-approval"

    id: id_field(IdPrefix.SOURCE_USE_APPROVAL)  # type: ignore[valid-type]
    source_id: id_field(IdPrefix.SOURCE)  # type: ignore[valid-type]
    operation: Operation
    action: ApprovalAction
    approver_id: str = Field(min_length=1)
    approver_role: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime
