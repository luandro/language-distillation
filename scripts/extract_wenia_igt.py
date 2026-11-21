#!/usr/bin/env python3
"""Extract the interlinear annex of the 2018 *Wenía* article into IGT records.

Cesarino 2018 (*Estudos de Literatura Brasileira Contemporânea* 53) closes with an annex,
"Anexo - Segmentação dos versos 545-585" (PDF pp. 52-53), that prints a stretch of the chant in
three tiers per line group:

1. the verse surface, with several verses on one printed line separated by ``/``;
2. the same verses segmented into morphemes (``-``);
3. a morpheme gloss line, Portuguese lexical glosses plus grammatical labels.

The abbreviations are listed on pp. 54-55 ("Siglas").

The annex is read from word bounding boxes (``pdftotext -bbox``), not ``-layout``: the layout
mode re-wraps long tier lines and inserts blank lines inside a group. With boxes, each printed
line is one line of words; a group is a surface line plus as many tier lines as it takes to
segment and gloss every surface verse, and a tier line that the author's word processor wrapped
(``Ato-vo-`` / ``ki``; ``Wa ravosh`` / ``matxi-ki``) is re-joined by rule:

* a segmented line continues while it ends in a hyphen or while its last verse is a strict prefix
  of the matching surface verse;
* a gloss line continues while it ends in a hyphen.

Every verse is then checked, never repaired:

* ``alignment_ok`` - the segmented tier and the gloss tier have the same number of words, and each
  word has the same number of morphemes (``-``/``=``-separated) as its gloss;
* ``round_trip_ok`` - the segmented tier with hyphens, spaces and quotes removed equals the
  surface tier.

When a printed group's word count disagrees with its gloss count, the gloss cannot be split per
verse without guessing, so those verses carry ``gloss: null`` and the whole printed gloss line in
``qc.gloss_unaligned``.

The annex numbers its verses 545-585, but the same verses are 497-537 in the main text, which
prints each verse beside its free Portuguese translation. Annex units are matched to main-text
verses by their letters; the main text's translation becomes ``por`` and both numbers are kept.
The translations and glosses are Portuguese, so there is no ``eng`` field and none is invented.

These records are morphology evidence for the LKB, **not** parallel training pairs: they must not
be written into ``exports/harvested_parallel/``.

Usage::

    .venv/bin/python scripts/extract_wenia_igt.py \
        --pdf var/external/wenia_2018/wenia_2018.pdf \
        --out exports/igt/cesarino_2018_wenia_igt.jsonl \
        --legend-out exports/igt/cesarino_2018_wenia_igt.legend.json \
        --qa var/artifacts/wenia_igt/qa.json
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SOURCE_KEY = "wenia-2018"
REF_PREFIX = "cesarino-2018"
ANNEX_PAGES = (52, 53)
LEGEND_PAGES = (54, 55)
#: Words whose top edges differ by less than this many points share a line.
LINE_TOLERANCE = 3.0
#: Running heads sit above this y and footers below the next one (points, A4-ish page).
HEADER_MAX_Y = 45.0
FOOTER_MIN_Y = 545.0
#: An annex unit whose letters differ from its main-text verse is still matched above this ratio.
MAIN_TEXT_MIN_RATIO = 0.8
#: Human readings of the 200 dpi page images where the text layer differs from the print. They
#: are attached as ``qc.image_reading`` notes; the observed text-layer tiers are never rewritten.
IMAGE_READINGS = {
    563: (
        "page image prints “Ẽ píti anõnã (surface) and “Ẽ píti anõ-nã (segmented); the text "
        "layer drops the Ẽ from the surface tier and its tilde from the segmented tier"
    ),
}

WORD_RE = re.compile(
    r'xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="[\d.]+">([^<]*)</word>'
)
VERSE_LABEL_RE = re.compile(r"^(\d+)\.$")
QUOTES = "“”\"'‘’"
#: Main-text two-column row: optional verse number, Marúbo cell, 3+ spaces, Portuguese cell.
MAIN_ROW_RE = re.compile(r"^\s*(?:(\d+)\.)?\s*(\S.*?)\s{3,}(\S.*?)\s*$")
#: A footnote reference glued to the end of a Portuguese cell ("Mulheres gavião50").
FOOTNOTE_RE = re.compile(r"(?<=[^\W\d_])(\d{1,3})$")
LEGEND_ROW_RE = re.compile(r"^\s*(\S+)\s{3,}(\S.*?)\s*$")


@dataclass
class Word:
    x: float
    y: float
    text: str


@dataclass
class Line:
    page: int
    y: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)


@dataclass
class Unit:
    """One ``/``-delimited verse unit of the annex, with its three tiers."""

    surface: str
    segmented: str
    gloss: str | None
    page: int
    label: int | None = None
    gloss_unaligned: str | None = None


@dataclass
class MainVerse:
    number: int
    mzr: str
    por: str
    page: int
    por_raw: str | None = None


@dataclass
class Verse:
    units: list[Unit] = field(default_factory=list)


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def letters(text: str) -> str:
    """Letters only: drop hyphens, slashes, quotes, spaces and other punctuation."""
    return "".join(character for character in nfc(text) if character.isalpha())


def words_of(tier: str) -> list[str]:
    """Words of a tier, with ``/`` and quotes removed and punctuation-only tokens dropped."""
    cleaned = tier.replace("/", " ")
    for quote in QUOTES:
        cleaned = cleaned.replace(quote, " ")
    return [token for token in cleaned.split() if any(ch.isalnum() or ch == "?" for ch in token)]


def morphemes(word: str) -> list[str]:
    return [part for part in re.split(r"[-=]", word) if part]


def split_units(text: str) -> list[str]:
    """Split a tier line into its ``/``-delimited units, dropping empty ones."""
    return [unit.strip() for unit in text.split("/") if unit.strip()]


def join_wrapped(previous: str, continuation: str) -> str:
    if previous.endswith("-"):
        return previous + continuation
    return previous + " " + continuation


# --- PDF reading -----------------------------------------------------------------------------


def run_pdftotext(pdf: Path, first: int, last: int, *flags: str) -> str:
    result = subprocess.run(
        ["pdftotext", *flags, "-f", str(first), "-l", str(last), str(pdf), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def parse_bbox(bbox_html: str, first_page: int) -> list[Line]:
    """Group ``pdftotext -bbox`` words into lines, dropping running heads and footers."""
    lines: list[Line] = []
    for offset, page_html in enumerate(bbox_html.split("<page ")[1:]):
        page = first_page + offset
        words = [
            Word(float(x0), float(y0), nfc(html.unescape(text)))
            for x0, y0, _x1, text in WORD_RE.findall(page_html)
        ]
        words = [w for w in words if HEADER_MAX_Y < w.y < FOOTER_MIN_Y]
        page_lines: list[Line] = []
        for word in sorted(words, key=lambda w: (w.y, w.x)):
            if page_lines and abs(page_lines[-1].y - word.y) < LINE_TOLERANCE:
                page_lines[-1].words.append(word)
            else:
                page_lines.append(Line(page, word.y, [word]))
        for line in page_lines:
            line.words.sort(key=lambda w: w.x)
        lines.extend(page_lines)
    return lines


# --- annex groups ----------------------------------------------------------------------------


def parse_group(tier_lines: list[str], page: int) -> tuple[list[Unit], int]:
    """Parse one printed group from the head of ``tier_lines``.

    A group is a surface line followed by (segmented, gloss) chunk pairs: a long surface line is
    printed as several chunk pairs, and any tier line may wrap. The group ends once every surface
    unit has its segmented form and gloss; vertical spacing is not used, because the annex puts
    the same gap inside some groups as between groups. Returns the units and the number of lines
    consumed.
    """
    surface_text = tier_lines[0]
    label: int | None = None
    head, _, rest = surface_text.partition(" ")
    match = VERSE_LABEL_RE.match(head)
    if match:
        label = int(match.group(1))
        surface_text = rest
    surfaces = split_units(surface_text)

    units: list[Unit] = []
    index = 1
    while len(units) < len(surfaces):
        if index >= len(tier_lines):
            raise ValueError(f"p{page}: group ends before every surface unit is segmented")
        segmented = tier_lines[index]
        index += 1
        while index < len(tier_lines) and _segmented_continues(segmented, surfaces, len(units)):
            segmented = join_wrapped(segmented, tier_lines[index])
            index += 1
        if index >= len(tier_lines):
            raise ValueError(f"p{page}: segmented tier without gloss: {segmented!r}")
        gloss = tier_lines[index]
        index += 1
        while index < len(tier_lines) and gloss.endswith("-"):
            gloss = join_wrapped(gloss, tier_lines[index])
            index += 1

        chunk = split_units(segmented)
        gloss_words = gloss.split()
        word_counts = [len(words_of(unit)) for unit in chunk]
        aligned = sum(word_counts) == len(gloss_words)
        start = 0
        for unit_text, count in zip(chunk, word_counts, strict=True):
            position = len(units)
            if position >= len(surfaces):
                raise ValueError(f"p{page}: more segmented units than surface units")
            unit = Unit(
                surface=surfaces[position],
                segmented=unit_text,
                gloss=" ".join(gloss_words[start : start + count]) if aligned else None,
                page=page,
                gloss_unaligned=None if aligned else gloss,
            )
            units.append(unit)
            start += count
    if len(units) != len(surfaces):
        raise ValueError(f"p{page}: {len(surfaces)} surface units but {len(units)} segmented")
    units[0].label = label
    return units, index


def _segmented_continues(segmented: str, surfaces: list[str], done: int) -> bool:
    """True when a segmented tier line was wrapped and the next printed line continues it."""
    if segmented.rstrip().endswith("-"):
        return True
    if segmented.rstrip().endswith("/"):
        return False
    chunk = split_units(segmented)
    position = done + len(chunk) - 1
    if not chunk or position >= len(surfaces):
        return False
    have, want = letters(chunk[-1]).lower(), letters(surfaces[position]).lower()
    return len(have) < len(want) and want.startswith(have)


def read_annex(pdf: Path) -> list[Unit]:
    bbox = run_pdftotext(pdf, ANNEX_PAGES[0], ANNEX_PAGES[1], "-bbox")
    lines = [line for line in parse_bbox(bbox, ANNEX_PAGES[0]) if not line.text.startswith("Anexo")]
    units: list[Unit] = []
    for page in ANNEX_PAGES:
        texts = [line.text for line in lines if line.page == page]
        while texts:
            group, consumed = parse_group(texts, page)
            units.extend(group)
            texts = texts[consumed:]
    return units


# --- main text (free translation) ------------------------------------------------------------


def parse_main_rows(
    layout_pages: list[str], first_page: int
) -> list[tuple[int, int | None, str, str]]:
    """Two-column chant rows of the main text as (pdf page, printed number, mzr, por)."""
    rows: list[tuple[int, int | None, str, str]] = []
    for offset, page_text in enumerate(layout_pages):
        for raw in page_text.splitlines():
            match = MAIN_ROW_RE.match(raw)
            if not match:
                continue
            number, mzr, por = match.groups()
            if any(re.fullmatch(r"[–\-]+", cell) for cell in (mzr, por)):
                continue
            if mzr.isdigit() or "estudos de literatura" in por or "estudos de literatura" in mzr:
                continue
            rows.append((first_page + offset, int(number) if number else None, nfc(mzr), nfc(por)))
    return rows


def number_rows(
    rows: list[tuple[int, int | None, str, str]],
) -> list[MainVerse]:
    """Number every row from the nearest printed verse number (printed every fifth verse)."""
    labelled = [i for i, row in enumerate(rows) if row[1] is not None]
    if not labelled:
        raise ValueError("main text: no printed verse number in range")
    anchor = labelled[0]
    base = rows[anchor][1]
    assert base is not None
    verses: list[MainVerse] = []
    for i, (page, printed, mzr, por) in enumerate(rows):
        number = base + (i - anchor)
        if printed is not None and printed != number:
            raise ValueError(f"main text: printed verse {printed} where {number} was expected")
        clean = FOOTNOTE_RE.sub("", por)
        verses.append(MainVerse(number, mzr, clean, page, por if clean != por else None))
    return verses


def read_main_text(pdf: Path, first_surface: str, last_surface: str) -> list[MainVerse]:
    """Main-text verses from the first annex verse to the last, located by their letters."""
    layout = run_pdftotext(pdf, 1, 999, "-layout").split("\f")
    rows = parse_main_rows(layout, 1)
    first_key, last_key = letters(first_surface).lower(), letters(last_surface).lower()
    starts = [i for i, row in enumerate(rows) if letters(row[2]).lower() == first_key]
    if not starts:
        raise ValueError(f"main text: no row matches the first annex verse {first_surface!r}")
    start = starts[0]
    # A verse number before the start lets the first rows be numbered; widen back to it.
    back = start
    while back > 0 and rows[back][1] is None:
        back -= 1
    end = next(i for i in range(start, len(rows)) if letters(rows[i][2]).lower() == last_key)
    numbered = number_rows(rows[back : end + 1])
    return numbered[start - back :]


# --- matching annex units to main-text verses ------------------------------------------------


def group_into_verses(
    units: list[Unit], main: list[MainVerse]
) -> list[tuple[Verse, MainVerse, float]]:
    """Merge consecutive annex units until their letters cover one main-text verse."""
    result: list[tuple[Verse, MainVerse, float]] = []
    index = 0
    for main_verse in main:
        if index >= len(units):
            raise ValueError(f"main verse {main_verse.number} has no annex unit left")
        want = letters(main_verse.mzr).lower()
        verse = Verse([units[index]])
        index += 1
        while index < len(units):
            have = letters(" ".join(u.surface for u in verse.units)).lower()
            if not (len(have) < len(want) and want.startswith(have)):
                break
            verse.units.append(units[index])
            index += 1
        have = letters(" ".join(u.surface for u in verse.units)).lower()
        ratio = difflib.SequenceMatcher(None, have, want).ratio()
        if ratio < MAIN_TEXT_MIN_RATIO:
            raise ValueError(
                f"annex unit {verse.units[0].surface!r} does not match main verse "
                f"{main_verse.number} {main_verse.mzr!r} (ratio {ratio:.2f})"
            )
        result.append((verse, main_verse, ratio))
    if index != len(units):
        raise ValueError(f"{len(units) - index} annex units left after the main-text range")
    return result


# --- checks ----------------------------------------------------------------------------------


def alignment_problems(segmented: str, gloss: str) -> list[str]:
    """Word and morpheme count mismatches between a segmented tier and its gloss."""
    seg_words, gloss_words = words_of(segmented), gloss.split()
    if len(seg_words) != len(gloss_words):
        return [f"words: {len(seg_words)} segmented vs {len(gloss_words)} gloss"]
    problems = []
    for word, label in zip(seg_words, gloss_words, strict=True):
        if len(morphemes(word)) != len(morphemes(label)):
            problems.append(f"{word} ({len(morphemes(word))}) vs {label} ({len(morphemes(label))})")
    return problems


def round_trip_ok(segmented: str, surface: str) -> bool:
    """Segmented letters equal surface letters; case is orthographic (``Amaĩnõ``/``a-maĩnõ``)."""
    return letters(segmented).lower() == letters(surface).lower()


def build_records(pdf: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    units = read_annex(pdf)
    first_label = units[0].label
    if first_label is None:
        raise ValueError("annex: first group carries no verse number")
    main = read_main_text(pdf, units[0].surface, units[-1].surface)
    records: list[dict[str, Any]] = []
    qa: dict[str, Any] = {
        "units": len(units),
        "verses": 0,
        "alignment_mismatches": [],
        "round_trip_mismatches": [],
        "main_text_mismatches": [],
        "merged_units": [],
        "label_mismatches": [],
    }
    for offset, (verse, main_verse, ratio) in enumerate(group_into_verses(units, main)):
        number = first_label + offset
        ref = f"{REF_PREFIX}:v{number}"
        # A printed margin number must head the verse it numbers.
        for position, unit in enumerate(verse.units):
            if unit.label is not None and (position or unit.label != number):
                qa["label_mismatches"].append({"ref": ref, "printed": unit.label})
        surface = " ".join(u.surface for u in verse.units)
        segmented = " ".join(u.segmented for u in verse.units)
        glosses = [u.gloss for u in verse.units]
        gloss = None if None in glosses else " ".join(g for g in glosses if g)
        unaligned = sorted({u.gloss_unaligned for u in verse.units if u.gloss_unaligned})
        problems = (
            alignment_problems(segmented, gloss)
            if gloss is not None
            else [f"printed gloss line does not split per verse: {unaligned[0]!r}"]
        )
        trip = round_trip_ok(segmented, surface)
        pages = sorted({u.page for u in verse.units})
        qc: dict[str, Any] = {"alignment_ok": not problems, "round_trip_ok": trip}
        if problems:
            qc["alignment_problems"] = problems
            qa["alignment_mismatches"].append({"ref": ref, "problems": problems})
        if not trip:
            qa["round_trip_mismatches"].append(
                {"ref": ref, "surface": surface, "segmented": segmented}
            )
        if unaligned:
            qc["gloss_unaligned"] = unaligned[0]
        if len(verse.units) > 1:
            qc["annex_units"] = [u.surface for u in verse.units]
            qa["merged_units"].append({"ref": ref, "units": qc["annex_units"]})
        if ratio < 1.0:
            qc["main_text_letter_ratio"] = round(ratio, 3)
            qa["main_text_mismatches"].append(
                {"ref": ref, "annex": surface, "main_text": main_verse.mzr}
            )
        if main_verse.por_raw is not None:
            qc["por_raw"] = main_verse.por_raw
        if number in IMAGE_READINGS:
            qc["image_reading"] = IMAGE_READINGS[number]
        records.append(
            {
                "ref": ref,
                "mzr": segmented,
                "gloss": gloss,
                "por": main_verse.por,
                "surface": surface,
                "source": {
                    "source_key": SOURCE_KEY,
                    "section": "Anexo - Segmentação dos versos 545-585",
                    "pdf_pages": pages,
                    "annex_verse": number,
                    "main_text_verse": main_verse.number,
                    "main_text_pdf_page": main_verse.page,
                    "main_text_mzr": main_verse.mzr,
                },
                "qc": qc,
            }
        )
    qa["verses"] = len(records)
    return records, qa


# --- legend ----------------------------------------------------------------------------------


def parse_legend(layout_pages: list[str], first_page: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for offset, page_text in enumerate(layout_pages):
        for raw in page_text.splitlines():
            match = LEGEND_ROW_RE.match(raw)
            if not match:
                continue
            abbreviation, expansion = match.groups()
            if re.fullmatch(r"[–\-]+", expansion) or "estudos de literatura" in expansion:
                continue
            if abbreviation.isdigit() or re.fullmatch(r"[–\-]+", abbreviation):
                continue
            entries.append(
                {
                    "abbreviation": nfc(abbreviation),
                    "expansion": nfc(expansion),
                    "pdf_page": first_page + offset,
                }
            )
    return entries


def unlisted_labels(records: list[dict[str, Any]], legend: list[dict[str, Any]]) -> list[str]:
    """Grammatical labels used in the glosses that the legend does not list."""
    keys = {entry["abbreviation"].rstrip(".") for entry in legend}
    found: set[str] = set()
    for record in records:
        texts = [record["gloss"]] if record["gloss"] else []
        texts.append(record["qc"].get("gloss_unaligned") or "")
        for text in texts:
            for part in re.split(r"[\s\-=.]+", text):
                core = re.sub(r"^(\d[a-z]*)", "", part)  # person prefix: 3pDEM -> DEM
                core = re.sub(r"(trans|intr)$", "", core)  # AUXtrans -> AUX
                core = re.sub(r"^[a-zçãõáéíóú]+(?=[A-Z])", "", core)  # caçarLE -> LE
                if sum(ch.isupper() for ch in core) < 2:
                    continue
                if part in keys or core in keys or any(core.startswith(k) for k in keys):
                    continue
                found.add(part)
    return sorted(found)


def build_legend(pdf: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    layout = run_pdftotext(pdf, LEGEND_PAGES[0], LEGEND_PAGES[1], "-layout").split("\f")
    text = "\f".join(layout)
    if "Siglas" not in text:
        raise ValueError("legend pages carry no 'Siglas' heading")
    entries = parse_legend(layout, LEGEND_PAGES[0])
    return {
        "source_key": SOURCE_KEY,
        "section": "Siglas",
        "pdf_pages": list(range(LEGEND_PAGES[0], LEGEND_PAGES[1] + 1)),
        "language_of_expansions": "por",
        "abbreviations": entries,
        "used_but_unlisted": unlisted_labels(records, entries),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--legend-out", type=Path, required=True)
    parser.add_argument("--qa", type=Path)
    args = parser.parse_args(argv)
    if "harvested_parallel" in args.out.parts:
        parser.error("IGT records are morphology evidence, not parallel pairs")
    records, qa = build_records(args.pdf)
    legend = build_legend(args.pdf, records)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    args.legend_out.write_text(
        json.dumps(legend, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    qa["legend_entries"] = len(legend["abbreviations"])
    qa["used_but_unlisted"] = legend["used_but_unlisted"]
    if args.qa is not None:
        args.qa.parent.mkdir(parents=True, exist_ok=True)
        args.qa.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(records)} IGT verses to {args.out}")
    print(json.dumps(qa, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(argv=sys.argv[1:]))
