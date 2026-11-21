"""WP2.15: ScriptureEarth Marúbo real-data integration test (opt-in ``realdata``).

Nothing here downloads, and no corpus bytes are committed, logged or written into reports. Every
real-data test is marked ``realdata`` and deselected by default (see ``pyproject.toml``); when
selected explicitly a missing package or manifest is a **failure, not a skip**
(M2 E9). The committed expectations file holds numbers and marker names only, and the count tests
fail until a senior fills and signs ``reviewed_by`` (a forcing function).

The pre-work check, ``_assert_authorized``, is manifest-only (ADR-0025): the manifest must
record where the package came from, every required local pipeline operation must resolve
allow, and every outward operation must resolve deny. It runs before any package scan,
registration, ingestion or extraction. Licences, authorities, rights holders, and permission
notes are records and are not checked.

Timing objects are preserved and hash-checked but never parsed as USFM: book/verse processing
selects objects by their declared USFM media type and rejects duplicate book codes instead of
silently overwriting them. Per-book verse counts are projected over the complete book set so
zero-verse books (XXF) stay visible. The leak checker reads setup-phase and call-phase captured
records plus report artifacts; the corpus fixture is function scoped, so each leak check covers
the pipeline run performed in its own test's setup. Data-bearing comparisons (verse pieces,
notes, unknown blocks, counts, sampled texts, token surfaces, inventory outliers) fail with
IDs/locators/hashes/counts
or U+XXXX labels only — never with verse, note or log content — and pytest's own rendering of
rewritten-assert operands is avoided for anything data-bearing. As a second layer,
``tests/integration/conftest.py`` sanitizes the reports of ``realdata`` items: captured
stdout/stderr/log sections are redacted (records stay inspectable in-test), and every failure
longrepr — including unexpected exceptions in setup, call or teardown, chained exceptions,
rewritten-assert operands and unmarked ``pytest.fail`` messages — is reduced to the exception
type plus safe test identity/location. Fixed diagnostics survive only through the explicit
safe-diagnostic marker added by ``_safe_fail``; the marker is a deliberate per-message decision,
never a default. Default-suite diagnostics are untouched. Synthetic subprocess regressions pin
that the complete stdout/stderr and the serialized reports (JUnit) of a failed test carry no
content. The observed-inventory report is count-only (``status: unverified``) and goes to a
temporary directory or a gitignored, untracked local destination — tracked or nonignored
repository destinations are rejected before anything is written.

The conservation check re-derives verse text with an independent, test-only USFM rescan
(``VerseRescan``) rather than the production scanner; its synthetic tests pin it against the
production extractor on repeated verse text, two midverse notes, a continued paragraph, an
XXF-like verse-free book and a book mixing skipped metadata, inline unknown markers and unknown
blocks.
"""

import hashlib
import itertools
import json
import logging
import os
import re
import subprocess
import sys
import textwrap
import time
import unicodedata
import xml.etree.ElementTree as ElementTree
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn
from urllib.parse import unquote, urlsplit

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AccessClass,
    EntityType,
    LineageKind,
    Operation,
    PolicyDecision,
    PolicyMode,
    RunStatus,
    SegmentStatus,
    SourceType,
)
from langpipe.domain.errors import UnsupportedSource
from langpipe.domain.ids import new_id
from langpipe.domain.models.source import PolicySpec, Provenance, SourceManifest, SourceObject
from langpipe.extraction.base import ExtractionContext, ExtractionOutput
from langpipe.extraction.service import ExtractionResult, extract_source
from langpipe.extraction.usfm import UsfmExtractor
from langpipe.governance.lineage_policy import effective_decision
from langpipe.governance.policy import resolve
from langpipe.ingestion.adapters.scriptureearth import (
    SE_MEDIA_TIMING,
    SE_MEDIA_USFM,
    ScriptureEarthPackage,
    build_manifest,
    scan_package,
    write_manifest,
)
from langpipe.ingestion.ingest import IngestResult, ingest_source
from langpipe.ingestion.registration import RegistrationResult, load_manifest, register_source
from langpipe.normalization.service import NormalizationResultSummary, normalize_extraction
from langpipe.storage.memory import InMemoryRepository
from langpipe.storage.objects.local import LocalContentStore
from langpipe.tokenization.service import TokenizationSummary, tokenize_normalization
from tests.integration.conftest import SAFE_DIAGNOSTIC_PREFIX

DIR_ENV = "LANGPIPE_MZR_SE_DIR"
MANIFEST_ENV = "LANGPIPE_MZR_SE_MANIFEST"
REPORT_ENV = "LANGPIPE_MZR_SE_REPORT_DIR"
EXPECTED_PATH = Path(__file__).with_name("expected") / "scriptureearth_mzr_counts.json"

REALDATA = pytest.mark.realdata
INTEGRATION = pytest.mark.integration

_VERSE_LABEL = re.compile(r"[0-9]+[a-z]?(?:-[0-9]+[a-z]?)?")
_BOOK = re.compile(r"[A-Z0-9]{3}")
_ID_CODE = re.compile(rb"\\id\s+([A-Za-z0-9]{3})")
_MARKER_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]*")
# Placeholder guard (senior decision on Q2): reject standalone placeholder values, placeholder
# words at word boundaries and explicit template fields — never arbitrary occurrences of letter
# sequences like "required"/"todo" inside otherwise valid prose or names, and never stray
# angle brackets around prose.
_PLACEHOLDER_VALUES = frozenset(
    {"placeholder", "todo", "tbd", "changeme", "test", "unknown", "fill in"}
)
_PLACEHOLDER_WORDS = re.compile(r"\b(?:placeholder|todo|tbd|changeme)\b", re.IGNORECASE)
_TEMPLATE_FIELD = re.compile(
    r"<\s*(?:fill[ _-]*in(?:[ _-]+here)?|name|value|date|operator|authority|"
    r"rights[ _-]*holder|notes?|here)\s*>"
    r"|\{\{[^{}]{0,50}\}\}",
    re.IGNORECASE,
)
_INVENTORY_REPORT_NAME = "mzr_observed_inventory.json"
_JOINERS = frozenset({"-", "‐", "'", "’"})
_OUTWARD_DENIED = (
    Operation.THIRD_PARTY_API,
    Operation.CLOUD_PROCESSING,
    Operation.REDISTRIBUTE_RAW,
    Operation.REDISTRIBUTE_DERIVED,
)
# Local operations this work package's pipeline needs; they must effectively resolve allow under
# the reviewed policy (Q4: no broad allow list for future align/distill/audio operations).
_LOCAL_REQUIRED = (
    Operation.INGEST,
    Operation.READ_RAW,
    Operation.EXTRACT,
    Operation.NORMALIZE,
)


def _safe_fail(message: str, *, pytrace: bool = False) -> NoReturn:
    """``pytest.fail`` whose fixed diagnostic survives realdata report sanitization.

    The conftest reducer preserves a failing realdata longrepr verbatim only when the message
    begins with ``SAFE_DIAGNOSTIC_PREFIX`` — an explicit, per-message opt-in. Every message
    routed here must already be content-free (IDs, counts, locators, `U+XXXX` labels, fixed
    prose). ``pytrace`` must stay False: a traceback would render source lines, which are not
    part of any reviewed diagnostic.
    """
    if pytrace:
        raise AssertionError("safe diagnostics are content-free; pytrace must be False")
    pytest.fail(SAFE_DIAGNOSTIC_PREFIX + message, pytrace=False)


def _is_placeholder(value: str | None) -> bool:
    """True for blank values, standalone placeholder values, placeholder words at word
    boundaries, or explicit template fields; false for legitimate prose and names."""
    if value is None:
        return True
    stripped = value.strip()
    if not stripped or stripped.lower() in _PLACEHOLDER_VALUES:
        return True
    if _PLACEHOLDER_WORDS.search(stripped):
        return True
    return bool(_TEMPLATE_FIELD.search(stripped))


# ---------------------------------------------------------------------------------------------
# Independent USFM rescan oracle (test-only; does not import production scanner helpers)
# ---------------------------------------------------------------------------------------------

_ORACLE_TOKEN = re.compile(
    r"\\(?P<plus>\+?)(?P<name>[A-Za-z]+)(?P<digits>[0-9]*)(?P<star>\*?)"
    r"|(?P<nl>\r\n|\r|\n)"
    r"|(?P<text>[^\\\r\n]+)"
    r"|(?P<slash>\\)"
)
_O_PARA = frozenset(
    {
        "p",
        "m",
        "pi",
        "q",
        "qm",
        "qc",
        "qr",
        "li",
        "pc",
        "pm",
        "mi",
        "nb",
        "cls",
        "pmo",
        "pmc",
        "pmr",
    }  # fmt: skip
)
_O_HEADING = frozenset({"s", "ms", "mr", "sr", "r", "sp", "d", "mt", "mte", "cl"})
_O_INTRO = frozenset({"ip", "is", "imt", "io", "ipr", "iq", "im", "imq"})
_O_METADATA = frozenset({"h", "toc", "toca", "ide", "rem", "sts", "usfm", "periph"})
_O_CHAR = frozenset(
    {
        "add",
        "nd",
        "wj",
        "bk",
        "qt",
        "k",
        "tl",
        "sc",
        "it",
        "bd",
        "bdit",
        "em",
        "no",
        "sup",
        "pn",
        "png",
        "qs",
        "qac",
        "w",
        "jmp",
    }  # fmt: skip
)
_O_NOTE_INNER = frozenset({"fq", "fqa", "ft", "fk", "fl", "fw", "fp", "fv", "fdc", "fr"})
_O_NOTE_OPEN = frozenset({"f", "fe"})
_O_SKIP_CLOSED = frozenset({"fig", "rq", "ca", "va"})
_O_BLANK = frozenset({"b", "ib"})
_O_STRUCTURAL = _O_PARA | _O_HEADING | _O_INTRO | frozenset({"v", "c", "id", "x", "f", "fe"})
_O_KNOWN = (
    _O_PARA
    | _O_HEADING
    | _O_INTRO
    | _O_METADATA
    | _O_CHAR
    | _O_NOTE_INNER
    | _O_NOTE_OPEN
    | _O_BLANK
    | _O_SKIP_CLOSED
    | frozenset({"v", "c", "id", "x", "cp", "vp"})
)
_O_VALUE = re.compile(r"[^\s\\]+")
_O_CALLER = re.compile(r"[^ \t]+")


@dataclass
class _OracleNote:
    discard: bool
    chapter: int
    verse: str
    resume_verse: bool
    caller: str = ""
    caller_pending: bool = True
    capturing_ref: bool = False
    buf: list[str] = field(default_factory=list)
    ref_buf: list[str] = field(default_factory=list)


@dataclass
class _OracleUnknown:
    chapter: int
    marker: str
    buf: list[str] = field(default_factory=list)


class VerseRescan:
    """Test-only, line-independent USFM rescan that re-derives verse pieces.

    A deliberately separate implementation: it mirrors the documented decoding rules (newline
    folding, ``~`` and ``//`` handling, note and attribute removal, edge stripping, paragraph and
    note piece splitting) without importing any production extractor code. It also counts the
    documented accounting counters (``metadata_markers``, ``unknown_marker:*``) so skipped
    metadata and unknown markers are accounted for by counts only.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.line_start = True
        self.book = ""
        self.chapter = 0
        self.last_marker = ""
        self.verse_label: str | None = None
        self.part = 0
        self.verse_had_text = False
        self.in_verse = False
        self.block_open = False
        self.buf: list[str] = []
        self.note: _OracleNote | None = None
        self.unknown: _OracleUnknown | None = None
        self.in_skip = False
        self.skip_closer: str | None = None
        self.char_stack: list[str] = []
        self.drop_for: str | None = None
        self.pieces: dict[tuple[str, int, str, int], str] = {}
        self.empty: list[tuple[str, int, str]] = []
        self.notes: list[tuple[str, int, str, str]] = []
        self.unknown_blocks: list[tuple[str, int, str, str]] = []
        self.stats: Counter[str] = Counter()

    # -- driver -------------------------------------------------------------------------------

    def run(self) -> "VerseRescan":
        while self.pos < len(self.text):
            match = _ORACLE_TOKEN.match(self.text, self.pos)
            assert match is not None
            self.pos = match.end()
            if match.group("name") is not None:
                self._marker(match)
            elif match.group("nl") is not None:
                self._newline()
            else:
                self._text(match.group(0))
        self._close_note()
        self._end_skip()
        self._close_unknown()
        self._end_verse()
        return self

    # -- tokens -------------------------------------------------------------------------------

    def _marker(self, match: re.Match[str]) -> None:
        plus = bool(match.group("plus"))
        name = str(match.group("name"))
        full = name + str(match.group("digits"))
        star = bool(match.group("star"))
        line_start = self.line_start
        self.line_start = False
        if self.note is not None:
            self._end_ref_capture()
            self.note.caller_pending = False

        if self.in_skip:
            if self.skip_closer is None:
                self._end_skip()
            elif star and not plus and name == self.skip_closer:
                self._end_skip()
                return
            elif not plus and name in _O_STRUCTURAL:
                self._end_skip()
            else:
                return

        if star:
            self._closer(name)
            return
        if self.note is not None and not plus and name in _O_STRUCTURAL:
            self._close_note()
        if self.note is not None and self.note.discard:
            return
        self._opener(name, full, plus, line_start)

    def _opener(self, name: str, full: str, plus: bool, line_start: bool) -> None:
        if plus:
            if name in _O_CHAR:
                self.char_stack.append(name)
            else:
                self._count_unknown(full)
        elif name == "v":
            self._verse_marker()
        elif name == "c":
            self._end_verse()
            self._close_unknown()
            self.block_open = False
            value = self._value()
            if value is not None and value.isdigit():
                self.chapter = int(value)
        elif name == "id":
            self._end_verse()
            self._close_unknown()
            self.block_open = False
            value = self._value()
            if value is not None:
                self.book = value.upper()
            self.stats["metadata_markers"] += 1
            self._start_skip(None)
        elif name in _O_NOTE_OPEN:
            self._open_note(discard=False)
        elif name == "x":
            self._open_note(discard=True)
        elif name == "fr" and self.note is not None:
            self.note.capturing_ref = True
            self.note.ref_buf = []
        elif name in _O_SKIP_CLOSED:
            self._start_skip(name)
        elif name in {"vp", "cp"}:
            self._value()
        elif name in _O_METADATA:
            self.stats["metadata_markers"] += 1
            self._start_skip(None)
        elif name in _O_PARA:
            self._para_marker(full)
        elif name in _O_HEADING or name in _O_INTRO:
            self._block_marker(full)
        elif name in _O_BLANK:
            return
        elif name in _O_CHAR:
            self.char_stack.append(name)
        elif name in _O_NOTE_INNER:
            return
        elif line_start and self.note is None:
            self._unknown_block(full)
        else:
            self._count_unknown(full)

    def _closer(self, name: str) -> None:
        note = self.note
        if note is not None:
            if note.discard:
                if name == "x":
                    self._close_note()
                return
            if name in _O_NOTE_OPEN:
                self._close_note()
                return
        if name in _O_CHAR:
            self._pop_char(name)
        elif name not in _O_KNOWN:
            self._count_unknown(name)

    def _text(self, run: str) -> None:
        if run.strip(" \t"):
            self.line_start = False
        if self.in_skip:
            return
        note = self.note
        if note is not None:
            if note.discard:
                return
            if note.capturing_ref:
                note.ref_buf.append(run)
                return
            if note.caller_pending:
                stripped = run.lstrip(" \t")
                if not stripped:
                    return
                caller = _O_CALLER.match(stripped)
                note.caller = caller.group(0) if caller else ""
                note.caller_pending = False
                run = stripped[len(note.caller) :]
            note.buf.append(self._keep(run))
            return
        kept = self._keep(run)
        if self.in_verse:
            self.buf.append(kept)
        elif self.unknown is not None:
            self.unknown.buf.append(kept)
        elif self.block_open:
            return
        else:
            self._unknown_block(self.last_marker)
            self.unknown.buf.append(kept)

    def _newline(self) -> None:
        self.line_start = True
        if self.in_skip:
            if self.skip_closer is None:
                self._end_skip()
            return
        if self.drop_for is not None:
            return
        note = self.note
        if note is not None:
            if note.discard:
                return
            if note.capturing_ref:
                note.ref_buf.append(" ")
                return
            note.caller_pending = False
            note.buf.append(self._fold())
        elif self.in_verse:
            self.buf.append(self._fold())
        elif self.unknown is not None:
            self.unknown.buf.append(self._fold())

    # -- verse and context helpers ------------------------------------------------------------

    def _verse_marker(self) -> None:
        self._flush_piece()
        self._close_unknown()
        self.block_open = False
        value = self._value()
        if value is None or _VERSE_LABEL.fullmatch(value) is None:
            return
        self.verse_label = value
        self.in_verse = True
        self.part = 0
        self.verse_had_text = False
        self.buf = []

    def _para_marker(self, full: str) -> None:
        self._flush_piece()
        self._close_unknown()
        self.last_marker = full
        if self.verse_label is not None:
            self.in_verse = True
            self.block_open = False
        else:
            self.in_verse = False
            self.block_open = False

    def _block_marker(self, full: str) -> None:
        self._flush_piece()
        self._close_unknown()
        self.in_verse = False
        self.block_open = True
        self.last_marker = full

    def _unknown_block(self, full: str) -> None:
        self._count_unknown(full)
        self._flush_piece()
        self._close_unknown()
        self.in_verse = False
        self.block_open = False
        self.unknown = _OracleUnknown(self.chapter, full)

    def _flush_piece(self) -> None:
        if not self.in_verse or self.verse_label is None:
            self.buf = []
            return
        text = "".join(self.buf).strip()
        self.buf = []
        if text:
            self.pieces[(self.book, self.chapter, self.verse_label, self.part)] = text
            self.part += 1
            self.verse_had_text = True

    def _end_verse(self) -> None:
        self._flush_piece()
        if self.verse_label is not None and not self.verse_had_text:
            self.empty.append((self.book, self.chapter, self.verse_label))
        self.verse_label = None
        self.in_verse = False
        self.part = 0
        self.verse_had_text = False
        self.buf = []

    def _close_unknown(self) -> None:
        unknown = self.unknown
        self.unknown = None
        if unknown is None:
            return
        text = "".join(unknown.buf).strip()
        if text:
            self.unknown_blocks.append((self.book, unknown.chapter, unknown.marker, text))

    def _open_note(self, *, discard: bool) -> None:
        resume_verse = self.in_verse
        self._flush_piece()
        self._close_unknown()
        self.block_open = False
        self.in_verse = False
        self.note = _OracleNote(
            discard=discard,
            chapter=self.chapter,
            verse=self.verse_label or "",
            resume_verse=resume_verse,
        )

    def _close_note(self) -> None:
        note = self.note
        self.note = None
        if note is None:
            return
        if not note.discard:
            text = "".join(note.buf).strip()
            if text:
                self.notes.append((self.book, note.chapter, note.verse, text))
        if note.resume_verse:
            self.in_verse = True
            self.buf = []

    def _end_ref_capture(self) -> None:
        note = self.note
        if note is not None and note.capturing_ref:
            note.capturing_ref = False
            note.ref_buf = []

    # -- skip / text helpers ------------------------------------------------------------------

    def _start_skip(self, closer: str | None) -> None:
        self.in_skip = True
        self.skip_closer = closer

    def _end_skip(self) -> None:
        self.in_skip = False
        self.skip_closer = None

    def _keep(self, run: str) -> str:
        if self.drop_for is not None:
            return ""
        owner = next((name for name in reversed(self.char_stack) if name in {"w", "jmp"}), None)
        if owner is not None and "|" in run:
            run = run.split("|", 1)[0]
            self.drop_for = owner
            self.stats[f"{owner}_attributes_dropped"] += 1
        if "~" in run:
            run = run.replace("~", "\u00a0")
        if "//" in run:
            run = run.replace("//", "")
        return run

    def _fold(self) -> str:
        return " "

    def _pop_char(self, name: str) -> None:
        if name not in self.char_stack:
            return
        index = len(self.char_stack) - 1 - self.char_stack[::-1].index(name)
        del self.char_stack[index:]
        if self.drop_for == name:
            self.drop_for = None

    def _value(self) -> str | None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t":
            self.pos += 1
        match = _O_VALUE.match(self.text, self.pos)
        if match is None:
            return None
        self.pos = match.end()
        return match.group(0)

    def _count_unknown(self, full: str) -> None:
        self.stats[f"unknown_marker:{full}"] += 1


def _accounted_stats(stats: Mapping[str, int]) -> dict[str, int]:
    """Project scanner stats to the documented accounting counters compared by the tests."""
    return {
        key: int(value)
        for key, value in stats.items()
        if key == "metadata_markers" or key.startswith("unknown_marker:")
    }


@dataclass(frozen=True)
class _Structure:
    pieces: dict[tuple[str, int, str, int], str]
    empty: tuple[tuple[str, int, str], ...]
    notes: tuple[str, ...]
    unknown: tuple[tuple[str, int, str, str], ...]
    stats: dict[str, int]


def _oracle_structure(data: bytes) -> _Structure:
    text = data.decode("utf-8")
    if text.startswith("\ufeff"):
        text = text[1:]
    rescan = VerseRescan(text).run()
    return _Structure(
        pieces=dict(rescan.pieces),
        empty=tuple(sorted(rescan.empty)),
        notes=tuple(text for *_rest, text in rescan.notes),
        unknown=tuple(rescan.unknown_blocks),
        stats=_accounted_stats(rescan.stats),
    )


def _production_structure(data: bytes) -> _Structure:
    context = ExtractionContext(
        source_id="src_00000000000000000000000000",
        source_object_id="sobj_00000000000000000000000000",
        source_type=SourceType.PUBLICATION,
        media_type="text/x-usfm",
        source_languages=("qaa",),
        language=None,
    )
    output: ExtractionOutput = UsfmExtractor().extract(data, context)
    pieces: dict[tuple[str, int, str, int], str] = {}
    empty: list[tuple[str, int, str]] = []
    notes: list[str] = []
    unknown: list[tuple[str, int, str, str]] = []
    for unit in output.units:
        locator = dict(unit.locator)
        if locator.get("unit") == "verse":
            key = (
                str(locator["book"]),
                int(locator["chapter"]),
                str(locator["verse"]),
                int(locator["part"]),
            )
            pieces[key] = unit.raw_text
        elif locator.get("unit") == "footnote":
            notes.append(unit.raw_text)
        elif locator.get("unit") == "unknown":
            unknown.append(
                (
                    str(locator["book"]),
                    int(locator["chapter"]),
                    str(locator.get("marker", "")),
                    unit.raw_text,
                )
            )
    for locator in output.empty_units:
        projected = dict(locator)
        if projected.get("unit") == "verse":
            empty.append(
                (str(projected["book"]), int(projected["chapter"]), str(projected["verse"]))
            )
    return _Structure(
        pieces=pieces,
        empty=tuple(sorted(empty)),
        notes=tuple(notes),
        unknown=tuple(unknown),
        stats=_accounted_stats(dict(output.stats)),
    )


_SYNTHETIC_USFM: dict[str, bytes] = {
    "repeated_verse_text": (b"\\id TST\n\\c 1\n\\v 1 kanu kanu kanu\n\\v 2 kanu kanu kanu\n"),
    "two_midverse_notes": (
        b"\\id TST\n\\c 1\n"
        b"\\v 1 before \\f + \\fr 1:2 \\ft one\\f* middle "
        b"\\f + \\fr 1:2 \\ft two\\f* after\n"
    ),
    "continued_paragraph": b"\\id TST\n\\c 1\n\\v 1 start \\p\\q1 middle\n\\p end\n",
    "xxf_like": b"\\id XXF\n\\zvideo content here\nmore content\n",
    "inline_markup_and_transforms": (
        b"\\id TST\n\\c 1\n"
        b'\\v 1 kanu \\w mabi|lemma="x"\\w* ~ tail // done\n'
        b"\\v 2 \\add extra\\add* text\n"
        b"\\v 3\n"
    ),
    "nested_plus_markup": b"\\id TST\n\\c 1\n\\v 1 \\+nd Ruth\\+nd* rest\n",
    "metadata_inline_unknown_and_unknown_block": (
        b"\\id TST\n\\ide UTF-8\n\\h Test\n\\toc1 Contents\n\\rem remark text\n"
        b"\\c 1\n\\v 1 kanu \\zq inline\\zq* mabi\n"
        b"\\ztoc block text\nmore block\n\\v 2 tarabi\n"
    ),
}


@pytest.mark.parametrize("name", sorted(_SYNTHETIC_USFM))
def test_oracle_matches_production_on_synthetic_usfm(name: str) -> None:
    data = _SYNTHETIC_USFM[name]
    assert _oracle_structure(data) == _production_structure(data)


def test_oracle_placeholder_detection_is_not_triggered_by_msgs() -> None:
    assert not _is_placeholder("Marúbo Language Council")


def test_placeholder_guard_accepts_legitimate_authorization_prose() -> None:
    """Senior decision on Q2: valid prose and names are not rejected for containing letter
    sequences like "required" or embedded "todo", or for stray angle brackets around prose;
    only standalone placeholder values, placeholder words at word boundaries and explicit
    template fields are rejected."""
    assert not _is_placeholder(
        "License checked by operator on 2026-10-13; local processing permitted; "
        "redistribution not required."
    )
    assert not _is_placeholder("Todomé Council of the Javari")
    assert not _is_placeholder("Atbdala Foundation")
    assert not _is_placeholder("Secretaría <de Asuntos> Marúbo, 1985")
    assert not _is_placeholder("<h> and \\toc1 are USFM markers, not template fields")


def test_placeholder_guard_rejects_placeholder_records() -> None:
    for value in (
        None,
        "",
        "   ",
        "placeholder",
        "changeme",
        "TBD",
        "TODO ask the council",
        "test",
        "unknown",
        "<fill in>",
        "<name>",
        "{{rights holder}}",
    ):
        assert _is_placeholder(value), value


# ---------------------------------------------------------------------------------------------
# Committed expectations: shape only (numbers and marker names)
# ---------------------------------------------------------------------------------------------


def _load_expected() -> dict[str, object]:
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


def test_expected_counts_file_is_numbers_and_marker_names_only() -> None:
    expected = _load_expected()
    assert set(expected) == {
        "books",
        "verse_markers_by_book",
        "verses_by_book",
        "verses_total",
        "unknown_markers",
        "normalization_failed",
        "token_span_unmappable",
        "reviewed_by",
        "reviewed_at",
    }
    books = expected["books"]
    assert isinstance(books, list)
    assert all(isinstance(book, str) and _BOOK.fullmatch(book) for book in books)
    for key in ("verse_markers_by_book", "verses_by_book"):
        mapping = expected[key]
        assert isinstance(mapping, dict)
        assert set(mapping) == set(books)
        assert all(isinstance(value, int) and value >= 0 for value in mapping.values())
    assert isinstance(expected["verses_total"], int) and expected["verses_total"] >= 0
    unknown = expected["unknown_markers"]
    assert isinstance(unknown, list)
    assert all(isinstance(name, str) and _MARKER_NAME.fullmatch(name) for name in unknown)
    for key in ("normalization_failed", "token_span_unmappable"):
        assert isinstance(expected[key], int) and expected[key] >= 0
    for key in ("reviewed_by", "reviewed_at"):
        assert expected[key] is None or isinstance(expected[key], str)


# ---------------------------------------------------------------------------------------------
# Content-free comparison helpers (fail with IDs/locators/hashes/counts or fixed diagnostics)
# ---------------------------------------------------------------------------------------------


def _assert_pieces_conserve(
    extracted: Mapping[tuple[str, int, str, int], str],
    rescanned: Mapping[tuple[str, int, str, int], str],
) -> None:
    if extracted == rescanned:
        return
    missing = sorted(set(rescanned) - set(extracted))
    extra = sorted(set(extracted) - set(rescanned))
    mismatched = sorted(
        key for key in set(extracted) & set(rescanned) if extracted[key] != rescanned[key]
    )
    _safe_fail(
        "verse-piece conservation failed: "
        f"missing={len(missing)} extra={len(extra)} mismatched={len(mismatched)}; "
        f"sample missing locators={missing[:5]} extra locators={extra[:5]} "
        f"mismatched locators={mismatched[:5]}",
        pytrace=False,
    )


def _assert_note_texts_conserve(extracted: Sequence[str], rescanned: Sequence[str]) -> None:
    if sorted(extracted) == sorted(rescanned):
        return
    only_extracted = sum((Counter(extracted) - Counter(rescanned)).values())
    only_rescanned = sum((Counter(rescanned) - Counter(extracted)).values())
    _safe_fail(
        "note conservation failed: "
        f"extracted={len(extracted)} rescanned={len(rescanned)} "
        f"unmatched_extracted={only_extracted} unmatched_rescanned={only_rescanned}",
        pytrace=False,
    )


def _assert_unknown_conserve(
    extracted: Sequence[tuple[str, int, str, str]],
    rescanned: Sequence[tuple[str, int, str, str]],
) -> None:
    if sorted(extracted) == sorted(rescanned):
        return
    markers_extracted = sorted({entry[2] for entry in extracted})
    markers_rescanned = sorted({entry[2] for entry in rescanned})
    _safe_fail(
        "unknown-block conservation failed: "
        f"extracted={len(extracted)} rescanned={len(rescanned)}; "
        f"extracted markers={markers_extracted} rescanned markers={markers_rescanned}",
        pytrace=False,
    )


def _assert_counts_conserve(
    extracted: Mapping[str, int], rescanned: Mapping[str, int], label: str
) -> None:
    if extracted == rescanned:
        return
    differing = [
        f"{key}:{extracted.get(key, 0)}!={rescanned.get(key, 0)}"
        for key in sorted(set(extracted) | set(rescanned))
        if extracted.get(key, 0) != rescanned.get(key, 0)
    ]
    _safe_fail(f"{label} counts differ: {', '.join(differing)}", pytrace=False)


def _assert_absent(sample: Sequence[str], haystack: str) -> None:
    """Every sampled text must be absent from ``haystack``; failures never echo text or logs."""
    for index, text in enumerate(sample):
        if text in haystack:
            _safe_fail(
                f"sampled text {index + 1} of {len(sample)} appears in captured logs or "
                "report artifacts",
                pytrace=False,
            )


def _caplog_haystack(caplog: pytest.LogCaptureFixture) -> str:
    """Setup-phase and call-phase captured records (pytest resets ``caplog.text`` per phase)."""
    records = caplog.get_records("setup") + caplog.get_records("call")
    return "\n".join(record.getMessage() for record in records)


# ---------------------------------------------------------------------------------------------
# Real-data fixture and helpers
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RealCorpus:
    ctx: AppContext
    manifest_path: Path
    manifest: SourceManifest
    package: ScriptureEarthPackage
    registration: RegistrationResult
    ingestion: IngestResult
    extraction: ExtractionResult
    normalization: NormalizationResultSummary
    tokenization: TokenizationSummary
    expected: dict[str, object]


def _stepping_clock() -> object:
    ticks = itertools.count()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return lambda: start + timedelta(seconds=next(ticks))


def _memory_context(tmp_path: Path) -> AppContext:
    return AppContext(
        repo=InMemoryRepository(),
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=_stepping_clock(),  # type: ignore[arg-type]
        new_id=new_id,
        actor="realdata-actor",
        code_revision="realdata-rev",
    )


def _leak_check(corpus: RealCorpus, caplog: pytest.LogCaptureFixture) -> None:
    """The WP2.15 no-leak check: sampled verse texts absent from captured logs and reports.

    Reads setup-phase and call-phase caplog records plus the report artifacts. With the
    function-scoped ``real_corpus`` fixture the current test's own pipeline run is part of
    those setup records. Shared with the synthetic ordering regression so both exercise one
    code path.
    """
    ctx = corpus.ctx
    verses = sorted(
        segment.raw_text
        for segment in _raw_segments(ctx, corpus.extraction)
        if segment.locator.get("unit") == "verse" and len(segment.raw_text) >= 20
    )
    if not verses:
        _safe_fail("no verse segments with at least 20 characters were produced", pytrace=False)
    sample = verses[:50]
    report_bytes = []
    for summary in (corpus.extraction, corpus.normalization, corpus.tokenization):
        report = getattr(summary, "report", None)
        if report is not None:
            report_bytes.append(ctx.artifact_store.read_bytes(report.sha256).decode("utf-8"))
    haystack = _caplog_haystack(caplog) + "\n" + "\n".join(report_bytes)
    _assert_absent(sample, haystack)


def _require_env() -> tuple[Path, Path]:
    dir_value = os.environ.get(DIR_ENV)
    manifest_value = os.environ.get(MANIFEST_ENV)
    if not dir_value or not manifest_value:
        _safe_fail(
            f"{DIR_ENV} and {MANIFEST_ENV} must point at an authorized ScriptureEarth package",
            pytrace=False,
        )
    root = Path(dir_value)
    manifest_path = Path(manifest_value)
    if not root.is_dir() or not manifest_path.is_file():
        _safe_fail(
            "ScriptureEarth package directory or reviewed manifest is missing", pytrace=False
        )
    return root, manifest_path


def _load_reviewed_manifest(manifest_path: Path) -> SourceManifest:
    try:
        manifest = load_manifest(manifest_path)
    except Exception:
        _safe_fail("the ScriptureEarth manifest is not a valid source manifest", pytrace=False)
    _assert_authorized(manifest)
    return manifest


def _assert_authorized(manifest: SourceManifest) -> None:
    """Pre-work sanity check, judged from the manifest alone with content-free diagnostics.

    ADR-0025: a source present in the repository is authorized, so this checks only that the
    manifest records where the package came from, that the local operations the pipeline needs
    resolve allow, and that outward operations (third-party API, cloud processing, raw/derived
    redistribution) stay denied. Licences, authorities, rights holders, and register notes are
    records and are not checked here.
    """
    policy = manifest.resolved_policy
    provenance = manifest.provenance
    if not provenance.acquired_from:
        _safe_fail("the manifest must record where the package was acquired from", pytrace=False)
    for operation in _LOCAL_REQUIRED:
        if resolve(policy, operation) is not PolicyDecision.ALLOW:
            _safe_fail(
                f"required local pipeline operation {operation.value} must resolve allow "
                "under the manifest policy",
                pytrace=False,
            )
    for operation in _OUTWARD_DENIED:
        if resolve(policy, operation) is not PolicyDecision.DENY:
            _safe_fail(
                f"outward operation {operation.value} must resolve deny under the manifest policy",
                pytrace=False,
            )


def _book_code(data: bytes) -> str | None:
    match = _ID_CODE.search(data)
    return match.group(1).decode("ascii").upper() if match else None


def _usfm_objects(
    ctx: AppContext, registration: RegistrationResult
) -> list[tuple[SourceObject, str, bytes]]:
    """Registered USFM objects with book codes, selected by declared media type.

    Timing (and any other non-USFM) objects are never parsed as USFM here; they stay preserved
    and hash-checked via the blob-conservation assertions. Duplicate book codes are rejected
    instead of silently overwriting a dict entry.
    """
    result: list[tuple[SourceObject, str, bytes]] = []
    owners: dict[str, str] = {}
    for obj in registration.objects:
        if obj.media_type != SE_MEDIA_USFM:
            continue
        data = ctx.raw_store.read_bytes(obj.sha256)
        code = _book_code(data)
        if code is None:
            _safe_fail(f"registered USFM object {obj.id} has no \\id book code", pytrace=False)
        if code in owners:
            _safe_fail(
                f"duplicate USFM book code {code} in objects {owners[code]} and {obj.id}",
                pytrace=False,
            )
        owners[code] = obj.id
        result.append((obj, code, data))
    return result


def _book_bytes(ctx: AppContext, registration: RegistrationResult) -> dict[str, bytes]:
    return {code: data for _obj, code, data in _usfm_objects(ctx, registration)}


def _origin_path(origin_uri: str) -> Path:
    return Path(unquote(urlsplit(origin_uri).path))


def _report_payload(ctx: AppContext, run_id: str) -> dict[str, object]:
    for object_id, role in ctx.repo.list_run_io(run_id):
        if role.value == "output" and ctx.repo.entity_type_of(object_id) is EntityType.ARTIFACT:
            artifact = ctx.repo.get_artifact(object_id)
            return json.loads(ctx.artifact_store.read_bytes(artifact.sha256))
    raise AssertionError("run has no report artifact")


def _raw_segments(ctx: AppContext, extraction: ExtractionResult) -> list:
    return ctx.repo.list_segments_for_run(extraction.run.id)


def _normalized_segments(ctx: AppContext, normalization: NormalizationResultSummary) -> list:
    return ctx.repo.list_segments_for_run(normalization.run.id)


def _count_markers(data: bytes) -> int:
    text = data.decode("utf-8", errors="replace")
    return sum(1 for m in re.finditer(r"\\([A-Za-z]+)", text) if m.group(1) == "v")


def _project_zero_books(counts: Counter[str], books: Iterable[str]) -> dict[str, int]:
    """Project per-book counts over the complete book set, retaining zero-verse books (XXF)."""
    return {book: counts.get(book, 0) for book in sorted(set(books) | set(counts))}


def _counts(ctx: AppContext) -> dict[str, int]:
    return {
        "segments": ctx.repo.count(EntityType.SEGMENT),
        "tokens": ctx.repo.count(EntityType.TOKEN_OCCURRENCE),
        "forms": ctx.repo.count(EntityType.FORM),
        "objects": ctx.repo.count(EntityType.SOURCE_OBJECT),
        "lineage": ctx.repo.count_lineage_edges(),
        "runs": ctx.repo.count_runs(),
        "blobs": ctx.repo.count_raw_blobs(),
    }


def _run_pipeline(ctx: AppContext, manifest_path: Path) -> RealCorpus:
    registration = register_source(ctx, manifest_path)
    ingestion = ingest_source(ctx, registration.source.id)
    extraction = extract_source(ctx, registration.source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    tokenization = tokenize_normalization(ctx, normalization.run.id)
    return RealCorpus(
        ctx=ctx,
        manifest_path=manifest_path,
        manifest=load_manifest(manifest_path),
        package=scan_package(manifest_path.parent),
        registration=registration,
        ingestion=ingestion,
        extraction=extraction,
        normalization=normalization,
        tokenization=tokenization,
        expected=_load_expected(),
    )


@pytest.fixture
def real_corpus(tmp_path: Path) -> RealCorpus:
    """Fresh memory corpus per test (WP2.15): function scoped, stores under ``tmp_path``.

    The scope is load-bearing, not a style choice. Each test's setup-phase pipeline run lands
    in that test's own caplog records, so ``test_no_text_in_logs_or_reports`` checks the
    pipeline it caused, and no test observes another test's corpus state (M1-fixture parity,
    no test-order effects). The separate PostgreSQL test stays independent of this fixture.
    """
    root, manifest_path = _require_env()
    # Policy before work: an unauthorized manifest is rejected before the package is scanned,
    # registered, ingested or extracted.
    _load_reviewed_manifest(manifest_path)
    try:
        scan_package(root)
    except UnsupportedSource:
        _safe_fail("ScriptureEarth package contains no USFM files", pytrace=False)
    ctx = _memory_context(tmp_path)
    return _run_pipeline(ctx, manifest_path)


def _reviewed_gate(expected: dict[str, object]) -> None:
    if expected["reviewed_by"] is None:
        _safe_fail(
            "scriptureearth_mzr_counts.json is unsigned: a senior must run the corpus, "
            "cross-check the counts and set reviewed_by",
            pytrace=False,
        )


# ---------------------------------------------------------------------------------------------
# Shared core pipeline assertions (synthetic verification first; also the RUT PostgreSQL proof)
# ---------------------------------------------------------------------------------------------


def _assert_blob_conservation(corpus: RealCorpus) -> None:
    """Every registered object (USFM and timing) keeps stored and origin bytes intact."""
    ctx = corpus.ctx
    for obj in corpus.registration.objects:
        stored = ctx.raw_store.read_bytes(obj.sha256)
        if hashlib.sha256(stored).hexdigest() != obj.sha256:
            _safe_fail(
                f"stored bytes of object {obj.id} do not hash to its registered sha256",
                pytrace=False,
            )
        origin = _origin_path(obj.origin_uri)
        if hashlib.sha256(origin.read_bytes()).hexdigest() != obj.sha256:
            _safe_fail(
                f"origin file of object {obj.id} does not hash to its registered sha256",
                pytrace=False,
            )


def _assert_normalized_identity(corpus: RealCorpus) -> None:
    ctx = corpus.ctx
    normalized = _normalized_segments(ctx, corpus.normalization)
    if not normalized:
        _safe_fail("no normalized segments produced", pytrace=False)
    for segment in normalized:
        parents = [
            edge.to_id
            for edge in ctx.repo.list_lineage_edges(segment.id, "out")
            if edge.kind is LineageKind.NORMALIZED_FROM
        ]
        if len(parents) != 1:
            _safe_fail(
                f"normalized segment {segment.id} has {len(parents)} normalized_from parents",
                pytrace=False,
            )
        parent = ctx.repo.get_segment(parents[0])
        if segment.raw_text != parent.raw_text:
            _safe_fail(
                f"normalized segment {segment.id} raw_text differs from parent {parent.id}",
                pytrace=False,
            )


def _assert_token_spans(corpus: RealCorpus) -> None:
    """Every emitted M2 token must roundtrip through both of its spans (senior review, item 2).

    A missing span is not equivalent to a documented skipped segment: each token must carry a
    raw span, a normalized span and a normalized surface over non-null segment text, and both
    slices must equal the stored surfaces. Diagnostics are fixed strings with token/segment IDs
    only. The documented ``token_span_unmappable`` skip accounting is checked separately in
    ``_assert_unmappable_count``.
    """
    ctx = corpus.ctx
    for segment in _normalized_segments(ctx, corpus.normalization):
        tokens = ctx.repo.list_tokens(segment.id)
        if not tokens:
            continue  # failed segments and documented unmappable skips emit no tokens
        normalized_text = segment.normalized_text
        if normalized_text is None:
            _safe_fail(
                f"segment {segment.id} emitted {len(tokens)} tokens without normalized text",
                pytrace=False,
            )
        for token in tokens:
            if token.raw_span is None:
                _safe_fail(
                    f"token {token.id} in segment {segment.id} has no raw span", pytrace=False
                )
            if token.normalized_span is None:
                _safe_fail(
                    f"token {token.id} in segment {segment.id} has no normalized span",
                    pytrace=False,
                )
            if token.normalized_surface is None:
                _safe_fail(
                    f"token {token.id} in segment {segment.id} has no normalized surface",
                    pytrace=False,
                )
            if segment.raw_text[token.raw_span.start : token.raw_span.end] != token.raw_surface:
                _safe_fail(
                    f"raw span does not slice to the raw surface of token {token.id} "
                    f"in segment {segment.id}",
                    pytrace=False,
                )
            if (
                normalized_text[token.normalized_span.start : token.normalized_span.end]
                != token.normalized_surface
            ):
                _safe_fail(
                    f"normalized span does not slice to the normalized surface of token "
                    f"{token.id} in segment {segment.id}",
                    pytrace=False,
                )


def _assert_unmappable_count(corpus: RealCorpus, expected_unmappable: int) -> None:
    """Reviewed ``token_span_unmappable`` skip accounting, kept separate from the span checks."""
    report = _report_payload(corpus.ctx, corpus.tokenization.run.id)
    unmappable = sum(1 for entry in report["skipped"] if entry["reason"] == "token_span_unmappable")
    if unmappable != expected_unmappable:
        _safe_fail(
            f"token_span_unmappable: {unmappable} (reviewed expectation {expected_unmappable})",
            pytrace=False,
        )


def _assert_normalization_failures(corpus: RealCorpus, expected_failed: int) -> None:
    failed = corpus.normalization.failed
    if failed != expected_failed:
        _safe_fail(
            f"normalization failures: {failed} (reviewed expectation {expected_failed})",
            pytrace=False,
        )


def _assert_rerun_reuse(corpus: RealCorpus) -> None:
    ctx = corpus.ctx
    before = _counts(ctx)
    registration = register_source(ctx, corpus.manifest_path)
    ingestion = ingest_source(ctx, registration.source.id)
    extraction = extract_source(ctx, registration.source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    tokenization = tokenize_normalization(ctx, normalization.run.id)
    stages = {
        "registration": registration.reused,
        "ingestion": ingestion.reused,
        "extraction": extraction.reused,
        "normalization": normalization.reused,
        "tokenization": tokenization.reused,
    }
    if not all(stages.values()):
        _safe_fail(f"rerun stages were not reused: {stages}", pytrace=False)
    after = _counts(ctx)
    if after != before:
        changed = sorted(key for key in before if after.get(key) != before[key])
        _safe_fail(f"rerun changed entity counts for: {', '.join(changed)}", pytrace=False)


def _assert_governance_denials(corpus: RealCorpus) -> None:
    ctx = corpus.ctx
    tokens = [
        token
        for segment in _normalized_segments(ctx, corpus.normalization)
        for token in ctx.repo.list_tokens(segment.id)
    ]
    if not tokens:
        _safe_fail("no tokens produced; governance sampling impossible", pytrace=False)
    stride = max(1, len(tokens) // 100)
    for token in tokens[::stride][:100]:
        # ADR-0025: distill_only evidence is trainable; only egress stays denied.
        if effective_decision(ctx.repo, token.id, Operation.DIRECT_TRAINING) is not (
            PolicyDecision.ALLOW
        ):
            _safe_fail(f"token {token.id} is not allowed for direct_training", pytrace=False)
        if effective_decision(ctx.repo, token.id, Operation.THIRD_PARTY_API) is not (
            PolicyDecision.DENY
        ):
            _safe_fail(f"token {token.id} is not denied for third_party_api", pytrace=False)


def _assert_core_pipeline_invariants(
    corpus: RealCorpus, *, expected_unmappable: int, expected_failed: int
) -> None:
    """Core assertions shared by the synthetic harness check and the one-book PostgreSQL run."""
    _assert_blob_conservation(corpus)
    _assert_normalized_identity(corpus)
    _assert_token_spans(corpus)
    _assert_unmappable_count(corpus, expected_unmappable)
    _assert_normalization_failures(corpus, expected_failed)
    _assert_rerun_reuse(corpus)
    _assert_governance_denials(corpus)


# ---------------------------------------------------------------------------------------------
# Synthetic harness and gate tests (run in the default suite; synthetic data only)
# ---------------------------------------------------------------------------------------------


def _synthetic_manifest(
    tmp_path: Path,
    *,
    notes: str | None = None,
    mode: PolicyMode = PolicyMode.DIRECT,
    allow: tuple[Operation, ...] = (),
    deny: tuple[Operation, ...] = (),
    authority: str = "repo-owner",
    rights_holder: str | None = None,
    include_policy: bool = True,
) -> SourceManifest:
    package = tmp_path / "auth-package"
    usfm = package / "usfm"
    usfm.mkdir(parents=True, exist_ok=True)
    (usfm / "TST.usfm").write_bytes(b"\\id TST\n\\c 1\n\\v 1 kanu\n")
    return build_manifest(
        scan_package(package),
        key="synthetic-auth",
        language="qaa",
        policy=(
            PolicySpec(
                mode=mode,
                access_class=AccessClass.COMMUNITY,
                authority=authority,
                allow=list(allow),
                deny=list(deny),
            )
            if include_policy
            else None
        ),
        provenance=Provenance(
            acquired_from="https://www.scriptureearth.org/00por.php?iso=zzz",
            rights_holder=rights_holder,
            notes=notes,
        ),
        acquired_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_authorization_gate_accepts_a_policy_less_rights_less_manifest(tmp_path: Path) -> None:
    """ADR-0025: presence authorizes. No policy block, rights holder, authority, or permission
    note is required; the resolved default still allows local work and denies egress."""
    _assert_authorized(_synthetic_manifest(tmp_path, include_policy=False))


def test_authorization_gate_enforces_local_and_outward_decisions(tmp_path: Path) -> None:
    """The check judges the manifest alone: a denied local operation or an allowed outward
    operation is rejected before any scan/registration/ingest/extract."""
    with pytest.raises(pytest.fail.Exception, match="must resolve allow"):
        _assert_authorized(_synthetic_manifest(tmp_path, deny=(Operation.READ_RAW,)))
    with pytest.raises(pytest.fail.Exception, match="must resolve deny"):
        _assert_authorized(_synthetic_manifest(tmp_path, allow=(Operation.THIRD_PARTY_API,)))


def test_verse_count_projection_retains_zero_verse_books() -> None:
    """A plain Counter over seen locators omits verse-free books; the projection keeps XXF=0."""
    seen: set[tuple[str, int, str]] = set()
    for name in ("repeated_verse_text", "xxf_like"):
        rescan = VerseRescan(_SYNTHETIC_USFM[name].decode("utf-8")).run()
        for book, chapter, verse, _part in rescan.pieces:
            seen.add((book, chapter, verse))
        for book, chapter, verse in rescan.empty:
            seen.add((book, chapter, verse))
    per_book = Counter(book for book, _chapter, _verse in seen)
    assert _project_zero_books(per_book, {"TST", "XXF"}) == {"TST": 2, "XXF": 0}


def test_book_bytes_ignores_timing_objects_and_rejects_duplicate_books(tmp_path: Path) -> None:
    """Timing objects are preserved and hash-checked but never parsed as USFM; duplicate book
    codes are rejected instead of silently overwriting dict entries."""
    package = tmp_path / "package"
    usfm = package / "usfm"
    timing = package / "timing"
    usfm.mkdir(parents=True)
    timing.mkdir(parents=True)
    timing_bytes = b"00:00:01.000\t00:00:02.000\t1:1\n"
    (usfm / "TST.usfm").write_bytes(b"\\id TST\n\\c 1\n\\v 1 kanu\n")
    (timing / "C01-TST.timing.txt").write_bytes(timing_bytes)
    manifest = build_manifest(
        scan_package(package),
        key="synthetic-timing",
        language="qaa",
        policy=PolicySpec(
            mode=PolicyMode.DISTILL_ONLY,
            access_class=AccessClass.COMMUNITY,
            authority="Synthetic Harness Authority",
        ),
        provenance=Provenance(
            acquired_from="https://www.scriptureearth.org/00por.php?iso=zzz",
            rights_holder="Synthetic Harness Rights Holder",
            notes="synthetic harness permission record",
        ),
        acquired_at=datetime(2026, 1, 1, tzinfo=UTC),
        include_timing=True,
    )
    manifest_path = package / "langpipe-manifest.yaml"
    write_manifest(manifest, manifest_path)
    ctx = _memory_context(tmp_path)
    registration = register_source(ctx, manifest_path)
    ingest_source(ctx, registration.source.id)

    timing_objects = [obj for obj in registration.objects if obj.media_type == SE_MEDIA_TIMING]
    assert len(timing_objects) == 1
    stored = ctx.raw_store.read_bytes(timing_objects[0].sha256)
    assert hashlib.sha256(stored).hexdigest() == timing_objects[0].sha256
    assert stored == timing_bytes
    assert set(_book_bytes(ctx, registration)) == {"TST"}

    (usfm / "TST-dup.usfm").write_bytes(b"\\id TST\n\\c 1\n\\v 2 mabi\n")
    dup_manifest = build_manifest(
        scan_package(package),
        key="synthetic-timing-dup",
        language="qaa",
        policy=manifest.resolved_policy,
        provenance=manifest.provenance,
        acquired_at=manifest.acquired_at,
        include_timing=True,
    )
    dup_path = package / "langpipe-manifest-dup.yaml"
    write_manifest(dup_manifest, dup_path)
    dup_ctx = _memory_context(tmp_path / "dup")
    dup_registration = register_source(dup_ctx, dup_path)
    ingest_source(dup_ctx, dup_registration.source.id)
    with pytest.raises(pytest.fail.Exception):
        _book_bytes(dup_ctx, dup_registration)


_LEAK_SENTINEL = "wp215-synthetic-leak-sentinel-7f3a"


@pytest.fixture
def _setup_phase_leak() -> None:
    # Emitted during fixture setup, before the test body: pytest resets caplog's call-phase
    # records, so only a checker that includes setup-phase records can catch this.
    logging.getLogger("langpipe").warning(_LEAK_SENTINEL)


def test_leak_checker_catches_setup_phase_log_without_printing_content(
    _setup_phase_leak: None, caplog: pytest.LogCaptureFixture
) -> None:
    haystack = _caplog_haystack(caplog)
    assert _LEAK_SENTINEL in haystack
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _assert_absent([_LEAK_SENTINEL], haystack)
    assert _LEAK_SENTINEL not in str(excinfo.value)


@pytest.fixture
def _leaky_pipeline_corpus(tmp_path: Path) -> RealCorpus:
    """Function-scoped ``real_corpus`` mirror that leaks during its own setup phase.

    Builds a synthetic package, runs the real five-stage pipeline helpers during fixture
    setup — the same phase in which the function-scoped ``real_corpus`` runs the real
    corpus — and then emits a pipeline-style log record carrying sampled synthetic verse
    text. Under a module-scoped corpus this record would be produced during an earlier
    test's setup and never reach a later test's setup/call caplog check.
    """
    package = tmp_path / "package"
    usfm = package / "usfm"
    usfm.mkdir(parents=True)
    (usfm / "TST.usfm").write_bytes(
        b"\\id TST\n\\c 1\n\\v 1 kanu mabi-ki rakanu nawa tuku\n\\v 2 tuki nawa\n"
    )
    manifest = build_manifest(
        scan_package(package),
        key="synthetic-pipeline-leak",
        language="qaa",
        policy=PolicySpec(
            mode=PolicyMode.DISTILL_ONLY,
            access_class=AccessClass.COMMUNITY,
            authority="Synthetic Harness Authority",
        ),
        provenance=Provenance(
            acquired_from="https://www.scriptureearth.org/00por.php?iso=zzz",
            rights_holder="Synthetic Harness Rights Holder",
        ),
        acquired_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    manifest_path = package / "langpipe-manifest.yaml"
    write_manifest(manifest, manifest_path)
    ctx = _memory_context(tmp_path)
    corpus = _run_pipeline(ctx, manifest_path)
    verses = sorted(
        segment.raw_text
        for segment in _raw_segments(ctx, corpus.extraction)
        if segment.locator.get("unit") == "verse" and len(segment.raw_text) >= 20
    )
    assert verses, "synthetic package must yield verse text of at least 20 characters"
    logging.getLogger("langpipe").warning("SYNTHETIC_PIPELINE_LOG %s", verses[0])
    return corpus


def test_leak_check_fails_on_setup_phase_pipeline_log_without_rendering_content(
    _leaky_pipeline_corpus: RealCorpus, caplog: pytest.LogCaptureFixture
) -> None:
    """A pipeline log leaked during corpus-fixture setup must fail the realdata leak check.

    Pins the WP2.15 ordering contract: the corpus fixture is function scoped, so its
    pipeline run — and any log it emits — belongs to the current test's setup-phase caplog
    records and is covered by that test's leak check. A module-scoped corpus runs during an
    earlier test, and the later leak check silently stops covering the pipeline (senior
    review, changes item 1).
    """
    assert real_corpus._fixture_function_marker.scope == "function"
    corpus = _leaky_pipeline_corpus
    sample = sorted(
        segment.raw_text
        for segment in _raw_segments(corpus.ctx, corpus.extraction)
        if segment.locator.get("unit") == "verse" and len(segment.raw_text) >= 20
    )
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _leak_check(corpus, caplog)
    message = str(excinfo.value)
    for text in sample:
        assert text not in message


def test_conservation_failure_output_omits_content() -> None:
    sentinel = "wp215-synthetic-verse-sentinel-9c2b"
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _assert_pieces_conserve({("TST", 1, "1", 0): sentinel}, {("TST", 1, "1", 0): "other"})
    assert sentinel not in str(excinfo.value)
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _assert_note_texts_conserve([sentinel], [])
    assert sentinel not in str(excinfo.value)
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _assert_unknown_conserve([("TST", 1, "zq", sentinel)], [])
    assert sentinel not in str(excinfo.value)
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _assert_counts_conserve({"unknown_marker:zq": 1}, {"unknown_marker:zq": 2}, "test")
    assert sentinel not in str(excinfo.value)
    assert "unknown_marker:zq:1!=2" in str(excinfo.value)


def test_harness_runs_end_to_end_on_synthetic_package(tmp_path: Path) -> None:
    """Proves the harness helpers (not the corpus) with synthetic USFM only."""
    package = tmp_path / "package"
    usfm = package / "usfm"
    usfm.mkdir(parents=True)
    (usfm / "TST.usfm").write_bytes(
        b'\\id TST\n\\c 1\n\\v 1 kanu \\w mabi|lemma="x"\\w*\n'
        b"\\v 2 \\f + \\fr 1:2 \\ft a note\\f* tail \\f + \\fr 1:2 \\ft two\\f* end\n"
        + "\\v 3 mabi-ki kanu\u0301 nawa\n".encode("utf-8")
    )
    manifest = build_manifest(
        scan_package(package),
        key="synthetic-harness",
        language="qaa",
        policy=PolicySpec(
            mode=PolicyMode.DISTILL_ONLY,
            access_class=AccessClass.COMMUNITY,
            authority="Synthetic Harness Authority",
        ),
        provenance=Provenance(
            acquired_from="https://www.scriptureearth.org/00por.php?iso=zzz",
            rights_holder="Synthetic Harness Rights Holder",
        ),
        acquired_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    manifest_path = package / "langpipe-manifest.yaml"
    write_manifest(manifest, manifest_path)

    ctx = _memory_context(tmp_path)
    corpus = _run_pipeline(ctx, manifest_path)
    assert corpus.extraction.segments > 0
    assert corpus.extraction.run.status is RunStatus.SUCCEEDED

    oracle = _oracle_structure((usfm / "TST.usfm").read_bytes())
    segment_pieces = {
        (
            str(segment.locator["book"]),
            int(segment.locator["chapter"]),
            str(segment.locator["verse"]),
            int(segment.locator["part"]),
        ): segment.raw_text
        for segment in _raw_segments(ctx, corpus.extraction)
        if segment.locator.get("unit") == "verse"
    }
    _assert_pieces_conserve(segment_pieces, oracle.pieces)

    # Positive NFC/NFD roundtrip coverage: the decomposed word normalizes to the precomposed
    # form, and its token's raw span covers the 5 raw code points while the normalized span
    # covers the 4 normalized ones (WP2.10 phenomenon, pinned here for the real-data checker).
    seen_nfd = False
    for segment in _normalized_segments(ctx, corpus.normalization):
        for token in ctx.repo.list_tokens(segment.id):
            if token.normalized_surface == "kanú":
                seen_nfd = True
                assert token.raw_span is not None
                assert segment.raw_text[token.raw_span.start : token.raw_span.end] == "kanú"
                assert token.normalized_span is not None
                assert segment.normalized_text is not None
                assert (
                    segment.normalized_text[token.normalized_span.start : token.normalized_span.end]
                    == "kanú"
                )
    assert seen_nfd, "harness produced no NFD→NFC token"

    # Shared core assertions, verified synthetically before real-data/PostgreSQL use.
    _assert_core_pipeline_invariants(corpus, expected_unmappable=0, expected_failed=0)


# ---------------------------------------------------------------------------------------------
# Token-span requirement probes (senior review, item 2): missing spans must fail, not pass
# ---------------------------------------------------------------------------------------------


@dataclass
class _ProbeSpan:
    start: int
    end: int


@dataclass
class _ProbeSegment:
    id: str
    raw_text: str
    normalized_text: str | None


@dataclass
class _ProbeToken:
    id: str
    raw_surface: str
    normalized_surface: str | None
    raw_span: _ProbeSpan | None
    normalized_span: _ProbeSpan | None


def _span_probe_corpus(segment: _ProbeSegment, tokens: Sequence[_ProbeToken]) -> object:
    """Minimal duck-typed corpus for probing ``_assert_token_spans`` (synthetic data only)."""
    return SimpleNamespace(
        ctx=SimpleNamespace(
            repo=SimpleNamespace(
                list_segments_for_run=lambda run_id: [segment],
                list_tokens=lambda segment_id: list(tokens),
            )
        ),
        normalization=SimpleNamespace(run=SimpleNamespace(id="run_probe")),
        tokenization=SimpleNamespace(run=SimpleNamespace(id="run_probe")),
    )


def _valid_probe_token() -> _ProbeToken:
    """Baseline token over ``"kanú"``: both spans and surfaces roundtrip correctly."""
    return _ProbeToken(
        id="tok_probe",
        raw_surface="kanú",
        normalized_surface="kanú",
        raw_span=_ProbeSpan(0, 5),
        normalized_span=_ProbeSpan(0, 4),
    )


def _probe_segment(normalized_text: str | None = "kanú") -> _ProbeSegment:
    return _ProbeSegment(id="seg_probe", raw_text="kanú", normalized_text=normalized_text)


def test_token_spans_check_accepts_valid_both_span_token() -> None:
    _assert_token_spans(_span_probe_corpus(_probe_segment(), [_valid_probe_token()]))


def test_token_spans_check_rejects_missing_raw_span() -> None:
    """Senior probe: a token with ``raw_span=None`` must fail the check, never pass silently."""
    token = _valid_probe_token()
    token.raw_span = None
    with pytest.raises(pytest.fail.Exception, match="no raw span"):
        _assert_token_spans(_span_probe_corpus(_probe_segment(), [token]))


def test_token_spans_check_rejects_missing_normalized_span() -> None:
    token = _valid_probe_token()
    token.normalized_span = None
    with pytest.raises(pytest.fail.Exception, match="no normalized span"):
        _assert_token_spans(_span_probe_corpus(_probe_segment(), [token]))


def test_token_spans_check_rejects_missing_normalized_surface() -> None:
    token = _valid_probe_token()
    token.normalized_surface = None
    with pytest.raises(pytest.fail.Exception, match="no normalized surface"):
        _assert_token_spans(_span_probe_corpus(_probe_segment(), [token]))


def test_token_spans_check_rejects_tokens_without_normalized_text() -> None:
    with pytest.raises(pytest.fail.Exception, match="without normalized text"):
        _assert_token_spans(
            _span_probe_corpus(_probe_segment(normalized_text=None), [_valid_probe_token()])
        )


def test_token_spans_check_accepts_segment_with_no_tokens() -> None:
    """Zero-token segments (failed or documented-unmappable) are not span violations."""
    _assert_token_spans(_span_probe_corpus(_probe_segment(), []))


# ---------------------------------------------------------------------------------------------
# Inventory report destination (senior item 3): gitignored local output only
# ---------------------------------------------------------------------------------------------


def test_inventory_report_destination_accepts_gitignored_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-selected destination under gitignored var/ is accepted and stays usable."""
    destination = _repo_root() / "var" / "wp215-destination-check"
    monkeypatch.setenv(REPORT_ENV, str(destination))
    assert _inventory_report_dir(Path("/nonexistent-tmp")) == destination
    report_file = _write_inventory_report(destination, {"a": 1})
    payload = json.loads(report_file.read_text(encoding="utf-8"))
    assert payload["status"] == "unverified"
    assert payload["code_points"] == {"U+0061": 1}
    report_file.unlink()
    destination.rmdir()


def test_inventory_report_destination_rejects_nonignored_repo_path_before_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tracked or nonignored repository destination is rejected with a fixed content-free
    diagnostic before any directory or file is created."""
    destination = _repo_root() / "tests" / "wp215-nonignored-destination"
    monkeypatch.setenv(REPORT_ENV, str(destination))
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _inventory_report_dir(Path("/nonexistent-tmp"))
    assert "no report file was written" in str(excinfo.value)
    assert not destination.exists()


def test_inventory_report_destination_defaults_to_temporary_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(REPORT_ENV, raising=False)
    assert _inventory_report_dir(tmp_path) == tmp_path
    report_file = _write_inventory_report(tmp_path, {"a": 1, "é": 2})
    text = report_file.read_text(encoding="utf-8")
    assert "U+0061" in text and "U+00E9" in text
    assert "é" not in text


# ---------------------------------------------------------------------------------------------
# Complete-output subprocess regressions (synthetic sentinels; every rendering channel)
# ---------------------------------------------------------------------------------------------


def _run_pytest_subprocess(
    tmp_path: Path, source: str, *, select_realdata: bool, junit: bool = False
) -> tuple[int, str]:
    """Run one generated synthetic test under a real pytest subprocess.

    The generated conftest re-exports the production ``realdata`` report-sanitization hook
    (``tests/integration/conftest.py``), so these runs exercise the exact capture/report
    behavior real-data tests get. Returns the exit code and the complete stdout+stderr, so
    the assertions inspect every rendering channel — failure blocks plus captured
    stdout/stderr/log sections — rather than only ``str(excinfo.value)``. With ``junit`` the
    run also serializes reports to ``tmp_path/"junit.xml"`` (the caller reads it), pinning
    that serialized reports carry no content either.
    """
    repo_root = _repo_root()
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "conftest.py").write_text(
        "from tests.integration.conftest import pytest_runtest_makereport  # noqa: F401\n",
        encoding="utf-8",
    )
    test_file = case_dir / "test_generated.py"
    test_file.write_text(source, encoding="utf-8")
    command = [sys.executable, "-m", "pytest", "-c", str(repo_root / "pyproject.toml")]
    if select_realdata:
        command += ["-m", "realdata"]
    command += [str(test_file), "-q"]
    if junit:
        command.append(f"--junitxml={tmp_path / 'junit.xml'}")
    completed = subprocess.run(
        command, cwd=repo_root, capture_output=True, text=True, timeout=600, check=False
    )
    return completed.returncode, completed.stdout + completed.stderr


def test_realdata_surface_failures_render_no_content_in_complete_output(tmp_path: Path) -> None:
    """NFC and joiner failures surface token/segment IDs only — the complete subprocess output
    of the failed tests (assertion rendering included) never echoes the synthetic surfaces."""
    source = textwrap.dedent(
        """\
        import pytest

        from tests.integration.test_scriptureearth_marubo import _assert_word_surface_wellformed


        @pytest.mark.realdata
        def test_joiner_edge() -> None:
            _assert_word_surface_wellformed(
                "SYNTHETIC_JOINER_EDGE_SENTINEL-", token_id="tok-syn", segment_id="seg-syn"
            )


        @pytest.mark.realdata
        def test_non_nfc() -> None:
            _assert_word_surface_wellformed(
                "SYNTHETIC_NON_NFC_SENTINEL_e\\u0301", token_id="tok-syn", segment_id="seg-syn"
            )
        """
    )
    code, output = _run_pytest_subprocess(tmp_path, source, select_realdata=True)
    assert code == 1, output
    assert "SYNTHETIC_JOINER_EDGE_SENTINEL" not in output
    assert "SYNTHETIC_NON_NFC_SENTINEL" not in output
    assert "́" not in output
    assert "joiner" in output
    assert "not NFC" in output


def test_realdata_inventory_outlier_renders_codepoint_labels_only(tmp_path: Path) -> None:
    """An inventory-category outlier fails by U+XXXX label only; the raw code point never
    appears anywhere in the complete output of the failed test."""
    source = textwrap.dedent(
        """\
        import pytest

        from tests.integration.test_scriptureearth_marubo import _assert_inventory_allowed


        @pytest.mark.realdata
        def test_outlier() -> None:
            _assert_inventory_allowed({"a": 1, chr(7): 3})
        """
    )
    code, output = _run_pytest_subprocess(tmp_path, source, select_realdata=True)
    assert code == 1, output
    assert chr(7) not in output
    assert "U+0007" in output
    assert "code points outside inventory categories" in output


def test_realdata_failure_output_omits_captured_setup_and_call_logs(tmp_path: Path) -> None:
    """A failing realdata test never echoes captured setup/call logs or captured stdout
    (senior probe): the sanitizing conftest redacts those capture sections on the report,
    while the in-test record inspection still detects and reports the leak content-free."""
    source = textwrap.dedent(
        """\
        import logging

        import pytest

        SENTINEL = "SYNTHETIC_SUBPROCESS_LOG_SENTINEL_42"

        @pytest.fixture
        def leaky_setup() -> None:
            logging.getLogger("langpipe").warning(SENTINEL)

        @pytest.mark.realdata
        def test_leak(leaky_setup: None, caplog: pytest.LogCaptureFixture) -> None:
            from tests.integration.test_scriptureearth_marubo import (
                _assert_absent,
                _caplog_haystack,
            )

            logging.getLogger("langpipe").warning(SENTINEL)
            print(SENTINEL)
            _assert_absent([SENTINEL], _caplog_haystack(caplog))
        """
    )
    code, output = _run_pytest_subprocess(tmp_path, source, select_realdata=True)
    assert code == 1, output
    assert "SYNTHETIC_SUBPROCESS_LOG_SENTINEL_42" not in output
    assert "appears in captured logs" in output
    assert "redacted" in output


def test_default_suite_capture_diagnostics_are_not_suppressed(tmp_path: Path) -> None:
    """Sanitization is scoped to realdata items: a plain failing test keeps pytest's default
    captured-log diagnostics."""
    source = textwrap.dedent(
        """\
        import logging

        import pytest

        SENTINEL = "SYNTHETIC_DEFAULT_SUITE_SENTINEL_77c1"

        def test_plain_failure() -> None:
            logging.getLogger("langpipe").warning(SENTINEL)
            pytest.fail("fixed synthetic diagnostic", pytrace=False)
        """
    )
    code, output = _run_pytest_subprocess(tmp_path, source, select_realdata=False)
    assert code == 1, output
    assert "SYNTHETIC_DEFAULT_SUITE_SENTINEL_77c1" in output
    assert "fixed synthetic diagnostic" in output


def test_realdata_unexpected_exceptions_render_no_content_in_any_phase(tmp_path: Path) -> None:
    """Unexpected exceptions in setup, call and teardown — plus chained exceptions, data-bearing
    rewritten assertions and unmarked ``pytest.fail`` messages — never echo content in the
    complete subprocess output nor in serialized reports (JUnit). Each failure still fails and
    still reports the exception type with safe test identity/location only (senior review,
    item 1: ``report.longrepr`` sanitization)."""
    source = textwrap.dedent(
        """\
        from collections.abc import Iterator

        import pytest


        @pytest.fixture
        def boom_setup() -> None:
            raise ValueError("SYNTHETIC_SETUP_EXCEPTION_SENTINEL_b1a2")


        @pytest.mark.realdata
        def test_setup_phase(boom_setup: None) -> None:
            pass


        @pytest.mark.realdata
        def test_call_phase() -> None:
            raise ValueError("SYNTHETIC_CALL_EXCEPTION_SENTINEL_c3d4")


        @pytest.fixture
        def boom_teardown() -> Iterator[None]:
            yield
            raise ValueError("SYNTHETIC_TEARDOWN_EXCEPTION_SENTINEL_e5f6")


        @pytest.mark.realdata
        def test_teardown_phase(boom_teardown: None) -> None:
            pass


        @pytest.mark.realdata
        def test_chained_exception() -> None:
            try:
                raise RuntimeError("SYNTHETIC_CHAIN_INNER_SENTINEL_g7h8")
            except RuntimeError as inner:
                raise ValueError("SYNTHETIC_CHAIN_OUTER_SENTINEL_i9j0") from inner


        @pytest.mark.realdata
        def test_rewritten_assertion_operands() -> None:
            assert "SYNTHETIC_REWRITTEN_ASSERT_SENTINEL_k1l2" == "constant"


        @pytest.mark.realdata
        def test_unmarked_pytest_fail_message() -> None:
            pytest.fail("SYNTHETIC_UNMARKED_FAIL_SENTINEL_m3n4", pytrace=False)
        """
    )
    junit_path = tmp_path / "junit.xml"
    code, output = _run_pytest_subprocess(tmp_path, source, select_realdata=True, junit=True)
    junit = junit_path.read_text(encoding="utf-8")
    sentinels = (
        "SYNTHETIC_SETUP_EXCEPTION_SENTINEL_b1a2",
        "SYNTHETIC_CALL_EXCEPTION_SENTINEL_c3d4",
        "SYNTHETIC_TEARDOWN_EXCEPTION_SENTINEL_e5f6",
        "SYNTHETIC_CHAIN_INNER_SENTINEL_g7h8",
        "SYNTHETIC_CHAIN_OUTER_SENTINEL_i9j0",
        "SYNTHETIC_REWRITTEN_ASSERT_SENTINEL_k1l2",
        "SYNTHETIC_UNMARKED_FAIL_SENTINEL_m3n4",
        "raise ValueError",  # no source excerpts either
    )
    for sentinel in sentinels:
        assert sentinel not in output, sentinel
        assert sentinel not in junit, sentinel
    # Failures stay failing and keep only the safe fixed diagnostics.
    assert code == 1, output
    assert "ValueError" in output and "ValueError" in junit
    assert "failure details redacted" in output and "failure details redacted" in junit
    assert "phase=setup" in output
    assert "phase=call" in output
    assert "phase=teardown" in output
    for name in (
        "test_setup_phase",
        "test_call_phase",
        "test_teardown_phase",
        "test_chained_exception",
        "test_rewritten_assertion_operands",
        "test_unmarked_pytest_fail_message",
    ):
        assert name in output, name


def test_default_suite_exception_diagnostics_are_not_suppressed(tmp_path: Path) -> None:
    """Sanitization stays scoped to realdata items: a plain unexpected exception outside
    ``realdata`` keeps pytest's default message and traceback diagnostics."""
    source = textwrap.dedent(
        """\
        import pytest


        def test_plain_exception() -> None:
            raise ValueError("SYNTHETIC_PLAIN_EXCEPTION_SENTINEL_q5r6")
        """
    )
    code, output = _run_pytest_subprocess(tmp_path, source, select_realdata=False)
    assert code == 1, output
    assert "SYNTHETIC_PLAIN_EXCEPTION_SENTINEL_q5r6" in output
    assert "ValueError" in output


def test_realdata_skips_render_safe_tuple_reasons_in_summary_and_junit(tmp_path: Path) -> None:
    """Setup- and call-phase skips keep pytest's ``(path, lineno, reason)`` longrepr shape with
    fixed safe values (senior review, G8 round 3, item 1): the ``-ra`` summary and the JUnit
    serialization never crash on the report tuple, never echo the sentinel reason or the
    data-bearing path it carried, and the original reason is never restored."""
    source = textwrap.dedent(
        """\
        import pytest

        SENTINEL = "SYNTHETIC_SKIP_REASON_SENTINEL_s7t8 at /tmp/synthetic-sensitive-corpus-path"

        @pytest.mark.realdata
        @pytest.mark.skip(reason=SENTINEL)
        def test_setup_skip() -> None:
            pass


        @pytest.mark.realdata
        def test_call_skip() -> None:
            pytest.skip(SENTINEL)
        """
    )
    junit_path = tmp_path / "junit.xml"
    code, output = _run_pytest_subprocess(tmp_path, source, select_realdata=True, junit=True)
    junit = junit_path.read_text(encoding="utf-8")
    for secret in ("SYNTHETIC_SKIP_REASON_SENTINEL_s7t8", "/tmp/synthetic-sensitive-corpus-path"):
        assert secret not in output, secret
        assert secret not in junit, secret
    # The summary renders instead of crashing on the skip report tuple (the round-3 bug).
    assert "INTERNALERROR" not in output
    assert "Traceback" not in output
    assert "AssertionError" not in output
    assert code == 0, output
    assert "2 skipped" in output
    assert "SKIPPED" in output
    assert "<realdata>" in output
    assert "skip reason redacted" in output
    # Serialized reports stay valid XML carrying the fixed safe reason and location.
    root = ElementTree.parse(junit_path).getroot()
    messages = [element.get("message") for element in root.iter("skipped")]
    assert messages == ["<realdata: skip reason redacted>"] * 2, messages
    assert 'type="pytest.skip"' in junit


def test_default_suite_skip_diagnostics_are_not_suppressed(tmp_path: Path) -> None:
    """Sanitization stays scoped to realdata items: a plain skip outside ``realdata`` keeps
    pytest's default reason rendering in the summary and in serialized reports."""
    source = textwrap.dedent(
        """\
        import pytest


        @pytest.mark.skip(reason="SYNTHETIC_PLAIN_SKIP_SENTINEL_u9v0")
        def test_plain_skip() -> None:
            pass
        """
    )
    junit_path = tmp_path / "junit.xml"
    code, output = _run_pytest_subprocess(tmp_path, source, select_realdata=False, junit=True)
    junit = junit_path.read_text(encoding="utf-8")
    assert code == 0, output
    assert "1 skipped" in output
    assert "SYNTHETIC_PLAIN_SKIP_SENTINEL_u9v0" in output
    assert "SYNTHETIC_PLAIN_SKIP_SENTINEL_u9v0" in junit


# ---------------------------------------------------------------------------------------------
# Real-data tests
# ---------------------------------------------------------------------------------------------


@REALDATA
def test_package_scan_finds_expected_books(real_corpus: RealCorpus) -> None:
    books = set(_book_bytes(real_corpus.ctx, real_corpus.registration))
    expected_books = real_corpus.expected["books"]
    assert isinstance(expected_books, list)
    assert books == set(expected_books)
    assert len(books) == 9


@REALDATA
def test_every_usfm_object_extracts_without_failure(real_corpus: RealCorpus) -> None:
    assert real_corpus.extraction.run.status is RunStatus.SUCCEEDED
    assert real_corpus.extraction.segments > 0
    assert real_corpus.ctx.repo.count_runs(RunStatus.FAILED) == 0


@REALDATA
def test_verse_counts_match_reviewed_expectations(real_corpus: RealCorpus) -> None:
    expected = real_corpus.expected
    _reviewed_gate(expected)

    books = _book_bytes(real_corpus.ctx, real_corpus.registration)
    markers = {book: _count_markers(data) for book, data in books.items()}
    if markers != expected["verse_markers_by_book"]:
        _safe_fail(
            f"verse-marker counts differ from reviewed expectations: {markers} != "
            f"{expected['verse_markers_by_book']}",
            pytrace=False,
        )

    seen: set[tuple[str, int, str]] = set()
    for segment in _raw_segments(real_corpus.ctx, real_corpus.extraction):
        if segment.locator.get("unit") == "verse":
            seen.add(
                (
                    str(segment.locator["book"]),
                    int(segment.locator["chapter"]),
                    str(segment.locator["verse"]),
                )
            )
    report = _report_payload(real_corpus.ctx, real_corpus.extraction.run.id)
    objects = report["objects"]
    assert isinstance(objects, list)
    for entry in objects:
        for locator in entry["empty_units"]:
            if locator.get("unit") == "verse":
                seen.add((str(locator["book"]), int(locator["chapter"]), str(locator["verse"])))
    per_book = Counter(book for book, _chapter, _verse in seen)
    expected_books = expected["books"]
    assert isinstance(expected_books, list)
    projected = _project_zero_books(per_book, set(expected_books) | set(books))
    if projected != expected["verses_by_book"]:
        _safe_fail(
            f"verse locator counts differ from reviewed expectations: {projected} != "
            f"{expected['verses_by_book']}",
            pytrace=False,
        )
    if sum(projected.values()) != expected["verses_total"]:
        _safe_fail(
            f"verse locator total {sum(projected.values())} != reviewed {expected['verses_total']}",
            pytrace=False,
        )

    assert markers["XXF"] == 0
    assert "XXF" in books
    assert any(
        segment.locator.get("unit") != "verse" and segment.locator.get("book") == "XXF"
        for segment in _raw_segments(real_corpus.ctx, real_corpus.extraction)
    )


@REALDATA
def test_locators_complete_and_monotone(real_corpus: RealCorpus) -> None:
    segments = [
        segment
        for segment in _raw_segments(real_corpus.ctx, real_corpus.extraction)
        if segment.locator.get("unit") == "verse"
    ]
    if not segments:
        _safe_fail("no verse segments produced", pytrace=False)
    by_book: dict[str, list[tuple[int, int, int]]] = {}
    for segment in segments:
        locator = segment.locator
        book = str(locator["book"])
        assert _BOOK.fullmatch(book)
        chapter = locator["chapter"]
        assert isinstance(chapter, int) and chapter >= 1
        verse = str(locator["verse"])
        match = _VERSE_LABEL.fullmatch(verse)
        assert match is not None
        first = int(re.match(r"[0-9]+", verse).group(0))  # type: ignore[union-attr]
        by_book.setdefault(book, []).append((segment.ordinal, chapter, first))
    for entries in by_book.values():
        ordered = [(chapter, first) for _ordinal, chapter, first in sorted(entries)]
        assert ordered == sorted(ordered)


@REALDATA
def test_unknown_markers_reported_not_dropped(real_corpus: RealCorpus) -> None:
    expected = real_corpus.expected
    _reviewed_gate(expected)
    ctx = real_corpus.ctx
    report = _report_payload(ctx, real_corpus.extraction.run.id)
    objects = report["objects"]
    assert isinstance(objects, list)
    reported: Counter[str] = Counter()
    for entry in objects:
        for key, value in entry["stats"].items():
            if key.startswith("unknown_marker:") and value > 0:
                reported[key.split(":", 1)[1]] += int(value)
    listed = set(expected["unknown_markers"])
    if set(reported) != listed:
        _safe_fail(
            f"reported unknown markers differ from the reviewed list: "
            f"reported={sorted(reported)} reviewed={sorted(listed)}",
            pytrace=False,
        )
    # Independent rescan, counts only: every reported occurrence is matched by the oracle, and
    # each observed marker produced units (unknown blocks, conserved separately) or documented
    # counted skips (the remainder of its occurrences).
    oracle_counts: Counter[str] = Counter()
    block_units: Counter[str] = Counter()
    for _obj, _code, data in _usfm_objects(ctx, real_corpus.registration):
        structure = _oracle_structure(data)
        for key, value in structure.stats.items():
            if key.startswith("unknown_marker:"):
                oracle_counts[key.split(":", 1)[1]] += value
        for _book, _chapter, marker, _text in structure.unknown:
            block_units[marker] += 1
    _assert_counts_conserve(dict(reported), dict(oracle_counts), "unknown-marker")
    for marker, blocks in sorted(block_units.items()):
        if blocks > oracle_counts.get(marker, 0):
            _safe_fail(
                f"unknown marker {marker} produced {blocks} block units beyond its counted "
                "occurrences",
                pytrace=False,
            )


@REALDATA
def test_raw_text_conservation_against_source_bytes(real_corpus: RealCorpus) -> None:
    ctx = real_corpus.ctx
    usfm_objects = _usfm_objects(ctx, real_corpus.registration)
    pieces: dict[tuple[str, int, str, int], str] = {}
    notes: list[str] = []
    unknown: list[tuple[str, int, str, str]] = []
    accounted: Counter[str] = Counter()
    for _obj, _code, data in usfm_objects:
        structure = _oracle_structure(data)
        pieces.update(structure.pieces)
        notes.extend(structure.notes)
        unknown.extend(structure.unknown)
        for key, value in structure.stats.items():
            accounted[key] += value

    segments = _raw_segments(ctx, real_corpus.extraction)
    segment_pieces = {
        (
            str(segment.locator["book"]),
            int(segment.locator["chapter"]),
            str(segment.locator["verse"]),
            int(segment.locator["part"]),
        ): segment.raw_text
        for segment in segments
        if segment.locator.get("unit") == "verse"
    }
    _assert_pieces_conserve(segment_pieces, pieces)

    segment_notes = [
        segment.raw_text for segment in segments if segment.locator.get("unit") == "footnote"
    ]
    _assert_note_texts_conserve(segment_notes, notes)

    segment_unknown = [
        (
            str(segment.locator["book"]),
            int(segment.locator["chapter"]),
            str(segment.locator.get("marker", "")),
            segment.raw_text,
        )
        for segment in segments
        if segment.locator.get("unit") == "unknown"
    ]
    _assert_unknown_conserve(segment_unknown, unknown)

    # Documented skipped metadata is accounted for by counts only, never by emitting content.
    report = _report_payload(ctx, real_corpus.extraction.run.id)
    objects = report["objects"]
    assert isinstance(objects, list)
    if len(objects) != len(usfm_objects):
        _safe_fail(
            f"extraction report covers {len(objects)} of {len(usfm_objects)} USFM objects",
            pytrace=False,
        )
    reported: Counter[str] = Counter()
    for entry in objects:
        for key, value in entry["stats"].items():
            reported[key] += int(value)
    _assert_counts_conserve(_accounted_stats(reported), dict(accounted), "rescan-accounted")


@REALDATA
def test_raw_blobs_unchanged_after_full_pipeline(real_corpus: RealCorpus) -> None:
    _assert_blob_conservation(real_corpus)
    assert real_corpus.ctx.repo.count_raw_blobs() >= len(real_corpus.registration.objects)


@REALDATA
def test_normalized_raw_text_identity(real_corpus: RealCorpus) -> None:
    _assert_normalized_identity(real_corpus)


@REALDATA
def test_normalization_failures_zero_or_reviewed(real_corpus: RealCorpus) -> None:
    _assert_normalization_failures(real_corpus, int(real_corpus.expected["normalization_failed"]))


@REALDATA
def test_token_spans_roundtrip_all_segments(real_corpus: RealCorpus) -> None:
    _assert_token_spans(real_corpus)
    _assert_unmappable_count(real_corpus, int(real_corpus.expected["token_span_unmappable"]))


def _assert_word_surface_wellformed(surface: str, *, token_id: str, segment_id: str) -> None:
    """Joiner/hyphen/NFC checks with content-free failures (token/segment IDs only).

    pytest renders the operands of a failing rewritten ``assert`` — including the whole
    surface — so these checks report by ID and never let the surface reach any output
    channel (senior review, item 1).
    """
    if not surface:
        _safe_fail(f"token {token_id} in segment {segment_id} has an empty surface", pytrace=False)
    edge = "starts" if surface[0] in _JOINERS else "ends" if surface[-1] in _JOINERS else None
    if edge is not None:
        _safe_fail(f"token {token_id} in segment {segment_id} {edge} with a joiner", pytrace=False)
    if "-" in surface:
        left, _sep, right = surface.partition("-")
        if not left or not right:
            _safe_fail(
                f"token {token_id} in segment {segment_id} has an empty side around '-'",
                pytrace=False,
            )
    if not unicodedata.is_normalized("NFC", surface):
        _safe_fail(f"surface of token {token_id} in segment {segment_id} is not NFC", pytrace=False)


@REALDATA
def test_hyphenated_and_nasal_forms_not_split(real_corpus: RealCorpus) -> None:
    ctx = real_corpus.ctx
    seen_words = 0
    for segment in _normalized_segments(ctx, real_corpus.normalization):
        for token in ctx.repo.list_tokens(segment.id):
            if token.form_id is None:
                continue
            seen_words += 1
            surface = token.normalized_surface or token.raw_surface
            _assert_word_surface_wellformed(surface, token_id=token.id, segment_id=segment.id)
    if seen_words == 0:
        _safe_fail("no word tokens with forms were produced", pytrace=False)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _inventory_report_dir(tmp_path: Path) -> Path:
    """Resolve the inventory-report destination before any directory or file is created.

    Accepts the per-test temporary directory (default) or a caller-selected local destination;
    a destination inside this repository is accepted only when the report file itself is
    gitignored and untracked (e.g. under var/). Tracked or nonignored repository destinations
    are rejected with a fixed content-free diagnostic and nothing is written (senior review,
    item 3). The global .gitignore is never extended to hide operator-chosen paths.
    """
    raw = os.environ.get(REPORT_ENV)
    if not raw:
        return tmp_path
    destination = Path(raw).expanduser()
    if not destination.is_absolute():
        _safe_fail(
            f"{REPORT_ENV} must be an absolute path to a local report directory",
            pytrace=False,
        )
    repo_root = _repo_root()
    report_file = (destination / _INVENTORY_REPORT_NAME).resolve()
    if report_file.is_relative_to(repo_root):
        relative = report_file.relative_to(repo_root).as_posix()
        tracked = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", "--", relative],
            capture_output=True,
            check=False,
        )
        ignored = subprocess.run(
            ["git", "-C", str(repo_root), "check-ignore", "-q", "--", relative],
            capture_output=True,
            check=False,
        )
        if tracked.returncode == 0 or ignored.returncode != 0:
            _safe_fail(
                "the inventory report destination inside this repository must be gitignored "
                "and untracked (use var/ or a temporary directory); no report file was written",
                pytrace=False,
            )
    return destination


def _write_inventory_report(report_dir: Path, counts: Mapping[str, int]) -> Path:
    """Write the observed-inventory report: count-only U+XXXX labels, status unverified."""
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "mzr-observed-inventory",
        "schema_version": 1,
        "status": "unverified",
        "code_points": {f"U+{ord(ch):04X}": n for ch, n in sorted(counts.items())},
    }
    report_file = report_dir / _INVENTORY_REPORT_NAME
    report_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return report_file


def _inventory_category_allowed(ch: str) -> bool:
    category = unicodedata.category(ch)
    return category[0] in {"L", "M", "P", "S"} or category in {"Zs", "Nd"}


def _assert_inventory_allowed(counts: Mapping[str, int]) -> None:
    """Fail by U+XXXX label only — a failing rewritten assert would render the raw characters."""
    outliers = sorted({ch for ch in counts if not _inventory_category_allowed(ch)})
    if outliers:
        _safe_fail(
            "code points outside inventory categories: "
            + ", ".join(f"U+{ord(ch):04X}" for ch in outliers),
            pytrace=False,
        )


@REALDATA
def test_observed_inventory_report(real_corpus: RealCorpus, tmp_path: Path) -> None:
    ctx = real_corpus.ctx
    counts: Counter[str] = Counter()
    for segment in _normalized_segments(ctx, real_corpus.normalization):
        if (
            segment.status is SegmentStatus.OK
            and segment.normalized_text
            and segment.locator.get("unit") == "verse"
        ):
            counts.update(segment.normalized_text)
    report_dir = _inventory_report_dir(tmp_path)
    _write_inventory_report(report_dir, counts)
    _assert_inventory_allowed(counts)


@REALDATA
def test_idempotent_full_rerun(real_corpus: RealCorpus) -> None:
    _assert_rerun_reuse(real_corpus)


@REALDATA
def test_distill_only_governance_on_real_data(real_corpus: RealCorpus) -> None:
    _assert_governance_denials(real_corpus)


@REALDATA
def test_no_text_in_logs_or_reports(
    real_corpus: RealCorpus, caplog: pytest.LogCaptureFixture
) -> None:
    _leak_check(real_corpus, caplog)


@REALDATA
@INTEGRATION
def test_full_pipeline_on_postgres_with_one_book(pg_repository, tmp_path: Path) -> None:
    root, manifest_path = _require_env()
    manifest = _load_reviewed_manifest(manifest_path)
    expected = _load_expected()

    # Original registered RUT object from a separate memory context (the policy gate above
    # already authorized the reviewed manifest; no full-corpus PostgreSQL parametrization).
    origin_ctx = _memory_context(tmp_path / "origin")
    origin_registration = register_source(origin_ctx, manifest_path)
    ingest_source(origin_ctx, origin_registration.source.id)
    origin_rut = next(
        (
            obj
            for obj in origin_registration.objects
            if obj.media_type == SE_MEDIA_USFM
            and _book_code(origin_ctx.raw_store.read_bytes(obj.sha256)) == "RUT"
        ),
        None,
    )
    if origin_rut is None:
        _safe_fail("the reviewed package has no RUT book", pytrace=False)

    source_dir = tmp_path / "package"
    usfm_dir = source_dir / "usfm"
    usfm_dir.mkdir(parents=True)
    rut_spec = next(
        (
            spec
            for spec in manifest.objects
            if spec.media_type == SE_MEDIA_USFM
            and _book_code((root / spec.path).read_bytes()) == "RUT"
        ),
        None,
    )
    if rut_spec is None:
        _safe_fail("the reviewed package has no RUT book", pytrace=False)
    rut_bytes = (root / rut_spec.path).read_bytes()
    if hashlib.sha256(rut_bytes).hexdigest() != origin_rut.sha256:
        _safe_fail(
            "RUT bytes do not match the registered full-corpus SourceObject sha256",
            pytrace=False,
        )
    (usfm_dir / Path(rut_spec.path).name).write_bytes(rut_bytes)

    one_book = build_manifest(
        scan_package(source_dir),
        key=manifest.key,
        language=manifest.languages[0],
        policy=manifest.resolved_policy,
        provenance=manifest.provenance,
        acquired_at=manifest.acquired_at,
    )
    single_manifest = source_dir / "langpipe-manifest.yaml"
    write_manifest(one_book, single_manifest)

    ctx = AppContext(
        repo=pg_repository,
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=_stepping_clock(),  # type: ignore[arg-type]
        new_id=new_id,
        actor="realdata-actor",
        code_revision="realdata-rev",
    )
    started = time.perf_counter()
    corpus = _run_pipeline(ctx, single_manifest)
    elapsed = time.perf_counter() - started
    print(f"elapsed_s={elapsed:.3f}")

    assert corpus.extraction.run.status is RunStatus.SUCCEEDED
    assert corpus.extraction.segments > 0
    _assert_core_pipeline_invariants(
        corpus,
        expected_unmappable=int(expected["token_span_unmappable"]),
        expected_failed=int(expected["normalization_failed"]),
    )
