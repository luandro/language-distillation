"""PDF smoke test for the dictionary print edition.

Skipped when the optional PDF toolchain is absent so CI stays compiler-free.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from langpipe.lexicon.audit.view import LexiconView
from langpipe.lexicon.dictionary.session import DictionarySessionBuilder
from tests.fixtures.artifacts import requires_built_lexicon

pytestmark = requires_built_lexicon

REPO_ROOT = Path(__file__).resolve().parents[2]
FONTS_DIR = REPO_ROOT / "assets" / "fonts"

pytest.importorskip("weasyprint", reason="weasyprint is not installed")

HAS_PDFTOTEXT = shutil.which("pdftotext") is not None
HAS_PDFFONTS = shutil.which("pdffonts") is not None


def _mzr_entries():
    import json

    with open(REPO_ROOT / "exports" / "mzr" / "dictionary.json", encoding="utf-8") as f:
        raw = json.load(f)
    view = LexiconView(raw, view="clean")
    return raw, view.entries


def test_render_pdf_produces_a_valid_pdf(tmp_path: Path):
    from langpipe.lexicon.exporters.pdf import render_pdf
    from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

    raw, entries = _mzr_entries()
    session = DictionarySessionBuilder(
        target_lang="mzr",
        target_name=raw["language_name"],
        contact_lang=raw["contact_language"],
        language_family=raw["language_family"],
        glottocode=raw["glottocode"],
        territory=raw["territory"],
    ).build(entries, morphology=raw.get("morphology", []))

    html_path = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr",
        target_name=raw["language_name"],
        contact_lang=raw["contact_language"],
        fonts_dir=FONTS_DIR,
    ).export(entries, html_path, session=session)

    pdf_path = render_pdf(html_path, tmp_path / "book.pdf")

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 50_000
    assert pdf_path.read_bytes()[:5] == b"%PDF-"


@pytest.mark.skipif(not HAS_PDFTOTEXT, reason="pdftotext is not available")
def test_pdf_text_preserves_marubo_diacritics(tmp_path: Path):
    """The no-.notdef-glyphs check: diacritics must survive to the PDF text layer."""
    from langpipe.lexicon.exporters.pdf import render_pdf
    from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

    raw, entries = _mzr_entries()
    session = DictionarySessionBuilder(target_lang="mzr", target_name=raw["language_name"]).build(
        entries
    )

    html_path = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr", target_name=raw["language_name"], fonts_dir=FONTS_DIR
    ).export(entries, html_path, session=session)

    pdf_path = render_pdf(html_path, tmp_path / "book.pdf")
    text = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert "ẽa" in text, "the nasal-vowel headword must survive into the PDF text layer"
    assert "wẽstisẽ" in text
    assert "nukẽ" in text


@pytest.mark.skipif(not HAS_PDFFONTS, reason="pdffonts is not available")
def test_pdf_embeds_charis(tmp_path: Path):
    from langpipe.lexicon.exporters.pdf import render_pdf
    from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

    raw, entries = _mzr_entries()
    session = DictionarySessionBuilder(target_lang="mzr", target_name=raw["language_name"]).build(
        entries
    )

    html_path = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr", target_name=raw["language_name"], fonts_dir=FONTS_DIR
    ).export(entries, html_path, session=session)

    pdf_path = render_pdf(html_path, tmp_path / "book.pdf")
    fonts = subprocess.run(
        ["pdffonts", str(pdf_path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert "Charis" in fonts, fonts
    assert "yes" in fonts, "the font must be embedded"


@pytest.mark.skipif(not HAS_PDFTOTEXT, reason="pdftotext is not available")
def test_pdf_guide_words_appear_in_running_head(tmp_path: Path):
    """The running head must show the first and last headword on the page.

    This is the regression guard for a subtle WeasyPrint behaviour: a flex or
    grid container around the headword silently suppresses string-set, and the
    running head renders empty with no error.
    """
    from langpipe.lexicon.exporters.pdf import render_pdf
    from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

    entries = [
        {
            "headword": f"palavra{i:03d}",
            "pos": "noun",
            "glosses_por": [f"glosa {i}"],
            "status": "supported",
            "provenance": "Costa (2002)",
            "audit": {
                "lexical_class": "lemma",
                "flags": [],
                "reasons": [],
                "related_entry": None,
                "use_scopes": ["grounding"],
            },
            "semantics": {"primary_domain": "general"},
            "citations": [],
        }
        for i in range(120)
    ]
    session = DictionarySessionBuilder(target_lang="mzr", target_name="Marúbo").build(entries)

    html_path = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr", target_name="Marúbo", fonts_dir=FONTS_DIR
    ).export(entries, html_path, session=session)

    pdf_path = render_pdf(html_path, tmp_path / "book.pdf")
    text = subprocess.run(
        ["pdftotext", str(pdf_path), "-"], capture_output=True, text=True, check=True
    ).stdout

    # The first headword of the body appears in the body AND in the running
    # head of the first body page, so it must occur more than once.
    assert text.count("palavra000") >= 2, "guide word for the first entry is missing"
    # The last headword of the body appears in the body and in the running head
    # of the final body page.
    assert text.count("palavra119") >= 2, "guide word for the last entry is missing"


def test_build_print_edition_writes_html_and_pdf(tmp_path: Path):
    from langpipe.lexicon.exporters.pdf import build_print_edition

    raw, entries = _mzr_entries()
    result = build_print_edition(
        entries,
        tmp_path,
        target_lang="mzr",
        target_name=raw["language_name"],
        contact_lang=raw["contact_language"],
        contact_name="Português",
        language_family=raw["language_family"],
        glottocode=raw["glottocode"],
        territory=raw["territory"],
        fonts_dir=FONTS_DIR,
    )

    assert Path(result["html"]).exists()
    assert Path(result["pdf"]).exists()
    assert result["entries"] == str(len(entries))


def test_pdf_has_outline_bookmarks_per_section(tmp_path: Path):
    """The PDF must carry a navigable outline: sections at level 1, letters at level 2."""
    from weasyprint import HTML

    from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

    raw, entries = _mzr_entries()
    session = DictionarySessionBuilder(target_lang="mzr", target_name=raw["language_name"]).build(
        entries, morphology=raw.get("morphology", [])
    )

    html_path = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr", target_name=raw["language_name"], fonts_dir=FONTS_DIR
    ).export(entries, html_path, session=session)

    document = HTML(filename=str(html_path), base_url=str(tmp_path)).render()
    bookmarks = [b for page in document.pages for b in page.bookmarks]

    labels = [b[1] for b in bookmarks]
    levels = {b[1]: b[0] for b in bookmarks}

    assert "Prefácio" in labels
    assert "Bibliografia" in labels
    assert "Morfemas e clíticos" in labels
    # Every letter that has entries gets its own level-2 bookmark.
    for letter in ("A", "C", "E", "M", "N", "O", "P", "W", "Y"):
        assert letter in labels, f"missing bookmark for letter {letter}"
        assert levels[letter] == 2, f"letter {letter} should be level 2"
    assert levels["Prefácio"] == 1
    assert len(bookmarks) >= 20
