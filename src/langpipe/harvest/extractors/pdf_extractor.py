"""PDF layout-preserving text extractor using pdftotext."""

import os
import subprocess
from pathlib import Path


class PdfExtractor:
    """Extracts text from PDF documents preserving layout and table alignments."""

    def __init__(self, pdftotext_bin: str = "/home/linuxbrew/.linuxbrew/bin/pdftotext"):
        if not os.path.exists(pdftotext_bin):
            pdftotext_bin = "pdftotext"
        self.pdftotext_bin = pdftotext_bin

    def extract_text(self, pdf_path: Path | str, output_txt_path: Path | str | None = None) -> str:
        """Extract layout-preserving text from PDF."""
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        if output_txt_path is None:
            output_txt_path = pdf_path.with_suffix(".txt")
        output_txt_path = Path(output_txt_path)

        cmd = [self.pdftotext_bin, "-layout", str(pdf_path), str(output_txt_path)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            # Fallback to python extraction if pdftotext fails
            raise RuntimeError(f"pdftotext execution failed: {e}") from e

        with open(output_txt_path, encoding="utf-8", errors="replace") as f:
            return f.read()
