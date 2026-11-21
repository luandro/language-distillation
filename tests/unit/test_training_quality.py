"""Tests for offline training data-quality checks. Synthetic fixtures only."""

from __future__ import annotations

import pytest

from langpipe.training.quality.dedup import dedup_pairs
from langpipe.training.quality.domain import check_scripture_cap, scripture_share
from langpipe.training.quality.length_ratio import length_ratio_ok
from langpipe.training.quality.probe_leak import shared_ngram_rate
from langpipe.training.quality.register import flag_archaic_or_gendered

# --- length_ratio ---------------------------------------------------------


def test_length_ratio_accepts_similar_lengths() -> None:
    assert length_ratio_ok("one two three", "uno dos tres")


def test_length_ratio_boundary_is_inclusive() -> None:
    # 5 words vs 2 words -> ratio exactly 2.5
    assert length_ratio_ok("a b c d e", "x y")
    # 6 words vs 2 words -> ratio 3.0, rejected
    assert not length_ratio_ok("a b c d e f", "x y")


def test_length_ratio_rejects_empty_sides() -> None:
    assert not length_ratio_ok("", "uno dos")
    assert not length_ratio_ok("one two", "")
    assert not length_ratio_ok("   ", "uno")


def test_length_ratio_counts_words_not_characters() -> None:
    # Long single word vs short single word: ratio 1.0 despite character difference.
    assert length_ratio_ok("extraordinarily", "ok")


def test_length_ratio_custom_max_ratio() -> None:
    assert not length_ratio_ok("a b c d", "x", max_ratio=2.5)
    assert length_ratio_ok("a b c d", "x", max_ratio=4.0)


# --- dedup ----------------------------------------------------------------


def test_dedup_removes_exact_duplicates_keeping_first() -> None:
    rows = [
        {"src": "alpha beta", "tgt": "gamma", "id": 1},
        {"src": "alpha beta", "tgt": "gamma", "id": 2},
        {"src": "alpha beta", "tgt": "delta", "id": 3},
    ]
    kept, removed = dedup_pairs(rows)
    assert removed == 1
    assert [r["id"] for r in kept] == [1, 3]


def test_dedup_collapses_whitespace_variants() -> None:
    rows = [
        {"src": "alpha  beta", "tgt": "gamma"},
        {"src": " alpha\tbeta ", "tgt": "gamma\n"},
    ]
    kept, removed = dedup_pairs(rows)
    assert removed == 1
    assert kept[0]["src"] == "alpha  beta"


def test_dedup_normalizes_unicode_composition() -> None:
    composed = "café"  # NFC: e with acute
    decomposed = "café"  # NFD: e plus combining acute
    kept, removed = dedup_pairs([{"src": composed, "tgt": "x"}, {"src": decomposed, "tgt": "x"}])
    assert removed == 1
    assert len(kept) == 1


def test_dedup_empty_input() -> None:
    assert dedup_pairs([]) == ([], 0)


# --- domain ---------------------------------------------------------------


def test_scripture_share_counts_marker_provenance() -> None:
    rows = [
        {"provenance": "corpus:A"},
        {"provenance": "elicited:s1"},
        {"provenance": "corpus:B"},
        {"provenance": "elicited:s2"},
    ]
    assert scripture_share(rows) == pytest.approx(0.5)


def test_scripture_share_custom_prefixes_and_missing_provenance() -> None:
    rows = [{"provenance": "bible:X"}, {}, {"provenance": "corpus:Y"}]
    assert scripture_share(rows, marker_provenance_prefixes=("bible:",)) == pytest.approx(1 / 3)


def test_scripture_share_empty_input_is_zero() -> None:
    assert scripture_share([]) == 0.0


def test_check_scripture_cap_passes_when_equal_to_cap() -> None:
    check_scripture_cap(0.2, cap=0.2)


def test_check_scripture_cap_raises_above_cap() -> None:
    with pytest.raises(ValueError, match="exceeds cap"):
        check_scripture_cap(0.21, cap=0.2)


# --- probe_leak -----------------------------------------------------------


def test_shared_ngram_rate_detects_verbatim_span() -> None:
    refs = ["the quick brown fox jumps over the lazy dog"]
    preds = [
        "a quick brown fox jumps somewhere",  # shares 4-gram "quick brown fox jumps"
        "completely unrelated output text here",
    ]
    assert shared_ngram_rate(preds, refs, n=4) == pytest.approx(0.5)


def test_shared_ngram_rate_is_case_and_punctuation_insensitive() -> None:
    refs = ["Alpha, beta; gamma delta."]
    assert shared_ngram_rate(["alpha beta gamma delta"], refs, n=4) == 1.0


def test_shared_ngram_rate_short_predictions_cannot_match() -> None:
    assert shared_ngram_rate(["alpha beta"], ["alpha beta gamma delta"], n=4) == 0.0


def test_shared_ngram_rate_empty_inputs() -> None:
    assert shared_ngram_rate([], ["alpha beta gamma delta"]) == 0.0
    assert shared_ngram_rate(["alpha beta gamma delta"], []) == 0.0


def test_shared_ngram_rate_rejects_invalid_n() -> None:
    with pytest.raises(ValueError):
        shared_ngram_rate(["a"], ["a"], n=0)


# --- register -------------------------------------------------------------


def test_flag_archaic_second_person_portuguese() -> None:
    assert flag_archaic_or_gendered("Vós sois os meus amigos.") == ["vós"]


def test_flag_returns_all_matches_in_order() -> None:
    text = "vossa casa e vossos bens; vós e vossas filhas"
    assert flag_archaic_or_gendered(text) == ["vossa", "vossos", "vós", "vossas"]


def test_flag_ignores_clean_text_and_substrings() -> None:
    assert flag_archaic_or_gendered("A casa é grande.") == []
    # "vosso" must not match inside a longer word.
    assert flag_archaic_or_gendered("revossomos") == []


def test_flag_empty_text() -> None:
    assert flag_archaic_or_gendered("") == []


def test_flag_nfc_normalizes_input() -> None:
    decomposed = "vós"  # o plus combining acute (NFD) for vos-acute
    assert flag_archaic_or_gendered(decomposed) == ["vós"]
