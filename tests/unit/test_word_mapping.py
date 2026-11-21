"""Unit tests for sequential word mapping (WP5.9, Gate 38)."""

from datetime import UTC, datetime

from langpipe.domain.enums import SpanRepresentation
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.igt import IgtMorph, IgtWord
from langpipe.domain.models.observation import Span, TokenOccurrence
from langpipe.morphology.word_mapping import is_pure_punctuation, map_words


def _token(raw: str, norm: str | None = None) -> TokenOccurrence:
    raw_span = Span(start=0, end=len(raw), representation=SpanRepresentation.RAW)
    norm_span = None
    if norm is not None:
        norm_span = Span(start=0, end=len(norm), representation=SpanRepresentation.NORMALIZED)
    return TokenOccurrence(
        id=new_id(IdPrefix.TOKEN),
        segment_id="seg_01JGZZZZZZZZZZZZZZZZZZZZ01",
        run_id="run_01JGZZZZZZZZZZZZZZZZZZZZ01",
        ordinal=0,
        raw_surface=raw,
        normalized_surface=norm,
        raw_span=raw_span,
        normalized_span=norm_span,
        tokenizer="regex_whitespace@0.1.0",
        created_at=datetime.now(UTC),
    )


def _igt_word(ordinal: int, text: str) -> IgtWord:
    return IgtWord(
        ordinal=ordinal,
        text=text,
        morphs=[IgtMorph(ordinal=0, text=text)],
    )


def test_is_pure_punctuation() -> None:
    assert is_pure_punctuation(".")
    assert is_pure_punctuation(",")
    assert is_pure_punctuation(";")
    assert is_pure_punctuation("?!")
    assert is_pure_punctuation("---")
    assert not is_pure_punctuation("canoa")
    assert not is_pure_punctuation("canoa.")
    assert not is_pure_punctuation("wesa-ra")
    assert not is_pure_punctuation("")
    assert not is_pure_punctuation("   ")


def test_map_words_exact_match_with_punctuation_skipping() -> None:
    igt_words = [
        _igt_word(0, "mabi"),
        _igt_word(1, "ki"),
        _igt_word(2, "nawa"),
    ]
    t1 = _token("mabi", "mabi")
    t2 = _token("ki", "ki")
    t3 = _token("nawa", "nawa")
    t4 = _token(".", ".")
    tokens = [t1, t2, t3, t4]

    result = map_words(igt_words, tokens)
    assert len(result.mapped) == 3
    assert result.unmapped_counts["count_mismatch"] == 0
    assert result.unmapped_counts["surface_mismatch"] == 0

    assert result.mapped[0][0].text == "mabi"
    assert result.mapped[0][1].id == t1.id
    assert result.mapped[1][0].text == "ki"
    assert result.mapped[1][1].id == t2.id
    assert result.mapped[2][0].text == "nawa"
    assert result.mapped[2][1].id == t3.id

    # Verify tuple unpacking
    mapped, unmapped = result
    assert len(mapped) == 3


def test_map_words_count_mismatch_never_forces() -> None:
    igt_words = [
        _igt_word(0, "mabi"),
        _igt_word(1, "nawa"),
    ]
    # 3 non-punctuation tokens vs 2 IGT words
    tokens = [
        _token("mabi", "mabi"),
        _token("ki", "ki"),
        _token("nawa", "nawa"),
    ]

    result = map_words(igt_words, tokens)
    assert len(result.mapped) == 0
    assert result.unmapped_counts["count_mismatch"] == 2
    assert result.unmapped_counts["surface_mismatch"] == 0


def test_map_words_surface_mismatch() -> None:
    igt_words = [
        _igt_word(0, "mabi"),
        _igt_word(1, "wesa"),
    ]
    tokens = [
        _token("mabi", "mabi"),
        _token("nawa", "nawa"),
    ]

    result = map_words(igt_words, tokens)
    assert len(result.mapped) == 1
    assert result.mapped[0][0].text == "mabi"
    assert result.unmapped_counts["count_mismatch"] == 0
    assert result.unmapped_counts["surface_mismatch"] == 1


def test_map_words_with_normalizer() -> None:
    igt_words = [_igt_word(0, "MABI")]
    tokens = [_token("mabi", "mabi")]

    # Without normalizer: surface mismatch (case sensitive)
    res1 = map_words(igt_words, tokens)
    assert len(res1.mapped) == 0
    assert res1.unmapped_counts["surface_mismatch"] == 1

    # With casefold normalizer: matches
    res2 = map_words(igt_words, tokens, normalizer=str.casefold)
    assert len(res2.mapped) == 1
