#!/usr/bin/env python3
"""Build a row-adjudication worklist from a clean-refs JSONL and split it into reader parts.

Selects rows with ``clean_evidence == conflict`` (or ``--evidence``), attaches the review
crop path for each, assigns a global ``idx`` and writes ``worklist.json`` plus
``part<i>.json`` (at most ``--max-per-part`` rows each, so one reader fits its context).
Writes only under ``--out``; never touches the candidates file or the images.
"""

import argparse
import json
from pathlib import Path
from typing import Any


def image_name(ref: str) -> str:
    """``cesarino-2013:p30:l18`` -> ``p30-l18.png`` (matches build_clean_ref_review)."""
    return "-".join(ref.split(":")[1:]) + ".png"


def select_rows(rows: list[dict[str, Any]], evidence: str) -> list[dict[str, Any]]:
    """Rows whose ``clean_evidence`` equals ``evidence``."""
    return [row for row in rows if row.get("clean_evidence") == evidence]


def build_worklist(rows: list[dict[str, Any]], img_dir: str) -> list[dict[str, Any]]:
    """One worklist item per row, with a global ``idx`` that part files keep."""
    return [
        {
            "idx": idx,
            "ref": row["ref"],
            "src": row["src"],
            "tgt": row.get("tgt", ""),
            "candidates": list(row["clean_candidates"]),
            "crop": f"{img_dir.rstrip('/')}/{image_name(row['ref'])}",
        }
        for idx, row in enumerate(rows)
    ]


def split_parts(items: list[dict[str, Any]], max_per_part: int) -> list[list[dict[str, Any]]]:
    """Split into the fewest near-equal parts of at most ``max_per_part`` items."""
    if max_per_part < 1:
        raise ValueError("max_per_part must be >= 1")
    if not items:
        return []
    count = -(-len(items) // max_per_part)
    size = -(-len(items) // count)
    return [items[start : start + size] for start in range(0, len(items), size)]


def missing_crops(items: list[dict[str, Any]]) -> list[str]:
    """Refs whose crop file does not exist on disk."""
    return [item["ref"] for item in items if not Path(item["crop"]).is_file()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refs", type=Path, required=True, help="clean-refs JSONL")
    parser.add_argument("--img-dir", required=True, help="directory of review crop PNGs")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--evidence", default="conflict")
    parser.add_argument("--max-per-part", type=int, default=100)
    args = parser.parse_args(argv)

    rows = [json.loads(line) for line in args.refs.read_text(encoding="utf-8").splitlines() if line]
    items = build_worklist(select_rows(rows, args.evidence), args.img_dir)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "worklist.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    parts = split_parts(items, args.max_per_part)
    for number, part in enumerate(parts):
        (args.out / f"part{number}.json").write_text(
            json.dumps(part, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    absent = missing_crops(items)
    print(json.dumps({"rows": len(items), "parts": len(parts), "missing_crops": len(absent)}))
    return 1 if absent else 0


if __name__ == "__main__":
    raise SystemExit(main())
