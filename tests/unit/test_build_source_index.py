"""Offline tests for scripts/build_source_index.py.

No database: the pure prefix->trace-id mapping is exercised on fake in-memory records.
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "build_source_index.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_source_index", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


source_index = _load()


def _record(key: str) -> object:
    return source_index.RegisteredSource(
        source_id=f"src_{key}",
        policy_id=f"pol_{key}",
        registration_run_id=f"run_{key}",
    )


def _all_records() -> dict[str, object]:
    return {key: _record(key) for key in source_index.PREFIX_SOURCE_KEYS.values()}


def test_mapping_table_is_explicit() -> None:
    assert dict(source_index.PREFIX_SOURCE_KEYS) == {
        "corpus:": "scriptureearth-mzr",
        "harvested:zenodo_1008779_cesarino_marubo_2017_parallel": "cesarino-marubo-2017-death-path",
        "harvested:cesarino_2018_wenia_parallel": "wenia-2018",
        "harvested:costa_2002_parallel": "costa-2002-ergatividade-cindida",
    }


def test_index_projects_the_three_trace_ids_per_prefix() -> None:
    index = source_index.build_source_index(_all_records())
    assert index["corpus:"] == {
        "source_id": "src_scriptureearth-mzr",
        "policy_id": "pol_scriptureearth-mzr",
        "run_id": "run_scriptureearth-mzr",
    }
    assert index["harvested:zenodo_1008779_cesarino_marubo_2017_parallel"]["run_id"] == (
        "run_cesarino-marubo-2017-death-path"
    )


def test_index_has_exactly_one_entry_per_prefix() -> None:
    index = source_index.build_source_index(_all_records())
    assert set(index) == set(source_index.PREFIX_SOURCE_KEYS)
    assert all(set(entry) == {"source_id", "policy_id", "run_id"} for entry in index.values())


def test_index_keys_are_sorted() -> None:
    index = source_index.build_source_index(_all_records())
    assert list(index) == sorted(source_index.PREFIX_SOURCE_KEYS)


def test_unused_records_do_not_appear() -> None:
    records = _all_records()
    records["another-source"] = _record("another-source")
    index = source_index.build_source_index(records)
    assert len(index) == len(source_index.PREFIX_SOURCE_KEYS)


def test_missing_source_key_is_named() -> None:
    records = _all_records()
    del records["costa-2002-ergatividade-cindida"]
    with pytest.raises(source_index.MissingSources) as raised:
        source_index.build_source_index(records)
    assert raised.value.keys == ("costa-2002-ergatividade-cindida",)
    assert "costa-2002-ergatividade-cindida" in str(raised.value)


def test_every_missing_source_key_is_reported_sorted() -> None:
    records = _all_records()
    del records["scriptureearth-mzr"]
    del records["wenia-2018"]
    with pytest.raises(source_index.MissingSources) as raised:
        source_index.build_source_index(records)
    assert raised.value.keys == ("scriptureearth-mzr", "wenia-2018")


def test_output_path_never_replaces_the_committed_index() -> None:
    assert source_index.OUTPUT_PATH.name == "source_index.generated.json"
    assert source_index.OUTPUT_PATH.parent.name == "exports"


def test_render_is_deterministic_and_round_trips() -> None:
    index = source_index.build_source_index(_all_records())
    text = source_index.render(index)
    assert text.endswith("\n")
    assert json.loads(text) == index
    assert text == source_index.render(dict(reversed(list(index.items()))))


def test_exporter_resolves_every_emitted_provenance_string() -> None:
    """The index must hit DatasetExporter._ids_for for the strings the loaders really emit."""
    from langpipe.synthesis.export_dataset import DatasetExporter

    index = source_index.build_source_index(_all_records())
    exporter = DatasetExporter(lang_code="mzr", source_index=index)
    emitted = {
        "corpus:GEN": "scriptureearth-mzr",
        # file stems from load_harvested_parallel_sentences; derived rows inherit these
        "harvested:zenodo_1008779_cesarino_marubo_2017_parallel": "cesarino-marubo-2017-death-path",
        "harvested:cesarino_2018_wenia_parallel": "wenia-2018",
        "harvested:costa_2002_parallel": "costa-2002-ergatividade-cindida",
    }
    for provenance, key in emitted.items():
        assert exporter._ids_for(provenance)["source_id"] == f"src_{key}", provenance
    assert exporter._ids_for("harvested:unknown_file_parallel") == {}
