"""plain_lines@0.1.0: one unit per non-blank line of plain text (M2 WP2.3). Pure."""

from dataclasses import dataclass
from typing import ClassVar

from langpipe.domain.errors import UnsupportedSource
from langpipe.extraction.base import (
    ExtractedUnit,
    ExtractionContext,
    ExtractionOutput,
    decode_utf8,
    split_lines,
)


def _resolve_language(ctx: ExtractionContext) -> str:
    if ctx.language is not None:
        return ctx.language
    if len(ctx.source_languages) == 1:
        return ctx.source_languages[0]
    raise UnsupportedSource("language_ambiguous")


@dataclass(frozen=True)
class PlainLinesExtractor:
    name: ClassVar[str] = "plain_lines"
    version: ClassVar[str] = "0.1.0"

    def extract(self, data: bytes, ctx: ExtractionContext) -> ExtractionOutput:
        language = _resolve_language(ctx)
        text, stats = decode_utf8(data, ctx.source_object_id)

        units: list[ExtractedUnit] = []
        blank_lines = 0
        for line_no, line in enumerate(split_lines(text), start=1):
            if not line.strip():
                blank_lines += 1
                continue
            units.append(
                ExtractedUnit(
                    ordinal=len(units),
                    language=language,
                    locator={"line": line_no},
                    raw_text=line,
                )
            )

        if blank_lines:
            stats["blank_lines"] = blank_lines
        return ExtractionOutput(units=tuple(units), stats=stats, empty_units=())
