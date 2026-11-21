"""Offline tests for the row-adjudication skill scripts (.skills/row-adjudication/scripts).

Pure helpers only: no PDF, no subprocess, tiny inline fixtures.
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / ".skills" / "row-adjudication" / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


worklist = _load("build_worklist")
zoom = _load("render_zoom")
compare = _load("compare_picks")


def _row(ref: str, evidence: str = "conflict") -> dict[str, Any]:
    return {
        "ref": ref,
        "src": "Awe aki amaino",
        "tgt": "x",
        "clean_evidence": evidence,
        "clean_candidates": ["Awẽ aki amaĩnõ", "awẽ aki amainõ"],
    }


def test_image_name_uses_page_and_line() -> None:
    assert worklist.image_name("cesarino-2013:p100:l11") == "p100-l11.png"
    assert zoom.zoom_name("cesarino-2013:p25:l6") == "p25-l6.png"


def test_select_and_build_assign_global_idx() -> None:
    rows = [_row("c:p1:l1"), _row("c:p1:l2", "unanimous"), _row("c:p2:l1")]
    items = worklist.build_worklist(worklist.select_rows(rows, "conflict"), "img/")
    assert [item["idx"] for item in items] == [0, 1]
    assert items[1]["crop"] == "img/p2-l1.png"
    assert items[0]["candidates"] == ["Awẽ aki amaĩnõ", "awẽ aki amainõ"]


@pytest.mark.parametrize(
    ("count", "cap", "sizes"),
    [(191, 100, [96, 95]), (5, 100, [5]), (0, 100, []), (10, 3, [3, 3, 3, 1])],
)
def test_split_parts_respects_cap(count: int, cap: int, sizes: list[int]) -> None:
    parts = worklist.split_parts([{"idx": i} for i in range(count)], cap)
    assert [len(part) for part in parts] == sizes


def test_split_parts_rejects_zero_cap() -> None:
    with pytest.raises(ValueError):
        worklist.split_parts([], 0)


def test_missing_crops_reports_absent_files(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(b"x")
    items = [
        {"ref": "r1", "crop": str(tmp_path / "a.png")},
        {"ref": "r2", "crop": str(tmp_path / "b.png")},
    ]
    assert worklist.missing_crops(items) == ["r2"]


def test_zoom_box_doubles_offsets_and_size() -> None:
    assert zoom.zoom_box([2418, 441, 969, 196], 200, 400) == [4836, 882, 1938, 392]


def test_plan_keys_by_full_ref_and_reports_missing() -> None:
    geometry = {"dpi": 200, "rows": {"c:p9:l1": {"page": 9, "crop_px": [10, 20, 30, 40]}}}
    found, absent = zoom.plan([{"ref": "c:p9:l1"}, {"ref": "p9:l1"}], geometry, 400)
    assert found == [("c:p9:l1", 9, [20, 40, 60, 80])]
    assert absent == ["p9:l1"]


def test_pdftoppm_args_carry_pixel_box() -> None:
    args = zoom.pdftoppm_args(Path("b.pdf"), 7, [1, 2, 3, 4], 400, Path("out/p7-l1"))
    assert args[args.index("-x") + 1 : args.index("-x") + 2] == ["1"]
    assert args[args.index("-W") + 1] == "3"
    assert args[-2:] == ["b.pdf", "out/p7-l1"]


def _pick(idx: int, pick: int, conf: str = "high") -> dict[str, Any]:
    return {"idx": idx, "pick": pick, "conf": conf}


def test_compare_classifies_agree_none_and_disagree() -> None:
    items = [{"idx": i, "ref": f"r{i}", "candidates": ["a", "b"]} for i in range(4)]
    readers = {
        "sonnet": {0: _pick(0, 1), 1: _pick(1, -1), 2: _pick(2, 0), 3: _pick(3, 1, "low")},
        "haiku": {0: _pick(0, 1), 1: _pick(1, -1), 2: _pick(2, -1), 3: _pick(3, 1)},
    }
    result = compare.compare(items, readers)
    assert result["totals"] == {
        "total": 4,
        "agree_picked": 2,
        "agree_none": 1,
        "disagree": 1,
        "low_conf_any": [3],
        "unread": [],
    }
    (disagreement,) = result["disagreements"]
    assert disagreement["picks"]["sonnet"]["form"] == "a"
    assert disagreement["picks"]["haiku"]["form"] is None


def test_compare_flags_unread_rows() -> None:
    items = [{"idx": 0, "ref": "r0", "candidates": ["a"]}]
    result = compare.compare(items, {"x": {0: _pick(0, 0)}, "y": {}})
    assert result["totals"]["unread"] == [0]
    assert result["totals"]["agree_picked"] == 0


def test_load_picks_merges_parts_and_rejects_duplicates(tmp_path: Path) -> None:
    first, second = tmp_path / "p0.json", tmp_path / "p1.json"
    first.write_text(json.dumps([_pick(0, 1)]), encoding="utf-8")
    second.write_text(json.dumps([_pick(1, 0)]), encoding="utf-8")
    assert sorted(compare.load_picks([first, second])) == [0, 1]
    second.write_text(json.dumps([_pick(0, 0)]), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate idx 0"):
        compare.load_picks([first, second])


def test_none_pick_yields_observation_with_provenance() -> None:
    items = [{"idx": 0, "ref": "r0", "crop": "img/p1-l1.png", "candidates": ["a", "b"]}]
    readers = {
        "gemma": {0: {"idx": 0, "pick": -1, "conf": "high", "printed": "awẽ aki amaĩno"}},
        "ocr2": {0: {"idx": 0, "pick": -1, "conf": "low"}},
    }
    result = compare.compare(items, readers)
    (obs,) = result["observations"]
    assert obs["clean_src"] is None
    assert obs["crop"] == "img/p1-l1.png"
    assert obs["printed"]["gemma"]["form"] == "awẽ aki amaĩno"
    assert result["totals"]["agree_none"] == 1


reader = _load("run_reader")


def test_build_prompt_lists_letters_and_wording() -> None:
    pick = reader.build_prompt(["awẽ aki", "awe aki"], "pick")
    assert "A. awẽ aki\nB. awe aki" in pick
    assert "one line of a printed book" in pick
    assert "single letter, or NONE" in pick
    assert "highlight box" in reader.build_prompt(["x"], "pick", "ctx")
    assert "TEXT:" in reader.build_prompt(["x"], "transcribe")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("B", 1),
        ("**a**", 0),
        ("Answer: C", 2),
        ("(b)", 1),
        ("NONE", -1),
        ("none of them", -1),
        ("D", None),  # letter beyond the candidate count
        ("Banana", None),
        ("", None),
    ],
)
def test_parse_answer_pick(text: str, expected: int | None) -> None:
    assert reader.parse_answer(text, 3, "pick") == expected


def test_parse_answer_transcribe_uses_answer_line() -> None:
    text = "TEXT: awẽ aki\nANSWER: **B**"
    assert reader.parse_answer(text, 2, "transcribe") == 1
    assert reader.parse_answer("TEXT: awẽ aki", 2, "transcribe") is None
    assert reader.parse_answer("ANSWER: none", 2, "transcribe") == -1
    assert reader.transcription(text) == "awẽ aki"


def test_normalise_marks_keeps_marks_drops_case_and_punctuation() -> None:
    assert reader.normalise_marks("Awẽ, “aki”!") == reader.normalise_marks("awẽ aki")
    assert reader.normalise_marks("awẽ") != reader.normalise_marks("awe")
    assert reader.normalise_marks("awẽ") == reader.normalise_marks("awẽ")
    assert reader.normalise_marks("káta") != reader.normalise_marks("katá")


def test_match_printed_is_exact_on_marks_and_none_when_ambiguous() -> None:
    cands = ["awẽ aki", "awe aki"]
    assert reader.match_printed("Awẽ aki", cands) == 0
    assert reader.match_printed("awe aki", cands) == 1
    assert reader.match_printed("awẽ akí", cands) == -1
    assert reader.match_printed("aki", ["Aki", "aki"]) == -1  # both match: ambiguous


def test_to_pick_marks_empty_answer_low_and_none() -> None:
    assert reader.to_pick({"idx": 4, "pred": 1}) == {"idx": 4, "pick": 1, "conf": "high"}
    empty = reader.to_pick({"idx": 5, "pred": None})
    assert empty["pick"] == -1 and empty["conf"] == "low"


def test_clean_output_strips_ansi_and_banner() -> None:
    assert reader.clean_output("\x1b[0m> build\n\nB\n") == "B"


def test_main_refuses_parallel_and_low_opencode_throttle(tmp_path: Path) -> None:
    base = ["--reader", "opencode:x/y", "--worklist", str(tmp_path / "w.json")]
    out = ["--out", str(tmp_path / "o.json")]
    assert reader.main([*base, *out, "--jobs", "2"]) == 2
    assert reader.main([*base, *out, "--throttle", "1"]) == 2
    assert reader.main(["--reader", "nope:m", "--worklist", "w", *out]) == 2


def test_load_done_skips_errored_rows(tmp_path: Path) -> None:
    out = tmp_path / "o.json"
    assert reader.load_done(out) == []
    rows = [{"idx": 1, "pred": 0, "err": None}, {"idx": 2, "pred": None, "err": "boom"}]
    out.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    assert [row["idx"] for row in reader.load_done(out)] == [1]


def test_blocked_run_saves_partial_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = [{"idx": i, "candidates": ["a", "b"], "crop": "c.png"} for i in range(3)]
    work = tmp_path / "w.json"
    work.write_text(json.dumps(items), encoding="utf-8")
    out = tmp_path / "o.json"
    calls: list[int] = []

    def fake(_model: str, _prompt: str, _image: str) -> str:
        calls.append(1)
        if len(calls) == 2:
            raise reader.BlockedError("blocked")
        return "A"

    monkeypatch.setitem(reader.CALLERS, "ollama", fake)
    argv = ["--reader", "ollama:m", "--worklist", str(work), "--out", str(out)]
    assert reader.main(argv) == reader.EXIT_BLOCKED
    assert [r["idx"] for r in json.loads(out.read_text())["rows"]] == [0]
    picks = tmp_path / "p.json"
    assert reader.main([*argv, "--picks-out", str(picks)]) == 0
    assert [p["idx"] for p in json.loads(picks.read_text())] == [0, 1, 2]
