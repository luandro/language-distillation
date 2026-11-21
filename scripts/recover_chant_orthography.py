#!/usr/bin/env python3
"""Cite a clean transcription form for OCR-damaged vernacular chant rows.

The Cesarino 2013 book is a scan whose OCR layer drops the Marúbo nasality marks, so its
aligned rows sit in ``exports/parallel_candidates/`` and cannot be trained on. Some of the
same chants are also printed, in full Unicode, by *born-digital* works that cite the book.
Those citations are evidence for the marks the scan lost - **not** a licence to rewrite the
observed line.

This script makes that evidence explicit and traceable:

* the book row keeps its observed ``src`` (the OCR text) untouched;
* a row whose whole token sequence also occurs, contiguously, in a born-digital reference
  gets the reference's own surface form as ``clean_src``, plus the locator of every
  occurrence (``clean_sources``) and the number of occurrences (``clean_votes``);
* when the references disagree about the marks for that same token sequence, the row is kept
  with ``clean_src: null`` and its ``clean_candidates`` listed - a conflict is reported, not
  resolved by majority.

Matching is *key*-based, never fuzzy. The key folds:

* case and every combining mark (the OCR dropped the marks; that is the point);
* the OCR confusions that stand in for a nasal vowel in this scan: ``z``/``l`` -> ``i`` and
  ``T`` -> ``i`` (Marúbo has no /l/ or /z/, and the 2013 scan prints ``Koz`` for ``Koĩ``,
  ``Chz`` for ``Chĩ``, ``inlki`` for ``inĩki``).

A key match therefore means "the same sequence of words is printed there with these
letters"; whichever marks the reference prints are then the cited form. The emitted
``clean_src`` is a **hypothesis with a citation**, never a validated observation: promotion
is a review step.

References come in two confidence tiers:

* ``quoted-chant`` - a born-digital PDF (``--reference``) that quotes the book's own chants;
  its locator is ``<label>:p<pdf page>``. A plain-text rendering of such a source
  (``--reference-text``, pages marked by ``=== page N ===`` lines, e.g. the decoded 2008
  Cesarino thesis) is the same tier with the same locator shape. Only this tier can
  originate a ``clean_src``.
* ``shared-formula`` - a born-digital aligned JSONL (``--reference-jsonl``) of a *different*
  chant that shares formulaic refrain lines with the book; its locator is the record's own
  ``ref``, verbatim (``cesarino-2018:p15:l1``); the label only names the reference set in the
  QA report. A shared-formula citation can confirm a quoted-chant citation (one more vote) or
  contradict it (``conflict``), but alone it leaves ``clean_src: null`` with
  ``clean_evidence: "uncorroborated"``.

When a shared-formula reference is supplied, every record also carries ``clean_confidence``
(the tier that originated ``clean_src``, ``shared-formula`` for an uncorroborated row, ``null``
for a conflict) and ``clean_citations`` (every locator with its surface and tier). A run with
quoted-chant references only keeps the earlier *record* schema byte for byte; the QA report
always gains ``uncorroborated`` and ``quoted_and_shared`` (rows cited by both tiers).

Usage::

    .venv/bin/python scripts/recover_chant_orthography.py \
        --candidates exports/parallel_candidates/cesarino_2013_columns.jsonl \
        --reference villada-2018:var/external/villada_2018/villada_2018.pdf \
        --reference-jsonl wenia-2018:exports/harvested_parallel/cesarino_2018_wenia_parallel.jsonl \
        --reference-text cesarino-2008:var/artifacts/cesarino_2008_thesis/decoded.txt \
        --out exports/parallel_candidates/cesarino_2013_clean_refs.jsonl \
        --qa var/artifacts/cesarino_2013/clean_refs_qa.json
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

#: Longest reference token window indexed; chant lines in the references are quoted as whole
#: verses, so the book's line length (rarely above eight tokens) is the natural bound.
MAX_WINDOW = 8
#: A one-token row ("A", "Sai") matches every occurrence of that word with different marks, so
#: no citation is attached below this many tokens; the key must also be as long as the row.
MIN_KEY_TOKENS = 2
#: Token pattern: any Unicode letters, with an optional clitic apostrophe (``shak'ini``).
TOKEN_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)
NASAL_MARKS = frozenset("ẽĩũãõā")
#: Letters that stand in for a nasal vowel in the 2013 scan's OCR layer.
OCR_NASAL_STANDS_IN = str.maketrans({"z": "i", "l": "i", "T": "i"})
#: Citation tiers, strongest first; only the first may originate a ``clean_src``.
QUOTED_CHANT = "quoted-chant"
SHARED_FORMULA = "shared-formula"
TIER_RANK = {QUOTED_CHANT: 0, SHARED_FORMULA: 1}


def fold(text: str) -> str:
    """Lowercase and strip every combining mark, so only the letters remain."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def tokens(text: str) -> list[str]:
    """Split normalized text into word tokens."""
    return TOKEN_RE.findall(unicodedata.normalize("NFC", text))


def row_key(text: str) -> tuple[str, ...]:
    """Matching key for an OCR'd vernacular line."""
    return tuple(tokens(fold(text.translate(OCR_NASAL_STANDS_IN))))


def reference_key(text: str) -> tuple[str, ...]:
    """Matching key for a reference (born-digital) line."""
    return tuple(tokens(fold(text)))


def adds_nasal_marks(clean: str, observed: str) -> bool:
    """True when the cited form carries a nasal mark that the observed OCR line lacks."""
    return any(mark in clean for mark in NASAL_MARKS) and clean != observed


def read_reference_layout(pdf: Path) -> list[tuple[int, str]]:
    """Return ``(pdf_page, line)`` for a born-digital PDF through ``pdftotext -layout``."""
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    lines: list[tuple[int, str]] = []
    for page_number, page in enumerate(result.stdout.split("\f"), start=1):
        for line in page.split("\n"):
            if line.strip():
                lines.append((page_number, line))
    return lines


PAGE_MARKER = re.compile(r"^=== page (\d+) ===\s*$")


def read_reference_text(path: Path) -> list[tuple[int, str]]:
    """Return ``(page, line)`` from a text file whose pages start at ``=== page N ===``.

    Marker lines are not content, blank lines are skipped and lines before the first marker
    belong to no page, so they are ignored.
    """
    lines: list[tuple[int, str]] = []
    page: int | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        marker = PAGE_MARKER.match(line)
        if marker:
            page = int(marker.group(1))
        elif page is not None and line.strip():
            lines.append((page, line))
    return lines


def page_locators(label: str, lines: list[tuple[int, str]]) -> list[tuple[str, str]]:
    """Turn ``(pdf_page, line)`` pairs into ``(locator, line)`` with ``<label>:p<page>``."""
    return [(f"{label}:p{page_number}", line) for page_number, line in lines]


def read_reference_jsonl(path: Path) -> list[tuple[str, str]]:
    """Return ``(ref, src)`` for every record of an aligned JSONL; ``ref`` is the locator."""
    lines: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        record = json.loads(raw)
        if record.get("src"):
            lines.append((str(record["ref"]), str(record["src"])))
    return lines


def build_index(
    references: dict[str, list[tuple[str, str]]],
) -> dict[tuple[str, ...], list[tuple[str, str, str]]]:
    """Index every contiguous token window of every reference.

    ``references`` maps ``label -> [(locator, line)]``; the index maps
    ``key -> [(label, locator, text)]``.
    """
    index: dict[tuple[str, ...], list[tuple[str, str, str]]] = collections.defaultdict(list)
    for label, lines in references.items():
        for locator, line in lines:
            line_tokens = tokens(line)
            for width in range(1, MAX_WINDOW + 1):
                for start in range(len(line_tokens) - width + 1):
                    window = line_tokens[start : start + width]
                    index[reference_key(" ".join(window))].append(
                        (label, locator, " ".join(window))
                    )
    return index


def recover(
    candidates: list[dict[str, Any]],
    references: dict[str, list[tuple[str, str]]],
    tiers: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach cited clean forms to candidate rows; never modify the observed line.

    ``tiers`` maps a reference label to its citation tier; a label not listed is
    ``quoted-chant``. The ``clean_confidence``/``clean_citations`` fields are emitted only
    when some reference is ``shared-formula``.
    """
    tiers = tiers or {}
    tier_of = {label: tiers.get(label, QUOTED_CHANT) for label in references}
    tiered = any(tier != QUOTED_CHANT for tier in tier_of.values())
    index = build_index(references)
    records: list[dict[str, Any]] = []
    qa: dict[str, Any] = {
        "candidates": len(candidates),
        "matched": 0,
        "unanimous": 0,
        "conflict": 0,
        "uncorroborated": 0,
        "adds_nasal_marks": 0,
        "confirms_observed": 0,
        "matched_pages": 0,
        "too_short": 0,
        "by_reference": {},
        "reference_windows": len(index),
        "quoted_and_shared": [],
    }
    per_reference: collections.Counter[str] = collections.Counter()
    matched_pages: set[int] = set()
    for candidate in candidates:
        observed = str(candidate.get("src") or "")
        key = row_key(observed)
        if len(key) < MIN_KEY_TOKENS or len(key) != len(tokens(observed)):
            qa["too_short"] = qa.get("too_short", 0) + 1
            continue
        occurrences = index.get(key)
        if not occurrences:
            continue
        qa["matched"] += 1
        matched_pages.add(int(candidate["qc"]["page"]))
        # Stable sort: a quoted-chant surface is always the one kept for its casefold group.
        occurrences = sorted(occurrences, key=lambda hit: TIER_RANK[tier_of[hit[0]]])
        surfaces: dict[str, tuple[str, list[str]]] = {}
        citations: dict[str, tuple[str, str]] = {}
        for label, locator, text in occurrences:
            per_reference[label] += 1
            folded = text.casefold()
            if folded not in surfaces:
                surfaces[folded] = (text, [])
            if locator not in surfaces[folded][1]:
                surfaces[folded][1].append(locator)
            citations.setdefault(locator, (text, tier_of[label]))
        cited_tiers = {tier for _, tier in citations.values()}
        if QUOTED_CHANT not in cited_tiers:
            evidence = "uncorroborated"
        else:
            evidence = "unanimous" if len(surfaces) == 1 else "conflict"
        qa[evidence] += 1
        if len(cited_tiers) > 1:
            qa["quoted_and_shared"].append({"ref": candidate["ref"], "evidence": evidence})
        record: dict[str, Any] = {
            "ref": candidate["ref"],
            "src": candidate["src"],
            "tgt": candidate["tgt"],
            "eng": "",
            "clean_src": None,
            "clean_candidates": sorted(surface for surface, _ in surfaces.values()),
            "clean_sources": [],
            "clean_votes": sum(len(locators) for _, locators in surfaces.values()),
            "clean_evidence": evidence,
        }
        if tiered:
            record["clean_confidence"] = {
                "unanimous": QUOTED_CHANT,
                "uncorroborated": SHARED_FORMULA,
                "conflict": None,
            }[evidence]
            record["clean_citations"] = [
                {"locator": locator, "surface": text, "clean_confidence": tier}
                for locator, (text, tier) in sorted(citations.items())
            ]
        record["qc"] = {
            "page": candidate["qc"]["page"],
            "printed_line": candidate["qc"].get("printed_line"),
            "src_tokens": len(tokens(candidate["src"])),
        }
        if evidence == "unanimous":
            surface, locators = next(iter(surfaces.values()))
            record["clean_src"] = surface
            record["clean_sources"] = sorted(locators)
            record["clean_candidates"] = [surface]
            if adds_nasal_marks(surface, candidate["src"]):
                qa["adds_nasal_marks"] += 1
                record["qc"]["clean_delta"] = "nasal-marks-added"
            elif surface != candidate["src"]:
                qa["confirms_observed"] += 1
                record["qc"]["clean_delta"] = "same-letters"
            else:
                qa["confirms_observed"] += 1
                record["qc"]["clean_delta"] = "identical"
        records.append(record)
    qa["matched_pages"] = len(matched_pages)
    qa["by_reference"] = dict(sorted(per_reference.items()))
    qa["clean_src_rows"] = sum(1 for record in records if record["clean_src"])
    return records, qa


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument(
        "--reference",
        action="append",
        default=[],
        metavar="LABEL:PDF",
        help="born-digital reference as label:path-to-pdf (repeatable)",
    )
    parser.add_argument(
        "--reference-jsonl",
        action="append",
        default=[],
        metavar="LABEL:JSONL",
        help="shared-formula reference as label:path-to-aligned-jsonl (repeatable); "
        "each record's src is the surface and its ref the locator",
    )
    parser.add_argument(
        "--reference-text",
        action="append",
        default=[],
        metavar="LABEL:TXT",
        help="quoted-chant reference as label:path-to-page-marked-text (repeatable); "
        "pages start at '=== page N ===' lines",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--qa", type=Path, default=None)
    args = parser.parse_args(argv)

    candidates = [
        json.loads(line)
        for line in args.candidates.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    references: dict[str, list[tuple[str, str]]] = {}
    tiers: dict[str, str] = {}
    for spec in args.reference:
        label, _, path = spec.partition(":")
        if not label or not path or label in references:
            parser.error(f"--reference must be a new LABEL:PDF, got {spec!r}")
        references[label] = page_locators(label, read_reference_layout(Path(path)))
        tiers[label] = QUOTED_CHANT
    for spec in args.reference_text:
        label, _, path = spec.partition(":")
        if not label or not path or label in references:
            parser.error(f"--reference-text must be a new LABEL:TXT, got {spec!r}")
        references[label] = page_locators(label, read_reference_text(Path(path)))
        tiers[label] = QUOTED_CHANT
    for spec in args.reference_jsonl:
        label, _, path = spec.partition(":")
        if not label or not path or label in references:
            parser.error(f"--reference-jsonl must be a new LABEL:JSONL, got {spec!r}")
        references[label] = read_reference_jsonl(Path(path))
        tiers[label] = SHARED_FORMULA
    records, qa = recover(candidates, references, tiers)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    if args.qa is not None:
        args.qa.parent.mkdir(parents=True, exist_ok=True)
        args.qa.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(records)} cited rows to {args.out}")
    print(json.dumps(qa, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(argv=sys.argv[1:]))
