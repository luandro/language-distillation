"""Scripture-share cap for training mixtures.

No text classifier is available offline, so scripture membership is decided by
provenance only: a row counts as scripture when its ``provenance`` string starts
with one of the marker prefixes (default ``"corpus:"``). Provenance is the signal
here, not the text content. Rows without a provenance string are not counted.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def scripture_share(
    rows: list[dict[str, Any]],
    marker_provenance_prefixes: Sequence[str] = ("corpus:",),
) -> float:
    """Return the fraction of rows whose provenance starts with a marker prefix.

    An empty row list returns 0.0.
    """
    if not rows:
        return 0.0
    markers = tuple(marker_provenance_prefixes)
    hits = sum(1 for row in rows if str(row.get("provenance", "")).startswith(markers))
    return hits / len(rows)


def check_scripture_cap(share: float, cap: float = 0.2) -> None:
    """Raise ValueError when share is strictly above cap. A share equal to cap passes."""
    if share > cap:
        raise ValueError(
            f"scripture share {share:.3f} exceeds cap {cap:.3f}; "
            "reduce marker-provenance rows or raise the cap explicitly"
        )
