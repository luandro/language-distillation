"""Baseline evaluation on a frozen parallel benchmark: loading, retrieval, metrics, bootstrap.

Everything here runs on CPU without torch or transformers. ``sacrebleu`` is imported lazily and
only by the scorer. Model generation lives in ``scripts/eval_baselines_v2.py``.

A benchmark row stores its two sides in a ``translation`` object keyed by language code, and
directions are written ``<source>-><target>``. Both codes, and the provenances whose rows are
ritual chant, come from the caller's ``BenchmarkSpec``: the codes name fields of the benchmark
files, so they are data and this module hardcodes none.
"""

from __future__ import annotations

import json
import math
import random
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SYNTHETIC_PREFIX = "synthetic:"

_PUNCT_OR_SPACE = re.compile(r"[^\w]+", re.UNICODE)


def fold_key(text: str) -> str:
    """NFC, casefold, no diacritics, no punctuation, collapsed whitespace (comparison only)."""
    folded = unicodedata.normalize("NFC", text).casefold()
    decomposed = unicodedata.normalize("NFD", folded)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(_PUNCT_OR_SPACE.sub(" ", stripped).split())


@dataclass(frozen=True)
class BenchmarkSpec:
    """The two side codes of a benchmark's rows, plus the provenances that count as chant.

    ``target`` is the language under evaluation and ``contact`` the language on the other side
    of every pair; both are keys of a row's ``translation`` object, so they are data named by
    the caller. ``chant_provenances`` is the profile's set of ritual-chant sources.
    """

    target: str
    contact: str
    chant_provenances: frozenset[str] = frozenset()

    @property
    def codes(self) -> tuple[str, str]:
        return (self.target, self.contact)

    def directions(self) -> tuple[str, str]:
        """The two translation directions, named ``source->target``."""
        return (f"{self.contact}->{self.target}", f"{self.target}->{self.contact}")

    def other(self, code: str) -> str:
        """Return the opposite side code; an unknown code is an error, not a guess."""
        if code == self.target:
            return self.contact
        if code == self.contact:
            return self.target
        raise ValueError(f"unknown side {code!r}; expected one of {self.codes}")


@dataclass(frozen=True)
class EvalRow:
    id: str
    translation: Mapping[str, str]
    provenance: str
    group: str  # "bible" or "chant"
    component: str | None = None
    in_v0_train: bool = False

    def side(self, code: str) -> str:
        return self.translation[code]

    @property
    def unit(self) -> str:
        """Bootstrap resampling unit: component for chant rows that have one, else the row."""
        if self.group == "chant" and self.component:
            return f"component:{self.component}"
        return f"row:{self.id}"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def group_of(provenance: str, spec: BenchmarkSpec) -> str:
    return "chant" if provenance in spec.chant_provenances else "bible"


def v0_keys(v0_train: Sequence[dict[str, Any]], spec: BenchmarkSpec) -> dict[str, set[str]]:
    """Folded keys per side code of the earlier adapter's training rows."""
    return {code: {fold_key(r["translation"][code]) for r in v0_train} for code in spec.codes}


def build_rows(
    raw: Sequence[dict[str, Any]],
    spec: BenchmarkSpec,
    components: dict[str, str] | None = None,
    v0: dict[str, set[str]] | None = None,
) -> list[EvalRow]:
    """Turn raw hf.jsonl rows into EvalRows; ``v0`` flags overlap by folded key on either side."""
    components = components or {}
    out: list[EvalRow] = []
    for r in raw:
        translation = {str(code): str(text) for code, text in r["translation"].items()}
        flag = False
        if v0 is not None:
            flag = any(
                fold_key(translation[code]) in v0.get(code, set())
                for code in spec.codes
                if code in translation
            )
        prov = r["provenance"]
        out.append(
            EvalRow(
                id=r["id"],
                translation=translation,
                provenance=prov,
                group=group_of(prov, spec),
                component=r.get("component") or components.get(r["id"]),
                in_v0_train=flag,
            )
        )
    return out


def load_benchmark(
    datasets_dir: Path,
    spec: BenchmarkSpec,
    v0_train: Sequence[dict[str, Any]] | None = None,
) -> dict[str, list[EvalRow]]:
    """Load val, test, chant_val, chant_test; primary chant rows borrow the chant component."""
    chant: dict[str, list[dict[str, Any]]] = {
        s: read_jsonl(datasets_dir / "chant_benchmark" / f"{s}.hf.jsonl") for s in ("val", "test")
    }
    comp = {r["id"]: r["component"] for rows in chant.values() for r in rows}
    v0 = v0_keys(v0_train, spec) if v0_train is not None else None
    sets: dict[str, list[EvalRow]] = {}
    for s in ("val", "test"):
        sets[s] = build_rows(read_jsonl(datasets_dir / f"{s}.hf.jsonl"), spec, comp, v0)
        sets[f"chant_{s}"] = build_rows(chant[s], spec, comp, v0)
    return sets


# --------------------------------------------------------------------------- retrieval


def _ngrams(key: str, n: int = 3) -> Counter[str]:
    padded = f" {key} "
    if len(padded) < n:
        return Counter([padded])
    return Counter(padded[i : i + n] for i in range(len(padded) - n + 1))


class NearestRowRetriever:
    """Return the paired translation of the nearest train row, chosen on the INPUT side only.

    Selection: exact folded-key match first; otherwise cosine over char 3-gram TF-IDF vectors of the
    folded input side. The output side of a candidate row is never consulted. Ties go to the
    earliest train row.
    """

    def __init__(self, train: Sequence[EvalRow], spec: BenchmarkSpec, n: int = 3) -> None:
        self.train = list(train)
        self.spec = spec
        self.n = n
        self._index: dict[str, _SideIndex] = {
            code: _SideIndex([r.side(code) for r in self.train], n) for code in spec.codes
        }

    def nearest(self, text: str, src_lang: str) -> tuple[int, float, bool]:
        """Return (train row index, similarity, exact_key_match)."""
        return self._index[src_lang].nearest(text)

    def translate(self, text: str, src_lang: str) -> str:
        tgt_lang = self.spec.other(src_lang)
        idx, _, _ = self.nearest(text, src_lang)
        return self.train[idx].side(tgt_lang)


class _SideIndex:
    def __init__(self, texts: Sequence[str], n: int) -> None:
        self.n = n
        self.keys = [fold_key(t) for t in texts]
        self.exact: dict[str, int] = {}
        for i, k in enumerate(self.keys):
            self.exact.setdefault(k, i)
        self.vecs = [_ngrams(k, n) for k in self.keys]
        df: Counter[str] = Counter()
        for v in self.vecs:
            df.update(v.keys())
        n_docs = max(len(self.keys), 1)
        self.idf = {g: math.log((1 + n_docs) / (1 + c)) + 1.0 for g, c in df.items()}
        self.norms: list[float] = []
        self.postings: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for i, v in enumerate(self.vecs):
            weights = {g: (1 + math.log(c)) * self.idf[g] for g, c in v.items()}
            norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
            self.norms.append(norm)
            for g, w in weights.items():
                self.postings[g].append((i, w / norm))

    def nearest(self, text: str) -> tuple[int, float, bool]:
        key = fold_key(text)
        if key in self.exact:
            return self.exact[key], 1.0, True
        q = _ngrams(key, self.n)
        qw = {g: (1 + math.log(c)) * self.idf[g] for g, c in q.items() if g in self.idf}
        qnorm = math.sqrt(sum(w * w for w in qw.values())) or 1.0
        scores: dict[int, float] = defaultdict(float)
        for g, w in qw.items():
            for i, dw in self.postings[g]:
                scores[i] += (w / qnorm) * dw
        if not scores:
            return 0, 0.0, False
        best = max(scores.items(), key=lambda kv: (kv[1], -kv[0]))
        return best[0], best[1], False


def retrieval_predictions(
    retriever: NearestRowRetriever, rows: Sequence[EvalRow], direction: str
) -> list[str]:
    src = direction.split("->")[0]
    return [retriever.translate(r.side(src), src) for r in rows]


# --------------------------------------------------------------------------- metrics


class Scorer:
    """chrF++ (word_order=2) and spBLEU (flores200) from additive per-row statistics."""

    def __init__(self, spbleu_tokenize: str = "flores200") -> None:
        import importlib

        metrics: Any = importlib.import_module("sacrebleu.metrics")
        self.chrf: Any = metrics.CHRF(word_order=2)
        self.bleu: Any = metrics.BLEU(tokenize=spbleu_tokenize)

    def row_stats(
        self, hyps: Sequence[str], refs: Sequence[str]
    ) -> list[tuple[list[float], list[float]]]:
        c = self.chrf._extract_corpus_statistics(list(hyps), [list(refs)])
        b = self.bleu._extract_corpus_statistics(list(hyps), [list(refs)])
        return [(list(map(float, x)), list(map(float, y))) for x, y in zip(c, b, strict=True)]

    def chrf_score(self, stats: Sequence[float]) -> float:
        return float(self.chrf._compute_score_from_stats(list(stats)).score)

    def bleu_score(self, stats: Sequence[float]) -> float:
        return float(self.bleu._compute_score_from_stats(list(stats)).score)


def sum_stats(rows: Sequence[Sequence[float]]) -> list[float]:
    if not rows:
        return []
    return [sum(col) for col in zip(*rows, strict=True)]


def percentile(sorted_vals: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0, 1]."""
    if not sorted_vals:
        return float("nan")
    pos = q * (len(sorted_vals) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def bootstrap_ci(
    stats: Sequence[Sequence[float]],
    units: Sequence[str],
    score_fn: Callable[[Sequence[float]], float],
    n_boot: int = 1000,
    seed: int = 13,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile CI of a corpus score, resampling whole ``units`` with replacement.

    ``stats`` are additive per-row statistics. Rows sharing a unit move together, so a chant
    component is drawn or dropped as a block. Deterministic for a given seed.
    """
    if len(stats) != len(units):
        raise ValueError("stats and units must have the same length")
    if not stats:
        return (float("nan"), float("nan"))
    by_unit: dict[str, list[Sequence[float]]] = {}
    for s, u in zip(stats, units, strict=True):
        by_unit.setdefault(u, []).append(s)
    unit_sums = [sum_stats(v) for v in by_unit.values()]
    k = len(unit_sums)
    rng = random.Random(seed)
    scores: list[float] = []
    for _ in range(n_boot):
        tot = [0.0] * len(unit_sums[0])
        for _i in range(k):
            for j, v in enumerate(unit_sums[rng.randrange(k)]):
                tot[j] += v
        scores.append(score_fn(tot))
    scores.sort()
    return (percentile(scores, alpha / 2), percentile(scores, 1 - alpha / 2))


@dataclass
class SliceResult:
    name: str
    n: int
    n_units: int
    unit: str
    chrf: float
    chrf_ci: tuple[float, float]
    spbleu: float
    spbleu_ci: tuple[float, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "slice": self.name,
            "n": self.n,
            "n_units": self.n_units,
            "bootstrap_unit": self.unit,
            "chrf++": round(self.chrf, 2),
            "chrf++_ci95": [round(x, 2) for x in self.chrf_ci],
            "spbleu": round(self.spbleu, 2),
            "spbleu_ci95": [round(x, 2) for x in self.spbleu_ci],
        }


def score_slice(
    name: str,
    rows: Sequence[EvalRow],
    row_stats: Sequence[tuple[Sequence[float], Sequence[float]]],
    scorer: Scorer,
    n_boot: int = 1000,
    seed: int = 13,
) -> SliceResult | None:
    if not rows:
        return None
    chrf_rows = [s[0] for s in row_stats]
    bleu_rows = [s[1] for s in row_stats]
    units = [r.unit for r in rows]
    has_components = any(u.startswith("component:") for u in units)
    return SliceResult(
        name=name,
        n=len(rows),
        n_units=len(set(units)),
        unit="component" if has_components else "row",
        chrf=scorer.chrf_score(sum_stats(chrf_rows)),
        chrf_ci=bootstrap_ci(chrf_rows, units, scorer.chrf_score, n_boot, seed),
        spbleu=scorer.bleu_score(sum_stats(bleu_rows)),
        spbleu_ci=bootstrap_ci(bleu_rows, units, scorer.bleu_score, n_boot, seed),
    )


def slice_definitions(set_name: str, rows: Sequence[EvalRow]) -> dict[str, list[int]]:
    """Row index lists per slice: all, bible, chant, per source, v0-overlap true/false."""
    defs: dict[str, list[int]] = {"all": list(range(len(rows)))}
    for g in ("bible", "chant"):
        idx = [i for i, r in enumerate(rows) if r.group == g]
        if idx and len(idx) != len(rows):
            defs[g] = idx
    for prov in sorted({r.provenance for r in rows}):
        defs[f"source:{prov}"] = [i for i, r in enumerate(rows) if r.provenance == prov]
    if any(r.in_v0_train for r in rows):
        defs["v0_overlap:true"] = [i for i, r in enumerate(rows) if r.in_v0_train]
        defs["v0_overlap:false"] = [i for i, r in enumerate(rows) if not r.in_v0_train]
    return defs


def evaluate_system(
    rows_by_set: dict[str, Sequence[EvalRow]],
    preds: dict[str, dict[str, dict[str, str]]],
    scorer: Scorer,
    n_boot: int = 1000,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Score one system. ``preds[direction][set_name][row_id] = hypothesis``.

    Returns ``{direction: {set_name: [slice dict, ...]}}``. Missing predictions skip the set.
    """
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for direction, per_set in preds.items():
        tgt = direction.split("->")[1]
        out[direction] = {}
        for set_name, hyp_by_id in per_set.items():
            rows = rows_by_set[set_name]
            if any(r.id not in hyp_by_id for r in rows):
                continue
            stats = scorer.row_stats([hyp_by_id[r.id] for r in rows], [r.side(tgt) for r in rows])
            results = []
            for name, idx in slice_definitions(set_name, rows).items():
                res = score_slice(
                    name, [rows[i] for i in idx], [stats[i] for i in idx], scorer, n_boot
                )
                if res:
                    results.append(res.as_dict())
            out[direction][set_name] = results
    return out


def markdown_table(
    results: dict[str, Any], set_name: str, slices: Sequence[str] = ("all", "bible", "chant")
) -> str:
    """Compact table: one row per system x direction, chrF++ [CI] for selected slices of one set."""
    head = "| system | direction | " + " | ".join(slices) + " |"
    lines = [head, "|" + "---|" * (len(slices) + 2)]
    for system, by_dir in results["systems"].items():
        for direction, by_set in by_dir.items():
            sl = {s["slice"]: s for s in by_set.get(set_name, [])}
            cells = []
            for name in slices:
                s = sl.get(name)
                if not s:
                    cells.append("-")
                    continue
                lo, hi = s["chrf++_ci95"]
                cells.append(f"{s['chrf++']:.1f} [{lo:.1f}, {hi:.1f}] (n={s['n']})")
            lines.append(f"| {system} | {direction} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


@dataclass
class Predictions:
    """Predictions for one system: ``data[direction][set_name][row_id]``."""

    system: str
    data: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)

    def add(self, direction: str, set_name: str, ids: Sequence[str], hyps: Sequence[str]) -> None:
        self.data.setdefault(direction, {}).setdefault(set_name, {}).update(
            zip(ids, hyps, strict=True)
        )
