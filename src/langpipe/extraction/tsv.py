"""tsv@0.1.0: tab-separated parallel and wordlist extractor (M2 WP2.3). Pure."""

import re
from dataclasses import dataclass
from typing import ClassVar

from langpipe.domain.errors import ExtractionFailed
from langpipe.extraction.base import (
    ExtractedUnit,
    ExtractionContext,
    ExtractionOutput,
    decode_utf8,
    split_lines,
)

_LANGUAGE_CODE = re.compile(r"[a-z]{3}")


@dataclass(frozen=True)
class TsvExtractor:
    name: ClassVar[str] = "tsv"
    version: ClassVar[str] = "0.1.0"

    def extract(self, data: bytes, ctx: ExtractionContext) -> ExtractionOutput:
        text, stats = decode_utf8(data, ctx.source_object_id)
        lines = split_lines(text)
        trailing = 0
        while lines and lines[-1] == "":
            lines.pop()
            trailing += 1
        if trailing:
            stats["trailing_empty_lines"] = trailing
        if not lines:
            raise ExtractionFailed("tsv_header_invalid", ctx.source_object_id, None)

        header = [column.strip(" ") for column in lines[0].split("\t")]
        languages = set(ctx.source_languages)
        language_columns: dict[int, str] = {}
        metadata_columns: list[int] = []
        ref_column: int | None = None
        for index, name in enumerate(header):
            if name in languages:
                language_columns[index] = name
            elif index == 0:
                ref_column = 0
            elif _LANGUAGE_CODE.fullmatch(name):
                raise ExtractionFailed("tsv_language_column_unknown", ctx.source_object_id, 1)
            else:
                metadata_columns.append(index)
        if not language_columns:
            raise ExtractionFailed("tsv_header_invalid", ctx.source_object_id, 1)

        units: list[ExtractedUnit] = []
        empty_units: list[dict[str, str | int]] = []
        metadata_cells = 0
        for line_no, line in enumerate(lines[1:], start=2):
            cells = line.split("\t")
            if len(cells) != len(header):
                raise ExtractionFailed("tsv_ragged_row", ctx.source_object_id, line_no)
            metadata_cells += len(metadata_columns)
            ref = cells[ref_column] if ref_column is not None else None
            for index, language in language_columns.items():
                cell = cells[index]
                if cell == "":
                    empty_units.append({"row": line_no, "column": language})
                    continue
                locator: dict[str, str | int] = {"row": line_no, "column": language}
                if ref is not None:
                    locator["ref"] = ref
                units.append(
                    ExtractedUnit(
                        ordinal=len(units),
                        language=language,
                        locator=locator,
                        raw_text=cell,
                    )
                )

        if metadata_cells:
            stats["metadata_cells"] = metadata_cells
        return ExtractionOutput(
            units=tuple(units),
            stats=stats,
            empty_units=tuple(empty_units),
        )
