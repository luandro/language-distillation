#!/usr/bin/env python3
"""Build the committed conflict-reads evidence file from free-reader picks.

Reads the committed clean-refs JSONL (refs, candidates) plus the local reader outputs under
``--reads-dir`` and writes one JSON line per ``clean_evidence == conflict`` row, sorted by ref:
``{ref, status, print_spelling, readers, claude_audit, candidates, crop, method, benchmark,
clean_src}``. Evidence only: ``clean_src`` is always null and ``src`` is never touched; promotion
stays an explicit ``langpipe review decide`` step.

``--reads-dir`` must hold (all produced by the row-adjudication probe, local-only):
``conflicts_worklist.json`` (global ``idx``, ``ref``, ``candidates``, ``crop``),
``conflicts_picks_glm.json`` and ``conflicts_picks_mimo.json`` (pick lists, ``-1`` = none),
``conflicts_compare_free.json`` (cross-check of the unread list) and ``free_vs_claude.json``.

Status: ``agreed`` both readers gave the same candidate; ``disputed`` both read it but disagree,
or either gave NONE/empty; ``unread`` fewer than two readers read it (free-tier IP block).

    .venv/bin/python scripts/build_conflict_reads.py \
        --refs exports/parallel_candidates/cesarino_2013_clean_refs.jsonl \
        --reads-dir var/artifacts/row_adjudication_probe \
        --out exports/parallel_candidates/cesarino_2013_conflict_reads.jsonl
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

READERS = ("glm", "mimo")
METHOD = "free-reader pick, tight 300 dpi crop; accepted on two-reader agreement"
BENCHMARK = "var/artifacts/row_adjudication_probe/reader_benchmark.md"
EMPTY_NOTE = "no parseable answer"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def conflict_rows(refs_path: Path) -> list[dict[str, Any]]:
    """Conflict rows of the clean-refs file, in file order (the worklist ``idx`` order)."""
    rows = [json.loads(line) for line in refs_path.read_text(encoding="utf-8").splitlines() if line]
    return [row for row in rows if row.get("clean_evidence") == "conflict"]


def check_worklist(rows: list[dict[str, Any]], worklist: list[dict[str, Any]]) -> None:
    """Fail loudly unless the worklist matches the conflict rows ref for ref."""
    if len(rows) != len(worklist):
        raise ValueError(f"{len(rows)} conflict rows vs {len(worklist)} worklist items")
    for idx, (row, item) in enumerate(zip(rows, worklist, strict=True)):
        if item["idx"] != idx or item["ref"] != row["ref"]:
            raise ValueError(f"idx {idx}: refs has {row['ref']}, worklist has {item['ref']}")
        if item["candidates"] != row["clean_candidates"]:
            raise ValueError(f"{row['ref']}: worklist candidates differ from clean_candidates")


def load_picks(path: Path, candidates: dict[int, list[str]]) -> dict[int, dict[str, Any]]:
    """Pick list -> ``idx -> pick``; every pick index must be -1 or a valid candidate index."""
    picks: dict[int, dict[str, Any]] = {}
    for pick in load_json(path):
        idx = pick["idx"]
        if idx not in candidates:
            raise ValueError(f"{path.name}: idx {idx} not in worklist")
        if idx in picks:
            raise ValueError(f"{path.name}: duplicate idx {idx}")
        if not -1 <= pick["pick"] < len(candidates[idx]):
            raise ValueError(f"{path.name}: idx {idx} pick {pick['pick']} out of range")
        picks[idx] = pick
    return picks


def reader_entry(name: str, pick: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": name, "pick": pick["pick"], "conf": pick["conf"]}
    if EMPTY_NOTE in (pick.get("note") or ""):
        entry["empty"] = True
    if pick.get("printed"):
        entry["printed"] = pick["printed"]
    return entry


def classify(readers: list[dict[str, Any]]) -> tuple[str, int | None]:
    """``(status, agreed candidate index)``; two readers with the same pick >= 0 agree."""
    if len(readers) < len(READERS):
        return "unread", None
    first, second = readers[0]["pick"], readers[1]["pick"]
    if first == second and first >= 0:
        return "agreed", first
    return "disputed", None


def claude_audit(idx: int, free_vs_claude: dict[str, Any]) -> dict[str, Any] | None:
    """Sonnet/Haiku picks for the row when known; ``None`` otherwise."""
    for item in free_vs_claude["free_disagree_or_empty"]:
        if item["idx"] == idx:
            return {
                "sonnet": item["sonnet"],
                "haiku": item["haiku"],
                "agree": item["sonnet"] == item["haiku"],
            }
    return None


def build(
    rows: list[dict[str, Any]],
    worklist: list[dict[str, Any]],
    picks: dict[str, dict[int, dict[str, Any]]],
    free_vs_claude: dict[str, Any],
) -> list[dict[str, Any]]:
    """One evidence record per conflict row, sorted by ref."""
    check_worklist(rows, worklist)
    out: list[dict[str, Any]] = []
    for idx, (row, item) in enumerate(zip(rows, worklist, strict=True)):
        readers = [reader_entry(n, picks[n][idx]) for n in READERS if idx in picks[n]]
        status, chosen = classify(readers)
        audit = claude_audit(idx, free_vs_claude)
        if status == "agreed" and audit is None:  # agreed rows equal both Claude reads (163/163)
            audit = {"sonnet": chosen, "haiku": chosen, "agree": True}
        out.append(
            {
                "ref": row["ref"],
                "status": status,
                "print_spelling": None if chosen is None else row["clean_candidates"][chosen],
                "readers": readers,
                "claude_audit": audit,
                "candidates": row["clean_candidates"],
                "crop": item["crop"],
                "method": METHOD,
                "benchmark": BENCHMARK,
                "clean_src": None,
            }
        )
    return sorted(out, key=lambda rec: str(rec["ref"]))


def check_against_compare(records: list[dict[str, Any]], compare: dict[str, Any]) -> None:
    """Cross-check the derived counts against the probe's own compare report."""
    totals = compare["totals"]
    counts = {
        s: sum(1 for r in records if r["status"] == s) for s in ("agreed", "disputed", "unread")
    }
    expected = {
        "agreed": totals["agree_picked"],
        "disputed": totals["disagree"] + totals["agree_none"],
        "unread": len(totals["unread"]),
    }
    if counts != expected:
        raise ValueError(f"status counts {counts} differ from compare_free totals {expected}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refs", type=Path, required=True)
    parser.add_argument("--reads-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = conflict_rows(args.refs)
    worklist = load_json(args.reads_dir / "conflicts_worklist.json")
    candidates = {item["idx"]: item["candidates"] for item in worklist}
    picks = {
        n: load_picks(args.reads_dir / f"conflicts_picks_{n}.json", candidates) for n in READERS
    }
    records = build(rows, worklist, picks, load_json(args.reads_dir / "free_vs_claude.json"))
    check_against_compare(records, load_json(args.reads_dir / "conflicts_compare_free.json"))
    args.out.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    counts: dict[str, int] = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    print(f"wrote {len(records)} rows to {args.out}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
