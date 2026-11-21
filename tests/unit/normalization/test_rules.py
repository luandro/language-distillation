import pytest

from langpipe.domain.errors import NormalizationFailed
from langpipe.normalization.base import NormalizationEvent
from langpipe.normalization.profiles import DEFAULT_TEXT_PROFILE, UNICODE_NFC_PROFILE


# Name kept from the WP2.5 spec for traceability. Its input is U+0301 (acute), though the name says
# "tilde"; test_nfc_composes_decomposed_tilde_with_real_tilde_and_spans covers U+0303.
def test_nfc_composes_decomposed_tilde_with_event_and_spans() -> None:
    raw = "kanú"

    result = UNICODE_NFC_PROFILE.normalize(raw)

    assert result.normalized == "kanú"
    assert result.events == (NormalizationEvent("nfc", 3, 5, 3, 4),)
    assert result.offsets.boundary == (0, 1, 2, 3, 5)
    assert result.diagnostics == {}


def test_nfc_composes_decomposed_tilde_with_real_tilde_and_spans() -> None:
    # Real combining tilde (U+0303). The test name above says "tilde" but its input is U+0301
    # (acute); this case covers the spec's tilde example.
    raw = "kanã"

    result = UNICODE_NFC_PROFILE.normalize(raw)

    assert result.normalized == "kanã"
    assert result.events == (NormalizationEvent("nfc", 3, 5, 3, 4),)
    assert result.offsets.boundary == (0, 1, 2, 3, 5)


def test_nfc_leading_mark_joins_first_chunk_with_one_starter() -> None:
    # U+0301 precedes the first starter, so it joins that chunk: raw [0,3) -> norm [0,2).
    raw = "́á"

    result = UNICODE_NFC_PROFILE.normalize(raw)

    assert result.normalized == "́á"
    assert result.events == (NormalizationEvent("nfc", 0, 3, 0, 2),)
    assert result.offsets.boundary == (0, 0, 3)
    assert result.diagnostics == {}


def test_nfc_leading_mark_joins_first_chunk_with_two_starters() -> None:
    # The second starter starts its own chunk, so only the first chunk changes at raw [0,3).
    raw = "́áé"

    result = UNICODE_NFC_PROFILE.normalize(raw)

    assert result.normalized == "́áé"
    assert result.events == (
        NormalizationEvent("nfc", 0, 3, 0, 2),
        NormalizationEvent("nfc", 3, 5, 2, 3),
    )
    assert result.offsets.boundary == (0, 0, 3, 5)


def test_nfc_leading_mark_with_unchanged_first_starter_emits_no_event() -> None:
    raw = "́b́"

    result = UNICODE_NFC_PROFILE.normalize(raw)

    assert result.normalized == raw
    assert result.events == ()


def test_nfc_all_mark_text_is_unchanged_and_emits_no_event() -> None:
    raw = "́́"

    result = UNICODE_NFC_PROFILE.normalize(raw)

    assert result.normalized == raw
    assert result.events == ()
    assert result.offsets.boundary == (0, 1, 2)


def test_nfc_already_composed_emits_no_event() -> None:
    raw = "kanú"

    result = UNICODE_NFC_PROFILE.normalize(raw)

    assert result.normalized == raw
    assert result.events == ()
    assert result.diagnostics == {}


def test_nfc_whole_segment_fallback_when_chunks_compose_across_starters() -> None:
    # Hangul L + V jamo are starters, so chunk-wise NFC cannot compose them; the whole text must be
    # normalized as one chunk and the fallback is counted.
    raw = "가"

    result = UNICODE_NFC_PROFILE.normalize(raw)

    assert result.normalized == "가"
    assert result.events == (NormalizationEvent("nfc", 0, 2, 0, 1),)
    assert result.diagnostics == {"nfc_whole_segment_fallback": 1}


def test_whitespace_collapses_nbsp_and_tabs_with_events() -> None:
    raw = "\tfoo  bar "

    result = DEFAULT_TEXT_PROFILE.normalize(raw)

    assert result.normalized == "foo bar"
    assert result.events == (
        NormalizationEvent("whitespace", 0, 1, 0, 0),
        NormalizationEvent("whitespace", 4, 6, 3, 4),
    )


def test_whitespace_single_space_emits_no_event() -> None:
    result = DEFAULT_TEXT_PROFILE.normalize("foo bar")

    assert result.normalized == "foo bar"
    assert result.events == ()


def test_crlf_and_tab_are_allowed_and_collapse_to_space() -> None:
    result = DEFAULT_TEXT_PROFILE.normalize("a\r\n\tb")

    assert result.normalized == "a b"


def test_zero_width_kept_and_diagnosed() -> None:
    raw = "a​b﻿"

    result = DEFAULT_TEXT_PROFILE.normalize(raw)

    assert result.normalized == raw
    assert result.events == ()
    assert result.diagnostics == {"zero_width:U+200B": 1, "zero_width:U+FEFF": 1}


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("a�b", "replacement_char"),
        ("a\x07b", "control_char"),
        ("a\x85b", "control_char"),
        ("   ", "empty_after_normalization"),
        ("\t\r\n", "empty_after_normalization"),
        ("", "empty_after_normalization"),
    ],
)
def test_failure_codes(raw: str, code: str) -> None:
    with pytest.raises(NormalizationFailed) as excinfo:
        DEFAULT_TEXT_PROFILE.normalize(raw)

    assert excinfo.value.code == code


@pytest.mark.parametrize("ch", ["\x00", "\x01", "\x08", "\x0b", "\x0c", "\x0e", "\x1f"])
def test_c0_controls_other_than_tab_lf_cr_fail(ch: str) -> None:
    with pytest.raises(NormalizationFailed) as excinfo:
        UNICODE_NFC_PROFILE.normalize(f"a{ch}b")

    assert excinfo.value.code == "control_char"


@pytest.mark.parametrize("ch", ["\x80", "\x85", "\x9e", "\x9f"])
def test_c1_controls_fail(ch: str) -> None:
    with pytest.raises(NormalizationFailed) as excinfo:
        UNICODE_NFC_PROFILE.normalize(f"a{ch}b")

    assert excinfo.value.code == "control_char"


def test_tab_lf_cr_are_allowed_at_control_boundaries() -> None:
    result = UNICODE_NFC_PROFILE.normalize("a\tb\nc\rd")

    assert result.normalized == "a\tb\nc\rd"


def test_del_and_code_points_just_outside_c1_are_not_control_failures() -> None:
    # The spec's control_char set is C0 U+0000-U+001F plus C1 U+0080-U+009F, so DEL (U+007F) and
    # U+00A0 stay allowed.
    raw = "a\x7fb c¡"

    assert UNICODE_NFC_PROFILE.normalize(raw).normalized == raw
