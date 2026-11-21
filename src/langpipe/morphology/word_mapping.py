"""Sequential word mapping between IGT words and token occurrences (M5-PLAN §6 WP5.9, Gate 38).

Maps parsed IGT words to token occurrences sequentially, skipping pure-punctuation tokens.
Contract: Word mapping NEVER forces an alignment (R3). If word and token counts differ,
the entire record is an honest count mismatch.
"""

import unicodedata
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from langpipe.domain.models.igt import IgtWord
from langpipe.domain.models.observation import TokenOccurrence


def is_pure_punctuation(surface: str) -> bool:
    """True if surface is nonempty and consists entirely of Unicode punctuation characters."""
    cleaned = surface.strip()
    return bool(cleaned) and all(unicodedata.category(ch).startswith("P") for ch in cleaned)


@dataclass(frozen=True)
class WordMappingResult:
    """Outcome of sequential word mapping.

    Unpacks as ``(mapped, unmapped_counts)`` for backwards-compatible call sites.
    """

    mapped: list[tuple[IgtWord, TokenOccurrence]]
    unmapped_counts: dict[str, int]

    def __iter__(self) -> Iterator[object]:
        return iter((self.mapped, self.unmapped_counts))


def map_words(
    igt_words: Sequence[IgtWord],
    tokens: Sequence[TokenOccurrence],
    normalizer: Callable[[str], str] | None = None,
) -> WordMappingResult:
    """Sequentially match IGT words against token occurrences.

    Skips pure-punctuation tokens.
    Returns mapped pairs and unmapped counts by reason:
      - `count_mismatch`: word count does not match non-punctuation token count
      - `surface_mismatch`: positions align but surfaces do not match
    """
    # 1. Filter out pure-punctuation tokens
    word_tokens: list[TokenOccurrence] = []
    for tok in tokens:
        surface = tok.normalized_surface if tok.normalized_surface is not None else tok.raw_surface
        if not is_pure_punctuation(surface):
            word_tokens.append(tok)

    num_words = len(igt_words)
    num_tokens = len(word_tokens)

    # 2. Honest count check: word mapping never forces (R3)
    if num_words != num_tokens:
        return WordMappingResult(
            mapped=[],
            unmapped_counts={
                "count_mismatch": num_words,
                "surface_mismatch": 0,
            },
        )

    # 3. Sequential 1-to-1 comparison
    mapped: list[tuple[IgtWord, TokenOccurrence]] = []
    surface_mismatch = 0

    for word, tok in zip(igt_words, word_tokens, strict=True):
        tok_surf = tok.normalized_surface if tok.normalized_surface is not None else tok.raw_surface

        w_clean = normalizer(word.text) if normalizer is not None else word.text
        t_clean = normalizer(tok_surf) if normalizer is not None else tok_surf

        w_norm = unicodedata.normalize("NFC", w_clean)
        t_norm = unicodedata.normalize("NFC", t_clean)

        if w_norm == t_norm:
            mapped.append((word, tok))
        else:
            surface_mismatch += 1

    return WordMappingResult(
        mapped=mapped,
        unmapped_counts={
            "count_mismatch": 0,
            "surface_mismatch": surface_mismatch,
        },
    )


__all__ = [
    "WordMappingResult",
    "is_pure_punctuation",
    "map_words",
]
