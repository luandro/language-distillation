"""Offline tests for scripts/build_clean_ref_review.py.

No PDF and no subprocess: the pure helpers are exercised on inline fixtures.
"""

import importlib.util
import sys
import unicodedata
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "build_clean_ref_review.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_clean_ref_review", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


review = _load()


def _geometry(text: str, page: int = 30, row: int = 18) -> Any:
    box = review.Box(100.0, 200.0, 180.0, 211.0)
    target = review.Box(260.0, 202.0, 340.0, 213.0)
    return review.RowGeometry(page=page, row=row, segment_text=text, source=box, target=target)


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "ref": "cesarino-2013:p30:l18",
        "src": "Ato aki amaino",
        "tgt": "E enquanto isso",
        "eng": "",
        "clean_src": None,
        "clean_candidates": ["Atõ aki amaĩnõ"],
        "clean_sources": [],
        "clean_votes": 1,
        "clean_evidence": "conflict",
        "clean_confidence": None,
        "clean_citations": [
            {
                "locator": "villada-2018:p8",
                "surface": "Atõ aki amaĩnõ",
                "clean_confidence": "quoted-chant",
            }
        ],
        "qc": {"page": 30, "printed_line": None, "src_tokens": 3},
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------------- #
# src == recovered segment text
# --------------------------------------------------------------------------- #


def test_check_segments_accepts_exact_match() -> None:
    assert (
        review.check_segments([_row()], {"cesarino-2013:p30:l18": _geometry("Ato aki amaino")})
        == []
    )


def test_check_segments_strips_glued_margin_number_like_the_extractor() -> None:
    row = _row(src="Ato awe")
    assert review.check_segments([row], {row["ref"]: _geometry("140. Ato awe")}) == []


def test_check_segments_compares_in_nfc() -> None:
    decomposed = unicodedata.normalize("NFD", "Awẽ aki")
    row = _row(src=unicodedata.normalize("NFC", "Awẽ aki"))
    assert review.check_segments([row], {row["ref"]: _geometry(decomposed)}) == []


def test_check_segments_reports_text_mismatch() -> None:
    problems = review.check_segments([_row()], {"cesarino-2013:p30:l18": _geometry("Ato aki")})
    assert len(problems) == 1
    assert problems[0].startswith("cesarino-2013:p30:l18: src")


def test_check_segments_reports_missing_locator() -> None:
    problems = review.check_segments([_row()], {})
    assert problems == ["cesarino-2013:p30:l18: no row at this locator"]


def test_check_segments_counts_every_row() -> None:
    rows = [_row(), _row(ref="cesarino-2013:p30:l19", src="Vana")]
    geometry = {"cesarino-2013:p30:l18": _geometry("Ato aki amaino")}
    assert len(review.check_segments(rows, geometry)) == 1


# --------------------------------------------------------------------------- #
# points -> pixels and crops
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("points", "dpi", "pixels"),
    [(72.0, 200, 200), (36.0, 200, 100), (0.0, 200, 0), (1381.85, 200, 3838), (72.0, 300, 300)],
)
def test_pt_to_px(points: float, dpi: int, pixels: int) -> None:
    assert review.pt_to_px(points, dpi) == pixels


def test_crop_is_clamped_to_the_left_book_page() -> None:
    geometry = review.RowGeometry(
        page=30,
        row=1,
        segment_text="Ato",
        source=review.Box(2.0, 5.0, 100.0, 16.0),
        target=review.Box(200.0, 6.0, 330.0, 17.0),
    )
    crop = review.crop_for(geometry, page_width=700.0, page_height=900.0, dpi=200)
    assert crop.half == "left"
    assert crop.x == 0 and crop.y == 0
    assert crop.x + crop.width == review.pt_to_px(330.0 + review.PAD_X_PT, 200)
    assert crop.x + crop.width <= review.pt_to_px(350.0, 200)
    left, top, right, bottom = crop.highlight
    assert 0.0 <= left < right <= 1.0 and 0.0 <= top < bottom <= 1.0


def test_crop_on_the_right_book_page_never_reaches_the_left_one() -> None:
    geometry = review.RowGeometry(
        page=46,
        row=3,
        segment_text="Ato",
        source=review.Box(360.0, 300.0, 440.0, 311.0),
        target=review.Box(560.0, 301.0, 690.0, 312.0),
    )
    crop = review.crop_for(geometry, page_width=700.0, page_height=900.0, dpi=200)
    assert crop.half == "right"
    assert crop.x >= review.pt_to_px(350.0, 200)
    assert crop.x + crop.width <= review.pt_to_px(700.0, 200)


def test_page_heights_reads_every_page() -> None:
    xml = '<page width="1381.85" height="939.877"></page><page width="1294.89" height="937.662">'
    assert review.page_heights(xml) == [939.877, 937.662]


# --------------------------------------------------------------------------- #
# HTML escaping
# --------------------------------------------------------------------------- #

HOSTILE = "<script>alert('x')</script> & \"q\""


def test_render_entry_escapes_every_data_value() -> None:
    row = _row(
        src=HOSTILE,
        tgt=HOSTILE,
        clean_src=HOSTILE,
        clean_evidence="unanimous",
        clean_candidates=[HOSTILE],
        clean_citations=[{"locator": HOSTILE, "surface": HOSTILE, "clean_confidence": HOSTILE}],
        qc={"page": 30, "printed_line": HOSTILE, "src_tokens": 3},
    )
    geometry = _geometry(HOSTILE)
    crop = review.crop_for(geometry, page_width=700.0, page_height=900.0, dpi=200)
    out = review.render_entry(row, geometry, crop, None)
    assert "<script>" not in out
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; &amp; &quot;q&quot;" in out


def test_render_entry_escapes_published_label_and_fallback_sources() -> None:
    row = _row(clean_citations=[], clean_sources=["<b>villada</b>"])
    published = {"clean_evidence": "<i>unanimous</i>", "qc": {"clean_delta": "<u>x</u>"}}
    out = review.render_entry(row, None, None, published)
    for raw in ("<b>", "<i>", "<u>"):
        assert raw not in out
    assert "&lt;b&gt;villada&lt;/b&gt;" in out
    assert "No crop" in out


def test_render_page_escapes_rows_and_is_standalone() -> None:
    row = _row(src=HOSTILE)
    geometry = {row["ref"]: _geometry(HOSTILE)}
    crops = {row["ref"]: review.crop_for(geometry[row["ref"]], 700.0, 900.0, 200)}
    page = review.render_page([row], geometry, crops, {}, "check <ok>")
    assert "<script" not in page
    assert "check &lt;ok&gt;" in page
    assert "http://" not in page and "https://" not in page


# --------------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("evidence", "delta", "expected"),
    [
        ("conflict", "nasal-marks-added", "conflict"),
        ("uncorroborated", None, "shared-formula"),
        ("unanimous", "nasal-marks-added", "nasal-added"),
        ("unanimous", "identical", "confirmation"),
        ("unanimous", "same-letters", "confirmation"),
    ],
)
def test_category(evidence: str, delta: str | None, expected: str) -> None:
    qc: dict[str, Any] = {"page": 30}
    if delta:
        qc["clean_delta"] = delta
    assert review.category(_row(clean_evidence=evidence, qc=qc)) == expected


def test_image_name_and_anchor() -> None:
    assert review.image_name("cesarino-2013:p30:l18") == "p30-l18.png"
    assert review.anchor("cesarino-2013:p30:l18") == "r-p30-l18"


def test_lede_warns_that_citations_can_differ_from_print() -> None:
    page = review.render_page([], {}, {}, {}, "check ok")
    assert "A citation can differ from the 2013 print" in page


# --------------------------------------------------------------------------- #
# default candidate file and reviewing the published set in place
# --------------------------------------------------------------------------- #


def test_candidates_default_to_the_committed_clean_ref_set() -> None:
    args = review.build_parser().parse_args([])
    assert args.candidates == Path("exports/parallel_candidates/cesarino_2013_clean_refs.jsonl")


def test_published_defaults_to_the_same_committed_file() -> None:
    args = review.build_parser().parse_args([])
    assert args.published == args.candidates
    assert review.same_file(args.candidates, args.published)


def test_same_file_ignores_spelling() -> None:
    assert review.same_file(Path("exports/../exports/a.jsonl"), Path("exports/a.jsonl"))
    assert not review.same_file(Path("var/artifacts/a.jsonl"), Path("exports/a.jsonl"))


def test_render_entry_drops_the_published_column_in_place() -> None:
    out = review.render_entry(_row(), None, None, None, compare_published=False)
    assert "published:" not in out
    assert "observed OCR src" in out


def test_render_page_says_the_candidates_are_the_published_set() -> None:
    page = review.render_page([_row()], {}, {}, None, "check ok")
    assert "candidate file is the published clean-ref set" in page
    assert "published:" not in page
    assert "not in the published clean-ref set" not in page


def test_render_page_omits_the_cross_reference_without_a_published_set() -> None:
    row = _row(clean_evidence="conflict", clean_src=None)
    published = {
        row["ref"]: {"clean_evidence": "conflict", "qc": {"clean_delta": "nasal-marks-added"}}
    }
    compared = review.render_page([row], {}, {}, published, "check ok")
    assert "more rows that the published set marks as nasal-marks-added" in compared
    in_place = review.render_page([row], {}, {}, None, "check ok")
    assert "more rows that the published set marks as nasal-marks-added" not in in_place
