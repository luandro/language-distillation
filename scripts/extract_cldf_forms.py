#!/usr/bin/env python3
"""Extract one language's rows from a CLDF Wordlist into a reviewable proposal artifact.

A CLDF wordlist (Lexibank) carries observed forms per language with concept IDs, segments,
sources and cognate codes. This script filters it to one language, normalizes the fields the
LKB needs, and writes JSONL proposals with row-level lineage back to the dataset DOI.

It deliberately stops at *proposals*: merging into `exports/<lang>/dictionary.json` is a lexicon
change and must pass the Clef gloss pipeline (ADR-0020/0021) before promotion.

Usage::

    uv run python scripts/extract_cldf_forms.py \\
        --dataset-dir var/external/cldf_oliveiraprotopanoan \\
        --language-id Marubo \\
        --dataset-id oliveiraprotopanoan \\
        --dataset-doi 10.5281/zenodo.10214016 \\
        --out exports/lexicon_proposals/cldf_marubo_forms.jsonl \\
        --qa var/artifacts/cldf_oliveiraprotopanoan/extraction_qa.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

FORM_FIELDS = (
    "ID",
    "Local_ID",
    "Language_ID",
    "Parameter_ID",
    "Value",
    "Form",
    "Segments",
    "Comment",
    "Source",
    "Cognacy",
    "Loan",
    "ConceptInSource",
    "UncertainCognacy",
    "ProtoSet",
)


@dataclass(frozen=True)
class FormProposal:
    """One observed form, shaped for review and later lexicon promotion."""

    ref: str
    form: str
    value: str
    concept: str
    segments: str
    cognacy: str
    source: str
    comment: str
    dataset_id: str
    dataset_doi: str
    language_id: str
    status: str = "candidate"


def clean(value: str) -> str:
    """Normalize a CLDF cell: readr-style exports write the literal string ``None``."""
    text = (value or "").strip()
    return "" if text in {"None", "NA", "NaN", "nan"} else text


def load_forms(path: Path) -> list[dict[str, str]]:
    """Read a CLDF ``forms.csv`` into dictionaries limited to the fields the LKB uses."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = ("ID", "Form", "Parameter_ID", "Language_ID")
        available = reader.fieldnames or []
        missing = [field for field in required if field not in available]
        if missing:
            raise SystemExit(f"forms.csv is missing required columns: {missing}")
        return [{field: clean(row.get(field) or "") for field in FORM_FIELDS} for row in reader]


def select_language(rows: list[dict[str, str]], language_id: str) -> list[dict[str, str]]:
    """Filter rows to one CLDF ``Language_ID`` (case-sensitive, as CLDF writes it)."""
    wanted = language_id.strip()
    return [row for row in rows if row["Language_ID"] == wanted]


def to_proposals(
    rows: list[dict[str, str]], dataset_id: str, dataset_doi: str, language_id: str
) -> list[FormProposal]:
    """Convert selected CLDF rows into proposal records, dropping empty forms."""
    proposals: list[FormProposal] = []
    for row in rows:
        form = unicodedata.normalize("NFC", row["Form"] or row["Value"])
        if not form:
            continue
        proposals.append(
            FormProposal(
                ref=row["ID"],
                form=form,
                value=unicodedata.normalize("NFC", row["Value"]),
                concept=row["Parameter_ID"],
                segments=row["Segments"],
                cognacy=row["Cognacy"],
                source=row["Source"],
                comment=unicodedata.normalize("NFC", row["Comment"]),
                dataset_id=dataset_id,
                dataset_doi=dataset_doi,
                language_id=language_id,
            )
        )
    return proposals


def build_qa(proposals: list[FormProposal], rows_seen: int, language_id: str) -> dict[str, Any]:
    """Summarize provenance, concept coverage and known gaps for the extraction."""
    concepts = {proposal.concept for proposal in proposals}
    sources: dict[str, int] = {}
    for proposal in proposals:
        key = proposal.source or "unspecified"
        sources[key] = sources.get(key, 0) + 1
    without_segments = sum(1 for proposal in proposals if not proposal.segments)
    cognate_coded = sum(1 for proposal in proposals if proposal.cognacy)
    return {
        "language_id": language_id,
        "rows_scanned": rows_seen,
        "proposals": len(proposals),
        "distinct_concepts": len(concepts),
        "sources": dict(sorted(sources.items(), key=lambda item: -item[1])),
        "without_segments": without_segments,
        "with_cognacy": cognate_coded,
        "note": (
            "Proposals only. Forms are compiler-normalised (Value == Form here), so raw "
            "spellings are not preserved; an IPA-to-orthography mapping must be recorded "
            "before any promotion. Promotion to the lexicon needs the Clef gloss pipeline."
        ),
    }


def write_jsonl(path: Path, proposals: list[FormProposal]) -> None:
    """Write proposals as newline-delimited JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for proposal in proposals:
            handle.write(json.dumps(asdict(proposal), ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = argparse.ArgumentParser(description="Extract one language from a CLDF wordlist")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--language-id", required=True, help="CLDF Language_ID, e.g. Marubo or Mar")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-doi", default="")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--qa", type=Path, default=None)
    args = parser.parse_args(argv)

    forms_path = args.dataset_dir / "forms.csv"
    if not forms_path.exists():
        print(f"error: {forms_path} not found", file=sys.stderr)
        return 1
    rows = load_forms(forms_path)
    selected = select_language(rows, args.language_id)
    proposals = to_proposals(selected, args.dataset_id, args.dataset_doi, args.language_id)
    write_jsonl(args.out, proposals)
    qa = build_qa(proposals, len(rows), args.language_id)
    if args.qa is not None:
        args.qa.parent.mkdir(parents=True, exist_ok=True)
        args.qa.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(proposals)} proposals to {args.out}")
    print(json.dumps({key: qa[key] for key in ("rows_scanned", "proposals", "distinct_concepts")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(argv=sys.argv[1:]))
