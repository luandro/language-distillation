"""Code-point offset maps between normalized and raw text (M1 D7: half-open spans)."""

import itertools
from dataclasses import dataclass

from langpipe.domain.errors import SchemaViolation


@dataclass(frozen=True)
class OffsetMap:
    """boundary[i] = raw code-point index of normalized boundary i; len == len(normalized)+1;
    0 <= boundary[i] <= len(raw); non-decreasing. Trimmed prefixes/suffixes need not be mapped.
    For identity only: boundary[0] == 0 and boundary[-1] == len(raw)."""

    boundary: tuple[int, ...]

    @classmethod
    def identity(cls, length: int) -> "OffsetMap":
        return cls(tuple(range(length + 1)))

    def raw_span(self, start: int, end: int) -> tuple[int, int]:
        return (self.boundary[start], self.boundary[end])

    def compose(self, inner: "OffsetMap") -> "OffsetMap":
        # self maps mid -> raw; inner maps new -> mid; the result maps new -> raw.
        limit = len(self.boundary)
        if any(b < 0 or b >= limit for b in inner.boundary):
            raise SchemaViolation()
        return OffsetMap(tuple(self.boundary[b] for b in inner.boundary))

    def validate(self, raw_len: int, norm_len: int) -> None:
        if len(self.boundary) != norm_len + 1:
            raise SchemaViolation()
        if any(b < 0 or b > raw_len for b in self.boundary):
            raise SchemaViolation()
        if any(prev > cur for prev, cur in itertools.pairwise(self.boundary)):
            raise SchemaViolation()
