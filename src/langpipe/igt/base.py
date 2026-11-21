"""IGT reader substrate (WP5.6, M5-PLAN §7.6): reader DTOs, the `IgtReader`
protocol, and the segmentation helpers shared by the Toolbox and Xigt readers.

Readers are pure: bytes in, `IgtDocument` out. A document preserves what the
source observably contains (verbatim tier lines, translations, per-record parse
status) and never interprets glosses (that is later morphology work, ADR-0017).
Per-record problems are recorded as `IgtParseStatus`/`diagnostics`, never raised;
only whole-document failures (decode, oversized or hardened-against XML) raise
`ExtractionFailed` with fixed codes and no source content.
"""

import re
from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import Field

from langpipe.domain.enums import IgtFormat, IgtParseStatus
from langpipe.domain.models.base import LANG_CODE, DomainModel
from langpipe.domain.models.igt import IgtTierLine, IgtWord
from langpipe.languages.base import MorphologyProfile
from langpipe.text.registry import Versioned

# `IgtMorph.boundary_before` is restricted by the domain model to ``-`` or ``=``
# (models/igt.py `_BOUNDARY_MARK`). Profiles may declare other working marks;
# such marks drive segmentation but are recorded as ``None`` rather than guessed.
RECORDABLE_BOUNDARY_MARKS = frozenset({"-", "="})

_COMMON_2_TO_3: dict[str, str] = {
    "pt": "por",
    "en": "eng",
    "es": "spa",
    "fr": "fra",
    "de": "deu",
    "it": "ita",
    "nl": "nld",
    "ru": "rus",
    "zh": "zho",
    "ja": "jpn",
}
_ISO_3_RE = re.compile(r"^[a-z]{3}$")


def normalize_lang_code(raw: str | None) -> str:
    """Normalize a language tag to ISO 639-3 (^[a-z]{3}$), defaulting to 'und'."""
    if not raw:
        return "und"
    tag = raw.strip().lower()
    primary = tag.split("-")[0].split("_")[0]
    if len(primary) == 2:
        mapped = _COMMON_2_TO_3.get(primary)
        if mapped:
            return mapped
    if _ISO_3_RE.match(primary):
        return primary
    return "und"


class IgtRecord(DomainModel):
    """One parsed IGT record: the verbatim tiers plus the parsed word layer.

    Mirrors `IGTObservation` (``models/igt.py:56``) without persistence fields;
    WP5.7 materializes observations from these records. Translation keys are the
    language prefix found on the line (normalized to ISO 639-3) or ``und`` when
    the source line does not name a language or names an unsupported tag.
    """

    record_ordinal: int
    record_ref: str | None = None
    format: IgtFormat
    locator: dict[str, Any] = Field(default_factory=dict)
    tiers: list[IgtTierLine] = Field(default_factory=list)
    words: list[IgtWord] = Field(default_factory=list)
    translations: dict[LANG_CODE, list[str]] = Field(default_factory=dict)
    parse_status: IgtParseStatus
    diagnostics: list[str] = Field(default_factory=list)


class IgtDocument(DomainModel):
    """A whole IGT file as read: header lines, records and counter stats.

    ``stats`` holds accounting counters only (``records``, per-status counts,
    ``unknown_marker:<marker>``, ...); never source content.
    """

    format: IgtFormat
    header: list[str] = Field(default_factory=list)
    records: list[IgtRecord] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)


class IgtReader(Versioned, Protocol):
    """A pure IGT reader: bytes to `IgtDocument` (WP5.6).

    ``ctx`` is anything carrying a ``source_object_id`` attribute (typically an
    `ExtractionContext`); it is used only for typed error addressing, never for
    content. ``profile`` supplies language-specific marker/morphology data; when
    None the generic `MorphologyProfile` is used.
    """

    def read(
        self,
        data: bytes,
        ctx: Any = None,
        profile: MorphologyProfile | None = None,
    ) -> IgtDocument: ...


def split_at_boundary_marks(text: str, marks: tuple[str, ...]) -> list[tuple[str, str | None]]:
    """Split ``text`` at its boundary marks, recording the mark before each piece.

    Returns ``(component, boundary_before)`` pairs in order. A mark before the
    first component is data too (a proclitic ``=ki``), so it is recorded;
    components without a preceding mark get ``boundary_before=None``. Marks that
    no `IgtMorph` can carry (the domain model fixes ``-`` and ``=``) still drive
    segmentation but are recorded as ``None``. Empty components (leading,
    trailing or doubled marks) are dropped: the verbatim text is still preserved
    in tiers and word text, so nothing is invented and nothing is lost.
    """
    components: list[tuple[str, str | None]] = []
    recordable: str | None = None
    current: list[str] = []
    for char in text:
        if char in marks:
            if current:
                components.append(("".join(current), recordable))
                current = []
            recordable = char if char in RECORDABLE_BOUNDARY_MARKS else None
        else:
            current.append(char)
    if current:
        components.append(("".join(current), recordable))
    return components


def locate_morphs(
    word_text: str,
    morph_texts: Sequence[str],
    marks: tuple[str, ...],
) -> list[str | None] | None:
    """Locate morph texts left-to-right inside the word surface.

    Returns the ``boundary_before`` values that reconnect the morph list to the
    verbatim word text (``None`` on the first morph, the single separating
    boundary mark before every later morph), or ``None`` when the morph list
    cannot be laid out contiguously against the word text (adjoining character
    runs that are not boundary marks, a morph that does not occur, ...).
    """
    boundaries: list[str | None] = []
    position = 0
    for text in morph_texts:
        index = word_text.find(text, position)
        if index < 0:
            return None
        separator = word_text[position:index]
        if separator:
            if len(separator) != 1 or separator not in marks:
                return None
            boundaries.append(separator if separator in RECORDABLE_BOUNDARY_MARKS else None)
        else:
            boundaries.append(None)
        position = index + len(text)
    return boundaries


def source_object_id(ctx: Any) -> str:
    """Address for typed extraction errors; identifiers only, never content."""
    value = getattr(ctx, "source_object_id", None)
    return value if isinstance(value, str) and value else "unknown"
