"""Leipzig gloss splitting (WP5.6, M5-PLAN §7.6, Leipzig rule 4).

A morph gloss splits on ``.`` into components: components that match the
profile's `grammatical_label_pattern` are grammatical labels (kept verbatim,
e.g. ``3SG`` is one label and is never decomposed, and ``ir.PST`` is one lexical
gloss plus one label); the remaining components are contact-language lexical
glosses. A gloss equal to a profile `unknown_gloss_markers` entry is UNKNOWN.
Nothing is normalised here: the source strings are returned as written.

Without an explicit profile the generic `MorphologyProfile` defaults apply.
"""

import re

from langpipe.domain.models.base import DomainModel
from langpipe.languages.base import MorphologyProfile


class SplitGlossResult(DomainModel):
    """The Leipzig-rule-4 split of one morph gloss, kept verbatim."""

    source_gloss: str
    is_unknown: bool
    grammatical_labels: tuple[str, ...]
    lexical_glosses: tuple[str, ...]


def split_gloss(gloss: str, profile: MorphologyProfile | None = None) -> SplitGlossResult:
    """Split one morph gloss into grammatical labels and lexical glosses."""
    resolved = profile if profile is not None else MorphologyProfile()
    if gloss in resolved.unknown_gloss_markers:
        return SplitGlossResult(
            source_gloss=gloss,
            is_unknown=True,
            grammatical_labels=(),
            lexical_glosses=(),
        )
    labels: list[str] = []
    lexical: list[str] = []
    for component in gloss.split("."):
        if not component:
            continue
        if re.fullmatch(resolved.grammatical_label_pattern, component):
            labels.append(component)
        else:
            lexical.append(component)
    return SplitGlossResult(
        source_gloss=gloss,
        is_unknown=False,
        grammatical_labels=tuple(labels),
        lexical_glosses=tuple(lexical),
    )
