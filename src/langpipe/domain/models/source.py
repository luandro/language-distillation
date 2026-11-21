from collections.abc import Iterable
from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from langpipe.domain.enums import (
    AccessClass,
    Operation,
    PolicyMode,
    SourceStatus,
    SourceType,
    access_rank,
)
from langpipe.domain.errors import PolicyConflict
from langpipe.domain.hashing import canonical_json, sha256_bytes
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.base import LANG_CODE, SHA256, DomainModel, id_field
from langpipe.governance.policy import validate_policy_lists

_KEY_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}$"
_MEDIA_TYPE_PATTERN = r"^[a-z]+/[a-z0-9.+-]+$"


def _check_policy_lists(
    mode: PolicyMode, allow: Iterable[Operation], deny: Iterable[Operation]
) -> None:
    # Pydantic only converts ValueError into ValidationError, so re-raise the domain conflict.
    try:
        validate_policy_lists(mode, allow, deny)
    except PolicyConflict as exc:
        raise ValueError("allow list contains an operation hard-denied for this mode") from exc


def _sorted_unique(operations: Iterable[Operation]) -> tuple[Operation, ...]:
    return tuple(sorted(set(operations), key=lambda operation: operation.value))


class Provenance(DomainModel):
    acquired_from: str = Field(min_length=1)
    rights_holder: str | None = None
    collector: str | None = None
    notes: str | None = None

    @field_validator("rights_holder", "collector", "notes")
    @classmethod
    def _blank_is_absent(cls, value: str | None) -> str | None:
        # ADR-0025: a rights holder is a record. A blank string means "not recorded", which
        # is represented as absent rather than as an empty record.
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class PolicySpec(DomainModel):
    mode: PolicyMode
    access_class: AccessClass
    authority: str = Field(min_length=1)
    allow: list[Operation] = Field(default_factory=list)
    deny: list[Operation] = Field(default_factory=list)
    restrictions: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _lists_respect_baseline(self) -> "PolicySpec":
        _check_policy_lists(self.mode, self.allow, self.deny)
        return self


# ADR-0025: a source present in the repository is authorized for processing and
# training. License, ownership, and register are recorded metadata, never gates.
# A manifest that omits a policy gets this one. Returned fresh so a caller that
# mutates the lists cannot leak the change into every later manifest.
def default_policy_spec() -> PolicySpec:
    return PolicySpec(
        mode=PolicyMode.DIRECT,
        access_class=AccessClass.PUBLIC,
        authority="repo-owner",
        allow=[],
        deny=[],
        restrictions={},
    )


class ObjectSpec(DomainModel):
    path: str = Field(min_length=1)
    media_type: str = Field(pattern=_MEDIA_TYPE_PATTERN)
    access_class: AccessClass | None = None

    @field_validator("path")
    @classmethod
    def _relative_posix_path(cls, value: str) -> str:
        if value.startswith("/") or "\\" in value or ".." in value.split("/"):
            raise ValueError("object path must be a relative POSIX path without '..' segments")
        return value


class SourceManifest(DomainModel):
    SCHEMA_NAME: ClassVar[str | None] = "source-manifest"

    manifest_version: Literal[1]
    key: str = Field(pattern=_KEY_PATTERN)
    title: str = Field(min_length=1)
    source_type: SourceType
    languages: list[LANG_CODE] = Field(min_length=1)
    provenance: Provenance
    acquired_at: datetime
    domains: list[str] = Field(default_factory=list)
    registers: list[str] = Field(default_factory=list)
    policy: PolicySpec | None = None
    objects: list[ObjectSpec] = Field(default_factory=list)

    @property
    def resolved_policy(self) -> PolicySpec:
        """The manifest's policy, or the permissive presence-based default (ADR-0025)."""
        return self.policy if self.policy is not None else default_policy_spec()

    @field_validator("languages")
    @classmethod
    def _languages_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("languages must be unique")
        return value

    @model_validator(mode="after")
    def _objects_consistent(self) -> "SourceManifest":
        paths = [obj.path for obj in self.objects]
        if len(set(paths)) != len(paths):
            raise ValueError("object paths must be unique")
        policy = self.resolved_policy
        if not self.objects and policy.mode is not PolicyMode.EXCLUDE:
            raise ValueError("objects are required unless policy mode is exclude")
        for obj in self.objects:
            if obj.access_class is not None and access_rank(obj.access_class) < access_rank(
                policy.access_class
            ):
                raise ValueError("object access_class must not be more permissive than policy")
        return self

    def manifest_sha256(self) -> str:
        return sha256_bytes(canonical_json(self.model_dump(mode="json")).encode("utf-8"))


class SourcePolicy(DomainModel):
    SCHEMA_NAME: ClassVar[str | None] = "source-policy"

    id: id_field(IdPrefix.POLICY)  # type: ignore[valid-type]
    mode: PolicyMode
    access_class: AccessClass
    authority: str = Field(min_length=1)
    allow: tuple[Operation, ...]
    deny: tuple[Operation, ...]
    restrictions: dict[str, JsonValue] = Field(default_factory=dict)
    policy_version: int = Field(default=1, ge=1)
    created_at: datetime

    @field_validator("allow", "deny")
    @classmethod
    def _sorted_and_deduplicated(cls, value: tuple[Operation, ...]) -> tuple[Operation, ...]:
        return _sorted_unique(value)

    @model_validator(mode="after")
    def _lists_respect_baseline(self) -> "SourcePolicy":
        _check_policy_lists(self.mode, self.allow, self.deny)
        return self


class Source(DomainModel):
    SCHEMA_NAME: ClassVar[str | None] = "source"

    id: id_field(IdPrefix.SOURCE)  # type: ignore[valid-type]
    key: str = Field(pattern=_KEY_PATTERN)
    title: str = Field(min_length=1)
    source_type: SourceType
    languages: tuple[LANG_CODE, ...]
    provenance: Provenance
    policy_id: id_field(IdPrefix.POLICY)  # type: ignore[valid-type]
    acquired_at: datetime
    status: SourceStatus = SourceStatus.REGISTERED
    domains: tuple[str, ...]
    registers: tuple[str, ...]
    manifest_sha256: SHA256
    registration_run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime
    updated_at: datetime


class SourceObject(DomainModel):
    SCHEMA_NAME: ClassVar[str | None] = "source-object"

    id: id_field(IdPrefix.SOURCE_OBJECT)  # type: ignore[valid-type]
    source_id: id_field(IdPrefix.SOURCE)  # type: ignore[valid-type]
    original_path: str
    origin_uri: str = Field(pattern=r"^file:///")
    sha256: SHA256
    size_bytes: int = Field(ge=0)
    media_type: str = Field(pattern=_MEDIA_TYPE_PATTERN)
    access_class: AccessClass
    registration_run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime


class RawBlob(DomainModel):
    sha256: SHA256
    size_bytes: int = Field(ge=0)
    storage_backend: Literal["local"]
    stored_at: datetime
    ingestion_run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
