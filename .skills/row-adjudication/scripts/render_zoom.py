#!/usr/bin/env python3
"""Render high-dpi zoom crops (default 400 dpi) for worklist rows from geometry.json.

``geometry.json`` (written by scripts/build_clean_ref_review.py) stores each row's
``crop_px`` at its own ``dpi`` and is keyed by the FULL ref (``cesarino-2013:p100:l11``).
A zoom at ``zoom_dpi`` scales the same box: pixel offsets and size by ``zoom_dpi / dpi``.
Needs ``pdftoppm``. Writes ``<out>/p<page>-l<row>.png`` only.
"""

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


def zoom_box(crop_px: list[int], base_dpi: int, zoom_dpi: int) -> list[int]:
    """Scale ``[x, y, w, h]`` pixels from ``base_dpi`` to ``zoom_dpi``."""
    return [round(value * zoom_dpi / base_dpi) for value in crop_px]


def zoom_name(ref: str) -> str:
    """``cesarino-2013:p25:l6`` -> ``p25-l6.png``."""
    return "-".join(ref.split(":")[1:]) + ".png"


def pdftoppm_args(pdf: Path, page: int, box: list[int], dpi: int, prefix: Path) -> list[str]:
    """Command line for one crop (``-x/-y/-W/-H`` are pixels at ``-r``)."""
    x, y, width, height = box
    return [
        "pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page),
        "-x", str(x), "-y", str(y), "-W", str(width), "-H", str(height),
        "-png", "-singlefile", str(pdf), str(prefix),
    ]  # fmt: skip


def plan(
    items: list[dict[str, Any]], geometry: dict[str, Any], zoom_dpi: int
) -> tuple[list[tuple[str, int, list[int]]], list[str]]:
    """``[(ref, pdf_page, zoom_box)]`` for rows with geometry, plus refs with none."""
    base_dpi = int(geometry["dpi"])
    found: list[tuple[str, int, list[int]]] = []
    absent: list[str] = []
    for item in items:
        row = geometry["rows"].get(item["ref"])
        if row is None:
            absent.append(item["ref"])
        else:
            found.append(
                (item["ref"], int(row["page"]), zoom_box(row["crop_px"], base_dpi, zoom_dpi))
            )
    return found, absent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--worklist", type=Path, required=True, help="worklist/part JSON")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=400)
    parser.add_argument("--only-idx", help="comma list of idx to render (e.g. disputed rows)")
    args = parser.parse_args(argv)

    items = json.loads(args.worklist.read_text(encoding="utf-8"))
    if args.only_idx:
        wanted = {int(part) for part in args.only_idx.split(",")}
        items = [item for item in items if item["idx"] in wanted]
    geometry = json.loads(args.geometry.read_text(encoding="utf-8"))
    found, absent = plan(items, geometry, args.dpi)
    args.out.mkdir(parents=True, exist_ok=True)
    for ref, page, box in found:
        prefix = (args.out / zoom_name(ref)).with_suffix("")
        subprocess.run(
            pdftoppm_args(args.pdf, page, box, args.dpi, prefix), check=True, capture_output=True
        )
    print(json.dumps({"rendered": len(found), "no_geometry": absent}))
    return 1 if absent else 0


if __name__ == "__main__":
    raise SystemExit(main())
