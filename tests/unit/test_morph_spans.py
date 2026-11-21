"""WP5.2 unit tests: segmentation signature and segment validation (M5-PLAN §6 WP5.2, ADR-0017 §4).

Contracts under test:
- `segmentation_signature` is a canonical sha256 over `[(start, end, is_zero, morpheme_id)]`:
  insensitive to construction order, sensitive to any span, zero-flag or morpheme change,
  and identical for model rows and their dict form;
- `check_segments` accepts exactly the ordered, non-overlapping, contiguous-ordinal
  segmentations that cover every non-boundary code point;
- property tests: random valid segmentations always pass, random corruptions always fail;
- `MorphologyProfile` is frozen profile data with the generic defaults, and the mzr
  profile carries its own (working-assumption) copy.
"""

from dataclasses import fields, is_dataclass
from datetime import UTC, datetime

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from langpipe.domain.enums import Abstention, AnalysisKind, SpanRepresentation
from langpipe.domain.models.morphology import MorphAnalysis, MorphSegment
from langpipe.languages.base import GENERIC_PROFILE, LanguageProfile, MorphologyProfile
from langpipe.languages.mzr.profile import MZR_PROFILE
from langpipe.morphology.spans import (
    check_analysis,
    check_segments,
    segmentation_signature,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
FIXTURE_SURFACE = "abab"
_ULID_CHARS = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _segment_row(
    ordinal: int,
    start: int,
    end: int,
    *,
    is_zero: bool = False,
    morpheme_id: str | None = None,
) -> dict[str, object]:
    return {
        "ordinal": ordinal,
        "start": start,
        "end": end,
        "is_zero": is_zero,
        "morpheme_id": morpheme_id,
    }


def _model_segment(
    ordinal: int,
    start: int,
    end: int,
    surface: str = FIXTURE_SURFACE,
    *,
    is_zero: bool = False,
    morpheme_id: str | None = None,
) -> MorphSegment:
    return MorphSegment(
        id=f"mseg_{'0' * 26}",
        analysis_id="ma_" + "0" * 26,
        ordinal=ordinal,
        start=start,
        end=end,
        is_zero=is_zero,
        surface="" if is_zero else surface[start:end],
        morpheme_id=morpheme_id,
        created_at=NOW,
    )


# ---------------------------------------------------------------- segmentation_signature


def test_signature_is_stable_and_prefixed_shape() -> None:
    rows = [_segment_row(0, 0, 4), _segment_row(1, 4, 6, morpheme_id="morph_" + "0" * 26)]

    first = segmentation_signature(AnalysisKind.SEGMENTED, rows)
    second = segmentation_signature(AnalysisKind.SEGMENTED, [dict(row) for row in rows])

    assert first == second
    assert len(first) == 64
    assert all(char in "0123456789abcdef" for char in first)


def test_signature_ignores_construction_order() -> None:
    rows = [
        _segment_row(0, 0, 2),
        _segment_row(1, 2, 3),
        _segment_row(2, 3, 6, morpheme_id="morph_" + "1" * 26),
    ]
    reversed_rows = list(reversed(rows))

    assert segmentation_signature(AnalysisKind.SEGMENTED, rows) == segmentation_signature(
        AnalysisKind.SEGMENTED, reversed_rows
    )


def test_signature_matches_for_models_and_dicts() -> None:
    models = [_model_segment(0, 0, 2), _model_segment(1, 2, 4, morpheme_id="morph_" + "2" * 26)]
    dicts = [
        _segment_row(segment.ordinal, segment.start, segment.end, morpheme_id=segment.morpheme_id)
        for segment in models
    ]

    assert segmentation_signature(AnalysisKind.SEGMENTED, models) == segmentation_signature(
        AnalysisKind.SEGMENTED, dicts
    )


def test_signature_sensitive_to_span_zero_and_morpheme_changes() -> None:
    base = [_segment_row(0, 0, 2), _segment_row(1, 2, 4)]

    narrower = [_segment_row(0, 0, 1), _segment_row(1, 2, 4)]
    shifted = [_segment_row(0, 0, 2), _segment_row(1, 2, 5)]
    zeroed = [_segment_row(0, 0, 2), _segment_row(1, 2, 2, is_zero=True)]
    with_morpheme = [_segment_row(0, 0, 2, morpheme_id="morph_" + "3" * 26), _segment_row(1, 2, 4)]

    base_signature = segmentation_signature(AnalysisKind.SEGMENTED, base)
    for corrupted in (narrower, shifted, zeroed, with_morpheme):
        assert segmentation_signature(AnalysisKind.SEGMENTED, corrupted) != base_signature


def test_signature_distinguishes_duplicate_zero_segments_by_position() -> None:
    # Two zero-width probes at different positions produce different signatures.
    at_one = [_segment_row(0, 1, 1, is_zero=True)]
    at_two = [_segment_row(0, 2, 2, is_zero=True)]

    assert segmentation_signature(AnalysisKind.SEGMENTED, at_one) != segmentation_signature(
        AnalysisKind.SEGMENTED, at_two
    )


@given(
    st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=8),
            st.integers(min_value=0, max_value=8),
        ),
        min_size=1,
        max_size=6,
        unique=True,
    ),
    st.data(),
)
def test_signature_is_order_insensitive_for_random_constructions(
    spans: list[tuple[int, int]], data: st.DataObject
) -> None:
    rows = []
    for ordinal, (start, end) in enumerate(spans):
        morpheme: str | None = None
        if data.draw(st.booleans()):
            morpheme = f"morph_{data.draw(st.text(alphabet=_ULID_CHARS, min_size=26, max_size=26))}"
        rows.append(_segment_row(ordinal, start, end, morpheme_id=morpheme))

    forward = segmentation_signature(AnalysisKind.SEGMENTED, rows)
    backward = segmentation_signature(AnalysisKind.SEGMENTED, list(reversed(rows)))

    assert forward == backward
    assert forward == segmentation_signature(AnalysisKind.SEGMENTED, [dict(row) for row in rows])


# ---------------------------------------------------------------- check_segments


def test_check_accepts_covering_segmentation_with_boundary_marks() -> None:
    surface = "mabi-ki=wesa"
    segments = [
        _model_segment(0, 0, 4, surface),
        _model_segment(1, 5, 7, surface),
        _model_segment(2, 8, 12, surface),
    ]

    check_segments(surface, segments, boundary_marks=("-", "="))


def test_check_requires_at_least_one_segment() -> None:
    with pytest.raises(ValueError, match="at least one"):
        check_segments("mabi", [], boundary_marks=("-", "="))


def test_check_requires_contiguous_ordinals_from_zero() -> None:
    segments = [_model_segment(1, 0, 4, "mabi")]
    with pytest.raises(ValueError, match="ordinal"):
        check_segments("mabi", segments, boundary_marks=("-", "="))

    gapped = [_model_segment(0, 0, 2), _model_segment(2, 2, 4)]
    with pytest.raises(ValueError, match="ordinal"):
        check_segments(FIXTURE_SURFACE, gapped, boundary_marks=("-", "="))


def test_check_requires_sorted_non_overlapping_spans() -> None:
    overlapping = [_model_segment(0, 0, 3), _model_segment(1, 2, 4)]
    with pytest.raises(ValueError, match="sorted"):
        check_segments(FIXTURE_SURFACE, overlapping, boundary_marks=("-", "="))

    reversed_order = [_model_segment(0, 2, 4), _model_segment(1, 0, 2)]
    with pytest.raises(ValueError, match="sorted"):
        check_segments(FIXTURE_SURFACE, reversed_order, boundary_marks=("-", "="))


def test_check_requires_spans_within_surface() -> None:
    with pytest.raises(ValueError, match="outside"):
        check_segments("ab", [_model_segment(0, 0, 3, "ab")], boundary_marks=("-", "="))
    with pytest.raises(ValueError, match="outside"):
        check_segments("ab", [_model_segment(0, 5, 6, "ab")], boundary_marks=("-", "="))


def test_check_surface_must_match_slice() -> None:
    wrong_surface = [_model_segment(0, 0, 2)]
    wrong_surface[0] = wrong_surface[0].model_copy(update={"surface": "xy"})
    with pytest.raises(ValueError, match="surface"):
        check_segments(FIXTURE_SURFACE, wrong_surface, boundary_marks=("-", "="))


def test_check_zero_width_rules() -> None:
    # A zero-width probe after a covering segment is accepted.
    covered = [_model_segment(0, 0, 2, "ab"), _model_segment(1, 2, 2, "ab", is_zero=True)]
    check_segments("ab", covered, boundary_marks=("-", "="))

    # The MorphSegment model already refuses an unflagged empty span at
    # construction (models keep the invariant); check_segments re-arms the rule,
    # reached here through a copy that skips validation.
    unflagged = _model_segment(0, 2, 2, "ab", is_zero=True).model_copy(update={"is_zero": False})
    with pytest.raises(ValueError, match="is_zero"):
        check_segments("ab", [unflagged], boundary_marks=("-", "="))

    zero_with_surface = _model_segment(0, 2, 2, "ab", is_zero=True).model_copy(
        update={"surface": "a"}
    )
    with pytest.raises(ValueError, match="zero"):
        check_segments("ab", [zero_with_surface], boundary_marks=("-", "="))


def test_check_uncovered_code_points_must_be_boundary_marks() -> None:
    # "x" is not a boundary mark: a segmentation leaving it uncovered must fail.
    segments = [_model_segment(0, 0, 1, "axb"), _model_segment(1, 2, 3, "axb")]
    with pytest.raises(ValueError, match="boundary"):
        check_segments("axb", segments, boundary_marks=("-", "="))

    # The same shape passes when every uncovered point is a declared mark.
    check_segments("axb", segments, boundary_marks=("x",))
    dashed = [_model_segment(0, 0, 1, "a-b"), _model_segment(1, 2, 3, "a-b")]
    check_segments("a-b", dashed, boundary_marks=("-",))


def test_check_uncovered_prefix_and_suffix() -> None:
    # Leading and trailing boundary marks may stay uncovered.
    check_segments("-ab=", [_model_segment(0, 1, 3, "-ab=")], boundary_marks=("-", "="))


def test_check_failure_messages_carry_no_surface_content() -> None:
    # Invariant 7 (no restricted text outside governed stores): surfaces come from
    # governed sources, so failure messages may carry ordinals, positions, offsets
    # and lengths only. Every failure branch runs with a sentinel surface and no
    # 2+ character substring of it may appear in the message.
    sentinel = "ZZSECRETZZ"
    marks = ("-", "=")
    fragments = [
        sentinel[start : start + length]
        for length in range(2, len(sentinel) + 1)
        for start in range(len(sentinel) - length + 1)
    ]

    wrong_surface = _model_segment(0, 0, len(sentinel), sentinel).model_copy(
        update={"surface": "-" + sentinel}
    )
    out_of_range = _model_segment(0, 0, len(sentinel), sentinel).model_copy(
        update={"end": len(sentinel) + 1}
    )
    zero_nonempty = _model_segment(0, 4, 4, sentinel, is_zero=True).model_copy(
        update={"surface": sentinel}
    )
    unflagged_empty = _model_segment(0, 4, 4, sentinel, is_zero=True).model_copy(
        update={"is_zero": False}
    )
    cases: list[tuple[str, str, list[MorphSegment]]] = [
        ("empty", sentinel, []),
        ("ordinal", sentinel, [_model_segment(1, 0, len(sentinel), sentinel)]),
        ("out_of_range", sentinel, [out_of_range]),
        (
            "overlap",
            sentinel,
            [_model_segment(0, 0, 6, sentinel), _model_segment(1, 4, 10, sentinel)],
        ),
        ("zero_span", sentinel, [_model_segment(0, 0, 4, sentinel, is_zero=True)]),
        ("zero_surface", sentinel, [zero_nonempty]),
        ("empty_span_unflagged", sentinel, [unflagged_empty]),
        ("surface_mismatch", sentinel, [wrong_surface]),
        ("uncovered", f"-{sentinel}-", [_model_segment(0, 0, 1, f"-{sentinel}-")]),
    ]

    for name, surface, segments in cases:
        with pytest.raises(ValueError) as excinfo:
            check_segments(surface, segments, boundary_marks=marks)
        message = str(excinfo.value)
        for fragment in fragments:
            assert fragment not in message, f"{name}: leaked {fragment!r} in {message!r}"


# ---------------------------------------------------------------- property tests


_ALPHABET = "abc"


def _coverings(surface: str) -> st.SearchStrategy[list[tuple[int, int]]]:
    max_cuts = max(0, len(surface) - 1)
    return st.lists(
        st.integers(min_value=1, max_value=max(1, len(surface) - 1)),
        max_size=max_cuts,
        unique=True,
    ).map(
        lambda cuts: [
            (start, end)
            for start, end in zip((0, *sorted(cuts)), (*sorted(cuts), len(surface)), strict=True)
            if start < end
        ]
    )


@given(data=st.data())
def test_random_valid_segmentations_always_pass(data: st.DataObject) -> None:
    surface = data.draw(st.text(alphabet=_ALPHABET, min_size=1, max_size=10))
    spans = data.draw(_coverings(surface))
    assert spans

    segments = [
        _model_segment(ordinal, start, end, surface) for ordinal, (start, end) in enumerate(spans)
    ]
    check_segments(surface, segments, boundary_marks=("-", "="))


@given(data=st.data())
def test_shuffled_valid_segmentation_fails_check(data: st.DataObject) -> None:
    surface = data.draw(st.text(alphabet=_ALPHABET, min_size=2, max_size=10))
    spans = data.draw(_coverings(surface))
    if len(spans) < 2:
        return

    # Rebuild in reversed span order with ordinals reassigned: ordinal contiguity
    # holds, so the failure must come from the sorted/non-overlapping rule.
    reversed_spans = list(reversed(spans))
    segments = [
        _model_segment(ordinal, start, end, surface)
        for ordinal, (start, end) in enumerate(reversed_spans)
    ]
    with pytest.raises(ValueError, match="sorted"):
        check_segments(surface, segments, boundary_marks=("-", "="))


@given(data=st.data())
def test_random_corruptions_always_fail_check(data: st.DataObject) -> None:
    # One drawn corruption applied to a drawn valid covering: check_segments must
    # reject every one of them (M5-PLAN WP5.2 "random corruptions always fail").
    surface = data.draw(st.text(alphabet=_ALPHABET, min_size=2, max_size=10))
    spans = data.draw(_coverings(surface))
    corruption = data.draw(
        st.sampled_from(
            ["ordinal", "overlap", "out_of_range", "surface", "drop", "empty"],
        )
    )
    target = data.draw(st.integers(min_value=0, max_value=len(spans) - 1))
    extra = data.draw(st.integers(min_value=1, max_value=3))

    segments = [
        _model_segment(ordinal, start, end, surface) for ordinal, (start, end) in enumerate(spans)
    ]

    if corruption == "ordinal":
        # Renumber one ordinal: contiguity from 0 breaks at its position.
        segments[target] = segments[target].model_copy(update={"ordinal": target + 1})
    elif corruption == "overlap":
        # Extend segment `target`'s end into its successor; needs a successor.
        assume(target + 1 < len(spans))
        next_start = spans[target + 1][0]
        segments[target] = segments[target].model_copy(update={"end": next_start + 1})
    elif corruption == "out_of_range":
        end = spans[target][1]
        segments[target] = segments[target].model_copy(update={"end": end + extra})
    elif corruption == "surface":
        start, end = spans[target]
        rotated = surface[start:end].translate(str.maketrans(_ALPHABET, "bca"))
        assert rotated != surface[start:end]
        segments[target] = segments[target].model_copy(update={"surface": rotated})
    elif corruption == "drop":
        # Removing a segment leaves its non-boundary code points uncovered (the
        # alphabet holds no boundary marks); renumber the tail so ordinal
        # contiguity alone is not what fails. Dropping a single-span covering
        # leaves the empty list, which must fail on its own rule.
        del segments[target]
        for ordinal, segment in enumerate(segments):
            segments[ordinal] = segment.model_copy(update={"ordinal": ordinal})
    else:  # empty
        segments = []

    with pytest.raises(ValueError):
        check_segments(surface, segments, boundary_marks=("-", "="))


@given(data=st.data())
def test_signature_sensitive_to_any_payload_change(data: st.DataObject) -> None:
    surface = data.draw(st.text(alphabet=_ALPHABET, min_size=2, max_size=10))
    spans = data.draw(_coverings(surface))
    target = data.draw(st.integers(min_value=0, max_value=len(spans) - 1))
    start, end = spans[target]

    rows = [_segment_row(ordinal, s, e) for ordinal, (s, e) in enumerate(spans)]
    base = segmentation_signature(AnalysisKind.SEGMENTED, rows)

    # Shrinking the chosen span changes the payload unless the span was already minimal.
    if end - start > 1:
        shrunk = [_segment_row(ordinal, s, e) for ordinal, (s, e) in enumerate(spans)]
        shrunk[target] = _segment_row(target, start, end - 1)
        assert segmentation_signature(AnalysisKind.SEGMENTED, shrunk) != base

    # Assigning a morpheme to the chosen span always changes the payload.
    with_morpheme = [_segment_row(ordinal, s, e) for ordinal, (s, e) in enumerate(spans)]
    with_morpheme[target] = _segment_row(target, start, end, morpheme_id="morph_" + "4" * 26)
    assert segmentation_signature(AnalysisKind.SEGMENTED, with_morpheme) != base


# ---------------------------------------------------------------- check_analysis


def _analysis_for(
    surface: str,
    segments: list[MorphSegment],
    *,
    kind: AnalysisKind = AnalysisKind.SEGMENTED,
    abstention: Abstention | None = None,
    signature: str | None = None,
) -> MorphAnalysis:
    return MorphAnalysis(
        id="ma_" + "0" * 26,
        target_token_id="tok_" + "0" * 26,
        analysis_kind=kind,
        method="igt_assertion@0.1.0",
        span_representation=SpanRepresentation.NORMALIZED,
        surface=surface,
        signature=signature if signature is not None else segmentation_signature(kind, segments),
        abstention=abstention,
        run_id="run_" + "0" * 26,
        created_at=NOW,
    )


def test_check_analysis_accepts_each_kind() -> None:
    segmented_segments = [_model_segment(0, 0, 2), _model_segment(1, 2, 4)]
    segmented = _analysis_for(FIXTURE_SURFACE, segmented_segments)
    check_analysis(segmented, segmented_segments, boundary_marks=("-", "="))

    unsegmented_segments = [_model_segment(0, 0, 4)]
    unsegmented = _analysis_for(
        FIXTURE_SURFACE,
        unsegmented_segments,
        kind=AnalysisKind.UNSEGMENTED,
        abstention=Abstention.INSUFFICIENT_EVIDENCE,
    )
    check_analysis(unsegmented, unsegmented_segments, boundary_marks=("-", "="))


def test_check_analysis_requires_segments_of_the_analysis() -> None:
    segments = [_model_segment(0, 0, 4)]
    foreign = segments[0].model_copy(update={"analysis_id": "ma_" + "1" * 26})
    analysis = _analysis_for(FIXTURE_SURFACE, segments)

    with pytest.raises(ValueError, match="belong"):
        check_analysis(analysis, [foreign], boundary_marks=("-", "="))


def test_check_analysis_signature_must_match_segments() -> None:
    segments = [_model_segment(0, 0, 4)]
    analysis = _analysis_for(FIXTURE_SURFACE, segments, signature="a" * 64)

    with pytest.raises(ValueError, match="signature"):
        check_analysis(analysis, segments, boundary_marks=("-", "="))


def test_check_analysis_unsegmented_rules() -> None:
    whole = [_model_segment(0, 0, 4)]

    # Exactly one segment.
    two_segments = whole + [_model_segment(1, 4, 4, is_zero=True)]
    two = _analysis_for(FIXTURE_SURFACE, two_segments, kind=AnalysisKind.UNSEGMENTED)
    with pytest.raises(ValueError, match="exactly one"):
        check_analysis(two, two_segments, boundary_marks=("-",))

    # Zero-width segment is not a whole-surface segment (the trailing "-" keeps
    # check_segments happy so the unsegmented rule itself is what fires).
    zero_surface = "-"
    zero = [_model_segment(0, 0, 0, zero_surface, is_zero=True)]
    zero_analysis = _analysis_for(zero_surface, zero, kind=AnalysisKind.UNSEGMENTED)
    with pytest.raises(ValueError, match="is_zero"):
        check_analysis(zero_analysis, zero, boundary_marks=("-",))

    # The single segment must span the whole surface (trailing marks may stay
    # uncovered, so the span rule is what fires).
    partial = [_model_segment(0, 0, 2, "ab--")]
    partial_analysis = _analysis_for("ab--", partial, kind=AnalysisKind.UNSEGMENTED)
    with pytest.raises(ValueError, match="whole"):
        check_analysis(partial_analysis, partial, boundary_marks=("-", "="))

    # No morpheme link on the unsegmented segment.
    linked = [_model_segment(0, 0, 4, morpheme_id="morph_" + "0" * 26)]
    linked_analysis = _analysis_for(FIXTURE_SURFACE, linked, kind=AnalysisKind.UNSEGMENTED)
    with pytest.raises(ValueError, match="morpheme"):
        check_analysis(linked_analysis, linked, boundary_marks=("-", "="))


def test_check_analysis_segmented_forbids_abstention() -> None:
    segments = [_model_segment(0, 0, 4)]
    analysis = _analysis_for(
        FIXTURE_SURFACE,
        segments,
        abstention=Abstention.CONFLICTING_EVIDENCE,
    )

    with pytest.raises(ValueError, match="abstention"):
        check_analysis(analysis, segments, boundary_marks=("-", "="))


def test_check_analysis_messages_carry_no_surface_content() -> None:
    # Same rule as check_segments: no governed surface text in error messages.
    sentinel = "ZZSECRETZZ"
    fragments = [
        sentinel[start : start + length]
        for length in range(2, len(sentinel) + 1)
        for start in range(len(sentinel) - length + 1)
    ]
    segments = [_model_segment(0, 0, len(sentinel), sentinel)]
    partial_surface = "ZZ--"
    partial_segments = [_model_segment(0, 0, 2, partial_surface)]
    cases: list[tuple[str, str, list[MorphSegment], MorphAnalysis]] = [
        (
            "unsegmented_partial",
            partial_surface,
            partial_segments,
            _analysis_for(partial_surface, partial_segments, kind=AnalysisKind.UNSEGMENTED),
        ),
        (
            "foreign_segment",
            sentinel,
            [segments[0].model_copy(update={"analysis_id": "ma_" + "1" * 26})],
            _analysis_for(sentinel, segments),
        ),
        (
            "signature",
            sentinel,
            segments,
            _analysis_for(sentinel, segments, signature="b" * 64),
        ),
    ]
    for name, _surface, case_segments, analysis in cases:
        with pytest.raises(ValueError) as excinfo:
            check_analysis(analysis, case_segments, boundary_marks=("-", "="))
        message = str(excinfo.value)
        for fragment in fragments:
            assert fragment not in message, f"{name}: leaked {fragment!r} in {message!r}"


# ---------------------------------------------------------------- MorphologyProfile


def test_morphology_profile_generic_defaults() -> None:
    profile = MorphologyProfile()

    assert profile.boundary_marks == ("-", "=")
    assert profile.clitic_marks == ("=",)
    assert profile.unknown_gloss_markers == ("***", "?", "??")
    assert profile.toolbox_markers == {
        "text": ("\\t", "\\tx"),
        "morphs": ("\\m", "\\mb"),
        "glosses": ("\\g", "\\ge"),
        "translation": ("\\f", "\\ft"),
    }
    assert profile.min_stem_length == 2
    assert profile.grammatical_label_pattern == r"^[A-Z0-9]+$"


def test_morphology_profile_is_frozen_dataclass() -> None:
    profile = MorphologyProfile()
    assert is_dataclass(profile)

    with pytest.raises(AttributeError):
        profile.boundary_marks = ("|",)  # type: ignore[misc]

    names = {entry.name for entry in fields(MorphologyProfile)}
    assert names == {
        "boundary_marks",
        "clitic_marks",
        "unknown_gloss_markers",
        "toolbox_markers",
        "min_stem_length",
        "grammatical_label_pattern",
    }


def test_language_profile_carries_default_morphology() -> None:
    assert GENERIC_PROFILE.morphology == MorphologyProfile()
    factory = LanguageProfile.__dataclass_fields__["morphology"].default_factory
    assert factory is not None and isinstance(factory(), MorphologyProfile)


def test_mzr_profile_declares_its_own_morphology_copy() -> None:
    # The mzr profile copies the generic values as an explicit working assumption
    # (docs/languages/mzr.md §Open items): it is a separate instance, not an alias.
    morphology = MZR_PROFILE.morphology
    assert morphology == MorphologyProfile()
    assert morphology is not GENERIC_PROFILE.morphology
