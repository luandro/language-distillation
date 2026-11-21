"""Morphology evidence scoring policy (WP5.8: M5-PLAN §7.8, ADR-0017 §7, ADR-0019).

Pure domain logic: no storage, no network, no source text. The policy turns observed
evidence, structural segment properties and morpheme links into a versioned `ScoreBreakdown`
with `policy_version="morph-v1"` and decides automated promotion to `supported`.

Invariant 3: Machine confidence NEVER promotes a hypothesis to `validated`.
This module returns `LifecycleStatus.CANDIDATE` or `LifecycleStatus.SUPPORTED`, never
`LifecycleStatus.VALIDATED`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from langpipe.domain.enums import EvidenceKind, EvidencePolarity, LifecycleStatus
from langpipe.domain.errors import InvalidTransition
from langpipe.domain.models.evidence import EvidenceItem
from langpipe.domain.models.morphology import (
    Morpheme,
    MorphSegment,
    ScoreBreakdown,
)

POLICY_VERSION: Final = "morph-v1"

# Raw score components in breakdown order (M5-PLAN §7.8).
IGT_SUPPORT: Final = "igt_support"
IGT_INDEPENDENCE: Final = "igt_independence"
FORM_DIVERSITY: Final = "form_diversity"
PROJECTION_SUPPORT: Final = "projection_support"
BOUNDARY_MARK_SUPPORT: Final = "boundary_mark_support"
CROSS_METHOD_AGREEMENT: Final = "cross_method_agreement"

COMPONENTS: Final = (
    IGT_SUPPORT,
    IGT_INDEPENDENCE,
    FORM_DIVERSITY,
    PROJECTION_SUPPORT,
    BOUNDARY_MARK_SUPPORT,
    CROSS_METHOD_AGREEMENT,
)

# Raw penalty components in breakdown order (M5-PLAN §7.8).
CONTRADICTION: Final = "contradiction"
UNKNOWN_SEGMENT: Final = "unknown_segment"
AMBIGUITY: Final = "ambiguity"

PENALTIES: Final = (
    CONTRADICTION,
    UNKNOWN_SEGMENT,
    AMBIGUITY,
)


@dataclass(frozen=True)
class MorphScoringPolicy:
    """Versioned parameters for morph-v1 scoring and promotion."""

    policy_version: str = POLICY_VERSION
    min_igt_support: int = 2
    min_igt_independence: int = 2
    min_form_diversity: int = 2
    method_allowlist: tuple[str, ...] = ()  # ADR-0019 empty in M5


DEFAULT_POLICY: Final = MorphScoringPolicy()


def _independence_axis(item: EvidenceItem) -> str | None:
    if item.independence_group:
        return item.independence_group
    return item.source_id or None


def _clean_count(val: float | int | None) -> float:
    if val is None or isinstance(val, bool) or not math.isfinite(val):
        return 0.0
    return max(0.0, float(val))


def score_morpheme(
    *,
    evidence_items: Sequence[EvidenceItem] = (),
    igt_support: int | None = None,
    igt_independence: int | None = None,
    form_diversity: int | None = None,
    projection_support: int = 0,
    boundary_mark_support: int = 0,
    cross_method_agreement: int = 0,
    contradiction: int | None = None,
    independence_groups: Sequence[str] = (),
    current_status: LifecycleStatus = LifecycleStatus.CANDIDATE,
    policy: MorphScoringPolicy | None = None,
) -> tuple[LifecycleStatus, ScoreBreakdown]:
    """Score a morpheme under `morph-v1` policy (§7.8).

    Promotion to `supported`:
      `igt_support >= 2` and (`igt_independence >= 2` or `form_diversity >= 2`)
      and no contradiction.
    Everything else stays `candidate`. `validated` is unreachable.
    """
    if current_status is LifecycleStatus.VALIDATED:
        raise InvalidTransition()

    pol = policy or DEFAULT_POLICY
    axes: set[str] = set(independence_groups)

    # Derive counts from evidence items if not provided explicitly
    if evidence_items:
        supporting = [i for i in evidence_items if i.polarity is EvidencePolarity.SUPPORTS]
        contradicting = [i for i in evidence_items if i.polarity is EvidencePolarity.CONTRADICTS]

        for item in evidence_items:
            axis = _independence_axis(item)
            if axis:
                axes.add(axis)

        if contradiction is None:
            contradiction = len(contradicting)

        if igt_support is None:
            # Count distinct IGT records
            igt_records: set[str] = set()
            for item in supporting:
                if item.kind is EvidenceKind.IGT_ASSERTION:
                    claim = item.claim or {}
                    obs_id = claim.get("igt_observation_id")
                    if obs_id:
                        igt_records.add(str(obs_id))
                    elif item.source_id:
                        igt_records.add(str(item.source_id))
            igt_support = len(igt_records)

        if igt_independence is None:
            igt_axes = {
                axis for axis in (_independence_axis(i) for i in supporting) if axis is not None
            }
            igt_independence = len(igt_axes)

        if form_diversity is None:
            forms = {
                str((item.claim or {}).get("word_form"))
                for item in supporting
                if (item.claim or {}).get("word_form")
            }
            form_diversity = len(forms)

    c_igt_sup = _clean_count(igt_support)
    c_igt_ind = _clean_count(igt_independence)
    c_form_div = _clean_count(form_diversity)
    c_proj_sup = _clean_count(projection_support)
    c_bound_sup = _clean_count(boundary_mark_support)
    c_agree = _clean_count(cross_method_agreement)
    c_contra = _clean_count(contradiction)

    components = {
        IGT_SUPPORT: c_igt_sup,
        IGT_INDEPENDENCE: c_igt_ind,
        FORM_DIVERSITY: c_form_div,
        PROJECTION_SUPPORT: c_proj_sup,
        BOUNDARY_MARK_SUPPORT: c_bound_sup,
        CROSS_METHOD_AGREEMENT: c_agree,
    }
    penalties = {
        CONTRADICTION: c_contra,
        UNKNOWN_SEGMENT: 0.0,
        AMBIGUITY: 0.0,
    }

    # Promotion evaluation (§7.8)
    promotable = (
        c_igt_sup >= pol.min_igt_support
        and (c_igt_ind >= pol.min_igt_independence or c_form_div >= pol.min_form_diversity)
        and c_contra == 0.0
    )

    new_status = LifecycleStatus.SUPPORTED if promotable else LifecycleStatus.CANDIDATE

    # Compute overall score in [0.0, 1.0]
    if c_contra > 0.0:
        overall = 0.0
    else:
        support_term = (
            0.35 * min(1.0, c_igt_sup / 4.0)
            + 0.25 * min(1.0, c_igt_ind / 3.0)
            + 0.20 * min(1.0, c_form_div / 3.0)
            + 0.10 * min(1.0, c_proj_sup / 3.0)
            + 0.05 * min(1.0, c_bound_sup / 2.0)
            + 0.05 * min(1.0, c_agree / 2.0)
        )
        overall = max(0.75, min(1.0, support_term)) if promotable else min(0.74, support_term)
    overall = round(max(0.0, min(1.0, overall)), 4)

    breakdown = ScoreBreakdown(
        policy_version=pol.policy_version,
        overall=overall,
        components=components,
        penalties=penalties,
        independence_groups=sorted(axes),
    )
    return new_status, breakdown


def score_allomorph(
    *,
    evidence_items: Sequence[EvidenceItem] = (),
    igt_support: int | None = None,
    igt_independence: int | None = None,
    form_diversity: int | None = None,
    projection_support: int = 0,
    boundary_mark_support: int = 0,
    cross_method_agreement: int = 0,
    contradiction: int | None = None,
    independence_groups: Sequence[str] = (),
    current_status: LifecycleStatus = LifecycleStatus.CANDIDATE,
    policy: MorphScoringPolicy | None = None,
) -> tuple[LifecycleStatus, ScoreBreakdown]:
    """Score an allomorph under `morph-v1` policy (§7.8).

    Same criteria as Morpheme: igt_support >= 2 and (igt_independence >= 2 or form_diversity >= 2)
    and no contradiction.
    """
    return score_morpheme(
        evidence_items=evidence_items,
        igt_support=igt_support,
        igt_independence=igt_independence,
        form_diversity=form_diversity,
        projection_support=projection_support,
        boundary_mark_support=boundary_mark_support,
        cross_method_agreement=cross_method_agreement,
        contradiction=contradiction,
        independence_groups=independence_groups,
        current_status=current_status,
        policy=policy,
    )


def score_analysis(
    *,
    method: str,
    linked_morphemes: Sequence[Morpheme] = (),
    linked_morpheme_statuses: Sequence[LifecycleStatus] = (),
    segments: Sequence[MorphSegment] = (),
    evidence_items: Sequence[EvidenceItem] = (),
    igt_support: int | None = None,
    igt_independence: int | None = None,
    form_diversity: int | None = None,
    projection_support: int = 0,
    boundary_mark_support: int = 0,
    cross_method_agreement: int = 0,
    contradiction: int | None = None,
    unknown_segment: int | None = None,
    ambiguity: int = 0,
    distinct_signatures_on_token: int = 1,
    independence_groups: Sequence[str] = (),
    current_status: LifecycleStatus = LifecycleStatus.CANDIDATE,
    policy: MorphScoringPolicy | None = None,
) -> tuple[LifecycleStatus, ScoreBreakdown]:
    """Score a MorphAnalysis under `morph-v1` policy (§7.8).

    Promotion to `supported`:
      Method is `igt_assertion` (or on ADR-0019 allowlist),
      every linked morpheme is `supported` or `validated`,
      no unknown segment (`unknown_segment == 0`),
      no contradiction (`contradiction == 0`).
    Everything else stays `candidate`. `validated` is unreachable.
    """
    if current_status is LifecycleStatus.VALIDATED:
        raise InvalidTransition()

    pol = policy or DEFAULT_POLICY
    axes: set[str] = set(independence_groups)

    if evidence_items:
        contradicting = [i for i in evidence_items if i.polarity is EvidencePolarity.CONTRADICTS]
        for item in evidence_items:
            axis = _independence_axis(item)
            if axis:
                axes.add(axis)
        if contradiction is None:
            contradiction = len(contradicting)

    # Derive unknown_segment from segments if not passed explicitly
    if unknown_segment is None:
        unknown_segment = sum(1 for s in segments if s.morpheme_id is None) if segments else 0

    # Ambiguity is distinct signatures on the token - 1
    if distinct_signatures_on_token > 1 and ambiguity == 0:
        ambiguity = distinct_signatures_on_token - 1

    c_igt_sup = _clean_count(igt_support)
    c_igt_ind = _clean_count(igt_independence)
    c_form_div = _clean_count(form_diversity)
    c_proj_sup = _clean_count(projection_support)
    c_bound_sup = _clean_count(boundary_mark_support)
    c_agree = _clean_count(cross_method_agreement)
    c_contra = _clean_count(contradiction)
    c_unk_seg = _clean_count(unknown_segment)
    c_ambig = _clean_count(ambiguity)

    components = {
        IGT_SUPPORT: c_igt_sup,
        IGT_INDEPENDENCE: c_igt_ind,
        FORM_DIVERSITY: c_form_div,
        PROJECTION_SUPPORT: c_proj_sup,
        BOUNDARY_MARK_SUPPORT: c_bound_sup,
        CROSS_METHOD_AGREEMENT: c_agree,
    }
    penalties = {
        CONTRADICTION: c_contra,
        UNKNOWN_SEGMENT: c_unk_seg,
        AMBIGUITY: c_ambig,
    }

    # Method check: igt_assertion (with or without version) or in allowlist
    base_method = method.partition("@")[0].strip()
    method_permitted = base_method == "igt_assertion" or method in pol.method_allowlist

    # Morpheme status check: all linked morphemes must be supported or validated
    statuses: list[LifecycleStatus] = list(linked_morpheme_statuses)
    if linked_morphemes:
        statuses.extend(m.status for m in linked_morphemes)

    # An analysis with zero morphemes or unknown segments cannot promote
    morphemes_supported = len(statuses) > 0 and all(
        s in (LifecycleStatus.SUPPORTED, LifecycleStatus.VALIDATED) for s in statuses
    )

    promotable = method_permitted and morphemes_supported and c_unk_seg == 0.0 and c_contra == 0.0

    new_status = LifecycleStatus.SUPPORTED if promotable else LifecycleStatus.CANDIDATE

    # Overall score in [0.0, 1.0]
    if c_contra > 0.0 or base_method == "unsegmented":
        overall = 0.0
    elif promotable:
        score = (
            0.80
            + 0.10 * min(1.0, c_agree / 2.0)
            + 0.10 * min(1.0, c_bound_sup / 2.0)
            - 0.05 * c_ambig
        )
        overall = max(0.75, min(1.0, score))
    else:
        score = (
            0.40
            + 0.10 * min(1.0, c_igt_sup / 2.0)
            + 0.10 * min(1.0, c_agree / 2.0)
            - 0.20 * c_unk_seg
            - 0.10 * c_ambig
        )
        overall = max(0.0, min(0.74, score))

    overall = round(max(0.0, min(1.0, overall)), 4)

    breakdown = ScoreBreakdown(
        policy_version=pol.policy_version,
        overall=overall,
        components=components,
        penalties=penalties,
        independence_groups=sorted(axes),
    )
    return new_status, breakdown


__all__ = [
    "AMBIGUITY",
    "BOUNDARY_MARK_SUPPORT",
    "COMPONENTS",
    "CONTRADICTION",
    "CROSS_METHOD_AGREEMENT",
    "DEFAULT_POLICY",
    "FORM_DIVERSITY",
    "IGT_INDEPENDENCE",
    "IGT_SUPPORT",
    "MorphScoringPolicy",
    "PENALTIES",
    "POLICY_VERSION",
    "PROJECTION_SUPPORT",
    "UNKNOWN_SEGMENT",
    "score_allomorph",
    "score_analysis",
    "score_morpheme",
]
