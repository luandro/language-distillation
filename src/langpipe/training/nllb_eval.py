"""Probe-set loading and language-drift metrics for NLLB fine-tuning evaluation.

Metrics here are deliberately simple and transparent. The English-leak check is a
function-word heuristic, not a language identifier, and is reported as a rate with
its method name so reviewers can judge its limits.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ENGLISH_FUNCTION_WORDS = frozenset(
    {
        "the",
        "good",
        "morning",
        "thank",
        "thanks",
        "hello",
        "please",
        "is",
        "are",
        "you",
        "what",
        "and",
        "of",
        "to",
        "it",
        "my",
        "your",
        "not",
        "this",
        "that",
        "with",
        "for",
    }
)
BUCKETS = ((1, 4, "1-4"), (5, 10, "5-10"), (11, 20, "11-20"), (21, 10**9, ">20"))


@dataclass(frozen=True)
class ProbeItem:
    """One probe row: its prompt side plus an optional reference in the target language.

    The probe file's key names are supplied by the caller, so no language code is baked in
    here (``input_key``/``reference_key`` name the two fields of the JSONL row).
    """

    id: str
    category: str
    input_text: str
    reference: str | None = None


def load_probe_items(
    path: Path, *, input_key: str, reference_key: str | None = None
) -> list[ProbeItem]:
    """Load a probe JSONL file. Ids must be unique; every row needs id, category and input.

    ``input_key`` (required) and ``reference_key`` (optional) are the row fields holding the
    prompt side and the target-language reference; the file's own key names are data, so the
    caller passes them instead of this module assuming a language.
    """
    items: list[ProbeItem] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            for key in ("id", "category", input_key):
                if not str(row.get(key) or "").strip():
                    raise ValueError(f"{path}:{lineno}: missing '{key}'")
            if row["id"] in seen:
                raise ValueError(f"{path}:{lineno}: duplicate id {row['id']}")
            seen.add(row["id"])
            reference = row.get(reference_key) if reference_key else None
            items.append(
                ProbeItem(
                    id=row["id"],
                    category=row["category"],
                    input_text=row[input_key],
                    reference=reference,
                )
            )
    return items


def length_bucket(text: str) -> str:
    """Bucket by whitespace-token count: 1-4, 5-10, 11-20, >20."""
    n = len(text.split())
    for lo, hi, label in BUCKETS:
        if lo <= n <= hi:
            return label
    raise ValueError("unreachable: bucket ranges cover all counts >= 1")


def looks_english(text: str, min_hits: int = 2) -> bool:
    """Heuristic: at least `min_hits` distinct English function words appear in the output."""
    tokens = {t.strip(".,!?;:\"'“”‘’()").lower() for t in text.split()}
    return len(tokens & ENGLISH_FUNCTION_WORDS) >= min_hits


def summarize(
    predictions: dict[str, str], items: list[ProbeItem]
) -> dict[str, dict[str, float | int]]:
    """Per length bucket: count, English-leak rate, exact-match rate (if references exist)."""
    stats: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"n": 0, "leak": 0, "exact_n": 0, "exact": 0}
    )
    for item in items:
        if item.id not in predictions:
            continue
        pred = predictions[item.id]
        s = stats[length_bucket(item.input_text)]
        s["n"] += 1
        s["leak"] += int(looks_english(pred))
        if item.reference is not None:
            s["exact_n"] += 1
            s["exact"] += int(pred.strip() == item.reference.strip())
    out: dict[str, dict[str, float | int]] = {}
    for _, _, label in BUCKETS:
        if label in stats:
            s = stats[label]
            out[label] = {
                "n": s["n"],
                "english_leak_rate": s["leak"] / s["n"],
                "exact_match_rate": (s["exact"] / s["exact_n"]) if s["exact_n"] else float("nan"),
            }
    return out
