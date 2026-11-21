"""Extractor interface. Extractors are pure: bytes in, units out (M2 E4)."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from langpipe.domain.enums import SourceType
from langpipe.domain.errors import ExtractionFailed
from langpipe.text.registry import Versioned

_UTF8_BOM = b"\xef\xbb\xbf"
_LINE_TERMINATOR = re.compile(r"\r\n|\r|\n")


@dataclass(frozen=True)
class ExtractionContext:
    source_id: str
    source_object_id: str
    source_type: SourceType
    media_type: str
    source_languages: tuple[str, ...]
    language: str | None  # explicit --language override


@dataclass(frozen=True)
class ExtractedUnit:
    ordinal: int
    language: str
    locator: Mapping[str, str | int]
    raw_text: str  # non-empty


@dataclass(frozen=True)
class ExtractionOutput:
    units: tuple[ExtractedUnit, ...]  # ordinals 0..n-1 contiguous, document order
    stats: Mapping[str, int]  # counters only; snake_case or unknown_marker:<marker>
    empty_units: tuple[Mapping[str, str | int], ...]  # structurally present but empty


class Extractor(Versioned, Protocol):
    def extract(self, data: bytes, ctx: ExtractionContext) -> ExtractionOutput: ...

    # ExtractionFailed on malformed input


def decode_utf8(data: bytes, source_object_id: str) -> tuple[str, dict[str, int]]:
    """Strict UTF-8 decode. Removes and counts a leading BOM; counts non-LF terminators."""
    stats: dict[str, int] = {}
    if data.startswith(_UTF8_BOM):
        data = data[len(_UTF8_BOM) :]
        stats["bom_removed"] = 1
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        # `from None`: the decoder message quotes the offending byte; never surface content.
        raise ExtractionFailed("decode_error", source_object_id, None) from None
    crlf = sum(1 for m in _LINE_TERMINATOR.finditer(text) if m.group() != "\n")
    if crlf:
        stats["crlf_lines"] = crlf
    return text, stats


def split_lines(text: str) -> list[str]:
    """Split on \\r\\n, \\r or \\n. A final terminator does not create a trailing empty line."""
    lines = _LINE_TERMINATOR.split(text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines
