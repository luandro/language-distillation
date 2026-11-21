"""Length-ratio guard for source/target training pairs."""

from __future__ import annotations


def _word_count(text: str) -> int:
    return len(text.split())


def length_ratio_ok(src: str, tgt: str, max_ratio: float = 2.5) -> bool:
    """Return True when the word-count ratio between src and tgt is within max_ratio.

    The ratio is max(n_src, n_tgt) / min(n_src, n_tgt). A ratio equal to max_ratio
    passes. An empty side (no words after whitespace split) always fails.
    """
    n_src = _word_count(src)
    n_tgt = _word_count(tgt)
    if n_src == 0 or n_tgt == 0:
        return False
    return max(n_src, n_tgt) / min(n_src, n_tgt) <= max_ratio
