#!/usr/bin/env python3
"""Build a static human review packet for the Cesarino 2013 clean-ref candidates.

``scripts/recover_chant_orthography.py`` cites a clean (born-digital) surface form for some
OCR-damaged chant rows of the 2013 scan. Those ``clean_src`` values are hypotheses with
citations; a person has to look at the printed page before any of them is promoted. This
script puts the evidence for one row on one screen: the observed OCR ``src``, every clean
candidate with its locators and confidence tier, and a 200 dpi crop of the printed row.

It is read-only with respect to the candidate files and promotes nothing. Candidate rows default to
the committed ``exports/parallel_candidates/cesarino_2013_clean_refs.jsonl``; when ``--published``
names that same file the published column is dropped, because every entry would only restate
itself.

Row geometry is not stored in the candidate rows, so it is recovered in memory by running
``extract_pairs.extract_columns`` again with the **same parameters** that produced
``exports/parallel_candidates/cesarino_2013_columns.jsonl`` (default ``--column-gap`` plus
the five ``--column-gap-page P=25`` overrides). Two of its module functions are wrapped for
the duration of that call to capture the source/target ``Segment`` of every row; the
extractor itself is not changed. Every candidate row's ``src`` must equal the recovered
segment text, or no packet is written.

Each scanned sheet holds two book pages, so a crop is clamped to the half of the sheet that
holds the row's vernacular column.
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

_EXTRACT_PAIRS_PATH = Path(__file__).resolve().parent / "extract_pairs.py"


def _load_extract_pairs() -> ModuleType:
    existing = sys.modules.get("extract_pairs")
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location("extract_pairs", _EXTRACT_PAIRS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ep = _load_extract_pairs()

PDF_POINTS_PER_INCH = 72.0
DEFAULT_DPI = 200
#: The committed clean-ref set; both ``--candidates`` and ``--published`` default to it, so a bare
#: run reviews that set in place and the published column is dropped.
DEFAULT_CLEAN_REFS = Path("exports/parallel_candidates/cesarino_2013_clean_refs.jsonl")
#: Horizontal padding around the row, in points.
PAD_X_PT = 10.0
#: Vertical context above and below the row (about two chant rows each way), in points.
CONTEXT_Y_PT = 26.0
#: Fallback glyph height when no word box backs a segment.
LINE_HEIGHT_PT = 11.0
#: The five sheets whose chant column is indented (exports/parallel_candidates/README.md).
DEFAULT_COLUMN_GAP_PAGES = ("25=25", "72=25", "106=25", "123=25", "148=25")

SECTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "nasal-added",
        "1. Nasal marks added",
        "A quoted-chant citation (Villada 2018) prints the observed letters with nasal marks "
        "the scan lost. Check the crop: does the printed line carry these marks?",
    ),
    (
        "confirmation",
        "2. Confirmations",
        "The cited surface has the observed letters (identical, or the same letters with other "
        "marks). Check the crop agrees with the cited form.",
    ),
    (
        "conflict",
        "3. Conflicts (T2)",
        "The references print this token sequence with different marks; clean_src is null. "
        "Decide from the crop which candidate (if any) the book prints. Never by vote count.",
    ),
    (
        "shared-formula",
        "4. Shared-formula citations only",
        "Only Wenía 2018 (a different chant sharing this refrain) cites the row. This tier may "
        "not originate clean_src; the crop is the only first-hand evidence.",
    ),
)


@dataclass(frozen=True)
class Box:
    """A rectangle in PDF points (origin top-left, as ``pdftotext -bbox-layout`` reports)."""

    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class RowGeometry:
    """Where one extracted row sits on its sheet."""

    page: int
    row: int
    segment_text: str
    source: Box
    target: Box


@dataclass(frozen=True)
class Crop:
    """A crop rectangle in pixels plus the row highlight as fractions of the crop."""

    x: int
    y: int
    width: int
    height: int
    half: str
    highlight: tuple[float, float, float, float]


def pt_to_px(value: float, dpi: int = DEFAULT_DPI) -> int:
    """Convert PDF points to pixels at ``dpi`` (1 pt = 1/72 inch)."""
    return round(value * dpi / PDF_POINTS_PER_INCH)


def same_file(left: Path, right: Path) -> bool:
    """True when both paths name one file; ``resolve`` also works for a missing path."""
    return left.resolve() == right.resolve()


def segment_src(segment_text: str) -> str:
    """The ``src`` the extractor emits for a segment: glued margin number off, NFC."""
    text, _ = ep._strip_leading_line_number(segment_text)
    return unicodedata.normalize("NFC", text)


def check_segments(rows: list[dict[str, Any]], geometry: dict[str, RowGeometry]) -> list[str]:
    """Return one message per row whose ``src`` is not its recovered segment text."""
    problems = []
    for row in rows:
        found = geometry.get(row["ref"])
        if found is None:
            problems.append(f"{row['ref']}: no row at this locator")
        elif segment_src(found.segment_text) != row["src"]:
            problems.append(f"{row['ref']}: src {row['src']!r} != segment {found.segment_text!r}")
    return problems


def page_heights(xml_text: str) -> list[float]:
    """Page heights in points, in page order, from a ``pdftotext -bbox-layout`` dump."""
    return [float(match) for match in re.findall(r'<page\b[^>]*\bheight="([0-9.]+)"', xml_text)]


def _segment_bottom(segment: Any, words: list[Any]) -> float:
    bottoms: list[float] = [
        float(word.y_max)
        for word in words
        if abs(word.y_min - segment.y) <= ep.LINE_TOLERANCE
        and segment.x_min - 0.5 <= word.x_min
        and word.x_max <= segment.x_max + 0.5
    ]
    return max(bottoms) if bottoms else float(segment.y) + LINE_HEIGHT_PT


def _box(segment: Any, words: list[Any]) -> Box:
    return Box(segment.x_min, segment.y, segment.x_max, _segment_bottom(segment, words))


@contextmanager
def _capture_rows() -> Iterator[tuple[dict[int, Any], list[list[Any]]]]:
    """Wrap two extractor functions to capture each row's source and target ``Segment``."""
    targets: dict[int, Any] = {}
    page_sources: list[list[Any]] = []
    original_match, original_assign = ep.match_rows, ep._assign_printed_lines

    def match_rows(*args: Any, **kwargs: Any) -> Any:
        pairs = original_match(*args, **kwargs)
        for source, target in pairs:
            targets[id(source)] = target
        return pairs

    def assign_printed_lines(numbers: Any, sources: Any, *args: Any, **kwargs: Any) -> Any:
        page_sources.append(list(sources))
        return original_assign(numbers, sources, *args, **kwargs)

    setattr(ep, "match_rows", match_rows)  # noqa: B010 - patch the loaded module, not a copy
    setattr(ep, "_assign_printed_lines", assign_printed_lines)  # noqa: B010
    try:
        yield targets, page_sources
    finally:
        setattr(ep, "match_rows", original_match)  # noqa: B010
        setattr(ep, "_assign_printed_lines", original_assign)  # noqa: B010


def recover_geometry(
    pages: list[tuple[float, list[Any]]],
    page_numbers: set[int],
    ref_prefix: str,
    column_gap: float,
    column_gap_pages: dict[int, float],
) -> dict[str, RowGeometry]:
    """Re-run ``extract_columns`` page by page and map each row ref to its geometry.

    Row locators are positional (``l<row>`` counts every paired row of the page before
    duplicates are dropped), so one page at a time with ``keep_repeats`` reproduces every
    locator of the full run while keeping each record next to its captured segment.
    """
    geometry: dict[str, RowGeometry] = {}
    for page in sorted(page_numbers):
        with _capture_rows() as (targets, page_sources):
            records, _ = ep.extract_columns(
                pages,
                ref_prefix=ref_prefix,
                page_range=(page, page),
                keep_repeats=True,
                column_gap=column_gap,
                column_gap_pages=column_gap_pages,
            )
        if not records:
            continue
        sources = page_sources[0]
        if len(page_sources) != 1 or len(sources) != len(records):
            raise RuntimeError(f"page {page}: captured {len(sources)} rows, {len(records)} records")
        words = pages[page - 1][1]
        for record, source in zip(records, sources, strict=True):
            geometry[record["ref"]] = RowGeometry(
                page=page,
                row=record["qc"]["row"],
                segment_text=source.text,
                source=_box(source, words),
                target=_box(targets[id(source)], words),
            )
    return geometry


def crop_for(row: RowGeometry, page_width: float, page_height: float, dpi: int) -> Crop:
    """Crop the row with context, clamped to the book page (sheet half) that holds it."""
    middle = page_width / 2.0
    half = "left" if row.source.x0 < middle else "right"
    lo, hi = (0.0, middle) if half == "left" else (middle, page_width)
    if not lo <= row.target.x0 <= hi:
        # the translation sits across the gutter: show both book pages rather than cut it off
        lo, hi, half = 0.0, page_width, "both"
    x0 = max(lo, min(row.source.x0, row.target.x0) - PAD_X_PT)
    x1 = min(hi, max(row.source.x1, row.target.x1) + PAD_X_PT)
    row_top = min(row.source.y0, row.target.y0)
    row_bottom = max(row.source.y1, row.target.y1)
    y0 = max(0.0, row_top - CONTEXT_Y_PT)
    y1 = min(page_height, row_bottom + CONTEXT_Y_PT)
    width, height = x1 - x0, y1 - y0
    highlight = (
        (min(row.source.x0, row.target.x0) - 2 - x0) / width,
        (row_top - 2 - y0) / height,
        (max(row.source.x1, row.target.x1) + 2 - x0) / width,
        (row_bottom + 2 - y0) / height,
    )
    clamped = tuple(min(1.0, max(0.0, value)) for value in highlight)
    return Crop(
        x=pt_to_px(x0, dpi),
        y=pt_to_px(y0, dpi),
        width=pt_to_px(x1, dpi) - pt_to_px(x0, dpi),
        height=pt_to_px(y1, dpi) - pt_to_px(y0, dpi),
        half=half,
        highlight=(clamped[0], clamped[1], clamped[2], clamped[3]),
    )


def render_crop(pdf: Path, page: int, crop: Crop, out_png: Path, dpi: int) -> None:
    """Render one crop with ``pdftoppm`` (``-x/-y/-W/-H`` are pixels at ``-r``)."""
    prefix = out_png.with_suffix("")
    subprocess.run(
        [
            "pdftoppm",
            "-r",
            str(dpi),
            "-f",
            str(page),
            "-l",
            str(page),
            "-x",
            str(crop.x),
            "-y",
            str(crop.y),
            "-W",
            str(crop.width),
            "-H",
            str(crop.height),
            "-png",
            "-singlefile",
            str(pdf),
            str(prefix),
        ],
        check=True,
        capture_output=True,
    )


def category(row: dict[str, Any]) -> str:
    """Review section of a candidate row; conflicts always get their own section."""
    evidence = row["clean_evidence"]
    if evidence == "conflict":
        return "conflict"
    if evidence == "uncorroborated":
        return "shared-formula"
    if row["qc"].get("clean_delta") == "nasal-marks-added":
        return "nasal-added"
    return "confirmation"


def published_label(published: dict[str, Any] | None) -> str:
    """How the published ``cesarino_2013_clean_refs.jsonl`` holds this row."""
    if published is None:
        return "not in the published clean-ref set"
    delta = published["qc"].get("clean_delta")
    return f"published: {published['clean_evidence']}" + (f", {delta}" if delta else "")


def image_name(ref: str) -> str:
    """``cesarino-2013:p30:l18`` -> ``p30-l18.png``."""
    return "-".join(ref.split(":")[1:]) + ".png"


def anchor(ref: str) -> str:
    return "r-" + "-".join(ref.split(":")[1:])


def _citations_for(row: dict[str, Any], surface: str) -> list[dict[str, Any]]:
    return [item for item in row.get("clean_citations", []) if item["surface"] == surface]


def render_entry(
    row: dict[str, Any],
    geometry: RowGeometry | None,
    crop: Crop | None,
    published: dict[str, Any] | None,
    compare_published: bool = True,
) -> str:
    """One review entry as an HTML ``<article>``; every value from the data is escaped.

    ``compare_published=False`` drops the published column: the row is its own published record.
    """
    esc = html.escape
    candidates = []
    for surface in row["clean_candidates"]:
        cites = _citations_for(row, surface)
        cite_items = "".join(
            f"<li><code>{esc(item['locator'])}</code> "
            f"<span class=tier>{esc(str(item['clean_confidence']))}</span></li>"
            for item in cites
        )
        if not cites:
            cite_items = "".join(
                f"<li><code>{esc(locator)}</code></li>" for locator in row.get("clean_sources", [])
            )
        chosen = " chosen" if surface == row.get("clean_src") else ""
        marker = " <span class=badge>clean_src</span>" if chosen else ""
        candidates.append(
            f"<div class='cand{chosen}'><div class=surface>{esc(surface)}{marker}</div>"
            f"<ul>{cite_items}</ul></div>"
        )
    where = ""
    figure = "<p class=missing>No crop: the row could not be located.</p>"
    if geometry is not None and crop is not None:
        left, top, right, bottom = crop.highlight
        style = (
            f"left:{left * 100:.2f}%;top:{top * 100:.2f}%;"
            f"width:{(right - left) * 100:.2f}%;height:{(bottom - top) * 100:.2f}%"
        )
        where = (
            f"PDF page {geometry.page}, row {geometry.row}, {esc(crop.half)} book page of the sheet"
        )
        figure = (
            f"<figure><div class=crop><img src='img/{esc(image_name(row['ref']))}' "
            f"alt='scan of {esc(row['ref'])}' loading=lazy>"
            f"<span class=hl style='{style}'></span></div>"
            f"<figcaption>{where}; highlight = extracted row</figcaption></figure>"
        )
    printed = row["qc"].get("printed_line")
    printed_note = f" · printed line {esc(str(printed))}" if printed else ""
    published_note = f" · {esc(published_label(published))}" if compare_published else ""
    clean_src = row.get("clean_src")
    clean_line = (
        f"<span class=clean>{esc(clean_src)}</span>"
        if clean_src
        else "<em>null</em> (no clean_src)"
    )
    return (
        f"<article id='{anchor(row['ref'])}'>"
        f"<header><code class=ref>{esc(row['ref'])}</code>"
        f"<span class=meta>{esc(row['clean_evidence'])} · "
        f"{esc(str(row.get('clean_confidence')))} · votes {int(row['clean_votes'])}"
        f"{printed_note}{published_note}</span></header>"
        f"<dl><dt>observed OCR src</dt><dd class=obs>{esc(row['src'])}</dd>"
        f"<dt>translation (tgt)</dt><dd>{esc(row['tgt'])}</dd>"
        f"<dt>clean_src</dt><dd>{clean_line}</dd></dl>"
        f"<div class=cands>{''.join(candidates)}</div>{figure}</article>"
    )


CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6862;--line:#dedad2;--card:#fff;--accent:#9a3412;
--ok:#14532d;--hl:rgba(234,88,12,.9)}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--muted:#a19d94;
--line:#34322e;--card:#1f1e1b;--accent:#fb923c;--ok:#86efac}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px}
h1{font-size:1.5rem;margin:0 0 .5rem}h2{margin:2.5rem 0 .25rem;font-size:1.2rem}
p.lede,p.note{color:var(--muted);max-width:75ch}
nav ul{padding-left:1.2rem}
article{background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:12px 14px;margin:14px 0}
header{display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:baseline}
.ref{font-weight:600}.meta{color:var(--muted);font-size:.85rem}
dl{display:grid;grid-template-columns:10rem 1fr;gap:2px 12px;margin:.6rem 0}
dt{color:var(--muted);font-size:.85rem}dd{margin:0}
.obs{font-family:ui-monospace,monospace}.clean{font-weight:600;color:var(--ok)}
.cands{display:flex;flex-wrap:wrap;gap:8px}
.cand{border:1px solid var(--line);border-radius:6px;padding:6px 10px;min-width:14rem}
.cand.chosen{border-color:var(--ok)}
.surface{font-size:1.1rem}.cand ul{margin:.2rem 0 0;padding-left:1.1rem;font-size:.85rem}
.tier{color:var(--muted)}
.badge{font-size:.7rem;border:1px solid var(--ok);color:var(--ok);border-radius:4px;
padding:0 4px;margin-left:4px;vertical-align:middle}
figure{margin:.8rem 0 0}.crop{position:relative;display:inline-block;max-width:100%}
.crop img{display:block;max-width:100%;height:auto;background:#fff}
.hl{position:absolute;outline:2px solid var(--hl);pointer-events:none}
figcaption{color:var(--muted);font-size:.8rem}
.missing{color:var(--accent)}
code{font-family:ui-monospace,monospace}
@media (max-width:600px){dl{grid-template-columns:1fr}}
"""


def render_page(
    rows: list[dict[str, Any]],
    geometry: dict[str, RowGeometry],
    crops: dict[str, Crop],
    published: dict[str, dict[str, Any]] | None,
    check_line: str,
) -> str:
    """The whole standalone review page (inline CSS, no script).

    ``published=None`` means the candidates are the published set, so no entry carries a
    published column and the section-3 cross-reference is omitted.
    """
    esc = html.escape
    compare = published is not None
    published_rows = published or {}
    by_section: dict[str, list[dict[str, Any]]] = {key: [] for key, _, _ in SECTIONS}
    for row in rows:
        by_section[category(row)].append(row)
    nav = "".join(
        f"<li><a href='#{key}'>{esc(title)}</a> — {len(by_section[key])}</li>"
        for key, title, _ in SECTIONS
    )
    moved = (
        [
            row
            for row in by_section["conflict"]
            if (published_rows.get(row["ref"]) or {}).get("qc", {}).get("clean_delta")
            == "nasal-marks-added"
        ]
        if compare
        else []
    )
    parts = []
    for key, title, note in SECTIONS:
        parts.append(f"<h2 id='{key}'>{esc(title)} ({len(by_section[key])})</h2>")
        parts.append(f"<p class=note>{esc(note)}</p>")
        if key == "nasal-added" and moved:
            links = ", ".join(
                f"<a href='#{anchor(row['ref'])}'>{esc(row['ref'])}</a>" for row in moved
            )
            parts.append(
                f"<p class=note>{len(moved)} more rows that the published set marks as "
                f"nasal-marks-added are T2 conflicts and are reviewed in section 3: {links}</p>"
            )
        for row in by_section[key]:
            ref = row["ref"]
            parts.append(
                render_entry(
                    row,
                    geometry.get(ref),
                    crops.get(ref),
                    published_rows.get(ref),
                    compare_published=compare,
                )
            )
    in_place = (
        ""
        if compare
        else "<p class=note>The candidate file is the published clean-ref set, so no entry "
        "carries a separate published column.</p>"
    )
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Clean-ref review packet</title>"
        f"<style>{CSS}</style></head><body><main>"
        "<h1>Cesarino 2013 clean-ref review packet</h1>"
        "<p class=lede>Each entry shows the observed OCR line, every clean candidate with its "
        "citations, and a 200 dpi crop of the printed row. Nothing here is promoted: every "
        "clean_src is a hypothesis with a citation. A citation can differ from the 2013 print: "
        "in the 10-crop sample, 3 printed lines did not match their cited form. Check the crop "
        "before deciding. Record decisions through <code>langpipe review decide</code>.</p>"
        f"<p class=note>{esc(check_line)}</p>{in_place}<nav><ul>{nav}</ul></nav>"
        f"{''.join(parts)}</main></body></html>\n"
    )


def _sort_key(row: dict[str, Any]) -> tuple[int, int]:
    match = re.search(r":p(\d+):l(\d+)$", row["ref"])
    assert match is not None, row["ref"]
    return int(match.group(1)), int(match.group(2))


def build_parser() -> argparse.ArgumentParser:
    """The CLI; ``--candidates`` and ``--published`` both default to the committed clean-ref set."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pdf",
        type=Path,
        default=Path(
            "var/external/marubo_sources/Cesarino_2013_QuandoATerraDeixouDeFalar_MitolMarubo.pdf"
        ),
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        default=DEFAULT_CLEAN_REFS,
        help="rows to review (default: the committed clean-ref set)",
    )
    parser.add_argument(
        "--published",
        type=Path,
        default=DEFAULT_CLEAN_REFS,
        help="published set shown per row; skipped when it is the --candidates file",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("var/artifacts/cesarino_2013/review"))
    parser.add_argument("--ref-prefix", default="cesarino-2013")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--column-gap", type=float, default=ep.COLUMN_GAP)
    parser.add_argument(
        "--column-gap-page",
        type=ep.parse_column_gap_page,
        action="append",
        default=None,
        metavar="PAGE=GAP",
        help="the overrides the candidate file was extracted with (default: the README's five)",
    )
    parser.add_argument("--jobs", type=int, default=8)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    gap_pages = dict(
        args.column_gap_page
        if args.column_gap_page is not None
        else [ep.parse_column_gap_page(value) for value in DEFAULT_COLUMN_GAP_PAGES]
    )
    rows = sorted(
        (
            row
            for row in (
                json.loads(line)
                for line in args.candidates.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
            if row.get("clean_candidates")
        ),
        key=_sort_key,
    )
    # reviewing the published set in place: a per-row published column would only restate the row
    in_place = same_file(args.candidates, args.published)
    published = (
        None
        if in_place
        else {
            row["ref"]: row
            for row in (
                json.loads(line)
                for line in args.published.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        }
    )
    if in_place:
        print("candidates are the published clean-ref set: no published column")

    xml_text = ep.run_pdftotext_bbox(args.pdf)
    pages = ep.parse_bbox_layout(xml_text)
    heights = page_heights(xml_text)
    geometry = recover_geometry(
        pages,
        {row["qc"]["page"] for row in rows},
        args.ref_prefix,
        args.column_gap,
        gap_pages,
    )
    problems = check_segments(rows, geometry)
    matched = len(rows) - len(problems)
    check_line = (
        f"Geometry check: {matched}/{len(rows)} rows have src == recovered segment text "
        f"(extract_columns, column_gap={args.column_gap:g}, column_gap_pages="
        f"{json.dumps({str(k): v for k, v in sorted(gap_pages.items())})})."
    )
    print(check_line)
    if problems:
        for problem in problems[:20]:
            print("  " + problem, file=sys.stderr)
        return 1

    img_dir = args.out_dir / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    crops = {
        row["ref"]: crop_for(
            geometry[row["ref"]],
            pages[geometry[row["ref"]].page - 1][0],
            heights[geometry[row["ref"]].page - 1],
            args.dpi,
        )
        for row in rows
    }
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(
            pool.map(
                lambda ref: render_crop(
                    args.pdf, geometry[ref].page, crops[ref], img_dir / image_name(ref), args.dpi
                ),
                crops,
            )
        )

    (args.out_dir / "index.html").write_text(
        render_page(rows, geometry, crops, published, check_line), encoding="utf-8"
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[category(row)] = counts.get(category(row), 0) + 1
    (args.out_dir / "geometry.json").write_text(
        json.dumps(
            {
                "check": {"matched": matched, "rows": len(rows)},
                "counts": counts,
                "dpi": args.dpi,
                "rows": {
                    ref: {
                        "page": geo.page,
                        "row": geo.row,
                        "source_pt": [geo.source.x0, geo.source.y0, geo.source.x1, geo.source.y1],
                        "target_pt": [geo.target.x0, geo.target.y0, geo.target.x1, geo.target.y1],
                        "crop_px": [
                            crops[ref].x,
                            crops[ref].y,
                            crops[ref].width,
                            crops[ref].height,
                        ],
                        "half": crops[ref].half,
                    }
                    for ref, geo in sorted(geometry.items())
                    if ref in crops
                },
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
