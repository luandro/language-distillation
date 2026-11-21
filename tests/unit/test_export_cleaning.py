"""Cross-split dedup (fix 1) and Bible row cleanup (fix 4) in the dataset exporter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langpipe.synthesis.export_dataset import (
    DatasetExporter,
    clean_bible_train_rows,
    comparison_key,
    drop_train_rows_overlapping_eval,
    has_edition_note,
    repair_space_before_punctuation,
)


def _row(ref: str, tgt: str, por: str, prov: str = "corpus:GEN") -> dict[str, Any]:
    return {
        "source_ref": ref,
        "target_text": tgt,
        "reference_text": por,
        "provenance": prov,
        "is_attested": True,
    }


def test_comparison_key_folds_case_punctuation_space_and_diacritics():
    assert comparison_key("  Atõ  aki, AMAĨNÕ! ") == comparison_key("ato aki amaino")
    assert comparison_key("“Nawa” wení") == comparison_key("nawa weni")
    assert comparison_key("...") == ""


def test_overlap_removes_train_rows_sharing_either_key_with_eval():
    train = [
        _row("t1", "Ato aya", "Povo junto"),  # shares mzr key with test
        _row("t2", "outra coisa", "Sobre eles pensou."),  # shares por key with val
        _row("t3", "unrelated", "nada"),
        _row("t4", "chain", "Povo junto"),  # chained through por key of t1
    ]
    val = [_row("v1", "x y", "sobre eles pensou")]
    test = [_row("e1", "Atõ aya!", "diferente")]
    kept, removed = drop_train_rows_overlapping_eval(train, val, test)
    assert [r["source_ref"] for r in kept] == ["t3"]
    assert removed == 3
    assert train[0]["target_text"] == "Ato aya"  # stored text is never rewritten


def test_overlap_keeps_eval_rows_and_train_only_groups():
    train = [_row("t1", "a b", "c d"), _row("t2", "a b", "c d")]
    kept, removed = drop_train_rows_overlapping_eval(train, [], [])
    assert len(kept) == 2 and removed == 0


def test_export_has_zero_key_overlap_between_splits(tmp_path: Path):
    harvested = [
        {
            "ref": f"h{i}",
            "src": f"Nawa wení {i % 3}",
            "tgt": f"Povo todo {i % 3}",
            "provenance": "harvested:a",
        }
        for i in range(30)
    ]
    verses = [
        _row(f"GEN 1:{i}", f"marubo verso numero {i} longo", f"texto portugues numero {i} longo")
        for i in range(60)
    ]
    summary = DatasetExporter(lang_code="mzr", output_dir=tmp_path).export(
        synthetic_phrases=[], attested_verses=verses, harvested_sentences=harvested
    )

    def keys(split: str) -> tuple[set[str], set[str]]:
        rows = [json.loads(x) for x in (tmp_path / f"{split}.hf.jsonl").read_text().splitlines()]
        return (
            {comparison_key(r["translation"]["mzr"]) for r in rows},
            {comparison_key(r["translation"]["por"]) for r in rows},
        )

    tr, va, te = keys("train"), keys("val"), keys("test")
    for a, b in ((tr, va), (tr, te), (va, te)):
        assert not (a[0] & b[0]) and not (a[1] & b[1])
    assert any("overlapping" in w for w in summary.warnings) or summary.train_count > 0


def test_edition_note_regex():
    assert has_edition_note("E tendo saído TR, RP: tendo saído – N4: enquanto saíam")
    assert has_edition_note("saídas. N4 não contém “até” do sábado")
    assert has_edition_note("RP, N4 não contêm “Filipe”")
    assert not has_edition_note("Disse-lhe o anjo do SENHOR: Multiplicarei tanto")
    assert not has_edition_note("O TRIBUNAL e a RPM")


def test_space_before_punctuation_only_touches_that():
    assert repair_space_before_punctuation("repreendeu-os , e disse : sim ; ok .") == (
        "repreendeu-os, e disse: sim; ok."
    )
    assert repair_space_before_punctuation("a  b ( c )") == "a  b ( c )"
    assert repair_space_before_punctuation("Olá , mundo") == "Olá, mundo"
    assert repair_space_before_punctuation("sem espaço, nada muda") == "sem espaço, nada muda"


def test_clean_bible_rows_drops_notes_repairs_spacing_and_applies_ratio():
    rows = [
        _row("A 1:1", "um dois três quatro cinco", "N4 não contém “x” um dois três quatro cinco"),
        _row("A 1:2", "um dois três quatro cinco", "um dois , três quatro cinco ."),
        _row("A 1:3", "um", "um dois três quatro cinco seis sete"),
        _row("A 1:4", "um dois três", "um dois três", prov="harvested:chant"),
    ]
    rows[3]["target_text"] = "um"  # a chant row the ratio rule must not touch
    kept, stats = clean_bible_train_rows(rows)
    assert [r["source_ref"] for r in kept] == ["A 1:2", "A 1:4"]
    assert kept[0]["reference_text"] == "um dois, três quatro cinco."
    assert stats == {"edition_notes": 1, "space_before_punctuation": 1, "length_ratio": 1}
