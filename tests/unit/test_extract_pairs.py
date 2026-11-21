"""Offline tests for scripts/extract_pairs.py.

No PDF and no subprocess: the extractors are exercised on small inline fixtures.
"""

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "extract_pairs.py"

BBOX = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<body>
<doc>
  <page width="600.0" height="800.0">
    <word xMin="30" yMin="100" xMax="90" yMax="110">Earo</word>
    <word xMin="95" yMin="100" xMax="160" yMax="110">Sanĩ</word>
    <word xMin="30" yMin="116" xMax="120" yMax="126">Nawa</word>
    <word xMin="38" yMin="132" xMax="140" yMax="142">Ea</word>
    <word xMin="145" yMin="132" xMax="200" yMax="142">wicha</word>
    <word xMin="330" yMin="100" xMax="380" yMax="110">Assim</word>
    <word xMin="385" yMin="100" xMax="440" yMax="110">aprendemos</word>
    <word xMin="330" yMin="116" xMax="360" yMax="126">sobre</word>
    <word xMin="330" yMin="132" xMax="360" yMax="142">das</word>
    <word xMin="365" yMin="132" xMax="450" yMax="142">plantas</word>
  </page>
</doc>
</body>
</html>
"""

IGT_TEXT = """REFERENCES

some prose that is not an appendix

Appendix B: Kamãne pikẽnkẽã yoã (The jaguar's almost eating story)

 7 kamã-ne     yawa pia-i
    jaguar-ERG white.lipped.peccary eat-HOD
    'The jaguar ate the white-lipped peccary.'

 8 ea kamã-ne ak-a o-rí
   INTJ 1SG jaguar-ERG get-HOD come:SG=DIR-IMP
    'A jaguar is getting me, come here.'
"""


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("extract_pairs", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ep = _load()


def test_parse_bbox_layout_reads_pages_and_words() -> None:
    pages = ep.parse_bbox_layout(BBOX)

    assert len(pages) == 1
    width, words = pages[0]
    assert width == 600.0
    assert [word.text for word in words][:3] == ["Earo", "Sanĩ", "Nawa"]


def test_split_columns_separates_left_and_right() -> None:
    _, words = ep.parse_bbox_layout(BBOX)[0]

    split = ep.split_columns(words, 600.0)

    assert split is not None
    left, right = split
    assert [word.text for word in left] == ["Earo", "Sanĩ", "Nawa", "Ea", "wicha"]
    assert [word.text for word in right] == ["Assim", "aprendemos", "sobre", "das", "plantas"]


def test_group_lines_orders_by_baseline() -> None:
    _, words = ep.parse_bbox_layout(BBOX)[0]

    left, _ = ep.split_columns(words, 600.0) or ([], [])
    lines = ep.group_lines(list(left))

    assert [line.text for line in lines] == ["Earo Sanĩ", "Nawa", "Ea wicha"]


def test_paragraphs_split_on_indent() -> None:
    _, words = ep.parse_bbox_layout(BBOX)[0]

    left, _ = ep.split_columns(words, 600.0) or ([], [])
    blocks = ep.paragraphs(ep.group_lines(list(left)))

    assert blocks == ["Earo Sanĩ Nawa", "Ea wicha"]


def test_orthography_heuristics() -> None:
    assert ep.looks_marubo("Askai nishõse professor marubo rasĩ ni ea take aki")
    assert not ep.looks_marubo("Este livro foi produzido com o apoio da associação")
    assert ep.looks_portuguese("As plantas que cultivamos na roça para a comunidade")
    assert not ep.looks_portuguese("Askai nishõse professor rasĩ ni ea take aki masvi")


def test_extract_facing_pairs_validated_paragraphs() -> None:
    pages = ep.parse_bbox_layout(BBOX)

    records, qa = ep.extract_facing(pages)

    assert qa["two_column_pages"] == 1
    assert records, "expected at least one validated facing pair"
    assert records[0]["ref"].startswith("vana-rasi:p1:p1")
    for record in records:
        assert record["src"] and record["tgt"]


IGT_LINES = [
    (72.0, "Appendix B: Kamãne pikẽnkẽã yoã (The jaguar's almost eating story)"),
    (77.5, "7 kamã-ne yawa pia-i"),
    (94.3, "jaguar-ERG white.lipped.peccary eat-HOD"),
    (94.3, "\u2018The jaguar ate the white-lipped peccary.\u2019"),
    (77.5, "8 ea kamã-ne ak-a o-rí"),
    (94.3, "INTJ 1SG jaguar-ERG get-HOD come:SG=DIR-IMP"),
    (94.3, "\u2018A jaguar is getting me, come here.\u2019"),
]


def test_extract_igt_lines_parses_numbered_clauses() -> None:
    records, qa = ep.extract_igt_lines(IGT_LINES)

    assert qa["clauses_found"] == 2
    assert len(records) == 2
    assert records[0]["ref"] == "smith-2021-twu:(appendix B clause 7)"
    assert "jaguar-ERG" in records[0]["gloss"]
    assert "white-lipped peccary" in records[0]["eng"]
    assert all("mzr" in record and "eng" in record for record in records)


# --------------------------------------------------------------------------- #
# ``columns`` extractor (interleaved chant/translation spreads)
# --------------------------------------------------------------------------- #

MZR_COLUMN = [
    "Awe nimeaito",
    "Ino Sheta Rekene",
    "Sheni vana nokoi",
    "Yove kaya apai",
    "Wa kaya nakiki",
    "Awe ar toya",
]
POR_COLUMN = [
    "Ali sempre vivia",
    "Mas Sheta Reke",
    "E chega o soprocanto",
    "Pajé mais forte",
    "O pátio da maloca",
    "Sua mulher grávida",
]
MZR_COLUMN_RIGHT = [
    "Niro Kaso iniki",
    "Awe tae tavasho",
    "Pakekawa kawai",
    "Amai tsaosho",
    "Ato okomaino",
    "Yoniokia aoa",
]
POR_COLUMN_RIGHT = [
    "O chamado Niro Kaso",
    "Na mesma aldeia",
    "Mas ela foge foge",
    "Com ela ficam",
    "E enquanto caçam",
    "E então ordena",
]


def _word(x: float, y: float, text: str, width: float = 38.0) -> str:
    return f'<word xMin="{x}" yMin="{y}" xMax="{x + width}" yMax="{y + 11}">{text}</word>'


def _line_words(x: float, y: float, text: str) -> list[str]:
    words, cursor = [], x
    for token in text.split():
        words.append(_word(cursor, y, token, width=6.0 * len(token)))
        cursor += 6.0 * len(token) + 6.0
    return words


def _spread_xhtml(
    *,
    right_shift: float = 8.0,
    repeat_first_row: bool = False,
    include_numbers: bool = True,
    wide_prose: bool = False,
) -> str:
    """Two book pages per sheet, each with a vernacular column and a translation column.

    The right-hand page keeps its own text and prints its translation column a few points
    lower, which is what the per-column baseline shift has to recover.
    """
    words: list[str] = []
    for index, (source, target) in enumerate(zip(MZR_COLUMN, POR_COLUMN, strict=True)):
        y = 100.0 + index * 26.0
        words += _line_words(110.0, y, source)
        words += _line_words(345.0, y, target)
    for index, (source, target) in enumerate(zip(MZR_COLUMN_RIGHT, POR_COLUMN_RIGHT, strict=True)):
        y = 100.0 + index * 26.0 + right_shift * 2
        words += _line_words(885.0, y, source)
        words += _line_words(1115.0, y + right_shift, target)
    if repeat_first_row:
        words += _line_words(110.0, 400.0, MZR_COLUMN[0])
        words += _line_words(345.0, 400.0, POR_COLUMN[0])
    if wide_prose:
        for index in range(6):
            y = 600.0 + index * 20.0
            words += _line_words(
                40.0, y, "o estatuto de verdade do evento narrado pelo cantador marubo"
            )
            words += _line_words(
                745.0, y, "como essa podem ser verificadas em algumas de minhas publicacoes"
            )
    if include_numbers:
        for y, number in ((100.0, "1"), (126.0, "5"), (152.0, "10")):
            words.append(_word(45.0, y, number, width=14.0))
            words.append(_word(760.0, y + right_shift * 2, number, width=14.0))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body><doc>'
        '<page width="1400.0" height="1000.0">' + "".join(words) + "</page>"
        "</doc></body></html>"
    )


def test_repair_portuguese_ocr_cedilla_and_superscript_variants() -> None:
    assert ep.repair_portuguese_ocr("Em seu come~o")[0] == "Em seu começo"
    assert ep.repair_portuguese_ocr("Com lan~as em punho")[0] == "Com lanças em punho"
    assert ep.repair_portuguese_ocr("Nao fa<;am assim!")[0] == "Nao façam assim!"
    assert ep.repair_portuguese_ocr("come\\:a a chorar")[0] == "começa a chorar"
    assert ep.repair_portuguese_ocr("forma\\=ªº")[0] == "formação"
    assert ep.repair_portuguese_ocr("tradi\\Ües")[0] == "tradições"
    assert ep.repair_portuguese_ocr("Grande Sucuri-Sol3")[0] == "Grande Sucuri-Sol"


def test_repair_portuguese_ocr_is_idempotent_and_reports_rules() -> None:
    repaired, applied = ep.repair_portuguese_ocr("A publica~ao saiu")

    assert repaired == "A publicação saiu"
    assert applied == ["cedilla-as-tilde", "nasal-diphthong"]
    assert ep.repair_portuguese_ocr(repaired) == (repaired, [])


def test_portuguese_residual_damage_flags_only_damaged_tokens() -> None:
    assert ep.portuguese_residual_damage("Texto limpo e correto") == []
    assert ep.portuguese_residual_damage('V6 disse "<leste copulam1') == [
        "V6",
        '"<leste',
        "copulam1",
    ]


def test_load_reference_vocabulary_reads_usfm_jsonl_and_tsv(tmp_path: Path) -> None:
    (tmp_path / "a.usfm").write_text("\\v 1 Awe nokoi \\w Ino\\w*\\v 2 Sheta", encoding="utf-8")
    (tmp_path / "b.jsonl").write_text(
        '{"src": "Yove kaya apai"}\n{"tgt": "ignored side"}\n', encoding="utf-8"
    )
    (tmp_path / "c.tsv").write_text("headword\tgloss\nVana\tfloresta\n", encoding="utf-8")

    vocabulary = ep.load_reference_vocabulary([str(tmp_path / "*")])

    assert {"awe", "nokoi", "ino", "yove", "kaya", "apai", "vana"} <= vocabulary
    assert "ignored" not in vocabulary


def test_vernacular_qc_flags_ocr_artifacts_without_repairing() -> None:
    qc = ep.vernacular_qc("Niro Kaso inlki", vocabulary={"niro", "kaso"})

    assert qc["src_tokens"] == 3
    assert qc["src_flags"] == ["l-for-nasal"]
    assert qc["src_unattested"] == ["inlki"]
    assert "src_unattested" not in ep.vernacular_qc("Niro Kaso", vocabulary={"niro", "kaso"})


def test_estimate_row_shift_recovers_printed_offset() -> None:
    source = [ep.Segment(110.0, 190.0, 100.0, "Awe"), ep.Segment(110.0, 200.0, 126.0, "Ino")]
    target = [ep.Segment(345.0, 420.0, 108.0, "Ali"), ep.Segment(345.0, 430.0, 134.0, "Mas")]

    shift = ep.estimate_row_shift(source, target)

    assert abs(shift - 8.0) <= 1.0
    pairs = ep.match_rows(source, target, shift)
    assert [(a.text, b.text) for a, b in pairs] == [("Awe", "Ali"), ("Ino", "Mas")]


def test_extract_columns_pairs_each_printed_row() -> None:
    pages = ep.parse_bbox_layout(_spread_xhtml())

    records, qa = ep.extract_columns(pages, ref_prefix="test-2013")

    assert qa["paired_pages"] == 1
    assert len(records) == 2 * len(MZR_COLUMN)
    pairs = [(record["src"], record["tgt"]) for record in records]
    assert pairs[0] == ("Awe nimeaito", "Ali sempre vivia")
    assert ("Sheni vana nokoi", "E chega o soprocanto") in pairs
    assert records[0]["ref"] == "test-2013:p1:l1"
    assert records[0]["eng"] == ""


def test_extract_columns_keeps_printed_line_locator() -> None:
    pages = ep.parse_bbox_layout(_spread_xhtml())

    records, _ = ep.extract_columns(pages)

    assert records[0]["qc"]["printed_line"] == "1"
    right_page = next(record for record in records if record["src"] == MZR_COLUMN_RIGHT[0])
    assert right_page["qc"]["printed_line"] == "1"
    assert right_page["qc"]["row"] != records[0]["qc"]["row"]


def test_extract_columns_drops_duplicate_row_pairs() -> None:
    pages = ep.parse_bbox_layout(_spread_xhtml(repeat_first_row=True))

    records, qa = ep.extract_columns(pages)

    assert qa["duplicates_removed"] == 1
    assert qa["duplicate_examples"][0]["src"] == MZR_COLUMN[0]
    assert len(records) == 2 * len(MZR_COLUMN)


def test_extract_columns_ignores_prose_spreads() -> None:
    pages = ep.parse_bbox_layout(_spread_xhtml(wide_prose=True))

    records, qa = ep.extract_columns(pages)

    assert len(records) == 2 * len(MZR_COLUMN)
    assert qa["pairs_found"] == len(records)


def test_extract_columns_requires_a_minimum_row_count() -> None:
    pages = ep.parse_bbox_layout(_spread_xhtml())

    records, qa = ep.extract_columns(pages, min_pairs_per_page=100)

    assert records == []
    assert qa["sparse_pages_skipped"] == 1


def _two_identical_sheets() -> list[tuple[float, list[Any]]]:
    sheet = ep.parse_bbox_layout(_spread_xhtml())[0]
    return [sheet, sheet]


def test_parse_column_gap_page_reads_page_and_gap() -> None:
    assert ep.parse_column_gap_page("25=25") == (25, 25.0)
    assert ep.parse_column_gap_page(" 148 = 22.5 ") == (148, 22.5)
    for bad in ("25", "25=", "x=25", "0=25", "25=0", "25=-3"):
        with pytest.raises(argparse.ArgumentTypeError):
            ep.parse_column_gap_page(bad)


def test_column_gap_override_changes_only_the_listed_page() -> None:
    pages = _two_identical_sheets()
    default, default_qa = ep.extract_columns(pages, keep_repeats=True)

    assert ep.extract_columns(pages, keep_repeats=True, column_gap_pages=None) == (
        default,
        default_qa,
    )
    assert ep.extract_columns(pages, keep_repeats=True, column_gap_pages={}) == (
        default,
        default_qa,
    )
    # A gap wide enough to merge every column leaves page 2 without pairs; page 1 is untouched.
    records, qa = ep.extract_columns(pages, keep_repeats=True, column_gap_pages={2: 5000.0})

    assert records == [record for record in default if record["qc"]["page"] == 1]
    assert qa["sparse_pages_skipped"] == 1


def test_column_gap_override_page_never_displaces_a_default_page_row() -> None:
    pages = _two_identical_sheets()

    plain, _ = ep.extract_columns(pages)
    # Same gap value, so page 1 extracts the same rows, but it is now an override page and
    # must yield every shared (src, tgt) key to the default-gap page 2.
    overridden, qa = ep.extract_columns(pages, column_gap_pages={1: ep.COLUMN_GAP})

    assert {record["qc"]["page"] for record in plain} == {1}
    assert {record["qc"]["page"] for record in overridden} == {2}
    assert [(r["src"], r["tgt"]) for r in overridden] == [(r["src"], r["tgt"]) for r in plain]
    assert qa["duplicates_removed"] == len(plain)
    assert qa["duplicate_examples"][0]["first_seen"].endswith(":p2:l1")


# --------------------------------------------------------------------------- #
# ``table`` extractor (born-digital chant tables) and the layout-era helpers
# --------------------------------------------------------------------------- #

TABLE_LAYOUT = """Pedro de Niemeyer Cesarino            ––––––––––––

Wenia: o surgimento dos antepassados
I. Filhos do Povo Sol (Vari Vake Nawavo)
1.             Vari awá chinãki                               Vida de anta-sol
               Vari mai paroke                                No vão da terra-sol
               Vari shõpa weki                                Vento de lírio-sol
               We sheamashõta                                 Vento envolve
5.             Veõini otivo                                   E ali repousa12

12
   O termo chinã, aí traduzido por “vida”, foi explicado como sendo uma metáfora para o sêmen.

               Vari mai nãko                                  Néctar da terra-sol13
               Nãko osõatõsho                                 Dentro do néctar
10.            Wení katsiinã                                  Surgimento começa
               Vari mai paroke                                No vão da terra-sol

59     estudos de literatura brasileira contemporânea, n. 53, p. 45-99, jan./abr. 2018.
"""


def test_words_with_tilde_i_are_one_token_not_two() -> None:
    """`postĩno` must not split at `ĩ`, or `no` counts as a Portuguese function word."""
    assert ep.vernacular_qc("Atõ kana postĩno")["src_tokens"] == 3
    assert ep.portuguese_ratio("Atõ kana postĩno") == 0.0
    assert ep.portuguese_ratio("Atõ awe shavokĩse") == 0.0


def test_parse_page_range_accepts_span_single_and_none() -> None:
    assert ep.parse_page_range(None) is None
    assert ep.parse_page_range("15") == (15, 15)
    assert ep.parse_page_range("15-48") == (15, 48)
    assert ep.parse_page_range(" 15 - 48 ") == (15, 48)


def test_split_table_row_reads_both_cells_and_margin_number() -> None:
    numbered = ep.split_table_row(
        "5.             Veõini otivo                                   E ali repousa12"
    )
    assert numbered == ("5", "Veõini otivo", "E ali repousa12")
    unnumbered = ep.split_table_row(
        "               Vari mai paroke                                No vão da terra-sol"
    )
    assert unnumbered == (None, "Vari mai paroke", "No vão da terra-sol")


def test_split_table_row_rejects_single_cell_lines() -> None:
    assert ep.split_table_row("I. Filhos do Povo Sol (Vari Vake Nawavo)") is None
    assert ep.split_table_row("Pedro de Niemeyer Cesarino            ––––––––––––") is None
    assert ep.split_table_row("") is None


def test_is_table_row_rejects_running_heads_and_wrapped_prose() -> None:
    assert not ep.is_table_row("Pedro de Niemeyer Cesarino", "––––––––––––")
    assert not ep.is_table_row(
        "estudos de literatura brasileira contemporânea",
        "n. 53, p. 45-99, jan./abr. 2018",
    )
    assert ep.is_table_row("Vari shõpa weki", "Vento de lírio-sol")


def test_extract_table_pairs_chant_rows_and_keeps_refrains() -> None:
    records, qa = ep.extract_table(TABLE_LAYOUT, ref_prefix="test-2018")

    assert qa["pages_with_pairs"] == 1
    pairs = [(record["src"], record["tgt"]) for record in records]
    assert pairs[0] == ("Vari awá chinãki", "Vida de anta-sol")
    assert ("Veõini otivo", "E ali repousa") in pairs
    # the refrain is printed twice and is text, not a duplicate to drop
    assert pairs.count(("Vari mai paroke", "No vão da terra-sol")) == 2
    assert qa["repeated_rows"] == 1
    assert records[0]["ref"] == "test-2018:p1:l1"
    assert records[0]["eng"] == ""


def test_extract_table_strips_footnote_markers_and_records_repairs() -> None:
    records, _ = ep.extract_table(TABLE_LAYOUT)

    repair = next(record for record in records if record["src"] == "Veõini otivo")
    assert repair["tgt"] == "E ali repousa"
    assert repair["qc"]["tgt_repairs"] == ["footnote-superscript"]
    assert repair["qc"]["tgt_raw"] == "E ali repousa12"
    other = next(record for record in records if record["src"] == "Vari mai nãko")
    assert other["tgt"] == "Néctar da terra-sol"


def test_extract_table_keeps_printed_line_locators_monotone() -> None:
    records, qa = ep.extract_table(TABLE_LAYOUT)

    locators = [record["qc"]["printed_line"] for record in records if record["qc"]["printed_line"]]
    assert locators == ["1", "5", "10"]
    assert qa["printed_line_locators"] == 3
    assert qa["numbering_gaps"] == 0


def test_extract_table_drops_prose_like_two_cell_lines() -> None:
    layout = (
        "12\n"
        "   O termo chinã, aí traduzido por vida,       foi explicado como metáfora.\n"
        "               Vari mai paroke                                No vão da terra-sol\n"
    )

    records, qa = ep.extract_table(layout)

    assert [record["src"] for record in records] == ["Vari mai paroke"]
    assert qa["prose_like_lines_rejected"] == 1


def test_assign_printed_lines_consumes_each_number_once() -> None:
    sources = [
        ep.Segment(x_min=98.0, x_max=180.0, y=y, text=text)
        for y, text in ((100.0, "a"), (112.0, "b"), (124.0, "c"), (136.0, "d"))
    ]
    # both numbers sit within the old tolerance of rows a and b; each may label one row only
    numbers = [(101.0, 70.0, "5"), (113.0, 70.0, "10")]

    assert ep._assign_printed_lines(numbers, sources) == ["5", "10", None, None]


def test_strip_leading_line_number_splits_glued_margin_number() -> None:
    assert ep._strip_leading_line_number("140. Ato awe shavoyai") == (
        "Ato awe shavoyai",
        "140",
    )
    assert ep._strip_leading_line_number("Ato awe shavoyai") == ("Ato awe shavoyai", None)
