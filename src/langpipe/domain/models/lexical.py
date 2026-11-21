"""Milestone 4 lexical evidence domain models (ADR-0013).

Hypotheses, never truth: `Lexeme`/`Sense`/`Concept` are candidate knowledge claims whose
`LifecycleStatus` only an authorized human review may move to `validated`. Contact-language
entries live in `Sense.glosses` as meaning hypotheses and are never target-language forms
(Invariants 2, 3, 8 and 9). Scope fence: no paradigm, slot or morphology bundle appears
anywhere in this module — morphology is Milestone 5 (ADR-0013 §2).
"""

import math
import re
from collections.abc import Mapping
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from langpipe.domain.enums import LifecycleStatus
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.base import LANG_CODE, DomainModel, id_field

# Language tag key of a `glosses` entry, e.g. "por"; Glosses are about meaning,
# never about the orthography of the target language.
_GLOSS_LANGUAGE_TAG = re.compile(r"^[a-z]{3}$")


def _finite_score(value: float) -> float:
    # bool is an int subclass and pydantic coerces it to 1.0; scores are never booleans.
    if isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("score values must be finite")
    return value


def _reject_boolean_mapping(value: object) -> object:
    # Before coercion: pydantic accepts any Mapping as dict[str, float] and would
    # otherwise turn True/False into 1.0/0.0.
    if isinstance(value, Mapping):
        for item in value.values():
            if isinstance(item, bool):
                raise ValueError("score values must be finite")
    return value


def _finite_mapping(value: dict[str, float]) -> dict[str, float]:
    return {name: _finite_score(score) for name, score in value.items()}


class LexicalScoreBreakdown(BaseModel):
    """Versioned raw scoring record for a lexical hypothesis. Never creates validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: str = Field(min_length=1)
    overall: float
    components: dict[str, float] = Field(default_factory=dict)
    penalties: dict[str, float] = Field(default_factory=dict)
    independence_groups: list[str] = Field(default_factory=list)

    @field_validator("overall", mode="before")
    @classmethod
    def _overall_is_not_bool(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("score values must be finite")
        return value

    @field_validator("overall")
    @classmethod
    def _overall_is_finite(cls, value: float) -> float:
        return _finite_score(value)

    @field_validator("components", "penalties", mode="before")
    @classmethod
    def _score_maps_are_not_bool(cls, value: object) -> object:
        return _reject_boolean_mapping(value)

    @field_validator("components", "penalties")
    @classmethod
    def _score_maps_are_finite(cls, value: dict[str, float]) -> dict[str, float]:
        return _finite_mapping(value)


class Concept(DomainModel):
    """A semantic referent, `local` by default with an optional external mapping."""

    SCHEMA_NAME: ClassVar[str | None] = "concept"

    id: id_field(IdPrefix.CONCEPT)  # type: ignore[valid-type]
    concept_type: str = Field(default="local", min_length=1)
    canonical_label: str = Field(min_length=1)
    concepticon_id: str | None = Field(default=None, min_length=1)
    external_urn: str | None = Field(default=None, min_length=1)
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime


class Lexeme(DomainModel):
    """An induced or curated lexical unit. No paradigms, slots or feature bundles (M4)."""

    SCHEMA_NAME: ClassVar[str | None] = "lexeme"

    id: id_field(IdPrefix.LEXEME)  # type: ignore[valid-type]
    language: LANG_CODE
    lemma_form_id: id_field(IdPrefix.FORM) | None = None  # type: ignore[valid-type]
    pos: str | None = Field(default=None, min_length=1)
    status: LifecycleStatus = LifecycleStatus.CANDIDATE
    register: str | None = Field(default=None, min_length=1)
    domain: str | None = Field(default=None, min_length=1)
    score_breakdown: LexicalScoreBreakdown | None = None
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime


class FormLexemeLink(DomainModel):
    """Explicit many-to-many join between orthographic forms and lexical hypotheses."""

    SCHEMA_NAME: ClassVar[str | None] = "form-lexeme-link"

    id: id_field(IdPrefix.FORM_LEXEME)  # type: ignore[valid-type]
    form_id: id_field(IdPrefix.FORM)  # type: ignore[valid-type]
    lexeme_id: id_field(IdPrefix.LEXEME)  # type: ignore[valid-type]
    role: str | None = Field(default=None, min_length=1)
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime

    @model_validator(mode="after")
    def _distinct_endpoints(self) -> "FormLexemeLink":
        if self.form_id == self.lexeme_id:
            raise ValueError("form_id and lexeme_id must differ")
        return self


class Sense(DomainModel):
    """One meaning hypothesis of a lexeme. Glosses are translations, never lexical forms."""

    SCHEMA_NAME: ClassVar[str | None] = "sense"

    id: id_field(IdPrefix.SENSE)  # type: ignore[valid-type]
    lexeme_id: id_field(IdPrefix.LEXEME)  # type: ignore[valid-type]
    glosses: dict[str, list[str]] = Field(default_factory=dict)
    concept_id: id_field(IdPrefix.CONCEPT) | None = None  # type: ignore[valid-type]
    status: LifecycleStatus = LifecycleStatus.CANDIDATE
    domain: str | None = Field(default=None, min_length=1)
    register: str | None = Field(default=None, min_length=1)
    score_breakdown: LexicalScoreBreakdown | None = None
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime

    @field_validator("glosses")
    @classmethod
    def _gloss_language_tags_and_surfaces(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        for tag, glosses in value.items():
            if _GLOSS_LANGUAGE_TAG.fullmatch(tag) is None:
                raise ValueError("gloss language tag must match ^[a-z]{3}$")
            if not glosses:
                raise ValueError("a gloss language entry must list at least one gloss")
            for gloss in glosses:
                if not gloss.strip():
                    raise ValueError("glosses must be nonempty strings")
        return value
