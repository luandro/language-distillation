#!/usr/bin/env python3
"""Locate the lost tilde on capital E in the Wenía 2018 text layer.

``var/external/wenia_2018/wenia_2018.pdf`` is born-digital (Word 2010). Where the author
printed a capital ``Ẽ`` (no precomposed WinAnsi glyph) the page content stream draws a
Book Antiqua ``E`` and then, as a SEPARATE text operator, one glyph of the CID font
``Times New Roman`` (Identity-H) with code 0x047A: the free-standing tilde. That font's
ToUnicode CMap maps the code to U+0020, so ``pdftotext`` emits a space, the tokenizer drops
it, and the harvested ``src`` shows a bare ``E`` (``var/artifacts/bare_e/findings.md``;
image-checked against page crops).

Detection is data, not inference. ``TILDE_TABLE`` lists ``(BaseFont, code)`` pairs verified
on page crops. An operator counts only when all of these hold:

* its font is a Type0 font whose BaseFont and code are in the table;
* that font's own ToUnicode maps the code to U+0020 (a stand-in for the tilde, not a
  space; genuine spaces are other codes of the body font);
* the operator immediately before it on the page is on the same baseline and its text
  ends in ``E``.

Anything else is left alone. In particular a word-initial ``E`` with no such operator is
plain ``E`` (18 of the 26 E-initial rows in the harvest; ``p42:l13 Enõ`` is plain while
``p43:l11 Ẽnõ`` is marked), so there is no blanket E -> Ẽ rule.

Each hit is located by the ``pdftotext -bbox-layout`` word that ends where the tilde
operator starts, then keyed to the ``pdftotext -layout`` line the extractor reads (same
text with whitespace removed, plus the index of the E in that text), which is how
``extract_pairs.py table --tilde-marks`` finds the row. The raw PDF is never modified.

Usage::

    python scripts/wenia_tilde_decode.py \\
        --rows exports/harvested_parallel/cesarino_2018_wenia_parallel.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Any

PDF_PATH = Path("var/external/wenia_2018/wenia_2018.pdf")
OUT_PATH = Path("exports/harvested_parallel/cesarino_2018_wenia_tilde_marks.json")

COMBINING_TILDE = "̃"

#: Image-verified tilde glyphs: ``(BaseFont, code)``. Same-code glyphs of other fonts that
#: also map to U+0020 (Times New Roman Italic 0x2FE/0x344, Book Antiqua Italic 0x28) are
#: either word gaps or draw the whole ``Ẽ``, so they are not tildes over a preceding E.
TILDE_TABLE: frozenset[tuple[str, int]] = frozenset({("Times New Roman", 0x047A)})

#: Letters a verified tilde may sit on (only E has been seen; others are never guessed).
BASE_LETTERS = frozenset({"E"})

BASELINE_TOLERANCE = 0.05
_XHTML = "{http://www.w3.org/1999/xhtml}"
_OBJ_RE = re.compile(rb"(\d+) 0 obj(.*?)endobj", re.S)
_TEXT_OP_RE = re.compile(
    rb"BT\s*(/F\d+) ([\d.]+) Tf\s*1 0 0 1 ([-\d.]+) ([-\d.]+) Tm\s*(?:[\d.\-]+ Tc)?\s*"
    rb"\[(.*?)\]\s*TJ",
    re.S,
)


def squash(text: str) -> str:
    """Whitespace-free form of a line; the join key shared with ``extract_pairs.py``."""
    return re.sub(r"\s+", "", text)


def apply_tilde(text: str, offset: int) -> str:
    """Return ``text`` with the E at ``offset`` as ``Ẽ`` (NFC); idempotent, E only."""
    char = text[offset]
    if unicodedata.normalize("NFC", char) == "Ẽ":
        return text
    if char not in BASE_LETTERS:
        raise ValueError(f"no base letter at {offset}: {text!r}")
    mark = unicodedata.normalize("NFC", char + COMBINING_TILDE)
    return text[:offset] + mark + text[offset + 1 :]


# --------------------------------------------------------------------------- #
# content streams
# --------------------------------------------------------------------------- #


def parse_objects(data: bytes) -> dict[int, tuple[bytes, bytes | None]]:
    """Map object number to ``(dictionary bytes, decoded stream or None)``."""
    objs: dict[int, tuple[bytes, bytes | None]] = {}
    for match in _OBJ_RE.finditer(data):
        body = match.group(2)
        stream_match = re.search(rb"stream\r?\n(.*)\r?\nendstream", body, re.S)
        head = body[: stream_match.start()] if stream_match else body
        stream: bytes | None = None
        if stream_match:
            stream = stream_match.group(1)
            if b"FlateDecode" in head:
                try:
                    stream = zlib.decompress(stream)
                except zlib.error:
                    stream = None
        objs[int(match.group(1))] = (head, stream)
    for head, stream in list(objs.values()):
        if b"/Type/ObjStm" in head and stream is not None:
            _expand_object_stream(head, stream, objs)
    return objs


def _expand_object_stream(
    head: bytes, stream: bytes, objs: dict[int, tuple[bytes, bytes | None]]
) -> None:
    """Add the dictionary objects packed in one ``/Type/ObjStm`` (never overriding direct ones)."""
    count = int(re.search(rb"/N (\d+)", head).group(1))  # type: ignore[union-attr]
    first = int(re.search(rb"/First (\d+)", head).group(1))  # type: ignore[union-attr]
    pairs = [(int(n), int(o)) for n, o in re.findall(rb"(\d+) (\d+)", stream[:first])][:count]
    for k, (number, offset) in enumerate(pairs):
        end = pairs[k + 1][1] if k + 1 < len(pairs) else len(stream) - first
        objs.setdefault(number, (stream[first + offset : first + end], None))


def parse_to_unicode(cmap: str) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", cmap, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            mapping[int(src, 16)] = bytes.fromhex(dst).decode("utf-16-be")
    for block in re.findall(r"beginbfrange(.*?)endbfrange", cmap, re.S):
        for line in block.strip().split("\n"):
            match = re.match(r"\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(.*)", line)
            if not match:
                continue
            low, high = int(match.group(1), 16), int(match.group(2), 16)
            rest = match.group(3).strip()
            if rest.startswith("["):
                for k, item in enumerate(re.findall(r"<([0-9A-Fa-f]+)>", rest)):
                    mapping[low + k] = bytes.fromhex(item).decode("utf-16-be")
            else:
                first = re.match(r"<([0-9A-Fa-f]+)>", rest)
                if first:
                    base = int(first.group(1), 16)
                    for k in range(high - low + 1):
                        mapping[low + k] = chr(base + k)
    return mapping


class CidFont:
    def __init__(self, base_font: str, to_unicode: dict[int, str]) -> None:
        self.base_font = base_font
        self.to_unicode = to_unicode


def load_fonts(objs: dict[int, tuple[bytes, bytes | None]]) -> dict[int, CidFont]:
    fonts: dict[int, CidFont] = {}
    for number, (head, _) in objs.items():
        if b"/Subtype/Type0" not in head.replace(b" ", b""):
            continue
        name = re.search(rb"/BaseFont\s*/([^/\s>]*)", head)
        tu_ref = re.search(rb"/ToUnicode (\d+)", head)
        if not name or not tu_ref:
            continue
        cmap = objs[int(tu_ref.group(1))][1]
        if cmap is None:
            continue
        base = name.group(1).decode("latin1").replace("#20", " ")
        base = re.sub(r"^[A-Z]{6}\+", "", base)
        fonts[number] = CidFont(base, parse_to_unicode(cmap.decode("latin1")))
    return fonts


def page_order(objs: dict[int, tuple[bytes, bytes | None]], count: int) -> list[int]:
    for head, _ in objs.values():
        flat = head.replace(b" ", b"")
        if b"/Type/Pages" in flat and b"/Kids" in head:
            kids_raw = re.search(rb"/Kids\s*\[(.*?)\]", head, re.S)
            if kids_raw:
                kids = [int(n) for n in re.findall(rb"(\d+) 0 R", kids_raw.group(1))]
                if len(kids) == count:
                    return kids
    raise ValueError(f"no flat page tree with {count} pages")


def page_content(
    objs: dict[int, tuple[bytes, bytes | None]], page_obj: int
) -> tuple[dict[str, int], bytes]:
    """Return a page's ``{font name: object}`` map and its joined content stream.

    Shapes this reader does not resolve raise instead of being skipped.
    """
    head = objs[page_obj][0]
    if re.search(rb"/Resources\s+\d+ 0 R", head):
        raise ValueError(f"page object {page_obj}: indirect /Resources is not supported")
    resources = {k.decode(): int(v) for k, v in re.findall(rb"/(F\d+) (\d+) 0 R", head)}
    single = re.search(rb"/Contents (\d+)", head)
    if single:
        refs = [int(single.group(1))]
    else:
        listed = re.search(rb"/Contents\s*\[(.*?)\]", head, re.S)
        refs = [int(n) for n in re.findall(rb"(\d+) 0 R", listed.group(1))] if listed else []
    stream = b"\n".join(objs[ref][1] or b"" for ref in refs)
    return resources, stream


def page_ops(
    objs: dict[int, tuple[bytes, bytes | None]], fonts: dict[int, CidFont], page_obj: int
) -> list[dict[str, Any]]:
    """Decode every ``BT /Fn Tf ... [..] TJ`` operator of one page, in stream order."""
    resources, stream = page_content(objs, page_obj)
    ops: list[dict[str, Any]] = []
    for match in _TEXT_OP_RE.finditer(stream):
        font_obj = resources.get(match.group(1)[1:].decode())
        font = fonts.get(font_obj) if font_obj is not None else None
        codes: list[int] = []
        text = ""
        if font is not None:
            for hexed in re.findall(rb"<([0-9A-Fa-f]+)>", match.group(5)):
                for k in range(0, len(hexed), 4):
                    code = int(hexed[k : k + 4], 16)
                    codes.append(code)
                    text += font.to_unicode.get(code, "")
        ops.append(
            {
                "font": font,
                "x": float(match.group(3)),
                "y": float(match.group(4)),
                "codes": codes,
                "text": text,
            }
        )
    return ops


def check_complete(
    objs: dict[int, tuple[bytes, bytes | None]],
    fonts: dict[int, CidFont],
    page_obj: int,
    ops: list[dict[str, Any]],
) -> None:
    """Raise unless a broad scan finds exactly as many tilde codes as the parsed operators.

    The scan walks ``/Fn Tf`` switches in the raw stream and counts the tilde code in every
    hex string drawn while a tilde font is selected, whatever operator draws it (``Tj``,
    ``'``, a ``TJ`` the shape regex missed). Literal strings in such a font are unsupported.
    """
    resources, stream = page_content(objs, page_obj)
    expected = sum(
        1 for op in ops if op["font"] is not None for c in op["codes"] if _is_tilde(op["font"], c)
    )
    found = 0
    parts = re.split(rb"(/F\d+) [\d.]+ Tf", stream)
    for name, chunk in zip(parts[1::2], parts[2::2], strict=True):
        font = fonts.get(resources.get(name[1:].decode(), -1))
        if font is None or not any(base == font.base_font for base, _ in TILDE_TABLE):
            continue
        if re.search(rb"\((?:[^()\\]|\\.)*\)", chunk):
            raise ValueError(f"page object {page_obj}: literal string in a CID tilde font")
        for hexed in re.findall(rb"<([0-9A-Fa-f]+)>", chunk):
            for k in range(0, len(hexed), 4):
                found += _is_tilde(font, int(hexed[k : k + 4], 16))
    if found != expected:
        raise ValueError(
            f"page object {page_obj}: {found} tilde codes in the stream, {expected} parsed"
        )


def _is_tilde(font: CidFont, code: int) -> bool:
    return (font.base_font, code) in TILDE_TABLE and font.to_unicode.get(code) == " "


def is_tilde_op(op: dict[str, Any]) -> bool:
    font: CidFont | None = op["font"]
    return font is not None and any(_is_tilde(font, code) for code in op["codes"])


def find_tilde_e(ops: list[dict[str, Any]]) -> list[dict[str, float]]:
    """Return ``{"x", "y"}`` of every tilde operator that directly follows an E."""
    hits: list[dict[str, float]] = []
    for i in range(1, len(ops)):
        if not is_tilde_op(ops[i]):
            continue
        prev = ops[i - 1]
        if abs(prev["y"] - ops[i]["y"]) > BASELINE_TOLERANCE:
            continue
        if prev["text"][-1:] in BASE_LETTERS:
            hits.append({"x": ops[i]["x"], "y": ops[i]["y"]})
    return hits


# --------------------------------------------------------------------------- #
# positions: bbox words and layout lines
# --------------------------------------------------------------------------- #


def parse_bbox_pages(xml_text: str) -> list[tuple[float, list[dict[str, Any]]]]:
    pages = []
    for page in ET.fromstring(xml_text).iter(f"{_XHTML}page"):
        words = [
            {
                "text": (w.text or "").strip(),
                "box": [float(w.get(k) or 0) for k in ("xMin", "yMin", "xMax", "yMax")],
            }
            for w in page.iter(f"{_XHTML}word")
            if (w.text or "").strip()
        ]
        pages.append((float(page.get("height") or 0), words))
    return pages


def locate(
    hit: dict[str, float], height: float, words: list[dict[str, Any]], layout_page: str
) -> dict[str, Any]:
    """Resolve one hit to its E word box, its layout line key and the E's index in it."""
    y_top = height - hit["y"]
    band = [w for w in words if w["box"][1] - 2 <= y_top <= w["box"][3] + 3]
    band.sort(key=lambda w: w["box"][0])
    e_words = [
        w
        for w in band
        if w["box"][0] < hit["x"] - 1.0
        and w["box"][2] >= hit["x"] - 0.6
        and w["text"][-1:] in BASE_LETTERS
    ]
    if len(e_words) != 1:
        raise ValueError(f"cannot place tilde at x={hit['x']} y={hit['y']}: {len(e_words)} words")
    e_word = e_words[0]
    before = "".join(squash(w["text"]) for w in band[: band.index(e_word)])
    offset = len(before) + len(squash(e_word["text"])) - 1
    key = squash("".join(w["text"] for w in band))
    keys = [squash(line) for line in layout_page.split("\n") if line.strip()]
    if key not in keys:
        raise ValueError(f"no -layout line matches {key!r}")
    occurrence = 0
    if keys.count(key) > 1:
        same = sorted({round(w["box"][1], 1) for w in words if _band_key(w, words) == key})
        occurrence = same.index(round(e_word["box"][1], 1))
    return {
        "word": e_word["text"],
        "bbox": [round(v, 2) for v in e_word["box"]],
        "line_key": key,
        "e_index": offset,
        "line_occurrence": occurrence,
    }


def _band_key(anchor: dict[str, Any], words: list[dict[str, Any]]) -> str:
    row = [w for w in words if abs(w["box"][1] - anchor["box"][1]) < 1.5]
    row.sort(key=lambda w: w["box"][0])
    return squash("".join(w["text"] for w in row))


def attach_refs(occurrences: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    """Set each occurrence's harvested ``ref`` (or None) by page and exact line text.

    Rows are keyed on their printed-E form (``Ẽ`` folded back to ``E``), so already-patched
    jsonl regenerates the same marks. A hit on a page the rows cover must find its row.
    """
    pages = {row["qc"]["page"] for row in rows}
    low, high = (min(pages), max(pages)) if pages else (0, -1)
    for occ in occurrences:
        matches = []
        for row in rows:
            if row["qc"]["page"] != occ["page"]:
                continue
            margin = f"{row['qc']['printed_line']}." if row["qc"]["printed_line"] else ""
            src = unicodedata.normalize("NFC", row["src"]).replace("\u1ebc", "E")
            line = squash(margin + src + row["qc"].get("tgt_raw", row["tgt"]))
            if line == occ["line_key"]:
                matches.append(row["ref"])
        occ["ref"] = (
            matches[occ["line_occurrence"]] if len(matches) > occ["line_occurrence"] else None
        )
        if occ["ref"] is None and low <= occ["page"] <= high:
            raise ValueError(f"tilde hit on page {occ['page']} has no harvested row: {occ}")


def decode_pdf(pdf: Path, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    data = pdf.read_bytes()
    bbox = subprocess.run(
        ["pdftotext", "-bbox-layout", str(pdf), "-"], capture_output=True, text=True, check=True
    ).stdout
    layout = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True
    ).stdout.split("\f")
    bbox_pages = parse_bbox_pages(bbox)
    objs = parse_objects(data)
    fonts = load_fonts(objs)
    order = page_order(objs, len(bbox_pages))
    occurrences: list[dict[str, Any]] = []
    for number, page_obj in enumerate(order, 1):
        ops = page_ops(objs, fonts, page_obj)
        check_complete(objs, fonts, page_obj, ops)
        for hit in find_tilde_e(ops):
            height, words = bbox_pages[number - 1]
            found = locate(hit, height, words, layout[number - 1])
            occurrences.append({"page": number, "stream_xy": [hit["x"], hit["y"]], **found})
    if rows is not None:
        attach_refs(occurrences, rows)
    font_name, code = sorted(TILDE_TABLE)[0]
    return {
        "source_pdf": str(pdf),
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "method": (
            "content-stream scan: a Type0 font glyph in TILDE_TABLE whose ToUnicode is U+0020, "
            "directly after an E on the same baseline; located by pdftotext -bbox-layout word, "
            "keyed to the pdftotext -layout line"
        ),
        "font": {"base_font": font_name, "encoding": "Identity-H"},
        "code": f"0x{code:04X}",
        "to_unicode": "U+0020",
        "result": "U+1EBC",
        "count": len(occurrences),
        "mapped_rows": sum(1 for o in occurrences if o.get("ref")),
        "occurrences": occurrences,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--pdf", type=Path, default=PDF_PATH)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument(
        "--rows", type=Path, default=None, help="harvested jsonl used to label each hit with a ref"
    )
    args = parser.parse_args()

    rows = None
    if args.rows:
        rows = [json.loads(line) for line in args.rows.read_text(encoding="utf-8").splitlines()]
    report = decode_pdf(args.pdf, rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {report['count']} marks ({report['mapped_rows']} mapped) to {args.out}")


if __name__ == "__main__":
    main()
