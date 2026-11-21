#!/usr/bin/env python3
"""Write strict candidate examples extracted from Costa (2002) *Ergatividade cindida em Marubo*.

Reads ``var/external/marubo_sources/costa_2002.txt`` (OCR text), writes

* ``exports/harvested_parallel/candidates/costa_2002_candidates.jsonl`` (accepted evidence),
* ``exports/harvested_parallel/candidates/costa_2002_held_back.jsonl`` (refused, with reason),

and prints counts only. Marubo text is never printed to stdout: the run log names reasons and
counts, not rows. Nothing is admitted to a training file here; admission is an owner action
described in ``exports/harvested_parallel/candidates/README.md``.

Usage::

    uv run python scripts/extract_costa_examples.py
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from langpipe.languages.mzr.costa_examples import (
    candidate_to_row,
    extract_examples,
    held_back_to_row,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "var" / "external" / "marubo_sources" / "costa_2002.txt"
OUT_DIR = ROOT / "exports" / "harvested_parallel" / "candidates"
CANDIDATES_OUT = OUT_DIR / "costa_2002_candidates.jsonl"
HELD_BACK_OUT = OUT_DIR / "costa_2002_held_back.jsonl"


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(payload, encoding="utf-8", newline="\n")


def main() -> int:
    text = SOURCE.read_bytes().decode("utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    candidates, held = extract_examples(text, source_ref=SOURCE.name)

    _write_rows(CANDIDATES_OUT, [candidate_to_row(row) for row in candidates])
    _write_rows(HELD_BACK_OUT, [held_back_to_row(row) for row in held])

    reasons = Counter(row.reason for row in held)
    print(f"source: {SOURCE.relative_to(ROOT)}")
    print(f"sha256: {digest}")
    print(f"accepted: {len(candidates)}")
    print(f"held_back: {len(held)}")
    print("reasons:")
    for reason in sorted(reasons):
        print(f"  {reason}: {reasons[reason]}")
    print(f"wrote: {CANDIDATES_OUT.relative_to(ROOT)}")
    print(f"wrote: {HELD_BACK_OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
