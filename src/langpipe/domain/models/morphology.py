"""Milestone 5 morphology graph domain models (ADR-0017, M5-PLAN §7.4).

Morphemes, allomorphs and analyses are hypotheses, never truth (Invariant 3):
their default `LifecycleStatus` is `candidate`, only `morph-v1` may move them to
`supported`, and only an authorized review reaches `validated`/`rejected`.
`IGTObservation` (``models/igt.py``) is the observation layer this graph is
asserted over; `MorphSegment` rows are append-only facts about one analysis and
`MorphGold` is a frozen benchmark fixture, not linguistic knowledge.

Scope fence (ADR-0013 §2, unchanged): no paradigm, slot or lexeme link appears
here — those stay deferred OPEN items in MORPHOLOGY.md.
"""

import re
import unicodedata
from datetime import datetime
from typing import Annotated, Any, ClassVar

from pydantic import ConfigDict, Field, field_validator, model_validator

from langpipe.domain.enums import (
    Abstention,
    AllomorphConditioning,
    AnalysisKind,
    FeatureAssignmentBasis,
    FormBasis,
    LifecycleStatus,
    MorphRole,
    SpanRepresentation,
)
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.base import (
    LANG_CODE,
    SHA256,
    VERSIONED_NAME,
    DomainModel,
    id_field,
)
from langpipe.domain.models.lexical import LexicalScoreBreakdown

# The lexical score breakdown is the generic versioned scoring record; `morph-v1`
# writes it with `policy_version="morph-v1"` (M5-PLAN §7.4).
ScoreBreakdown = LexicalScoreBreakdown

# Feature namespaces: the external vocabularies known in M5, plus the local
# per-language namespace `local:<lang>` (ADR-0017 §6). No other external
# namespace is accepted until its mapping is specified.
_NAMESPACE = re.compile(r"^(unimorph|ud|local:[a-z]{3})$")


def _glosses_are_language_tagged(glosses: dict[str, list[str]]) -> dict[str, list[str]]:
    # Same contract as `Sense.glosses` (M5-PLAN §7.4 "Sense validator reused"):
    # language-tagged contact-meaning hypotheses, never target-language forms.
    # models/lexical.py is outside this work package's owned files, so the checks
    # are repeated here rather than imported from it.
    for tag, entries in glosses.items():
        if len(tag) != 3 or not tag.isalpha() or not tag.islower():
            raise ValueError("gloss language tag must match ^[a-z]{3}$")
        if not entries:
            raise ValueError("a gloss language entry must list at least one gloss")
        for gloss in entries:
            if not gloss.strip():
                raise ValueError("glosses must be nonempty strings")
    return glosses


class Feature(DomainModel):
    """One gloss label in the append-only feature vocabulary, keyed `(namespace, label)`.

    Features carry no source lineage: a gloss label is not source content, so
    revocation never removes vocabulary (ADR-0017 §6) — the `MorphSegmentFeature`
    assignment rows carry the governed link.
    """

    SCHEMA_NAME: ClassVar[str | None] = "feature"

    id: id_field(IdPrefix.FEATURE)  # type: ignore[valid-type]
    namespace: str
    label: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    defined_by: str
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime

    @field_validator("namespace")
    @classmethod
    def _namespace_is_known(cls, value: str) -> str:
        if _NAMESPACE.fullmatch(value) is None:
            raise ValueError("namespace must be unimorph, ud or local:<lang>")
        return value


class Morpheme(DomainModel):
    """A hypothesized morpheme. Identity is per producing run (ADR-0017 §8)."""

    SCHEMA_NAME: ClassVar[str | None] = "morpheme"

    id: id_field(IdPrefix.MORPHEME)  # type: ignore[valid-type]
    language: LANG_CODE
    role: MorphRole
    canonical_form: str | None = None
    form_basis: FormBasis
    glosses: dict[str, list[str]] = Field(default_factory=dict)
    gloss_labels: list[str] = Field(default_factory=list)
    identity_key: SHA256
    status: LifecycleStatus = LifecycleStatus.CANDIDATE
    score_breakdown: ScoreBreakdown | None = None
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime

    @field_validator("glosses")
    @classmethod
    def _glosses_valid(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        return _glosses_are_language_tagged(value)

    @model_validator(mode="after")
    def _canonical_form_is_nfc(self) -> "Morpheme":
        if self.canonical_form is not None and not unicodedata.is_normalized(
            "NFC", self.canonical_form
        ):
            raise ValueError("canonical_form must be NFC-normalized")
        return self


class Allomorph(DomainModel):
    """One realized form of a morpheme; unique by `(morpheme_id, form)` (ADR-0017 §8)."""

    SCHEMA_NAME: ClassVar[str | None] = "allomorph"

    id: id_field(IdPrefix.ALLOMORPH)  # type: ignore[valid-type]
    morpheme_id: id_field(IdPrefix.MORPHEME)  # type: ignore[valid-type]
    form: str
    is_zero: bool = False
    form_basis: FormBasis
    conditioning: AllomorphConditioning
    conditioning_note: str | None = None
    status: LifecycleStatus = LifecycleStatus.CANDIDATE
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime

    @model_validator(mode="after")
    def _form_is_nfc_and_nonempty_unless_zero(self) -> "Allomorph":
        if self.form == "" and not self.is_zero:
            raise ValueError("an empty form is allowed only for a zero allomorph")
        if self.form != "" and not unicodedata.is_normalized("NFC", self.form):
            raise ValueError("form must be NFC-normalized")
        return self


class MorphSegment(DomainModel):
    """One piece of one analysis: a span fact plus optional morpheme/role links.

    Append-only; a segment links at most one `Morpheme` (fusion stays open,
    OPEN-MORPH-001) and realizes features through `MorphSegmentFeature`.
    """

    SCHEMA_NAME: ClassVar[str | None] = "morph-segment"

    id: id_field(IdPrefix.MORPH_SEGMENT)  # type: ignore[valid-type]
    analysis_id: id_field(IdPrefix.MORPH_ANALYSIS)  # type: ignore[valid-type]
    ordinal: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    is_zero: bool = False
    surface: str
    morpheme_id: id_field(IdPrefix.MORPHEME) | None = None  # type: ignore[valid-type]
    allomorph_id: id_field(IdPrefix.ALLOMORPH) | None = None  # type: ignore[valid-type]
    role: MorphRole | None = None
    source_gloss: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def _span_and_link_rules(self) -> "MorphSegment":
        if self.start > self.end:
            raise ValueError("segment start must not exceed end")
        if self.start == self.end and not self.is_zero:
            raise ValueError("an empty span requires is_zero=True")
        if self.allomorph_id is not None and self.morpheme_id is None:
            raise ValueError("allomorph_id requires morpheme_id")
        return self


class MorphSegmentFeature(DomainModel):
    """Assignment of a feature to a segment, with its assignment basis.

    This join carries the governed link between vocabulary and sources: the
    feature row itself has no source lineage (ADR-0017 §6).
    """

    SCHEMA_NAME: ClassVar[str | None] = "morph-segment-feature"

    segment_id: id_field(IdPrefix.MORPH_SEGMENT)  # type: ignore[valid-type]
    feature_id: id_field(IdPrefix.FEATURE)  # type: ignore[valid-type]
    basis: FeatureAssignmentBasis
    created_at: datetime


class MorphAnalysis(DomainModel):
    """A hypothesized segmentation of one token occurrence (competing rows allowed).

    `signature` is the canonical segmentation signature (``morphology.spans``);
    `method` is a versioned method name; an `unsegmented` analysis carries an
    optional `abstention` reason and is a hypothesis like any other (ADR-0017 §5).
    """

    SCHEMA_NAME: ClassVar[str | None] = "morph-analysis"

    id: id_field(IdPrefix.MORPH_ANALYSIS)  # type: ignore[valid-type]
    target_token_id: id_field(IdPrefix.TOKEN)  # type: ignore[valid-type]
    analysis_kind: AnalysisKind
    method: VERSIONED_NAME
    span_representation: SpanRepresentation
    surface: str
    signature: SHA256
    abstention: Abstention | None = None
    status: LifecycleStatus = LifecycleStatus.CANDIDATE
    score_breakdown: ScoreBreakdown | None = None
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime


CharSpan = Annotated[
    list[Annotated[int, Field(ge=0)]],
    Field(
        min_length=2,
        max_length=2,
        description="[start, end] character offset pair where 0 <= start <= end",
    ),
]


def _validate_morph_span(span: Any, kind: str, surface: str | None = None) -> list[int]:
    if not isinstance(span, (list, tuple)) or len(span) != 2:
        raise ValueError(f"{kind} span must be a [start, end] pair of ints, got {span}")
    start, end = span[0], span[1]
    if (
        not isinstance(start, int)
        or not isinstance(end, int)
        or isinstance(start, bool)
        or isinstance(end, bool)
    ):
        raise ValueError(f"{kind} span indices must be integers, got {span}")
    if start < 0 or end < start:
        raise ValueError(f"invalid {kind} span offsets: {span}")
    if surface is not None and end > len(surface):
        raise ValueError(f"{kind} span {span} exceeds surface length {len(surface)}")
    return [start, end]


class MorphGoldSelector(DomainModel):
    """Selector identifying an observed token in the corpus or IGT."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        json_schema_extra={
            "description": (
                "Selector identifying an observed token in the corpus or IGT. "
                "Must specify at least one of observation_id, igt_ref, record_ref, "
                "record_ordinal, or segment_locator with non-empty values."
            ),
            "anyOf": [
                {
                    "properties": {"observation_id": {"type": "string"}},
                    "required": ["observation_id"],
                },
                {
                    "properties": {"igt_ref": {"type": "string"}},
                    "required": ["igt_ref"],
                },
                {
                    "properties": {"record_ref": {"type": "string"}},
                    "required": ["record_ref"],
                },
                {
                    "properties": {"record_ordinal": {"type": "integer"}},
                    "required": ["record_ordinal"],
                },
                {
                    "properties": {"segment_locator": {"type": "object"}},
                    "required": ["segment_locator"],
                },
            ],
        },
    )

    observation_id: str | None = Field(default=None, pattern=r"\S")
    segment_id: str | None = Field(default=None, pattern=r"\S")
    igt_ref: str | None = Field(default=None, pattern=r"\S")
    record_ref: str | None = Field(default=None, pattern=r"\S")
    record_ordinal: int | None = Field(default=None, ge=0)
    source_key: str | None = Field(default=None, pattern=r"\S")
    segment_locator: dict[str, Any] | None = Field(
        default=None, json_schema_extra={"minProperties": 1}
    )
    token_ordinal: int | None = Field(default=None, ge=0)
    word_ordinal: int | None = Field(default=None, ge=0)

    @field_validator("segment_locator", mode="after")
    @classmethod
    def _validate_locator(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and len(v) == 0:
            raise ValueError("segment_locator must not be empty")
        return v

    @model_validator(mode="after")
    def _validate_selector(self) -> "MorphGoldSelector":
        has_obs = self.observation_id is not None
        has_igt = self.igt_ref is not None
        has_rec = self.record_ref is not None
        has_ord = self.record_ordinal is not None
        has_loc = self.segment_locator is not None
        if not (has_obs or has_igt or has_rec or has_ord or has_loc):
            raise ValueError(
                "selector must specify at least one of observation_id, igt_ref, "
                "record_ref, record_ordinal, or segment_locator"
            )
        return self

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) and getattr(self, key) is not None


class MorphGoldItem(DomainModel):
    """One gold annotation item with selector and character spans."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        json_schema_extra={
            "description": (
                "One gold annotation item with selector and character spans. "
                "Character spans must be [start, end] pairs with 0 <= start <= end. "
                "When surface is provided, end <= len(surface) is strictly enforced."
            ),
        },
    )

    selector: MorphGoldSelector
    surface: str | None = None
    segments: list[CharSpan] = Field(..., min_length=1)
    affix_spans: list[CharSpan] = Field(default_factory=list)
    root_span: CharSpan | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("segments", mode="before")
    @classmethod
    def _validate_segments(cls, v: Any) -> Any:
        if not isinstance(v, (list, tuple)) or len(v) == 0:
            raise ValueError("gold item segments must not be empty")
        return [_validate_morph_span(span, "segment") for span in v]

    @field_validator("affix_spans", mode="before")
    @classmethod
    def _validate_affixes(cls, v: Any) -> Any:
        if isinstance(v, (list, tuple)):
            return [_validate_morph_span(span, "affix") for span in v]
        return v

    @field_validator("root_span", mode="before")
    @classmethod
    def _validate_root(cls, v: Any) -> Any:
        if v is not None:
            return _validate_morph_span(v, "root")
        return None

    @model_validator(mode="after")
    def _validate_item(self) -> "MorphGoldItem":
        if not self.segments:
            raise ValueError("gold item segments must not be empty")
        if self.surface is not None:
            surf_len = len(self.surface)
            for span in self.segments:
                if span[1] > surf_len:
                    raise ValueError(f"segment span {span} exceeds surface length {surf_len}")
            for span in self.affix_spans:
                if span[1] > surf_len:
                    raise ValueError(f"affix span {span} exceeds surface length {surf_len}")
            if self.root_span is not None and self.root_span[1] > surf_len:
                raise ValueError(f"root span {self.root_span} exceeds surface length {surf_len}")
        return self

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) and getattr(self, key) is not None


class MorphGold(DomainModel):
    """A frozen benchmark fixture over held-out items; never linguistic truth."""

    SCHEMA_NAME: ClassVar[str | None] = "morph-gold"

    gold_id: str
    language: LANG_CODE
    items: list[MorphGoldItem] = Field(..., min_length=1)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_items(self) -> "MorphGold":
        if not self.items:
            raise ValueError("gold items list must not be empty")
        return self

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)
