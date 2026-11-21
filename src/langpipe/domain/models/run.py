from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from pydantic import Field, JsonValue, field_validator, model_validator

from langpipe.domain.enums import (
    AccessClass,
    ArtifactKind,
    AuditEventType,
    Operation,
    PolicyDecision,
    PolicyMode,
    RunStage,
    RunStatus,
)
from langpipe.domain.hashing import canonical_json, config_hash, sha256_bytes
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.base import SHA256, DomainModel, id_field

# Enum-valued audit detail keys and the enum each value must belong to.
_ENUM_DETAILS: Mapping[str, type[StrEnum]] = {
    "mode": PolicyMode,
    "operation": Operation,
    "decision": PolicyDecision,
}
_COUNT_DETAIL = "objects"


class ProcessingRun(DomainModel):
    SCHEMA_NAME: ClassVar[str | None] = "processing-run"

    id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    stage: RunStage
    tool_name: str
    tool_version: str
    config: dict[str, JsonValue]
    config_hash: SHA256
    code_revision: str
    run_key: SHA256
    random_seed: int | None = None
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    error_type: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def _status_fields_consistent(self) -> "ProcessingRun":
        if self.config_hash != config_hash(self.config):
            raise ValueError("config_hash must match config")
        if self.status is RunStatus.RUNNING:
            if (
                self.finished_at is not None
                or self.error_type is not None
                or self.error_message is not None
            ):
                raise ValueError("a running run must not carry finished_at or error fields")
        elif self.status is RunStatus.SUCCEEDED:
            if (
                self.finished_at is None
                or self.error_type is not None
                or self.error_message is not None
            ):
                raise ValueError("a succeeded run needs finished_at and no error fields")
        elif self.finished_at is None or not self.error_type:
            raise ValueError("a failed run needs finished_at and error_type")
        return self

    @staticmethod
    def compute_run_key(
        stage: RunStage,
        tool_name: str,
        tool_version: str,
        config_hash: str,
        input_ids: Iterable[str],
    ) -> str:
        # The code revision is deliberately absent: reruns with a new revision reuse the key.
        payload = {
            "stage": stage,
            "tool_name": tool_name,
            "tool_version": tool_version,
            "config_hash": config_hash,
            "inputs": sorted(input_ids),
        }
        return sha256_bytes(canonical_json(payload).encode("utf-8"))


class Artifact(DomainModel):
    SCHEMA_NAME: ClassVar[str | None] = "artifact"

    id: id_field(IdPrefix.ARTIFACT)  # type: ignore[valid-type]
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    kind: ArtifactKind
    media_type: str
    sha256: SHA256
    size_bytes: int = Field(ge=0)
    access_class: AccessClass
    schema_name: str | None = None
    schema_version: int | None = None
    created_at: datetime


class AuditEvent(DomainModel):
    id: id_field(IdPrefix.AUDIT)  # type: ignore[valid-type]
    event_type: AuditEventType
    actor: str
    subject_id: str | None
    run_id: str | None
    details: dict[str, str | int | bool]
    occurred_at: datetime

    @field_validator("details")
    @classmethod
    def _details_are_allowlisted(
        cls, value: dict[str, str | int | bool]
    ) -> dict[str, str | int | bool]:
        # Values are checked, never echoed: an error must not leak the offending content.
        for key, item in value.items():
            if key in _ENUM_DETAILS:
                if not isinstance(item, str):
                    raise ValueError(f"audit detail {key} has an unknown value")
                try:
                    _ENUM_DETAILS[key](item)
                except ValueError as exc:
                    raise ValueError(f"audit detail {key} has an unknown value") from exc
            elif key == _COUNT_DETAIL:
                if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                    raise ValueError("audit detail objects must be a non-negative integer")
            else:
                raise ValueError("audit detail key is not allowlisted")
        return value
