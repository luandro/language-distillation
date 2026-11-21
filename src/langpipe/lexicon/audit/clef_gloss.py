"""Pivot-side Clef Gloss Classifier for Lexicon Audit (ADR-0006, ADR-0021).

Evaluates ONLY the Portuguese glosses (never target-language surface forms),
enforcing Invariant 10 and ADR-0006.
"""

from __future__ import annotations

import re
from typing import Any, Protocol


class GlossClassifier(Protocol):
    """Protocol for pivot-side gloss classification."""

    def classify_gloss(self, glosses: list[str]) -> dict[str, Any]:
        """Classify grammatical and semantic nature of the pivot gloss."""
        ...


class HeuristicGlossClassifier:
    """Deterministic, offline pivot classifier for Portuguese glosses."""

    # Portuguese names, biblical figures, and toponyms
    KNOWN_PIVOT_NAMES = {
        "judas",
        "iscariotes",
        "elimeleque",
        "noemi",
        "pedro",
        "simão",
        "maria",
        "madalena",
        "jesus",
        "cristo",
        "paulo",
        "saulo",
        "davi",
        "noé",
        "noe",
        "samaria",
        "samaritanos",
        "samaritano",
        "nilo",
        "caldeu",
        "caldeus",
        "judeu",
        "judeus",
        "israel",
        "israelitas",
        "israelita",
        "fariseu",
        "fariseus",
        "cananeu",
        "cananeus",
        "jebuseu",
        "yavé",
        "senhor_biblico",
        "adão",
        "adao",
        "eva",
        "belem",
        "belém",
        "jerusalém",
        "jerusalem",
        "efrata",
    }

    def classify_gloss(self, glosses: list[str]) -> dict[str, Any]:
        """Examine Portuguese glosses for proper names, inflected forms, and artifacts."""
        clean_glosses = [re.sub(r"[^\w\s]", "", g.lower()).strip() for g in glosses if g]

        is_name = False
        name_kind: str | None = None
        matched_name = ""

        for g in clean_glosses:
            words = g.split()
            for w in words:
                if w in self.KNOWN_PIVOT_NAMES:
                    is_name = True
                    matched_name = w
                    if w in ("nilo", "samaria", "belem", "belém", "jerusalém", "jerusalem"):
                        name_kind = "place"
                    elif w in ("caldeus", "caldeu", "judeus", "judeu", "israelitas", "fariseus"):
                        name_kind = "ethnic_group"
                    elif w in ("yavé", "deus"):
                        name_kind = "deity"
                    else:
                        name_kind = "person"
                    break
            if is_name:
                break

        return {
            "is_name": is_name,
            "name_kind": name_kind,
            "matched_name": matched_name,
        }


def get_gloss_classifier() -> GlossClassifier:
    """Factory for pivot gloss classifier."""
    return HeuristicGlossClassifier()
