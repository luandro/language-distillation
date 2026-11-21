"""CPU-only tests for baseline_eval: retrieval, bootstrap, slices, contamination flags."""

from __future__ import annotations

import pytest

from langpipe.languages.mzr.profile import MZR_PROFILE
from langpipe.training.baseline_eval import (
    BenchmarkSpec,
    EvalRow,
    NearestRowRetriever,
    bootstrap_ci,
    build_rows,
    fold_key,
    percentile,
    retrieval_predictions,
    slice_definitions,
    sum_stats,
    v0_keys,
)

TARGET = MZR_PROFILE.language
CONTACT = "por"
SPEC = BenchmarkSpec(
    target=TARGET, contact=CONTACT, chant_provenances=frozenset(MZR_PROFILE.chant_provenances)
)


def _row(i: str, mzr: str, por: str, group: str = "bible", comp: str | None = None) -> EvalRow:
    prov = "corpus:GEN" if group == "bible" else "harvested:cesarino_2018_wenia_parallel"
    return EvalRow(i, {"mzr": mzr, "por": por}, prov, group, comp)


def test_fold_key_ignores_case_punct_diacritics() -> None:
    assert fold_key("  Nawá,  WENÍ! ") == fold_key("nawa weni")


def test_retrieval_selects_on_input_side_only() -> None:
    train = [
        _row("a", "nawa weni iniya", "povo junto surge"),
        # Output side of this row is a perfect match for the query text; must be ignored.
        _row("b", "xxxx yyyy", "aa bb cc dd"),
    ]
    r = NearestRowRetriever(train, SPEC)
    # por->mzr input "aa bb cc dd" equals the por side of b: exact input match, mzr returned
    assert r.translate("aa bb cc dd", "por") == "xxxx yyyy"
    # the same text as an mzr input must not match b: only the input side is indexed
    idx, _, exact = r.nearest("aa bb cc dd", "mzr")
    assert not exact


def test_retrieval_exact_folded_and_ngram_fallback() -> None:
    train = [_row("a", "kena shavo", "casa grande"), _row("b", "mato ene", "rio fundo")]
    r = NearestRowRetriever(train, SPEC)
    assert r.translate("CASA, grande!", "por") == "kena shavo"
    assert r.translate("rio fundos", "por") == "mato ene"  # near match, not exact
    idx, sim, exact = r.nearest("rio fundos", "por")
    assert idx == 1 and 0 < sim < 1 and not exact


def test_retrieval_predictions_direction() -> None:
    train = [_row("a", "kena shavo", "casa grande")]
    r = NearestRowRetriever(train, SPEC)
    rows = [_row("t", "kena shavo", "x")]
    assert retrieval_predictions(r, rows, "mzr->por") == ["casa grande"]


def test_sum_stats_and_percentile() -> None:
    assert sum_stats([[1, 2], [3, 4]]) == [4, 6]
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5


def _mean_score(tot: list[float]) -> float:
    return tot[0] / tot[1]


def test_bootstrap_deterministic_and_brackets_point() -> None:
    stats = [[float(i % 3), 1.0] for i in range(60)]
    units = [f"row:{i}" for i in range(60)]
    a = bootstrap_ci(stats, units, _mean_score, n_boot=300, seed=1)
    b = bootstrap_ci(stats, units, _mean_score, n_boot=300, seed=1)
    assert a == b
    point = _mean_score(sum_stats(stats))
    assert a[0] <= point <= a[1]


def test_bootstrap_by_component_is_wider_than_by_row() -> None:
    # 20 components of 5 rows; rows inside a component are identical -> strong clustering.
    stats, comps, rows = [], [], []
    for c in range(20):
        for j in range(5):
            stats.append([float(c % 2), 1.0])
            comps.append(f"component:{c}")
            rows.append(f"row:{c}-{j}")
    by_comp = bootstrap_ci(stats, comps, _mean_score, n_boot=500, seed=2)
    by_row = bootstrap_ci(stats, rows, _mean_score, n_boot=500, seed=2)
    assert (by_comp[1] - by_comp[0]) > (by_row[1] - by_row[0])


def test_bootstrap_constant_and_validation() -> None:
    assert bootstrap_ci([[1.0, 1.0]] * 5, list("abcde"), _mean_score, n_boot=50) == (1.0, 1.0)
    with pytest.raises(ValueError):
        bootstrap_ci([[1.0, 1.0]], ["a", "b"], _mean_score)


def test_unit_uses_component_for_chant_only() -> None:
    assert _row("1", "a", "b", "chant", "c9").unit == "component:c9"
    assert _row("2", "a", "b", "bible", "c9").unit == "row:2"
    assert _row("3", "a", "b", "chant").unit == "row:3"


def test_v0_overlap_flag_and_slices() -> None:
    v0 = v0_keys([{"translation": {"mzr": "Nawa weni", "por": "Povo surge"}}], SPEC)
    raw = [
        {
            "id": "1",
            "translation": {"mzr": "nawa, weni", "por": "outra"},
            "provenance": "corpus:GEN",
        },
        {
            "id": "2",
            "translation": {"mzr": "novo", "por": "povo SURGE"},
            "provenance": "harvested:cesarino_2018_wenia_parallel",
            "component": "cx",
        },
        {"id": "3", "translation": {"mzr": "zzz", "por": "yyy"}, "provenance": "corpus:LUK"},
    ]
    rows = build_rows(raw, SPEC, v0=v0)
    assert [r.in_v0_train for r in rows] == [True, True, False]
    assert rows[1].group == "chant" and rows[1].component == "cx"
    defs = slice_definitions("test", rows)
    assert defs["bible"] == [0, 2] and defs["chant"] == [1]
    assert defs["v0_overlap:true"] == [0, 1] and defs["v0_overlap:false"] == [2]
    assert defs["source:corpus:GEN"] == [0]


def test_scorer_matches_sacrebleu_corpus_score() -> None:
    sacrebleu = pytest.importorskip("sacrebleu")
    from langpipe.training.baseline_eval import Scorer

    hyps = ["a casa velha", "oi tudo bem", "nada"]
    refs = ["a casa velha e", "oi tudo", "nada aqui"]
    sc = Scorer(spbleu_tokenize="13a")  # avoids the spm model download in tests
    st = sc.row_stats(hyps, refs)
    got = sc.chrf_score(sum_stats([s[0] for s in st]))
    want = sacrebleu.corpus_chrf(hyps, [refs], word_order=2).score
    assert got == pytest.approx(want)
    got_b = sc.bleu_score(sum_stats([s[1] for s in st]))
    assert got_b == pytest.approx(
        sacrebleu.metrics.BLEU(tokenize="13a").corpus_score(hyps, [refs]).score
    )
