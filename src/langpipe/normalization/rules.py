"""Generic normalization rules: ``nfc`` and ``whitespace`` (M2 WP2.5).

Pure and deterministic. Rules never case-fold, strip diacritics, map punctuation or apply NFKC.
"""

import unicodedata
from typing import ClassVar

from langpipe.domain.errors import NormalizationFailed
from langpipe.normalization.base import NormalizationEvent, RuleOutput
from langpipe.text.offsets import OffsetMap

_REPLACEMENT_CHAR = "�"
_ALLOWED_CONTROLS = frozenset("\t\n\r")
_ZERO_WIDTH = frozenset("​‌‍﻿")


def _check_codepoints(text: str) -> None:
    for ch in text:
        if ch == _REPLACEMENT_CHAR:
            raise NormalizationFailed("replacement_char")
        code = ord(ch)
        if (code < 0x20 or 0x80 <= code <= 0x9F) and ch not in _ALLOWED_CONTROLS:
            raise NormalizationFailed("control_char")


def _chunks(text: str) -> list[str]:
    # The first starter (combining class 0) opens the first chunk, so leading combining marks join
    # it. Every later starter opens a new chunk. Text with no starter stays one chunk.
    first = next((i for i, ch in enumerate(text) if unicodedata.combining(ch) == 0), 0)
    starts = [i for i, ch in enumerate(text) if i > first and unicodedata.combining(ch) == 0]
    bounds = [0, *starts, len(text)]
    return [text[lo:hi] for lo, hi in zip(bounds, bounds[1:], strict=False)]


class NfcRule:
    name: ClassVar[str] = "nfc"

    def apply(self, text: str) -> RuleOutput:
        _check_codepoints(text)
        if unicodedata.is_normalized("NFC", text):
            return RuleOutput(text, OffsetMap.identity(len(text)), (), {})

        diagnostics: dict[str, int] = {}
        chunks = _chunks(text)
        if "".join(unicodedata.normalize("NFC", chunk) for chunk in chunks) != (
            unicodedata.normalize("NFC", text)
        ):
            # Chunk-wise composition is not equivalent here; normalize the whole segment instead.
            chunks = [text]
            diagnostics["nfc_whole_segment_fallback"] = 1

        parts: list[str] = []
        events: list[NormalizationEvent] = []
        boundary = [0]
        raw_pos = 0
        out_pos = 0
        for chunk in chunks:
            raw_start, raw_end = raw_pos, raw_pos + len(chunk)
            composed = unicodedata.normalize("NFC", chunk)
            if composed == chunk:
                boundary.extend(range(raw_start + 1, raw_end + 1))
            else:
                # Boundaries inside a changed chunk map to its raw start; its end maps to raw end.
                boundary.extend([raw_start] * (len(composed) - 1))
                boundary.append(raw_end)
                events.append(
                    NormalizationEvent("nfc", raw_start, raw_end, out_pos, out_pos + len(composed))
                )
            parts.append(composed)
            out_pos += len(composed)
            raw_pos = raw_end

        return RuleOutput("".join(parts), OffsetMap(tuple(boundary)), tuple(events), diagnostics)


class WhitespaceRule:
    name: ClassVar[str] = "whitespace"

    def apply(self, text: str) -> RuleOutput:
        out: list[str] = []
        boundary = [0]  # boundary[j] = input index of collapsed boundary j
        changed: list[tuple[int, int, int, int]] = []  # (raw_start, raw_end, out_start, out_end)
        diagnostics: dict[str, int] = {}
        index = 0
        while index < len(text):
            ch = text[index]
            if ch.isspace():
                end = index + 1
                while end < len(text) and text[end].isspace():
                    end += 1
                if text[index:end] != " ":
                    changed.append((index, end, len(out), len(out) + 1))
                out.append(" ")
                boundary.append(end)
                index = end
                continue
            if ch in _ZERO_WIDTH:
                key = f"zero_width:U+{ord(ch):04X}"
                diagnostics[key] = diagnostics.get(key, 0) + 1
            out.append(ch)
            boundary.append(index + 1)
            index += 1

        collapsed = "".join(out)
        core = collapsed.strip(" ")
        lead = len(collapsed) - len(collapsed.lstrip(" "))

        def project(position: int) -> int:
            return min(max(position - lead, 0), len(core))

        events = tuple(
            NormalizationEvent(
                "whitespace", raw_start, raw_end, project(out_start), project(out_end)
            )
            for raw_start, raw_end, out_start, out_end in changed
        )
        return RuleOutput(
            core,
            OffsetMap(tuple(boundary[lead : lead + len(core) + 1])),
            events,
            diagnostics,
        )
