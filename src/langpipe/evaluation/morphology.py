"""Morphology benchmark metrics, gold representation, and scoring (M5-PLAN §6 WP5.11, ADR-0019).

Computes micro boundary P/R/F1, exact segmentation accuracy, affix/stem preservation,
over/under segmentation, coverage, abstention, distinct signatures, and oracle F1.
"""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from langpipe.domain.enums import Abstention, RunStatus
from langpipe.domain.errors import GoldAlignmentError, InvalidLineage, NotFound
from langpipe.domain.hashing import canonical_json, sha256_bytes
from langpipe.domain.models.igt import IGTObservation
from langpipe.domain.models.morphology import (
    MorphAnalysis,
    MorphGold,
    MorphGoldItem,
    MorphGoldSelector,
    MorphSegment,
)
from langpipe.storage.repository import Repository


@dataclass(frozen=True)
class MorphologyMethodMetrics:
    """Evaluation metrics for one morphology induction method on a gold set."""

    boundary_precision: float
    boundary_recall: float
    boundary_f1: float
    exact_accuracy: float
    known_affix_preservation: float
    stem_preservation: float
    over_segmentation_rate: float
    under_segmentation_rate: float
    coverage: float
    abstention_rate: float
    mean_distinct_signatures_per_token: float
    top1_boundary_f1: float
    oracle_boundary_f1: float
    downstream_chrf: str = "not_applicable"
    downstream_feature_error: str = "not_applicable"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _token_boundaries(segments: Sequence[Sequence[int]] | Sequence[MorphSegment]) -> set[int]:
    """Return non-initial segment start offsets (internal cut points)."""
    boundaries: set[int] = set()
    for seg in segments:
        start = seg.start if isinstance(seg, MorphSegment) else int(seg[0])
        if start > 0:
            boundaries.add(start)
    return boundaries


def _token_segments_list(
    segments: Sequence[Sequence[int]] | Sequence[MorphSegment],
) -> list[list[int]]:
    result: list[list[int]] = []
    for s in segments:
        if isinstance(s, MorphSegment):
            result.append([s.start, s.end])
        else:
            result.append([int(s[0]), int(s[1])])
    return result


def gold_from_igt(
    repo: Repository,
    igt_extract_run_id: str,
    refs: Sequence[str],
    language: str | None = None,
    *,
    strict: bool = False,
) -> MorphGold:
    """Build a deterministic MorphGold v1 object from held-out IGT records.

    If IGT morphemes cannot be located in the word, excludes the unresolved item
    (or raises GoldAlignmentError if strict=True) rather than inventing unsegmented answers.
    """
    igt_run = repo.get_run(igt_extract_run_id)
    if igt_run.status is not RunStatus.SUCCEEDED:
        raise InvalidLineage()

    observations = repo.list_igt_observations_for_run(igt_extract_run_id)
    matched_obs_by_ref: dict[str, list[IGTObservation]] = {}

    for ref_str in refs:
        if ref_str.startswith("ref:"):
            target_val = ref_str[4:]
            matched = [o for o in observations if o.record_ref == target_val]
        elif ref_str.startswith("ord:"):
            target_val = ref_str[4:]
            matched = [o for o in observations if str(o.record_ordinal) == target_val]
        elif ref_str.startswith("id:"):
            target_val = ref_str[3:]
            matched = [o for o in observations if o.id == target_val]
        else:
            ref_matches = [o for o in observations if o.record_ref == ref_str]
            ord_matches = [o for o in observations if str(o.record_ordinal) == ref_str]
            id_matches = [o for o in observations if o.id == ref_str]

            non_empty = [{o.id for o in m} for m in (ref_matches, ord_matches, id_matches) if m]
            if len(non_empty) > 1 and not all(s == non_empty[0] for s in non_empty[1:]):
                raise ValueError(
                    f"Ambiguous reference '{ref_str}' matches multiple record namespaces. "
                    f"Disambiguate with 'ref:{ref_str}' or 'ord:{ref_str}'."
                )
            matched = ref_matches or ord_matches or id_matches

        if matched:
            matched_obs_by_ref[ref_str] = matched

    missing_refs = set(refs) - set(matched_obs_by_ref.keys())
    if missing_refs:
        raise NotFound("igt_observation", f"missing_refs={sorted(missing_refs)}")

    unique_obs: dict[str, IGTObservation] = {}
    for obs_list in matched_obs_by_ref.values():
        for o in obs_list:
            unique_obs[o.id] = o
    matched_obs = sorted(unique_obs.values(), key=lambda o: o.record_ordinal)

    items: list[MorphGoldItem] = []
    unresolved: list[dict[str, Any]] = []
    target_lang = language or igt_run.config.get("language", "und")
    boundary_marks = ("-", "=", "~")

    for obs in matched_obs:
        source = repo.get_source(obs.source_id)
        source_key = source.key

        for igt_word in obs.words:
            w_text = igt_word.text
            segments: list[list[int]] = []
            affix_spans: list[list[int]] = []
            root_span: list[int] | None = None

            curr = 0
            loc_ok = True
            for morph in igt_word.morphs:
                while curr < len(w_text) and w_text[curr] in boundary_marks:
                    curr += 1
                m_len = len(morph.text)
                if curr + m_len <= len(w_text) and w_text[curr : curr + m_len] == morph.text:
                    span = [curr, curr + m_len]
                    segments.append(span)
                    if morph.boundary_before or (morph.gloss and morph.gloss.isupper()):
                        affix_spans.append(span)
                    else:
                        if root_span is None:
                            root_span = span
                        else:
                            affix_spans.append(span)
                    curr += m_len
                else:
                    loc_ok = False
                    break

            if igt_word.morphs:
                if not loc_ok or curr != len(w_text) or not segments:
                    # Alignment failure: morphemes were annotated but could not be aligned
                    unresolved.append(
                        {
                            "observation_id": obs.id,
                            "record_ref": obs.record_ref or str(obs.record_ordinal),
                            "word_ordinal": igt_word.ordinal,
                            "surface": w_text,
                            "morphs": [m.text for m in igt_word.morphs],
                        }
                    )
                    if strict:
                        ref_label = obs.record_ref or str(obs.record_ordinal)
                        morph_list = [m.text for m in igt_word.morphs]
                        raise GoldAlignmentError(
                            f"IGT morphemes {morph_list} could not be aligned "
                            f"to word surface '{w_text}' in ref '{ref_label}'"
                        )
                    continue
            else:
                # Genuinely unsegmented word in IGT
                segments = [[0, len(w_text)]]
                affix_spans = []
                root_span = [0, len(w_text)]

            item = MorphGoldItem(
                selector=MorphGoldSelector(
                    source_key=source_key,
                    observation_id=obs.id,
                    segment_id=obs.segment_id,
                    igt_ref=obs.record_ref or f"ord:{obs.record_ordinal}",
                    record_ref=obs.record_ref,
                    record_ordinal=obs.record_ordinal,
                    word_ordinal=igt_word.ordinal,
                ),
                surface=w_text,
                segments=segments,
                affix_spans=affix_spans,
                root_span=root_span,
            )
            items.append(item)

    if not items:
        raise ValueError(f"Derived gold set from IGT run {igt_extract_run_id} has no valid items")

    provenance = {
        "igt_extract_run_id": igt_extract_run_id,
        "refs": sorted(refs),
        "unresolved": unresolved,
        "unresolved_count": len(unresolved),
    }
    gold_digest = sha256_bytes(
        canonical_json(
            {
                "language": target_lang,
                "items": [it.model_dump() for it in items],
                "provenance": provenance,
            }
        ).encode("utf-8")
    )
    gold_id = f"gold-morph-{gold_digest[:16]}"

    return MorphGold(
        gold_id=gold_id,
        language=target_lang,
        items=items,
        provenance=provenance,
    )


def evaluate_morphology(
    gold_items: Sequence[MorphGoldItem | Mapping[str, Any]],
    analyses_by_token: Mapping[str, Sequence[MorphAnalysis]],
    segments_by_analysis: Mapping[str, Sequence[MorphSegment]],
    token_id_map: Mapping[int, str],
    token_surfaces: Mapping[str, str],
    token_abstentions: Mapping[str, Abstention] | None = None,
) -> MorphologyMethodMetrics:
    """Compute benchmark metrics for candidate analyses against gold items."""
    if not gold_items:
        return MorphologyMethodMetrics(
            boundary_precision=0.0,
            boundary_recall=0.0,
            boundary_f1=0.0,
            exact_accuracy=0.0,
            known_affix_preservation=0.0,
            stem_preservation=0.0,
            over_segmentation_rate=0.0,
            under_segmentation_rate=0.0,
            coverage=0.0,
            abstention_rate=1.0,
            mean_distinct_signatures_per_token=0.0,
            top1_boundary_f1=0.0,
            oracle_boundary_f1=0.0,
        )

    abstentions = token_abstentions or {}
    total_tokens = len(gold_items)

    tp_top1 = 0
    fp_top1 = 0
    fn_top1 = 0

    tp_oracle = 0
    fp_oracle = 0
    fn_oracle = 0

    exact_matches = 0
    total_gold_affixes = 0
    preserved_gold_affixes = 0
    total_gold_stems = 0
    preserved_gold_stems = 0

    covered_tokens = 0
    abstained_tokens = 0
    total_signatures = 0

    for idx, item in enumerate(gold_items):
        gold_segs = item["segments"]
        gold_boundaries = _token_boundaries(gold_segs)
        gold_affixes = item.get("affix_spans", [])
        gold_root = item.get("root_span")

        total_gold_affixes += len(gold_affixes)
        if gold_root is not None:
            total_gold_stems += 1

        token_id = token_id_map.get(idx)
        cand_analyses = analyses_by_token.get(token_id, ()) if token_id else ()
        tok_surf = token_surfaces.get(token_id) if token_id else None
        item_surf = item.get("surface")
        surface = tok_surf if tok_surf is not None else (item_surf if item_surf is not None else "")
        span_len = len(surface) if surface else (int(gold_segs[-1][1]) if gold_segs else 0)

        distinct_sigs = {a.signature for a in cand_analyses}
        total_signatures += len(distinct_sigs)

        has_real_analysis = any(a.abstention is None for a in cand_analyses)
        is_abstained = (
            (token_id in abstentions)
            or (len(cand_analyses) == 0)
            or any(a.abstention is not None for a in cand_analyses)
        )
        if is_abstained:
            abstained_tokens += 1
        if has_real_analysis:
            covered_tokens += 1

        # Missing analysis counts as unsegmented prediction (empty boundaries, whole span)
        if not cand_analyses:
            top1_segs: list[list[int]] = [[0, span_len]]
            top1_boundaries: set[int] = set()
            oracle_boundaries: set[int] = set()
        else:
            # Deterministic Top-1 selection:
            # highest morph-v1 overall, ties broken by method name then signature (ascending)
            sorted_analyses = sorted(
                cand_analyses,
                key=lambda a: (
                    -(a.score_breakdown.overall if a.score_breakdown is not None else 0.0),
                    a.method,
                    a.signature,
                ),
            )
            top1_ana = sorted_analyses[0]
            top1_segs_rows = segments_by_analysis.get(top1_ana.id, ())
            top1_segs = _token_segments_list(top1_segs_rows)
            top1_boundaries = _token_boundaries(top1_segs_rows)

            # Oracle selection: candidate maximizing boundary match with gold
            best_oracle_b: set[int] = top1_boundaries
            best_oracle_f1: float = -1.0
            for a in cand_analyses:
                a_segs = segments_by_analysis.get(a.id, ())
                a_b = _token_boundaries(a_segs)
                b_tp = len(a_b & gold_boundaries)
                b_fp = len(a_b - gold_boundaries)
                b_fn = len(gold_boundaries - a_b)
                p = (
                    b_tp / (b_tp + b_fp)
                    if (b_tp + b_fp) > 0
                    else (1.0 if not gold_boundaries else 0.0)
                )
                r = b_tp / (b_tp + b_fn) if (b_tp + b_fn) > 0 else (1.0 if not a_b else 0.0)
                f = (2 * p * r) / (p + r) if (p + r) > 0 else 0.0
                if f > best_oracle_f1:
                    best_oracle_f1 = f
                    best_oracle_b = a_b
            oracle_boundaries = best_oracle_b

        # Boundary counts (micro)
        b_tp = len(top1_boundaries & gold_boundaries)
        b_fp = len(top1_boundaries - gold_boundaries)
        b_fn = len(gold_boundaries - top1_boundaries)

        tp_top1 += b_tp
        fp_top1 += b_fp
        fn_top1 += b_fn

        tp_oracle += len(oracle_boundaries & gold_boundaries)
        fp_oracle += len(oracle_boundaries - gold_boundaries)
        fn_oracle += len(gold_boundaries - oracle_boundaries)

        # Exact segmentation match
        if _token_segments_list(top1_segs) == _token_segments_list(gold_segs):
            exact_matches += 1

        # Affix preservation
        for aff in gold_affixes:
            if [int(aff[0]), int(aff[1])] in top1_segs:
                preserved_gold_affixes += 1

        # Stem preservation
        if gold_root is not None and [int(gold_root[0]), int(gold_root[1])] in top1_segs:
            preserved_gold_stems += 1

    # Aggregate boundary P/R/F1 for top-1
    prec = (
        tp_top1 / (tp_top1 + fp_top1) if tp_top1 + fp_top1 > 0 else (1.0 if fn_top1 == 0 else 0.0)
    )
    rec = tp_top1 / (tp_top1 + fn_top1) if tp_top1 + fn_top1 > 0 else (1.0 if fp_top1 == 0 else 0.0)

    f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0

    # Oracle boundary F1
    if tp_oracle + fp_oracle > 0:
        prec_o = tp_oracle / (tp_oracle + fp_oracle)
    else:
        prec_o = 1.0 if fn_oracle == 0 else 0.0

    if tp_oracle + fn_oracle > 0:
        rec_o = tp_oracle / (tp_oracle + fn_oracle)
    else:
        rec_o = 1.0 if fp_oracle == 0 else 0.0

    f1_oracle = (2 * prec_o * rec_o) / (prec_o + rec_o) if (prec_o + rec_o) > 0 else 0.0

    over_seg = fp_top1 / (tp_top1 + fp_top1) if (tp_top1 + fp_top1) > 0 else 0.0
    under_seg = fn_top1 / (tp_top1 + fn_top1) if (tp_top1 + fn_top1) > 0 else 0.0

    exact_acc = exact_matches / total_tokens if total_tokens > 0 else 0.0
    affix_pres = preserved_gold_affixes / total_gold_affixes if total_gold_affixes > 0 else 1.0
    stem_pres = preserved_gold_stems / total_gold_stems if total_gold_stems > 0 else 1.0
    coverage = covered_tokens / total_tokens if total_tokens > 0 else 0.0
    abstention_rate = abstained_tokens / total_tokens if total_tokens > 0 else 0.0
    mean_sigs = total_signatures / total_tokens if total_tokens > 0 else 0.0

    return MorphologyMethodMetrics(
        boundary_precision=round(prec, 4),
        boundary_recall=round(rec, 4),
        boundary_f1=round(f1, 4),
        exact_accuracy=round(exact_acc, 4),
        known_affix_preservation=round(affix_pres, 4),
        stem_preservation=round(stem_pres, 4),
        over_segmentation_rate=round(over_seg, 4),
        under_segmentation_rate=round(under_seg, 4),
        coverage=round(coverage, 4),
        abstention_rate=round(abstention_rate, 4),
        mean_distinct_signatures_per_token=round(mean_sigs, 4),
        top1_boundary_f1=round(f1, 4),
        oracle_boundary_f1=round(f1_oracle, 4),
        downstream_chrf="not_applicable",
        downstream_feature_error="not_applicable",
    )
