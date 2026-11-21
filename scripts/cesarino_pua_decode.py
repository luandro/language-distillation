#!/usr/bin/env python3
"""Decode the private-use tilde glyphs in the Cesarino 2008 thesis text layer.

``pdftotext -layout`` on ``var/external/cesarino_2008_thesis/cesarino_2008_thesis.pdf``
emits three Private Use Area codepoints where the typesetter drew a free-standing tilde
over a vowel that has no precomposed WinAnsi glyph (``ĩ``, ``ẽ``): U+F017, U+F018 and
U+F01C. Every page crop read for this decoder (evidence in
``var/artifacts/cesarino_2008_thesis/evidence.json``) shows the same glyph, a tilde, so
each mapped code becomes U+0303 COMBINING TILDE on the letter it follows in the text
stream (``Pani<U+F018>papa`` -> ``Panĩpapa``).

The table below is data, not inference: a code enters ``PUA_TABLE`` only after image
verification. Anything this decoder cannot place stays visible as ``<U+XXXX>``:

* a PUA code missing from the table (never guessed);
* a mapped code with no letter right before it. The only gap bridged is one space or one
  hyphen that the extraction put between the letter and its mark (``yochi-<U+F018>ra`` ->
  ``yochĩ-ra``; ``vaki <U+F01C>`` -> ``vakĩ ``); page crops show the tilde on that letter.

Rendering caveat, recorded in the evidence file: the tilde glyph is drawn at a fixed
offset left of its pen position, so after a narrow ``i`` it can *look* centred on the
previous letter (``oi<U+F018>`` prints like ``õi``). Stream order, not visual position,
decides the base; where the raw text already spells those words in real Unicode, the mark
is on the ``i`` (counts, computed from the raw text, in ``evidence.json``).

Usage::

    python scripts/cesarino_pua_decode.py            # writes decoded.txt + qa.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

PDF_PATH = Path("var/external/cesarino_2008_thesis/cesarino_2008_thesis.pdf")
OUT_DIR = Path("var/artifacts/cesarino_2008_thesis")

COMBINING_TILDE = "̃"

#: Image-verified PUA codes and the Unicode string each one stands for.
PUA_TABLE: dict[str, str] = {
    "": COMBINING_TILDE,
    "": COMBINING_TILDE,
    "": COMBINING_TILDE,
}

#: Characters the extraction may insert between a letter and its mark (at most one).
_BRIDGE = frozenset(" -")


def is_pua(ch: str) -> bool:
    return 0xE000 <= ord(ch) <= 0xF8FF


def marker(ch: str) -> str:
    return f"<U+{ord(ch):04X}>"


@dataclass
class DecodeStats:
    seen: Counter[str] = field(default_factory=Counter)
    mapped: Counter[str] = field(default_factory=Counter)
    bridged: Counter[str] = field(default_factory=Counter)
    unmapped: Counter[str] = field(default_factory=Counter)
    unattached: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, dict[str, int]]:
        def hexed(c: Counter[str]) -> dict[str, int]:
            return {f"U+{ord(k):04X}": v for k, v in sorted(c.items())}

        return {
            "seen": hexed(self.seen),
            "mapped": hexed(self.mapped),
            "bridged": hexed(self.bridged),
            "unmapped": hexed(self.unmapped),
            "unattached": hexed(self.unattached),
        }


def _attach(out: list[str], mark: str) -> bool:
    """Put ``mark`` on the letter ending ``out`` (bridging one space/hyphen); False if none."""
    gap = 1 if out and out[-1] in _BRIDGE else 0
    idx = len(out) - 1 - gap
    if idx < 0 or not out[idx].isalpha():
        return False
    out[idx] = unicodedata.normalize("NFC", out[idx] + mark)
    return True


def decode_text(text: str, stats: DecodeStats | None = None) -> str:
    """Return ``text`` with mapped PUA codes applied and every other PUA code as ``<U+XXXX>``."""
    stats = stats if stats is not None else DecodeStats()
    out: list[str] = []
    for ch in text:
        if not is_pua(ch):
            out.append(ch)
            continue
        stats.seen[ch] += 1
        mark = PUA_TABLE.get(ch)
        if mark is None:
            stats.unmapped[ch] += 1
            out.append(marker(ch))
            continue
        bridged = bool(out) and out[-1] in _BRIDGE
        if _attach(out, mark):
            stats.mapped[ch] += 1
            if bridged:
                stats.bridged[ch] += 1
        else:
            stats.unattached[ch] += 1
            out.append(marker(ch))
    return "".join(out)


def remaining_pua(text: str) -> int:
    return sum(1 for ch in text if is_pua(ch))


def extract_layout_text(pdf: Path) -> str:
    return subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True, text=True, check=True,
    ).stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--pdf", type=Path, default=PDF_PATH)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    raw = extract_layout_text(args.pdf)
    pages = raw.split("\f")
    if pages and pages[-1] == "":
        pages.pop()

    stats = DecodeStats()
    chunks = [f"=== page {n} ===\n{decode_text(page, stats)}" for n, page in enumerate(pages, 1)]
    decoded = "\n".join(chunks)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "decoded.txt").write_text(decoded, encoding="utf-8")
    qa = {
        "source_pdf": str(args.pdf),
        "source_sha256": hashlib.sha256(args.pdf.read_bytes()).hexdigest(),
        "extraction": "pdftotext -layout",
        "raw_text_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "pages": len(pages),
        "pua_before": remaining_pua(raw),
        "pua_after": remaining_pua(decoded),
        "markers_left": sum(stats.unmapped.values()) + sum(stats.unattached.values()),
        "table": {f"U+{ord(k):04X}": f"U+{ord(v):04X}" for k, v in PUA_TABLE.items()},
        "counts": stats.as_dict(),
    }
    (args.out_dir / "qa.json").write_text(
        json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(qa, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
