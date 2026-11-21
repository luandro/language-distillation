"""WeasyPrint driver for the dictionary print edition.

Holds no layout logic: it renders the HTML produced by
`langpipe.lexicon.exporters.printable` and nothing else.

WeasyPrint is imported lazily so that `import langpipe.lexicon.exporters`
never requires the PDF toolchain.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

__all__ = [
    "PdfToolchainUnavailable",
    "build_print_edition",
    "render_pdf",
]


class PdfToolchainUnavailable(RuntimeError):
    """Raised when WeasyPrint (or its system libraries) are not importable."""


def render_pdf(html_path: Path | str, pdf_path: Path | str, *, base_url: str | None = None) -> Path:
    """Render an HTML file to PDF with WeasyPrint."""
    try:
        from weasyprint import HTML
    except Exception as exc:  # pragma: no cover - exercised only without the toolchain
        raise PdfToolchainUnavailable(
            "weasyprint is not available; install it with `uv sync` to build PDFs"
        ) from exc

    source = Path(html_path)
    target = Path(pdf_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    html = HTML(filename=str(source), base_url=base_url or str(source.parent))
    html.write_pdf(str(target))
    return target


def build_print_edition(
    entries: list[dict[str, Any]],
    output_dir: Path | str,
    *,
    target_lang: str,
    target_name: str,
    contact_lang: str,
    contact_name: str,
    language_family: str = "",
    glottocode: str = "",
    territory: str = "",
    fonts_dir: Path | str | None = None,
    edition_date: str = "",
    session: dict[str, Any] | None = None,
    morphology: list[dict[str, Any]] | None = None,
    parallel_sentences: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Build the print edition: HTML template + rendered PDF."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    html_path = out_dir / f"dictionary_{target_lang}_printable.html"
    pdf_path = out_dir / f"dictionary_{target_lang}_printable.pdf"

    exporter = PrintableDictionaryExporter(
        target_lang=target_lang,
        target_name=target_name,
        contact_lang=contact_lang,
        contact_name=contact_name,
        language_family=language_family,
        glottocode=glottocode,
        territory=territory,
        fonts_dir=fonts_dir,
        edition_date=edition_date,
    )
    exporter.export(
        entries,
        html_path,
        session=session,
        morphology=morphology,
        parallel_sentences=parallel_sentences,
    )

    render_pdf(html_path, pdf_path)
    return {
        "html": str(html_path),
        "pdf": str(pdf_path),
        "entries": str(len(entries)),
    }
