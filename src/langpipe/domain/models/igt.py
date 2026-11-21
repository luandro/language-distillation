"""Milestone 5 IGT observation domain model (ADR-0017 §1).

An `IGTObservation` is an observation, not an analysis (Invariant 2): the source's
tiers are preserved verbatim (marker, line number, raw line) alongside a parsed
layer modeled on Xigt (words → morphs → glosses) plus translations. Imported
glosses keep their source strings and are never mapped to a universal scheme at
import. Everything inferred from an observation lives in the morphology models
(``models/morphology.py``), never here.
"""

from datetime import datetime
from typing import Annotated, Any, ClassVar

from pydantic import Field, StringConstraints

from langpipe.domain.enums import IgtFormat, IgtParseStatus
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.base import LANG_CODE, DomainModel, id_field

# Morpheme boundary marks as written inside a parsed word: ``-`` (affix) and
# ``=`` (clitic). Profile boundary marks live on `MorphologyProfile`; this
# pattern fixes only what the IGT parse layer may record per morph.
_BOUNDARY_MARK = Annotated[str, StringConstraints(pattern=r"^[-=]$")] | None

# Fixed parse diagnostic codes (``missing_tier``, ``unparsed``, ...): lowercase
# snake_case only, so no free text — and no source content — can hide in the
# diagnostics list (invariant 7: no restricted text in reports).
_DIAGNOSTIC_CODE = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]


class IgtTierLine(DomainModel):
    """One verbatim source line of an IGT record (Invariant 1: never rewritten)."""

    marker: str
    line_number: int
    raw: str


class IgtMorph(DomainModel):
    """One parsed morph inside a word, with its verbatim source gloss (if any)."""

    ordinal: int
    text: str
    boundary_before: _BOUNDARY_MARK = None
    gloss: str | None = None


class IgtWord(DomainModel):
    """One parsed word of the text tier, segmented into its morphs."""

    ordinal: int
    text: str
    morphs: list[IgtMorph]


class IGTObservation(DomainModel):
    """A tiered interlinear record captured verbatim from a source object.

    Immutable evidence: append-only at the storage layer, `segment_id` links the
    text-tier `Segment` produced by the same extraction run (stage 7a), and
    `diagnostics` carries fixed parse codes — never free text, never source prose
    (Invariant: no restricted text in reports).
    """

    SCHEMA_NAME: ClassVar[str | None] = "igt-observation"

    id: id_field(IdPrefix.IGT_OBSERVATION)  # type: ignore[valid-type]
    source_id: id_field(IdPrefix.SOURCE)  # type: ignore[valid-type]
    source_object_id: id_field(IdPrefix.SOURCE_OBJECT)  # type: ignore[valid-type]
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    segment_id: id_field(IdPrefix.SEGMENT) | None = None  # type: ignore[valid-type]
    record_ordinal: int = Field(ge=0)
    record_ref: str | None = None
    format: IgtFormat
    locator: dict[str, Any]
    tiers: list[IgtTierLine]
    words: list[IgtWord]
    translations: dict[LANG_CODE, list[str]] = Field(default_factory=dict)
    parse_status: IgtParseStatus
    diagnostics: list[_DIAGNOSTIC_CODE] = Field(default_factory=list)
    created_at: datetime
