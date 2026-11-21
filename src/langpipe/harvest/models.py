"""Data models for universal indigenous resource harvesting."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RepositoryCategory(str, Enum):  # noqa: UP042 - str() must stay "RepositoryCategory.X"
    SCHOLARLY_AGGREGATOR = "scholarly_aggregator"
    LINGUISTIC_ARCHIVE = "linguistic_archive"
    PARALLEL_CORPUS = "parallel_corpus"
    COMMUNITY_PORTAL = "community_portal"


class HarvestPolicy(str, Enum):  # noqa: UP042 - str()/f-string must stay "HarvestPolicy.X"
    PERMISSIVE_ACADEMIC = "permissive_academic"
    DISTILL_ONLY = "distill_only"
    RESTRICTED = "restricted"
    PUBLIC_DOMAIN = "public_domain"
    # ADR-0025: presence in the repository is authorization; this is the default label.
    DIRECT = "direct"


class HarvestStatus(str, Enum):  # noqa: UP042 - str()/f-string must stay "HarvestStatus.X"
    INDEXED = "indexed"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    VERIFIED = "verified"
    EXTRACTED = "extracted"
    FAILED = "failed"


class DiscoveredResource(BaseModel):
    """A resource discovered by a spider or registered in the universal catalog."""

    source_id: str
    language_code: str
    glottocode: str | None = None
    title: str
    author: str | None = None
    year: int | None = None
    repository_id: str
    url: str
    download_url: str | None = None
    local_path: str | None = None
    sha256: str | None = None
    file_size_bytes: int | None = None
    mime_type: str = "application/pdf"
    policy: HarvestPolicy = HarvestPolicy.PERMISSIVE_ACADEMIC
    status: HarvestStatus = HarvestStatus.INDEXED
    features: list[str] = Field(default_factory=list)
    related_languages: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class HarvesterTarget(BaseModel):
    """Query target for discovering resources for an indigenous language."""

    model_config = {"extra": "ignore", "populate_by_name": True}

    iso639_3: str
    language_name: str = ""
    autonym: str | None = None
    glottocode: str | None = None
    asjp_code: str | None = None
    family: str = "Indigenous"
    contact_language: str = "por"
    known_dialects: list[str] = Field(default_factory=list)
    sister_languages: list[str] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list)

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "HarvesterTarget":
        if isinstance(obj, dict) and "language_name" not in obj and "name" in obj:
            obj["language_name"] = obj["name"]
        return super().model_validate(obj, *args, **kwargs)
