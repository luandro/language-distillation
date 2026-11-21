import re
from datetime import datetime
from typing import ClassVar

from pydantic import Field, JsonValue, field_validator, model_validator

from langpipe.domain.enums import EvidenceKind, EvidencePolarity, LineageKind
from langpipe.domain.ids import IdPrefix, is_id
from langpipe.domain.models.base import DomainModel, id_field

_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9_.-]+$")


class EvidenceItem(DomainModel):
    """Evidence about a target object. Evidence is not a hypothesis and never a validation."""

    SCHEMA_NAME: ClassVar[str | None] = "evidence-item"

    id: id_field(IdPrefix.EVIDENCE)  # type: ignore[valid-type]
    kind: EvidenceKind
    polarity: EvidencePolarity
    target_id: str
    claim: dict[str, JsonValue] | None = None
    source_id: id_field(IdPrefix.SOURCE) | None = None  # type: ignore[valid-type]
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    strength: dict[str, float] = Field(default_factory=dict)
    policy_version: str | None = None
    independence_group: str | None = None
    domain: str | None = None
    register: str | None = None
    extensions: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("target_id")
    @classmethod
    def _target_is_id(cls, value: str) -> str:
        if not is_id(value):
            raise ValueError("target_id must be a valid identifier")
        return value

    @model_validator(mode="after")
    def _extension_namespaces(self) -> "EvidenceItem":
        for namespace in self.extensions:
            if not _NAMESPACE_PATTERN.fullmatch(namespace):
                raise ValueError("extension namespace must match ^[a-z0-9_.-]+$")
        return self


class LineageEdge(DomainModel):
    """`from_id` depends on `to_id` (child → parent). ADR-0009."""

    SCHEMA_NAME: ClassVar[str | None] = "lineage-edge"

    id: id_field(IdPrefix.LINEAGE)  # type: ignore[valid-type]
    from_id: str
    to_id: str
    kind: LineageKind
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime

    @field_validator("from_id", "to_id")
    @classmethod
    def _endpoint_is_id(cls, value: str) -> str:
        if not is_id(value):
            raise ValueError("lineage endpoints must be valid identifiers")
        return value

    @model_validator(mode="after")
    def _no_self_edge(self) -> "LineageEdge":
        if self.from_id == self.to_id:
            raise ValueError("lineage edge must not point at itself")
        return self
