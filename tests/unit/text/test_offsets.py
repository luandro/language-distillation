from typing import ClassVar

import pytest
from hypothesis import given
from hypothesis import strategies as st

from langpipe.domain.errors import NormalizationFailed, SchemaViolation
from langpipe.normalization.base import (
    NormalizationEvent,
    NormalizationResult,
    NormalizationRule,
    RuleChainProfile,
    RuleOutput,
    _project_span,
)
from langpipe.text.offsets import OffsetMap


def test_offset_identity_and_validate() -> None:
    identity = OffsetMap.identity(5)

    assert identity.boundary == (0, 1, 2, 3, 4, 5)
    identity.validate(5, 5)
    assert identity.raw_span(1, 3) == (1, 3)
    with pytest.raises(SchemaViolation):
        identity.validate(5, 4)


@st.composite
def monotone_maps(draw: st.DrawFn, dom: int, cod: int) -> OffsetMap:
    # boundary has dom+1 entries; each entry is a position in a codomain of length cod.
    values = draw(st.lists(st.integers(0, cod), min_size=dom + 1, max_size=dom + 1))
    return OffsetMap(tuple(sorted(values)))


@st.composite
def three_maps(draw: st.DrawFn) -> tuple[OffsetMap, OffsetMap, OffsetMap]:
    l0 = draw(st.integers(0, 8))
    l1 = draw(st.integers(0, 8))
    l2 = draw(st.integers(0, 8))
    l3 = draw(st.integers(0, 8))
    h = draw(monotone_maps(l1, l0))  # mid1 -> raw
    g = draw(monotone_maps(l2, l1))  # mid2 -> mid1
    f = draw(monotone_maps(l3, l2))  # new -> mid2
    return h, g, f


@given(three_maps())
def test_offset_compose_associative(maps: tuple[OffsetMap, OffsetMap, OffsetMap]) -> None:
    h, g, f = maps

    assert h.compose(g).compose(f) == h.compose(g.compose(f))


def test_offset_validate_rejects_decreasing_or_wrong_length() -> None:
    with pytest.raises(SchemaViolation):
        OffsetMap((0, 2, 1)).validate(5, 2)
    with pytest.raises(SchemaViolation):
        OffsetMap((0, 1, 2)).validate(5, 3)
    with pytest.raises(SchemaViolation):
        OffsetMap((0, 6)).validate(5, 1)


def test_trimmed_edges_do_not_enter_token_raw_span() -> None:
    # "  kanu  " -> "kanu": the trimmed prefix and suffix are not mapped, so a token over
    # the whole normalized text has raw span [2, 6) and never includes the trimmed spaces.
    trimmed = OffsetMap((2, 3, 4, 5, 6))

    trimmed.validate(8, 4)
    assert trimmed.raw_span(0, 4) == (2, 6)


class _StripEdges:
    name: ClassVar[str] = "strip"
    version: ClassVar[str] = "0.0.1"

    def apply(self, text: str) -> RuleOutput:
        body = text.strip(" ")
        start = len(text) - len(text.lstrip(" "))
        end = start + len(body)
        events: list[NormalizationEvent] = []
        if start:
            events.append(NormalizationEvent("strip", 0, start, 0, 0))
        if end < len(text):
            events.append(NormalizationEvent("strip", end, len(text), len(body), len(body)))
        offsets = OffsetMap(tuple(range(start, end + 1)))
        return RuleOutput(body, offsets, tuple(events), {"stripped_edges": len(events)})


class _DropHyphen:
    name: ClassVar[str] = "drop_hyphen"
    version: ClassVar[str] = "0.0.1"

    def apply(self, text: str) -> RuleOutput:
        kept = [i for i, ch in enumerate(text) if ch != "-"]
        out = "".join(text[i] for i in kept)
        # boundary[j] is the input index of output character j; the last entry is the end.
        offsets = OffsetMap((*kept, len(text)))
        events: list[NormalizationEvent] = []
        for i, ch in enumerate(text):
            if ch == "-":
                at = sum(k < i for k in kept)
                events.append(NormalizationEvent("drop_hyphen", i, i + 1, at, at))
        return RuleOutput(out, offsets, tuple(events), {"dropped_hyphen": len(events)})


class _Chain(RuleChainProfile):
    name: ClassVar[str] = "chain_test"
    version: ClassVar[str] = "0.0.1"
    rules = (_StripEdges(), _DropHyphen())


def test_rule_chain_reprojects_events_and_offsets() -> None:
    result = _Chain().normalize("  ka-nu  ")

    assert result.normalized == "kanu"
    assert result.offsets.boundary == (2, 3, 5, 6, 7)
    # Events are listed rule by rule, in each rule's input order.
    assert result.events == (
        NormalizationEvent("strip", 0, 2, 0, 0),
        NormalizationEvent("strip", 7, 9, 4, 4),
        NormalizationEvent("drop_hyphen", 4, 5, 2, 2),
    )
    assert result.diagnostics == {"stripped_edges": 2, "dropped_hyphen": 1}


def test_rule_chain_empty_result_fails_before_map() -> None:
    with pytest.raises(NormalizationFailed) as excinfo:
        _Chain().normalize("   ")

    assert excinfo.value.code == "empty_after_normalization"


class _Substitute:
    """Test double: replaces each non-overlapping ``old`` with ``new``. Same-length replacements
    keep character-for-character offsets; other replacements map every new character to the
    segment start. Unchanged characters keep their own offsets."""

    def __init__(self, name: str, old: str, new: str) -> None:
        assert old
        self.name = name
        self.old = old
        self.new = new

    def apply(self, text: str) -> RuleOutput:
        out: list[str] = []
        boundary: list[int] = []
        events: list[NormalizationEvent] = []
        hits = 0
        i = 0
        while i < len(text):
            if text.startswith(self.old, i):
                hits += 1
                start = len(boundary)
                same_length = len(self.new) == len(self.old)
                for k, ch in enumerate(self.new):
                    out.append(ch)
                    boundary.append(i + k if same_length else i)
                events.append(
                    NormalizationEvent(self.name, i, i + len(self.old), start, len(boundary))
                )
                i += len(self.old)
            else:
                out.append(text[i])
                boundary.append(i)
                i += 1
        boundary.append(len(text))
        diagnostics = {self.name: hits} if hits else {}
        return RuleOutput("".join(out), OffsetMap(tuple(boundary)), tuple(events), diagnostics)


def _normalize(raw: str, *rules: NormalizationRule) -> NormalizationResult:
    profile = RuleChainProfile()
    profile.rules = rules
    return profile.normalize(raw)


@pytest.mark.parametrize(
    ("boundary", "span", "expected"),
    [
        ((0, 2), (1, 2), (0, 1)),  # contraction: the changed input character survives
        ((0, 0, 1), (0, 1), (0, 2)),  # expansion plateau
        ((0, 0, 0, 4), (1, 2), (0, 3)),  # whole-segment fallback
        ((2, 3, 4, 5, 6), (0, 2), (0, 0)),  # leading trim: wholly deleted
        ((2, 3, 4, 5, 6), (6, 8), (4, 4)),  # trailing trim: wholly deleted
        ((2, 3, 4, 5, 6), (2, 6), (0, 4)),  # kept body
        ((0, 0, 1), (0, 0), (0, 0)),  # zero-width event stays zero-width
    ],
)
def test_event_span_projection_examples(
    boundary: tuple[int, ...], span: tuple[int, int], expected: tuple[int, int]
) -> None:
    assert _project_span(OffsetMap(boundary), *span) == expected


def test_leading_and_trailing_deletion_keeps_body_offsets() -> None:
    raw = "  kanu "
    result = _normalize(raw, _StripEdges())

    assert result.raw == raw
    assert result.normalized == "kanu"
    assert result.offsets.boundary == (2, 3, 4, 5, 6)
    assert result.events == (
        NormalizationEvent("strip", 0, 2, 0, 0),
        NormalizationEvent("strip", 6, 7, 4, 4),
    )
    assert result.diagnostics == {"stripped_edges": 2}


def test_combining_contraction_keeps_full_raw_span() -> None:
    raw = "café!"  # "e" + combining acute contracts to one "é"
    result = _normalize(raw, _Substitute("compose", "é", "é"))

    assert result.raw == raw
    assert result.normalized == "café!"
    assert result.offsets.boundary == (0, 1, 2, 3, 5, 6)
    assert result.events == (NormalizationEvent("compose", 3, 5, 3, 4),)
    assert result.diagnostics == {"compose": 1}


def test_reordered_combining_marks_keep_character_offsets() -> None:
    raw = "bạ́c"
    result = _normalize(raw, _Substitute("reorder_marks", "̣́", "̣́"))

    assert result.raw == raw
    assert result.normalized == "bạ́c"
    assert result.offsets.boundary == (0, 1, 2, 3, 4, 5)
    assert result.events == (NormalizationEvent("reorder_marks", 2, 4, 2, 4),)
    assert result.diagnostics == {"reorder_marks": 1}


def test_expansion_then_deletion_projects_surviving_span() -> None:
    raw = "pxq"
    result = _normalize(raw, _Substitute("expand", "x", "ab"), _Substitute("drop_b", "b", ""))

    assert result.raw == raw
    assert result.normalized == "paq"
    assert result.offsets.boundary == (0, 1, 2, 3)
    # The expansion event keeps the surviving "a" and does not widen to the deleted "b".
    assert result.events == (
        NormalizationEvent("expand", 1, 2, 1, 2),
        NormalizationEvent("drop_b", 1, 2, 2, 2),
    )
    assert result.diagnostics == {"expand": 1, "drop_b": 1}


def test_whole_segment_fallback_projects_inner_event_to_full_output() -> None:
    raw = "abcd"
    result = _normalize(
        raw,
        _Substitute("mark", "b", "B"),
        _Substitute("coarse", "aBcd", "XYZ"),
    )

    assert result.raw == raw
    assert result.normalized == "XYZ"
    assert result.offsets.boundary == (0, 0, 0, 4)
    assert result.events == (
        NormalizationEvent("mark", 1, 2, 0, 3),
        NormalizationEvent("coarse", 0, 4, 0, 3),
    )
    assert result.diagnostics == {"mark": 1, "coarse": 1}


def test_three_rule_composition_projects_every_event() -> None:
    raw = "  xé-y  "
    result = _normalize(
        raw,
        _StripEdges(),
        _Substitute("compose", "é", "é"),
        _Substitute("drop_hyphen", "-", ""),
    )

    assert result.raw == raw
    assert result.normalized == "xéy"
    assert result.offsets.boundary == (2, 3, 6, 7)
    assert result.events == (
        NormalizationEvent("strip", 0, 2, 0, 0),
        NormalizationEvent("strip", 7, 9, 3, 3),
        NormalizationEvent("compose", 3, 5, 1, 2),
        NormalizationEvent("drop_hyphen", 5, 6, 2, 2),
    )
    assert result.diagnostics == {"stripped_edges": 2, "compose": 1, "drop_hyphen": 1}
