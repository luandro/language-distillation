#!/usr/bin/env python3
"""Compare two or more readers' picks over a worklist and report agreement.

Pick files are JSON lists of ``{idx, pick, conf, note?}`` where ``pick`` is the 0-based index
into the row's ``candidates`` and ``-1`` means "none of the candidates" (a real outcome: the
print shows a third spelling). Reader files are given as ``NAME=part0.json,part1.json``.
A pick may carry ``printed`` (the form actually read from the print). Output ``compare.json``:
``totals``, ``picks`` (reader -> idx -> pick), ``disagreements`` and ``observations`` (every
row where any reader said none-of-the-candidates: printed form per reader, reader name and crop
as provenance, ``clean_src`` always null). ``--reader`` takes the reader's name, whatever it is.
Evidence only: nothing here is a vote, a promotion or a rewrite of ``src``.
"""

import argparse
import json
from pathlib import Path
from typing import Any


def load_picks(paths: list[Path]) -> dict[int, dict[str, Any]]:
    """Merge pick files into ``idx -> pick`` (a duplicated idx is an error)."""
    merged: dict[int, dict[str, Any]] = {}
    for path in paths:
        for pick in json.loads(path.read_text(encoding="utf-8")):
            if pick["idx"] in merged:
                raise ValueError(f"duplicate idx {pick['idx']} in {path}")
            merged[pick["idx"]] = pick
    return merged


def form_of(item: dict[str, Any], pick: dict[str, Any]) -> str | None:
    """Candidate text for a pick, ``None`` for none-of-the-candidates."""
    return None if pick["pick"] < 0 else str(item["candidates"][pick["pick"]])


def observation(item: dict[str, Any], row_picks: dict[str, Any]) -> dict[str, Any]:
    """Printed-form observation for a none-of-the-candidates row; ``clean_src`` stays null."""
    return {
        "idx": item["idx"],
        "ref": item["ref"],
        "crop": item.get("crop"),
        "clean_src": None,
        "printed": {
            name: {"form": pick.get("printed"), "conf": pick["conf"], "none": pick["pick"] < 0}
            for name, pick in row_picks.items()
            if pick
        },
        "status": "needs-owner-review",
    }


def compare(
    items: list[dict[str, Any]], readers: dict[str, dict[int, dict[str, Any]]]
) -> dict[str, Any]:
    """Classify every row: agree_picked, agree_none, disagree; list low-confidence rows."""
    names = sorted(readers)
    counts = {"agree_picked": 0, "agree_none": 0, "disagree": 0}
    disagreements: list[dict[str, Any]] = []
    low_conf: list[int] = []
    unread: list[int] = []
    observations: list[dict[str, Any]] = []
    for item in items:
        idx = item["idx"]
        row_picks = {name: readers[name].get(idx) for name in names}
        if any(pick is None for pick in row_picks.values()):
            unread.append(idx)
            continue
        if any(pick["conf"] == "low" for pick in row_picks.values() if pick):
            low_conf.append(idx)
        values = {pick["pick"] for pick in row_picks.values() if pick}
        if -1 in values:
            observations.append(observation(item, row_picks))
        if len(values) > 1:
            counts["disagree"] += 1
            disagreements.append(
                {
                    "idx": idx,
                    "ref": item["ref"],
                    "candidates": item["candidates"],
                    "picks": {
                        name: {
                            "pick": pick["pick"],
                            "form": form_of(item, pick),
                            "conf": pick["conf"],
                            "note": pick.get("note"),
                        }
                        for name, pick in row_picks.items()
                        if pick
                    },
                }
            )
        elif values == {-1}:
            counts["agree_none"] += 1
        else:
            counts["agree_picked"] += 1
    totals = {"total": len(items), **counts, "low_conf_any": low_conf, "unread": unread}
    return {
        "totals": totals,
        "picks": {
            name: {str(idx): pick for idx, pick in sorted(readers[name].items())} for name in names
        },
        "disagreements": disagreements,
        "observations": observations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--worklist", type=Path, required=True)
    parser.add_argument(
        "--reader", action="append", required=True, help="NAME=part0.json,part1.json (repeat)"
    )
    parser.add_argument("--out", type=Path, required=True, help="compare.json to write")
    args = parser.parse_args(argv)

    items = json.loads(args.worklist.read_text(encoding="utf-8"))
    readers: dict[str, dict[int, dict[str, Any]]] = {}
    for spec in args.reader:
        name, _, files = spec.partition("=")
        readers[name] = load_picks([Path(part) for part in files.split(",")])
    result = compare(items, readers)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result["totals"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
