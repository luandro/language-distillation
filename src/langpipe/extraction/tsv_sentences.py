"""tsv_sentences@0.1.0: opt-in TSV adapter with sentence splitting (M3 WP3.4, ADR-0011 §4).

Wraps the M2 ``tsv`` extractor and splits only the explicitly configured ``por`` column
at ``.!?`` followed by whitespace or end of cell. Maximal delimiter runs stay with their
sentence; inter-unit whitespace is excluded from units and retained in the source bytes.
Each split unit carries ``sentence_part`` plus half-open Unicode ``cell_start``/``cell_end``
offsets into the original cell, so ``raw_text`` is always a direct cell slice.

This is deliberately not a general Portuguese sentence recognizer and is never the default
extractor; it exists to exercise actual 1:2 golden membership. Other languages pass through
unchanged. The language rule lives here, in this named adapter, not in generic code.
"""

from dataclasses import dataclass
from typing import ClassVar

from langpipe.extraction.base import (
    ExtractedUnit,
    ExtractionContext,
    ExtractionOutput,
)
from langpipe.extraction.tsv import TsvExtractor

_SENTENCE_DELIMITERS = frozenset(".!?")
_SPLIT_LANGUAGE = "por"


def _sentence_parts(cell: str) -> list[tuple[int, int]]:
    """Half-open ``[start, end)`` slices of sentence parts within ``cell``.

    A maximal run of delimiters ends a part only when followed by whitespace or the end of
    the cell; the whitespace between parts belongs to no part.
    """
    parts: list[tuple[int, int]] = []
    start = 0
    index = 0
    length = len(cell)
    while index < length:
        if cell[index] not in _SENTENCE_DELIMITERS:
            index += 1
            continue
        end = index
        while end < length and cell[end] in _SENTENCE_DELIMITERS:
            end += 1
        if end < length and not cell[end].isspace():
            # Delimiter inside a token (e.g. ``3.14``): not a boundary.
            index = end
            continue
        parts.append((start, end))
        next_start = end
        while next_start < length and cell[next_start].isspace():
            next_start += 1
        if next_start >= length:
            return parts
        start = next_start
        index = next_start
    if start < length:
        parts.append((start, length))
    return parts


@dataclass(frozen=True)
class TsvSentencesExtractor:
    name: ClassVar[str] = "tsv_sentences"
    version: ClassVar[str] = "0.1.0"

    def extract(self, data: bytes, ctx: ExtractionContext) -> ExtractionOutput:
        base = TsvExtractor().extract(data, ctx)
        units: list[ExtractedUnit] = []
        for unit in base.units:
            if unit.language != _SPLIT_LANGUAGE:
                units.append(
                    ExtractedUnit(
                        ordinal=len(units),
                        language=unit.language,
                        locator=unit.locator,
                        raw_text=unit.raw_text,
                    )
                )
                continue
            cell = unit.raw_text
            for part, (cell_start, cell_end) in enumerate(_sentence_parts(cell)):
                locator = dict(unit.locator)
                locator["sentence_part"] = part
                locator["cell_start"] = cell_start
                locator["cell_end"] = cell_end
                units.append(
                    ExtractedUnit(
                        ordinal=len(units),
                        language=unit.language,
                        locator=locator,
                        raw_text=cell[cell_start:cell_end],
                    )
                )
        return ExtractionOutput(
            units=tuple(units),
            stats=base.stats,
            empty_units=base.empty_units,
        )
