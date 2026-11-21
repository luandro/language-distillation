"""Derived full-phrase rows (ADR-0026): building, loading, leakage and determinism."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from langpipe.languages.mzr.profile import MZR_HARVESTED_SOURCES, MZR_PROFILE
from langpipe.synthesis.derived_rows import (
    build_wenia_stanzas,
    build_zenodo_sentences,
    load_derived_rows,
    wenia_blocks,
)
from langpipe.synthesis.export_dataset import (
    DatasetExporter,
    select_derived_train_rows,
)

# The language and the harvested sources are profile data, so the tests read them from there.
LANG = MZR_PROFILE.language
_WENIA = MZR_HARVESTED_SOURCES.stanza
_ZENODO = MZR_HARVESTED_SOURCES.sentence
assert _WENIA is not None and _ZENODO is not None
WENIA_PROVENANCE = _WENIA.provenance
ZENODO_PROVENANCE = _ZENODO.provenance


def _line(ref: str, src: str, tgt: str, page: int, row: int, **qc: Any) -> dict[str, Any]:
    return {"ref": ref, "src": src, "tgt": tgt, "eng": "", "qc": {"page": page, "row": row, **qc}}


def _split(line: str) -> tuple[str | None, str, str] | None:
    parts = [p for p in line.split("  ") if p.strip()]
    return (None, parts[0].strip(), parts[1].strip()) if len(parts) == 2 else None


def _table(_src: str, _tgt: str) -> bool:
    return True


LAYOUT = (
    "Heading line\n"
    "aa bb    um dois\n"
    "cc dd    tres quatro\n"
    "\n"
    "ee ff    cinco seis\n"
    "\n"
    "gg hh    sete oito\n"
    "orphan\n"
    "ii jj    nove dez\n"
    "kk ll    onze doze\n"
    "\f"
    "mm nn    treze catorze\n"
    "oo pp    quinze dezesseis\n"
)


def _wenia_rows() -> list[dict[str, Any]]:
    data = [
        ("aa bb", "um dois", 1, 1),
        ("cc dd", "tres quatro", 1, 2),
        ("ee ff", "cinco seis", 1, 3),
        ("gg hh", "sete oito", 1, 4),
        ("ii jj", "nove dez", 1, 5),
        ("kk ll", "onze doze", 1, 6),
        ("mm nn", "treze catorze", 2, 1),
        ("oo pp", "quinze dezesseis", 2, 2),
    ]
    return [_line(f"w:p{p}:l{r}", s, t, p, r) for s, t, p, r in data]


def _wenia_build() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = _wenia_rows()
    blocks = wenia_blocks(LAYOUT, rows, _split, _table, page_range=(1, 2))
    return build_wenia_stanzas(
        rows,
        blocks,
        source_file="f.jsonl",
        source_sha256="a" * 64,
        pdf_sha256="b" * 64,
        provenance=WENIA_PROVENANCE,
        lang=LANG,
    )


def test_wenia_blocks_break_at_blank_unpaired_and_page_end() -> None:
    built, skipped = _wenia_build()
    assert [r["id"] for r in built] == [
        "derived:cesarino-2018:p1:l1-l2",
        "derived:cesarino-2018:p1:l5-l6",
        "derived:cesarino-2018:p2:l1-l2",
    ]
    assert {s["where"]: s["reason"] for s in skipped} == {
        "p1:l3-l3": "single_line_block",
        "p1:l4-l4": "single_line_block",
    }
    first = built[0]
    assert first["src"] == "aa bb cc dd" and first["tgt"] == "um dois tres quatro"
    assert first["separator"] == " " and first["line_count"] == 2
    assert first["split_constraint"] == "train_only" and first["register"] == "ritual_chant"
    assert first["unit_kind"] == "stanza" and first["schema_version"] == 1
    assert [m["ref"] for m in first["member_refs"]] == ["w:p1:l1", "w:p1:l2"]
    assert all(m["provenance"] == WENIA_PROVENANCE for m in first["member_refs"])


def test_wenia_block_rejects_unverifiable_layout() -> None:
    rows = _wenia_rows()
    rows[1]["tgt"] = "different"
    with pytest.raises(ValueError, match="translation differs"):
        wenia_blocks(LAYOUT, rows, _split, _table, page_range=(1, 2))


def test_wenia_skips_ocr_residue_and_never_rewrites() -> None:
    rows = _wenia_rows()
    rows[0]["qc"]["tgt_residual"] = ["x"]
    blocks = wenia_blocks(LAYOUT, rows, _split, _table, page_range=(1, 2))
    built, skipped = build_wenia_stanzas(
        rows,
        blocks,
        source_file="f",
        source_sha256="a",
        pdf_sha256="b",
        provenance=WENIA_PROVENANCE,
        lang=LANG,
    )
    assert "derived:cesarino-2018:p1:l1-l2" not in {r["id"] for r in built}
    assert any(s["reason"] == "translation_ocr_residue" for s in skipped)


def test_build_is_deterministic() -> None:
    assert _wenia_build() == _wenia_build()


def _z(n: int, src: str, tgt: str) -> dict[str, Any]:
    return {"ref": f"Cesarino-2017:({n})", "src": src, "tgt": tgt, "eng": ""}


def test_zenodo_sentences_close_only_when_both_sides_end() -> None:
    rows = [
        _z(1, "a,", "x,"),
        _z(2, "b.", "y,"),  # src ends, tgt does not: keep merging
        _z(3, "c!", "z."),
        _z(4, "d.", "w."),
        _z(5, "e,", "v,"),
    ]
    built, skipped = build_zenodo_sentences(
        rows, source_file="z", source_sha256="c" * 64, provenance=ZENODO_PROVENANCE, lang=LANG
    )
    assert [r["id"] for r in built] == [
        "derived:Cesarino-2017:(1)-(3)",
        "derived:Cesarino-2017:(4)",
    ]
    assert built[0]["src"] == "a, b. c!" and built[0]["tgt"] == "x, y, z."
    assert skipped == [{"where": "(5)", "lines": 1, "reason": "unterminated_tail"}]
    assert built[0]["member_refs"][0]["provenance"] == ZENODO_PROVENANCE


def test_zenodo_skips_footnote_digit_residue() -> None:
    rows = [_z(1, "a,", "x,"), _z(2, "b.", "y.’5")]
    built, skipped = build_zenodo_sentences(
        rows, source_file="z", source_sha256="c", provenance=ZENODO_PROVENANCE, lang=LANG
    )
    assert built == [] and skipped[0]["reason"] == "footnote_digit_residue"


# --------------------------------------------------------------------------- loader


def _write_derived(directory: Path, records: list[dict[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "x_stanza_derived.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )


def test_loader_marks_rows_derived_not_attested_and_ignores_plain_glob(tmp_path: Path) -> None:
    built, _ = _wenia_build()
    _write_derived(tmp_path, built)
    rows = load_derived_rows(tmp_path, "mzr")
    assert len(rows) == 3
    assert all(r["is_derived"] and r["is_attested"] is False for r in rows)
    assert rows[0]["derived"]["split_constraint"] == "train_only"
    from langpipe.synthesis.export_dataset import load_harvested_parallel_sentences

    assert load_harvested_parallel_sentences(tmp_path) == []


def test_loader_rejects_non_train_only_and_empty_members(tmp_path: Path) -> None:
    built, _ = _wenia_build()
    _write_derived(tmp_path, [{**built[0], "split_constraint": "any"}])
    with pytest.raises(ValueError, match="train_only"):
        load_derived_rows(tmp_path)
    _write_derived(tmp_path, [{**built[0], "member_refs": []}])
    with pytest.raises(ValueError, match="member_refs"):
        load_derived_rows(tmp_path)


# --------------------------------------------------------------------------- leakage


def _row(ref: str, src: str, tgt: str) -> dict[str, Any]:
    return {
        "source_ref": ref,
        "target_text": src,
        "reference_text": tgt,
        "provenance": WENIA_PROVENANCE,
        "is_attested": True,
        "register": "ritual_chant",
    }


def _derived(ref: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_ref": ref,
        "target_text": " ".join(m["target_text"] for m in members),
        "reference_text": " ".join(m["reference_text"] for m in members),
        "provenance": WENIA_PROVENANCE,
        "is_attested": False,
        "is_derived": True,
        "register": "ritual_chant",
        "derived": {
            "unit_kind": "stanza",
            "split_constraint": "train_only",
            "member_refs": [
                {"provenance": WENIA_PROVENANCE, "ref": m["source_ref"]} for m in members
            ],
        },
    }


def test_derived_row_with_a_val_member_is_excluded_and_eval_never_moves() -> None:
    a, b, c = _row("l1", "aa", "um"), _row("l2", "bb", "dois"), _row("l3", "cc", "tres")
    e = _row("l4", "dd", "quatro")
    d1, d2 = _derived("d1", [a, b]), _derived("d2", [c, e])
    kept, excluded = select_derived_train_rows([d1, d2], [a, b, c, e], pinned_eval=[a])
    assert [r["source_ref"] for r in kept] == ["d2"]
    assert excluded == [{"id": "d1", "reason": "member_in_eval"}]
    assert a not in kept


def test_refrain_component_excludes_derived_rows_sharing_the_refrain() -> None:
    refrain_val = _row("v", "Kayaini ikirao", "Elas vão subindo")
    refrain_train = _row("t", "kayaini  ikirao!", "outra tradução")
    other = _row("o", "zz", "yy")
    d_refrain = _derived("dr", [refrain_train, other])
    n1, n2 = _row("n1", "p", "q"), _row("n2", "r", "s")
    d_clean = _derived("dc", [n1, n2])
    kept, excluded = select_derived_train_rows(
        [d_refrain, d_clean], [refrain_train, other, n1, n2], pinned_eval=[refrain_val]
    )
    assert [r["source_ref"] for r in kept] == ["dc"]
    assert excluded == [{"id": "dr", "reason": "key_component_touches_eval"}]


def test_dedup_dropped_member_resolves_through_alias() -> None:
    kept_row = _row("k", "aa", "um")
    dropped = _row("dropped", "aa", "um")
    other = _row("o", "bb", "dois")
    derived = _derived("d", [dropped, other])
    # the dropped duplicate is not in the line universe handed in: alias must resolve it
    kept, _ = select_derived_train_rows(
        [derived],
        [kept_row, other],
        pinned_eval=[],
        aliases={f"{WENIA_PROVENANCE}|dropped": f"{WENIA_PROVENANCE}|k"},
    )
    assert [r["source_ref"] for r in kept] == ["d"]
    with pytest.raises(ValueError, match="unknown member"):
        select_derived_train_rows([derived], [kept_row, other], pinned_eval=[])


def test_selection_is_deterministic_and_drops_duplicate_pairs() -> None:
    a, b = _row("l1", "aa", "um"), _row("l2", "bb", "dois")
    d_first, d_second = _derived("d1", [a, b]), _derived("d2", [a, b])
    run1 = select_derived_train_rows([d_second, d_first], [a, b], [])
    run2 = select_derived_train_rows([d_first, d_second], [a, b], [])
    assert [r["source_ref"] for r in run1[0]] == [r["source_ref"] for r in run2[0]] == ["d1"]
    assert run1[1] == [{"id": "d2", "reason": "duplicate_derived_pair"}]


# --------------------------------------------------------------------------- export


def _export(tmp_path: Path, derived: list[dict[str, Any]], harvested: list[dict[str, Any]]):
    exporter = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "out")
    verses = [
        {
            "source_ref": f"v{i}",
            "target_text": f"scripture target {i}",
            "reference_text": f"scripture reference {i}",
            "provenance": "corpus:GEN",
            "is_attested": True,
            "register": "scripture",
        }
        for i in range(60)
    ]
    summary = exporter.export(
        synthetic_phrases=[],
        attested_verses=verses,
        harvested_sentences=harvested,
        derived_rows=derived,
        benchmark_version=1,
    )
    return summary, tmp_path / "out"


def test_export_writes_derived_train_rows_with_metadata_and_counts(tmp_path: Path) -> None:
    lines = [_row(f"l{i}", f"chant {i}", f"canto {i}") for i in range(8)]
    derived = [_derived("d1", lines[:3]), _derived("d2", lines[3:6])]
    summary, out = _export(tmp_path, derived, lines)
    assert summary.derived_built_count == 2
    assert summary.derived_train_count + sum(summary.derived_excluded.values()) == 2
    records = [json.loads(x) for x in (out / "train.hf.jsonl").read_text().splitlines()]
    in_train = {r["id"]: r for r in records if r["id"].startswith("d")}
    for record in in_train.values():
        meta = record["derived"]
        assert meta["split_constraint"] == "train_only" and meta["unit_kind"] == "stanza"
    for split in ("val", "test"):
        text = (out / f"{split}.hf.jsonl").read_text()
        assert '"derived"' not in text
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["derived_train_count"] == summary.derived_train_count
    assert (out / "derived_rows_audit.json").exists()


def test_built_rows_and_committed_files_validate_against_schema() -> None:
    import jsonschema

    root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (root / "schemas/exports/derived-parallel-row.v1.schema.json").read_text(encoding="utf-8")
    )
    built, _ = _wenia_build()
    z_built, _ = build_zenodo_sentences(
        [_z(1, "a.", "x.")],
        source_file="z",
        source_sha256="c" * 64,
        provenance=ZENODO_PROVENANCE,
        lang=LANG,
    )
    for record in [*built, *z_built]:
        jsonschema.validate(record, schema)
    # Committed *_derived.jsonl files are local build artifacts (gitignored); validating
    # rows built here keeps this test meaningful in a data-free clone.
