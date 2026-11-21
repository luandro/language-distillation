import unicodedata

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from langpipe.domain.errors import NormalizationFailed
from langpipe.normalization.base import NormalizationProfile, NormalizationResult
from langpipe.normalization.profiles import DEFAULT_TEXT_PROFILE, GENERIC_NORMALIZATION_PROFILES

# Fixed alphabet. Covers ASCII letters, combining marks (acute, tilde, diaeresis, cedilla,
# ypogegrammeni, combining enclosing arrow), every Zs space in the spec, TAB/LF/CR, zero-width
# characters, precomposed letters, Hangul syllable and jamo, and soft hyphen.
# Forbidden inputs are excluded on purpose: U+FFFD and C0/C1 controls other than TAB/LF/CR.
# test_forbidden_codepoints_always_fail covers those inputs separately.
_ALPHABET = "".join(
    (
        "aAzZkK",
        "̧́̃̈⃗ͅ",
        "        　",
        "\t\n\r",
        "​‌‍﻿",
        "úáéñ",
        "각가",
        "­",
    )
)
_FORBIDDEN = ("�", "\x00", "\x1f", "\x80", "\x9f")


def _has_content(text: str) -> bool:
    return any(not ch.isspace() for ch in text)


_TEXT = st.text(alphabet=_ALPHABET, max_size=40).filter(_has_content)
_PROFILE = st.sampled_from(GENERIC_NORMALIZATION_PROFILES)


def _inside_event(result: NormalizationResult, point: int) -> bool:
    return any(event.norm_start < point < event.norm_end for event in result.events)


@given(_TEXT, _PROFILE)
def test_profile_idempotent(raw: str, profile: NormalizationProfile) -> None:
    first = profile.normalize(raw)

    second = profile.normalize(first.normalized)

    assert second.normalized == first.normalized
    assert second.events == ()


@given(_TEXT, _PROFILE)
def test_offset_map_valid_and_monotone(raw: str, profile: NormalizationProfile) -> None:
    result = profile.normalize(raw)

    assert len(result.offsets.boundary) == len(result.normalized) + 1
    result.offsets.validate(len(raw), len(result.normalized))


@given(_TEXT, _PROFILE)
def test_result_is_nfc(raw: str, profile: NormalizationProfile) -> None:
    result = profile.normalize(raw)

    assert unicodedata.is_normalized("NFC", result.normalized)


@given(_TEXT, _PROFILE, st.data())
def test_span_roundtrip(raw: str, profile: NormalizationProfile, data: st.DataObject) -> None:
    result = profile.normalize(raw)
    normalized = result.normalized
    start = data.draw(st.integers(0, len(normalized)))
    end = data.draw(st.integers(start, len(normalized)))
    # Precondition: a boundary inside an event has no exact raw counterpart.
    assume(not _inside_event(result, start) and not _inside_event(result, end))
    raw_start, raw_end = result.offsets.raw_span(start, end)
    raw_slice = raw[raw_start:raw_end]
    # Precondition: a whitespace-only raw slice has no content to re-normalize.
    assume(_has_content(raw_slice))

    again = profile.normalize(raw_slice).normalized

    assert again.strip(" ") == normalized[start:end].strip(" ")


@given(_TEXT)
def test_raw_never_mutated(raw: str) -> None:
    snapshot = "".join(list(raw))

    result = DEFAULT_TEXT_PROFILE.normalize(raw)

    assert result.raw is raw
    assert raw == snapshot


@given(_TEXT, _PROFILE, st.sampled_from(_FORBIDDEN), st.data())
def test_forbidden_codepoints_always_fail(
    raw: str, profile: NormalizationProfile, bad: str, data: st.DataObject
) -> None:
    # U+FFFD fails as replacement_char; C0/C1 controls fail as control_char. The insertion point
    # does not matter because the NFC rule checks every code point before any other work.
    position = data.draw(st.integers(0, len(raw)))
    text = raw[:position] + bad + raw[position:]
    expected = "replacement_char" if bad == "�" else "control_char"

    with pytest.raises(NormalizationFailed) as excinfo:
        profile.normalize(text)

    assert excinfo.value.code == expected
