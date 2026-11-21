"""Unit tests for high-throughput batch synthesis and dataset exporter (WP 2.3 & 2.4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from langpipe.synthesis.batch import HighThroughputBatchHarness
from langpipe.synthesis.export_dataset import (
    DatasetExporter,
    load_harvested_parallel_sentences,
    load_source_index,
)
from tests.fixtures.artifacts import requires_built_lexicon


@requires_built_lexicon
def test_batch_synthesis_harness(tmp_path: Path):
    harness = HighThroughputBatchHarness(
        lang_code="mzr",
        output_dir=tmp_path,
        use_clef=True,
    )
    phrases, summary = harness.run_batch(target_count=20, seed=42)

    assert len(phrases) == 20
    assert summary.total_generated == 20
    assert summary.passed_count + summary.quarantined_count == 20

    # Ensure output file is written and parseable
    out_file = tmp_path / "synthetic_phrases.json"
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(data["phrases"]) == 20
    assert "metadata" in data


def test_dataset_exporter_splits_and_governance(tmp_path: Path):
    exporter = DatasetExporter(lang_code="mzr", output_dir=tmp_path)

    # Mock synthetic clean phrases
    synth_phrases = [
        {
            "target": f"vaki-n isu oya-ai {i}",
            "portuguese": f"o menino vê o macaco {i}",
            "source_ref": f"synth_{i}",
            "valid": True,
            "quarantined": False,
            "provenance": "curriculum_template_v1",
        }
        for i in range(50)
    ]

    # Mock human-attested gold corpus verses
    gold_verses = [
        {
            "source_ref": f"GEN 1:{i + 1}",
            "target_text": f"Marubo text verse {i}",
            "reference_text": f"Texto em portugues {i}",
            "provenance": "corpus:GEN",
            "is_attested": True,
        }
        for i in range(40)
    ]

    summary = exporter.export(
        synthetic_phrases=synth_phrases,
        attested_verses=gold_verses,
        train_ratio=0.8,
        val_ratio=0.1,
        seed=42,
    )

    # Invariant 2 Check: Test split must be strictly 100% human-attested gold truth
    assert summary.test_purity_verified is True
    assert summary.test_count > 0

    # Check generated files
    assert (tmp_path / "train.hf.jsonl").exists()
    assert (tmp_path / "val.hf.jsonl").exists()
    assert (tmp_path / "test.hf.jsonl").exists()
    assert (tmp_path / "train.alpaca.jsonl").exists()
    assert (tmp_path / "train.chatml.jsonl").exists()
    assert (tmp_path / "manifest.json").exists()

    # Inspect test partition to guarantee NO synthetic entries leaked into test
    test_lines = (tmp_path / "test.hf.jsonl").read_text(encoding="utf-8").strip().split("\n")
    for line in test_lines:
        rec = json.loads(line)
        assert not rec["id"].startswith("synth_")
        assert "corpus:" in rec["provenance"]


def test_dataset_exporter_with_harvested_parallel(tmp_path: Path):
    exporter = DatasetExporter(lang_code="mzr", output_dir=tmp_path)

    synth = [
        {
            "target": "vaki-n oya-ai",
            "portuguese": "o menino vê",
            "source_ref": "s1",
            "valid": True,
            "quarantined": False,
        }
    ]
    attested = [
        {
            "source_ref": f"GEN 1:{i}",
            "target_text": f"biblical {i}",
            "reference_text": f"bíblia {i}",
            "provenance": "corpus:GEN",
            "is_attested": True,
        }
        for i in range(100)
    ]
    harvested = [
        {
            "source_ref": f"Cesarino-2017:({i})",
            "target_text": f"oral {i}",
            "reference_text": f"oral {i}",
            "provenance": "harvested:cesarino_2017",
            "is_attested": True,
        }
        for i in range(105)
    ]

    summary = exporter.export(
        synthetic_phrases=synth,
        attested_verses=attested,
        harvested_sentences=harvested,
        seed=42,
        # The per-file split is tested on its own here; the register cap has its own tests.
        max_register_share=None,
    )

    assert summary.test_purity_verified is True
    assert summary.val_purity_verified is True
    assert summary.harvested_test_count == 50
    assert summary.harvested_val_count == 25
    assert summary.harvested_train_count == 30
    assert len(summary.sha256_checksums) == 9
    assert (tmp_path / "manifest.json").exists()

    # Verify manifest JSON on disk has checksums
    manifest_data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert "sha256_checksums" in manifest_data
    assert manifest_data["harvested_test_count"] == 50
    assert manifest_data["test_purity_verified"] is True


def test_synthetic_target_phrase_rows_are_written(tmp_path: Path):
    # Regression for the silent drop: synthetic records use target_phrase /
    # portuguese_translation, which the old extractor did not read.
    exporter = DatasetExporter(lang_code="mzr", output_dir=tmp_path)
    synth = [
        {
            "target_phrase": f"vaki-n oya-ai {i}",
            "portuguese_translation": f"o menino vê {i}",
            "source_ref": f"synth_{i}",
            "valid": True,
            "quarantined": False,
            "provenance": "curriculum_template_v1",
        }
        for i in range(3)
    ]

    summary = exporter.export(synthetic_phrases=synth, attested_verses=[], seed=42)

    rows = (tmp_path / "train.hf.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(rows) == 3
    assert summary.synthetic_train_count == 3
    assert summary.train_count == len(rows)


def test_trace_ids_are_written_when_source_index_is_given(tmp_path: Path):
    exporter = DatasetExporter(
        lang_code="mzr",
        output_dir=tmp_path,
        source_index={
            "corpus:": {"source_id": "src_1", "policy_id": "pol_1", "run_id": "run_1"},
            "harvested:": {"source_id": "src_2", "policy_id": "pol_2", "run_id": "run_2"},
        },
    )
    attested = [
        {
            "source_ref": f"GEN 1:{i}",
            "target_text": f"biblical {i}",
            "reference_text": f"bíblia {i}",
            "provenance": "corpus:GEN",
            "is_attested": True,
        }
        for i in range(10)
    ]

    summary = exporter.export(synthetic_phrases=[], attested_verses=attested, seed=42)

    def first_row(name: str) -> dict:
        text = (tmp_path / name).read_text(encoding="utf-8").splitlines()[0]
        return json.loads(text)

    hf = first_row("test.hf.jsonl")
    alpaca = first_row("test.alpaca.jsonl")
    chatml = first_row("test.chatml.jsonl")
    for record in (hf, alpaca, chatml):
        assert record["source_id"] == "src_1"
        assert record["policy_id"] == "pol_1"
        assert record["run_id"] == "run_1"
        assert record["provenance"] == "corpus:GEN"
    assert summary.source_ids == ["src_1"]
    assert summary.policy_ids == ["pol_1"]


def test_empty_side_raises_instead_of_being_dropped(tmp_path: Path):
    exporter = DatasetExporter(lang_code="mzr", output_dir=tmp_path)
    synth = [
        {
            "target_phrase": "",
            "portuguese_translation": "texto",
            "source_ref": "broken",
            "valid": True,
            "quarantined": False,
            "provenance": "curriculum_template_v1",
        }
    ]

    with pytest.raises(ValueError, match="empty target or contact side"):
        exporter.export(synthetic_phrases=synth, attested_verses=[], seed=42)


def test_exported_rows_pass_the_training_trace_check(tmp_path: Path):
    # End-to-end: an exported corpus row is accepted by the training gate (ADR-0025).
    from langpipe.training.eligibility import filter_eligible

    exporter = DatasetExporter(lang_code="mzr", output_dir=tmp_path)
    attested = [
        {
            "source_ref": f"GEN 1:{i}",
            "target_text": f"biblical {i}",
            "reference_text": f"bíblia {i}",
            "provenance": "corpus:GEN",
            "is_attested": True,
        }
        for i in range(100)
    ]

    exporter.export(synthetic_phrases=[], attested_verses=attested, seed=42)

    rows = [
        json.loads(line)
        for line in (tmp_path / "train.hf.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows
    eligible, rejected = filter_eligible(rows)
    assert len(eligible) == len(rows)
    assert rejected == []


def test_prefix_resolution_stops_at_a_segment_boundary(tmp_path: Path):
    exporter = DatasetExporter(
        lang_code="mzr",
        output_dir=tmp_path,
        source_index={"corpus:GEN": {"source_id": "src_gen", "policy_id": "pol_1"}},
    )
    assert exporter._ids_for("corpus:GEN")["source_id"] == "src_gen"
    assert exporter._ids_for("corpus:GEN:1:1")["source_id"] == "src_gen"
    assert exporter._ids_for("corpus:GENESIS") == {}


def test_missing_production_inputs_raise_instead_of_exporting_tiny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)  # no var/ and no data/raw
    exporter = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "out")
    with pytest.raises(RuntimeError, match="no attested corpus verses"):
        exporter.export(synthetic_phrases=[])


def test_malformed_source_index_raises(tmp_path: Path):
    index = tmp_path / "index.json"
    index.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        load_source_index(index)


def test_harvested_loader_rejects_a_malformed_line(tmp_path: Path):
    harvested = tmp_path / "harvested"
    harvested.mkdir()
    (harvested / "x_parallel.jsonl").write_text(
        '{"src": "a", "tgt": "b"}\nnot-json\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="malformed JSON"):
        load_harvested_parallel_sentences(harvested)


def test_harvested_loader_skips_other_language_records(tmp_path: Path):
    harvested = tmp_path / "harvested"
    harvested.mkdir()
    (harvested / "x_parallel.jsonl").write_text(
        json.dumps({"src": "a", "tgt": "b", "lang": "mzr"})
        + "\n"
        + json.dumps({"src": "c", "tgt": "d", "lang": "eng"})
        + "\n",
        encoding="utf-8",
    )
    rows = load_harvested_parallel_sentences(harvested, lang_code="mzr")
    assert len(rows) == 1
    assert rows[0]["target_text"] == "a"


def _attested(n: int = 100) -> list[dict]:
    return [
        {
            "source_ref": f"GEN 1:{i}",
            "target_text": f"biblical {i}",
            "reference_text": f"bíblia {i}",
            "provenance": "corpus:GEN",
            "is_attested": True,
        }
        for i in range(n)
    ]


def _harvested(n: int = 100) -> list[dict]:
    return [
        {
            "source_ref": f"Cesarino-2017:({i})",
            "target_text": f"oral {i}",
            "reference_text": f"oral {i}",
            "provenance": "harvested:cesarino",
            "is_attested": True,
        }
        for i in range(n)
    ]


def test_harvested_benchmark_is_order_independent(tmp_path: Path):
    rows = _harvested(100)

    first = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "a").export(
        synthetic_phrases=[], attested_verses=_attested(), harvested_sentences=rows, seed=42
    )
    second = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "b").export(
        synthetic_phrases=[],
        attested_verses=_attested(),
        harvested_sentences=list(reversed(rows)),
        seed=42,
    )

    def test_ids(directory: str) -> list[str]:
        path = tmp_path / directory / "test.hf.jsonl"
        return [json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines()]

    # 20 scripture test rows anchor the default 20% register cap: 0.2 * 20 / 0.8 = 5.
    assert first.harvested_test_count == second.harvested_test_count == 5
    assert sorted(test_ids("a")) == sorted(test_ids("b"))


def test_manifest_counts_equal_file_rows(tmp_path: Path):
    summary = DatasetExporter(lang_code="mzr", output_dir=tmp_path).export(
        synthetic_phrases=[], attested_verses=_attested(120), seed=42
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in (
        ("train.hf.jsonl", summary.train_count),
        ("val.hf.jsonl", summary.val_count),
        ("test.hf.jsonl", summary.test_count),
    ):
        lines = (tmp_path / name).read_text(encoding="utf-8").splitlines()
        assert len(lines) == expected
        assert manifest[name.split(".")[0] + "_count"] == expected


def test_synthetic_rows_get_a_real_provenance_and_are_counted_untraceable(tmp_path: Path):
    synth = [
        {
            "target_phrase": "vaki-n oya-ai",
            "portuguese_translation": "o menino vê",
            "source_ref": "synth_1",
            "valid": True,
            "quarantined": False,
        }
    ]
    summary = DatasetExporter(lang_code="mzr", output_dir=tmp_path).export(
        synthetic_phrases=synth, attested_verses=[], seed=42
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "train.hf.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows and all(row["provenance"] == "synthetic:curriculum" for row in rows)
    assert "unknown" not in rows[0]["provenance"]
    # No registered source maps synthetic rows yet, so the manifest says so honestly.
    assert summary.rows_without_source_ids == len(rows)


def test_adding_a_harvested_file_does_not_swap_an_existing_benchmark(tmp_path: Path):
    rows = _harvested(100)
    other = [
        {
            "source_ref": f"Wenia-2018:({i})",
            "target_text": f"wenia {i}",
            "reference_text": f"wenia {i}",
            "provenance": "harvested:wenia",
            "is_attested": True,
        }
        for i in range(100)
    ]

    # Per-file split only; the capped variant is test_register_cap_adding_another_register_*.
    one = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "one").export(
        synthetic_phrases=[],
        attested_verses=_attested(),
        harvested_sentences=rows,
        seed=42,
        max_register_share=None,
    )
    two = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "two").export(
        synthetic_phrases=[],
        attested_verses=_attested(),
        harvested_sentences=rows + other,
        seed=42,
        max_register_share=None,
    )

    def test_rows(directory: str) -> list[dict]:
        path = tmp_path / directory / "test.hf.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    cesarino_one = {r["id"] for r in test_rows("one") if r["provenance"] == "harvested:cesarino"}
    cesarino_two = {r["id"] for r in test_rows("two") if r["provenance"] == "harvested:cesarino"}
    assert cesarino_one == cesarino_two
    # Each source contributes its own share; the second file does not replace the first.
    assert one.harvested_test_count == 50
    assert two.harvested_test_count == 100
    assert any(r["provenance"] == "harvested:wenia" for r in test_rows("two"))


def _rows(directory: Path, split: str) -> list[dict]:
    path = directory / f"{split}.hf.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _chant(prefix: str, n: int, register: str | None = None) -> list[dict]:
    rows = []
    for i in range(n):
        row = {
            "source_ref": f"{prefix}:({i})",
            "target_text": f"{prefix} mzr {i}",
            "reference_text": f"{prefix} por {i}",
            "provenance": f"harvested:{prefix}",
            "is_attested": True,
        }
        if register:
            row["register"] = register
        rows.append(row)
    return rows


def test_register_cap_holds_in_test_and_val_and_overflow_goes_to_train(tmp_path: Path):
    # 2,000 verses -> 200 scripture test rows, 180 val rows; 1,000 chant rows -> 50/25 per file.
    attested = _attested(2000)
    harvested = _chant("wenia", 1000, "ritual_chant") + _chant("zenodo", 200, "ritual_chant")
    synth = [
        {"target_phrase": "a b", "portuguese_translation": "c d", "valid": True},
    ]
    uncapped = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "off").export(
        synthetic_phrases=synth,
        attested_verses=attested,
        harvested_sentences=harvested,
        seed=42,
        max_register_share=None,
    )
    summary = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "on").export(
        synthetic_phrases=synth,
        attested_verses=attested,
        harvested_sentences=harvested,
        seed=42,
    )
    out = tmp_path / "on"

    assert summary.max_register_share == 0.20
    assert summary.register_cap_limits == {"test": 50, "val": 45}
    for split in ("test", "val"):
        rows = _rows(out, split)
        chant = [r for r in rows if r["provenance"].startswith("harvested:")]
        assert len(chant) / len(rows) <= 0.20
        # Trace ids and attested-only purity survive the cap.
        assert all(r["provenance"] for r in rows)
        assert not any(r["provenance"].startswith("synthetic:") for r in rows)
    assert summary.test_purity_verified and summary.val_purity_verified
    assert summary.register_histogram["test"] == {"ritual_chant": 50, "scripture": 200}
    assert summary.register_overflow_to_train == {
        "test": {"ritual_chant": 50},
        "val": {"ritual_chant": 5},
    }
    # Count conservation: overflow moves to train, nothing is dropped.
    # Rows the chant benchmark moves out of train are the only other place a row can go.
    total = summary.train_count + summary.val_count + summary.test_count
    total += summary.chant_benchmark["train_rows_removed"]
    assert total == uncapped.train_count + uncapped.val_count + uncapped.test_count
    moved = summary.chant_benchmark["train_rows_removed"]
    assert summary.harvested_train_count == uncapped.harvested_train_count + 55 - moved
    train_ids = {r["id"] for r in _rows(out, "train")}
    moved = {r["id"] for r in _rows(tmp_path / "off", "test")} - {
        r["id"] for r in _rows(out, "test")
    }
    # Overflow rows land in train, or in the separate chant benchmark when it claims them.
    chant_ids = {r["id"] for r in _rows(out / "chant_benchmark", "test")}
    assert moved and moved <= train_ids | chant_ids


def test_register_cap_adding_another_register_leaves_existing_test_rows(tmp_path: Path):
    base = _chant("wenia", 1000, "ritual_chant")
    added = _chant("vana", 300, "narrative")
    one = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "one").export(
        synthetic_phrases=[], attested_verses=_attested(2000), harvested_sentences=base, seed=42
    )
    two = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "two").export(
        synthetic_phrases=[],
        attested_verses=_attested(2000),
        harvested_sentences=base + added,
        seed=42,
    )

    def ids(directory: str, split: str, prefix: str) -> set[str]:
        return {
            r["id"]
            for r in _rows(tmp_path / directory, split)
            if r["provenance"] == f"harvested:{prefix}"
        }

    assert ids("one", "test", "wenia") == ids("two", "test", "wenia")
    assert ids("one", "val", "wenia") == ids("two", "val", "wenia")
    assert one.register_cap_limits == two.register_cap_limits
    assert ids("two", "test", "vana")


def test_register_cap_adding_a_same_register_file_only_shrinks_existing_rows(tmp_path: Path):
    base = _chant("zenodo", 200, "ritual_chant")
    added = _chant("wenia", 1000, "ritual_chant")
    one = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "one").export(
        synthetic_phrases=[], attested_verses=_attested(2000), harvested_sentences=base, seed=42
    )
    two = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "two").export(
        synthetic_phrases=[],
        attested_verses=_attested(2000),
        harvested_sentences=base + added,
        seed=42,
    )

    def ids(directory: str, prefix: str) -> set[str]:
        return {
            r["id"]
            for r in _rows(tmp_path / directory, "test")
            if r["provenance"] == f"harvested:{prefix}"
        }

    assert len(ids("one", "zenodo")) == 50
    # The register's 50 slots are shared evenly; the old file keeps a subset, no swaps.
    assert len(ids("two", "zenodo")) == len(ids("two", "wenia")) == 25
    assert ids("two", "zenodo") < ids("one", "zenodo")
    assert "test" not in one.register_overflow_to_train
    assert two.register_overflow_to_train["test"] == {"ritual_chant": 50}
    kept = two.train_count + two.val_count + two.test_count
    assert kept + two.chant_benchmark["train_rows_removed"] == 2000 + 1200


def test_absent_register_loads_as_unspecified_and_is_capped(tmp_path: Path):
    harvested = tmp_path / "harvested"
    harvested.mkdir()
    (harvested / "x_parallel.jsonl").write_text(
        json.dumps({"ref": "r1", "src": "a", "tgt": "b"})
        + "\n"
        + json.dumps({"ref": "r2", "src": "c", "tgt": "d", "register": "ritual_chant"})
        + "\n",
        encoding="utf-8",
    )
    rows = load_harvested_parallel_sentences(harvested)
    assert [r["register"] for r in rows] == ["unspecified", "ritual_chant"]

    summary = DatasetExporter(lang_code="mzr", output_dir=tmp_path / "out").export(
        synthetic_phrases=[],
        attested_verses=_attested(2000),
        harvested_sentences=_chant("zenodo", 200),
        seed=42,
    )
    assert summary.register_histogram["test"]["unspecified"] == 50


def test_register_cap_without_scripture_is_skipped_with_a_warning(tmp_path: Path):
    summary = DatasetExporter(lang_code="mzr", output_dir=tmp_path).export(
        synthetic_phrases=[], attested_verses=[], harvested_sentences=_chant("w", 100), seed=42
    )
    assert summary.harvested_test_count == 50
    assert summary.register_cap_limits["test"] is None
    assert any("no scripture rows" in w for w in summary.warnings)


def test_register_cap_rejects_an_out_of_range_share(tmp_path: Path):
    with pytest.raises(ValueError, match="max_register_share"):
        DatasetExporter(lang_code="mzr", output_dir=tmp_path).export(
            synthetic_phrases=[], attested_verses=_attested(), max_register_share=0.0
        )


def test_failed_export_leaves_the_previous_dataset_untouched(tmp_path: Path):
    exporter = DatasetExporter(lang_code="mzr", output_dir=tmp_path)
    exporter.export(synthetic_phrases=[], attested_verses=_attested(120), seed=42)
    before = {path.name: path.read_bytes() for path in tmp_path.glob("*.jsonl")}
    manifest_before = (tmp_path / "manifest.json").read_bytes()

    broken = [
        {
            "target_phrase": "",
            "portuguese_translation": "texto",
            "provenance": "synthetic:curriculum",
            "valid": True,
            "quarantined": False,
        }
    ]
    with pytest.raises(ValueError, match="empty target or contact side"):
        exporter.export(synthetic_phrases=broken, attested_verses=[], seed=42)

    after = {path.name: path.read_bytes() for path in tmp_path.glob("*.jsonl")}
    assert after == before
    assert (tmp_path / "manifest.json").read_bytes() == manifest_before
    assert not list(tmp_path.glob("*.tmp"))
