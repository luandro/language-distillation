#!/usr/bin/env python3
"""Extract learner-quality parallel and IGT data from source PDFs.

Four extractors, all deterministic and offline once the PDF text is available:

``facing``
    Two-column facing-translation books (Marúbo source column + Portuguese translation
    column). Uses ``pdftotext -bbox-layout`` word boxes to rebuild each column, groups
    lines into paragraphs, pairs paragraphs by position on the page, and validates that
    the left column looks like Marúbo and the right like Portuguese. Emits records shaped
    for ``exports/harvested_parallel/*_parallel.jsonl`` (``ref``/``src``/``tgt``).

``columns``
    Interleaved line-by-line chant/cantillation books: a narrow source column and its
    translation column printed side by side inside each book page, with two book pages
    per scanned sheet. Pairs segments *by visual row* (y position with a per-page baseline
    shift), never by rank, so a missing translation loses a pair instead of shifting all
    of them. Repairs deterministic Portuguese OCR damage (``~``/``\\:``/``<;`` → ``ç``,
    footnote superscripts) and records every repair. Marúbo OCR damage is **not**
    repaired: it is measured and flagged, because inventing missing diacritics would be
    inventing target-language forms.

``igt``
    Numbered interlinear clauses in an appendix (Marúbo tier, gloss tier, free
    translation). Emits ``ref``/``mzr``/``gloss``/``eng`` records for morphology evidence.
    These are *not* mzr↔por pairs, so they must not be written into the training export.

``table``
    Born-digital two-column chant tables (a journal or book typeset from a digital
    manuscript). Reads ``pdftotext -layout`` instead of word boxes: the two cells of a row
    are already on one reconstructed line, so the pair is read out of the source rather than
    inferred from baselines, and the printed margin line numbers become locators. No OCR
    repair is needed because there is no OCR layer - the Marúbo diacritics are simply there.

Usage::

    uv run python scripts/extract_pairs.py facing \\
        --pdf var/external/vana_rasi/vana_rasi.pdf \\
        --out exports/harvested_parallel/vana_rasi_2026_parallel.jsonl \\
        --qa var/artifacts/vana_rasi/facing_qa.json

    uv run python scripts/extract_pairs.py columns \\
        --pdf var/external/marubo_sources/Cesarino_2013_QuandoATerraDeixouDeFalar_MitolMarubo.pdf \\
        --ref-prefix cesarino-2013 \\
        --mzr-reference 'var/external/scriptureearth/mzr/*.usfm' \\
        --out exports/parallel_candidates/cesarino_2013_columns.jsonl \\
        --qa var/artifacts/cesarino_2013/columns_qa.json

    uv run python scripts/extract_pairs.py igt \\
        --pdf var/external/smith_2021_twu/smith_2021_twu.pdf \\
        --out exports/igt/smith_2021_twu_igt.jsonl \\
        --qa var/artifacts/smith_2021_twu/igt_qa.json
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MARUBO_MARKS = frozenset("ẽĩũɨ")
MARUBO_HINTS = frozenset(
    [
        "iki",
        "ikí",
        "aská",
        "asho",
        "ãwẽ",
        "awe",
        "mãinõ",
        "mainõ",
        "vano",
        "vana",
        "yora",
        "nawa",
        "shovia",
        "rasĩ",
        "ato",
        "ea",
        "mĩ",
        "mia",
        "nukẽ",
        "vake",
        "westi",
        "oni",
        "namã",
        "namasho",
        "keyo",
        "shovo",
        "iyã",
        "vãiya",
        "viki",
    ]
)
PT_STOPWORDS = frozenset(
    [
        "a",
        "ao",
        "aos",
        "as",
        "com",
        "como",
        "da",
        "das",
        "de",
        "do",
        "dos",
        "e",
        "em",
        "entre",
        "essa",
        "esse",
        "esta",
        "este",
        "foi",
        "mais",
        "mas",
        "na",
        "nas",
        "no",
        "nos",
        "não",
        "o",
        "os",
        "ou",
        "para",
        "pela",
        "pelo",
        "por",
        "que",
        "se",
        "sem",
        "são",
        "sobre",
        "também",
        "um",
        "uma",
        "é",
    ]
)
_XHTML = "{http://www.w3.org/1999/xhtml}"


@dataclass(frozen=True)
class Word:
    """One word bounding box on a page."""

    text: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass
class Line:
    """A group of words sharing a baseline."""

    y: float
    x_start: float
    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words).strip()


def parse_bbox_layout(xml_text: str) -> list[tuple[float, list[Word]]]:
    """Return ``(page_width, words)`` for every page of a ``pdftotext -bbox-layout`` dump."""
    root = ET.fromstring(xml_text)
    pages: list[tuple[float, list[Word]]] = []
    for page in root.iter(f"{_XHTML}page"):
        width = float(page.get("width", "0") or 0)
        words = [
            Word(
                text=(word.text or "").strip(),
                x_min=float(word.get("xMin", "0") or 0),
                y_min=float(word.get("yMin", "0") or 0),
                x_max=float(word.get("xMax", "0") or 0),
                y_max=float(word.get("yMax", "0") or 0),
            )
            for word in page.iter(f"{_XHTML}word")
            if (word.text or "").strip()
        ]
        pages.append((width, words))
    return pages


def group_lines(words: list[Word], tolerance: float = 3.0) -> list[Line]:
    """Group words into lines by vertical position, sorted top-to-bottom."""
    lines: list[Line] = []
    for word in sorted(words, key=lambda w: (w.y_min, w.x_min)):
        target = None
        for line in reversed(lines[-3:]):
            if abs(line.y - word.y_min) <= tolerance:
                target = line
                break
        if target is None:
            lines.append(Line(y=word.y_min, x_start=word.x_min, words=[word]))
        else:
            target.words.append(word)
            target.x_start = min(target.x_start, word.x_min)
            target.y = min(target.y, word.y_min)
    for line in lines:
        line.words.sort(key=lambda w: w.x_min)
    return sorted(lines, key=lambda line: line.y)


def split_columns(words: list[Word], page_width: float) -> tuple[list[Word], list[Word]] | None:
    """Split a page into left/right column words, or None when it is not a two-column page."""
    if page_width <= 0 or len(words) < 8:
        return None
    boundary = page_width / 2.0
    straddling = sum(1 for word in words if word.x_min < boundary < word.x_max)
    left = [word for word in words if word.x_max <= boundary + 2]
    right = [word for word in words if word.x_min >= boundary - 2]
    if straddling > max(3, len(words) // 50):
        return None
    if len(left) < 3 or len(right) < 3:
        return None
    return left, right


def paragraphs(lines: list[Line], indent_threshold: float = 6.0) -> list[str]:
    """Join lines into paragraphs using indentation and vertical gaps."""
    if not lines:
        return []
    gaps = [lines[i + 1].y - lines[i].y for i in range(len(lines) - 1)]
    positive = [gap for gap in gaps if gap > 0]
    typical = sorted(positive)[len(positive) // 2] if positive else 12.0
    base_x = min(line.x_start for line in lines)
    out: list[str] = []
    current: list[str] = []
    for index, line in enumerate(lines):
        starts_paragraph = bool(current) and (
            line.x_start - base_x > indent_threshold
            or (index > 0 and line.y - lines[index - 1].y > typical * 1.6)
        )
        if starts_paragraph:
            out.append(" ".join(current).strip())
            current = []
        current.append(line.text)
    if current:
        out.append(" ".join(current).strip())
    return [block for block in out if block]


def looks_marubo(text: str) -> bool:
    """Heuristic: Marúbo orthography or a low Portuguese-stopword ratio."""
    if len(text) < 12:
        return False
    if any(character in MARUBO_MARKS for character in text):
        return True
    tokens = re.findall(r"[A-Za-zÀ-ÿ]{2,}", text.lower())
    if not tokens:
        return False
    portuguese = sum(1 for token in tokens if token in PT_STOPWORDS)
    return portuguese / len(tokens) < 0.06


def looks_portuguese(text: str) -> bool:
    """Heuristic: Portuguese stopwords or Portuguese-only diacritics."""
    if len(text) < 12:
        return False
    tokens = re.findall(r"[A-Za-zÀ-ÿ]{2,}", text.lower())
    if len(tokens) >= 3:
        portuguese = sum(1 for token in tokens if token in PT_STOPWORDS)
        if portuguese / len(tokens) >= 0.15:
            return True
    return "ç" in text


def extract_facing(
    pages: list[tuple[float, list[Word]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pair facing columns page by page; return records and a QA summary."""
    records: list[dict[str, Any]] = []
    qa: dict[str, Any] = {
        "pages": len(pages),
        "two_column_pages": 0,
        "skipped_single_column": 0,
        "pairs_found": 0,
        "pairs_rejected": 0,
        "paragraph_count_mismatch_pages": 0,
        "rejected": [],
    }
    for page_number, (width, words) in enumerate(pages, start=1):
        split = split_columns(words, width)
        if split is None:
            qa["skipped_single_column"] += 1
            continue
        qa["two_column_pages"] += 1
        left_paras = paragraphs(group_lines(split[0]))
        right_paras = paragraphs(group_lines(split[1]))
        if len(left_paras) != len(right_paras):
            qa["paragraph_count_mismatch_pages"] += 1
        for index, (source, target) in enumerate(zip(left_paras, right_paras, strict=False)):
            if looks_marubo(source) and looks_portuguese(target):
                records.append(
                    {
                        "ref": f"vana-rasi:p{page_number}:p{index + 1}",
                        "src": unicodedata.normalize("NFC", source),
                        "tgt": unicodedata.normalize("NFC", target),
                        "eng": "",
                    }
                )
                qa["pairs_found"] += 1
            else:
                qa["pairs_rejected"] += 1
                if len(qa["rejected"]) < 20:
                    qa["rejected"].append(
                        {
                            "page": page_number,
                            "para": index + 1,
                            "src": source[:90],
                            "tgt": target[:90],
                        }
                    )
    return records, qa


_CLAUSE_RE = re.compile(r"^(\d{1,3})\s+(\S.*)$")
_QUOTE_RE = re.compile(r"^[‘“'\"]")
_GLOSS_TOKEN = re.compile(
    r"^(?:[A-Z][A-Z0-9.:=/<>~-]*|[a-z0-9.]*-[A-Z][A-Z0-9.]*|[0-9]+(?:SG|PL)?)$"
)
_HEADER_RE = re.compile(r"^(Appendix [A-C]|Appendices|References|Abbreviations)\b")
ENGLISH_STOPWORDS = frozenset(
    [
        "the",
        "and",
        "of",
        "to",
        "in",
        "is",
        "that",
        "for",
        "with",
        "this",
        "are",
        "as",
        "on",
        "at",
        "be",
        "by",
        "from",
        "it",
        "an",
        "or",
        "not",
        "which",
        "was",
        "were",
        "has",
        "have",
        "can",
        "these",
        "those",
        "their",
        "they",
    ]
)


def looks_english(text: str) -> bool:
    """True when a line reads as English prose rather than a Marúbo tier."""
    tokens = re.findall(r"[A-Za-z]{2,}", text.lower())
    if len(tokens) < 4:
        return False
    english = sum(1 for token in tokens if token in ENGLISH_STOPWORDS)
    return english / len(tokens) >= 0.2


def looks_like_gloss(line: str) -> bool:
    """True when most tokens look like morpheme glosses rather than running text."""
    tokens = [token for token in line.split() if token not in {":", "=", "/", ">", "<", "~"}]
    if len(tokens) < 2:
        return False
    gloss = sum(1 for token in tokens if _GLOSS_TOKEN.match(token))
    return gloss / len(tokens) >= 0.6


def looks_like_translation(line: str) -> bool:
    """Free translations start with a quote or end in one."""
    stripped = line.strip()
    return bool(_QUOTE_RE.match(stripped)) or stripped.endswith(("’", "”", "')"))


def extract_igt_lines(
    lines: list[tuple[float, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse numbered IGT clauses from ordered ``(x_start, text)`` lines."""
    records: list[dict[str, Any]] = []
    qa: dict[str, Any] = {"clauses_found": 0, "records": 0, "rejected": 0, "rejected_samples": []}
    clause: str | None = None
    appendix = "B"
    vernacular: list[str] = []
    gloss: list[str] = []
    translation: list[str] = []
    last_number = 0

    def flush() -> None:
        nonlocal clause, vernacular, gloss, translation
        if clause is None:
            return
        source = " ".join(vernacular).strip()
        gloss_text = " ".join(gloss).strip()
        target = " ".join(translation).strip()
        clean = (
            source
            and gloss_text
            and target
            and not re.search(r"[A-Z]{2,}", source)
            and not looks_portuguese(source)
            and not looks_english(source)
            and not looks_like_gloss(source)
        )
        if clean:
            records.append(
                {
                    "ref": f"smith-2021-twu:(appendix {appendix} clause {clause})",
                    "mzr": unicodedata.normalize("NFC", source),
                    "gloss": unicodedata.normalize("NFC", gloss_text),
                    "eng": unicodedata.normalize("NFC", target),
                }
            )
            qa["records"] += 1
        else:
            qa["rejected"] += 1
            if len(qa["rejected_samples"]) < 10:
                qa["rejected_samples"].append(
                    {"clause": clause, "src": source[:80], "tgt": target[:80]}
                )
        clause, vernacular, gloss, translation = None, [], [], []

    started = False
    for x_start, text in lines:
        stripped = text.strip()
        if not started:
            if stripped.startswith("Appendix B"):
                started = True
            continue
        if not stripped:
            continue
        heading = _HEADER_RE.match(stripped)
        if heading:
            flush()
            if stripped.startswith("Appendix C"):
                appendix = "C"
            continue
        match = _CLAUSE_RE.match(stripped)
        if match and x_start < 90:
            number = int(match.group(1))
            if last_number == 0 or number in (last_number, last_number + 1):
                flush()
                clause = match.group(1)
                last_number = number
                qa["clauses_found"] += 1
                remainder = match.group(2).strip()
                if remainder:
                    vernacular.append(remainder)
                continue
        if clause is None:
            continue
        if looks_like_translation(stripped):
            translation.append(stripped)
        elif looks_like_gloss(stripped):
            gloss.append(stripped)
        elif translation:
            if stripped.lower().startswith(("cf.", "lit.", "(")):
                translation.append(stripped)
        else:
            vernacular.append(stripped)
    flush()
    return records, qa


def extract_monolingual(
    pages: list[tuple[float, list[Word]]], min_chars: int = 120
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collect Marúbo-only prose blocks (no translation column) with page locators."""
    blocks: list[dict[str, Any]] = []
    qa: dict[str, Any] = {"pages": len(pages), "blocks": 0, "dropped_short": 0}
    for page_number, (width, words) in enumerate(pages, start=1):
        split = split_columns(words, width)
        columns = split if split is not None else (words,)
        current: list[str] = []
        lines: list[Line] = []
        for column in columns:
            lines.extend(group_lines(list(column)))
        for line in lines:
            text = line.text.strip()
            if not text or re.fullmatch(r"\d{1,3}", text):
                continue
            tokens = {token.lower() for token in re.findall(r"[A-Za-zÀ-ÿ]{2,}", text)}
            hints = len(tokens & MARUBO_HINTS)
            is_marubo = (
                (
                    any(character in MARUBO_MARKS for character in text)
                    or hints >= 2
                    or bool(re.search(r"\b[a-zà-ÿ]+-[a-zà-ÿ]+", text))
                )
                and not looks_portuguese(text)
                and not looks_english(text)
            )
            if is_marubo:
                current.append(text)
            elif current:
                joined = " ".join(current).strip()
                if len(joined) >= min_chars:
                    blocks.append(
                        {
                            "ref": f"vana-rasi:p{page_number}:b{qa['blocks'] + 1}",
                            "text": unicodedata.normalize("NFC", joined),
                            "eng": "",
                        }
                    )
                    qa["blocks"] += 1
                else:
                    qa["dropped_short"] += 1
                current = []
        if current:
            joined = " ".join(current).strip()
            if len(joined) >= min_chars:
                blocks.append(
                    {
                        "ref": f"vana-rasi:p{page_number}:b{qa['blocks'] + 1}",
                        "text": unicodedata.normalize("NFC", joined),
                        "eng": "",
                    }
                )
                qa["blocks"] += 1
            else:
                qa["dropped_short"] += 1
    return blocks, qa


def pages_to_lines(pages: list[tuple[float, list[Word]]]) -> list[tuple[float, str]]:
    """Flatten pages into ordered ``(x_start, text)`` lines, dropping page furniture."""
    out: list[tuple[float, str]] = []
    for _, words in pages:
        for line in group_lines(words):
            text = line.text
            if not text:
                continue
            if re.fullmatch(r"\d{1,3}", text):
                continue
            out.append((line.x_start, text))
    return out


# --------------------------------------------------------------------------- #
# ``columns``: line-interleaved chant/translation columns inside scanned spreads
# --------------------------------------------------------------------------- #

SEGMENT_GAP = 25.0
MIN_SEGMENT_WIDTH = 30.0
MAX_SEGMENT_WIDTH = 340.0
LINE_TOLERANCE = 3.0
COLUMN_GAP = 60.0
COLUMN_MIN_SEGMENTS = 5
COLUMN_PT_RATIO = 0.10
MAX_ROW_SHIFT = 3.0
SHIFT_SEARCH = 20.0
SHIFT_STEP = 0.5
X_DELTA_RANGE = (80.0, 400.0)
MIN_PAIRS_PER_PAGE = 3
#: A segment wider than this fraction of the page is page furniture (a footnote, a running
#: head, a rule), not a chant line. Footnotes sitting on the chant baseline were otherwise
#: paired with translations, which is how a prose footnote could enter the record.
MAX_WIDTH_FRACTION = 0.5
PT_OCR_MARKERS = ("~", "\\", "<;", "c;")
_SEGMENT_ALPHA = re.compile(r"[^\W\d_]", re.UNICODE)
_PT_WORD = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
#: Margin line number printed before the chant line, either alone ("140") or glued to the
#: line ("140. Ato awe shavoyai"). Chants number every fifth line, so it is a locator, not
#: part of the verse.
_MARGIN_NUMBER_RE = re.compile(r"\d{1,3}")
_LEADING_NUMBER_RE = re.compile(r"^(\d{1,3})\.\s+(?=[^\W\d_])")
_REF_SUFFIXES = frozenset({".usfm", ".txt", ".jsonl", ".tsv"})

#: Ordered deterministic repairs for the Portuguese OCR layer of the 2013 scan.
#: Every rule is a pure string rewrite: no candidate is guessed and discarded.
PT_OCR_RULES: tuple[tuple[str, str, str], ...] = (
    (r"(?:\\=|\\:|\\'\.|\\|<;|c;)", "ç", "cedilla-marker"),
    (r"~", "ç", "cedilla-as-tilde"),
    (r"ç(?:ªº|aO|ao)", "ção", "nasal-diphthong"),
    (r"ç(?:Ües|6es|óes|oes|Oes)", "ções", "nasal-plural"),
    (r"ç(?:ª|Ü)", "ç", "stray-vowel-glyph"),
    (r"(?<=[^\W\d_])1(?=[^\W\d_])", "i", "digit-as-i"),
    (r"(?<=[^\W\d_])\d+$", "", "footnote-superscript"),
    # a footnote marker can also sit after a closing quote ("...parece”37"), where the
    # letter-bound rule above does not fire
    (r"(?<=[”\"'’])\d{1,2}$", "", "footnote-superscript"),
    (r"\s+\d{1,2}$", "", "footnote-superscript-spaced"),
)
PT_OCR_RESIDUAL = re.compile(r"[~\\<;]|c;")
_INDEX_ARTIFACTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<=[a-zà-ÿ])l(?=[a-zà-ÿ])"), "l-for-nasal"),
    (re.compile(r"(?<=[a-zà-ÿ])T(?=[a-zà-ÿ])"), "T-for-nasal"),
    (re.compile(r"(?<=[a-zà-ÿ])\d"), "digit-in-token"),
    (re.compile(r"[~\\]"), "ocr-control"),
)


@dataclass(frozen=True)
class Segment:
    """A run of words on one visual row that is not separated by a wide gap."""

    x_min: float
    x_max: float
    y: float
    text: str

    @property
    def width(self) -> float:
        """Horizontal extent in points."""
        return self.x_max - self.x_min


def line_segments(line: Line, gap: float = SEGMENT_GAP) -> list[Segment]:
    """Split one visual row into segments separated by gaps wider than ``gap`` points."""
    words = sorted(line.words, key=lambda word: word.x_min)
    groups: list[list[Word]] = []
    for word in words:
        if groups and word.x_min - max(item.x_max for item in groups[-1]) > gap:
            groups.append([word])
        elif groups:
            groups[-1].append(word)
        else:
            groups.append([word])
    return [
        Segment(
            x_min=min(word.x_min for word in group),
            x_max=max(word.x_max for word in group),
            y=line.y,
            text=" ".join(word.text for word in group).strip(),
        )
        for group in groups
    ]


def portuguese_ratio(text: str) -> float:
    """Fraction of alphabetic tokens that are Portuguese function words."""
    tokens = _PT_WORD.findall(text.lower())
    if not tokens:
        return 0.0
    return sum(1 for token in tokens if token in PT_STOPWORDS) / len(tokens)


def classify_segment(segment: Segment) -> str:
    """Classify a segment as ``por`` when it carries Portuguese evidence, else ``mzr``."""
    text = segment.text
    if not _SEGMENT_ALPHA.search(text):
        return "num" if re.search(r"\d", text) else "other"
    if any(marker in text for marker in PT_OCR_MARKERS):
        return "por"
    return "por" if portuguese_ratio(text) >= COLUMN_PT_RATIO else "mzr"


def cluster_columns(segments: list[Segment], gap: float = COLUMN_GAP) -> list[list[Segment]]:
    """Group segments into vertical bands by their left edge.

    Chant columns are narrow and flush left, so every column is a cluster of segments that
    share an ``x_min``. A single line cannot decide whether a column is vernacular or
    Portuguese ("Pajé Samaúma" has no Portuguese function word in it) but the whole column
    can, which is why the decision is made per cluster, not per line.
    """
    ordered = sorted(segments, key=lambda segment: segment.x_min)
    columns: list[list[Segment]] = []
    for segment in ordered:
        if columns and segment.x_min - max(item.x_min for item in columns[-1]) <= gap:
            columns[-1].append(segment)
        else:
            columns.append([segment])
    return columns


def column_kind(column: list[Segment]) -> str:
    """Classify a whole column as ``mzr``, ``por`` or ``other`` from aggregate evidence.

    The decision is per column because a single chant line cannot decide it ("Pajé Samaúma"
    has no Portuguese function word in it), and it is taken over the whole column because
    translated poetry lines often carry no function word either. Page furniture that would
    skew the ratio (footnotes, running heads, section titles) is removed before clustering
    by :data:`MAX_WIDTH_FRACTION`; the ratio itself is unchanged from the 2013 extraction.
    """
    if len(column) < COLUMN_MIN_SEGMENTS:
        return "other"
    if any(marker in segment.text for marker in PT_OCR_MARKERS for segment in column):
        return "por"
    joined = " ".join(segment.text for segment in column)
    return "por" if portuguese_ratio(joined) >= COLUMN_PT_RATIO else "mzr"


def pair_columns(
    columns: list[list[Segment]],
) -> list[tuple[list[Segment], list[Segment]]]:
    """Pair each vernacular column with the translation column immediately to its right."""
    kinds = [column_kind(column) for column in columns]
    pairs: list[tuple[list[Segment], list[Segment]]] = []
    for index, kind in enumerate(kinds):
        if kind != "mzr":
            continue
        source_x = sum(segment.x_min for segment in columns[index]) / len(columns[index])
        for offset in range(index + 1, len(columns)):
            if kinds[offset] != "por":
                continue
            target_x = sum(segment.x_min for segment in columns[offset]) / len(columns[offset])
            if X_DELTA_RANGE[0] <= target_x - source_x <= X_DELTA_RANGE[1]:
                pairs.append((columns[index], columns[offset]))
            break
    return pairs


def _x_delta_ok(source: Segment, target: Segment) -> bool:
    """True when the horizontal offset between two segments is a plausible column offset."""
    low, high = X_DELTA_RANGE
    return low <= target.x_min - source.x_min <= high


def estimate_row_shift(source: list[Segment], target: list[Segment]) -> float:
    """Estimate the baseline shift between a vernacular row and its translation row.

    The two columns of a printed chant page are typeset with a constant vertical offset
    that varies from page to page. Instead of assuming an offset, search for the one that
    pairs the most segments, so a page shift cannot silently shift every pair.
    """
    steps = int(round(SHIFT_SEARCH / SHIFT_STEP))
    candidates: list[tuple[int, float, float]] = []
    for step in range(-steps, steps + 1):
        shift = step * SHIFT_STEP
        deltas = [
            min(
                (
                    abs(other.y - (row.y + shift))
                    for other in target
                    if _x_delta_ok(row, other) and abs(other.y - (row.y + shift)) <= MAX_ROW_SHIFT
                ),
                default=None,
            )
            for row in source
        ]
        matched = [delta for delta in deltas if delta is not None]
        if not matched:
            candidates.append((0, abs(shift), shift))
            continue
        candidates.append((-len(matched), round(sum(matched), 3), shift))
    candidates.sort()
    return candidates[0][2]


def match_rows(
    source: list[Segment], target: list[Segment], shift: float
) -> list[tuple[Segment, Segment]]:
    """Pair vernacular and translation segments by row, preserving reading order."""
    ordered_source = sorted(source, key=lambda segment: (segment.y, segment.x_min))
    ordered_target = sorted(target, key=lambda segment: (segment.y, segment.x_min))
    used: set[int] = set()
    pairs: list[tuple[Segment, Segment]] = []
    last_index = -1
    for row in ordered_source:
        candidates = [
            (abs((other.y) - (row.y + shift)), index, other)
            for index, other in enumerate(ordered_target)
            if index > last_index
            and index not in used
            and _x_delta_ok(row, other)
            and abs(other.y - (row.y + shift)) <= MAX_ROW_SHIFT
        ]
        if not candidates:
            continue
        candidates.sort()
        _, index, other = candidates[0]
        used.add(index)
        last_index = index
        pairs.append((row, other))
    return pairs


def repair_portuguese_ocr(text: str) -> tuple[str, list[str]]:
    """Apply the deterministic Portuguese OCR repairs; return the text and rule labels."""
    repaired = text
    applied: list[str] = []
    for pattern, replacement, label in PT_OCR_RULES:
        updated = re.sub(pattern, replacement, repaired)
        if updated != repaired:
            applied.append(label)
            repaired = updated
    return repaired, applied


def portuguese_residual_damage(text: str) -> list[str]:
    """Tokens of a repaired Portuguese line that still carry OCR damage markers."""
    return [
        token for token in text.split() if PT_OCR_RESIDUAL.search(token) or re.search(r"\d", token)
    ]


def load_reference_vocabulary(patterns: list[str]) -> set[str]:
    """Build a lowercase reference vocabulary from UTF-8 text, USFM, JSONL or TSV files.

    Used to *measure* how much of an OCR'd vernacular line is attested elsewhere, never to
    rewrite it: an unattested token is reported as a review flag, not corrected.
    """
    vocabulary: set[str] = set()
    for pattern in patterns:
        for raw_path in sorted(glob.glob(pattern)):
            path = Path(raw_path)
            if not path.is_file() or path.suffix.lower() not in _REF_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix.lower() == ".usfm":
                text = re.sub(r"\\[a-z0-9-]+\*?", " ", text)
            elif path.suffix.lower() == ".jsonl":
                chunks = []
                for line in text.splitlines():
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    for key in ("src", "mzr", "form", "lemma", "headword"):
                        value = record.get(key)
                        if isinstance(value, str):
                            chunks.append(value)
                text = " ".join(chunks)
            elif path.suffix.lower() == ".tsv":
                text = " ".join(line.split("\t")[0] for line in text.splitlines())
            vocabulary.update(token.lower() for token in _PT_WORD.findall(text))
    return vocabulary


def vernacular_qc(text: str, vocabulary: set[str] | None = None) -> dict[str, Any]:
    """Describe the OCR state of a vernacular (Marúbo) line without changing it."""
    tokens = _PT_WORD.findall(text)
    flags = sorted({label for pattern, label in _INDEX_ARTIFACTS if pattern.search(text)})
    qc: dict[str, Any] = {"src_tokens": len(tokens), "src_flags": flags}
    if vocabulary:
        unattested = [token for token in tokens if token.lower() not in vocabulary]
        if unattested:
            qc["src_unattested"] = unattested
    return qc


def _margin_numbers(line_segments_: list[Segment]) -> list[tuple[float, float, str]]:
    """Margin line numbers as ``(y, x_max, text)``; they are narrower than any text column."""
    numbers = []
    for segment in line_segments_:
        stripped = segment.text.strip().rstrip(".")
        if segment.width <= 25 and _MARGIN_NUMBER_RE.fullmatch(stripped):
            numbers.append((segment.y, segment.x_max, stripped))
    return numbers


def _strip_leading_line_number(text: str) -> tuple[str, str | None]:
    """Split a glued margin number off a chant line.

    ``"140. Ato awe"`` -> ``("Ato awe", "140")``.
    """
    match = _LEADING_NUMBER_RE.match(text)
    if not match:
        return text, None
    return text[match.end() :].strip(), match.group(1)


def _assign_printed_lines(
    numbers: list[tuple[float, float, str]],
    sources: list[Segment],
    tolerance: float = 10.0,
) -> list[str | None]:
    """Attach each margin line number to the one vernacular row it labels.

    Chant rows are set about 11 points apart while a number's baseline can sit a few points
    off its line, so nearest-row matching alone stamped the same number on three rows. Every
    number is therefore consumed once, nearest row first. A margin number belongs to the text
    column just right of it, so the x offset has to be plausible; otherwise a number from the
    facing page would be attached to this row.
    """
    assignment: list[str | None] = [None] * len(sources)
    used: set[int] = set()
    for number_y, number_x_max, text in sorted(numbers):
        candidates = [
            (abs(number_y - source.y), index)
            for index, source in enumerate(sources)
            if index not in used
            and abs(number_y - source.y) <= tolerance
            and 20.0 <= source.x_min - number_x_max <= 140.0
        ]
        if not candidates:
            continue
        candidates.sort()
        _, index = candidates[0]
        assignment[index] = text
        used.add(index)
    return assignment


def extract_columns(
    pages: list[tuple[float, list[Word]]],
    ref_prefix: str = "pdf",
    vocabulary: set[str] | None = None,
    min_pairs_per_page: int = MIN_PAIRS_PER_PAGE,
    page_range: tuple[int, int] | None = None,
    keep_repeats: bool = False,
    column_gap: float = COLUMN_GAP,
    column_gap_pages: dict[int, float] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extract line-aligned vernacular/translation pairs from interleaved column pages.

    ``column_gap_pages`` maps a PDF page number to a column gap used on that page only; every
    other page keeps ``column_gap``, so its row locators do not move.
    """
    records: list[dict[str, Any]] = []
    qa: dict[str, Any] = {
        "pages": len(pages),
        "pages_in_range": 0,
        "paired_pages": 0,
        "sparse_pages_skipped": 0,
        "pairs_found": 0,
        "duplicates_removed": 0,
        "duplicate_examples": [],
        "tgt_tokens_repaired": 0,
        "tgt_tokens_residual_damage": 0,
        "src_tokens": 0,
        "printed_line_locators": 0,
        "src_flagged": {},
        "sparse_examples": [],
    }
    seen: dict[tuple[str, str], str] = {}
    candidates: list[dict[str, Any]] = []
    flagged: dict[str, int] = {}
    for page_number, (page_width, words) in enumerate(pages, start=1):
        if page_range and not page_range[0] <= page_number <= page_range[1]:
            continue
        qa["pages_in_range"] += 1
        all_segments = [
            segment
            for line in group_lines(words, tolerance=LINE_TOLERANCE)
            for segment in line_segments(line)
            if segment.text
        ]
        text_segments = [
            segment
            for segment in all_segments
            if MIN_SEGMENT_WIDTH <= segment.width <= MAX_SEGMENT_WIDTH
            and (not page_width or segment.width <= page_width * MAX_WIDTH_FRACTION)
            and _SEGMENT_ALPHA.search(segment.text)
        ]
        numbers = _margin_numbers(all_segments)
        row_pairs: list[tuple[float, Segment, Segment]] = []
        page_gap = (column_gap_pages or {}).get(page_number, column_gap)
        for source_column, target_column in pair_columns(
            cluster_columns(text_segments, gap=page_gap)
        ):
            shift = estimate_row_shift(source_column, target_column)
            for source, target in match_rows(source_column, target_column, shift):
                row_pairs.append((source.y + shift / 2.0, source, target))
        row_pairs.sort(key=lambda item: item[0])
        if len(row_pairs) < min_pairs_per_page:
            qa["sparse_pages_skipped"] += 1
            if len(qa["sparse_examples"]) < 10:
                qa["sparse_examples"].append(
                    {
                        "page": page_number,
                        "pairs": len(row_pairs),
                        "src": row_pairs[0][1].text[:70] if row_pairs else "",
                    }
                )
            continue
        qa["paired_pages"] += 1
        printed_lines = _assign_printed_lines(numbers, [source for _, source, _ in row_pairs])
        for index, (_, source, target) in enumerate(row_pairs, start=1):
            source_text, glued_number = _strip_leading_line_number(source.text)
            printed_line = glued_number or printed_lines[index - 1]
            repaired, applied = repair_portuguese_ocr(target.text)
            residual = portuguese_residual_damage(repaired)
            qc = vernacular_qc(source_text, vocabulary)
            for flag in qc["src_flags"]:
                flagged[flag] = flagged.get(flag, 0) + 1
            qc.update(
                {
                    "page": page_number,
                    "row": index,
                    "printed_line": printed_line,
                    "tgt_repairs": applied,
                    "tgt_residual": residual,
                }
            )
            if applied:
                qc["tgt_raw"] = target.text
            record = {
                "ref": f"{ref_prefix}:p{page_number}:l{index}",
                "src": unicodedata.normalize("NFC", source_text),
                "tgt": unicodedata.normalize("NFC", repaired),
                "eng": "",
                "qc": qc,
            }
            if qc["printed_line"]:
                qa["printed_line_locators"] += 1
            candidates.append(record)
    # First occurrence wins, but a page read with a --column-gap-page override only claims a
    # (src, tgt) key that no default-gap page holds, so adding an override never drops a row
    # the default run already emitted. Without overrides this is plain page-order first-wins.
    overridden = set(column_gap_pages or ())
    kept: set[int] = set()
    for position in sorted(
        range(len(candidates)), key=lambda i: candidates[i]["qc"]["page"] in overridden
    ):
        record = candidates[position]
        key = (record["src"], record["tgt"])
        if key in seen and not keep_repeats:
            qa["duplicates_removed"] += 1
            if len(qa["duplicate_examples"]) < 10:
                qa["duplicate_examples"].append(
                    {"ref": record["ref"], "first_seen": seen[key], "src": record["src"][:70]}
                )
            continue
        seen.setdefault(key, record["ref"])
        kept.add(position)
    for position, record in enumerate(candidates):
        if position not in kept:
            continue
        records.append(record)
        qa["pairs_found"] += 1
        qa["tgt_tokens_repaired"] += len(record["qc"]["tgt_repairs"])
        qa["tgt_tokens_residual_damage"] += len(record["qc"]["tgt_residual"])
        qa["src_tokens"] += record["qc"]["src_tokens"]
    qa["src_flagged"] = dict(sorted(flagged.items()))
    qa["pages_with_pairs"] = len({record["qc"]["page"] for record in records})
    return records, qa


def run_pdftotext_bbox(pdf: Path) -> str:
    """Run ``pdftotext -bbox-layout`` and return the XHTML as text."""
    result = subprocess.run(
        ["pdftotext", "-bbox-layout", str(pdf), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


# --------------------------------------------------------------------------- #
# ``table``: born-digital chant tables (print-quality text, no OCR layer)
# --------------------------------------------------------------------------- #

#: Minimum run of spaces between the vernacular cell and the translation cell of a table.
TABLE_COLUMN_GAP = 5
#: Chant cells are short by construction (the metre is about four syllables a line); prose
#: paragraphs on the same page wrap at twice this width, so length is what separates a table
#: row from a footnote or a running head that also happens to contain a wide space.
MAX_TABLE_SOURCE_CHARS = 40
MAX_TABLE_TRANSLATION_CHARS = 45
_TABLE_MARGIN_NUMBER_RE = re.compile(r"^\s*(\d{1,3})\.\s{2,}")


def split_table_row(line: str) -> tuple[str | None, str, str] | None:
    """Split one ``pdftotext -layout`` line into ``(printed_line, source, translation)``.

    Returns ``None`` for anything that is not a two-cell chant row: headings, running heads,
    page footers, footnote prose and blank lines are single-cell or wider than a verse.

    The split is taken at the widest run of spaces, which is the cell gutter. ``-layout``
    reconstructs the visual line, so a row of a born-digital table keeps the two cells on one
    line; pairing is therefore positional in the source itself, not an inference from
    baselines.
    """
    if not line.strip():
        return None
    margin = _TABLE_MARGIN_NUMBER_RE.match(line)
    body = line[margin.end() :] if margin else line
    gaps = [(match.start(), match.end() - match.start()) for match in re.finditer(r" {5,}", body)]
    if not gaps:
        return None
    split_at, _ = max(gaps, key=lambda gap: (gap[1], -gap[0]))
    source = body[:split_at].strip()
    translation = body[split_at:].strip()
    if not source or not translation:
        return None
    if not _SEGMENT_ALPHA.search(source) or not _SEGMENT_ALPHA.search(translation):
        return None
    return (
        margin.group(1) if margin else None,
        source,
        translation,
    )


def is_table_row(source: str, translation: str) -> bool:
    """True when the two cells look like a chant line and its translation, not page prose.

    The vernacular cell must not read as Portuguese (a running head does) and neither cell may
    be as long as wrapped prose (a footnote or a page footer). Both failures were observed on
    the 2018 Wenia article, where the running head, page footers and footnote continuations
    otherwise split into two cells at their wide spaces.
    """
    if portuguese_ratio(source) > 0:
        return False
    return not (
        len(source) > MAX_TABLE_SOURCE_CHARS or len(translation) > MAX_TABLE_TRANSLATION_CHARS
    )


def load_tilde_marks(path: Path) -> dict[int, list[dict[str, Any]]]:
    """Read ``wenia_tilde_decode.py`` output as ``{page: [occurrence, ...]}``."""
    report = json.loads(path.read_text(encoding="utf-8"))
    marks: dict[int, list[dict[str, Any]]] = {}
    for occurrence in report["occurrences"]:
        marks.setdefault(occurrence["page"], []).append(occurrence)
    return marks


def apply_tilde_to_source(line: str, source: str, e_index: int) -> str:
    """Return ``source`` with the E at squashed-line index ``e_index`` as ``Ẽ`` (idempotent).

    ``e_index`` counts non-space characters of the whole ``-layout`` line, margin number
    included; it is mapped back to the raw line and then into the source cell.
    """
    raw = [i for i, ch in enumerate(line) if not ch.isspace()][e_index]
    margin = _TABLE_MARGIN_NUMBER_RE.match(line)
    start = line.find(source, margin.end() if margin else 0)
    rel = raw - start
    if start < 0 or not 0 <= rel < len(source):
        raise ValueError(f"tilde mark falls outside the source cell of {line!r}")
    if unicodedata.normalize("NFC", source[rel]) == "\u1ebc":
        return source
    if source[rel] != "E":
        raise ValueError(f"tilde mark is not on an E in {line!r}")
    return source[:rel] + unicodedata.normalize("NFC", "E\u0303") + source[rel + 1 :]


def extract_table(
    layout_text: str,
    ref_prefix: str = "pdf",
    vocabulary: set[str] | None = None,
    page_range: tuple[int, int] | None = None,
    tilde_marks: dict[int, list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extract line pairs from a born-digital two-column chant table.

    Every line that carries both a vernacular cell and its translation becomes one record, in
    reading order, with the printed margin line number kept as a locator. Repeated rows are
    kept: in a chant a refrain is text, not noise.

    ``tilde_marks`` (``wenia_tilde_decode.py`` output) restores a capital ``Ẽ`` whose tilde the
    PDF draws as a separate glyph that ``pdftotext`` turns into a space. Each mark names its
    page, its ``-layout`` line (whitespace-free text plus the index of the repeat among equal
    lines on the page) and the E's index in it; the vocabulary QC still sees the printed
    ``E``, so only ``src`` changes. A mark on a page in range that no row consumes is an error.
    """
    pages = layout_text.split("\f")
    records: list[dict[str, Any]] = []
    qa: dict[str, Any] = {
        "pages": len(pages),
        "pages_in_range": 0,
        "pages_with_pairs": 0,
        "pairs_found": 0,
        "printed_line_locators": 0,
        "repeated_rows": 0,
        "single_cell_lines_skipped": 0,
        "prose_like_lines_rejected": 0,
        "tgt_tokens_repaired": 0,
        "tgt_tokens_residual_damage": 0,
        "src_tokens": 0,
        "src_flagged": {},
        "numbering_gaps": 0,
    }
    if tilde_marks is not None:
        qa["tilde_marks_applied"] = 0
    flagged: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    previous_locator: int | None = None
    for page_number, page in enumerate(pages, start=1):
        if page_range and not page_range[0] <= page_number <= page_range[1]:
            continue
        qa["pages_in_range"] += 1
        row_index = 0
        pending = list((tilde_marks or {}).get(page_number, []))
        line_repeats: dict[str, int] = {}
        for line in page.split("\n"):
            mark = None
            if pending and line.strip():
                key = re.sub(r"\s+", "", line)
                repeat = line_repeats.get(key, 0)
                line_repeats[key] = repeat + 1
                mark = next(
                    (m for m in pending if m["line_key"] == key and m["line_occurrence"] == repeat),
                    None,
                )
            split = split_table_row(line)
            if split is None:
                if line.strip():
                    qa["single_cell_lines_skipped"] += 1
                continue
            printed_line, source, translation = split
            if not is_table_row(source, translation):
                qa["prose_like_lines_rejected"] += 1
                continue
            row_index += 1
            repaired, applied = repair_portuguese_ocr(translation)
            residual = portuguese_residual_damage(repaired)
            qc = vernacular_qc(source, vocabulary)
            for flag in qc["src_flags"]:
                flagged[flag] = flagged.get(flag, 0) + 1
            qc.update(
                {
                    "page": page_number,
                    "row": row_index,
                    "printed_line": printed_line,
                    "tgt_repairs": applied,
                    "tgt_residual": residual,
                }
            )
            if applied:
                qc["tgt_raw"] = translation
            record = {
                "ref": f"{ref_prefix}:p{page_number}:l{row_index}",
                "src": unicodedata.normalize("NFC", source),
                "tgt": unicodedata.normalize("NFC", repaired),
                "eng": "",
                "qc": qc,
            }
            if mark is not None:
                record["src"] = unicodedata.normalize(
                    "NFC", apply_tilde_to_source(line, source, mark["e_index"])
                )
                pending.remove(mark)
                qa["tilde_marks_applied"] += 1
            if (record["src"], record["tgt"]) in seen:
                qa["repeated_rows"] += 1
            seen.add((record["src"], record["tgt"]))
            if printed_line:
                qa["printed_line_locators"] += 1
                locator = int(printed_line)
                if previous_locator is not None and locator <= previous_locator:
                    qa["numbering_gaps"] += 1
                previous_locator = locator
            records.append(record)
            qa["pairs_found"] += 1
            qa["tgt_tokens_repaired"] += len(applied)
            qa["tgt_tokens_residual_damage"] += len(residual)
            qa["src_tokens"] += qc["src_tokens"]
        if pending:
            raise ValueError(f"unmatched tilde marks on page {page_number}: {pending}")
    qa["src_flagged"] = dict(sorted(flagged.items()))
    qa["pages_with_pairs"] = len({record["qc"]["page"] for record in records})
    return records, qa


def run_pdftotext_layout(pdf: Path) -> str:
    """Run ``pdftotext -layout`` and return the reconstructed pages as text."""
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def parse_page_range(text: str | None) -> tuple[int, int] | None:
    """Parse a ``--pages`` value: ``"15-48"``, ``"15"`` or ``None`` (whole PDF)."""
    if not text:
        return None
    match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", text)
    if not match:
        raise ValueError(f"bad page range: {text!r}; expected e.g. 15-48")
    start = int(match.group(1))
    end = int(match.group(2) or start)
    if start < 1 or end < start:
        raise ValueError(f"bad page range: {text!r}")
    return start, end


def parse_column_gap_page(text: str) -> tuple[int, float]:
    """Parse a ``--column-gap-page`` value: ``"25=25"`` gives PDF page 25 a 25-point gap."""
    match = re.fullmatch(r"\s*(\d+)\s*=\s*(\d+(?:\.\d+)?)\s*", text)
    if not match:
        raise argparse.ArgumentTypeError(f"bad page gap: {text!r}; expected e.g. 25=25")
    page, gap = int(match.group(1)), float(match.group(2))
    if page < 1 or gap <= 0:
        raise argparse.ArgumentTypeError(f"bad page gap: {text!r}")
    return page, gap


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Write records as newline-delimited JSON, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = argparse.ArgumentParser(description="Extract facing-translation or IGT data from PDFs")
    sub = parser.add_subparsers(dest="command", required=True)

    facing = sub.add_parser("facing", help="two-column facing-translation PDF")
    facing.add_argument("--pdf", type=Path, required=True)
    facing.add_argument("--out", type=Path, required=True)
    facing.add_argument("--qa", type=Path, default=None)

    mono = sub.add_parser("monolingual", help="Marúbo-only prose pages")
    mono.add_argument("--pdf", type=Path, required=True)
    mono.add_argument("--out", type=Path, required=True)
    mono.add_argument("--qa", type=Path, default=None)

    columns = sub.add_parser("columns", help="line-interleaved chant/translation columns")
    columns.add_argument("--pdf", type=Path, required=True)
    columns.add_argument("--out", type=Path, required=True)
    columns.add_argument("--qa", type=Path, default=None)
    columns.add_argument("--ref-prefix", default="pdf", help="stable ref prefix for records")
    columns.add_argument(
        "--mzr-reference",
        action="append",
        default=[],
        help="glob of clean vernacular sources used to measure (never repair) OCR loss",
    )
    columns.add_argument(
        "--min-pairs-per-page",
        type=int,
        default=MIN_PAIRS_PER_PAGE,
        help="a page with fewer row pairs is treated as prose, not chant",
    )
    columns.add_argument(
        "--pages",
        default=None,
        help="restrict to PDF page numbers, e.g. 15-48 (chant sections start and end mid-book)",
    )
    columns.add_argument(
        "--keep-repeats",
        action="store_true",
        help="keep identical (source, translation) rows; chant refrains are text, not noise",
    )
    columns.add_argument(
        "--column-gap",
        type=float,
        default=COLUMN_GAP,
        help=(
            "maximum left-edge distance (points) between segments of one column; lower it when "
            "the chant table is indented inside the page's prose margin"
        ),
    )
    columns.add_argument(
        "--column-gap-page",
        type=parse_column_gap_page,
        action="append",
        default=[],
        metavar="PAGE=GAP",
        help=(
            "use GAP instead of --column-gap on one PDF page (repeatable); other pages, and so "
            "their positional row locators, are unchanged"
        ),
    )

    igt = sub.add_parser("igt", help="numbered IGT appendix")
    igt.add_argument("--pdf", type=Path, required=True)
    igt.add_argument("--out", type=Path, required=True)
    igt.add_argument("--qa", type=Path, default=None)

    table = sub.add_parser("table", help="born-digital two-column chant table")
    table.add_argument("--pdf", type=Path, required=True)
    table.add_argument("--out", type=Path, required=True)
    table.add_argument("--qa", type=Path, default=None)
    table.add_argument("--ref-prefix", default="pdf", help="stable ref prefix for records")
    table.add_argument(
        "--mzr-reference",
        action="append",
        default=[],
        help="glob of clean vernacular sources used to measure (never repair) lexical coverage",
    )
    table.add_argument(
        "--pages",
        default=None,
        help="restrict to PDF page numbers, e.g. 15-48 (chant sections start and end mid-book)",
    )
    table.add_argument(
        "--tilde-marks",
        type=Path,
        default=None,
        help="wenia_tilde_decode.py JSON: restore the E-tilde the text layer dropped",
    )

    args = parser.parse_args(argv)

    if args.command == "facing":
        records, qa = extract_facing(parse_bbox_layout(run_pdftotext_bbox(args.pdf)))
    elif args.command == "monolingual":
        pages = parse_bbox_layout(run_pdftotext_bbox(args.pdf))
        records, qa = extract_monolingual(pages)
    elif args.command == "table":
        vocabulary = load_reference_vocabulary(args.mzr_reference)
        records, qa = extract_table(
            run_pdftotext_layout(args.pdf),
            ref_prefix=args.ref_prefix,
            vocabulary=vocabulary or None,
            page_range=parse_page_range(args.pages),
            tilde_marks=load_tilde_marks(args.tilde_marks) if args.tilde_marks else None,
        )
        qa["mzr_reference_words"] = len(vocabulary)
    elif args.command == "columns":
        pages = parse_bbox_layout(run_pdftotext_bbox(args.pdf))
        vocabulary = load_reference_vocabulary(args.mzr_reference)
        records, qa = extract_columns(
            pages,
            ref_prefix=args.ref_prefix,
            vocabulary=vocabulary or None,
            min_pairs_per_page=args.min_pairs_per_page,
            page_range=parse_page_range(args.pages),
            keep_repeats=args.keep_repeats,
            column_gap=args.column_gap,
            column_gap_pages=dict(args.column_gap_page) or None,
        )
        qa["mzr_reference_words"] = len(vocabulary)
    else:
        pages = parse_bbox_layout(run_pdftotext_bbox(args.pdf))
        records, qa = extract_igt_lines(pages_to_lines(pages))

    write_jsonl(args.out, records)
    if args.qa is not None:
        args.qa.parent.mkdir(parents=True, exist_ok=True)
        args.qa.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(records)} records to {args.out}")
    summary = {key: value for key, value in qa.items() if key != "rejected"}
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(argv=sys.argv[1:]))
