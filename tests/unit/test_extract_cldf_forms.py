"""Offline tests for scripts/extract_cldf_forms.py."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "extract_cldf_forms.py"

CSV_HEADER = (
    "ID,Local_ID,Language_ID,Parameter_ID,Value,Form,Segments,Comment,Source,"
    "Cognacy,Loan,ConceptInSource,UncertainCognacy,ProtoSet"
)
CSV_ROWS = [
    'Marubo-1_tomaketokill-1,1,Marubo,1_tomaketokill,a-,a-,a,,"Oliveira2014",12,false,,,',
    'Marubo-13_big-1,13,Marubo,13_big,ˈɐ̃ni-,ˈɐ̃ni-,ɐ̃ n i,,"Costa1992",7,false,,,',
    'Kakataibo-13_big-1,13,Kakataibo,13_big,ani-,ani-,a n i,,"Fleck2005",7,false,,,',
    'Marubo-99_empty-1,99,Marubo,99_empty,,, ,,"Censo",,false,,,',
]
CSV_TEXT = "\n".join([CSV_HEADER, *CSV_ROWS]) + "\n"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("extract_cldf_forms", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cf = _load()


def _write_csv(tmp_path: Path) -> Path:
    path = tmp_path / "forms.csv"
    path.write_text(CSV_TEXT, encoding="utf-8")
    return path


def test_load_and_select_language(tmp_path: Path) -> None:
    rows = cf.load_forms(_write_csv(tmp_path))

    selected = cf.select_language(rows, "Marubo")

    assert len(rows) == 4
    assert [row["ID"] for row in selected] == [
        "Marubo-1_tomaketokill-1",
        "Marubo-13_big-1",
        "Marubo-99_empty-1",
    ]


def test_to_proposals_drops_empty_forms_and_keeps_lineage(tmp_path: Path) -> None:
    rows = cf.select_language(cf.load_forms(_write_csv(tmp_path)), "Marubo")

    proposals = cf.to_proposals(rows, "oliveiraprotopanoan", "10.5281/zenodo.10214016", "Marubo")

    assert len(proposals) == 2
    first = proposals[0]
    assert first.ref == "Marubo-1_tomaketokill-1"
    assert first.form == "a-"
    assert first.concept == "1_tomaketokill"
    assert first.dataset_doi == "10.5281/zenodo.10214016"
    assert first.status == "candidate"
    assert first.comment == ""  # literal 'None' cells are normalised away
    # NFC normalization keeps the nasalized form intact
    assert proposals[1].form == "ˈɐ̃ni-"


def test_build_qa_counts_sources_and_cognacy(tmp_path: Path) -> None:
    rows = cf.select_language(cf.load_forms(_write_csv(tmp_path)), "Marubo")
    proposals = cf.to_proposals(rows, "ds", "doi", "Marubo")

    qa = cf.build_qa(proposals, len(rows), "Marubo")

    assert qa["proposals"] == 2
    assert qa["distinct_concepts"] == 2
    assert qa["sources"] == {"Costa1992": 1, "Oliveira2014": 1}
    assert qa["with_cognacy"] == 2
    assert "Proposals only" in qa["note"]


def test_cli_writes_proposals_and_qa(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    _write_csv(dataset).replace(dataset / "forms.csv")
    out = tmp_path / "out.jsonl"
    qa_path = tmp_path / "qa.json"

    code = cf.main(
        [
            "--dataset-dir",
            str(dataset),
            "--language-id",
            "Marubo",
            "--dataset-id",
            "oliveiraprotopanoan",
            "--dataset-doi",
            "10.5281/zenodo.10214016",
            "--out",
            str(out),
            "--qa",
            str(qa_path),
        ]
    )

    assert code == 0
    records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert json.loads(qa_path.read_text(encoding="utf-8"))["proposals"] == 2
