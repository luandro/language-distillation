"""Offline tests for scripts/wenia_tilde_decode.py and ``extract_pairs.py table --tilde-marks``.

The fixtures are a miniature PDF (uncompressed objects) whose content stream copies the real
Wenía 2018 operator pattern: Book Antiqua ``E`` followed by a separate Times New Roman CID
glyph, code 0x047A, whose ToUnicode is U+0020. One regression test reads the real PDF and is
skipped when it or ``pdftotext`` is absent.
"""

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


wtd = _load("wenia_tilde_decode")
ep = _load("extract_pairs")

BODY_CMAP = "beginbfchar\n<0028> <0045>\n<0003> <0020>\n<0050> <0070>\nendbfchar"
TNR_CMAP = "beginbfchar\n<047A> <0020>\n<0003> <0020>\nendbfchar"


def _obj(number: int, body: str) -> bytes:
    return f"{number} 0 obj\n{body}\nendobj\n".encode("latin1")


def _stream_obj(number: int, text: str) -> bytes:
    return _obj(number, f"<</Length {len(text)}>>\nstream\n{text}\nendstream")


def _pdf(content: str, tnr_name: str = "Times#20New#20Roman", tnr_cmap: str = TNR_CMAP) -> bytes:
    parts = [
        _obj(1, "<</Type/Pages/Kids[2 0 R]/Count 1>>"),
        _obj(2, "<</Type/Page/Contents 3 0 R/Resources<</Font<</F1 4 0 R/F2 5 0 R>>>>>>"),
        _stream_obj(3, content),
        _obj(4, "<</Type/Font/Subtype/Type0/BaseFont/ABCDEE+Book#20Antiqua/ToUnicode 6 0 R>>"),
        _obj(5, f"<</Type/Font/Subtype/Type0/BaseFont/{tnr_name}/ToUnicode 7 0 R>>"),
        _stream_obj(6, BODY_CMAP),
        _stream_obj(7, tnr_cmap),
    ]
    return b"".join(parts)


def _ops(data: bytes) -> list[dict[str, Any]]:
    objs = wtd.parse_objects(data)
    fonts = wtd.load_fonts(objs)
    ops: list[dict[str, Any]] = wtd.page_ops(objs, fonts, 2)
    return ops


def _stream(*ops: tuple[str, float, float, str]) -> str:
    return "\n".join(
        f"BT\n{font} 12 Tf\n1 0 0 1 {x} {y} Tm\n[<{hexed}>] TJ\nET" for font, x, y, hexed in ops
    )


E_OP = ("/F1", 97.584, 151.58, "0028")
TILDE_OP = ("/F2", 103.34, 151.58, "047A")


def test_detects_tilde_op_directly_after_e() -> None:
    hits = wtd.find_tilde_e(_ops(_pdf(_stream(E_OP, TILDE_OP))))

    assert hits == [{"x": 103.34, "y": 151.58}]


def test_plain_e_without_tilde_op_is_not_a_hit() -> None:
    plain = ("/F1", 120.0, 151.58, "0050")
    assert wtd.find_tilde_e(_ops(_pdf(_stream(E_OP, plain)))) == []


def test_tilde_op_on_another_baseline_or_after_non_e_is_not_a_hit() -> None:
    elsewhere = ("/F2", 103.34, 200.0, "047A")
    assert wtd.find_tilde_e(_ops(_pdf(_stream(E_OP, elsewhere)))) == []
    after_p = ("/F1", 97.584, 151.58, "0050")
    assert wtd.find_tilde_e(_ops(_pdf(_stream(after_p, TILDE_OP)))) == []


def test_genuine_space_code_and_unlisted_font_are_not_tildes() -> None:
    space = ("/F2", 103.34, 151.58, "0003")
    assert wtd.find_tilde_e(_ops(_pdf(_stream(E_OP, space)))) == []
    other_font = _pdf(_stream(E_OP, TILDE_OP), tnr_name="Arial")
    assert wtd.find_tilde_e(_ops(other_font)) == []
    # code in the table but the font's own ToUnicode does not map it to a space
    not_space = _pdf(_stream(E_OP, TILDE_OP), tnr_cmap="beginbfchar\n<047A> <1EBD>\nendbfchar")
    assert wtd.find_tilde_e(_ops(not_space)) == []


def _word(text: str, x0: float, x1: float, y0: float = 434.0) -> dict[str, Any]:
    return {"text": text, "box": [x0, y0, x1, y0 + 11.4]}


def test_locate_maps_hit_to_word_box_and_layout_line() -> None:
    words = [
        _word("515.", 56.0, 70.0),
        _word("“E", 97.584, 108.17),
        _word("píti", 110.5, 130.0),
    ]
    layout = "header\n 515.   “E píti\n"
    found = wtd.locate({"x": 108.14, "y": 595.32 - 440.0}, 595.32, words, layout)

    assert found["word"] == "“E"
    assert found["line_key"] == "515.“Epíti"
    assert found["e_index"] == 5
    assert found["line_occurrence"] == 0


def test_locate_refuses_when_no_layout_line_matches() -> None:
    words = [_word("E", 97.584, 103.4)]
    with pytest.raises(ValueError, match="no -layout line"):
        wtd.locate({"x": 103.34, "y": 595.32 - 440.0}, 595.32, words, "something else")


def test_apply_tilde_is_nfc_idempotent_and_e_only() -> None:
    once = wtd.apply_tilde("“E awe", 1)
    assert once == "“Ẽ awe"
    assert len(once) == len("“E awe")
    assert wtd.apply_tilde(once, 1) == once
    with pytest.raises(ValueError, match="no base letter"):
        wtd.apply_tilde("“E awe", 2)


def test_attach_refs_uses_page_line_and_occurrence() -> None:
    row = {
        "ref": "t:p1:l2",
        "src": "E anõ",
        "tgt": "Que",
        "qc": {"page": 1, "printed_line": "7"},
    }
    other = {**row, "ref": "t:p2:l1", "qc": {"page": 2, "printed_line": "7"}}
    occ = [{"page": 1, "line_key": "7.EanõQue", "line_occurrence": 0}]
    wtd.attach_refs(occ, [other, row])
    assert occ[0]["ref"] == "t:p1:l2"
    stray = [{"page": 3, "line_key": "nothing", "line_occurrence": 0}]
    wtd.attach_refs(stray, [row])
    assert stray[0]["ref"] is None


def test_attach_refs_is_idempotent_on_already_patched_rows() -> None:
    row = {
        "ref": "t:p1:l2",
        "src": "Ẽ anõ",
        "tgt": "Que",
        "qc": {"page": 1, "printed_line": "7"},
    }
    occ = [{"page": 1, "line_key": "7.EanõQue", "line_occurrence": 0}]
    wtd.attach_refs(occ, [row])
    assert occ[0]["ref"] == "t:p1:l2"


def test_attach_refs_raises_for_unmapped_hit_inside_harvested_pages() -> None:
    row = {"ref": "t:p1:l1", "src": "x", "tgt": "y", "qc": {"page": 1, "printed_line": None}}
    with pytest.raises(ValueError, match="no harvested row"):
        wtd.attach_refs([{"page": 1, "line_key": "nope", "line_occurrence": 0}], [row])


def _check(data: bytes) -> None:
    objs = wtd.parse_objects(data)
    fonts = wtd.load_fonts(objs)
    wtd.check_complete(objs, fonts, 2, wtd.page_ops(objs, fonts, 2))


def test_completeness_guard_passes_when_scan_and_parse_agree() -> None:
    _check(_pdf(_stream(E_OP, TILDE_OP)))
    _check(_pdf(_stream(E_OP)))


def test_completeness_guard_raises_on_tilde_drawn_by_unparsed_operator() -> None:
    tj = "BT\n/F1 12 Tf\n1 0 0 1 97.584 151.58 Tm\n[<0028>] TJ\nET\nBT /F2 12 Tf <047A> Tj ET"
    with pytest.raises(ValueError, match="1 tilde codes in the stream, 0 parsed"):
        _check(_pdf(tj))
    literal = "BT /F2 12 Tf (x) Tj ET"
    with pytest.raises(ValueError, match="literal string"):
        _check(_pdf(literal))


def test_object_stream_members_are_resolved() -> None:
    header = b"10 0 11 9 "
    stream = header + b"<</A 1>> <</BaseFont/X>>"
    head = b"<</Type/ObjStm/N 2/First 10>>"
    objs: dict[int, tuple[bytes, bytes | None]] = {}
    wtd._expand_object_stream(head, stream, objs)
    assert objs[10][0] == b"<</A 1>> " and objs[11][0] == b"<</BaseFont/X>>"


def test_unsupported_pdf_structures_raise() -> None:
    data = _pdf(_stream(E_OP)).replace(b"/Resources<<", b"/Resources 9 0 R<<", 1)
    objs = wtd.parse_objects(data)
    with pytest.raises(ValueError, match="indirect /Resources"):
        wtd.page_content(objs, 2)


LAYOUT = (
    "     5.      “E anõ ikinã”                          Que estou pedindo\n"
    "             Vari mai paroke                        No vão da terra\n"
    "             E anõ ikinã”                           Que estou pedindo\n"
    "             E anõ ikinã”                           Que estou pedindo\n"
)


def _mark(key: str, e_index: int, occurrence: int = 0) -> dict[str, Any]:
    return {"page": 1, "line_key": key, "e_index": e_index, "line_occurrence": occurrence}


def test_extract_table_applies_marks_to_src_only_and_by_line_repeat() -> None:
    plain, _ = ep.extract_table(LAYOUT, ref_prefix="t")
    marks = {
        1: [
            _mark("5.“Eanõikinã”Queestoupedindo", 3),
            _mark("Eanõikinã”Queestoupedindo", 0, occurrence=1),
        ]
    }
    marked, qa = ep.extract_table(LAYOUT, ref_prefix="t", tilde_marks=marks)

    srcs = [r["src"] for r in marked]
    assert srcs == ["“Ẽ anõ ikinã”", "Vari mai paroke", "E anõ ikinã”", "Ẽ anõ ikinã”"]
    assert qa["tilde_marks_applied"] == 2
    for before, after in zip(plain, marked, strict=True):
        assert {k: v for k, v in before.items() if k != "src"} == {
            k: v for k, v in after.items() if k != "src"
        }


def test_extract_table_without_marks_is_unchanged_and_marks_are_idempotent() -> None:
    plain, qa = ep.extract_table(LAYOUT, ref_prefix="t")
    assert "tilde_marks_applied" not in qa
    assert ep.apply_tilde_to_source("E anõ", "E anõ", 0) == "Ẽ anõ"
    assert ep.apply_tilde_to_source("Ẽ anõ", "Ẽ anõ", 0) == "Ẽ anõ"
    assert plain[2]["src"] == "E anõ ikinã”"


def test_extract_table_rejects_mark_off_an_e_and_unmatched_marks() -> None:
    with pytest.raises(ValueError, match="not on an E"):
        ep.extract_table(LAYOUT, tilde_marks={1: [_mark("5.“Eanõikinã”Queestoupedindo", 4)]})
    with pytest.raises(ValueError, match="unmatched tilde marks"):
        ep.extract_table(LAYOUT, tilde_marks={1: [_mark("no such line", 0)]})


def test_load_tilde_marks_groups_by_page(tmp_path: Path) -> None:
    path = tmp_path / "marks.json"
    path.write_text(
        json.dumps({"occurrences": [{"page": 3, "e_index": 0}, {"page": 3}, {"page": 9}]}),
        encoding="utf-8",
    )
    loaded = ep.load_tilde_marks(path)
    assert sorted(loaded) == [3, 9] and len(loaded[3]) == 2


PDF = ROOT / "var/external/wenia_2018/wenia_2018.pdf"
MARKS = ROOT / "exports/harvested_parallel/cesarino_2018_wenia_tilde_marks.json"
EXPECTED_REFS = {
    "cesarino-2018:p33:l25",
    "cesarino-2018:p37:l11",
    "cesarino-2018:p37:l16",
    "cesarino-2018:p42:l28",
    "cesarino-2018:p43:l11",
    "cesarino-2018:p43:l19",
    "cesarino-2018:p45:l12",
    "cesarino-2018:p46:l2",
}


@pytest.mark.realdata
@pytest.mark.skipif(not MARKS.exists(), reason="local Wenía marks report absent")
def test_committed_marks_cover_the_eight_image_confirmed_rows() -> None:
    report = json.loads(MARKS.read_text(encoding="utf-8"))
    assert report["count"] == len(report["occurrences"]) == 9
    assert {o["ref"] for o in report["occurrences"] if o["ref"]} == EXPECTED_REFS
    assert report["code"] == "0x047A"


@pytest.mark.realdata
@pytest.mark.skipif(
    not PDF.exists() or shutil.which("pdftotext") is None, reason="Wenía PDF or pdftotext absent"
)
def test_real_pdf_decodes_to_the_committed_marks() -> None:
    fresh = wtd.decode_pdf(PDF)
    committed = json.loads(MARKS.read_text(encoding="utf-8"))
    keep = ("page", "bbox", "e_index", "line_key", "line_occurrence")
    assert [{k: o[k] for k in keep} for o in fresh["occurrences"]] == [
        {k: o[k] for k in keep} for o in committed["occurrences"]
    ]
