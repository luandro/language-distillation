"""Offline tests for scripts/build_conflict_reads.py (tiny inline fixtures, no var/ inputs)."""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "build_conflict_reads.py"
_spec = importlib.util.spec_from_file_location("build_conflict_reads", _PATH)
assert _spec is not None and _spec.loader is not None
bcr = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bcr
_spec.loader.exec_module(bcr)

CANDS = ["awẽ aki", "awe aki"]


def _rows(refs: list[str]) -> list[dict[str, Any]]:
    return [{"ref": r, "clean_evidence": "conflict", "clean_candidates": CANDS} for r in refs]


def _worklist(refs: list[str]) -> list[dict[str, Any]]:
    return [
        {"idx": i, "ref": r, "candidates": CANDS, "crop": f"img/{i}.png"}
        for i, r in enumerate(refs)
    ]


def _pick(idx: int, pick: int, conf: str = "high", note: str = "") -> dict[str, Any]:
    return {"idx": idx, "pick": pick, "conf": conf, "note": note}


def test_conflict_rows_filters_and_keeps_file_order(tmp_path: Path) -> None:
    path = tmp_path / "refs.jsonl"
    lines = [
        {"ref": "b", "clean_evidence": "conflict"},
        {"ref": "a", "clean_evidence": "unanimous"},
        {"ref": "c", "clean_evidence": "conflict"},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    assert [r["ref"] for r in bcr.conflict_rows(path)] == ["b", "c"]


def test_check_worklist_fails_on_ref_or_candidate_mismatch() -> None:
    refs = ["r:p1:l1", "r:p1:l2"]
    bcr.check_worklist(_rows(refs), _worklist(refs))
    with pytest.raises(ValueError, match="worklist has r:p1:l9"):
        bcr.check_worklist(_rows(refs), _worklist(["r:p1:l1", "r:p1:l9"]))
    with pytest.raises(ValueError, match="worklist items"):
        bcr.check_worklist(_rows(refs), _worklist(refs[:1]))
    bad = _worklist(refs)
    bad[0]["candidates"] = ["x"]
    with pytest.raises(ValueError, match="candidates differ"):
        bcr.check_worklist(_rows(refs), bad)


def test_load_picks_rejects_out_of_range_and_duplicates(tmp_path: Path) -> None:
    cands = {0: CANDS}
    path = tmp_path / "p.json"
    path.write_text(json.dumps([_pick(0, 1)]), encoding="utf-8")
    assert bcr.load_picks(path, cands)[0]["pick"] == 1
    path.write_text(json.dumps([_pick(0, 2)]), encoding="utf-8")
    with pytest.raises(ValueError, match="out of range"):
        bcr.load_picks(path, cands)
    path.write_text(json.dumps([_pick(0, 0), _pick(0, 0)]), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        bcr.load_picks(path, cands)
    path.write_text(json.dumps([_pick(7, 0)]), encoding="utf-8")
    with pytest.raises(ValueError, match="not in worklist"):
        bcr.load_picks(path, cands)


def test_classify_statuses() -> None:
    def mk(*picks: int) -> list[dict[str, Any]]:
        return [{"name": "x", "pick": p, "conf": "high"} for p in picks]

    assert bcr.classify(mk(1, 1)) == ("agreed", 1)
    assert bcr.classify(mk(0, 1)) == ("disputed", None)
    assert bcr.classify(mk(-1, -1)) == ("disputed", None)
    assert bcr.classify(mk(0)) == ("unread", None)
    assert bcr.classify([]) == ("unread", None)


def test_build_records_sorted_with_null_clean_src() -> None:
    refs = ["r:p2:l1", "r:p1:l1", "r:p3:l1"]
    picks = {
        "glm": {0: _pick(0, 1), 1: _pick(1, 0), 2: _pick(2, 1)},
        "mimo": {0: _pick(0, 1), 1: _pick(1, -1, "low", "no parseable answer")},
    }
    fvc = {"free_disagree_or_empty": [{"idx": 1, "sonnet": 0, "haiku": 0}]}
    records = bcr.build(_rows(refs), _worklist(refs), picks, fvc)
    assert [r["ref"] for r in records] == ["r:p1:l1", "r:p2:l1", "r:p3:l1"]
    by_ref = {r["ref"]: r for r in records}
    agreed = by_ref["r:p2:l1"]
    assert agreed["status"] == "agreed" and agreed["print_spelling"] == "awe aki"
    assert agreed["claude_audit"] == {"sonnet": 1, "haiku": 1, "agree": True}
    disputed = by_ref["r:p1:l1"]
    assert disputed["status"] == "disputed" and disputed["print_spelling"] is None
    assert disputed["readers"][1]["empty"] is True
    assert disputed["claude_audit"] == {"sonnet": 0, "haiku": 0, "agree": True}
    unread = by_ref["r:p3:l1"]
    assert unread["status"] == "unread" and unread["claude_audit"] is None
    assert all(r["clean_src"] is None for r in records)


def test_check_against_compare_fails_loudly() -> None:
    records = [{"status": "agreed"}, {"status": "unread"}]
    ok = {"totals": {"agree_picked": 1, "agree_none": 0, "disagree": 0, "unread": [3]}}
    bcr.check_against_compare(records, ok)
    bad = {"totals": {"agree_picked": 2, "agree_none": 0, "disagree": 0, "unread": [3]}}
    with pytest.raises(ValueError, match="differ"):
        bcr.check_against_compare(records, bad)
