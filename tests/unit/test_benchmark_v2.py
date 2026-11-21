"""Benchmark v2: held-out Bible repair/exclusion and the separate chant benchmark."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from langpipe.languages.mzr.profile import MZR_PROFILE
from langpipe.synthesis.export_dataset import (
    CHANT_REGISTER,
    DatasetExporter,
    apply_benchmark_v2,
    comparison_key,
    register_of,
    select_chant_components,
)

# Ritual-chant provenances are profile data (LanguageProfile.chant_provenances).
CHANT_PROVENANCES = MZR_PROFILE.chant_provenances
WENIA = "harvested:cesarino_2018_wenia_parallel"
ZENODO = "harvested:zenodo_1008779_cesarino_marubo_2017_parallel"


def _verse(i: int) -> dict[str, Any]:
    por = f"texto portugues numero {i} longo e distinto"
    if i % 5 == 0:
        por = f"TR: {por}"
    elif i % 7 == 0:
        por = f"{por} , com espaco ."
    return {
        "source_ref": f"GEN {i}",
        "target_text": f"marubo verso numero {i} longo e distinto",
        "reference_text": por,
        "provenance": "corpus:GEN",
        "is_attested": True,
        "register": "scripture",
    }


def _chant_rows(prov: str, n: int, refrain_every: int = 0) -> list[dict[str, Any]]:
    tag = prov.split(":")[1][:4]
    rows = []
    for i in range(n):
        shared = refrain_every and i % refrain_every == 0
        rows.append(
            {
                "source_ref": f"{tag}:{i}",
                "target_text": "refrao comum" if shared else f"{tag} canto {i} " + "ka " * (i % 6),
                "reference_text": f"{tag} verso {i} " + "de " * (i % 6),
                "provenance": prov,
                "is_attested": True,
                "register": "unspecified",
            }
        )
    return rows


def _read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _keys(rows: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    return (
        {comparison_key(r["translation"]["mzr"]) for r in rows},
        {comparison_key(r["translation"]["por"]) for r in rows},
    )


def test_chant_provenances_get_the_ritual_chant_register():
    for prov in CHANT_PROVENANCES:
        row = {"provenance": prov, "register": "unspecified"}
        assert register_of(row, CHANT_PROVENANCES) == CHANT_REGISTER
    assert (
        register_of({"provenance": "harvested:other", "register": "unspecified"}, CHANT_PROVENANCES)
        == "unspecified"
    )
    assert (
        register_of({"provenance": WENIA, "register": "narrative"}, CHANT_PROVENANCES)
        == "narrative"
    )


def test_apply_benchmark_v2_repairs_spacing_and_excludes_edition_notes():
    rows = [
        _verse(1),
        _verse(5),  # edition note
        _verse(7),  # whitespace before punctuation
        {**_verse(3), "provenance": WENIA, "reference_text": "TR no canto"},  # not scripture
    ]
    kept, repaired, excluded = apply_benchmark_v2(rows, "test")
    assert [r["source_ref"] for r in kept] == ["GEN 1", "GEN 7", "GEN 3"]
    assert kept[1]["reference_text"] == "texto portugues numero 7 longo e distinto, com espaco."
    assert [e["source_ref"] for e in excluded] == ["GEN 5"]
    assert excluded[0]["reason"] == "edition_note" and excluded[0]["split"] == "test"
    assert excluded[0]["portuguese"].startswith("TR:")
    assert [e["source_ref"] for e in repaired] == ["GEN 7"]
    assert repaired[0]["reason"] == "space_before_punctuation"
    assert repaired[0]["before"] != repaired[0]["after"]
    assert rows[2]["reference_text"].endswith(" .")  # input rows are never mutated


def test_export_v2_matches_v1_minus_exclusions_with_audit(tmp_path: Path):
    verses = [_verse(i) for i in range(1, 700)]
    one = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "v1").export(
        synthetic_phrases=[], attested_verses=verses, harvested_sentences=[], benchmark_version=1
    )
    two = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "v2").export(
        synthetic_phrases=[], attested_verses=verses, harvested_sentences=[]
    )
    audit = json.loads((tmp_path / "v2" / "benchmark_v2_audit.json").read_text(encoding="utf-8"))
    ex = {s: [e for e in audit["excluded"] if e["split"] == s] for s in ("val", "test")}
    assert ex["val"] and ex["test"] and audit["repaired"]
    assert two.val_count == one.val_count - len(ex["val"])
    assert two.test_count == one.test_count - len(ex["test"])
    assert two.train_count == one.train_count
    for split in ("val", "test"):
        for row in _read(tmp_path / "v2" / f"{split}.hf.jsonl"):
            por = row["translation"]["por"]
            assert "TR" not in por and " ," not in por and " ." not in por
    manifest = json.loads((tmp_path / "v2" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["benchmark_version"] == 2
    assert manifest["benchmark_audit_file"] == "benchmark_v2_audit.json"
    assert manifest["benchmark_audit_sha256"]
    assert json.loads((tmp_path / "v1" / "manifest.json").read_text())["benchmark_version"] == 1
    assert not (tmp_path / "v1" / "benchmark_v2_audit.json").exists()
    # excluded rows are not refilled and never appear in train
    excluded_refs = {e["source_ref"] for e in audit["excluded"]}
    train_ids = {r["id"] for r in _read(tmp_path / "v2" / "train.hf.jsonl")}
    assert not excluded_refs & train_ids


def test_select_chant_components_takes_whole_components_only():
    def r(ref: str, src: str, tgt: str, prov: str = WENIA) -> dict[str, Any]:
        return {
            "source_ref": ref,
            "target_text": src,
            "reference_text": tgt,
            "provenance": prov,
        }

    # a1/a2 share the Marubo key, a2/a3 share the Portuguese key: one component of three.
    pool = [r("a1", "x y", "um"), r("a2", "x y", "dois"), r("a3", "w", "dois")]
    pool += [r(f"s{i}", f"solo {i}", f"unico {i}") for i in range(10)]
    chosen, comps = select_chant_components(pool, target=4, seed=7)
    refs = {row["source_ref"] for row in chosen}
    assert ("a1" in refs) == ("a2" in refs) == ("a3" in refs)
    assert len(chosen) <= 4
    assert set(comps) == {id(row) for row in chosen}
    again, _ = select_chant_components(pool, target=4, seed=7)
    assert [x["source_ref"] for x in again] == [x["source_ref"] for x in chosen]


def _export_with_chant(out: Path) -> tuple[Any, dict[str, Any]]:
    verses = [
        {
            "source_ref": f"GEN {i}",
            "target_text": f"marubo verso numero {i} longo e distinto",
            "reference_text": f"texto portugues numero {i} longo e distinto",
            "provenance": "corpus:GEN",
            "is_attested": True,
            "register": "scripture",
        }
        for i in range(1, 1501)
    ]
    chant = _chant_rows(WENIA, 500, refrain_every=25) + _chant_rows(ZENODO, 160, refrain_every=40)
    summary = DatasetExporter(lang_code="mzr", output_dir=out).export(
        synthetic_phrases=[], attested_verses=verses, harvested_sentences=chant
    )
    manifest = json.loads((out / "chant_benchmark" / "manifest.json").read_text(encoding="utf-8"))
    return summary, manifest


def test_chant_benchmark_is_separate_exempt_leak_free_and_deterministic(tmp_path: Path):
    summary, cm = _export_with_chant(tmp_path / "a")
    out = tmp_path / "a"
    ctest = _read(out / "chant_benchmark" / "test.hf.jsonl")
    cval = _read(out / "chant_benchmark" / "val.hf.jsonl")
    assert len(ctest) == 100 and 25 <= len(cval) <= 40
    assert cm["status"] == "frozen" and cm["register_cap_exempt"] is True
    assert cm["test_count"] == 100 and cm["val_count"] == len(cval)
    assert cm["components"]["test"] >= 1 and cm["components"]["val"] >= 1
    assert cm["train_rows_removed"] >= 0
    assert len({r["component"] for r in ctest}) == cm["components"]["test"]
    assert all(r["register"] == CHANT_REGISTER for r in (*ctest, *cval))
    # the primary chant test rows are reused
    primary_test = _read(out / "test.hf.jsonl")
    primary_chant = [r for r in primary_test if r["provenance"] in CHANT_PROVENANCES]
    assert primary_chant and {r["id"] for r in primary_chant} <= {r["id"] for r in ctest}
    assert len(primary_chant) < len(ctest)  # chant benchmark is exempt from the 0.2 cap
    # zero both-side key overlap between the chant benchmark and train, and val vs test
    train = _read(out / "train.hf.jsonl")
    tr_m, tr_p = _keys(train)
    for rows in (ctest, cval):
        m, p = _keys(rows)
        assert not m & tr_m and not p & tr_p
    cm_k, cp_k = _keys(ctest)
    vm, vp = _keys(cval)
    assert not cm_k & vm and not cp_k & vp
    train_ids = {r["id"] for r in train}
    assert not train_ids & {r["id"] for r in (*ctest, *cval)}
    assert summary.register_histogram["test"][CHANT_REGISTER] == len(primary_chant)
    # determinism: a second export elsewhere is byte-identical
    _export_with_chant(tmp_path / "b")
    for rel in (
        "train.hf.jsonl",
        "val.hf.jsonl",
        "test.hf.jsonl",
        "benchmark_v2_audit.json",
        "chant_benchmark/manifest.json",
        "chant_benchmark/test.hf.jsonl",
        "chant_benchmark/val.hf.jsonl",
    ):
        a = (tmp_path / "a" / rel).read_bytes()
        b = (tmp_path / "b" / rel).read_bytes()
        assert a.replace(str(tmp_path / "a").encode(), b"X") == b.replace(
            str(tmp_path / "b").encode(), b"X"
        ), rel


def test_chant_benchmark_is_provisional_when_material_is_too_small(tmp_path: Path):
    verses = [_verse(i) for i in range(1, 300) if i % 5 and i % 7]
    chant = _chant_rows(WENIA, 90)
    DatasetExporter(lang_code="mzr", output_dir=tmp_path).export(
        synthetic_phrases=[], attested_verses=verses, harvested_sentences=chant
    )
    cm = json.loads((tmp_path / "chant_benchmark" / "manifest.json").read_text())
    assert cm["status"] == "provisional"
    assert cm["test_count"] < 100


@pytest.mark.parametrize("bad", [0, 3])
def test_unknown_benchmark_version_is_rejected(tmp_path: Path, bad: int):
    with pytest.raises(ValueError, match="benchmark_version"):
        DatasetExporter(lang_code="mzr", output_dir=tmp_path).export(
            synthetic_phrases=[],
            attested_verses=[_verse(1)],
            harvested_sentences=[],
            benchmark_version=bad,
        )
