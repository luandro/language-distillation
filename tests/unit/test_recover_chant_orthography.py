"""Offline tests for scripts/recover_chant_orthography.py.

No PDF and no subprocess: the matcher is exercised on small inline reference lines. The one
regression test that reads the Villada PDF is skipped when it or ``pdftotext`` is absent.
"""

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "recover_chant_orthography.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("recover_chant_orthography", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rc = _load()

CANDIDATE = {
    "ref": "cesarino-2013:p30:l18",
    "src": "Ato aki amaino",
    "tgt": "E enquanto isso",
    "eng": "",
    "qc": {"page": 30, "printed_line": None},
}


def test_row_key_repairs_the_scan_nasal_stand_ins() -> None:
    # Marúbo has no /l/ or /z/, and the 2013 scan prints `z`/`l`/`T` for a nasal vowel.
    assert rc.row_key("Koz rome weki") == rc.row_key("Koĩ rome weki")
    assert rc.row_key("inlki") == rc.row_key("inĩki")
    assert rc.row_key("Chz kirinatosho") == rc.row_key("Chĩ kirinatosho")


def test_reference_key_keeps_both_but_strips_every_mark() -> None:
    assert rc.reference_key("Awẽ aki amaĩnõ") == rc.reference_key("awe aki amaino")
    assert rc.fold("Kaná Kawã") == "kana kawa"


def test_adds_nasal_marks_only_when_a_mark_is_new() -> None:
    assert rc.adds_nasal_marks("Atõ aki amaĩnõ", "Ato aki amaino")
    assert not rc.adds_nasal_marks("A iki aoi", "A iki aoi")


def test_recover_attaches_the_cited_form_and_keeps_the_observation() -> None:
    references = {"villada-2018": [("villada-2018:p8", "Atõ aki amaĩnõ")]}

    records, qa = rc.recover([CANDIDATE], references)

    assert len(records) == 1
    record = records[0]
    assert record["src"] == CANDIDATE["src"]  # observed OCR text untouched
    assert record["clean_src"] == "Atõ aki amaĩnõ"
    assert record["clean_sources"] == ["villada-2018:p8"]
    assert record["clean_evidence"] == "unanimous"
    assert record["qc"]["clean_delta"] == "nasal-marks-added"
    assert qa["matched"] == 1
    assert qa["adds_nasal_marks"] == 1
    assert qa["clean_src_rows"] == 1


def test_recover_reports_conflicting_citations_instead_of_voting() -> None:
    references = {
        "villada-2018": [("villada-2018:p8", "Kaná Kawã yochĩni")],
        "other-article": [("other-article:p3", "Kanã kawã yochĩni")],
    }
    candidate = {**CANDIDATE, "src": "Kaná kawa yochini"}

    records, qa = rc.recover([candidate], references)

    record = records[0]
    assert record["clean_src"] is None
    assert record["clean_evidence"] == "conflict"
    assert record["clean_candidates"] == ["Kaná Kawã yochĩni", "Kanã kawã yochĩni"]
    assert qa["conflict"] == 1
    assert qa["unanimous"] == 0


def test_recover_ignores_rows_shorter_than_the_key_bound() -> None:
    references = {"villada-2018": [("villada-2018:p8", "a")]}
    candidate = {**CANDIDATE, "src": "A"}

    records, qa = rc.recover([candidate], references)

    assert records == []
    assert qa["too_short"] == 1


def test_recover_skips_rows_with_no_reference_match() -> None:
    records, qa = rc.recover(
        [CANDIDATE], {"villada-2018": [("villada-2018:p8", "Iki kavi amaĩno")]}
    )

    assert records == []
    assert qa["matched"] == 0


# --- shared-formula (JSONL) references ---------------------------------------------------

WENIA_LINE = {"ref": "cesarino-2018:p38:l21", "src": "Atõ aki amaĩnõ", "tgt": "E então"}
TIERS = {"villada-2018": rc.QUOTED_CHANT, "wenia-2018": rc.SHARED_FORMULA}


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def test_page_locators_keep_the_pdf_locator_shape() -> None:
    assert rc.page_locators("villada-2018", [(8, "Atõ aki amaĩnõ")]) == [
        ("villada-2018:p8", "Atõ aki amaĩnõ")
    ]


def test_read_reference_jsonl_uses_the_record_ref_verbatim_as_locator(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path / "wenia.jsonl", [WENIA_LINE, {"ref": "x:p1:l1", "src": ""}])

    assert rc.read_reference_jsonl(path) == [("cesarino-2018:p38:l21", "Atõ aki amaĩnõ")]


def test_jsonl_reference_confirms_a_quoted_chant_citation_with_tiered_fields() -> None:
    references = {
        "villada-2018": [("villada-2018:p8", "Atõ aki amaĩnõ")],
        "wenia-2018": [("cesarino-2018:p38:l21", "atõ aki amaĩnõ")],
    }

    records, qa = rc.recover([CANDIDATE], references, TIERS)

    record = records[0]
    assert record["clean_src"] == "Atõ aki amaĩnõ"  # the quoted-chant surface is kept
    assert record["clean_evidence"] == "unanimous"
    assert record["clean_confidence"] == "quoted-chant"
    assert record["clean_votes"] == 2
    # locator naming: PDF as <label>:p<page>, JSONL as the record ref, never <label>:<ref>
    assert record["clean_sources"] == ["cesarino-2018:p38:l21", "villada-2018:p8"]
    assert record["clean_citations"] == [
        {
            "locator": "cesarino-2018:p38:l21",
            "surface": "atõ aki amaĩnõ",
            "clean_confidence": "shared-formula",
        },
        {
            "locator": "villada-2018:p8",
            "surface": "Atõ aki amaĩnõ",
            "clean_confidence": "quoted-chant",
        },
    ]
    assert not any(src.startswith("wenia-2018:") for src in record["clean_sources"])
    assert qa["quoted_and_shared"] == [{"ref": CANDIDATE["ref"], "evidence": "unanimous"}]
    assert qa["by_reference"] == {"villada-2018": 1, "wenia-2018": 1}


def test_shared_formula_alone_never_originates_a_clean_src() -> None:
    references = {
        "villada-2018": [("villada-2018:p8", "Iki kavi amaĩno")],
        "wenia-2018": [("cesarino-2018:p38:l21", "Atõ aki amaĩnõ")],
    }

    records, qa = rc.recover([CANDIDATE], references, TIERS)

    record = records[0]
    assert record["src"] == CANDIDATE["src"]
    assert record["clean_src"] is None
    assert record["clean_sources"] == []
    assert record["clean_evidence"] == "uncorroborated"
    assert record["clean_confidence"] == "shared-formula"
    assert record["clean_candidates"] == ["Atõ aki amaĩnõ"]
    assert "clean_delta" not in record["qc"]
    assert qa["uncorroborated"] == 1
    assert qa["clean_src_rows"] == 0
    assert qa["quoted_and_shared"] == []


def test_shared_formula_with_different_marks_turns_a_citation_into_a_reported_conflict() -> None:
    references = {
        "villada-2018": [("villada-2018:p8", "Atõ aki amaĩnõ")],
        "wenia-2018": [("cesarino-2018:p38:l21", "Ato aki amaĩno")],
    }

    records, qa = rc.recover([CANDIDATE], references, TIERS)

    record = records[0]
    assert record["clean_src"] is None
    assert record["clean_evidence"] == "conflict"
    assert record["clean_confidence"] is None
    assert record["clean_candidates"] == ["Ato aki amaĩno", "Atõ aki amaĩnõ"]
    assert qa["quoted_and_shared"] == [{"ref": CANDIDATE["ref"], "evidence": "conflict"}]


def test_quoted_chant_only_run_keeps_the_published_record_schema() -> None:
    records, _ = rc.recover([CANDIDATE], {"villada-2018": [("villada-2018:p8", "Atõ aki amaĩnõ")]})

    assert list(records[0]) == [
        "ref",
        "src",
        "tgt",
        "eng",
        "clean_src",
        "clean_candidates",
        "clean_sources",
        "clean_votes",
        "clean_evidence",
        "qc",
    ]


def test_cli_accepts_reference_jsonl(tmp_path: Path) -> None:
    candidates = _write_jsonl(tmp_path / "candidates.jsonl", [CANDIDATE])
    wenia = _write_jsonl(tmp_path / "wenia.jsonl", [WENIA_LINE])
    out = tmp_path / "out.jsonl"

    assert (
        rc.main(
            [
                "--candidates",
                str(candidates),
                "--reference-jsonl",
                f"wenia-2018:{wenia}",
                "--out",
                str(out),
            ]
        )
        == 0
    )

    (record,) = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert record["clean_evidence"] == "uncorroborated"
    assert record["clean_citations"][0]["locator"] == "cesarino-2018:p38:l21"


def test_read_reference_text_pages_and_skips(tmp_path: Path) -> None:
    text = tmp_path / "ref.txt"
    text.write_text(
        "preamble before any marker\n=== page 3 ===\n  Atõ aki amaĩnõ  \n\n   \n"
        "=== page 4 ===\nsegunda linha\n",
        encoding="utf-8",
    )

    assert rc.read_reference_text(text) == [(3, "  Atõ aki amaĩnõ  "), (4, "segunda linha")]


def test_cli_text_reference_originates_clean_src(tmp_path: Path) -> None:
    candidates = _write_jsonl(tmp_path / "candidates.jsonl", [CANDIDATE])
    text = tmp_path / "thesis.txt"
    text.write_text("=== page 12 ===\nAtõ aki amaĩnõ     Portuguese gloss\n", encoding="utf-8")
    out = tmp_path / "out.jsonl"

    assert (
        rc.main(
            [
                "--candidates",
                str(candidates),
                "--reference-text",
                f"cesarino-2008:{text}",
                "--out",
                str(out),
            ]
        )
        == 0
    )

    (record,) = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert record["clean_src"] == "Atõ aki amaĩnõ"
    assert record["clean_sources"] == ["cesarino-2008:p12"]
    assert record["clean_evidence"] == "unanimous"


def test_cli_rejects_duplicate_reference_labels(tmp_path: Path) -> None:
    candidates = _write_jsonl(tmp_path / "candidates.jsonl", [CANDIDATE])
    text = tmp_path / "thesis.txt"
    text.write_text("=== page 1 ===\nx\n", encoding="utf-8")
    wenia = _write_jsonl(tmp_path / "wenia.jsonl", [WENIA_LINE])
    base = ["--candidates", str(candidates), "--out", str(tmp_path / "o.jsonl")]

    for extra in (
        ["--reference-text", f"a:{text}", "--reference-text", f"a:{text}"],
        ["--reference-text", f"a:{text}", "--reference-jsonl", f"a:{wenia}"],
    ):
        with pytest.raises(SystemExit):
            rc.main(base + extra)


REPO = MODULE_PATH.parents[1]
VILLADA_PDF = REPO / "var" / "external" / "villada_2018" / "villada_2018.pdf"
COLUMNS = REPO / "exports" / "parallel_candidates" / "cesarino_2013_columns.jsonl"
PUBLISHED = REPO / "exports" / "parallel_candidates" / "cesarino_2013_clean_refs.jsonl"
WENIA = REPO / "exports" / "harvested_parallel" / "cesarino_2018_wenia_parallel.jsonl"
THESIS_TEXT = REPO / "var" / "artifacts" / "cesarino_2008_thesis" / "decoded.txt"


@pytest.mark.realdata
@pytest.mark.skipif(
    shutil.which("pdftotext") is None
    or not VILLADA_PDF.exists()
    or not WENIA.exists()
    or not THESIS_TEXT.exists(),
    reason="needs pdftotext, the Villada PDF, the Wenia jsonl and the decoded thesis text",
)
def test_three_reference_run_reproduces_the_published_file_byte_for_byte(tmp_path: Path) -> None:
    out = tmp_path / "clean_refs.jsonl"

    rc.main(
        [
            "--candidates",
            str(COLUMNS),
            "--reference",
            f"villada-2018:{VILLADA_PDF}",
            "--reference-jsonl",
            f"wenia-2018:{WENIA}",
            "--reference-text",
            f"cesarino-2008:{THESIS_TEXT}",
            "--out",
            str(out),
        ]
    )

    assert out.read_text(encoding="utf-8") == PUBLISHED.read_text(encoding="utf-8")
