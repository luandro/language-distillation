"""NMT and LoRA instruction-tuning dataset exporter (Milestone 2, WP 2.4).

Partitions validated synthetic and attested parallel data for immediate model fine-tuning:
- train.jsonl (verified synthetic phrases + attested parallel verses + harvested pairs)
- val.jsonl (attested + harvested validation partition)
- test.jsonl (STRICTLY human-attested gold verses; zero synthetic data allowed)

Governance (ADR-0025):
- a source present in the repository is trainable; license, ownership, and register are
  recorded metadata and never filter a row here;
- Invariant 2: test benchmarks require human ground truth;
- every record carries a trace id (``provenance`` plus, when known, ``source_id``,
  ``policy_id``, ``run_id``) so it can be traced back into the repository;
- the writer raises if a pool's written row count differs from its length: no silent drops,
  and a missing expected production input fails loudly instead of exporting a tiny "success".
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import unicodedata
from collections import Counter
from collections.abc import Collection
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from langpipe.languages.base import profile_for
from langpipe.lexicon.citations import load_parallel_verses_from_dirs
from langpipe.synthesis.derived_rows import load_derived_rows
from langpipe.training.quality.length_ratio import length_ratio_ok

SYNTHETIC_PROVENANCE = "synthetic:curriculum"
SCRIPTURE_REGISTER = "scripture"
UNSPECIFIED_REGISTER = "unspecified"
DEFAULT_MAX_REGISTER_SHARE = 0.20
CHANT_REGISTER = "ritual_chant"
# Benchmark revisions. Scores are comparable only within one version (see docs/EVALUATION.md).
#   1: legacy held-out text as selected (datasets_legacy/v1).
#   2: held-out Bible rows repaired (space before punctuation) or excluded (edition notes).
BENCHMARK_VERSIONS = (1, 2)
BENCHMARK_VERSION = 2
BENCHMARK_AUDIT_FILE = "benchmark_v2_audit.json"
CHANT_BENCHMARK_DIR = "chant_benchmark"
DERIVED_AUDIT_FILE = "derived_rows_audit.json"
CHANT_TEST_TARGET = 100
CHANT_VAL_TARGET = 40
CHANT_VAL_MIN = 25
CHANT_MAX_TRAIN_LOSS_SHARE = 0.25


_PUNCT_OR_SPACE = re.compile(r"[^\w]+", re.UNICODE)
_EDITION_SIGLA = re.compile(r"(?<!\w)(?:TR|RP|N4)(?!\w)")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+(?=[,.;:!?])")


def comparison_key(text: str) -> str:
    """Leak-check key: NFC, casefold, no punctuation/quotes, collapsed space, no diacritics.

    Used ONLY to compare rows across splits; stored text is never rewritten from it.
    """
    folded = unicodedata.normalize("NFC", text).casefold()
    decomposed = unicodedata.normalize("NFD", folded)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(_PUNCT_OR_SPACE.sub(" ", stripped).split())


def _row_texts(row: dict[str, Any]) -> tuple[str, str]:
    target = (
        row.get("target") or row.get("target_text") or row.get("target_phrase") or row.get("src")
    )
    contact = (
        row.get("portuguese")
        or row.get("reference_text")
        or row.get("portuguese_translation")
        or row.get("tgt")
    )
    return str(target or ""), str(contact or "")


def has_edition_note(text: str) -> bool:
    """True when a Bible Portuguese verse carries a textual-apparatus note (TR, RP, N4 sigla)."""
    return _EDITION_SIGLA.search(text) is not None


def repair_space_before_punctuation(text: str) -> str:
    """Remove spaces before ``, . ; : ! ?``; nothing else is changed."""
    return _SPACE_BEFORE_PUNCT.sub("", text)


def clean_bible_train_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Clean scripture (``corpus:``) rows only; any other row passes through untouched.

    Drops verses whose Portuguese carries edition notes, repairs whitespace before
    punctuation in the Portuguese, and drops rows failing the word-count ratio guard.
    """
    stats = {"edition_notes": 0, "space_before_punctuation": 0, "length_ratio": 0}
    kept: list[dict[str, Any]] = []
    for row in rows:
        if not str(row.get("provenance") or "").startswith("corpus:"):
            kept.append(row)
            continue
        target, contact = _row_texts(row)
        if has_edition_note(contact):
            stats["edition_notes"] += 1
            continue
        repaired = repair_space_before_punctuation(contact)
        if not length_ratio_ok(target, repaired):
            stats["length_ratio"] += 1
            continue
        if repaired != contact:
            stats["space_before_punctuation"] += 1
            row = {**row, "reference_text": repaired}
        kept.append(row)
    return kept, stats


def drop_train_rows_overlapping_eval(
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    test: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Drop every train row whose group touches a val or test row.

    Rows are grouped (union-find) when they share a target-language key or a contact-language
    key across all sources. Val/test rows are never altered or removed here.
    """
    everything = [(row, "train") for row in train] + [(row, "eval") for row in (*val, *test)]
    parent = list(range(len(everything)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first_seen: dict[tuple[str, str], int] = {}
    for index, (row, _) in enumerate(everything):
        for side, text in zip(("src", "tgt"), _row_texts(row), strict=True):
            key = comparison_key(text)
            if not key:
                continue
            owner = first_seen.setdefault((side, key), index)
            if owner != index:
                parent[find(index)] = find(owner)
    eval_roots = {find(i) for i, (_, split) in enumerate(everything) if split == "eval"}
    kept = [
        row
        for i, (row, split) in enumerate(everything)
        if split == "train" and find(i) not in eval_roots
    ]
    return kept, len(train) - len(kept)


def drop_val_rows_overlapping_test(
    val: list[dict[str, Any]], test: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Drop val rows sharing a target or contact key with a test row (test is untouched)."""
    test_keys = {
        (side, key)
        for row in test
        for side, text in zip(("src", "tgt"), _row_texts(row), strict=True)
        if (key := comparison_key(text))
    }
    kept = [
        row
        for row in val
        if not any(
            (side, comparison_key(text)) in test_keys
            for side, text in zip(("src", "tgt"), _row_texts(row), strict=True)
        )
    ]
    return kept, len(val) - len(kept)


def apply_benchmark_v2(
    rows: list[dict[str, Any]], split: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Held-out Bible revision: repair whitespace before punctuation, exclude edition notes.

    Only scripture (``corpus:``) rows are touched. A row whose Portuguese carries a TR/RP/N4
    apparatus note leaves the benchmark (it is not refilled and not returned to train); any
    other row with whitespace before ``, . ; : ! ?`` keeps its slot with that whitespace
    removed from the Portuguese. Returns ``(kept, repaired, excluded)``; the audit entries
    carry the original text so every change is reviewable and restorable by a later version.
    Input rows are never mutated.
    """
    kept: list[dict[str, Any]] = []
    repaired: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for row in rows:
        provenance = str(row.get("provenance") or "")
        if not provenance.startswith("corpus:"):
            kept.append(row)
            continue
        target, contact = _row_texts(row)
        entry = {
            "split": split,
            "source_ref": str(row.get("source_ref") or ""),
            "provenance": provenance,
            "target": target,
        }
        if has_edition_note(contact):
            excluded.append({**entry, "reason": "edition_note", "portuguese": contact})
            continue
        fixed = repair_space_before_punctuation(contact)
        if fixed != contact:
            repaired.append(
                {**entry, "reason": "space_before_punctuation", "before": contact, "after": fixed}
            )
            row = {**row, "reference_text": fixed}
        kept.append(row)
    return kept, repaired, excluded


def _group_roots(rows: list[dict[str, Any]]) -> list[int]:
    """Union-find root per row; rows sharing a target or contact key share a root."""
    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first_seen: dict[tuple[str, str], int] = {}
    for index, row in enumerate(rows):
        for side, text in zip(("src", "tgt"), _row_texts(row), strict=True):
            key = comparison_key(text)
            if not key:
                continue
            owner = first_seen.setdefault((side, key), index)
            if owner != index:
                parent[find(index)] = find(owner)
    return [find(i) for i in range(len(rows))]


def _row_ident(row: dict[str, Any]) -> str:
    return f"{row.get('provenance') or ''}|{row.get('source_ref') or row.get('ref') or ''}"


def _component_ids(rows: list[dict[str, Any]]) -> dict[int, str]:
    """Stable component id per row (``id(row)`` -> ``c`` + hash of the sorted member idents)."""
    roots = _group_roots(rows)
    members: dict[int, list[int]] = {}
    for index, root in enumerate(roots):
        members.setdefault(root, []).append(index)
    out: dict[int, str] = {}
    for indexes in members.values():
        idents = sorted(_row_ident(rows[i]) for i in indexes)
        digest = hashlib.sha256("\0".join(idents).encode()).hexdigest()[:10]
        for i in indexes:
            out[id(rows[i])] = f"c{digest}"
    return out


def _word_count(row: dict[str, Any]) -> int:
    return len(_row_texts(row)[0].split())


def select_chant_components(
    pool: list[dict[str, Any]],
    target: int,
    seed: int,
    already: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], dict[int, str]]:
    """Choose whole key-linked components from ``pool`` totalling at most ``target`` rows.

    Components (rows linked by a shared folded target or contact key) are never split.
    Selection is stratified by source (provenance) and target word-length tercile: at every
    step the least-represented source (counting ``already``, per provenance) and then its
    least-represented length bucket gives its next component in seeded hash order that still
    fits. Returns ``(chosen rows, {id(row): component id})``.
    """
    comp_of = _component_ids(pool)
    lengths = sorted(_word_count(row) for row in pool)
    edges = (lengths[len(lengths) // 3], lengths[(2 * len(lengths)) // 3]) if lengths else (0, 0)

    def bucket(mean_words: float) -> int:
        return 0 if mean_words <= edges[0] else 1 if mean_words <= edges[1] else 2

    by_comp: dict[str, list[dict[str, Any]]] = {}
    for row in pool:
        by_comp.setdefault(comp_of[id(row)], []).append(row)
    cells: dict[tuple[str, int], list[tuple[str, list[dict[str, Any]]]]] = {}
    for cid, members in by_comp.items():
        source = sorted(str(m.get("provenance") or "") for m in members)[0]
        mean = sum(_word_count(m) for m in members) / len(members)
        cells.setdefault((source, bucket(mean)), []).append((cid, members))
    for cell in cells.values():
        cell.sort(key=lambda item: hashlib.sha256(f"{seed}\0{item[0]}".encode()).hexdigest())

    per_source: dict[str, int] = dict(already or {})
    per_cell: dict[tuple[str, int], int] = {}
    chosen: list[dict[str, Any]] = []
    remaining = target
    while remaining > 0:
        sources = sorted(
            {src for (src, _), items in cells.items() if items},
            key=lambda src: (per_source.get(src, 0), src),
        )
        picked = False
        for src in sources:
            buckets = sorted(
                (b for (s2, b), items in cells.items() if s2 == src and items),
                key=lambda b: (per_cell.get((src, b), 0), b),
            )
            for b in buckets:
                items = cells[(src, b)]
                index = next((i for i, item in enumerate(items) if len(item[1]) <= remaining), None)
                if index is None:
                    items.clear()  # remaining only shrinks: nothing here can fit again
                    continue
                _, members = items.pop(index)
                chosen.extend(members)
                per_source[src] = per_source.get(src, 0) + len(members)
                per_cell[(src, b)] = per_cell.get((src, b), 0) + len(members)
                remaining -= len(members)
                picked = True
                break
            if picked:
                break
        if not picked:
            break
    return chosen, {id(row): comp_of[id(row)] for row in chosen}


def register_of(row: dict[str, Any], chant_provenances: Collection[str] = ()) -> str:
    """Return a row's register label; an absent label stays ``unspecified`` (Invariant 7).

    ``chant_provenances`` are the provenances whose rows are ritual chant, read from the
    language profile (``LanguageProfile.chant_provenances``): a record without an explicit
    label inherits the chant register from them. Generic code carries no such provenance.
    """
    declared = str(row.get("register") or "").strip()
    provenance = str(row.get("provenance") or "")
    if provenance in chant_provenances and declared in ("", UNSPECIFIED_REGISTER):
        return CHANT_REGISTER
    if declared:
        return declared
    if provenance.startswith("corpus:"):
        return SCRIPTURE_REGISTER
    if provenance.startswith("synthetic:"):
        return "synthetic"
    return UNSPECIFIED_REGISTER


def load_harvested_parallel_sentences(
    harvested_dir: Path | str = "exports/harvested_parallel",
    lang_code: str = "",
) -> list[dict[str, Any]]:
    """Load harvested authentic parallel sentences from open science / indigenous repositories.

    A malformed line or a record with an empty side raises ``ValueError`` (with the file and
    line) instead of truncating the file silently, because this loader supplies the gold test
    benchmark. When ``lang_code`` is set, records that declare a different language are
    skipped; records that declare no language are accepted (older files predate the field).
    A record's optional ``register`` label is carried through; an absent label loads as
    ``unspecified``, so files without the field keep loading unchanged.
    """
    h_dir = Path(harvested_dir)
    if not h_dir.exists():
        return []

    results: list[dict[str, Any]] = []
    for file_path in sorted(h_dir.glob("*_parallel.jsonl")):
        for line_no, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{file_path}:{line_no}: malformed JSON") from exc
            if not isinstance(rec, dict):
                raise ValueError(f"{file_path}:{line_no}: record is not an object")
            declared = rec.get("lang") or rec.get("language")
            if lang_code and declared and declared != lang_code:
                continue
            src = unicodedata.normalize("NFC", str(rec.get("src") or "").strip())
            tgt = unicodedata.normalize("NFC", str(rec.get("tgt") or "").strip())
            if not (src and tgt):
                raise ValueError(f"{file_path}:{line_no}: empty source or target side")
            results.append(
                {
                    "source_ref": rec.get("ref", ""),
                    "target_text": src,
                    "reference_text": tgt,
                    "provenance": f"harvested:{file_path.stem}",
                    "is_attested": True,
                    "english": str(rec.get("eng") or "").strip(),
                    "register": str(rec.get("register") or "").strip() or UNSPECIFIED_REGISTER,
                }
            )
    return results


def select_derived_train_rows(
    derived: list[dict[str, Any]],
    line_rows: list[dict[str, Any]],
    pinned_eval: list[dict[str, Any]],
    other_rows: list[dict[str, Any]] | None = None,
    aliases: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep the derived rows whose key component touches no pinned eval row (ADR-0026).

    ``line_rows`` are ALL harvested line rows, including those a dedup step later dropped, so
    components are built before any dedup removes a row. A component links rows that share a
    folded target key or a folded contact key (comparison only), plus a derived->member edge
    for every ``member_refs`` entry (resolved by ``provenance|ref``; ``aliases`` maps the ident
    of a deduplicated member to the ident of the row that was kept). ``pinned_eval`` is every
    val, test and chant-benchmark row: a derived row whose component contains one is excluded,
    and nothing is ever moved into train from eval. Exact duplicate derived pairs keep the
    first. Returns ``(kept, excluded)``; each excluded entry carries ``reason``.
    """
    aliases = aliases or {}
    by_ident = {_row_ident(row): row for row in line_rows}
    universe: list[dict[str, Any]] = []
    index_of: dict[int, int] = {}
    for row in [*line_rows, *pinned_eval, *(other_rows or []), *derived]:
        if id(row) not in index_of:
            index_of[id(row)] = len(universe)
            universe.append(row)
    parent = list(range(len(universe)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    first_seen: dict[tuple[str, str], int] = {}
    for index, row in enumerate(universe):
        for side, text in zip(("src", "tgt"), _row_texts(row), strict=True):
            key = comparison_key(text)
            if key:
                union(index, first_seen.setdefault((side, key), index))
    member_rows: dict[int, list[dict[str, Any]]] = {}
    for row in derived:
        resolved = []
        for member in row["derived"]["member_refs"]:
            ident = f"{member['provenance']}|{member['ref']}"
            target = by_ident.get(aliases.get(ident, ident))
            if target is None:
                raise ValueError(f"derived row {row['source_ref']!r}: unknown member {ident!r}")
            resolved.append(target)
            union(index_of[id(row)], index_of[id(target)])
        member_rows[id(row)] = resolved
    eval_roots = {find(index_of[id(row)]) for row in pinned_eval}
    eval_ids = {id(row) for row in pinned_eval}
    kept: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for row in sorted(derived, key=lambda item: str(item["source_ref"])):
        reason = None
        if any(id(m) in eval_ids for m in member_rows[id(row)]):
            reason = "member_in_eval"
        elif find(index_of[id(row)]) in eval_roots:
            reason = "key_component_touches_eval"
        else:
            pair = (_row_texts(row)[0], _row_texts(row)[1])
            if pair in seen_pairs:
                reason = "duplicate_derived_pair"
            seen_pairs.add(pair)
        if reason:
            excluded.append({"id": row["source_ref"], "reason": reason})
        else:
            kept.append(row)
    return kept, excluded


@dataclass
class _ChantBenchmark:
    """Result of the chant benchmark selection (rows are the exporter's own row objects)."""

    test_rows: list[dict[str, Any]]
    val_rows: list[dict[str, Any]]
    train_pool: list[dict[str, Any]]
    extra_test_rows: list[dict[str, Any]]
    component_of: dict[int, str]
    status: str
    reused_test: int
    train_before: int
    train_rows_removed: int
    per_source: dict[str, dict[str, int]]
    word_stats: dict[str, dict[str, int]]
    notes: list[str]


def _count_by_split(entries: list[dict[str, Any]]) -> dict[str, int]:
    return {split: sum(1 for e in entries if e["split"] == split) for split in ("val", "test")}


def _build_chant_benchmark(
    train_pool: list[dict[str, Any]],
    val_pool: list[dict[str, Any]],
    test_pool: list[dict[str, Any]],
    seed: int,
    chant_provenances: Collection[str] = (),
    test_target: int = CHANT_TEST_TARGET,
    val_target: int = CHANT_VAL_TARGET,
    val_min: int = CHANT_VAL_MIN,
    max_train_loss_share: float = CHANT_MAX_TRAIN_LOSS_SHARE,
) -> _ChantBenchmark:
    """Build the separate chant benchmark (exempt from the register cap).

    Test = every chant row already in primary test (reused) plus whole key-linked components
    moved out of train, up to ``test_target`` rows. Val = whole components among the chant
    rows already in primary val, at most ``val_target``. Only components made entirely of
    chant rows of one split are eligible, so leakage rules are never weakened: a component
    sharing a key with a non-chant row stays where it is. The loss of chant train rows is
    capped at ``max_train_loss_share``; if the targets cannot be met the benchmark is marked
    ``provisional`` instead.
    """
    tagged = [(row, "train") for row in train_pool]
    tagged += [(row, "val") for row in val_pool] + [(row, "test") for row in test_pool]
    universe = [row for row, _ in tagged]
    roots = _group_roots(universe)
    members: dict[int, list[int]] = {}
    for index, root in enumerate(roots):
        members.setdefault(root, []).append(index)

    def eligible(split: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for indexes in members.values():
            if all(
                tagged[i][1] == split
                and register_of(tagged[i][0], chant_provenances) == CHANT_REGISTER
                for i in indexes
            ):
                rows.extend(tagged[i][0] for i in indexes)
        return rows

    chant_train = [
        row for row in train_pool if register_of(row, chant_provenances) == CHANT_REGISTER
    ]
    base_test = [row for row in test_pool if register_of(row, chant_provenances) == CHANT_REGISTER]
    notes: list[str] = []
    budget = int(max_train_loss_share * len(chant_train))
    wanted = max(0, test_target - len(base_test))
    already: dict[str, int] = {}
    for row in base_test:
        prov = str(row.get("provenance") or "")
        already[prov] = already.get(prov, 0) + 1
    extra, _ = select_chant_components(
        eligible("train"), min(wanted, budget), seed, already=already
    )
    if wanted > budget:
        notes.append(
            f"train-loss budget ({max_train_loss_share:.0%} of {len(chant_train)} chant train "
            f"rows = {budget}) limits additions; {wanted} wanted"
        )
    val_rows, _ = select_chant_components(eligible("val"), val_target, seed)
    test_rows = [*base_test, *extra]
    if len(test_rows) < test_target:
        notes.append(f"test has {len(test_rows)} of {test_target} target rows")
    if len(val_rows) < val_min:
        notes.append(f"val has {len(val_rows)} of the minimum {val_min} rows")
    status = "frozen" if not notes else "provisional"

    component_of = _component_ids([*test_rows, *val_rows])
    extra_ids = {id(row) for row in extra}
    new_train = [row for row in train_pool if id(row) not in extra_ids]

    def per_source(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = Counter(str(row.get("provenance") or "") for row in rows)
        return dict(sorted(counts.items()))

    def words(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = sorted(_word_count(row) for row in rows)
        if not counts:
            return {"min": 0, "median": 0, "max": 0}
        return {"min": counts[0], "median": counts[len(counts) // 2], "max": counts[-1]}

    return _ChantBenchmark(
        test_rows=test_rows,
        val_rows=val_rows,
        train_pool=new_train,
        extra_test_rows=extra,
        component_of=component_of,
        status=status,
        reused_test=len(base_test),
        train_before=len(chant_train),
        train_rows_removed=len(extra),
        per_source={"test": per_source(test_rows), "val": per_source(val_rows)},
        word_stats={"test": words(test_rows), "val": words(val_rows)},
        notes=notes,
    )


def _assert_no_leakage(
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    test: list[dict[str, Any]],
    chant: _ChantBenchmark,
) -> None:
    """Raise unless no target or contact key is shared across any two benchmark sets."""

    def keys(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
        return {
            (side, key)
            for row in rows
            for side, text in zip(("src", "tgt"), _row_texts(row), strict=True)
            if (key := comparison_key(text))
        }

    sets = {
        "train": keys(train),
        "val": keys(val),
        "test": keys(test),
        "chant_val": keys(chant.val_rows),
        "chant_test_extra": keys(chant.extra_test_rows),
    }
    pairs = [("train", "val"), ("train", "test"), ("val", "test")]
    pairs += [("train", "chant_val"), ("train", "chant_test_extra")]
    pairs += [
        ("chant_test_extra", "val"),
        ("chant_test_extra", "test"),
        ("chant_test_extra", "chant_val"),
    ]
    pairs += [("chant_val", "test")]
    for a, b in pairs:
        shared = sets[a] & sets[b]
        if shared:
            raise RuntimeError(f"key leakage between {a} and {b}: {len(shared)} shared key(s)")


@dataclass
class DatasetExportSummary:
    """Summary of exported training, validation, and test splits."""

    target_language: str
    contact_language: str
    train_count: int
    val_count: int
    test_count: int
    synthetic_train_count: int
    attested_train_count: int
    corpus_train_count: int = 0
    harvested_test_count: int = 0
    harvested_val_count: int = 0
    harvested_train_count: int = 0
    rows_without_source_ids: int = 0
    test_purity_verified: bool = True
    val_purity_verified: bool = True
    output_dir: str = ""
    sha256_checksums: dict[str, str] = field(default_factory=dict)
    source_ids: list[str] = field(default_factory=list)
    policy_ids: list[str] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)
    source_index_path: str | None = None
    source_index_sha256: str | None = None
    max_register_share: float | None = None
    register_cap_limits: dict[str, int | None] = field(default_factory=dict)
    register_overflow_to_train: dict[str, dict[str, int]] = field(default_factory=dict)
    register_histogram: dict[str, dict[str, int]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    benchmark_version: int = 1
    benchmark_audit_file: str | None = None
    benchmark_audit_sha256: str | None = None
    benchmark_repaired: dict[str, int] = field(default_factory=dict)
    benchmark_excluded: dict[str, int] = field(default_factory=dict)
    chant_benchmark: dict[str, Any] = field(default_factory=dict)
    derived_train_count: int = 0
    derived_built_count: int = 0
    derived_excluded: dict[str, int] = field(default_factory=dict)
    derived_by_unit_kind: dict[str, int] = field(default_factory=dict)
    derived_audit_file: str | None = None
    derived_audit_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_source_index(path: Path | str) -> dict[str, dict[str, str]]:
    """Load a provenance -> {source_id, policy_id, run_id} index, or {} when absent."""
    index_path = Path(path)
    if not index_path.exists():
        return {}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"source index {index_path} is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError(f"source index {index_path} must be an object")
    index: dict[str, dict[str, str]] = {}
    for provenance, ids in data.items():
        if not isinstance(ids, dict):
            raise ValueError(f"source index {index_path}: entry {provenance!r} must be an object")
        index[str(provenance)] = {
            str(key): str(value) for key, value in ids.items() if value is not None
        }
    return index


class DatasetExporter:
    """Exports and partitions fine-tuning datasets for NMT and LoRA."""

    def __init__(
        self,
        lang_code: str = "und",
        contact_lang: str = "por",
        output_dir: Path | str | None = None,
        source_index: dict[str, dict[str, str]] | None = None,
        source_index_path: Path | str | None = None,
        chant_provenances: Collection[str] | None = None,
    ) -> None:
        self.lang_code = lang_code
        self.contact_lang = contact_lang
        # Provenances whose rows count as ritual chant, from the language profile unless the
        # caller supplies an explicit set (ADR-0026). Generic code hardcodes none.
        self.chant_provenances: Collection[str] = (
            chant_provenances
            if chant_provenances is not None
            else profile_for(lang_code).chant_provenances
        )
        self.output_dir = (
            Path(output_dir) if output_dir else Path("exports") / lang_code / "datasets"
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # ADR-0025: ids are traceability metadata, not an authorization check. Callers that
        # have a registered source set pass the index explicitly (see `synth export`).
        self.source_index = source_index if source_index is not None else {}
        self.source_index_path = Path(source_index_path) if source_index_path else None
        self.source_index_sha256 = (
            hashlib.sha256(self.source_index_path.read_bytes()).hexdigest()
            if self.source_index_path is not None and self.source_index_path.exists()
            else None
        )

    def _ids_for(self, provenance: str) -> dict[str, str]:
        """Return the trace ids for a provenance string (exact match, then longest prefix).

        A non-separator key only matches on a separator boundary, so ``corpus:GEN`` never
        captures ``corpus:GENESIS``.
        """

        def matches(key: str) -> bool:
            if provenance == key:
                return True
            if key.endswith((":", "/", "_", ".", "-")):
                return provenance.startswith(key)
            return provenance.startswith(key + ":")

        if provenance in self.source_index:
            return dict(self.source_index[provenance])
        candidates = [key for key in self.source_index if matches(key)]
        if not candidates:
            return {}
        return dict(self.source_index[max(candidates, key=len)])

    def _load_corpus_verses(self) -> list[dict[str, Any]]:
        target_dir = Path("var") / f"scriptureearth_{self.lang_code}"
        ref_dir = Path("var") / "external" / f"parallel_{self.contact_lang}"
        if not (target_dir.exists() and ref_dir.exists()):
            target_dir = Path("data/raw/scriptureearth") / self.lang_code / "raw"
            ref_dir = Path("data/raw/ebible") / self.contact_lang / "raw"
        if not (target_dir.exists() and ref_dir.exists()):
            return []
        corpus_verses = load_parallel_verses_from_dirs(target_dir=target_dir, reference_dir=ref_dir)
        return [
            {
                "source_ref": v.source_ref,
                "target_text": unicodedata.normalize("NFC", v.target_text),
                "reference_text": unicodedata.normalize("NFC", v.reference_text),
                "provenance": f"corpus:{v.book}",
                "is_attested": True,
                "register": SCRIPTURE_REGISTER,
            }
            for v in corpus_verses
        ]

    def export(
        self,
        synthetic_phrases: list[dict[str, Any]],
        attested_verses: list[dict[str, Any]] | None = None,
        harvested_sentences: list[dict[str, Any]] | None = None,
        train_ratio: float = 0.80,
        val_ratio: float = 0.10,
        seed: int = 42,
        max_register_share: float | None = DEFAULT_MAX_REGISTER_SHARE,
        benchmark_version: int = BENCHMARK_VERSION,
        derived_rows: list[dict[str, Any]] | None = None,
    ) -> DatasetExportSummary:
        """Create partitioned train/val/test splits obeying governance invariants.

        ``max_register_share`` caps each harvested register in test and val (see step 6);
        ``None`` or ``1.0`` disables the cap. ``benchmark_version`` 2 (default) repairs or
        excludes defective held-out Bible rows and builds the separate chant benchmark;
        1 reproduces the legacy selection.
        """
        if benchmark_version not in BENCHMARK_VERSIONS:
            raise ValueError(f"benchmark_version must be one of {BENCHMARK_VERSIONS}")
        if max_register_share is not None and not 0.0 < max_register_share <= 1.0:
            raise ValueError("max_register_share must be in (0, 1] or None")
        rng = random.Random(seed)
        warnings: list[str] = []

        # 1. Collect human-attested gold parallel sentences if not provided.
        load_production_inputs = attested_verses is None
        if attested_verses is None:
            attested_verses = self._load_corpus_verses()
            if not attested_verses:
                raise RuntimeError(
                    "production export found no attested corpus verses under var/ or data/raw; "
                    "refusing to export a silently tiny dataset"
                )

        # 2. Collect harvested authentic parallel sentences (e.g. Cesarino et al. 2017).
        if harvested_sentences is None:
            harvested_sentences = (
                load_harvested_parallel_sentences(
                    harvested_dir=Path("exports") / "harvested_parallel",
                    lang_code=self.lang_code,
                )
                if load_production_inputs
                else []
            )
        if load_production_inputs and not harvested_sentences:
            warnings.append("no harvested parallel sentences found")

        # 2b. Derived full-phrase rows (ADR-0026): train-only, never split or benchmarked.
        if derived_rows is None:
            derived_rows = (
                load_derived_rows(Path("exports") / "harvested_parallel", self.lang_code)
                if load_production_inputs
                else []
            )

        # 3. Filter ONLY passed, unquarantined synthetic phrases. A real provenance is
        # required: the exporter never invents an "unknown" trace id.
        clean_synth = [
            {
                **phrase,
                "provenance": phrase.get("provenance") or SYNTHETIC_PROVENANCE,
            }
            for phrase in synthetic_phrases
            if phrase.get("valid") and not phrase.get("quarantined")
        ]

        # 4. Partition harvested sentences deterministically, per source file. The gold
        # benchmark is selected independently for each harvested source by a content hash, so
        # neither reordering a file nor adding another file can silently swap an existing
        # source's test rows, and the selection is not clustered by lexical ref order. Duplicate
        # (target, contact) pairs within a source are dropped before splitting, so a refrain
        # cannot appear in both train and test from the same file.
        def harvested_hash(provenance: str, row: dict[str, Any]) -> str:
            ref = str(row.get("source_ref") or row.get("ref") or "")
            return hashlib.sha256(f"{provenance}\0{ref}".encode()).hexdigest()

        by_provenance: dict[str, list[dict[str, Any]]] = {}
        for row in harvested_sentences:
            provenance = str(row.get("provenance") or "harvested:unknown")
            by_provenance.setdefault(provenance, []).append(row)

        h_test: list[dict[str, Any]] = []
        h_val: list[dict[str, Any]] = []
        h_train: list[dict[str, Any]] = []
        duplicate_rows = 0
        dedup_aliases: dict[str, str] = {}
        for provenance in sorted(by_provenance):
            unique: list[dict[str, Any]] = []
            seen_pairs: set[tuple[str, str]] = set()
            kept_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
            for row in sorted(
                by_provenance[provenance], key=lambda item: harvested_hash(provenance, item)
            ):
                pair = (
                    str(row.get("target_text") or row.get("src") or "").strip(),
                    str(row.get("reference_text") or row.get("tgt") or "").strip(),
                )
                if pair in seen_pairs:
                    duplicate_rows += 1
                    dedup_aliases[_row_ident(row)] = _row_ident(kept_by_pair[pair])
                    continue
                seen_pairs.add(pair)
                kept_by_pair[pair] = row
                unique.append(row)
            group = unique
            total_h = len(group)
            if total_h >= 75:
                # 50 to test, 25 to val, rest to train
                h_test.extend(group[:50])
                h_val.extend(group[50:75])
                h_train.extend(group[75:])
            else:
                n_h_test = max(1, int(total_h * 0.40))
                n_h_val = max(1, int(total_h * 0.25))
                h_test.extend(group[:n_h_test])
                h_val.extend(group[n_h_test : n_h_test + n_h_val])
                h_train.extend(group[n_h_test + n_h_val :])
        if duplicate_rows:
            warnings.append(f"dropped {duplicate_rows} duplicate harvested row(s)")

        # 5. Partition attested verses (ScriptureEarth)
        shuffled_attested = list(attested_verses)
        rng.shuffle(shuffled_attested)

        # Allocate 100-200 gold verses strictly for test
        test_size = (
            min(200, max(20, int(len(shuffled_attested) * 0.10))) if shuffled_attested else 0
        )
        gold_test_verses = shuffled_attested[:test_size]
        remaining_attested = shuffled_attested[test_size:]

        n_att_val = int(len(remaining_attested) * val_ratio)
        att_val = remaining_attested[:n_att_val]
        att_train = remaining_attested[n_att_val:]

        # 5b. Bible cleanup applies to TRAIN scripture rows only; gold val/test text is never
        # altered. Chant rows are exempt (a 1-word line translating a phrase is genuine poetry).
        att_train, bible_stats = clean_bible_train_rows(att_train)
        for key, label in (
            ("edition_notes", "with Portuguese edition notes (TR/RP/N4)"),
            ("space_before_punctuation", "for space before punctuation"),
            ("length_ratio", "failing the word-length ratio guard"),
        ):
            if bible_stats[key]:
                verb = "repaired" if key == "space_before_punctuation" else "dropped"
                warnings.append(f"{verb} {bible_stats[key]} train Bible row(s) {label}")

        # 6. Register cap. In test and val, each harvested register may hold at most
        # floor(share / (1 - share) * S) rows, where S is the split's scripture block; with
        # S fixed, that register is at most `share` of the split. The limit depends only on
        # S, so adding a file of another register never moves an existing row. Within a
        # register the slots are shared evenly across its source files (water-filling, so a
        # small file's unused slots go to the others), and each file keeps its lowest content
        # hashes (the same hash as step 4). Adding a file to the same register can therefore
        # only shrink an existing file's rows to a subset, never swap them. Overflow rows move
        # to TRAIN, never dropped. With no scripture block the cap cannot be anchored, so it
        # is skipped with a warning rather than emptying the benchmark.
        cap_limits: dict[str, int | None] = {}
        overflow_counts: dict[str, dict[str, int]] = {}
        overflow_rows: list[dict[str, Any]] = []

        def apply_register_cap(
            split: str, rows: list[dict[str, Any]], anchor: int
        ) -> list[dict[str, Any]]:
            if max_register_share is None or max_register_share >= 1.0 or not rows:
                cap_limits[split] = None
                return rows
            if anchor == 0:
                cap_limits[split] = None
                warnings.append(f"register cap not applied to {split}: no scripture rows")
                return rows
            # The epsilon keeps an exact bound (0.2 of 200 -> 50) from flooring to 49.
            limit = int(max_register_share * anchor / (1.0 - max_register_share) + 1e-9)
            cap_limits[split] = limit
            by_register: dict[str, dict[str, list[dict[str, Any]]]] = {}
            for row in rows:
                provenance = str(row.get("provenance") or "harvested:unknown")
                by_register.setdefault(register_of(row, self.chant_provenances), {}).setdefault(
                    provenance, []
                ).append(row)
            kept_ids: set[int] = set()
            for register in sorted(by_register):
                files = by_register[register]
                remaining = limit
                order = sorted(files, key=lambda prov: (len(files[prov]), prov))
                for position, provenance in enumerate(order):
                    quota = min(len(files[provenance]), remaining // (len(order) - position))
                    remaining -= quota
                    ranked = sorted(
                        files[provenance],
                        key=lambda item: harvested_hash(provenance, item),  # noqa: B023
                    )
                    kept_ids.update(id(row) for row in ranked[:quota])
                overflow = sum(len(group) for group in files.values()) - (limit - remaining)
                if overflow:
                    overflow_counts.setdefault(split, {})[register] = overflow
            kept = [row for row in rows if id(row) in kept_ids]
            overflow_rows.extend(row for row in rows if id(row) not in kept_ids)
            return kept

        h_test = apply_register_cap("test", h_test, len(gold_test_verses))
        h_val = apply_register_cap("val", h_val, len(att_val))
        h_train.extend(overflow_rows)
        for split, counts in overflow_counts.items():
            for register, count in sorted(counts.items()):
                warnings.append(
                    f"register cap moved {count} {register} row(s) from {split} to train"
                )

        # 7. Compose Final Pools:
        # Strict Invariant 2 Check: test and val pools MUST be 100% human-attested gold
        # truth (zero synthetic).
        test_pool = h_test + gold_test_verses
        val_pool = h_val + att_val
        # A val row repeating a test row (same target or contact key) leaves val; test and
        # the remaining val text are kept exactly as selected.
        val_pool, val_removed = drop_val_rows_overlapping_test(val_pool, test_pool)
        if val_removed:
            warnings.append(f"removed {val_removed} val row(s) overlapping test")
        # All clean synthetic phrases join the training pool to maximize coverage, minus any
        # row whose group (shared target or contact key) touches val or test.
        train_pool = h_train + att_train + clean_synth
        train_pool, train_removed = drop_train_rows_overlapping_eval(
            train_pool, val_pool, test_pool
        )
        if train_removed:
            warnings.append(f"removed {train_removed} train row(s) overlapping val/test")

        # 7b. Benchmark v2. Held-out Bible rows with edition notes leave val/test (no refill,
        # not returned to train); whitespace before punctuation is repaired in place. Key
        # sets are unchanged (the key ignores punctuation), so the dedup above still holds.
        audit_repaired: list[dict[str, Any]] = []
        audit_excluded: list[dict[str, Any]] = []
        chant_result: _ChantBenchmark | None = None
        if benchmark_version >= 2:
            val_pool, rep_val, exc_val = apply_benchmark_v2(val_pool, "val")
            test_pool, rep_test, exc_test = apply_benchmark_v2(test_pool, "test")
            audit_repaired = [*rep_val, *rep_test]
            audit_excluded = [*exc_val, *exc_test]
            if audit_excluded:
                warnings.append(
                    f"benchmark v2 excluded {len(exc_val)} val / {len(exc_test)} test Bible "
                    "row(s) with Portuguese edition notes"
                )
            if audit_repaired:
                warnings.append(
                    f"benchmark v2 repaired {len(rep_val)} val / {len(rep_test)} test Bible "
                    "row(s) for space before punctuation"
                )
            chant_result = _build_chant_benchmark(
                train_pool,
                val_pool,
                test_pool,
                seed,
                chant_provenances=self.chant_provenances,
            )
            train_pool = chant_result.train_pool
            warnings.append(
                f"chant benchmark ({chant_result.status}): moved {chant_result.train_rows_removed} "
                "chant row(s) out of train"
            )
        # 7c. Derived rows join TRAIN last, after every split and the chant benchmark are
        # pinned: they can only be excluded, never move a row between splits.
        derived_kept: list[dict[str, Any]] = []
        derived_excluded: list[dict[str, Any]] = []
        if derived_rows:
            pinned = [*val_pool, *test_pool]
            if chant_result is not None:
                pinned += [*chant_result.val_rows, *chant_result.test_rows]
            derived_kept, derived_excluded = select_derived_train_rows(
                derived_rows, harvested_sentences, pinned, train_pool, dedup_aliases
            )
            train_pool = [*train_pool, *derived_kept]
            warnings.append(
                f"derived rows: {len(derived_kept)} of {len(derived_rows)} kept in train "
                f"({len(derived_excluded)} excluded)"
            )
        rng.shuffle(train_pool)
        # Keep the manifest's harvested counts equal to what was actually written.
        val_ids = {id(row) for row in val_pool}
        h_val = [row for row in h_val if id(row) in val_ids]
        train_ids = {id(row) for row in train_pool}
        h_train = [row for row in h_train if id(row) in train_ids]

        test_purity_verified = all(v.get("is_attested") is True for v in test_pool)
        val_purity_verified = all(v.get("is_attested") is True for v in val_pool)

        # 8. Write splits to temporary files, check every count, then publish atomically. A
        # failed export must not destroy the previous good dataset or its manifest.
        file_paths = [
            self.output_dir / "train.hf.jsonl",
            self.output_dir / "val.hf.jsonl",
            self.output_dir / "test.hf.jsonl",
            self.output_dir / "train.alpaca.jsonl",
            self.output_dir / "val.alpaca.jsonl",
            self.output_dir / "test.alpaca.jsonl",
            self.output_dir / "train.chatml.jsonl",
            self.output_dir / "val.chatml.jsonl",
            self.output_dir / "test.chatml.jsonl",
        ]
        nonce = f".{os.getpid()}.{len(file_paths)}x{random.randrange(1 << 30):x}"
        tmp_paths = [path.with_name(path.name + nonce + ".tmp") for path in file_paths]
        writers = (
            self._write_hf_nmt,
            self._write_hf_nmt,
            self._write_hf_nmt,
            self._write_alpaca,
            self._write_alpaca,
            self._write_alpaca,
            self._write_chatml,
            self._write_chatml,
            self._write_chatml,
        )
        pools = (train_pool, val_pool, test_pool) * 3
        try:
            written = {
                final.name: writer(tmp, pool)
                for final, tmp, writer, pool in zip(
                    file_paths, tmp_paths, writers, pools, strict=True
                )
            }
            for final, _tmp in zip(file_paths, tmp_paths, strict=True):
                if written[final.name] != len(pools[file_paths.index(final)]):
                    raise RuntimeError(
                        f"{final.name}: wrote {written[final.name]} rows but its pool has "
                        f"{len(pools[file_paths.index(final)])}; a record was dropped at write time"
                    )
        except BaseException:
            for tmp in tmp_paths:
                tmp.unlink(missing_ok=True)
            raise
        for final, tmp in zip(file_paths, tmp_paths, strict=True):
            os.replace(tmp, final)
        audit_sha: str | None = None
        chant_summary: dict[str, Any] = {}
        if benchmark_version >= 2 and chant_result is not None:
            _assert_no_leakage(train_pool, val_pool, test_pool, chant_result)
            audit_sha = self._write_json(
                self.output_dir / BENCHMARK_AUDIT_FILE,
                {
                    "benchmark_version": benchmark_version,
                    "policy": (
                        "Held-out Bible rows with Portuguese edition notes (TR/RP/N4) are "
                        "excluded and not refilled; whitespace before punctuation is repaired "
                        "in the Portuguese. Excluded rows stay out of train and are restorable "
                        "only by a verified correction in another benchmark version."
                    ),
                    "counts": {
                        "repaired": _count_by_split(audit_repaired),
                        "excluded": _count_by_split(audit_excluded),
                    },
                    "repaired": audit_repaired,
                    "excluded": audit_excluded,
                },
            )
            chant_summary = self._write_chant_benchmark(chant_result, seed)

        derived_audit_sha: str | None = None
        if derived_rows:
            derived_audit_sha = self._write_json(
                self.output_dir / DERIVED_AUDIT_FILE,
                {
                    "policy": (
                        "Derived rows are train-only. A derived row is excluded when its key "
                        "component (shared folded target or contact key, plus derived->member "
                        "edges) touches val, test or the chant benchmark. Eval rows are never "
                        "moved."
                    ),
                    "built": len(derived_rows),
                    "kept": [
                        {
                            "id": row["source_ref"],
                            "unit_kind": row["derived"]["unit_kind"],
                            "member_refs": row["derived"]["member_refs"],
                        }
                        for row in derived_kept
                    ],
                    "excluded": derived_excluded,
                    "member_aliases": dict(sorted(dedup_aliases.items())),
                },
            )

        # 9. Compute cryptographic SHA-256 hashes for all exported files
        checksums: dict[str, str] = {}
        for fp in file_paths:
            content = fp.read_bytes()
            checksums[fp.name] = hashlib.sha256(content).hexdigest()

        source_ids: set[str] = set()
        policy_ids: set[str] = set()
        run_ids: set[str] = set()
        rows_without_source_ids = 0
        for item in (*train_pool, *val_pool, *test_pool):
            ids = self._ids_for(str(item.get("provenance") or ""))
            if not ids.get("source_id") and not ids.get("policy_id"):
                rows_without_source_ids += 1
            for key, target in (
                ("source_id", source_ids),
                ("policy_id", policy_ids),
                ("run_id", run_ids),
            ):
                if ids.get(key):
                    target.add(ids[key])

        summary = DatasetExportSummary(
            target_language=self.lang_code,
            contact_language=self.contact_lang,
            train_count=len(train_pool),
            val_count=len(val_pool),
            test_count=len(test_pool),
            synthetic_train_count=len(clean_synth),
            attested_train_count=len(att_train),
            corpus_train_count=len(att_train),
            harvested_test_count=len(h_test),
            harvested_val_count=len(h_val),
            harvested_train_count=len(h_train),
            rows_without_source_ids=rows_without_source_ids,
            test_purity_verified=test_purity_verified,
            val_purity_verified=val_purity_verified,
            output_dir=str(self.output_dir),
            sha256_checksums=checksums,
            source_ids=sorted(source_ids),
            policy_ids=sorted(policy_ids),
            run_ids=sorted(run_ids),
            source_index_path=str(self.source_index_path) if self.source_index_path else None,
            source_index_sha256=self.source_index_sha256,
            max_register_share=max_register_share,
            register_cap_limits=cap_limits,
            register_overflow_to_train=overflow_counts,
            register_histogram={
                split: dict(
                    sorted(
                        Counter(register_of(row, self.chant_provenances) for row in pool).items()
                    )
                )
                for split, pool in (("train", train_pool), ("val", val_pool), ("test", test_pool))
            },
            warnings=warnings,
            benchmark_version=benchmark_version,
            benchmark_audit_file=BENCHMARK_AUDIT_FILE if audit_sha else None,
            benchmark_audit_sha256=audit_sha,
            benchmark_repaired=_count_by_split(audit_repaired),
            benchmark_excluded=_count_by_split(audit_excluded),
            chant_benchmark=chant_summary,
            derived_train_count=len(derived_kept),
            derived_built_count=len(derived_rows or []),
            derived_excluded=dict(sorted(Counter(e["reason"] for e in derived_excluded).items())),
            derived_by_unit_kind=dict(
                sorted(Counter(r["derived"]["unit_kind"] for r in derived_kept).items())
            ),
            derived_audit_file=DERIVED_AUDIT_FILE if derived_audit_sha else None,
            derived_audit_sha256=derived_audit_sha,
        )

        # Write dataset manifest atomically: a crash must not leave new splits under an old
        # manifest. The files are swapped one by one, so a crash can still mix runs; the
        # manifest replace is the last step and the tmp name is unique per process.
        manifest_path = self.output_dir / "manifest.json"
        manifest_tmp = manifest_path.with_name(manifest_path.name + nonce + ".tmp")
        try:
            manifest_tmp.write_text(
                json.dumps(summary.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(manifest_tmp, manifest_path)
        except BaseException:
            manifest_tmp.unlink(missing_ok=True)
            raise

        return summary

    def _write_json(self, path: Path, payload: dict[str, Any]) -> str:
        """Write ``payload`` atomically (stable key order); return the file's sha256."""
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _write_chant_benchmark(self, chant: _ChantBenchmark, seed: int) -> dict[str, Any]:
        """Write the separate chant benchmark (hf format + manifest); return its summary."""
        out_dir = self.output_dir / CHANT_BENCHMARK_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        checksums: dict[str, str] = {}
        for split, rows in (("val", chant.val_rows), ("test", chant.test_rows)):
            path = out_dir / f"{split}.hf.jsonl"
            tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                for row in sorted(rows, key=_row_ident):
                    tgt, cont, ref_id = self._extract_pair(row)
                    record = {
                        "id": ref_id,
                        "translation": {self.lang_code: tgt, self.contact_lang: cont},
                        "register": CHANT_REGISTER,
                        "component": chant.component_of[id(row)],
                        **self._trace(row),
                    }
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            os.replace(tmp, path)
            checksums[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {
            "chant_benchmark_version": 1,
            "primary_benchmark_version": BENCHMARK_VERSION,
            "status": chant.status,
            "register": CHANT_REGISTER,
            "register_cap_exempt": True,
            "seed": seed,
            "targets": {
                "test": CHANT_TEST_TARGET,
                "val_max": CHANT_VAL_TARGET,
                "val_min": CHANT_VAL_MIN,
            },
            "test_count": len(chant.test_rows),
            "val_count": len(chant.val_rows),
            "components": {
                "test": len({chant.component_of[id(r)] for r in chant.test_rows}),
                "val": len({chant.component_of[id(r)] for r in chant.val_rows}),
            },
            "reused_from_primary": {
                "test": chant.reused_test,
                "val": len(chant.val_rows),
            },
            "per_source": chant.per_source,
            "words_per_row": chant.word_stats,
            "train_rows_removed": chant.train_rows_removed,
            "chant_train_rows_before": chant.train_before,
            "chant_train_rows_after": chant.train_before - chant.train_rows_removed,
            "excluded_from_train": True,
            "bootstrap_unit": "component",
            "notes": chant.notes,
            "sha256_checksums": checksums,
        }
        manifest_sha = self._write_json(out_dir / "manifest.json", manifest)
        return {
            "dir": CHANT_BENCHMARK_DIR,
            "manifest_sha256": manifest_sha,
            "status": chant.status,
            "test_count": manifest["test_count"],
            "val_count": manifest["val_count"],
            "components": manifest["components"],
            "train_rows_removed": chant.train_rows_removed,
        }

    def _extract_pair(self, item: dict[str, Any]) -> tuple[str, str, str]:
        """Extract (target_text, contact_text, ref_id) from synthetic, harvested, or attested.

        Synthetic records use ``target_phrase``/``portuguese_translation``; attested and
        harvested records use their own keys. An empty side raises instead of being dropped.
        """
        target = (
            item.get("target")
            or item.get("target_text")
            or item.get("target_phrase")
            or item.get("src")
            or ""
        )
        contact = (
            item.get("portuguese")
            or item.get("reference_text")
            or item.get("portuguese_translation")
            or item.get("tgt")
            or ""
        )
        target_clean = unicodedata.normalize("NFC", str(target).strip())
        contact_clean = unicodedata.normalize("NFC", str(contact).strip())
        ref_hash = hashlib.md5(f"{target_clean}:{contact_clean}".encode()).hexdigest()[:12]
        ref_id = item.get("source_ref") or item.get("ref") or ref_hash
        if not (target_clean and contact_clean):
            raise ValueError(
                f"row {ref_id!r} has an empty target or contact side; refusing to drop it silently"
            )
        return target_clean, contact_clean, ref_id

    @staticmethod
    def _derived_meta(item: dict[str, Any]) -> dict[str, Any]:
        """Train-only metadata of a derived row (ADR-0026); empty for every other row."""
        derived = item.get("derived")
        if not item.get("is_derived") or not isinstance(derived, dict):
            return {}
        return {
            "derived": {
                **derived,
                "register": item.get("register"),
            }
        }

    def _trace(self, item: dict[str, Any]) -> dict[str, str]:
        """Trace fields written on every record (ADR-0025): provenance plus known ids.

        Provenance is required; the exporter never writes an ``unknown`` placeholder because
        the training gate treats a present provenance as a trace id.
        """
        provenance = item.get("provenance")
        if not isinstance(provenance, str) or not provenance.strip():
            raise ValueError("row has no provenance; refusing to write an untraceable record")
        record = {"provenance": provenance}
        ids = self._ids_for(provenance)
        for key in ("source_id", "policy_id", "run_id"):
            if ids.get(key):
                record[key] = ids[key]
        return record

    def _write_hf_nmt(self, path: Path, items: list[dict[str, Any]]) -> int:
        """Write in HuggingFace standard NMT jsonl format. Returns rows written."""
        written = 0
        with open(path, "w", encoding="utf-8") as f:
            for item in items:
                tgt, cont, ref_id = self._extract_pair(item)
                record = {
                    "id": ref_id,
                    "translation": {
                        self.lang_code: tgt,
                        self.contact_lang: cont,
                    },
                    **self._trace(item),
                    **self._derived_meta(item),
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
        return written

    def _write_alpaca(self, path: Path, items: list[dict[str, Any]]) -> int:
        """Write in Alpaca instruction tuning jsonl format. Returns rows written."""
        inst_text = (
            f"Traduza a seguinte frase para a língua indígena {self.lang_code} "
            "obedecendo estritamente às regras de concordância gramatical."
        )
        written = 0
        with open(path, "w", encoding="utf-8") as f:
            for item in items:
                tgt, cont, ref_id = self._extract_pair(item)
                record = {
                    "id": ref_id,
                    "instruction": inst_text,
                    "input": cont,
                    "output": tgt,
                    **self._trace(item),
                    **self._derived_meta(item),
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
        return written

    def _write_chatml(self, path: Path, items: list[dict[str, Any]]) -> int:
        """Write in standard ChatML multi-turn conversational format. Returns rows written."""
        sys_msg = f"Você é um tradutor especialista e rigoroso para a língua {self.lang_code}."
        written = 0
        with open(path, "w", encoding="utf-8") as f:
            for item in items:
                tgt, cont, ref_id = self._extract_pair(item)
                record = {
                    "id": ref_id,
                    "messages": [
                        {"role": "system", "content": sys_msg},
                        {"role": "user", "content": cont},
                        {"role": "assistant", "content": tgt},
                    ],
                    **self._trace(item),
                    **self._derived_meta(item),
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
        return written
