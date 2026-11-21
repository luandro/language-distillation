"""WP5.6 unit tests: Xigt XML reader `xigt_xml@0.1.0` and the round-trip.

Contracts under test (WP5.6, M5-PLAN §7.6, gate 35 review focus):
- pre-parse hardening: byte-size cap and refusal of ``<!DOCTYPE``/``<!ENTITY``
  (case-insensitive) raise `ExtractionFailed` before any XML machinery runs;
- the sample fixture parses words, morphemes (segmentation → words), glosses
  (alignment → morphemes, content by `content` reference) and translations;
- every tier item is synthesized as an `IgtTierLine` ``marker="xigt:<type>"``,
  including unknown tier types (kept as evidence);
- unsupported or malformed per-record structures yield
  `IgtParseStatus.UNPARSED` plus a fixed diagnostic, and never crash;
- wholly malformed XML raises `ExtractionFailed("xml_malformed", ...)`;
- invalid UTF-8 raises `ExtractionFailed("decode_error", ...)`; no error
  message carries source content;
- round-trip: toolbox → IgtDocument → `write_xigt_xml` → xigt reader →
  IgtDocument, equal on the parsed layer for records that parsed ``ok``.
"""

import io
from pathlib import Path

import pytest

import langpipe.igt.xigt as xigt_module
from langpipe.domain.enums import IgtFormat
from langpipe.domain.errors import ExtractionFailed
from langpipe.igt.registry import IGT_READERS
from langpipe.igt.toolbox import ToolboxIgtReader
from langpipe.igt.xigt import XigtXmlReader, write_xigt_xml

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "igt"
SAMPLE = FIXTURES / "sample.xigt.xml"
UNSUPPORTED = FIXTURES / "unsupported.xigt.xml"
TOOLBOX = FIXTURES / "toolbox_sample.txt"


def _read(path: Path) -> bytes:
    return path.read_bytes()


def test_sample_fixture_parses_all_four_roles() -> None:
    document = XigtXmlReader().read(_read(SAMPLE))
    assert document.format is IgtFormat.XIGT
    assert document.stats["records"] == 1
    assert document.stats["ok"] == 1

    record = document.records[0]
    assert record.record_ref == "i1"
    assert record.parse_status.value == "ok"
    assert record.diagnostics == []
    # gloss g2 has no own text: its `content` reference resolves to g1 ("canoa")
    assert word_layer(record.words) == [
        ("mabi-ki", [("mabi", None, "canoa"), ("ki", "-", "canoa")]),
        ("nawa", [("nawa", None, "rio")]),
    ]
    assert record.translations == {"por": ["A canoa foi ao rio."]}
    assert [(tier.marker, tier.line_number, tier.raw) for tier in record.tiers] == [
        ("xigt:words", 1, "mabi-ki"),
        ("xigt:words", 2, "nawa"),
        ("xigt:morphemes", 1, "mabi"),
        ("xigt:morphemes", 2, "ki"),
        ("xigt:morphemes", 3, "nawa"),
        ("xigt:glosses", 1, "canoa"),
        ("xigt:glosses", 2, "canoa"),
        ("xigt:glosses", 3, "rio"),
        ("xigt:translations", 1, "A canoa foi ao rio."),
    ]
    assert record.locator == {"igt_ordinal": 0, "id": "i1"}


def test_unsupported_structures_flag_the_record_never_crash() -> None:
    document = XigtXmlReader().read(_read(UNSUPPORTED))
    record = document.records[0]
    assert record.parse_status.value == "unparsed"
    assert set(record.diagnostics) == {
        "unknown_tier_type",
        "unknown_tier_ref",
        "dangling_item_ref",
    }
    assert document.stats["records"] == 1
    assert document.stats["unparsed"] == 1
    # The foreign tier survives as verbatim evidence, with its `content` reference
    # resolved against the words tier.
    odin = [tier for tier in record.tiers if tier.marker == "xigt:odin-source-tag"]
    assert [(tier.line_number, tier.raw) for tier in odin] == [(1, "nawa")]
    # The words tier still yielded its word; no crash, no silent failure.
    assert word_layer(record.words) == [("nawa", [("nawa", None, None)])]


def test_missing_words_tier_is_reported() -> None:
    data = (
        b"<xigt-corpus><igt id='i1'>"
        b"<tier id='tt' type='translations'><item xml:lang='por'>x</item></tier>"
        b"</igt></xigt-corpus>"
    )
    document = XigtXmlReader().read(data)
    record = document.records[0]
    assert record.parse_status.value == "unparsed"
    assert record.diagnostics == ["missing_words_tier"]
    assert record.words == []


def test_unknown_root_element_raises_typed_malformed() -> None:
    for bad in (b"<foo></foo>", b"<not-a-corpus><igt/></not-a-corpus>"):
        with pytest.raises(ExtractionFailed) as excinfo:
            XigtXmlReader().read(bad)
        assert excinfo.value.code == "xml_malformed"


def test_malformed_xml_raises_without_content() -> None:
    blob = b"<xigt-corpus><igt><item>nawa"
    with pytest.raises(ExtractionFailed) as excinfo:
        XigtXmlReader().read(blob)
    assert excinfo.value.code == "xml_malformed"
    assert "nawa" not in str(excinfo.value)


def test_doctype_and_entity_are_refused_case_insensitively() -> None:
    blob = (
        b"<!DOCTYPE xigt-corpus [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]>"
        b"<xigt-corpus>&xxe;</xigt-corpus>"
    )
    with pytest.raises(ExtractionFailed) as excinfo:
        XigtXmlReader().read(blob)
    assert excinfo.value.code == "xml_entity_expansion_refused"
    with pytest.raises(ExtractionFailed) as lowercase:
        XigtXmlReader().read(b"<xigt-corpus><!-- <!entity clause -->></xigt-corpus>")
    assert lowercase.value.code == "xml_entity_expansion_refused"


def test_entity_refusal_alone_is_refused() -> None:
    with pytest.raises(ExtractionFailed) as excinfo:
        XigtXmlReader().read(b"<xigt-corpus><!-- <!ENTITY note -->></xigt-corpus>")
    assert excinfo.value.code == "xml_entity_expansion_refused"


def test_byte_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xigt_module, "MAX_XIGT_BYTES", 8)
    with pytest.raises(ExtractionFailed) as excinfo:
        XigtXmlReader().read(b"<xigt-corpus></xigt-corpus>")
    assert excinfo.value.code == "xml_too_large"


def test_invalid_utf8_raises_decode_error() -> None:
    with pytest.raises(ExtractionFailed) as excinfo:
        XigtXmlReader().read(b"<xigt-corpus> \xff </xigt-corpus>")
    assert excinfo.value.code == "decode_error"
    assert "nawa" not in str(excinfo.value)


def test_ctx_addresses_errors_by_identifier() -> None:
    class Ctx:
        source_object_id = "so_1234567890123456789012345"

    with pytest.raises(ExtractionFailed) as excinfo:
        XigtXmlReader().read(b"<nope/>", Ctx())
    assert "so_1234567890123456789012345" in str(excinfo.value)


def test_translations_without_lang_key_land_under_und() -> None:
    data = (
        b"<xigt-corpus><igt>"
        b"<tier id='tw' type='words'><item id='w1'>nawa</item></tier>"
        b"<tier id='tt' type='translations'><item>x</item></tier>"
        b"</igt></xigt-corpus>"
    )
    document = XigtXmlReader().read(data)
    record = document.records[0]
    assert record.words[0].text == "nawa"  # word item without a morphemes tier
    assert record.translations == {"und": ["x"]}


def test_translation_lang_normalized_to_iso_639_3() -> None:
    data = (
        b"<xigt-corpus><igt>"
        b"<tier id='tw' type='words'><item id='w1'>nawa</item></tier>"
        b"<tier id='tt' type='translations'><item xml:lang='pt-BR'>A canoa</item></tier>"
        b"</igt></xigt-corpus>"
    )
    document = XigtXmlReader().read(data)
    assert document.records[0].translations == {"por": ["A canoa"]}


def test_xml_declaration_encoding_does_not_corrupt_utf8() -> None:
    doc = (
        '<?xml version="1.0" encoding="ISO-8859-1"?><xigt-corpus><igt id="i1">'
        '<tier id="tw" type="words"><item id="w1">akwã</item></tier>'
        '<tier id="tt" type="translations"><item xml:lang="por">A canção</item></tier>'
        "</igt></xigt-corpus>"
    ).encode()
    document = XigtXmlReader().read(doc)
    record = document.records[0]
    assert record.words[0].text == "akwã"
    assert record.translations == {"por": ["A canção"]}


def test_v1_style_one_letter_tier_aliases() -> None:
    data = (
        b"<xigt-corpus><igt id='i1'>"
        b"<tier id='tw' type='tx'><item id='w1'>mabi-ki</item></tier>"
        b"<tier id='tm' type='mb' segmentation='tw'><item id='m1' segmentation='w1'>mabi</item>"
        b"<item id='m2' segmentation='w1'>ki</item></tier>"
        b"<tier id='tg' type='ge' alignment='tm'><item id='g1' alignment='m1'>canoa</item>"
        b"<item id='g2' alignment='m2'>ERG</item></tier>"
        b"<tier id='tt' type='ft'><item xml:lang='por'>A canoa!</item></tier>"
        b"</igt></xigt-corpus>"
    )
    document = XigtXmlReader().read(data)
    record = document.records[0]
    assert record.parse_status.value == "ok"
    assert word_layer(record.words) == [("mabi-ki", [("mabi", None, "canoa"), ("ki", "-", "ERG")])]
    assert [tier.marker for tier in record.tiers][:2] == ["xigt:tx", "xigt:mb"]


def word_layer(words: list) -> list:
    return [
        (
            word.text,
            [(morph.text, morph.boundary_before, morph.gloss) for morph in word.morphs],
        )
        for word in words
    ]


def test_roundtrip_toolbox_to_xigt_preserves_parsed_layer() -> None:
    toolbox_document = ToolboxIgtReader().read(_read(TOOLBOX))
    xml = write_xigt_xml(toolbox_document)
    assert isinstance(xml, str)
    xigt_document = XigtXmlReader().read(xml.encode("utf-8"))

    for toolbox_record, xigt_record in zip(
        toolbox_document.records, xigt_document.records, strict=True
    ):
        assert xigt_record.format is IgtFormat.XIGT
        assert xigt_record.record_ref == toolbox_record.record_ref
        assert xigt_record.translations == toolbox_record.translations
        if toolbox_record.parse_status.value != "ok":
            # Only the parsed layer of `ok` records is round-trip equal; degraded
            # records keep their diagnostics in the toolbox document while the
            # xigt materialization re-derives what was actually serialized.
            continue
        assert xigt_record.parse_status.value == "ok"
        assert xigt_record.diagnostics == toolbox_record.diagnostics == []
        assert word_layer(xigt_record.words) == word_layer(toolbox_record.words)
    # ordinal mapping survives the materialization too
    assert [r.record_ref for r in xigt_document.records] == [
        r.record_ref for r in toolbox_document.records
    ]


def test_writer_output_is_parseable_stdlib_and_balanced() -> None:
    import xml.etree.ElementTree as ET

    toolbox_document = ToolboxIgtReader().read(_read(TOOLBOX))
    root = ET.parse(io.StringIO(write_xigt_xml(toolbox_document))).getroot()
    assert root.tag == "xigt-corpus"
    igt_ids = {igt.get("id") for igt in root.findall("igt")}
    assert igt_ids == {"IGT-1", "IGT-2", "IGT-3", "IGT-4"}
    # Every tier/item id pair needed by the reader is present and unique.
    all_ids = {element.get("id") for element in root.iter() if element.get("id")}
    referenced = {element.get("segmentation") for element in root.iter()} | {
        element.get("alignment") for element in root.iter()
    }
    assert referenced - {None} <= all_ids


def test_registry_lists_both_readers() -> None:
    assert "xigt_xml@0.1.0" in IGT_READERS.names()
    assert "toolbox_igt@0.1.0" in IGT_READERS.names()
