"""Standard Format (Toolbox / SFM) IGT reader, `toolbox_igt@0.1.0` (WP5.6).

Pure: bytes to `IgtDocument`. Records start at ``\\ref``; every line before the
first ``\\ref`` is document header. Every input line is preserved verbatim in
one record's `IgtTierLine` list (marker, 1-based line number, raw line). Tier
roles resolve through `MorphologyProfile.toolbox_markers`; unknown markers are
kept verbatim in tiers and counted ``unknown_marker:<marker>`` in stats.

Parsing rules (M5-PLAN §7.6):
- lines without a marker continue the previous tier; marked contents of one
  record tier concatenate in order, joined with one space (the raw tiers keep
  the source layout, so nothing is repaired or invented);
- words are a whitespace split of the text tier;
- morphs split at profile boundary marks, recording ``boundary_before``;
- the gloss tier aligns word-by-word and morph-by-morph; a count mismatch keeps
  the word (that word's morph glosses stay ``None``) and marks the record
  ``tier_mismatch``;
- a record without a text tier is ``missing_tier``.

Per-record problems never fail the document. No reader path raises with source
content: typed errors address documents by id, records by status.
"""

import re
from typing import ClassVar

from langpipe.domain.enums import IgtFormat, IgtParseStatus
from langpipe.domain.models.igt import IgtMorph, IgtTierLine, IgtWord
from langpipe.extraction.base import decode_utf8, split_lines
from langpipe.igt.base import (
    IgtDocument,
    IgtRecord,
    normalize_lang_code,
    source_object_id,
    split_at_boundary_marks,
)
from langpipe.languages.base import MorphologyProfile

_ROLES = ("text", "morphs", "glosses", "translation")

# Marker lines: ``\`` + one non-space run, then the tier content (may be empty:
# ``\tx`` alone on a line is a marked empty line). ``\\t`` and ``\\tx`` are both
# accepted by the generic profile (languages/base.py:48).
_MARKER_LINE = re.compile(r"^\\(\S+)(?:[ \t](.*))?$")

SAFE_TOOLBOX_MARKERS: frozenset[str] = frozenset(
    {
        "\\id",
        "\\ref",
        "\\h",
        "\\c",
        "\\v",
        "\\s",
        "\\p",
        "\\b",
        "\\dt",
        "\\co",
        "\\nt",
        "\\el",
        "\\so",
        "\\aud",
        "\\vid",
        "\\trk",
        "\\tx",
        "\\t",
        "\\mb",
        "\\m",
        "\\ge",
        "\\g",
        "\\ps",
        "\\ft",
        "\\f",
        "\\fe",
        "\\fn",
        "\\sn",
        "\\pn",
        "\\xv",
        "\\xe",
        "\\xn",
        "\\rf",
        "\\x",
    }
)

# A translation line may name its language with a prefix (Toolbox convention:
# ``\ft por: A canoa foi ao rio.``). Standard 2-3 letter code or BCP-47 tag.
_LANG_PREFIX = re.compile(r"^([a-zA-Z]{2,3}(?:-[a-zA-Z0-9]+)?)\s*:\s*(.*)$")


class ToolboxIgtReader:
    """Toolbox/SFM reader. See module docstring for the parse contract."""

    name: ClassVar[str] = "toolbox_igt"
    version: ClassVar[str] = "0.1.0"

    def read(
        self,
        data: bytes,
        ctx: object = None,
        profile: MorphologyProfile | None = None,
    ) -> IgtDocument:
        obj_id = source_object_id(ctx)
        profiled = profile if profile is not None else MorphologyProfile()
        text, decode_stats = decode_utf8(data, obj_id)  # raises decode_error
        lines = split_lines(text)

        header: list[str] = []
        records: list[IgtRecord] = []
        counters: dict[str, int] = {}
        builder = _Builder(profiled)
        open_record = False
        # Role of the last marked line; "unknown" for foreign markers (their
        # continuation lines are preserved as verbatim evidence only).
        last_role: str | None = None

        for number, line in enumerate(lines, start=1):
            match = _MARKER_LINE.match(line)
            if match is None:
                if not open_record:
                    header.append(line)
                elif last_role == "translation":
                    builder.add_tier("", number, line)
                    if line.strip():
                        builder.add_translation_continuation(line.strip())
                elif last_role in _ROLES:
                    builder.add_tier("", number, line)
                    if line.strip():
                        builder.parts[last_role].append(line.strip())
                else:
                    builder.add_tier("", number, line)
                    if last_role == "unknown":
                        builder.bump("unknown_continuation")
                    else:
                        builder.bump("orphan_continuation")
                continue

            marker = f"\\{match[1]}"
            content = (match[2] or "").strip()
            if not open_record:
                if marker == "\\ref":
                    builder = _Builder(profiled, record_ref=content or None)
                    builder.add_tier("\\ref", number, line)
                    open_record = True
                    last_role = None
                else:
                    header.append(line)
                continue

            if marker == "\\ref":
                builder.finish(records)
                for k, v in builder.counters.items():
                    counters[k] = counters.get(k, 0) + v
                builder = _Builder(profiled, record_ref=content or None)
                builder.add_tier("\\ref", number, line)
                last_role = None
                continue

            builder.add_tier(marker, number, line)
            role = _resolve_role(marker, profiled)
            if role is None:
                if marker in SAFE_TOOLBOX_MARKERS:
                    builder.bump(f"unknown_marker:{marker}")
                else:
                    builder.bump("unknown_marker:UNKNOWN")
                last_role = "unknown"
                continue
            if role == "translation":
                builder.add_translation(content)
            else:
                builder.parts[role].append(content)
            last_role = role
        if open_record:
            builder.finish(records)
            for k, v in builder.counters.items():
                counters[k] = counters.get(k, 0) + v

        stats: dict[str, int] = dict(decode_stats)
        stats["header_lines"] = len(header)
        words = sum(len(record.words) for record in records)
        morphs = sum(len(word.morphs) for record in records for word in record.words)
        stats.update({"records": len(records), "words": words, "morphs": morphs})
        for status in IgtParseStatus:
            stats[status.value] = sum(1 for r in records if r.parse_status == status)
        stats.update(counters)
        return IgtDocument(format=IgtFormat.TOOLBOX, header=header, records=records, stats=stats)


def _resolve_role(marker: str, profile: MorphologyProfile) -> str | None:
    for role, markers in profile.toolbox_markers.items():
        if marker in markers:
            return role
    return None


class _Builder:
    """Accumulates one record's verbatim tiers and marked tier contents."""

    def __init__(self, profile: MorphologyProfile, record_ref: str | None = None) -> None:
        self.profile = profile
        self.record_ref = record_ref
        self.tiers: list[IgtTierLine] = []
        self.parts: dict[str, list[str]] = {role: [] for role in _ROLES}
        self.translations_raw: list[list[str]] = []
        self.counters: dict[str, int] = {}

    def bump(self, key: str) -> None:
        self.counters[key] = self.counters.get(key, 0) + 1

    def add_tier(self, marker: str, number: int, raw: str) -> None:
        self.tiers.append(IgtTierLine(marker=marker, line_number=number, raw=raw))

    def add_translation(self, text: str) -> None:
        self.translations_raw.append([text])

    def add_translation_continuation(self, text: str) -> None:
        if self.translations_raw:
            self.translations_raw[-1].append(text)
        else:
            self.translations_raw.append([text])

    def finish(self, records: list[IgtRecord]) -> None:
        words, status, diagnostics = _align(self.profile, self.parts)
        records.append(
            IgtRecord(
                record_ordinal=len(records),
                record_ref=self.record_ref,
                format=IgtFormat.TOOLBOX,
                locator={
                    "line_start": self.tiers[0].line_number,
                    "line_end": self.tiers[-1].line_number,
                    "ref": self.record_ref,
                },
                tiers=self.tiers,
                words=words,
                translations=self._translations(),
                parse_status=status,
                diagnostics=diagnostics,
            )
        )

    def _translations(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for item in self.translations_raw:
            full = " ".join(piece for piece in item if piece).strip()
            if not full:
                continue
            match = _LANG_PREFIX.match(full)
            if match is not None:
                tag = match[1]
                # Language codes are lowercase or uppercase tags (never titlecase words like "Ora:")
                if tag.islower() or tag.isupper():
                    norm = normalize_lang_code(tag)
                    if norm != "und":
                        out.setdefault(norm, []).append(match[2].strip())
                        continue
            out.setdefault("und", []).append(full)
        return out


def _align(
    profile: MorphologyProfile,
    parts: dict[str, list[str]],
) -> tuple[list[IgtWord], IgtParseStatus, list[str]]:
    """Build the parsed word layer and the record's status/diagnostics.

    Never raises on tier shape problems: misalignment is reported through the
    returned status. Splitting and gloss assignment stay on the source data;
    nothing is guessed or repaired.
    """
    diagnostics: list[str] = []
    status = IgtParseStatus.OK

    def mismatch() -> None:
        nonlocal status
        status = IgtParseStatus.TIER_MISMATCH
        if "tier_mismatch" not in diagnostics:
            diagnostics.append("tier_mismatch")

    text_words = " ".join(parts["text"]).split() if parts["text"] else []
    morph_words = " ".join(parts["morphs"]).split() if parts["morphs"] else None
    gloss_words = " ".join(parts["glosses"]).split() if parts["glosses"] else None
    if not text_words:
        return [], IgtParseStatus.MISSING_TIER, ["missing_tier"]

    morph_ok = morph_words is not None and len(morph_words) == len(text_words)
    if morph_words is not None and not morph_ok:
        mismatch()  # morph words do not map onto text words one-to-one
    gloss_ok = gloss_words is not None and len(gloss_words) == len(text_words)
    if gloss_words is not None and not gloss_ok:
        mismatch()  # gloss words do not map onto text words one-to-one

    words: list[IgtWord] = []
    for index, word_text in enumerate(text_words):
        if morph_words is not None and len(morph_words) == len(text_words):
            pieces = split_at_boundary_marks(morph_words[index], profile.boundary_marks)
        else:
            pieces = split_at_boundary_marks(word_text, profile.boundary_marks)
        glosses: list[str | None] = [None] * len(pieces)
        if gloss_words is not None and len(gloss_words) == len(text_words):
            gloss_pieces = split_at_boundary_marks(gloss_words[index], profile.boundary_marks)
            if len(gloss_pieces) == len(pieces):
                glosses = [piece[0] for piece in gloss_pieces]
            else:
                mismatch()  # this word is kept; its morph glosses stay None
        morphs = [
            IgtMorph(
                ordinal=ordinal,
                text=piece[0],
                boundary_before=piece[1],
                gloss=glosses[ordinal],
            )
            for ordinal, piece in enumerate(pieces)
        ]
        words.append(IgtWord(ordinal=index, text=word_text, morphs=morphs))
    return words, status, diagnostics
