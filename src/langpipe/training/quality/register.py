"""Flag archaic second-person and gendered forms in Portuguese text.

STARTING LIST: these entries are a first draft and must be reviewed by a
Portuguese speaker before use. Matching is case-insensitive on whole word tokens.
"""

from __future__ import annotations

import re
import unicodedata

# Archaic second-person forms (vós family) and gendered generic markers.
# Review with a Portuguese speaker; extend or prune as needed.
FLAGGED_TOKENS: frozenset[str] = frozenset(
    {
        "vós",
        "vos",
        "vossa",
        "vossas",
        "vosso",
        "vossos",
        "outrem",
        "amigo(a)",
        "todos(as)",
        "caro(a)",
    }
)

_TOKEN = re.compile(r"[\w()]+")


def flag_archaic_or_gendered(text: str) -> list[str]:
    """Return flagged tokens found in text, in order of appearance (duplicates kept).

    Text is NFC-normalized and lowercased before matching against FLAGGED_TOKENS.
    """
    normalized = unicodedata.normalize("NFC", text).lower()
    return [tok for tok in _TOKEN.findall(normalized) if tok in FLAGGED_TOKENS]
