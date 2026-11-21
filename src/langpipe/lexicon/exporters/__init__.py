"""Multi-format lexicographical exporters (Milestone 1, WP 1.4)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langpipe.lexicon.audit.view import LexiconView
from langpipe.lexicon.dictionary.session import DictionarySessionBuilder
from langpipe.lexicon.exporters.cldf import CldfDictionaryExporter
from langpipe.lexicon.exporters.lift import LiftExporter
from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

logger = logging.getLogger(__name__)

# `src/langpipe/lexicon/exporters/__init__.py` -> parents[0]=exporters,
# [1]=lexicon, [2]=langpipe, [3]=src, [4]=repository root.
REPO_ROOT = Path(__file__).resolve().parents[4]


def _fonts_dir() -> Path | None:
    """Locate the vendored Charis SIL webfonts, if present."""
    candidate = REPO_ROOT / "assets" / "fonts"
    return candidate if candidate.exists() else None


def export_all_formats(
    lang_code: str,
    output_dir: Path | str | None = None,
    view: str = "clean",
) -> dict[str, Any]:
    """Generate LIFT XML, CLDF tables, print-ready HTML, and the print PDF."""
    out = Path(output_dir) if output_dir else Path("exports") / lang_code / "formats"
    out.mkdir(parents=True, exist_ok=True)

    view_obj = LexiconView.load(lang_code=lang_code, view=view)
    entries = view_obj.entries
    contact_lang = getattr(view_obj, "contact_language", "por")
    lang_name = view_obj.language_name

    raw = view_obj.raw_data or {}

    # 1. LIFT XML
    lift_file = out / f"dictionary_{lang_code}.lift"
    LiftExporter(target_lang=lang_code, contact_lang=contact_lang).export(entries, lift_file)

    # 2. CLDF Tables
    cldf_dir = out / "cldf"
    cldf_files = CldfDictionaryExporter(target_lang=lang_code, contact_lang=contact_lang).export(
        entries, cldf_dir
    )

    # 3. Dictionary session (shared by the web tab and the print edition)
    builder = DictionarySessionBuilder(
        target_lang=lang_code,
        target_name=lang_name,
        contact_lang=contact_lang,
        language_family=raw.get("language_family", ""),
        glottocode=raw.get("glottocode", ""),
        territory=raw.get("territory", ""),
    )
    session = builder.build(
        entries,
        morphology=raw.get("morphology", []),
        parallel_sentences=raw.get("parallel_sentences", []),
        # The clean view drops the audited inflected forms. They are not
        # published as headwords, but a reader must still be able to look one
        # up under its base, so the full lexicon is the forms source.
        forms_source=raw.get("lexicon", []),
    )

    # 4. Print-Ready HTML Book
    print_file = out / f"dictionary_{lang_code}_printable.html"
    PrintableDictionaryExporter(
        target_lang=lang_code,
        target_name=lang_name,
        contact_lang=contact_lang,
        contact_name="Português",
        language_family=raw.get("language_family", ""),
        glottocode=raw.get("glottocode", ""),
        territory=raw.get("territory", ""),
        fonts_dir=_fonts_dir(),
    ).export(entries, print_file, session=session)

    # 5. Print PDF (best-effort: the toolchain is optional)
    #
    # The Exports tab links straight at the generated PDF, so a failure here
    # must not take the other formats down with it. The exception is logged
    # rather than swallowed: a silent `except Exception` makes a broken render
    # indistinguishable from a missing toolchain.
    pdf_file = ""
    try:
        from langpipe.lexicon.exporters.pdf import build_print_edition

        result = build_print_edition(
            entries,
            out,
            target_lang=lang_code,
            target_name=lang_name,
            contact_lang=contact_lang,
            contact_name="Português",
            language_family=raw.get("language_family", ""),
            glottocode=raw.get("glottocode", ""),
            territory=raw.get("territory", ""),
            fonts_dir=_fonts_dir(),
            session=session,
            morphology=raw.get("morphology", []),
            parallel_sentences=raw.get("parallel_sentences", []),
        )
        pdf_file = result["pdf"]
    except Exception as exc:  # noqa: BLE001 - the PDF is optional, the rest is not
        logger.warning("print PDF not generated for %s: %s", lang_code, exc)

    return {
        "lift": str(lift_file),
        "cldf": cldf_files,
        "printable_html": str(print_file),
        "printable_pdf": pdf_file,
        "total_entries": len(entries),
    }


__all__ = [
    "CldfDictionaryExporter",
    "LiftExporter",
    "PrintableDictionaryExporter",
    "export_all_formats",
]
