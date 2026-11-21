"""Normalization interfaces and the shared rule-chain profile (M2 WP2.2).

Coordinates: a rule's ``RuleOutput.offsets`` maps its output text to its input text. The
chain composes these maps to raw text and re-projects every event to raw and final coordinates.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Protocol

from langpipe.domain.errors import NormalizationFailed
from langpipe.text.offsets import OffsetMap
from langpipe.text.registry import Versioned


@dataclass(frozen=True)
class NormalizationEvent:
    rule: str  # rule name, e.g. "nfc", "whitespace"
    raw_start: int
    raw_end: int
    norm_start: int
    norm_end: int


@dataclass(frozen=True)
class RuleOutput:
    text: str
    offsets: OffsetMap  # output text -> input text
    events: tuple[NormalizationEvent, ...]  # this rule's input/output coordinates
    diagnostics: Mapping[str, int]  # required, {} when none; chain sums matching counters


class NormalizationRule(Protocol):
    name: ClassVar[str]

    def apply(self, text: str) -> RuleOutput: ...

    # NormalizationFailed(code) if the input cannot be normalized


@dataclass(frozen=True)
class NormalizationResult:
    raw: str
    normalized: str
    offsets: OffsetMap  # normalized -> raw
    events: tuple[NormalizationEvent, ...]  # raw/final coordinates
    diagnostics: Mapping[str, int]  # report-only


class NormalizationProfile(Versioned, Protocol):
    rules: ClassVar[tuple[NormalizationRule, ...]]

    def normalize(self, raw: str) -> NormalizationResult: ...


def _project_span(offsets: OffsetMap, start: int, end: int) -> tuple[int, int]:
    """Project a span in a rule's input coordinates to its output coordinates.

    Audit envelopes, not exact attribution (M2 WP2.2 interval contract). A nonempty ``[start, end)``
    begins at the first output boundary of the greatest mapped input value <= start and ends at the
    last output boundary of the least mapped input value >= end; positions outside the mapped
    coverage clamp to output 0 or the output length. A zero-width span stays zero-width at the first
    output boundary >= start, clamped to the output length.
    """
    boundary = offsets.boundary
    last = len(boundary) - 1
    if start == end:
        point = min(bisect_left(boundary, start), last)
        return point, point
    below = bisect_right(boundary, start) - 1
    new_start = bisect_left(boundary, boundary[below]) if below >= 0 else 0
    above = bisect_left(boundary, end)
    new_end = bisect_right(boundary, boundary[above]) - 1 if above <= last else last
    return new_start, new_end


class RuleChainProfile:
    """Applies ``rules`` in order. Subclasses set ClassVar name, version and rules."""

    name: ClassVar[str]
    version: ClassVar[str]
    rules: ClassVar[tuple[NormalizationRule, ...]]

    def normalize(self, raw: str) -> NormalizationResult:
        text = raw
        raw_maps: list[OffsetMap] = []  # raw_maps[i] maps the text entering rule i to raw
        outputs: list[RuleOutput] = []
        totals: dict[str, int] = {}
        composed = OffsetMap.identity(len(raw))
        for rule in self.rules:
            out = rule.apply(text)
            out.offsets.validate(len(text), len(out.text))
            raw_maps.append(composed)
            outputs.append(out)
            composed = composed.compose(out.offsets)
            for key, count in out.diagnostics.items():
                totals[key] = totals.get(key, 0) + count
            text = out.text

        if not text:
            raise NormalizationFailed("empty_after_normalization")
        composed.validate(len(raw), len(text))

        events: list[NormalizationEvent] = []
        for index, out in enumerate(outputs):
            for event in out.events:
                raw_start, raw_end = raw_maps[index].raw_span(event.raw_start, event.raw_end)
                norm_start, norm_end = event.norm_start, event.norm_end
                for later in outputs[index + 1 :]:
                    norm_start, norm_end = _project_span(later.offsets, norm_start, norm_end)
                events.append(
                    NormalizationEvent(event.rule, raw_start, raw_end, norm_start, norm_end)
                )

        return NormalizationResult(
            raw=raw,
            normalized=text,
            offsets=composed,
            events=tuple(events),
            diagnostics=totals,
        )
