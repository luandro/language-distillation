from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from langpipe.domain.enums import SegmentStatus, SpanRepresentation
from langpipe.domain.errors import SchemaViolation
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.observation import Form, Segment, Span, TokenOccurrence

NOW = datetime(2026, 1, 1, tzinfo=UTC)
PROFILE = "mzr-nfc@1.0"


def _segment(
    raw_text: str = "abcdef",
    normalized_text: str | None = None,
    normalization_profile: str | None = None,
    status: SegmentStatus = SegmentStatus.OK,
) -> Segment:
    return Segment(
        id=new_id(IdPrefix.SEGMENT),
        source_id=new_id(IdPrefix.SOURCE),
        source_object_id=new_id(IdPrefix.SOURCE_OBJECT),
        run_id=new_id(IdPrefix.RUN),
        ordinal=0,
        language="mzr",
        raw_text=raw_text,
        normalized_text=normalized_text,
        normalization_profile=normalization_profile,
        status=status,
        created_at=NOW,
    )


def _token(segment: Segment, raw_surface: str, raw_span: Span | None) -> TokenOccurrence:
    return TokenOccurrence(
        id=new_id(IdPrefix.TOKEN),
        segment_id=segment.id,
        run_id=segment.run_id,
        ordinal=0,
        raw_surface=raw_surface,
        raw_span=raw_span,
        tokenizer="whitespace@1",
        created_at=NOW,
    )


def test_token_span_must_match_segment_raw_text() -> None:
    segment = _segment("abcdef")
    raw = SpanRepresentation.RAW
    _token(segment, "cd", Span(representation=raw, start=2, end=4)).check_against(segment)

    with pytest.raises(SchemaViolation):
        _token(segment, "xx", Span(representation=raw, start=2, end=4)).check_against(segment)
    with pytest.raises(SchemaViolation):
        _token(segment, "f", Span(representation=raw, start=5, end=99)).check_against(segment)
    with pytest.raises(SchemaViolation):
        other = _segment("abcdef")
        _token(segment, "cd", Span(representation=raw, start=2, end=4)).check_against(other)


def test_token_span_representation_is_checked_at_construction() -> None:
    segment = _segment("abcdef")
    with pytest.raises(ValidationError):
        TokenOccurrence(
            id=new_id(IdPrefix.TOKEN),
            segment_id=segment.id,
            run_id=segment.run_id,
            ordinal=0,
            raw_surface="cd",
            raw_span=Span(representation=SpanRepresentation.NORMALIZED, start=2, end=4),
            tokenizer="whitespace@1",
            created_at=NOW,
        )


def _normalized_token(segment: Segment, normalized_surface: str, end: int = 4) -> TokenOccurrence:
    return TokenOccurrence(
        id=new_id(IdPrefix.TOKEN),
        segment_id=segment.id,
        run_id=segment.run_id,
        ordinal=0,
        raw_surface="CD",
        normalized_surface=normalized_surface,
        raw_span=Span(representation=SpanRepresentation.RAW, start=2, end=4),
        normalized_span=Span(representation=SpanRepresentation.NORMALIZED, start=2, end=end),
        tokenizer="whitespace@1",
        created_at=NOW,
    )


def test_token_normalized_span_must_match_normalized_text() -> None:
    segment = _segment("ABCDEF", normalized_text="abcdef", normalization_profile=PROFILE)
    _normalized_token(segment, "cd").check_against(segment)

    with pytest.raises(SchemaViolation):
        _normalized_token(segment, "xx").check_against(segment)
    with pytest.raises(SchemaViolation):
        _normalized_token(segment, "cd", end=99).check_against(segment)
    raw_only = _segment("ABCDEF")
    with pytest.raises(SchemaViolation):
        _normalized_token(raw_only, "cd").check_against(raw_only)


def test_span_slice_codepoints() -> None:
    precomposed = "ú"
    combining = "ú"
    assert len(precomposed) == 1
    assert len(combining) == 2

    whole = Span(representation=SpanRepresentation.RAW, start=0, end=1)
    assert whole.slice(precomposed) == precomposed
    assert whole.slice(combining) == "u"
    accent = Span(representation=SpanRepresentation.RAW, start=1, end=2)
    assert accent.slice(combining) == "́"


def test_span_end_exclusive() -> None:
    assert Span(representation=SpanRepresentation.RAW, start=0, end=1).slice("abc") == "a"
    assert Span(representation=SpanRepresentation.RAW, start=0, end=3).slice("abc") == "abc"
    assert Span(representation=SpanRepresentation.RAW, start=1, end=1).slice("abc") == ""
    with pytest.raises(ValidationError):
        Span(representation=SpanRepresentation.RAW, start=2, end=1)


@given(text=st.text(), data=st.data())
def test_span_slice_roundtrip(text: str, data: st.DataObject) -> None:
    start = data.draw(st.integers(min_value=0, max_value=len(text)))
    end = data.draw(st.integers(min_value=start, max_value=len(text)))
    span = Span(representation=SpanRepresentation.RAW, start=start, end=end)
    assert span.slice(text) == text[start:end]
    assert text[:start] + span.slice(text) + text[end:] == text


def test_form_rejects_non_nfc() -> None:
    kwargs = {
        "id": new_id(IdPrefix.FORM),
        "language": "mzr",
        "orthography_profile": PROFILE,
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    Form(text="ú", **kwargs)
    with pytest.raises(ValidationError):
        Form(text="ú", **kwargs)


def test_segment_normalized_requires_profile() -> None:
    _segment(normalized_text="abc", normalization_profile=PROFILE)
    _segment()
    with pytest.raises(ValidationError):
        _segment(normalized_text="abc")
    with pytest.raises(ValidationError):
        _segment(normalization_profile=PROFILE)


def test_normalization_failed_has_no_normalized_text() -> None:
    _segment(status=SegmentStatus.NORMALIZATION_FAILED)
    with pytest.raises(ValidationError):
        _segment(
            normalized_text="abc",
            normalization_profile=PROFILE,
            status=SegmentStatus.NORMALIZATION_FAILED,
        )
