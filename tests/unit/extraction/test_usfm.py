import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from langpipe.domain.enums import SourceType
from langpipe.domain.errors import ExtractionFailed, UnsupportedSource
from langpipe.extraction.base import ExtractionContext, ExtractionOutput
from langpipe.extraction.registry import EXTRACTORS
from langpipe.extraction.usfm import UsfmExtractor

FIXTURE = Path(__file__).parents[2] / "fixtures" / "text" / "qaa_sample.usfm"

PAYLOAD = "zzsecretzz"  # distinctive text that must never appear in an error message


def _ctx(language: str | None = None, languages: tuple[str, ...] = ("qaa",)) -> ExtractionContext:
    return ExtractionContext(
        source_id="src-test",
        source_object_id="obj-test",
        source_type=SourceType.PUBLICATION,
        media_type="text/x-usfm",
        source_languages=languages,
        language=language,
    )


def _run(text: str | bytes, language: str | None = None) -> ExtractionOutput:
    data = text if isinstance(text, bytes) else text.encode("utf-8")
    return UsfmExtractor().extract(data, _ctx(language))


def _units(out: ExtractionOutput) -> list[tuple[dict[str, Any], str]]:
    return [(dict(u.locator), u.raw_text) for u in out.units]


def test_usfm_sample_unit_sequence() -> None:
    out = UsfmExtractor().extract(FIXTURE.read_bytes(), _ctx())

    book = "RUT"
    expected: list[tuple[dict[str, Any], str]] = [
        (
            {"book": book, "chapter": 0, "unit": "heading", "marker": "mt1", "para_index": 0},
            "Ruth",
        ),
        (
            {"book": book, "chapter": 1, "unit": "heading", "marker": "s1", "para_index": 0},
            "Opening heading",
        ),
        (
            {
                "book": book,
                "chapter": 1,
                "verse": "1",
                "unit": "verse",
                "para": "p",
                "para_index": 0,
                "part": 0,
            },
            "Kanu  kanu mabi-ki \u00a0 ok  done",
        ),
        (
            {
                "book": book,
                "chapter": 1,
                "verse": "2-3",
                "unit": "verse",
                "para": "p",
                "para_index": 0,
                "part": 0,
            },
            "Kanu\u0301  ge  Ruth ya",
        ),
        (
            {
                "book": book,
                "chapter": 1,
                "verse": "2-3",
                "unit": "verse",
                "para": "p",
                "para_index": 1,
                "part": 1,
            },
            "more of verse three",
        ),
        (
            {
                "book": book,
                "chapter": 1,
                "verse": "2-3",
                "unit": "footnote",
                "note_index": 0,
                "caller": "+",
                "note_ref": "1:2",
            },
            "a note",
        ),
        (
            {
                "book": book,
                "chapter": 1,
                "verse": "2-3",
                "unit": "verse",
                "para": "p",
                "para_index": 1,
                "part": 2,
            },
            "after note",
        ),
        (
            {
                "book": book,
                "chapter": 1,
                "verse": "2-3",
                "unit": "verse",
                "para": "q1",
                "para_index": 2,
                "part": 3,
            },
            "line one",
        ),
        (
            {
                "book": book,
                "chapter": 1,
                "verse": "2-3",
                "unit": "verse",
                "para": "q1",
                "para_index": 2,
                "part": 4,
            },
            "and line two",
        ),
        (
            {
                "book": book,
                "chapter": 1,
                "verse": "4",
                "unit": "verse",
                "para": "q1",
                "para_index": 2,
                "part": 0,
            },
            "Four",
        ),
        (
            {
                "book": book,
                "chapter": 1,
                "unit": "unknown",
                "marker": "zfoo",
                "para_index": 2,
            },
            "marker content",
        ),
        (
            {
                "book": book,
                "chapter": 2,
                "verse": "1",
                "unit": "verse",
                "para": "q1",
                "para_index": 2,
                "part": 0,
            },
            "Ruth  here end",
        ),
    ]
    assert _units(out) == expected
    assert [u.ordinal for u in out.units] == list(range(len(expected)))
    assert {u.language for u in out.units} == {"qaa"}
    assert list(out.empty_units) == [
        {
            "book": book,
            "chapter": 1,
            "verse": "5",
            "unit": "verse",
            "para": "q1",
            "para_index": 2,
            "part": 0,
        }
    ]
    assert out.stats["metadata_markers"] == 3
    assert out.stats["xref_notes"] == 1
    assert out.stats["w_attributes_dropped"] == 1
    assert out.stats["jmp_attributes_dropped"] == 1
    assert out.stats["tilde_nbsp"] == 1
    assert out.stats["optional_breaks"] == 1
    assert out.stats["unknown_marker:zfoo"] == 1


def test_usfm_verse_across_paragraphs_has_parts() -> None:
    out = _run("\\id RUT\n\\c 1\n\\p\n\\v 1 a\n\\p\nb\n\\q1 c\n")

    parts = [(u.locator["para"], u.locator["part"], u.raw_text) for u in out.units]
    assert parts == [("p", 0, "a"), ("p", 1, "b"), ("q1", 2, "c")]
    assert all(u.locator["verse"] == "1" for u in out.units)


def test_usfm_footnote_separate_unit_and_absent_from_verse() -> None:
    out = _run("\\id RUT\n\\c 1\n\\p\n\\v 1 wo\\f + \\ft NOTE\\f*rd\n")

    verse_texts = [u.raw_text for u in out.units if u.locator["unit"] == "verse"]
    assert verse_texts == ["wo", "rd"]
    notes = [u.raw_text for u in out.units if u.locator["unit"] == "footnote"]
    assert notes == ["NOTE"]
    assert all("NOTE" not in text for text in verse_texts)


def test_usfm_multiple_midverse_notes_preserve_piece_order() -> None:
    out = _run("\\id RUT\n\\c 1\n\\p\n\\v 1 a\\f + \\ft X\\f*b\\f + \\ft Y\\f*c\n")

    assert [(u.locator["unit"], u.raw_text) for u in out.units] == [
        ("verse", "a"),
        ("footnote", "X"),
        ("verse", "b"),
        ("footnote", "Y"),
        ("verse", "c"),
    ]
    assert [u.locator["part"] for u in out.units if u.locator["unit"] == "verse"] == [0, 1, 2]
    assert [u.locator["note_index"] for u in out.units if u.locator["unit"] == "footnote"] == [
        0,
        1,
    ]


def test_usfm_bare_q_pi_and_jmp_attributes() -> None:
    out = _run('\\id RUT\n\\c 1\n\\q\n\\v 1 hi \\jmp go|href="u"\\jmp*\n\\pi1 x\n')

    assert [(u.locator["para"], u.raw_text) for u in out.units] == [
        ("q", "hi  go"),
        ("pi1", "x"),
    ]
    assert out.stats["jmp_attributes_dropped"] == 1


def test_usfm_verse_free_book_preserves_unknown_blocks() -> None:
    out = _run("\\id RUT\n\\ip Intro text\n\\c 1\n\\p Some para\n\\s1 H\n")

    assert _units(out) == [
        ({"book": "RUT", "unit": "introduction", "marker": "ip", "para_index": 0}, "Intro text"),
        (
            {"book": "RUT", "chapter": 1, "unit": "unknown", "marker": "p", "para_index": 0},
            "Some para",
        ),
        ({"book": "RUT", "chapter": 1, "unit": "heading", "marker": "s1", "para_index": 0}, "H"),
    ]


def test_usfm_character_markers_removed_content_kept() -> None:
    out = _run("\\id RUT\n\\c 1\n\\p\n\\v 1 a\\add b\\add*c\n")

    assert [u.raw_text for u in out.units] == ["a bc"]
    assert "\\" not in out.units[0].raw_text


def test_usfm_skipped_markers_are_counted() -> None:
    text = (
        "\\id RUT\n\\c 1\n\\p\n"
        '\\v 1 a\\x - \\xo 1:2 \\xt Gen\\x* b\\fig cap|src="x"\\fig* c'
        "\\rq (ref)\\rq* d\\ca 5\\ca*\\vp 3b\\vp* e\\cp 2\n"
        "\\v 2 f\n"
    )
    out = _run(text)

    assert out.stats["xref_notes"] == 1
    assert out.stats["figures"] == 1
    assert out.stats["inline_refs"] == 1
    assert out.stats["alt_numbering"] == 2
    assert out.stats["published_chapter"] == 1
    assert out.stats["metadata_markers"] == 1
    assert "Gen" not in " ".join(u.raw_text for u in out.units)
    assert "ref" not in " ".join(u.raw_text for u in out.units)


def test_usfm_unknown_marker_preserved_as_unit() -> None:
    out = _run("\\id RUT\n\\c 1\n\\p\n\\v 1 a\n\\zfoo block text\n\\v 2 b\n")

    assert [(u.locator["unit"], u.raw_text) for u in out.units] == [
        ("verse", "a"),
        ("unknown", "block text"),
        ("verse", "b"),
    ]
    assert out.units[1].locator["marker"] == "zfoo"
    assert out.stats["unknown_marker:zfoo"] == 1


def test_usfm_omitted_verse_in_empty_units() -> None:
    out = _run("\\id RUT\n\\c 1\n\\v 4 a\n\\v 5\n\\v 6 b\n")

    assert [u.locator["verse"] for u in out.units] == ["4", "6"]
    assert list(out.empty_units) == [
        {
            "book": "RUT",
            "chapter": 1,
            "verse": "5",
            "unit": "verse",
            "para": "",
            "para_index": 0,
            "part": 0,
        }
    ]


def test_usfm_nfd_text_preserved() -> None:
    out = _run("\\id RUT\n\\c 1\n\\p\n\\v 1 kanu\u0301\n")

    assert out.units[0].raw_text == "kanu\u0301"
    assert out.units[0].raw_text != unicodedata.normalize("NFC", out.units[0].raw_text)


def test_usfm_verse_range_and_letter_suffix_kept_as_strings() -> None:
    out = _run("\\id RUT\n\\c 1\n\\p\n\\v 1-2 a\n\\v 3a b\n")

    assert [u.locator["verse"] for u in out.units] == ["1-2", "3a"]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("~a~", "a", id="tilde-edges-are-stripped"),
        pytest.param("a~b", "a\u00a0b", id="internal-tilde-becomes-nbsp"),
        pytest.param("\u00a0a\u00a0", "a", id="literal-nbsp-edges-are-stripped"),
        pytest.param("\u2003a\u3000", "a", id="unicode-space-edges-are-stripped"),
        pytest.param("x\u00a0y", "x\u00a0y", id="internal-literal-nbsp-kept"),
        pytest.param("\u2003b~c\u2003", "b\u00a0c", id="unicode-edges-around-tilde"),
    ],
)
def test_usfm_edge_whitespace_stripped_internal_kept(body: str, expected: str) -> None:
    out = _run(f"\\id RUT\n\\c 1\n\\v 1 {body}\n")

    assert [u.raw_text for u in out.units] == [expected]


def test_usfm_edge_whitespace_counts_include_tilde_and_stripped_code_points() -> None:
    out = _run("\\id RUT\n\\c 1\n\\v 1 ~a~\n")

    assert out.stats["tilde_nbsp"] == 2
    # Separator space after \v 1, two NBSP from the tildes, and the trailing newline fold.
    assert out.stats["edge_whitespace_stripped"] == 4


@pytest.mark.parametrize(
    "body",
    [pytest.param("~ \u2003", id="tilde-and-unicode-space"), pytest.param("   ", id="spaces")],
)
def test_usfm_whitespace_only_verse_is_omitted_verse(body: str) -> None:
    out = _run(f"\\id RUT\n\\c 1\n\\v 4 {body}\n\\v 5 a\n")

    assert [u.raw_text for u in out.units] == ["a"]
    assert [u["verse"] for u in out.empty_units] == ["4"]


def test_usfm_published_verse_not_given_to_footnote_before_first_piece() -> None:
    out = _run("\\id RUT\n\\c 1\n\\v 1 \\vp 1a\\vp*\\f + \\ft note\\f*host\n")

    assert [(u.locator["unit"], u.raw_text) for u in out.units] == [
        ("footnote", "note"),
        ("verse", "host"),
    ]
    assert "published_verse" not in out.units[0].locator
    assert out.units[1].locator["published_verse"] == "1a"


def test_usfm_published_verse_applies_to_all_pieces_of_its_verse() -> None:
    out = _run("\\id RUT\n\\c 1\n\\v 1 a\\f + \\ft n\\f*b\\vp 1a\\vp* c\n")

    assert [(u.locator["unit"], u.raw_text) for u in out.units] == [
        ("verse", "a"),
        ("footnote", "n"),
        ("verse", "b c"),
    ]
    assert [u.locator.get("published_verse") for u in out.units] == ["1a", None, "1a"]


def test_usfm_published_verse_not_leaked_to_heading_or_next_verse_or_chapter() -> None:
    out = _run("\\id RUT\n\\c 1\n\\v 1 a\\vp 1x\\vp*\n\\s1 Head\n\\v 2 b\n\\c 2\n\\v 1 c\n")

    assert [
        (u.locator["unit"], u.raw_text, u.locator.get("published_verse")) for u in out.units
    ] == [
        ("verse", "a", "1x"),
        ("heading", "Head", None),
        ("verse", "b", None),
        ("verse", "c", None),
    ]


def test_usfm_published_verse_on_empty_verse_locator() -> None:
    out = _run("\\id RUT\n\\c 1\n\\v 5\\vp 5a\\vp*\n\\v 6 b\n")

    assert [u["verse"] for u in out.empty_units] == ["5"]
    assert out.empty_units[0]["published_verse"] == "5a"
    assert "published_verse" not in out.units[0].locator


def test_usfm_published_chapter_scoped_to_its_chapter() -> None:
    out = _run("\\id RUT\n\\c 1\n\\cp I\n\\v 1 a\n\\c 2\n\\v 1 b\n")

    assert [(u.raw_text, u.locator.get("published_chapter")) for u in out.units] == [
        ("a", "I"),
        ("b", None),
    ]


def test_usfm_metadata_line_does_not_swallow_following_text() -> None:
    out = _run("\\id RUT\n\\h Ruth\nstray text\n\\c 1\n\\v 1 a\n")

    assert "stray text" in [u.raw_text for u in out.units]
    assert [u.raw_text for u in out.units if u.locator["unit"] == "verse"] == ["a"]


def test_usfm_language_resolution_matches_plain_lines() -> None:
    data = b"\\id RUT\n\\c 1\n\\p\n\\v 1 a\n"
    ctx = _ctx(languages=("qaa", "mzr"))

    with pytest.raises(UnsupportedSource) as excinfo:
        UsfmExtractor().extract(data, ctx)
    assert excinfo.value.reason == "language_ambiguous"
    out = UsfmExtractor().extract(data, _ctx(language="mzr", languages=("qaa", "mzr")))
    assert {u.language for u in out.units} == {"mzr"}


@pytest.mark.parametrize(
    ("data", "code", "line"),
    [
        pytest.param(f"\\c 1\n\\v 1 {PAYLOAD}\n".encode(), "usfm_missing_id", 1, id="missing-id"),
        pytest.param(
            f"\\id RUT\n\\v 1 {PAYLOAD}\n".encode(), "usfm_verse_before_chapter", 2, id="verse"
        ),
        pytest.param(
            f"\\id RUT\n\\c 1\n\\v 1 a\\f + \\ft {PAYLOAD}\n\\v 2 b\n".encode(),
            "usfm_unclosed_note",
            4,
            id="unclosed-note",
        ),
        pytest.param(
            f"\\id RUT\r\\c 1\r\\v 1 a\\f + \\ft {PAYLOAD}\r\\v 2 b\n".encode(),
            "usfm_unclosed_note",
            4,
            id="unclosed-note-after-cr",
        ),
        pytest.param(
            f"\\id RUT\n\\c {PAYLOAD}\n".encode(), "usfm_bad_chapter", 2, id="bad-chapter"
        ),
        pytest.param(
            f"\\id RUT\n\\c 1\n\\v 1a-b {PAYLOAD}\n".encode(), "usfm_bad_verse", 3, id="bad-verse"
        ),
        pytest.param(
            b"\\id RUT\n\\c 1\n\\v 1 \xff" + PAYLOAD.encode() + b"\n",
            "decode_error",
            3,
            id="decode-error",
        ),
        pytest.param(
            b"\\id RUT\r\\c 1\r\\v 1 \xff" + PAYLOAD.encode() + b"\n",
            "decode_error",
            3,
            id="decode-error-after-lone-cr",
        ),
        pytest.param(
            b"\\id RUT\r\n\\c 1\r\n\\v 1 \xff" + PAYLOAD.encode() + b"\n",
            "decode_error",
            3,
            id="decode-error-after-crlf",
        ),
    ],
)
def test_usfm_errors_have_line_numbers_and_no_text(data: bytes, code: str, line: int) -> None:
    with pytest.raises(ExtractionFailed) as excinfo:
        UsfmExtractor().extract(data, _ctx())

    assert excinfo.value.code == code
    assert excinfo.value.line == line
    assert excinfo.value.source_object_id == "obj-test"
    assert PAYLOAD not in str(excinfo.value)


# ----- text conservation: independent oracle over generated simple USFM ----------------------
#
# Each generator returns the USFM fragment together with an ordered list of events describing
# what the text should become. The oracle below consumes only those events (never parser output):
# "keep" appends already-transformed text, "flush" ends the current verse/unknown piece,
# "note" emits a footnote unit, "count" records a skipped/unknown counter. Expected unit texts
# are therefore fixed in document order, including NBSP from "~", removed "//", and the notes.

_Event = tuple[Any, ...]
_Frag = tuple[str, list[_Event]]

_TEXT_CHARS = "abcdeKLMé\u0301ŋñ .,;:!?'\"()-0123456789\u00a0"  # no \ ~ / * + | or line breaks
_CHAR_NAMES = ("add", "nd", "bd", "it")
_UNKNOWN_NAMES = ("zq", "zr")
_SKIP_STATS = frozenset({"xref_notes", "figures", "inline_refs"})


@st.composite
def _plain_text(draw: st.DrawFn) -> str:
    return draw(st.text(alphabet=_TEXT_CHARS, min_size=1, max_size=4))


@st.composite
def _simple(draw: st.DrawFn, depth: int) -> _Frag:
    kinds = ["text", "tilde", "break", "newline"]
    if depth < 2:
        kinds.append("char")
    kind = draw(st.sampled_from(kinds))
    if kind == "text":
        text = draw(_plain_text())
        return text, [("keep", text)]
    if kind == "tilde":
        return "~", [("keep", "\u00a0")]
    if kind == "break":
        return "//", [("keep", "")]
    if kind == "newline":
        return "\nk", [("keep", " "), ("keep", "k")]
    name = draw(st.sampled_from(_CHAR_NAMES))
    marker = ("+" if draw(st.booleans()) else "") + name
    inner, events = draw(_seq(depth + 1))
    return f"\\{marker} {inner}\\{marker}*", [("keep", " "), *events]


@st.composite
def _seq(draw: st.DrawFn, depth: int) -> _Frag:
    frags = draw(st.lists(_simple(depth), max_size=4))
    return "".join(text for text, _ in frags), [e for _, events in frags for e in events]


@st.composite
def _body_item(draw: st.DrawFn) -> _Frag:
    kind = draw(st.sampled_from(["simple", "note", "para", "xref", "fig", "rq", "unknown"]))
    if kind == "simple":
        return draw(_simple(0))
    if kind == "note":
        inner, events = draw(_seq(1))
        return f"\\f + \\ft {inner}\\f*", [("note", events)]
    if kind == "para":
        return "\n\\p\nk", [("keep", " "), ("flush",), ("keep", " "), ("keep", "k")]
    if kind == "xref":
        skipped = draw(_plain_text())
        return f"\\x - \\xt {skipped}\\x*", [("count", "xref_notes", 1), ("flush",)]
    if kind == "fig":
        caption = draw(_plain_text())
        return f'\\fig {caption}|src="a.jpg"\\fig*', [("count", "figures", 1)]
    if kind == "rq":
        return "\\rq (ref)\\rq*", [("count", "inline_refs", 1)]
    name = draw(st.sampled_from(_UNKNOWN_NAMES))
    inner, events = draw(_seq(1))
    counted = ("count", f"unknown_marker:{name}", 2)
    return f"\\{name} {inner}\\{name}*", [counted, ("keep", " "), *events]


@st.composite
def _verse(draw: st.DrawFn, number: int) -> _Frag:
    body = draw(st.lists(_body_item(), max_size=6))
    usfm = f"\n\\v {number} " + "".join(text for text, _ in body)
    events: list[_Event] = [("keep", " "), ("flush",), ("keep", " ")]
    events += [event for _, body_events in body for event in body_events]
    if draw(st.booleans()):  # a line-start unknown block ends the verse; it runs to the next \v
        inner, inner_events = draw(_seq(1))
        usfm += f"\n\\zb {inner}"
        events += [("keep", " "), ("flush",), ("keep", " "), ("count", "unknown_marker:zb", 1)]
        events += inner_events
    return usfm, events


@st.composite
def _document(draw: st.DrawFn) -> tuple[str, list[_Event]]:
    usfm = "\\id RUT\n\\c 1"
    events: list[_Event] = []
    for number in range(1, draw(st.integers(min_value=0, max_value=4)) + 1):
        verse_usfm, verse_events = draw(_verse(number))
        usfm += verse_usfm
        events += verse_events
    events.append(("flush",))
    return usfm + "\n", events


def _oracle(events: list[_Event]) -> tuple[list[str], Counter[str]]:
    texts: list[str] = []
    counts: Counter[str] = Counter()
    pending: list[str] = []

    def flush() -> None:
        text = "".join(pending).strip()
        pending.clear()
        if text:
            texts.append(text)

    for event in events:
        if event[0] == "keep":
            pending.append(event[1])
        elif event[0] == "count":
            counts[event[1]] += event[2]
        elif event[0] == "flush":
            flush()
        elif event[0] == "note":
            flush()
            note: list[str] = []
            for inner in event[1]:
                if inner[0] == "keep":
                    note.append(inner[1])
                else:
                    counts[inner[1]] += inner[2]
            text = "".join(note).strip()
            if text:
                texts.append(text)
    return texts, counts


@given(_document())
def test_usfm_text_conservation(document: tuple[str, list[_Event]]) -> None:
    usfm, events = document
    expected_texts, expected_counts = _oracle(events)

    out = _run(usfm)

    assert [u.raw_text for u in out.units] == expected_texts
    observed = {
        key: value
        for key, value in out.stats.items()
        if key in _SKIP_STATS or key.startswith("unknown_marker:")
    }
    assert observed == dict(expected_counts)


def test_usfm_extraction_is_deterministic() -> None:
    data = FIXTURE.read_bytes()

    assert UsfmExtractor().extract(data, _ctx()) == UsfmExtractor().extract(data, _ctx())


def test_usfm_registered_as_versioned_extractor() -> None:
    extractor = EXTRACTORS.get("usfm@0.1.0")

    assert isinstance(extractor, UsfmExtractor)
    assert EXTRACTORS.get("usfm") is extractor
    assert UsfmExtractor.name == "usfm"
    assert UsfmExtractor.version == "0.1.0"
