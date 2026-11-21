"""Verbatim-reproduction check: do model outputs share word n-grams with references?"""

from __future__ import annotations

import re

_WORD = re.compile(r"\w+")


def _ngrams(text: str, n: int) -> list[tuple[str, ...]]:
    tokens = tuple(_WORD.findall(text.lower()))
    return [tokens[i : i + n] for i in range(len(tokens) - n + 1)]


def shared_ngram_rate(predictions: list[str], reference_texts: list[str], n: int = 4) -> float:
    """Return the fraction of predictions sharing any word n-gram with any reference.

    Tokens are lowercased ``\\w+`` words. Reference n-grams go into one set, so the
    cost is linear in total tokens. Predictions shorter than n tokens cannot match.
    Returns 0.0 when there are no predictions. Raises ValueError when n < 1.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    if not predictions:
        return 0.0
    reference_grams: set[tuple[str, ...]] = set()
    for ref in reference_texts:
        reference_grams.update(_ngrams(ref, n))
    leaked = sum(
        1 for pred in predictions if any(gram in reference_grams for gram in _ngrams(pred, n))
    )
    return leaked / len(predictions)
