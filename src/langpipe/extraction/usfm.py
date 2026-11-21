"""USFM extractor ``usfm@0.1.0`` (M2 WP2.4): a hand-written, line-independent marker scanner.

Pure: bytes in, ``ExtractionOutput`` out. No I/O, no clock, no logging of content. The only text
changes are USFM markup decoding (newline folding, ``~``, ``//``, edge stripping); see ADR-0010.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import ClassVar, NoReturn

from langpipe.domain.errors import ExtractionFailed, UnsupportedSource
from langpipe.extraction.base import ExtractedUnit, ExtractionContext, ExtractionOutput

# One token per match: a marker, a line break, a run of text (no backslash or line break), or a
# lone backslash. Every character of the input belongs to exactly one token.
_TOKEN = re.compile(
    r"\\(?P<plus>\+?)(?P<name>[A-Za-z]+)(?P<digits>[0-9]*)(?P<star>\*?)"
    r"|(?P<newline>\r\n|\r|\n)"
    r"|[^\\\r\n]+"
    r"|\\"
)
_SPACES = re.compile(r"[ \t]*")
_VALUE = re.compile(r"[^\s\\]+")
_CALLER = re.compile(r"[^ \t]+")
_CHAPTER = re.compile(r"[0-9]+")
_VERSE = re.compile(r"[0-9]+[a-z]?(?:-[0-9]+[a-z]?)?")
_LINE_BREAK = re.compile(rb"\r\n|\r|\n")

_PARA = frozenset(
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
    }
)
_HEADING = frozenset({"s", "ms", "mr", "sr", "r", "sp", "d", "mt", "mte", "cl"})
_INTRO = frozenset({"ip", "is", "imt", "io", "ipr", "iq", "im", "imq"})
_METADATA = frozenset({"h", "toc", "toca", "ide", "rem", "sts", "usfm", "periph"})
_CHAR = frozenset(
    {
        "add", "nd", "wj", "bk", "qt", "k", "tl", "sc", "it", "bd", "bdit", "em", "no", "sup",
        "pn", "png", "qs", "qac", "w", "jmp",
    }
)  # fmt: skip
_NOTE_INNER = frozenset({"fq", "fqa", "ft", "fk", "fl", "fw", "fp", "fv", "fdc", "fr"})
_NOTE_OPENERS = frozenset({"f", "fe"})
_BLANK = frozenset({"b", "ib"})
# Skipped content with a closing marker: name -> stats counter.
_SKIP_CLOSED: dict[str, str] = {
    "fig": "figures",
    "rq": "inline_refs",
    "ca": "alt_numbering",
    "va": "alt_numbering",
}
_KNOWN = (
    _PARA
    | _HEADING
    | _INTRO
    | _METADATA
    | _CHAR
    | _NOTE_INNER
    | _NOTE_OPENERS
    | _BLANK
    | frozenset({"v", "c", "id", "x", "cp", "vp"})
    | frozenset(_SKIP_CLOSED)
)
# Markers that end a verse piece or an open note; inside a note they are an unclosed-note error.
_STRUCTURAL = _PARA | _HEADING | _INTRO | frozenset({"v", "c", "id", "x", "f", "fe"})


@dataclass
class _Verse:
    chapter: int
    label: str
    para: str
    para_index: int
    pieces: int = 0
    published: str | None = None  # \vp value of this verse, applied to all its pieces
    locators: list[dict[str, str | int]] = field(default_factory=list)


@dataclass
class _Ctx:
    """An open text context; its buffer becomes one unit when it closes."""

    kind: str  # verse | heading | introduction | unknown
    marker: str
    chapter: int
    para: str
    para_index: int
    verse: _Verse | None
    buf: list[str] = field(default_factory=list)


@dataclass
class _Note:
    discard: bool  # \x: counted and removed, never emitted as a unit
    chapter: int
    verse: str
    note_index: int
    resume: _Ctx | None
    caller: str = ""
    note_ref: str = ""
    caller_pending: bool = True
    capturing_ref: bool = False
    buf: list[str] = field(default_factory=list)
    ref_buf: list[str] = field(default_factory=list)


@dataclass
class _Skip:
    closer: str | None  # None: the skipped content ends at the next marker or line break


class _Scanner:
    def __init__(self, source_object_id: str, language: str, text: str) -> None:
        self.source_object_id = source_object_id
        self.language = language
        self.text = text
        self.pos = 0
        self.line = 1
        self.line_start = True
        self.book: str | None = None
        self.chapter = 0
        self.para = ""
        self.para_index = 0
        self.para_count = 0
        self.last_marker = ""
        self.verse: _Verse | None = None
        self.ctx: _Ctx | None = None
        self.note: _Note | None = None
        self.skip: _Skip | None = None
        self.char_stack: list[str] = []
        self.drop_for: str | None = None
        self.chapter_published: dict[int, str] = {}  # \cp value per chapter number
        self.note_count = 0
        self.units: list[tuple[dict[str, str | int], str]] = []
        self.empty: list[dict[str, str | int]] = []
        self.stats: Counter[str] = Counter()

    def run(self) -> ExtractionOutput:
        while self.pos < len(self.text):
            match = _TOKEN.match(self.text, self.pos)
            assert match is not None  # _TOKEN matches every character
            self.pos = match.end()
            if match.group("name") is not None:
                self._marker(match)
            elif match.group("newline") is not None:
                self._newline()
            else:
                self._text(match.group(0))
        self._finish()
        self._apply_chapter_labels()
        units = tuple(
            ExtractedUnit(ordinal=i, language=self.language, locator=loc, raw_text=text)
            for i, (loc, text) in enumerate(self.units)
        )
        return ExtractionOutput(units=units, stats=dict(self.stats), empty_units=tuple(self.empty))

    # ----- tokens -------------------------------------------------------------------------

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

        if self.skip is not None:
            if self.skip.closer is None:
                self._end_skip()
            elif star and not plus and name == self.skip.closer:
                self._end_skip()
                return
            elif not plus and name in _STRUCTURAL:
                self._end_skip()
            else:
                return

        if star:
            self._closer(name, full)
            return
        if self.note is not None and not plus and name in _STRUCTURAL:
            self._fail("usfm_unclosed_note")
        if self.note is not None and self.note.discard:
            return
        self._opener(name, full, plus, line_start)

    def _opener(self, name: str, full: str, plus: bool, line_start: bool) -> None:
        if plus:
            if name in _CHAR:
                self.char_stack.append(name)
            else:
                self._count_unknown(full)
        elif name == "v":
            self._verse_marker()
        elif name == "c":
            self._chapter_marker()
        elif name == "id":
            self._id_marker()
        elif name in _NOTE_OPENERS:
            self._open_note(discard=False)
        elif name == "x":
            self._open_note(discard=True)
        elif name == "fr" and self.note is not None:
            self.note.capturing_ref = True
            self.note.ref_buf = []
        elif name in _SKIP_CLOSED:
            self.stats[_SKIP_CLOSED[name]] += 1
            self._start_skip(name)
        elif name == "vp":
            self.stats["alt_numbering"] += 1
            self._set_published_verse(self._value())
        elif name == "cp":
            self.stats["published_chapter"] += 1
            self._set_published_chapter(self._value())
        elif name in _METADATA:
            self.stats["metadata_markers"] += 1
            self._start_skip(None)
        elif name in _PARA:
            self._para_marker(full)
        elif name in _HEADING:
            self._block_marker("heading", full)
        elif name in _INTRO:
            self._block_marker("introduction", full)
        elif name in _BLANK:
            self.stats["b_markers"] += 1
        elif name in _CHAR:
            self.char_stack.append(name)
        elif name in _NOTE_INNER:
            return
        elif line_start and self.note is None:
            self._unknown_block(full)
        else:
            self._count_unknown(full)

    def _closer(self, name: str, full: str) -> None:
        note = self.note
        if note is not None:
            if note.discard:
                if name == "x":
                    self._close_note()
                return
            if name in _NOTE_OPENERS:
                self._close_note()
                return
        if name in _CHAR:
            self._pop_char(name)
        elif name not in _KNOWN:
            self._count_unknown(full)

    def _text(self, run: str) -> None:
        if run.strip(" \t"):
            self.line_start = False
        if self.skip is not None:
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
                caller = _CALLER.match(stripped)
                note.caller = caller.group(0) if caller else ""
                note.caller_pending = False
                run = stripped[len(note.caller) :]
            note.buf.append(self._keep(run))
            return
        if self.ctx is None:
            if not run.strip(" \t"):
                return
            self._open_ctx("unknown", self.last_marker)
        assert self.ctx is not None
        self.ctx.buf.append(self._keep(run))

    def _newline(self) -> None:
        self.line += 1
        self.line_start = True
        if self.skip is not None:
            if self.skip.closer is None:  # metadata and \id values end with their line
                self._end_skip()
            return
        if self.drop_for is not None:
            return
        if self.note is not None:
            if self.note.discard:
                return
            if self.note.capturing_ref:
                self.note.ref_buf.append(" ")
                return
            self.note.caller_pending = False
            self.note.buf.append(self._fold())
        elif self.ctx is not None:
            self.ctx.buf.append(self._fold())

    def _finish(self) -> None:
        if self.note is not None:
            self._fail("usfm_unclosed_note")
        self._end_skip()
        self._close_ctx()
        self._finish_verse()
        self._require_book()

    # ----- structure ----------------------------------------------------------------------

    def _verse_marker(self) -> None:
        self._close_ctx()
        self._finish_verse()
        self._reset_chars()
        self._require_book()
        value = self._value()
        if self.chapter == 0:
            self._fail("usfm_verse_before_chapter")
        if value is None or _VERSE.fullmatch(value) is None:
            self._fail("usfm_bad_verse")
        self.verse = _Verse(self.chapter, value, self.para, self.para_index)
        self._open_ctx("verse", "")

    def _chapter_marker(self) -> None:
        self._close_ctx()
        self._finish_verse()
        self._reset_chars()
        self._require_book()
        value = self._value()
        if value is None or _CHAPTER.fullmatch(value) is None or int(value) < 1:
            self._fail("usfm_bad_chapter")
        self.chapter = int(value)
        self.last_marker = "c"

    def _id_marker(self) -> None:
        self._close_ctx()
        self._finish_verse()
        self._reset_chars()
        value = self._value()
        if value is None:
            self._fail("usfm_missing_id")
        self.book = value.upper()
        self.stats["metadata_markers"] += 1
        self._start_skip(None)

    def _para_marker(self, full: str) -> None:
        self._close_ctx()
        self._reset_chars()
        self.para = full
        self.para_index = self.para_count
        self.para_count += 1
        if self.verse is not None:
            self._open_ctx("verse", "")
        else:
            self._open_ctx("unknown", full)
        self.last_marker = full

    def _block_marker(self, kind: str, full: str) -> None:
        self._close_ctx()
        self._reset_chars()
        self._open_ctx(kind, full)
        self.last_marker = full

    def _unknown_block(self, full: str) -> None:
        self._count_unknown(full)
        self._close_ctx()
        self._reset_chars()
        self._open_ctx("unknown", full)

    def _open_note(self, *, discard: bool) -> None:
        resume = self.ctx
        self._close_ctx()
        if discard:
            self.stats["xref_notes"] += 1
            index = 0
        else:
            index = self.note_count
            self.note_count += 1
        verse = self.verse.label if self.verse is not None else ""
        self.note = _Note(
            discard=discard,
            chapter=self.chapter,
            verse=verse,
            note_index=index,
            resume=resume,
        )

    def _close_note(self) -> None:
        note = self.note
        self.note = None
        if note is None:
            return
        if not note.discard:
            text = self._strip(note.buf)
            base: dict[str, str | int] = {
                "chapter": note.chapter,
                "verse": note.verse,
                "unit": "footnote",
                "note_index": note.note_index,
                "caller": note.caller,
                "note_ref": note.note_ref,
            }
            if text:
                self._emit(base, text)
            else:
                self.empty.append({"book": self._require_book(), **base})
        self.ctx = self._reopen(note.resume)

    def _end_ref_capture(self) -> None:
        note = self.note
        if note is not None and note.capturing_ref:
            note.capturing_ref = False
            note.note_ref = "".join(note.ref_buf).strip()

    def _start_skip(self, closer: str | None) -> None:
        self.skip = _Skip(closer=closer)

    def _end_skip(self) -> None:
        self.skip = None

    def _set_published_verse(self, value: str | None) -> None:
        """Attach a \\vp value to the verse it appears in, including pieces already emitted."""
        verse = self.verse
        if value is None or verse is None:
            return  # no verse to attach to; footnotes, headings and units never take it
        verse.published = value
        for locator in verse.locators:
            locator["published_verse"] = value

    def _set_published_chapter(self, value: str | None) -> None:
        if value is not None:
            self.chapter_published[self.chapter] = value

    def _apply_chapter_labels(self) -> None:
        for locator in [loc for loc, _ in self.units] + self.empty:
            chapter = locator.get("chapter")
            if isinstance(chapter, int) and chapter in self.chapter_published:
                locator["published_chapter"] = self.chapter_published[chapter]

    # ----- contexts and units -------------------------------------------------------------

    def _open_ctx(self, kind: str, marker: str) -> None:
        verse = self.verse if kind == "verse" else None
        self.ctx = _Ctx(kind, marker, self.chapter, self.para, self.para_index, verse)

    def _reopen(self, old: _Ctx | None) -> _Ctx | None:
        if old is None:
            return None
        return _Ctx(old.kind, old.marker, old.chapter, old.para, old.para_index, old.verse)

    def _close_ctx(self) -> None:
        ctx = self.ctx
        self.ctx = None
        if ctx is None:
            return
        text = self._strip(ctx.buf)
        if not text:
            return
        self._require_book()
        if ctx.verse is not None:
            verse = ctx.verse
            base: dict[str, str | int] = {
                "chapter": verse.chapter,
                "verse": verse.label,
                "unit": "verse",
                "para": ctx.para,
                "para_index": ctx.para_index,
                "part": verse.pieces,
            }
            verse.pieces += 1
            locator = self._emit(base, text)
            if verse.published is not None:
                locator["published_verse"] = verse.published
            verse.locators.append(locator)
            return
        if ctx.kind == "unknown":
            base = {
                "chapter": ctx.chapter,
                "unit": "unknown",
                "marker": ctx.marker,
                "para_index": ctx.para_index,
            }
        elif ctx.kind == "introduction":
            base = {"unit": "introduction", "marker": ctx.marker, "para_index": ctx.para_index}
        else:
            base = {
                "chapter": ctx.chapter,
                "unit": "heading",
                "marker": ctx.marker,
                "para_index": ctx.para_index,
            }
        self._emit(base, text)

    def _emit(self, base: dict[str, str | int], text: str) -> dict[str, str | int]:
        locator: dict[str, str | int] = {"book": self._require_book(), **base}
        self.units.append((locator, text))
        return locator

    def _finish_verse(self) -> None:
        verse = self.verse
        self.verse = None
        if verse is None or verse.pieces:
            return
        empty: dict[str, str | int] = {
            "book": self._require_book(),
            "chapter": verse.chapter,
            "verse": verse.label,
            "unit": "verse",
            "para": verse.para,
            "para_index": verse.para_index,
            "part": 0,
        }
        if verse.published is not None:
            empty["published_verse"] = verse.published
        self.empty.append(empty)

    # ----- text helpers -------------------------------------------------------------------

    def _keep(self, run: str) -> str:
        """Apply the markup-decoding rules to a run of text that is kept."""
        if self.drop_for is not None:
            return ""
        owner = self._attribute_owner()
        if owner is not None and "|" in run:
            run, _, _ = run.partition("|")
            self.drop_for = owner
            self.stats[f"{owner}_attributes_dropped"] += 1
        if "~" in run:
            self.stats["tilde_nbsp"] += run.count("~")
            run = run.replace("~", "\u00a0")
        if "//" in run:
            self.stats["optional_breaks"] += run.count("//")
            run = run.replace("//", "")
        return run

    def _fold(self) -> str:
        self.stats["newline_folds"] += 1
        return " "

    def _strip(self, parts: list[str]) -> str:
        raw = "".join(parts)
        text = raw.strip()
        if len(text) != len(raw):
            self.stats["edge_whitespace_stripped"] += len(raw) - len(text)
        return text

    def _attribute_owner(self) -> str | None:
        for name in reversed(self.char_stack):
            if name in ("w", "jmp"):
                return name
        return None

    def _pop_char(self, name: str) -> None:
        if name not in self.char_stack:
            return
        index = len(self.char_stack) - 1 - self.char_stack[::-1].index(name)
        del self.char_stack[index:]
        if self.drop_for == name:
            self.drop_for = None

    def _reset_chars(self) -> None:
        self.char_stack.clear()
        self.drop_for = None

    def _value(self) -> str | None:
        """Read the value token that follows a marker on the same line."""
        spaces = _SPACES.match(self.text, self.pos)
        start = spaces.end() if spaces is not None else self.pos
        value = _VALUE.match(self.text, start)
        if value is None:
            self.pos = start
            return None
        self.pos = value.end()
        return value.group(0)

    def _count_unknown(self, full: str) -> None:
        self.stats[f"unknown_marker:{full}"] += 1

    def _require_book(self) -> str:
        if self.book is None:
            self._fail("usfm_missing_id")
        return self.book

    def _fail(self, code: str) -> NoReturn:
        raise ExtractionFailed(code, self.source_object_id, self.line)


def _resolve_language(ctx: ExtractionContext) -> str:
    # Same rule as plain_lines (M2 WP2.3): explicit override, else the single source language.
    if ctx.language is not None:
        return ctx.language
    if len(ctx.source_languages) == 1:
        return ctx.source_languages[0]
    raise UnsupportedSource("language_ambiguous")


def _decode(data: bytes, source_object_id: str) -> tuple[str, bool]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = len(_LINE_BREAK.findall(data, 0, exc.start)) + 1
        raise ExtractionFailed("decode_error", source_object_id, line) from None
    if text.startswith("\ufeff"):
        return text[1:], True
    return text, False


class UsfmExtractor:
    name: ClassVar[str] = "usfm"
    version: ClassVar[str] = "0.1.0"

    def extract(self, data: bytes, ctx: ExtractionContext) -> ExtractionOutput:
        language = _resolve_language(ctx)
        text, bom_removed = _decode(data, ctx.source_object_id)
        scanner = _Scanner(ctx.source_object_id, language, text)
        if bom_removed:
            scanner.stats["bom_removed"] = 1
        return scanner.run()
