"""Tests for probe loading and drift metrics."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from langpipe.training.nllb_eval import (
    ProbeItem,
    length_bucket,
    load_probe_items,
    looks_english,
    summarize,
)


def test_length_buckets() -> None:
    assert length_bucket("Qual seu nome?") == "1-4"
    assert length_bucket("a b c d e") == "5-10"
    assert length_bucket(" ".join(["x"] * 15)) == "11-20"
    assert length_bucket(" ".join(["x"] * 30)) == ">20"


def test_looks_english_flags_english_output() -> None:
    assert looks_english("What is your name?")
    assert looks_english("This is the river.")


def test_looks_english_passes_non_english_output() -> None:
    assert not looks_english("Ãwẽ aská")
    assert not looks_english("Qual seu nome?")


def test_load_rejects_duplicate_ids(tmp_path: Path) -> None:
    p = tmp_path / "p.jsonl"
    p.write_text(
        '{"id":"a","category":"q","pt":"Oi"}\n{"id":"a","category":"q","pt":"Tchau"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate id"):
        load_probe_items(p, input_key="pt")


def test_load_rejects_missing_field(tmp_path: Path) -> None:
    p = tmp_path / "p.jsonl"
    p.write_text('{"id":"a","category":"q"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="missing 'pt'"):
        load_probe_items(p, input_key="pt")


def test_summarize_leak_and_exact_match() -> None:
    items = [
        ProbeItem("1", "name", "Qual seu nome?", reference="Ãwẽ aská"),
        ProbeItem("2", "name", "Oi, tudo bem?"),
    ]
    preds = {"1": "What is your name?", "2": "Ãwẽ aská"}
    s = summarize(preds, items)["1-4"]
    assert s["n"] == 2
    assert s["english_leak_rate"] == 0.5
    assert s["exact_match_rate"] == 0.0


def test_summarize_exact_match_nan_without_refs() -> None:
    items = [ProbeItem("1", "q", "Oi")]
    s = summarize({"1": "Ãwẽ"}, items)["1-4"]
    assert math.isnan(s["exact_match_rate"])
