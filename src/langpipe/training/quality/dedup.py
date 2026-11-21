"""Exact-duplicate removal for (src, tgt) training pairs."""

from __future__ import annotations

import unicodedata
from typing import Any


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def dedup_pairs(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Drop rows whose (src, tgt) repeats an earlier row.

    Keys are NFC-normalized with whitespace collapsed, so variants differing only in
    spacing or Unicode composition count as duplicates. The first occurrence is kept
    unchanged. Returns (kept_rows, removed_count).
    """
    seen: set[tuple[str, str]] = set()
    kept: list[dict[str, Any]] = []
    for row in rows:
        key = (_normalize(str(row.get("src", ""))), _normalize(str(row.get("tgt", ""))))
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept, len(rows) - len(kept)
