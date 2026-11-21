import unicodedata
from datetime import datetime
from typing import ClassVar

from pydantic import Field, model_validator

from langpipe.domain.enums import SegmentStatus, SpanRepresentation
from langpipe.domain.errors import SchemaViolation
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.base import LANG_CODE, VERSIONED_NAME, DomainModel, id_field


class Span(DomainModel):
    """Half-open code-point range `[start, end)` over one text representation."""

    representation: SpanRepresentation
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _start_not_after_end(self) -> "Span":
        if self.start > self.end:
            raise ValueError("span start must be <= end")
        return self

    def slice(self, text: str) -> str:
        return text[self.start : self.end]


class Segment(DomainModel):
    SCHEMA_NAME: ClassVar[str | None] = "segment"

    id: id_field(IdPrefix.SEGMENT)  # type: ignore[valid-type]
    source_id: id_field(IdPrefix.SOURCE)  # type: ignore[valid-type]
    source_object_id: id_field(IdPrefix.SOURCE_OBJECT)  # type: ignore[valid-type]
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    ordinal: int = Field(ge=0)
    language: LANG_CODE
    locator: dict[str, str | int] = Field(default_factory=dict)
    raw_text: str
    normalized_text: str | None = None
    normalization_profile: VERSIONED_NAME | None = None
    status: SegmentStatus = SegmentStatus.OK
    created_at: datetime

    @model_validator(mode="after")
    def _normalization_fields_are_paired(self) -> "Segment":
        if (self.normalized_text is None) != (self.normalization_profile is None):
            raise ValueError("normalized_text and normalization_profile must be set together")
        if self.status is SegmentStatus.NORMALIZATION_FAILED and self.normalized_text is not None:
            raise ValueError("a normalization_failed segment must not carry normalized_text")
        return self


class TokenOccurrence(DomainModel):
    SCHEMA_NAME: ClassVar[str | None] = "token-occurrence"

    id: id_field(IdPrefix.TOKEN)  # type: ignore[valid-type]
    segment_id: id_field(IdPrefix.SEGMENT)  # type: ignore[valid-type]
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    ordinal: int = Field(ge=0)
    raw_surface: str = Field(min_length=1)
    normalized_surface: str | None = None
    raw_span: Span | None = None
    normalized_span: Span | None = None
    tokenizer: VERSIONED_NAME
    form_id: id_field(IdPrefix.FORM) | None = None  # type: ignore[valid-type]
    created_at: datetime

    @model_validator(mode="after")
    def _span_representations(self) -> "TokenOccurrence":
        if self.raw_span is not None and self.raw_span.representation is not SpanRepresentation.RAW:
            raise ValueError("raw_span must use the raw representation")
        if (
            self.normalized_span is not None
            and self.normalized_span.representation is not SpanRepresentation.NORMALIZED
        ):
            raise ValueError("normalized_span must use the normalized representation")
        return self

    def check_against(self, segment: Segment) -> None:
        if self.segment_id != segment.id:
            raise SchemaViolation()
        if self.raw_span is not None:
            _check_span(self.raw_span, segment.raw_text, self.raw_surface)
        if self.normalized_span is not None:
            if segment.normalized_text is None or self.normalized_surface is None:
                raise SchemaViolation()
            _check_span(self.normalized_span, segment.normalized_text, self.normalized_surface)


def _check_span(span: Span, text: str, surface: str) -> None:
    if span.end > len(text) or span.slice(text) != surface:
        raise SchemaViolation()


class Form(DomainModel):
    SCHEMA_NAME: ClassVar[str | None] = "form"

    id: id_field(IdPrefix.FORM)  # type: ignore[valid-type]
    language: LANG_CODE
    orthography_profile: VERSIONED_NAME
    text: str = Field(min_length=1)
    run_id: id_field(IdPrefix.RUN)  # type: ignore[valid-type]
    created_at: datetime

    @model_validator(mode="after")
    def _text_is_nfc(self) -> "Form":
        if not unicodedata.is_normalized("NFC", self.text):
            raise ValueError("form text must be NFC-normalized")
        return self
