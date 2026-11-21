"""WP5.6 unit tests: Toolbox reader `toolbox_igt@0.1.0` and the IGT registry.

Contracts under test (WP5.6, M5-PLAN §7.6 + gate 35 review focus):
- strict UTF-8 via `extraction.base.decode_utf8`; byte failure raises
  `ExtractionFailed("decode_error", ...)` and never leaks content;
- records start at ``\\ref``; every line before it is header; every input line
  is preserved verbatim (marker, 1-based line number, raw) in exactly one
  record's tiers or the header;
- the golden fixture's ``\\t``/``\\m``/``\\g``/``\\f`` records parse into words,
  morphs and glosses aligned word-by-word and morph-by-morph;
- count mismatch keeps the word and marks the record ``tier_mismatch``; a
  missing text tier is ``missing_tier``; per-record problems never fail the
  document;
- unknown markers are preserved verbatim and counted ``unknown_marker:<m>``;
- Hypothesis: arbitrary marker/line soup never raises and accounts for every
  line;
- registry: both readers registered under ``name@version`` and media-type
  resolution.
"""

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from langpipe.domain.enums import IgtFormat
from langpipe.domain.errors import ExtractionFailed
from langpipe.domain.models.igt import IgtMorph
from langpipe.extraction.base import split_lines
from langpipe.igt.base import split_at_boundary_marks
from langpipe.igt.registry import IGT_READERS, reader_for_media_type
from langpipe.igt.toolbox import ToolboxIgtReader
from langpipe.languages.base import MorphologyProfile

REPO = Path(__file__).resolve().parents[2]
GOLDEN_IGT = REPO / "tests" / "golden" / "fixture" / "sources" / "04-igt" / "igt.txt"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "igt"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _lines(data: bytes) -> list[str]:
    return split_lines(data.decode("utf-8"))


def test_golden_fixture_records_parse_fully() -> None:
    document = ToolboxIgtReader().read(GOLDEN_IGT.read_bytes())
    assert document.format is IgtFormat.TOOLBOX
    assert document.header == []
    assert document.stats["records"] == 2
    assert document.stats["ok"] == 2

    first = document.records[0]
    assert first.record_ref == "IGT-1"
    assert first.parse_status.value == "ok"
    assert first.diagnostics == []
    assert [(word.text, word.ordinal) for word in first.words] == [
        ("mabi-ki", 0),
        ("nawa", 1),
        ("wesa", 2),
    ]
    morphs = first.words[0].morphs
    assert [(morph.text, morph.boundary_before, morph.gloss) for morph in morphs] == [
        ("mabi", None, "canoa"),
        ("ki", "-", "ERG"),
    ]
    assert [(m.text, m.gloss) for m in first.words[1].morphs] == [("nawa", "rio")]
    assert first.words[2].morphs[0].gloss == "ir.PST"  # kept verbatim, unsplit
    assert first.translations == {"und": ["A canoa foi ao rio."]}
    # The blank separator line between records is itself proof of an open
    # record's tail: preserved verbatim as an unmarked continuation tier line.
    assert [(tier.marker, tier.line_number) for tier in first.tiers] == [
        ("\\ref", 1),
        ("\\t", 2),
        ("\\m", 3),
        ("\\g", 4),
        ("\\f", 5),
        ("", 6),
    ]
    assert [tier.raw for tier in first.tiers] == [
        "\\ref IGT-1",
        "\\t mabi-ki nawa wesa",
        "\\m mabi-ki nawa wesa",
        "\\g canoa-ERG rio ir.PST",
        "\\f A canoa foi ao rio.",
        "",
    ]
    assert first.locator == {"line_start": 1, "line_end": 6, "ref": "IGT-1"}

    second = document.records[1]
    assert second.record_ref == "IGT-2"
    assert [
        (morph.text, morph.boundary_before, morph.gloss) for morph in second.words[0].morphs
    ] == [("wesa", None, "ir"), ("ra", "-", "NEG")]
    assert second.translations == {"und": ["não foi"]}


def test_sample_fixture_header_unknown_marker_and_mismatch() -> None:
    data = _read("toolbox_sample.txt")
    document = ToolboxIgtReader().read(data)
    lines = _lines(data)
    assert document.header == lines[:3]  # verbatim, not parsed
    assert len(document.records) == 4
    assert document.stats["unknown_marker:\\x"] == 1

    third = document.records[2]
    assert third.record_ref == "IGT-3"
    assert [(m.text, m.gloss) for m in third.words[0].morphs] == [
        ("akwã", "falls"),
        ("ra", "NEG"),
    ]
    # A foreign marker is preserved verbatim with its continuation line; the
    # blank separator line after it is part of this record too.
    assert [(tier.marker, tier.raw) for tier in third.tiers][-3:] == [
        ("\\x", "\\x foreign-extra"),
        ("", "unknown tier continuation"),
        ("", ""),
    ]

    fourth = document.records[3]
    assert fourth.record_ref == "IGT-4"
    # One extra gloss word ("?") breaks the word-by-word alignment: the word is
    # kept, but no gloss is assigned from a misaligned gloss tier (evidence
    # stays verbatim in the tiers; the record reports the mismatch).
    assert fourth.parse_status.value == "tier_mismatch"
    assert fourth.diagnostics == ["tier_mismatch"]
    assert [
        (morph.text, morph.boundary_before, morph.gloss) for morph in fourth.words[0].morphs
    ] == [
        ("aka", None, None),
        ("ra", "-", None),
        ("ra", "-", None),
    ]


def test_mismatch_fixture_signals_and_keeps_words() -> None:
    document = ToolboxIgtReader().read(_read("toolbox_mismatch.txt"))
    record = document.records[0]
    assert record.parse_status.value == "tier_mismatch"
    assert record.diagnostics == ["tier_mismatch"]
    assert [word.text for word in record.words] == ["mabi-ki", "nawa"]
    assert all(morph.gloss is None for word in record.words for morph in word.morphs)


def test_missing_text_tier_is_reported_never_raised() -> None:
    document = ToolboxIgtReader().read(_read("toolbox_missing_text.txt"))
    record = document.records[0]
    assert record.parse_status.value == "missing_tier"
    assert record.diagnostics == ["missing_tier"]
    assert record.words == []
    assert [tier.marker for tier in record.tiers] == ["\\ref", "\\m", "\\g"]
    assert document.stats["records"] == 1


def test_empty_record_still_missing_tier_but_translations_parsed() -> None:
    document = ToolboxIgtReader().read(b"\\ref IGT-1\n\\f por: nota\n")
    record = document.records[0]
    assert record.record_ref == "IGT-1"
    assert record.parse_status.value == "missing_tier"
    assert record.translations == {"por": ["nota"]}


def test_header_only_file_has_no_records() -> None:
    document = ToolboxIgtReader().read(b"\\id nothing\nstill no ref\n")
    assert document.records == []
    assert document.stats["records"] == 0
    assert document.stats["header_lines"] == 2


def test_invalid_utf8_raises_decode_error_without_content() -> None:
    for bad in (b"\\ref x \\t mabi \xff", b"\xff\xfe \\ref"):
        with pytest.raises(ExtractionFailed) as excinfo:
            ToolboxIgtReader().read(bad)
        assert excinfo.value.code == "decode_error"
        assert str(excinfo.value) == (
            "extraction failed: code=decode_error source_object=unknown line=none"
        )
        assert "mabi" not in str(excinfo.value)


def test_ctx_source_object_id_addresses_decode_failure() -> None:
    class Ctx:
        source_object_id = "so_1234567890123456789012345"

    with pytest.raises(ExtractionFailed) as excinfo:
        ToolboxIgtReader().read(b"\xff", Ctx())
    assert "so_1234567890123456789012345" in str(excinfo.value)
    assert "mabi" not in str(excinfo.value)


def test_repeated_bundles_concatenate_in_order() -> None:
    text = (
        "\\ref R1\n"
        "\\t mabi-ki\n"
        "\\m mabi-ki\n"
        "\\g canoa-ERG\n"
        "\\t nawa\n"
        "\\m nawa\n"
        "\\g rio\n"
        "\\f por: uma\n"
        "\\f por: duas\n"
    )
    document = ToolboxIgtReader().read(text.encode("utf-8"))
    record = document.records[0]
    assert record.parse_status.value == "ok"
    assert [word.text for word in record.words] == ["mabi-ki", "nawa"]
    assert [(m.text, m.gloss) for m in record.words[0].morphs] == [
        ("mabi", "canoa"),
        ("ki", "ERG"),
    ]
    assert record.translations == {"por": ["uma", "duas"]}


def test_continuation_lines_extend_the_previous_tier() -> None:
    text = "\\ref R1\n\\t mabi-\nki\n\\m mabi-\nki\n\\g eye-\nLOC\n"
    document = ToolboxIgtReader().read(text.encode("utf-8"))
    record = document.records[0]
    assert [word.text for word in record.words] == ["mabi-", "ki"]
    assert [(m.text, m.gloss) for m in record.words[0].morphs] == [("mabi", "eye")]
    assert [(m.text, m.gloss) for m in record.words[1].morphs] == [("ki", "LOC")]


def test_wrapped_translation_continuation_concatenates() -> None:
    text = "\\ref R1\n\\t a-b\n\\f por: uma frase\nmuito longa\n"
    document = ToolboxIgtReader().read(text.encode("utf-8"))
    record = document.records[0]
    assert record.translations == {"por": ["uma frase muito longa"]}


def test_titlecase_sentence_starter_does_not_invent_language() -> None:
    text = "\\ref R1\n\\t a-b\n\\f Ora: pois entao\n"
    document = ToolboxIgtReader().read(text.encode("utf-8"))
    record = document.records[0]
    assert record.translations == {"und": ["Ora: pois entao"]}


def test_unknown_markers_summed_across_multiple_records() -> None:
    text = "\\ref R1\n\\x one\n\\ref R2\n\\x two\n"
    document = ToolboxIgtReader().read(text.encode("utf-8"))
    assert document.stats["unknown_marker:\\x"] == 2


def test_profile_supplies_custom_markers() -> None:
    profile = MorphologyProfile(
        toolbox_markers={
            "text": ("\\TXT",),
            "morphs": ("\\MORF",),
            "glosses": ("\\GLO",),
        },
    )
    text = "\\ref R1\n\\TXT mabi-ki\n\\MORF mabi-ki\n\\GLO canoa-ERG\n"
    document = ToolboxIgtReader().read(text.encode("utf-8"), profile=profile)
    record = document.records[0]
    assert record.parse_status.value == "ok"
    assert [(m.text, m.gloss) for m in record.words[0].morphs] == [
        ("mabi", "canoa"),
        ("ki", "ERG"),
    ]


def test_default_profile_knows_tx_marker() -> None:
    document = ToolboxIgtReader().read(b"\\ref R1\n\\tx mabi-ki\n")
    known = [key for key in document.stats if key.startswith("unknown_marker:")]
    assert known == []


_SOUP_PIECES = (
    "\\ref IGT-x",
    "\\ref",
    "\\ref token",
    "\\t mabi-ki",
    "\\t x-y",
    "\\m x-y",
    "\\m",
    "\\g A-B",
    "\\g ***",
    "\\g",
    "\\f por: A canoa.",
    "\\ft sem marca",
    "\\tx mabi-ki",
    "\\zz desconhecido",
    "\\unknown extra",
    "continu",
    "",
    " ",
    "12:34",
    "😀 até",
    "\\data 2026-01-01",
)

_SOUP_STRATEGY = st.lists(st.sampled_from(_SOUP_PIECES), max_size=24)


def _assert_soup_invariants(lines: list[str], document: object) -> None:
    total = len(split_lines("\n".join(lines)))
    assert (
        document.stats["header_lines"] + sum(len(record.tiers) for record in document.records)
        == total
    )
    inputs = set(lines)
    for ordinal, record in enumerate(document.records):
        assert record.format is IgtFormat.TOOLBOX
        assert record.record_ordinal == ordinal
        assert record.parse_status.value in {"ok", "tier_mismatch", "missing_tier", "unparsed"}
        for tier in record.tiers:
            assert tier.raw in inputs
            assert tier.line_number >= 1


@settings(suppress_health_check=[HealthCheck.too_slow])
@given(lines=_SOUP_STRATEGY)
def test_line_soup_never_raises_and_accounts_every_line(lines: list[str]) -> None:
    document = ToolboxIgtReader().read("\n".join(lines).encode("utf-8"))
    _assert_soup_invariants(lines, document)


@settings(suppress_health_check=[HealthCheck.too_slow])
@given(lines=_SOUP_STRATEGY)
def test_line_soup_absorbs_crlf_and_bom(lines: list[str]) -> None:
    data = b"\xef\xbb\xbf" + "\r\n".join(lines).encode("utf-8")
    document = ToolboxIgtReader().read(data)
    total = len(split_lines("\n".join(lines)))
    assert (
        document.stats["header_lines"] + sum(len(record.tiers) for record in document.records)
        == total
    )
    assert document.stats["bom_removed"] == 1
    assert document.stats.get("crlf_lines", 0) == max(0, len(lines) - 1)


def test_split_boundary_marks_helper_contracts() -> None:
    assert split_at_boundary_marks("mabi-ki", ("-", "=")) == [("mabi", None), ("ki", "-")]
    assert split_at_boundary_marks("=ki", ("-", "=")) == [("ki", "=")]
    assert split_at_boundary_marks("mabi--ki", ("-", "=")) == [("mabi", None), ("ki", "-")]
    assert split_at_boundary_marks("nawa", ("-", "=")) == [("nawa", None)]
    # A non-recordable profile mark (e.g. "·") still segments but cannot be
    # recorded into `IgtMorph.boundary_before` (models/igt.py:23).
    assert split_at_boundary_marks("a·b", ("-", "=", "·")) == [("a", None), ("b", None)]
    with pytest.raises(ValidationError):
        IgtMorph(ordinal=0, text="a", boundary_before="x")


def test_registry_resolves_readers_and_media_types() -> None:
    assert IGT_READERS.names() == ["toolbox_igt@0.1.0", "xigt_xml@0.1.0"]
    assert IGT_READERS.get("toolbox_igt").version == "0.1.0"
    assert IGT_READERS.get("xigt_xml").version == "0.1.0"
    assert reader_for_media_type("text/plain") == "toolbox_igt@0.1.0"
    assert reader_for_media_type("text/plain; charset=utf-8") == "toolbox_igt@0.1.0"
    assert reader_for_media_type("APPLICATION/XML") == "xigt_xml@0.1.0"
    assert reader_for_media_type("application/xigt+xml") == "xigt_xml@0.1.0"
    assert reader_for_media_type("text/csv") is None
