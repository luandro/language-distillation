"""Unit tests for multi-format lexicographical exporters (WP 1.4)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from langpipe.lexicon.exporters.cldf import CldfDictionaryExporter
from langpipe.lexicon.exporters.lift import LiftExporter
from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter


def test_lift_exporter(tmp_path: Path):
    mock_entries = [
        {
            "headword": "vaki",
            "pos": "noun",
            "glosses_por": ["menino", "criança"],
            "semantics": {"primary_domain": "kinship_social", "valence": "non_verbal"},
            "citations": [
                {
                    "source_text": "vaki ka-ai",
                    "reference_text": "o menino vai",
                    "source_ref": "GEN 1:1",
                }
            ],
        }
    ]

    out_file = tmp_path / "test.lift"
    LiftExporter(target_lang="test", contact_lang="por").export(mock_entries, out_file)

    assert out_file.exists()
    tree = ET.parse(out_file)
    root = tree.getroot()
    assert root.tag == "lift"
    assert root.attrib["version"] == "0.13"

    entry = root.find("entry")
    assert entry is not None
    assert entry.attrib["id"] == "test_vaki"

    lex_text = entry.find(".//lexical-unit/form/text")
    assert lex_text is not None and lex_text.text == "vaki"

    gloss_text = entry.find(".//sense/gloss/text")
    assert gloss_text is not None and "menino" in gloss_text.text

    example = entry.find(".//sense/example")
    assert example is not None
    assert example.find(".//form/text").text == "vaki ka-ai"


def test_cldf_exporter(tmp_path: Path):
    mock_entries = [
        {
            "headword": "oya",
            "pos": "verb",
            "glosses_por": ["ver"],
            "semantics": {"primary_domain": "perception_mind", "valence": "transitive"},
            "citations": [],
        }
    ]

    exporter = CldfDictionaryExporter(target_lang="test", contact_lang="por")
    files = exporter.export(mock_entries, tmp_path)
    assert len(files) == 4
    assert (tmp_path / "entries.csv").exists()
    assert (tmp_path / "senses.csv").exists()
    assert (tmp_path / "examples.csv").exists()
    assert (tmp_path / "Dictionary-metadata.json").exists()


def test_printable_exporter(tmp_path: Path):
    mock_entries = [
        {
            "headword": "waka",
            "pos": "s.",
            "glosses_por": ["água", "rio"],
            "semantics": {"primary_domain": "universe_nature"},
            "citations": [
                {
                    "source_text": "waka ura-ka",
                    "reference_text": "o rio é longe",
                    "source_ref": "SOUT 1:2",
                }
            ],
        }
    ]

    out_file = tmp_path / "test_book.html"
    PrintableDictionaryExporter(
        target_lang="test",
        target_name="TestLang",
        contact_lang="por",
        contact_name="Português",
    ).export(mock_entries, out_file)

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "waka" in content
    assert "água" in content
    assert "universe_nature" in content
    assert "waka ura-ka" in content


def test_printable_exporter_uses_charis_and_guide_words(tmp_path: Path):
    from langpipe.lexicon.dictionary.session import DictionarySessionBuilder

    entries = [
        {
            "headword": "waka",
            "pos": "noun",
            "glosses_por": ["água", "rio"],
            "status": "validated",
            "provenance": "Costa (2002)",
            "audit": {
                "lexical_class": "lemma",
                "flags": [],
                "reasons": [],
                "related_entry": None,
                "use_scopes": ["grounding"],
            },
            "semantics": {
                "primary_domain": "universe_nature",
                "valence": "non_verbal",
                "inalienability": "not_applicable",
                "confidence": 0.9,
            },
            "citations": [
                {
                    "citation_id": "c1",
                    "source_ref": "GEN 1:1",
                    "target_text": "waka ura-ka",
                    "reference_text": "o rio é longe",
                    "matched_token": "waka",
                    "score": 1.5,
                },
            ],
        }
    ]
    session = DictionarySessionBuilder(target_lang="mzr", target_name="Marúbo").build(entries)

    out_file = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr",
        target_name="Marúbo",
        contact_lang="por",
        fonts_dir=Path(__file__).resolve().parents[2] / "assets" / "fonts",
    ).export(entries, out_file, session=session)

    content = out_file.read_text(encoding="utf-8")

    # Charis is the only typeface in the print path.
    assert "@font-face" in content
    assert "Charis" in content
    assert "Newsreader" not in content

    # Guide words must use the working WeasyPrint form.
    assert "string-set: gw content(text);" in content
    assert "string(gw, first)" in content
    assert "string(gw, last)" in content
    # The forms that were empirically proven broken must not reappear.
    assert "position: running(" not in content
    assert ":first-of-type" not in content
    # WeasyPrint 70 drops string-set on flex/grid items, so the headword row
    # must not be a flex container.
    assert "display: flex" not in content.split(".entry-head")[1][:200]

    # Cross-references and folios.
    assert "target-counter" in content
    assert "counter(page)" in content

    # Content.
    assert "waka" in content
    assert "água" in content
    assert "waka ura-ka" in content
    assert "GEN 1:1" in content

    # Front matter.
    assert "Prefácio" in content or "Preface" in content
    assert "Bibliografia" in content or "Bibliography" in content


def test_printable_exporter_buckets_letters_by_normalized_key(tmp_path: Path):
    entries = [
        {
            "headword": "ártemis",
            "pos": "noun",
            "glosses_por": ["artemis"],
            "status": "supported",
            "provenance": "Costa (2002)",
            "audit": {
                "lexical_class": "lemma",
                "flags": [],
                "reasons": [],
                "related_entry": None,
                "use_scopes": ["grounding"],
            },
            "semantics": {},
            "citations": [],
        },
        {
            "headword": "mama",
            "pos": "noun",
            "glosses_por": ["mãe"],
            "status": "supported",
            "provenance": "Costa (2002)",
            "audit": {
                "lexical_class": "lemma",
                "flags": [],
                "reasons": [],
                "related_entry": None,
                "use_scopes": ["grounding"],
            },
            "semantics": {},
            "citations": [],
        },
    ]
    out_file = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr",
        target_name="Marúbo",
        fonts_dir=tmp_path / "fonts",
    ).export(entries, out_file)

    content = out_file.read_text(encoding="utf-8")
    # The letter heading for A must exist, and no separate 'Á' heading.
    assert 'id="letter-A"' in content
    assert 'id="letter-Á"' not in content


def test_printable_exporter_numbers_bibliography_without_duplicates(tmp_path: Path):
    entries = [
        {
            "headword": "a",
            "pos": "noun",
            "glosses_por": ["x"],
            "status": "supported",
            "provenance": "Costa (2002); ex: a x",
            "audit": {
                "lexical_class": "lemma",
                "flags": [],
                "reasons": [],
                "related_entry": None,
                "use_scopes": ["grounding"],
            },
            "semantics": {},
            "citations": [],
        },
        {
            "headword": "b",
            "pos": "noun",
            "glosses_por": ["y"],
            "status": "supported",
            "provenance": "Costa (2002); ex: b x",
            "audit": {
                "lexical_class": "lemma",
                "flags": [],
                "reasons": [],
                "related_entry": None,
                "use_scopes": ["grounding"],
            },
            "semantics": {},
            "citations": [],
        },
    ]
    out_file = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr",
        target_name="Marúbo",
        fonts_dir=tmp_path / "fonts",
    ).export(entries, out_file)

    content = out_file.read_text(encoding="utf-8")
    # 'Costa (2002)' is cited twice but must be listed once.
    assert content.count("Costa (2002)") == 2, "one marker + one bibliography row"


def test_printable_exporter_uses_only_glyphs_present_in_charis(tmp_path: Path):
    """Every character the template can emit must exist in Charis SIL 7.000.

    A glyph missing from the font makes WeasyPrint fall back to DejaVu Serif,
    so the printed book silently becomes a two-typeface object. The defect is
    invisible in the HTML and only shows up in `pdffonts` on the rendered PDF.
    """
    fonts_dir = Path(__file__).resolve().parents[2] / "assets" / "fonts"
    if not (fonts_dir / "Charis-Regular.woff2").exists():
        import pytest

        pytest.skip("Charis webfonts are not vendored")

    from fontTools.ttLib import TTFont

    covered: set[int] = set()
    for face in ("Charis-Regular.woff2", "Charis-Bold.woff2", "Charis-Italic.woff2"):
        path = fonts_dir / face
        if path.exists():
            covered |= set(TTFont(path).getBestCmap())

    entries = [
        {
            "headword": "waka",
            "pos": "noun",
            "glosses_por": ["água"],
            "status": "candidate",
            "provenance": "Costa (2002)",
            "audit": {
                "lexical_class": "lemma",
                "flags": [],
                "reasons": [],
                "related_entry": None,
                "use_scopes": ["grounding"],
            },
            "semantics": {"primary_domain": "universe_nature"},
            "citations": [],
        }
    ]
    out_file = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr",
        target_name="Marúbo",
        fonts_dir=fonts_dir,
    ).export(entries, out_file)

    content = out_file.read_text(encoding="utf-8")
    # Strip the CSS block: it is authored text, not rendered content.
    body = re.sub(r"<style.*?</style>", " ", content, flags=re.DOTALL)
    body = re.sub(r"<[^>]+>", " ", body)

    missing = sorted({c for c in body if ord(c) not in covered and not c.isspace()})
    assert not missing, f"characters absent from Charis SIL 7.000: {missing}"


def test_printable_exporter_status_marks_are_distinct_and_in_charis(tmp_path: Path):
    """The three evidence markers must be distinct, and none may be a triangle.

    U+25B3 WHITE UP-POINTING TRIANGLE is not in Charis (it has no triangle at
    all), and U+2206 renders as a sigma, not a triangle, in this font.
    """
    from langpipe.lexicon.exporters.printable import STATUS_MARKS

    marks = STATUS_MARKS["validated"], STATUS_MARKS["supported"], STATUS_MARKS["candidate"]
    assert len(set(marks)) == 3, f"evidence markers are not distinct: {marks}"
    assert "△" not in marks, "U+25B3 is not in Charis; it forces a font fallback"


def test_printable_exporter_prints_inflected_forms_under_the_lemma():
    """A form hangs under its base and is never given a headword of its own (ADR-0027 D9).

    The shipped data has no attachable form yet (every audited base is a gloss-side name), so
    this rendering path would otherwise be unexercised until new data arrives.
    """
    exporter = PrintableDictionaryExporter(target_lang="mzr", target_name="Marúbo")
    html = exporter._render_entry(
        {
            "headword": "berequias",
            "pos": "noun",
            "glosses": ["Berequias"],
            "status": "supported",
            "forms": [{"surface": "berequiasnẽ", "pos": "noun", "clitic": "nẽ"}],
        },
        {},
        {},
        set(),
    )

    assert 'class="forms"' in html
    assert "Formas" in html
    assert "berequiasnẽ" in html
    assert "-nẽ" in html
    assert 'class="headword">berequiasnẽ' not in html


def test_printable_exporter_omits_the_forms_block_without_forms():
    exporter = PrintableDictionaryExporter(target_lang="mzr", target_name="Marúbo")
    html = exporter._render_entry(
        {
            "headword": "berequias",
            "pos": "noun",
            "glosses": ["Berequias"],
            "status": "supported",
        },
        {},
        {},
        set(),
    )

    assert 'class="forms"' not in html
    assert "Formas" not in html


def test_export_all_formats_includes_printable_pdf(tmp_path: Path):
    from langpipe.lexicon.exporters import export_all_formats

    result = export_all_formats("mzr", output_dir=tmp_path, view="clean")

    assert "lift" in result
    assert "cldf" in result
    assert "printable_html" in result
    assert Path(result["printable_html"]).exists()
    # The PDF key must always be present, even when the toolchain is absent.
    assert "printable_pdf" in result
    if result["printable_pdf"]:
        assert Path(result["printable_pdf"]).exists()
